"""Flujo completo sin IA: texto → borrador → transacción guardada."""
import datetime as dt

from sqlalchemy import select

from app.models import ACCOUNT_CREDIT, Account, Installment, Person
from app.money import D, total
from app.services.capture import build_context, commit_draft, draft_from_parsed
from app.services.fallback import parse_text_rules
from app.services.periods import current_period, today


async def _pipeline(session, text: str) -> dict:
    ctx = await build_context(session)
    parsed = parse_text_rules(text, ctx)
    return await draft_from_parsed(session, parsed, source="text", raw_text=text)


async def test_gasto_simple_de_texto(session):
    payload = await _pipeline(session, "almuerzo 12.50")
    tx = await commit_draft(session, payload)

    assert tx.amount == D("12.50")
    assert tx.kind == "expense"
    from app.models import Category

    assert (await session.get(Category, tx.category_id)).name == "Comida"
    assert tx.period == current_period()


async def test_ingreso_reconocido_como_tal(session):
    payload = await _pipeline(session, "me pagaron 450 de asesoria")
    tx = await commit_draft(session, payload)
    assert tx.kind == "income"
    assert tx.amount == D("450.00")


async def test_compra_con_tarjeta_genera_cuota_en_el_corte(session):
    session.add(Account(name="Visa", type=ACCOUNT_CREDIT, cut_day=20, due_day=10))
    await session.flush()

    payload = await _pipeline(session, "gasolina 25 con la visa")
    payload["date"] = dt.date(2026, 8, 15).isoformat()
    await commit_draft(session, payload)

    cuotas = (await session.execute(select(Installment))).scalars().all()
    assert len(cuotas) == 1
    assert cuotas[0].statement_period == "2026-08"
    assert cuotas[0].due_date == dt.date(2026, 9, 10)


async def test_diferido_desde_texto(session):
    session.add(Account(name="Diners", type=ACCOUNT_CREDIT, cut_day=5, due_day=25))
    await session.flush()

    payload = await _pipeline(session, "tv 900 diferido a 12 meses con diners")
    payload["date"] = dt.date(2026, 8, 3).isoformat()
    await commit_draft(session, payload)

    cuotas = (await session.execute(select(Installment))).scalars().all()
    assert len(cuotas) == 12
    assert total(c.amount for c in cuotas) == D("900.00")
    assert cuotas[0].statement_period == "2026-08"


async def test_gasto_con_amigos_crea_personas_y_divide(session):
    payload = await _pipeline(session, "cena 96 con Ana y Luis")
    tx = await commit_draft(session, payload)

    assert tx.my_share == D("32.00")
    people = (await session.execute(select(Person))).scalars().all()
    assert {p.name for p in people} == {"Ana", "Luis"}


async def test_uso_del_colchon_registra_movimiento(session):
    from app.services import buffer as buffer_service

    await buffer_service.set_total(session, D("500"))
    payload = await _pipeline(session, "saque 100 del colchon")
    await commit_draft(session, payload)

    state = await buffer_service.state(session)
    assert state.debt == D("100.00")
    assert state.available == D("400.00")


async def test_recibo_con_items_dividido_por_producto(session):
    from app.services.ai import ParsedCapture, ParsedItem

    parsed = ParsedCapture(
        kind="expense", amount=46.0, date=today().isoformat(),
        description="Cena", merchant="Doña Elsa", category="Comida",
        people=["Ana"],
        items=[
            ParsedItem(name="Lomo", total=20.0),
            ParsedItem(name="Ensalada", total=20.0),
            ParsedItem(name="IVA", total=6.0, kind="tax"),
        ],
    )
    payload = await draft_from_parsed(session, parsed, source="photo")
    ana_id = payload["people_ids"][0]
    payload["split_mode"] = ""
    payload["assign"] = {"0": ["me"], "1": [ana_id]}

    tx = await commit_draft(session, payload)
    shares = {s.person_id: s.amount for s in tx.split.shares}
    assert shares[None] == D("23.00")
    assert shares[ana_id] == D("23.00")
    assert len(tx.items) == 3
