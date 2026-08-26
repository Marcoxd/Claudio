"""El flujo completo de /conciliar, con el estado de cuenta simulado."""
import datetime as dt
from types import SimpleNamespace

import pytest

from app.bot.handlers import reconcile as R
from app.models import ACCOUNT_CREDIT, STATUS_DONE, Account, CardPayment, Transaction
from app.money import D
from app.services.ai import ParsedStatement, StatementLine
from app.services.cards import build_installments


class FakeMessage:
    def __init__(self, user_id: int = 1):
        self.from_user = SimpleNamespace(id=user_id)
        self.chat = SimpleNamespace(id=user_id)
        self.document = SimpleNamespace(
            file_id="x", mime_type="application/pdf", file_size=1000
        )
        self.photo = None
        self.sent: list[str] = []
        self.markups: list = []

    async def answer(self, text, reply_markup=None, **kw):
        self.sent.append(text)
        self.markups.append(reply_markup)
        return self

    async def edit_text(self, text, **kw):
        self.sent.append(text)
        return self

    async def edit_reply_markup(self, **kw):
        return self

    async def delete(self):
        return True


class FakeCallback:
    def __init__(self, data, message):
        self.data = data
        self.message = message
        self.from_user = SimpleNamespace(id=1)

    async def answer(self, *a, **k):
        pass


class FakeState:
    def __init__(self):
        self.state = None

    async def set_state(self, s):
        self.state = s

    async def clear(self):
        self.state = None


class FakeBot:
    async def download(self, file_id):
        import io

        return io.BytesIO(b"pdf")


ESTADO = ParsedStatement(
    card_name="Pacifico",
    period_start="2026-07-25",
    period_end="2026-08-24",
    due_date="2026-09-08",
    total_due=2422.91,
    minimum_due=642.38,
    lines=[
        StatementLine(date="2026-08-02", description="COMERCIAL KYWI SA", amount=13.83),
        StatementLine(date="2026-08-02", description="SUPER SANTAMARIA SANGO", amount=154.75),
        StatementLine(date="2026-08-01", description="MARCO FERNANDEZ", amount=40.25),
        StatementLine(date="2026-08-04", description="SU PAGO PAGO DIRECTO BDP",
                      amount=490.74, kind="pago"),
        StatementLine(date="2026-07-04", description="PAT PRIMO TIENDA CCI",
                      amount=30.36, kind="cuota", installment="02/06"),
    ],
)


@pytest.fixture
async def escenario(session, monkeypatch):
    tarjeta = Account(name="Pacifico", type=ACCOUNT_CREDIT, cut_day=20, due_day=10)
    session.add(tarjeta)
    await session.flush()

    # lo que ya tenía anotado
    session.add(
        Transaction(kind="expense", status=STATUS_DONE, date=dt.date(2026, 8, 2),
                    period="2026-08", amount=D("13.83"), description="kiwy",
                    account_id=tarjeta.id)
    )
    session.add(
        Transaction(kind="expense", status=STATUS_DONE, date=dt.date(2026, 8, 2),
                    period="2026-08", amount=D("154.73"), description="Santa Maria",
                    account_id=tarjeta.id)
    )
    # un diferido que sí cae en este corte
    patprimo = Transaction(
        kind="expense", status=STATUS_DONE, date=dt.date(2026, 7, 4),
        period="2026-07", amount=D("182.16"), description="Patprimo",
        account_id=tarjeta.id, installments_total=6,
    )
    session.add(patprimo)
    await session.flush()
    for cuota in build_installments(patprimo, tarjeta, 6):
        session.add(cuota)
    await session.flush()

    async def fake_parse(datos, mime, ctx):
        return ESTADO

    monkeypatch.setattr(R.ai, "parse_statement", fake_parse)
    return tarjeta


async def test_conciliar_clasifica_los_movimientos(session, escenario):
    m = FakeMessage()
    await R.on_statement(m, FakeState(), session, FakeBot())
    texto = m.sent[-1]

    assert "Pacifico" in texto
    assert "Revisé 4 movimientos" in texto        # el pago no cuenta como consumo
    assert "MARCO FERNANDEZ" in texto             # el que falta
    assert "Santa Maria" in texto                 # el que difiere por 2 centavos
    assert "corte 24 y pago 8" in texto.lower() or "Fijar corte 24" in str(m.markups[-1])


async def test_agregar_los_faltantes_los_crea_con_su_cuota(session, escenario):
    from sqlalchemy import select

    from app.models import Draft, Installment

    m = FakeMessage()
    await R.on_statement(m, FakeState(), session, FakeBot())
    draft = (await session.execute(select(Draft))).scalars().first()

    await R.cb_add(FakeCallback(f"k:add:{draft.id}", m), session)

    nuevo = (
        await session.execute(
            select(Transaction).where(Transaction.description == "MARCO FERNANDEZ")
        )
    ).scalar_one()
    assert nuevo.amount == D("40.25")
    assert nuevo.account_id == escenario.id
    cuotas = (
        await session.execute(
            select(Installment).where(Installment.transaction_id == nuevo.id)
        )
    ).scalars().all()
    assert len(cuotas) == 1


async def test_corregir_montos_deja_el_del_banco(session, escenario):
    from sqlalchemy import select

    from app.models import Draft

    m = FakeMessage()
    await R.on_statement(m, FakeState(), session, FakeBot())
    draft = (await session.execute(select(Draft))).scalars().first()

    await R.cb_fix(FakeCallback(f"k:fix:{draft.id}", m), session)
    corregido = (
        await session.execute(
            select(Transaction).where(Transaction.description == "Santa Maria")
        )
    ).scalar_one()
    assert corregido.amount == D("154.75")


async def test_fijar_las_fechas_del_estado(session, escenario):
    from sqlalchemy import select

    from app.models import Draft

    m = FakeMessage()
    await R.on_statement(m, FakeState(), session, FakeBot())
    draft = (await session.execute(select(Draft))).scalars().first()

    await R.cb_dates(FakeCallback(f"k:dates:{draft.id}", m), session)
    assert escenario.cut_day == 24
    assert escenario.due_day == 8


async def test_registrar_el_pago_del_periodo(session, escenario):
    from sqlalchemy import select

    from app.models import Draft

    m = FakeMessage()
    await R.on_statement(m, FakeState(), session, FakeBot())
    draft = (await session.execute(select(Draft))).scalars().first()

    await R.cb_pay(FakeCallback(f"k:pay:{draft.id}", m), session)
    pagos = (await session.execute(select(CardPayment))).scalars().all()
    assert len(pagos) == 1
    assert pagos[0].amount == D("490.74")
    assert pagos[0].statement_period == "2026-08"
