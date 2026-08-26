"""Humo sobre los handlers: que respondan sin reventar con datos reales."""
from types import SimpleNamespace

import pytest

from app.bot.handlers import buffer as buffer_h
from app.bot.handlers import cards as cards_h
from app.bot.handlers import common as common_h
from app.bot.handlers import fixed as fixed_h
from app.bot.handlers import people as people_h
from app.bot.handlers import reports as reports_h
from app.models import ACCOUNT_CREDIT, Account, FixedExpense, RecurringIncome
from app.money import D


class FakeMessage:
    def __init__(self, text: str = "", user_id: int = 1):
        self.text = text
        self.from_user = SimpleNamespace(id=user_id)
        self.chat = SimpleNamespace(id=user_id)
        self.sent: list[str] = []
        self.documents: list = []

    async def answer(self, text, **kwargs):
        self.sent.append(text)
        return self

    async def answer_document(self, document, **kwargs):
        self.documents.append(document)
        return self

    async def edit_text(self, text, **kwargs):
        self.sent.append(text)
        return self

    async def delete(self):
        return True


class FakeCallback:
    def __init__(self, data: str, message: FakeMessage):
        self.data = data
        self.message = message
        self.from_user = SimpleNamespace(id=1)
        self.answers: list = []

    async def answer(self, text: str = "", **kwargs):
        self.answers.append(text)


@pytest.fixture
async def poblado(session):
    session.add(Account(name="Visa", type=ACCOUNT_CREDIT, cut_day=20, due_day=10,
                        credit_limit=D("2000")))
    session.add(FixedExpense(name="Arriendo", amount=D("400"), due_day=5,
                             start_period="2026-01"))
    session.add(RecurringIncome(name="Sueldo", amount=D("1500"), pay_day=30,
                                start_period="2026-01"))
    await session.flush()
    return session


async def test_start_y_ayuda(session):
    m = FakeMessage()
    await common_h.cmd_start(m, session)
    await common_h.cmd_help(m)
    assert len(m.sent) == 2


async def test_resumen_con_datos(poblado):
    m = FakeMessage()
    await reports_h.cmd_summary(m, poblado)
    assert "Te queda para gastar" in m.sent[0]


async def test_resumen_sin_datos(session):
    m = FakeMessage()
    await reports_h.cmd_summary(m, session)
    assert m.sent


async def test_tarjetas(poblado):
    m = FakeMessage()
    await cards_h.cmd_cards(m, poblado)
    assert "Visa" in m.sent[0]


async def test_tarjetas_sin_tarjetas(session):
    m = FakeMessage()
    await cards_h.cmd_cards(m, session)
    assert "/setup" in m.sent[0]


async def test_fijos(poblado):
    m = FakeMessage()
    await fixed_h.cmd_fixed(m, poblado)
    assert "Arriendo" in m.sent[0]


async def test_colchon_sin_configurar(session):
    m = FakeMessage()
    await buffer_h.cmd_buffer(m, session)
    assert "colchontotal" in m.sent[0]


async def test_colchon_configurado(session):
    m = FakeMessage("/colchontotal 500")
    await buffer_h.cmd_set_total(m, session)
    m2 = FakeMessage()
    await buffer_h.cmd_buffer(m2, session)
    assert "$500.00" in m2.sent[0]


async def test_deudas_vacias(session):
    m = FakeMessage()
    await people_h.cmd_debts(m, session)
    assert "Nadie te debe" in m.sent[0]


async def test_exportar_genera_csv(poblado):
    m = FakeMessage("/exportar")
    await reports_h.cmd_export(m, poblado)
    assert m.documents
    contenido = m.documents[0].data.decode("utf-8-sig")
    assert "Fecha;Tipo" in contenido
    assert "Arriendo" in contenido


async def test_pagar_tarjeta_parcial(poblado):
    m = FakeMessage("/pagar visa 100")
    await cards_h.cmd_pay(m, poblado)
    assert "Abono de $100.00" in m.sent[0]


async def test_pagar_tarjeta_inexistente(poblado):
    m = FakeMessage("/pagar mastercard 100")
    await cards_h.cmd_pay(m, poblado)
    assert "No encontré esa tarjeta" in m.sent[0]


async def test_corte_dice_en_que_mes_cae_lo_de_hoy(poblado):
    m = FakeMessage("/corte")
    await cards_h.cmd_cuts(m, poblado)
    assert "Visa" in m.sent[0]
    assert "entra al corte" in m.sent[0]


async def test_corte_sin_tarjetas(session):
    m = FakeMessage("/corte")
    await cards_h.cmd_cuts(m, session)
    assert "/nuevatarjeta" in m.sent[0]


async def test_detalle_del_corte_lista_los_movimientos(poblado):
    import datetime as dt

    from sqlalchemy import select

    from app.models import STATUS_DONE, Account, Transaction
    from app.services.cards import build_installments

    card = (
        await poblado.execute(select(Account).where(Account.name == "Visa"))
    ).scalar_one()
    tx = Transaction(
        kind="expense", status=STATUS_DONE, date=dt.date(2026, 8, 4),
        period="2026-08", amount=D("60.00"), description="Supermaxi",
        account_id=card.id,
    )
    poblado.add(tx)
    await poblado.flush()
    for inst in build_installments(tx, card, 1):
        poblado.add(inst)
    await poblado.flush()

    m = FakeMessage()
    await cards_h.cb_statement_detail(FakeCallback(f"c:det:{card.id}:2026-08", m), poblado)
    assert "Supermaxi" in m.sent[0]
    assert "$60.00" in m.sent[0]
    assert "Cierra el" in m.sent[0]


async def test_detalle_de_corte_vacio(poblado):
    from sqlalchemy import select

    from app.models import Account

    card = (
        await poblado.execute(select(Account).where(Account.name == "Visa"))
    ).scalar_one()
    m = FakeMessage()
    await cards_h.cb_statement_detail(FakeCallback(f"c:det:{card.id}:2027-01", m), poblado)
    assert "No hay movimientos" in m.sent[0]
