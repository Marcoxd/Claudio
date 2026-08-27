import datetime as dt

from app.models import SPLIT_EQUAL, SPLIT_ITEMS, Person, ReceiptItem, Transaction
from app.money import D, total
from app.services.splits import apply_split, balances, settle_person


async def _people(session, *names):
    people = [Person(name=n) for n in names]
    session.add_all(people)
    await session.flush()
    return people


def _tx(amount, items=None):
    tx = Transaction(
        date=dt.date(2026, 8, 10), period="2026-08", amount=D(amount), description="Cena"
    )
    for name, value, kind in items or []:
        tx.items.append(ReceiptItem(name=name, total=D(value), kind=kind, quantity=D(1)))
    return tx


async def test_partes_iguales_incluyendome(session):
    ana, luis = await _people(session, "Ana", "Luis")
    tx = _tx("96.00")
    session.add(tx)
    apply_split(tx, SPLIT_EQUAL, person_ids=[ana.id, luis.id])
    assert tx.my_share == D("32.00")
    assert total(s.amount for s in tx.split.shares) == D("96.00")


async def test_partes_iguales_sin_incluirme(session):
    ana, = await _people(session, "Ana")
    tx = _tx("50.00")
    session.add(tx)
    apply_split(tx, SPLIT_EQUAL, person_ids=[ana.id], include_me=False)
    assert tx.my_share == D("0.00")
    assert tx.split.shares[0].amount == D("50.00")


async def test_division_por_items_prorratea_iva_y_propina(session):
    ana, = await _people(session, "Ana")
    tx = _tx(
        "46.00",
        items=[
            ("Lomo", "20.00", "item"),
            ("Ensalada", "20.00", "item"),
            ("IVA", "6.00", "tax"),
        ],
    )
    session.add(tx)
    await session.flush()
    lomo, ensalada = [i for i in tx.items if i.kind == "item"]

    apply_split(
        tx, SPLIT_ITEMS,
        assignment={lomo.id: [None], ensalada.id: [ana.id]},
    )
    shares = {s.person_id: s.amount for s in tx.split.shares}
    assert shares[None] == D("23.00")
    assert shares[ana.id] == D("23.00")
    assert total(shares.values()) == D("46.00")


async def test_item_compartido_entre_dos(session):
    ana, = await _people(session, "Ana")
    tx = _tx("30.00", items=[("Pizza", "30.00", "item")])
    session.add(tx)
    await session.flush()
    pizza = tx.items[0]

    apply_split(tx, SPLIT_ITEMS, assignment={pizza.id: [None, ana.id]})
    assert tx.my_share == D("15.00")


async def test_items_sin_asignar_no_se_cobran_a_nadie_pero_cuadra_el_total(session):
    ana, = await _people(session, "Ana")
    tx = _tx("60.00", items=[("A", "30.00", "item"), ("B", "30.00", "item")])
    session.add(tx)
    await session.flush()
    a = tx.items[0]

    apply_split(tx, SPLIT_ITEMS, assignment={a.id: [ana.id]})
    # el ítem B no asignado queda para mí vía prorrateo del faltante
    assert total(s.amount for s in tx.split.shares) == D("60.00")


async def test_saldar_deuda_completa(session):
    ana, = await _people(session, "Ana")
    tx = _tx("100.00")
    session.add(tx)
    apply_split(tx, SPLIT_EQUAL, person_ids=[ana.id])
    await session.flush()

    assert (await balances(session))[0].owes_me == D("50.00")
    settled = await settle_person(session, ana.id)
    assert settled == D("50.00")
    assert await balances(session) == []


async def test_abono_parcial_deja_el_resto_pendiente(session):
    ana, = await _people(session, "Ana")
    tx = _tx("100.00")
    session.add(tx)
    apply_split(tx, SPLIT_EQUAL, person_ids=[ana.id])
    await session.flush()

    await settle_person(session, ana.id, D("20.00"))
    rest = await balances(session)
    assert rest[0].owes_me == D("30.00")


async def test_gasto_que_no_es_mio_no_me_cuenta(session):
    """Lo pagué yo, pero es de ellos: mi parte es cero y me deben todo."""
    ana, luis = await _people(session, "Ana", "Luis")
    tx = _tx("60.00")
    session.add(tx)
    apply_split(tx, SPLIT_EQUAL, person_ids=[ana.id, luis.id], include_me=False)
    await session.flush()

    assert tx.my_share == D("0.00")
    assert tx.effective_amount() == D("0.00")
    assert total(b.owes_me for b in await balances(session)) == D("60.00")


async def test_gasto_de_una_sola_persona_ajena(session):
    ana, = await _people(session, "Ana")
    tx = _tx("29.14")
    session.add(tx)
    apply_split(tx, SPLIT_EQUAL, person_ids=[ana.id], include_me=False)
    await session.flush()
    assert tx.my_share == D("0.00")
    assert (await balances(session))[0].owes_me == D("29.14")
