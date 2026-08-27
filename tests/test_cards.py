import datetime as dt

from app.models import ACCOUNT_CREDIT, Account, Transaction
from app.money import D, total
from app.services.cards import (
    build_installments,
    due_date_for,
    statement_period_for,
)
from app.services.reports import statement_due_in


def card(cut=20, due=10):
    return Account(id=1, name="Visa", type=ACCOUNT_CREDIT, cut_day=cut, due_day=due)


def test_compra_antes_del_corte_entra_en_el_mes():
    assert statement_period_for(dt.date(2026, 8, 15), 20) == "2026-08"


def test_compra_despues_del_corte_pasa_al_siguiente():
    assert statement_period_for(dt.date(2026, 8, 21), 20) == "2026-09"


def test_compra_el_dia_del_corte_entra_en_ese_corte():
    assert statement_period_for(dt.date(2026, 8, 20), 20) == "2026-08"


def test_vencimiento_cuando_el_pago_es_despues_del_corte():
    # corte 5, pago 25 -> mismo mes
    assert due_date_for("2026-08", 5, 25) == dt.date(2026, 8, 25)


def test_vencimiento_cuando_el_pago_cae_el_mes_siguiente():
    # corte 20, pago 10 -> mes siguiente
    assert due_date_for("2026-08", 20, 10) == dt.date(2026, 9, 10)


def test_dia_de_pago_31_en_febrero_se_ajusta():
    assert due_date_for("2026-02", 5, 31) == dt.date(2026, 2, 28)


def test_diferido_reparte_cuotas_mes_a_mes_sin_perder_centavos():
    tx = Transaction(date=dt.date(2026, 8, 10), amount=D("1000.00"), period="2026-08")
    cuotas = build_installments(tx, card(), 12)

    assert len(cuotas) == 12
    assert total(c.amount for c in cuotas) == D("1000.00")
    assert cuotas[0].statement_period == "2026-08"
    assert cuotas[11].statement_period == "2027-07"
    assert cuotas[0].due_date == dt.date(2026, 9, 10)


def test_diferido_que_empieza_despues_del_corte():
    tx = Transaction(date=dt.date(2026, 8, 25), amount=D("300.00"), period="2026-08")
    cuotas = build_installments(tx, card(), 3)
    assert [c.statement_period for c in cuotas] == ["2026-09", "2026-10", "2026-11"]


def test_compra_corriente_genera_una_sola_cuota():
    tx = Transaction(date=dt.date(2026, 8, 3), amount=D("45.30"), period="2026-08")
    cuotas = build_installments(tx, card(), 1)
    assert len(cuotas) == 1 and cuotas[0].amount == D("45.30")


def test_que_corte_se_paga_este_mes():
    # corte 20, pago 10 -> en agosto pago el corte de julio
    assert statement_due_in("2026-08", 20, 10) == "2026-07"
    # corte 5, pago 25 -> en agosto pago el corte de agosto
    assert statement_due_in("2026-08", 5, 25) == "2026-08"


def test_ventana_del_corte():
    from app.services.cards import statement_window

    # corte el 20: el estado de agosto cubre del 21 de julio al 20 de agosto
    assert statement_window("2026-08", 20) == (dt.date(2026, 7, 21), dt.date(2026, 8, 20))


def test_ventana_del_corte_en_marzo_tras_febrero():
    from app.services.cards import statement_window

    start, end = statement_window("2026-03", 31)
    assert start == dt.date(2026, 3, 1)   # febrero cerró el 28
    assert end == dt.date(2026, 3, 31)


def test_compra_de_hoy_dice_a_que_corte_va():
    from app.money import ZERO
    from app.services.cards import place_purchase

    p = place_purchase(card(cut=20, due=10), dt.date(2026, 8, 26), ZERO, 1)
    assert p.period == "2026-09"
    assert p.cut_date == dt.date(2026, 9, 20)
    assert p.due_date == dt.date(2026, 10, 10)
    assert not p.is_deferred


def test_diferido_dice_desde_y_hasta_que_corte():
    from app.services.cards import place_purchase

    p = place_purchase(card(cut=20, due=10), dt.date(2026, 8, 26), D("1200"), 12)
    assert p.period == "2026-09"
    assert p.last_period == "2027-08"
    assert p.last_due_date == dt.date(2027, 9, 10)
    assert p.installment_amount == D("100.00")
    assert p.is_deferred


def test_compra_con_debito_no_tiene_corte():
    from app.models import ACCOUNT_DEBIT
    from app.services.cards import place_purchase

    debito = Account(id=2, name="Débito", type=ACCOUNT_DEBIT)
    assert place_purchase(debito, dt.date(2026, 8, 26), D("10"), 1) is None


async def test_saldo_pendiente_de_un_diferido(session):
    from app.models import STATUS_DONE
    from app.services.cards import deferred_purchases

    card = Account(name="Pacífico", type=ACCOUNT_CREDIT, cut_day=20, due_day=10)
    session.add(card)
    await session.flush()

    tx = Transaction(
        kind="expense", status=STATUS_DONE, date=dt.date(2026, 6, 10),
        period="2026-06", amount=D("182.16"), description="Patprimo",
        account_id=card.id, installments_total=6,
    )
    session.add(tx)
    await session.flush()
    for inst in build_installments(tx, card, 6):
        session.add(inst)
    await session.flush()

    # en agosto ya cerraron los cortes de junio, julio y agosto: 3 de 6
    compras = await deferred_purchases(session, period="2026-08")
    assert len(compras) == 1
    compra = compras[0]
    assert compra.count == 6
    assert compra.paid == 3
    assert compra.remaining == 3
    assert compra.installment == D("30.36")
    assert compra.remaining_amount == D("91.08")
    assert compra.next_period == "2026-09"


async def test_diferido_terminado_no_aparece(session):
    from app.models import STATUS_DONE
    from app.services.cards import deferred_purchases

    card = Account(name="Titanium", type=ACCOUNT_CREDIT, cut_day=5, due_day=25)
    session.add(card)
    await session.flush()
    tx = Transaction(
        kind="expense", status=STATUS_DONE, date=dt.date(2026, 1, 10),
        period="2026-01", amount=D("300"), description="Llantas",
        account_id=card.id, installments_total=3,
    )
    session.add(tx)
    await session.flush()
    for inst in build_installments(tx, card, 3):
        session.add(inst)
    await session.flush()

    assert await deferred_purchases(session, period="2026-08") == []


async def test_compra_corriente_no_cuenta_como_diferido(session):
    from app.models import STATUS_DONE
    from app.services.cards import deferred_purchases

    card = Account(name="Visa", type=ACCOUNT_CREDIT, cut_day=20, due_day=10)
    session.add(card)
    await session.flush()
    tx = Transaction(
        kind="expense", status=STATUS_DONE, date=dt.date(2026, 8, 10),
        period="2026-08", amount=D("40"), description="Gasolina",
        account_id=card.id,
    )
    session.add(tx)
    await session.flush()
    for inst in build_installments(tx, card, 1):
        session.add(inst)
    await session.flush()
    assert await deferred_purchases(session, period="2026-08") == []


async def test_tarjeta_sin_saldo_no_dice_que_vencio(session):
    """Un corte en cero no está vencido aunque su fecha ya pasó."""
    from app.services.cards import statement

    card = Account(name="Sin uso", type=ACCOUNT_CREDIT, cut_day=20, due_day=10)
    session.add(card)
    await session.flush()
    resumen = await statement(session, card, "2020-01")
    assert resumen.to_pay == D("0.00")
    assert resumen.is_overdue is False
    assert resumen.days_left < 0


def test_ventana_usa_el_corte_por_defecto_si_falta():
    from app.services.cards import cut_day_of, statement_window

    sin_fechas = Account(id=9, name="Nueva", type=ACCOUNT_CREDIT)
    start, end = statement_window("2026-08", cut_day_of(sin_fechas))
    assert end.day == 20 and start.day == 21


# Verificado contra un estado de cuenta PacifiCard real (corte 24, pago 8):
# "Período de corte desde 25/JUL/2026 hasta 24/AGO/2026,
#  fecha máxima de pago sin recargos 08/SEP/2026".
PACIFICARD_CORTE, PACIFICARD_PAGO = 24, 8


def test_pacificard_ventana_y_vencimiento_reales():
    from app.services.cards import statement_window

    assert statement_window("2026-08", PACIFICARD_CORTE) == (
        dt.date(2026, 7, 25),
        dt.date(2026, 8, 24),
    )
    assert due_date_for("2026-08", PACIFICARD_CORTE, PACIFICARD_PAGO) == dt.date(2026, 9, 8)


def test_pacificard_asigna_cada_consumo_a_su_corte():
    """Fechas tomadas de los movimientos del estado de cuenta."""
    en_el_corte_de_agosto = [
        dt.date(2026, 7, 26),   # el consumo más viejo del período
        dt.date(2026, 7, 30),
        dt.date(2026, 7, 31),
        dt.date(2026, 8, 1),
        dt.date(2026, 8, 17),
        dt.date(2026, 8, 24),   # el mismo día del corte entra
    ]
    for fecha in en_el_corte_de_agosto:
        assert statement_period_for(fecha, PACIFICARD_CORTE) == "2026-08"

    # un día después del corte ya es del mes siguiente
    assert statement_period_for(dt.date(2026, 8, 25), PACIFICARD_CORTE) == "2026-09"
    # y el día del corte anterior pertenece al corte anterior
    assert statement_period_for(dt.date(2026, 7, 24), PACIFICARD_CORTE) == "2026-07"
