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
