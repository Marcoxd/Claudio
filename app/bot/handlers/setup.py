"""Asistente de configuración inicial (/setup).

Pensado para entregar el bot ya instalado y que el usuario lo deje listo en
5 minutos: nombre, sueldo, gastos fijos, tarjetas y colchón.
"""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards import main_menu
from app.config import settings
from app.models import ACCOUNT_CREDIT, Account, FixedExpense, RecurringIncome, Setting
from app.money import D
from app.services import buffer as buffer_service
from app.services.dashboard_link import dashboard_url
from app.services.format import money
from app.services.periods import current_period

router = Router(name="setup")

OWNER_NAME_KEY = "owner_name"


class Setup(StatesGroup):
    name = State()
    salary = State()
    salary_day = State()
    fixed_name = State()
    fixed_amount = State()
    fixed_day = State()
    card_name = State()
    card_cut = State()
    card_due = State()
    card_limit = State()
    buffer = State()


def _more(kind: str, label: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=f"➕ Agregar {label}", callback_data=f"su:more:{kind}"),
                InlineKeyboardButton(text="✔️ Siguiente", callback_data=f"su:next:{kind}"),
            ]
        ]
    )


def _skip(kind: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="⏭️ Saltar", callback_data=f"su:next:{kind}")]]
    )


async def _save_setting(session: AsyncSession, key: str, value: str) -> None:
    row = (await session.execute(select(Setting).where(Setting.key == key))).scalar_one_or_none()
    if row is None:
        session.add(Setting(key=key, value=value))
    else:
        row.value = value
    await session.flush()


@router.message(Command("setup", "configurar"))
async def cmd_setup(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(Setup.name)
    await message.answer(
        f"⚙️ <b>Configuremos {settings.app_name}</b>\n\n"
        "Son 5 pasos cortos. Puedes saltarte los que quieras y cambiarlos después.\n\n"
        "<b>1/5 · ¿Cómo te llamas?</b>"
    )


@router.message(Setup.name)
async def step_name(message: Message, state: FSMContext, session: AsyncSession) -> None:
    name = message.text.strip()[:64]
    await _save_setting(session, OWNER_NAME_KEY, name)
    await state.set_state(Setup.salary)
    await message.answer(
        f"Listo, {name} 👋\n\n"
        "<b>2/5 · Tu sueldo</b>\n"
        "¿Cuánto recibes fijo al mes? <i>(solo el número)</i>",
        reply_markup=_skip("salary"),
    )


@router.message(Setup.salary)
async def step_salary(message: Message, state: FSMContext) -> None:
    try:
        amount = D(message.text.replace("$", "").strip())
    except Exception:
        await message.answer("Mándame solo el número, por ejemplo <code>1200</code>.")
        return
    await state.update_data(salary=float(amount))
    await state.set_state(Setup.salary_day)
    await message.answer("📅 ¿Qué día del mes te pagan? <i>(1 a 31)</i>")


@router.message(Setup.salary_day)
async def step_salary_day(message: Message, state: FSMContext, session: AsyncSession) -> None:
    raw = message.text.strip()
    if not raw.isdigit() or not 1 <= int(raw) <= 31:
        await message.answer("Dime un número del 1 al 31.")
        return
    data = await state.get_data()
    session.add(
        RecurringIncome(
            name="Sueldo",
            amount=D(data["salary"]),
            pay_day=int(raw),
            start_period=current_period(),
        )
    )
    await session.flush()
    await _ask_fixed(message, state)


async def _ask_fixed(message: Message, state: FSMContext) -> None:
    await state.set_state(Setup.fixed_name)
    await message.answer(
        "<b>3/5 · Gastos fijos</b>\n"
        "Arriendo, internet, teléfono, préstamo, cuota del carro…\n\n"
        "¿Cómo se llama el primero? <i>(o sáltate este paso)</i>",
        reply_markup=_skip("fixed"),
    )


@router.message(Setup.fixed_name)
async def step_fixed_name(message: Message, state: FSMContext) -> None:
    await state.update_data(fixed_name=message.text.strip()[:96])
    await state.set_state(Setup.fixed_amount)
    await message.answer("💵 ¿Cuánto pagas al mes?")


@router.message(Setup.fixed_amount)
async def step_fixed_amount(message: Message, state: FSMContext) -> None:
    try:
        amount = D(message.text.replace("$", "").strip())
    except Exception:
        await message.answer("Solo el número, por favor.")
        return
    await state.update_data(fixed_amount=float(amount))
    await state.set_state(Setup.fixed_day)
    await message.answer("📅 ¿Qué día del mes se paga?")


@router.message(Setup.fixed_day)
async def step_fixed_day(message: Message, state: FSMContext, session: AsyncSession) -> None:
    raw = message.text.strip()
    if not raw.isdigit() or not 1 <= int(raw) <= 31:
        await message.answer("Dime un número del 1 al 31.")
        return
    data = await state.get_data()
    fixed = FixedExpense(
        name=data["fixed_name"],
        amount=D(data["fixed_amount"]),
        due_day=int(raw),
        start_period=current_period(),
    )
    session.add(fixed)
    await session.flush()
    await state.set_state(Setup.fixed_name)
    await message.answer(
        f"✅ {fixed.name} — {money(fixed.amount)} el día {fixed.due_day}.",
        reply_markup=_more("fixed", "otro gasto fijo"),
    )


@router.callback_query(F.data == "su:more:fixed")
async def cb_more_fixed(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(Setup.fixed_name)
    await callback.message.answer("¿Cómo se llama el siguiente gasto fijo?")
    await callback.answer()


async def _ask_card(message: Message, state: FSMContext) -> None:
    await state.set_state(Setup.card_name)
    await message.answer(
        "<b>4/5 · Tarjetas de crédito</b>\n"
        "Necesito el día de <b>corte</b> y el día máximo de <b>pago</b> de cada una: "
        "con eso sé en qué mes cae cada compra y cuánto te toca pagar.\n\n"
        "¿Cómo le dices a la primera? <i>(ej: Visa Pichincha)</i>",
        reply_markup=_skip("card"),
    )


@router.message(Setup.card_name)
async def step_card_name(message: Message, state: FSMContext) -> None:
    await state.update_data(card_name=message.text.strip()[:64])
    await state.set_state(Setup.card_cut)
    await message.answer("✂️ ¿Qué día es el <b>corte</b>? <i>(1 a 31)</i>")


@router.message(Setup.card_cut)
async def step_card_cut(message: Message, state: FSMContext) -> None:
    raw = message.text.strip()
    if not raw.isdigit() or not 1 <= int(raw) <= 31:
        await message.answer("Dime un número del 1 al 31.")
        return
    await state.update_data(card_cut=int(raw))
    await state.set_state(Setup.card_due)
    await message.answer("💳 ¿Y qué día vence el pago?")


@router.message(Setup.card_due)
async def step_card_due(message: Message, state: FSMContext) -> None:
    raw = message.text.strip()
    if not raw.isdigit() or not 1 <= int(raw) <= 31:
        await message.answer("Dime un número del 1 al 31.")
        return
    await state.update_data(card_due=int(raw))
    await state.set_state(Setup.card_limit)
    await message.answer(
        "💠 ¿Cuál es el cupo de la tarjeta? <i>(opcional)</i>",
        reply_markup=_skip("card_limit"),
    )


@router.message(Setup.card_limit)
async def step_card_limit(message: Message, state: FSMContext, session: AsyncSession) -> None:
    try:
        limit = D(message.text.replace("$", "").strip())
    except Exception:
        limit = None
    await _create_card(message, state, session, limit)


@router.callback_query(F.data == "su:next:card_limit")
async def cb_skip_limit(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    await _create_card(callback.message, state, session, None)
    await callback.answer()


async def _create_card(message, state: FSMContext, session: AsyncSession, limit) -> None:
    data = await state.get_data()
    card = Account(
        name=data["card_name"],
        type=ACCOUNT_CREDIT,
        cut_day=data["card_cut"],
        due_day=data["card_due"],
        credit_limit=limit,
    )
    session.add(card)
    await session.flush()
    await state.set_state(Setup.card_name)
    await message.answer(
        f"✅ <b>{card.name}</b> · corte {card.cut_day} · vence {card.due_day}"
        + (f" · cupo {money(card.credit_limit)}" if card.credit_limit else ""),
        reply_markup=_more("card", "otra tarjeta"),
    )


@router.callback_query(F.data == "su:more:card")
async def cb_more_card(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(Setup.card_name)
    await callback.message.answer("¿Cómo le dices a la siguiente tarjeta?")
    await callback.answer()


async def _ask_buffer(message: Message, state: FSMContext) -> None:
    await state.set_state(Setup.buffer)
    await message.answer(
        f"<b>5/5 · {settings.buffer_name}</b>\n"
        "Ese dinero que usas pero <b>no es tuyo</b>. Lo llevo aparte para que nunca "
        "lo confundas con tu saldo.\n\n"
        "¿De cuánto es? <i>(o sáltate este paso)</i>",
        reply_markup=_skip("buffer"),
    )


@router.message(Setup.buffer)
async def step_buffer(message: Message, state: FSMContext, session: AsyncSession) -> None:
    try:
        amount = D(message.text.replace("$", "").strip())
    except Exception:
        await message.answer("Solo el número, por favor.")
        return
    await buffer_service.set_total(session, amount)
    await _finish(message, state, session)


# ------------------------------------------------------------------ navegación


@router.callback_query(F.data.startswith("su:next:"))
async def cb_next(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    kind = callback.data.split(":")[2]
    await callback.answer()
    if kind == "salary":
        await _ask_fixed(callback.message, state)
    elif kind == "fixed":
        await _ask_card(callback.message, state)
    elif kind == "card":
        await _ask_buffer(callback.message, state)
    elif kind == "buffer":
        await _finish(callback.message, state, session)


async def _finish(message, state: FSMContext, session: AsyncSession) -> None:
    await state.clear()
    cards = (
        await session.execute(select(Account).where(Account.type == ACCOUNT_CREDIT))
    ).scalars().all()
    fixed = (await session.execute(select(FixedExpense))).scalars().all()
    incomes = (await session.execute(select(RecurringIncome))).scalars().all()
    buffer_state = await buffer_service.state(session)

    lines = ["🎉 <b>¡Todo listo!</b>", ""]
    if incomes:
        lines.append(f"💼 Sueldo: {money(incomes[0].amount)} el día {incomes[0].pay_day}")
    if fixed:
        lines.append(f"🏠 {len(fixed)} gastos fijos por {money(sum(f.amount for f in fixed))}/mes")
    if cards:
        lines.append(f"💳 {len(cards)} tarjeta(s): " + ", ".join(c.name for c in cards))
    if buffer_state.total > 0:
        lines.append(f"🛏️ {buffer_state.name}: {money(buffer_state.total)}")

    lines += [
        "",
        "Ahora simplemente escríbeme tus gastos:",
        "<i>«almuerzo 12.50 con la visa»</i>",
        "…o mándame la foto del recibo 📷 o una nota de voz 🎤",
        "",
        f"📈 Tu panel: {dashboard_url()}",
    ]
    await message.answer("\n".join(lines), reply_markup=main_menu(), disable_web_page_preview=True)
