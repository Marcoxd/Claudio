#!/usr/bin/env python3
"""Carga datos de ejemplo para ver el panel funcionando (o hacer una demo de venta).

Uso:  python scripts/demo.py [--reset]
"""
from __future__ import annotations

import asyncio
import datetime as dt
import random
import sys

from sqlalchemy import select

from app.db import SessionLocal, engine, init_db
from app.models import (
    ACCOUNT_CREDIT,
    ACCOUNT_DEBIT,
    KIND_EXPENSE,
    KIND_INCOME,
    SPLIT_EQUAL,
    STATUS_DONE,
    Account,
    Base,
    Category,
    FixedExpense,
    Person,
    ReceiptItem,
    RecurringIncome,
    Transaction,
)
from app.money import D
from app.services import buffer as buffer_service
from app.services.cards import build_installments
from app.services.fixed import ensure_period_materialized, mark_paid
from app.services.periods import add_months, current_period, period_of, today
from app.services.splits import apply_split

VARIABLES = [
    ("Almuerzo", "Comida", 8, 18), ("Supermaxi", "Supermercado", 35, 120),
    ("Gasolina", "Combustible", 20, 45), ("Uber", "Transporte", 3, 12),
    ("Farmacia", "Salud", 6, 40), ("Cine", "Entretenimiento", 9, 25),
    ("Café", "Comida", 2, 7), ("Netflix", "Suscripciones", 12, 12),
]


async def main(reset: bool = False) -> None:
    if reset:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
    await init_db()

    async with SessionLocal() as s:
        cats = {c.name: c for c in (await s.execute(select(Category))).scalars().all()}
        if (await s.execute(select(Account).where(Account.type == ACCOUNT_CREDIT))).first():
            print("Ya hay datos. Usa --reset para empezar de cero.")
            return

        debito = Account(name="Débito Pichincha", type=ACCOUNT_DEBIT)
        visa = Account(name="Visa Pichincha", type=ACCOUNT_CREDIT, cut_day=20, due_day=10,
                       credit_limit=D("3000"))
        diners = Account(name="Diners", type=ACCOUNT_CREDIT, cut_day=5, due_day=25,
                         credit_limit=D("1500"))
        ana, luis, sofi = Person(name="Ana"), Person(name="Luis"), Person(name="Sofía")
        s.add_all([debito, visa, diners, ana, luis, sofi])
        await s.flush()

        s.add(RecurringIncome(name="Sueldo", amount=D("1450"), pay_day=30,
                              account_id=debito.id, start_period="2026-01"))
        for name, amount, day, cat in [
            ("Arriendo", "420", 5, "Vivienda"),
            ("Internet Netlife", "32", 8, "Internet y teléfono"),
            ("Plan celular", "28", 12, "Internet y teléfono"),
            ("Cuota del carro", "265", 15, "Transporte"),
            ("Préstamo a Marcelo", "150", 20, "Préstamos"),
        ]:
            s.add(FixedExpense(name=name, amount=D(amount), due_day=day,
                               category_id=cats[cat].id, start_period="2026-01"))
        await s.flush()

        await buffer_service.set_total(s, D("600"))
        await buffer_service.use(s, D("180"), note="Imprevisto del carro",
                                 date=today() - dt.timedelta(days=20))
        await buffer_service.repay(s, D("80"), date=today() - dt.timedelta(days=5))

        random.seed(7)
        period = current_period()

        # Diferido a 12 meses hecho hace dos meses
        tv = Transaction(kind=KIND_EXPENSE, status=STATUS_DONE,
                         date=today().replace(day=10) - dt.timedelta(days=60),
                         amount=D("1080"), description="Televisor 55\"",
                         merchant="Artefacta", category_id=cats["Otros"].id,
                         account_id=visa.id, installments_total=12, source="photo")
        tv.period = period_of(tv.date)
        s.add(tv)
        await s.flush()
        for inst in build_installments(tv, visa, 12):
            s.add(inst)

        for months_back in (2, 1, 0):
            p = add_months(period, -months_back)
            await ensure_period_materialized(s, p)
            year, month = int(p[:4]), int(p[5:])
            for tx in (await s.execute(
                select(Transaction).where(Transaction.period == p,
                                          Transaction.fixed_expense_id.is_not(None))
            )).scalars().all():
                if months_back > 0 or tx.date <= today():
                    await mark_paid(s, tx)
            for income in (await s.execute(
                select(Transaction).where(Transaction.period == p,
                                          Transaction.recurring_income_id.is_not(None))
            )).scalars().all():
                if months_back > 0:
                    income.status = STATUS_DONE

            for _ in range(random.randint(9, 15)):
                name, cat, low, high = random.choice(VARIABLES)
                day = random.randint(1, 28 if months_back else max(1, today().day))
                account = random.choice([debito, visa, visa, diners])
                tx = Transaction(
                    kind=KIND_EXPENSE, status=STATUS_DONE,
                    date=dt.date(year, month, day), period=p,
                    amount=D(round(random.uniform(low, high), 2)),
                    description=name, category_id=cats[cat].id,
                    account_id=account.id, source="text",
                )
                s.add(tx)
                await s.flush()
                if account.type == ACCOUNT_CREDIT:
                    for inst in build_installments(tx, account, 1):
                        s.add(inst)

            if months_back == 0:
                s.add(Transaction(kind=KIND_INCOME, status=STATUS_DONE,
                                  date=dt.date(year, month, min(18, today().day)),
                                  period=p, amount=D("380"),
                                  description="Asesoría contable",
                                  income_type="asesoramiento",
                                  category_id=cats["Asesoramiento"].id,
                                  account_id=debito.id, source="text"))

        # Cena compartida con recibo e ítems
        cena = Transaction(
            kind=KIND_EXPENSE, status=STATUS_DONE,
            date=today() - dt.timedelta(days=4), period=period,
            amount=D("96.60"), description="Cena de cumpleaños",
            merchant="La Cocina de Doña Elsa", category_id=cats["Comida"].id,
            account_id=visa.id, source="photo",
        )
        for item, value, kind in [
            ("Lomo a la plancha", "18.50", "item"),
            ("Corvina al ajillo", "16.90", "item"),
            ("Pasta al pesto", "14.50", "item"),
            ("Jarra de sangría", "22.00", "item"),
            ("Postres (3)", "12.00", "item"),
            ("IVA 15%", "12.59", "tax"),
            ("Servicio 10%", "0.11", "tip"),
        ]:
            cena.items.append(ReceiptItem(name=item, total=D(value), kind=kind, quantity=D(1)))
        s.add(cena)
        await s.flush()
        for inst in build_installments(cena, visa, 1):
            s.add(inst)
        apply_split(cena, SPLIT_EQUAL, person_ids=[ana.id, luis.id, sofi.id])

        salida = Transaction(
            kind=KIND_EXPENSE, status=STATUS_DONE,
            date=today() - dt.timedelta(days=11), period=period,
            amount=D("54.00"), description="Bar con los panas",
            category_id=cats["Entretenimiento"].id, account_id=diners.id, source="voice",
        )
        s.add(salida)
        await s.flush()
        for inst in build_installments(salida, diners, 1):
            s.add(inst)
        apply_split(salida, SPLIT_EQUAL, person_ids=[luis.id])

        await s.commit()
        print("✅ Datos de demostración cargados.")
        print("   Corre:  uvicorn app.main:app --reload   y abre el panel.")


if __name__ == "__main__":
    asyncio.run(main(reset="--reset" in sys.argv))
