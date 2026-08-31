import datetime as dt

from app.models import KIND_EXPENSE, KIND_INCOME, Transaction
from app.money import D
from app.web.api import export_transactions


async def test_export_transactions(session):
    tx1 = Transaction(
        kind=KIND_EXPENSE,
        date=dt.date(2026, 8, 15),
        amount=D("15.50"),
        description="Almuerzo",
        period="2026-08",
    )
    tx2 = Transaction(
        kind=KIND_INCOME,
        date=dt.date(2026, 8, 30),
        amount=D("1200.00"),
        description="Sueldo",
        period="2026-08",
    )
    tx3 = Transaction(
        kind=KIND_EXPENSE,
        date=dt.date(2026, 7, 10),
        amount=D("50.00"),
        description="Supermercado",
        period="2026-07",
    )
    session.add_all([tx1, tx2, tx3])
    await session.flush()

    # 1. Exportar por mes
    res_mes = await export_transactions(tipo="mes", period="2026-08", token="test", session=session)
    content_mes = res_mes.body.decode("utf-8-sig")
    assert "Almuerzo" in content_mes
    assert "Sueldo" in content_mes
    assert "Supermercado" not in content_mes

    # 2. Exportar por día
    res_dia = await export_transactions(tipo="dia", date="2026-08-15", token="test", session=session)
    content_dia = res_dia.body.decode("utf-8-sig")
    assert "Almuerzo" in content_dia
    assert "Sueldo" not in content_dia

    # 3. Exportar por año
    res_ano = await export_transactions(tipo="ano", year=2026, token="test", session=session)
    content_ano = res_ano.body.decode("utf-8-sig")
    assert "Almuerzo" in content_ano
    assert "Sueldo" in content_ano
    assert "Supermercado" in content_ano

    # 4. Exportar todo
    res_todo = await export_transactions(tipo="todo", token="test", session=session)
    content_todo = res_todo.body.decode("utf-8-sig")
    assert "Almuerzo" in content_todo
    assert "Supermercado" in content_todo
