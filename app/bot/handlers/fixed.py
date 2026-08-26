"""Gastos fijos mensuales: arriendo, internet, préstamos, carro…"""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards import fixed_list, pick_list
from app.models import STATUS_PLANNED, Category, FixedExpense, Transaction
from app.money import D, total
from app.services.fixed import mark_paid, pending_this_month
from app.services.format import date_es, money
from app.services.periods import current_period, period_label, today

router = Router(name="fixed")


class NewFixed(StatesGroup):
    name = State()
    amount = State()
    day = State()
    category = State()


@router.message(Command("fijos"))
@router.message(F.text == "🏠 Fijos")
async def cmd_fixed(message: Message, session: AsyncSession) -> None:
    period = current_period()
    pending = await pending_this_month(session, period)
    defined = (
        await session.execute(
            select(FixedExpense).where(FixedExpense.active.is_(True)).order_by(FixedExpense.due_day)
        )
    ).scalars().all()

    if not defined:
        await message.answer(
            "🏠 Aún no tienes gastos fijos.\n\n"
            "Agrégalos con /nuevofijo (arriendo, internet, teléfono, préstamo, carro…) "
            "y cada mes te los recuerdo y los descuento de tu disponible.",
        )
        return

    lines = [f"🏠 <b>Gastos fijos</b> · {period_label(period)}", ""]
    paid = [
        t
        for t in (
            await session.execute(
                select(Transaction).where(
                    Transaction.period == period,
                    Transaction.fixed_expense_id.is_not(None),
                    Transaction.status != STATUS_PLANNED,
                )
            )
        ).scalars().all()
    ]
    for tx in pending:
        mark = "⚠️" if tx.date < today() else "🕒"
        lines.append(f"{mark} {tx.description} — <b>{money(tx.amount)}</b> · vence {date_es(tx.date)}")
    for tx in paid:
        lines.append(f"✅ {tx.description} — {money(tx.amount)}")

    lines.append("")
    lines.append(f"Pendiente: <b>{money(total(t.amount for t in pending))}</b>")
    lines.append(f"Pagado: {money(total(t.amount for t in paid))}")

    loans = [f for f in defined if f.lender_person_id or f.installments_total]
    if loans:
        lines.append("\n🏦 <b>Préstamos</b>")
        for loan in loans:
            who = loan.lender.name if loan.lender else "—"
            extra = f" · {loan.installments_total} cuotas" if loan.installments_total else ""
            lines.append(f"   • {loan.name} ({who}) {money(loan.amount)}/mes{extra}")

    await message.answer("\n".join(lines), reply_markup=fixed_list(pending))


@router.callback_query(F.data.startswith("f:paid:"))
async def cb_mark_paid(callback: CallbackQuery, session: AsyncSession) -> None:
    tx = await session.get(Transaction, int(callback.data.split(":")[2]))
    if tx is None:
        await callback.answer("No encontrado", show_alert=True)
        return
    await mark_paid(session, tx, date=today())
    await callback.message.answer(f"✅ {tx.description} marcado como pagado ({money(tx.amount)}).")
    await callback.answer("Pagado")


# ------------------------------------------------------------- alta guiada


@router.callback_query(F.data == "f:new")
async def cb_new_fixed(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(NewFixed.name)
    await callback.message.answer("🏠 ¿Cómo se llama el gasto fijo? <i>(ej: Arriendo)</i>")
    await callback.answer()


@router.message(Command("nuevofijo"))
async def cmd_new_fixed(message: Message, state: FSMContext) -> None:
    await state.set_state(NewFixed.name)
    await message.answer("🏠 ¿Cómo se llama el gasto fijo? <i>(ej: Arriendo)</i>")


@router.message(NewFixed.name)
async def step_name(message: Message, state: FSMContext) -> None:
    await state.update_data(name=message.text.strip()[:96])
    await state.set_state(NewFixed.amount)
    await message.answer("💵 ¿Cuánto es al mes?")


@router.message(NewFixed.amount)
async def step_amount(message: Message, state: FSMContext) -> None:
    try:
        amount = D(message.text.replace("$", "").strip())
    except Exception:
        await message.answer("Mándame solo el número, por ejemplo <code>350</code>.")
        return
    await state.update_data(amount=float(amount))
    await state.set_state(NewFixed.day)
    await message.answer("📅 ¿Qué día del mes se paga? <i>(1 a 31)</i>")


@router.message(NewFixed.day)
async def step_day(message: Message, state: FSMContext, session: AsyncSession) -> None:
    raw = message.text.strip()
    if not raw.isdigit() or not 1 <= int(raw) <= 31:
        await message.answer("Dime un número del 1 al 31.")
        return
    await state.update_data(day=int(raw))
    cats = (
        await session.execute(
            select(Category).where(Category.kind == "expense").order_by(Category.name)
        )
    ).scalars().all()
    await state.set_state(NewFixed.category)
    await message.answer(
        "🏷️ ¿En qué categoría lo pongo?",
        reply_markup=pick_list("f:cat", 0, [(c.id, c.label()) for c in cats], back=False),
    )


@router.callback_query(F.data.startswith("f:cat:"), NewFixed.category)
async def step_category(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    category_id = int(callback.data.split(":")[3])
    data = await state.get_data()
    fixed = FixedExpense(
        name=data["name"],
        amount=D(data["amount"]),
        due_day=data["day"],
        category_id=category_id,
        start_period=current_period(),
    )
    session.add(fixed)
    await session.flush()
    await state.clear()
    await callback.message.edit_text(
        f"✅ Gasto fijo creado:\n<b>{fixed.name}</b> — {money(fixed.amount)} "
        f"cada día {fixed.due_day}.\n\nLo verás en /fijos y en tu disponible mensual."
    )
    await callback.answer("Creado")
