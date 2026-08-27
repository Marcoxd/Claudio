import datetime as dt

from app.models import (
    ACCOUNT_CREDIT,
    STATUS_DONE,
    Account,
    FixedExpense,
    RecurringIncome,
    Transaction,
)
from app.money import D
from app.services import buffer as buffer_service
from app.services.cards import build_installments
from app.services.fixed import ensure_period_materialized, pending_this_month
from app.services.reports import month_report

PERIOD = "2026-08"


async def _base(session):
    session.add(RecurringIncome(name="Sueldo", amount=D("1500"), pay_day=30, start_period="2026-01"))
    session.add(FixedExpense(name="Arriendo", amount=D("400"), due_day=5, start_period="2026-01"))
    session.add(FixedExpense(name="Internet", amount=D("35"), due_day=12, start_period="2026-01"))
    await session.flush()


async def test_materializacion_es_idempotente(session):
    await _base(session)
    await ensure_period_materialized(session, PERIOD)
    await ensure_period_materialized(session, PERIOD)
    pending = await pending_this_month(session, PERIOD)
    assert len(pending) == 2


async def test_fijo_fuera_de_su_vigencia_no_se_materializa(session):
    session.add(
        FixedExpense(name="Curso", amount=D("100"), due_day=1,
                     start_period="2026-01", end_period="2026-06")
    )
    await session.flush()
    await ensure_period_materialized(session, PERIOD)
    assert await pending_this_month(session, PERIOD) == []


async def test_disponible_descuenta_fijos_tarjetas_y_variables(session):
    await _base(session)
    card = Account(name="Visa", type=ACCOUNT_CREDIT, cut_day=20, due_day=10)
    session.add(card)
    await session.flush()

    # compra de julio que se paga en agosto (corte 20/07, vence 10/08)
    compra = Transaction(
        kind="expense", status=STATUS_DONE, date=dt.date(2026, 7, 15),
        period="2026-07", amount=D("200"), description="TV", account_id=card.id,
    )
    session.add(compra)
    await session.flush()
    for inst in build_installments(compra, card, 1):
        session.add(inst)

    # gasto variable en efectivo de agosto
    session.add(
        Transaction(kind="expense", status=STATUS_DONE, date=dt.date(2026, 8, 3),
                    period=PERIOD, amount=D("60"), description="Mercado")
    )
    await session.flush()

    r = await month_report(session, PERIOD)
    assert r.income_total == D("1500")
    assert r.fixed_total == D("435")
    assert r.cards_due == D("200")
    assert r.cash_variable == D("60")
    assert r.available_to_spend == D("805")


async def test_gasto_compartido_solo_cuenta_mi_parte(session):
    from app.models import SPLIT_EQUAL, Person
    from app.services.splits import apply_split

    ana = Person(name="Ana")
    session.add(ana)
    tx = Transaction(kind="expense", status=STATUS_DONE, date=dt.date(2026, 8, 4),
                     period=PERIOD, amount=D("80"), description="Cena")
    session.add(tx)
    await session.flush()
    apply_split(tx, SPLIT_EQUAL, person_ids=[ana.id])
    await session.flush()

    r = await month_report(session, PERIOD)
    assert r.cash_variable == D("40")
    assert r.others_owe_me == D("40")


async def test_colchon_no_cuenta_como_dinero_propio(session):
    await buffer_service.set_total(session, D("500"))
    await buffer_service.use(session, D("120"), note="Emergencia")
    await buffer_service.repay(session, D("20"))

    state = await buffer_service.state(session)
    assert state.total == D("500")
    assert state.debt == D("100")
    assert state.available == D("400")

    r = await month_report(session, PERIOD)
    assert r.income_total == D("0")   # el colchón nunca es ingreso


async def test_el_numero_grande_y_el_flujo_usan_la_misma_definicion(session):
    """`cash_out` y `available_to_spend` deben cuadrar contra el ingreso."""
    await _base(session)
    card = Account(name="Visa", type=ACCOUNT_CREDIT, cut_day=20, due_day=10)
    session.add(card)
    await session.flush()

    # compra diferida de agosto: cae en cortes de agosto en adelante
    compra = Transaction(
        kind="expense", status=STATUS_DONE, date=dt.date(2026, 8, 5),
        period=PERIOD, amount=D("1200"), description="TV", account_id=card.id,
        installments_total=12,
    )
    session.add(compra)
    await session.flush()
    for inst in build_installments(compra, card, 12):
        session.add(inst)
    await session.flush()

    r = await month_report(session, PERIOD)
    # comprado incluye el televisor completo; lo que sale, solo lo que exige el corte
    assert r.purchased == D("1635")          # 435 de fijos + 1200 del televisor
    assert r.cash_out == D("435")            # el corte de agosto se paga en septiembre
    assert r.income_total - r.cash_out == r.available_to_spend
    assert r.net == r.income_total - r.cash_out
