"""Tarjetas de crédito: cortes, cuotas y pagos."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards import card_actions, card_fields, card_list
from app.models import ACCOUNT_CREDIT, Account, CardPayment
from app.money import D, ZERO, total
from app.services.cards import (
    card_balance,
    credit_cards,
    cut_day_of,
    deferred_purchases,
    due_day_of,
    future_commitments,
    place_purchase,
    statement,
)
from app.services.format import block, date_es, money, row
from app.services.periods import current_period, period_label, today
from app.services.reports import statement_due_in

router = Router(name="cards")


async def _cards_text(session: AsyncSession) -> tuple[str, list]:
    cards = await credit_cards(session)
    if not cards:
        return (
            "Todavía no tienes tarjetas registradas.\n"
            "Agrégalas con /setup: nombre, día de corte y día de pago.",
            [],
        )
    period = current_period()
    lines = [f"<b>Tarjetas</b> · {period_label(period)}", ""]
    statements = []
    grand_total = ZERO
    for card in cards:
        target = statement_due_in(period, cut_day_of(card), due_day_of(card))
        summary = await statement(session, card, target)
        statements.append(summary)
        grand_total = D(grand_total + summary.to_pay)

        if summary.to_pay <= 0:
            when = "sin saldo por pagar"
        elif summary.is_overdue:
            when = f"venció el {date_es(summary.due_date)}"
        elif summary.days_left == 0:
            when = "vence hoy"
        elif summary.days_left <= 5:
            when = f"vence en {summary.days_left} días"
        else:
            when = f"vence {date_es(summary.due_date)}"

        lines.append(f"<b>{card.name}</b> · {money(summary.to_pay)}")
        lines.append(f"Corte {date_es(summary.cut_date)} · {when}")
        if summary.others_share > 0:
            lines.append(f"De eso, {money(summary.others_share)} es de otros.")
        deferred = [i for i in summary.installments if i.count > 1]
        if deferred:
            plural = "cuota" if len(deferred) == 1 else "cuotas"
            lines.append(f"{len(deferred)} {plural} de diferidos en este corte.")
        if card.credit_limit:
            used = await card_balance(session, card)
            lines.append(
                f"Cupo libre {money(D(D(card.credit_limit) - used))} "
                f"de {money(card.credit_limit)}."
            )
        lines.append("")

    lines.append(f"<b>Total a pagar este mes: {money(grand_total)}</b>")
    return "\n".join(lines), statements


@router.message(Command("tarjetas"))
@router.message(F.text == "Tarjetas")
async def cmd_cards(message: Message, session: AsyncSession) -> None:
    text, statements = await _cards_text(session)
    await message.answer(text, reply_markup=card_actions(statements) if statements else None)


@router.callback_query(F.data == "c:future")
async def cb_future(callback: CallbackQuery, session: AsyncSession) -> None:
    period = current_period()
    lines = ["<b>Cuotas ya comprometidas</b>", ""]
    for card in await credit_cards(session):
        rows = await future_commitments(session, card, period, months=6)
        rows = [(p, a) for p, a in rows if a > 0]
        if not rows:
            continue
        lines.append(f"<b>{card.name}</b>")
        for p, amount in rows:
            lines.append(f"   {period_label(p)}: {money(amount)}")
        lines.append("")
    if len(lines) <= 2:
        lines.append("No hay cuotas futuras registradas.")
    await callback.message.answer("\n".join(lines))
    await callback.answer()


@router.callback_query(F.data.startswith("c:pay:"))
async def cb_pay(callback: CallbackQuery, session: AsyncSession) -> None:
    _, _, account_id, period = callback.data.split(":")
    card = await session.get(Account, int(account_id))
    if card is None:
        await callback.answer("Tarjeta no encontrada", show_alert=True)
        return
    summary = await statement(session, card, period)
    if summary.to_pay <= 0:
        await callback.answer("Ese corte ya está pagado", show_alert=True)
        return
    session.add(
        CardPayment(
            account_id=card.id,
            date=summary.due_date,
            amount=summary.to_pay,
            statement_period=period,
            note="Pago total del corte",
        )
    )
    await session.flush()
    await callback.message.answer(
        f"Registrado el pago de <b>{money(summary.to_pay)}</b> a {card.name} "
        f"(corte {period_label(period)})."
    )
    await callback.answer("Pago registrado")


@router.message(Command("pagar"))
async def cmd_pay(message: Message, session: AsyncSession) -> None:
    """/pagar visa 250  → registra un abono parcial."""
    parts = (message.text or "").split()
    if len(parts) < 3:
        await message.answer(
            "Uso: <code>/pagar visa 250</code>\n"
            "Registra un abono a esa tarjeta contra el corte que vence este mes."
        )
        return
    name, raw_amount = " ".join(parts[1:-1]), parts[-1]
    cards = await credit_cards(session)
    card = next((c for c in cards if name.lower() in c.name.lower()), None)
    if card is None:
        await message.answer(
            "No encontré esa tarjeta. Tienes: " + ", ".join(c.name for c in cards)
        )
        return
    try:
        amount = D(raw_amount)
    except Exception:
        await message.answer("No entendí el monto.")
        return
    period = statement_due_in(current_period(), cut_day_of(card), due_day_of(card))
    session.add(
        CardPayment(account_id=card.id, date=today(),
                    amount=amount, statement_period=period, note="Abono")
    )
    await session.flush()
    summary = await statement(session, card, period)
    await message.answer(
        f"Abono de {money(amount)} a <b>{card.name}</b>.\n"
        f"Queda pendiente <b>{money(summary.to_pay)}</b> del corte {period_label(period)}."
    )


# ------------------------------------------------------- detalle de un corte


@router.callback_query(F.data.startswith("c:det:"))
async def cb_statement_detail(callback: CallbackQuery, session: AsyncSession) -> None:
    _, _, account_id, period = callback.data.split(":")
    card = await session.get(Account, int(account_id))
    if card is None:
        await callback.answer("Tarjeta no encontrada", show_alert=True)
        return
    summary = await statement(session, card, period)

    lines = [
        f"<b>{card.name}</b> · corte de {period_label(period).lower()}",
        f"Cierra el {date_es(summary.cut_date)}, lo pagas el {date_es(summary.due_date)}.",
        "",
    ]
    if not summary.installments:
        lines.append("No hay movimientos en este corte.")
    else:
        detalle = []
        for inst in summary.installments:
            tx = inst.transaction
            etiqueta = tx.description[:20] if tx else "Movimiento"
            if inst.count > 1:
                etiqueta = f"{etiqueta} {inst.number}/{inst.count}"
            fecha = tx.date.strftime("%d/%m") if tx else ""
            detalle.append(row(f"{fecha} {etiqueta}", money(inst.amount), 34))
        lines.append(block(detalle))
        lines.append("")
        lines.append(f"<b>Total del corte: {money(summary.charges)}</b>")
        if summary.paid > 0:
            lines.append(f"Pagado: {money(summary.paid)} · queda {money(summary.to_pay)}")
        if summary.others_share > 0:
            lines.append(f"De eso, {money(summary.others_share)} es de otros.")

    await callback.message.answer("\n".join(lines))
    await callback.answer()


@router.message(Command("corte", "cortes"))
async def cmd_cuts(message: Message, session: AsyncSession) -> None:
    """Explica, tarjeta por tarjeta, qué se compra hoy y a qué mes cae."""
    cards = await credit_cards(session)
    if not cards:
        await message.answer(
            "No tienes tarjetas registradas. Agrégalas con /nuevatarjeta."
        )
        return

    hoy = today()
    lines = [f"<b>En qué mes cae lo que compres hoy</b> ({date_es(hoy)})", ""]
    for card in cards:
        placement = place_purchase(card, hoy, ZERO, 1)
        lines.append(f"<b>{card.name}</b>")
        lines.append(
            f"Corte el {card.cut_day} · pago el {card.due_day}"
        )
        lines.append(
            f"Lo que compres hoy entra al corte del "
            f"{date_es(placement.cut_date)} y lo pagas el "
            f"{date_es(placement.due_date)}."
        )
        restantes = (placement.cut_date - hoy).days
        if restantes == 0:
            lines.append("<i>Hoy es el corte: mañana ya cae al mes siguiente.</i>")
        elif 0 < restantes <= 3:
            lines.append(f"<i>Faltan {restantes} días para el corte.</i>")
        lines.append("")

    lines.append("Cambia las fechas con /tarjetas → Editar fechas.")
    await message.answer("\n".join(lines))


# --------------------------------------------------------- alta y edición


class CardEdit(StatesGroup):
    value = State()
    new_name = State()
    new_cut = State()
    new_due = State()
    new_limit = State()


FIELD_LABEL = {
    "cut": ("día de corte", "El día del mes en que cierra el estado de cuenta."),
    "due": ("día de pago", "El día máximo para pagar sin intereses."),
    "limit": ("cupo", "El cupo total de la tarjeta."),
}


@router.callback_query(F.data == "c:cards")
async def cb_card_list(callback: CallbackQuery, session: AsyncSession) -> None:
    cards = await credit_cards(session)
    text = (
        "<b>Tus tarjetas</b>\n\n"
        "El <b>día de corte</b> decide en qué mes cae cada compra; "
        "el <b>día de pago</b>, cuándo tienes que pagarla.\n\n"
        "Elige una para cambiarle las fechas."
        if cards
        else "Todavía no tienes tarjetas."
    )
    await callback.message.answer(text, reply_markup=card_list(cards))
    await callback.answer()


@router.message(Command("tarjeta", "editartarjeta"))
async def cmd_card_list(message: Message, session: AsyncSession) -> None:
    cards = await credit_cards(session)
    if not cards:
        await message.answer("No tienes tarjetas. Agrégalas con /nuevatarjeta.")
        return
    await message.answer("<b>Tus tarjetas</b>", reply_markup=card_list(cards))


@router.callback_query(F.data.startswith("c:edit:"))
async def cb_card_edit(callback: CallbackQuery, session: AsyncSession) -> None:
    card = await session.get(Account, int(callback.data.split(":")[2]))
    if card is None:
        await callback.answer("Tarjeta no encontrada", show_alert=True)
        return
    hoy = today()
    placement = place_purchase(card, hoy, ZERO, 1)
    await callback.message.answer(
        f"<b>{card.name}</b>\n"
        f"Corte el {card.cut_day} · pago el {card.due_day}"
        + (f" · cupo {money(card.credit_limit)}" if card.credit_limit else "")
        + f"\n\nLo que compres hoy cae en el corte del "
        f"{date_es(placement.cut_date)} y se paga el {date_es(placement.due_date)}.\n\n"
        "¿Qué quieres cambiar?",
        reply_markup=card_fields(card.id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("c:set:"))
async def cb_card_set(callback: CallbackQuery, state: FSMContext) -> None:
    _, _, card_id, field = callback.data.split(":")
    label, hint = FIELD_LABEL[field]
    await state.set_state(CardEdit.value)
    await state.update_data(card_id=int(card_id), field=field)
    await callback.message.answer(f"¿Cuál es el {label}?\n<i>{hint}</i>")
    await callback.answer()


@router.message(CardEdit.value)
async def step_card_value(message: Message, state: FSMContext, session: AsyncSession) -> None:
    data = await state.get_data()
    field = data["field"]
    raw = (message.text or "").replace("$", "").strip()
    card = await session.get(Account, data["card_id"])
    if card is None:
        await state.clear()
        await message.answer("Esa tarjeta ya no existe.")
        return

    if field in ("cut", "due"):
        if not raw.isdigit() or not 1 <= int(raw) <= 31:
            await message.answer("Dime un número del 1 al 31.")
            return
        setattr(card, "cut_day" if field == "cut" else "due_day", int(raw))
    else:
        try:
            card.credit_limit = D(raw)
        except Exception:
            await message.answer("Mándame solo el número del cupo.")
            return

    await session.flush()
    await state.clear()
    placement = place_purchase(card, today(), ZERO, 1)
    await message.answer(
        f"Listo. <b>{card.name}</b>: corte el {card.cut_day}, pago el {card.due_day}"
        + (f", cupo {money(card.credit_limit)}" if card.credit_limit else "")
        + f".\n\nLo que compres hoy cae en el corte del {date_es(placement.cut_date)} "
        f"y lo pagas el {date_es(placement.due_date)}."
    )


@router.callback_query(F.data == "c:new")
async def cb_new_card(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(CardEdit.new_name)
    await callback.message.answer("¿Cómo le dices a la tarjeta? <i>(ej: Visa Pichincha)</i>")
    await callback.answer()


@router.message(Command("nuevatarjeta"))
async def cmd_new_card(message: Message, state: FSMContext) -> None:
    await state.set_state(CardEdit.new_name)
    await message.answer("¿Cómo le dices a la tarjeta? <i>(ej: Visa Pichincha)</i>")


@router.message(CardEdit.new_name)
async def step_new_name(message: Message, state: FSMContext) -> None:
    await state.update_data(name=message.text.strip()[:64])
    await state.set_state(CardEdit.new_cut)
    await message.answer(
        "¿Qué día es el <b>corte</b>?\n"
        "<i>Es el día que cierra el estado de cuenta: lo que compres después "
        "ya cae al mes siguiente.</i>"
    )


@router.message(CardEdit.new_cut)
async def step_new_cut(message: Message, state: FSMContext) -> None:
    raw = message.text.strip()
    if not raw.isdigit() or not 1 <= int(raw) <= 31:
        await message.answer("Dime un número del 1 al 31.")
        return
    await state.update_data(cut=int(raw))
    await state.set_state(CardEdit.new_due)
    await message.answer("¿Y qué día vence el pago?")


@router.message(CardEdit.new_due)
async def step_new_due(message: Message, state: FSMContext) -> None:
    raw = message.text.strip()
    if not raw.isdigit() or not 1 <= int(raw) <= 31:
        await message.answer("Dime un número del 1 al 31.")
        return
    await state.update_data(due=int(raw))
    await state.set_state(CardEdit.new_limit)
    await message.answer("¿Cuál es el cupo? <i>(o escribe «no sé»)</i>")


@router.message(CardEdit.new_limit)
async def step_new_limit(message: Message, state: FSMContext, session: AsyncSession) -> None:
    raw = (message.text or "").replace("$", "").strip()
    try:
        limit = D(raw)
    except Exception:
        limit = None
    data = await state.get_data()
    card = Account(
        name=data["name"], type=ACCOUNT_CREDIT,
        cut_day=data["cut"], due_day=data["due"], credit_limit=limit,
    )
    session.add(card)
    await session.flush()
    await state.clear()
    placement = place_purchase(card, today(), ZERO, 1)
    await message.answer(
        f"Tarjeta creada: <b>{card.name}</b>, corte el {card.cut_day}, "
        f"pago el {card.due_day}"
        + (f", cupo {money(card.credit_limit)}" if card.credit_limit else "")
        + f".\n\nLo que compres hoy con ella cae en el corte del "
        f"{date_es(placement.cut_date)} y lo pagas el {date_es(placement.due_date)}."
    )


# --------------------------------------------------------------- diferidos


@router.message(Command("diferidos", "cuotas"))
async def cmd_deferred(message: Message, session: AsyncSession) -> None:
    """Cuánto falta por pagar de cada compra a cuotas."""
    compras = await deferred_purchases(session)
    if not compras:
        await message.answer(
            "No tienes compras a cuotas con saldo pendiente.\n\n"
            "Cuando anotes algo como <code>tv 899 diferido a 12 meses con visa</code> "
            "aquí verás cuánto te falta de cada una."
        )
        return

    lines = ["<b>Compras a cuotas</b>", ""]
    detalle = []
    for c in compras:
        nombre = c.transaction.description[:22]
        faltan = ("falta 1 cuota" if c.remaining == 1
                  else f"faltan {c.remaining} cuotas")
        lines.append(f"<b>{nombre}</b> · {c.account.name}")
        lines.append(
            f"{money(c.total)} a {c.count} meses · {money(c.installment)} al mes"
        )
        lines.append(
            f"Pagadas {c.paid} de {c.count} · {faltan}: "
            f"<b>{money(c.remaining_amount)}</b>"
        )
        lines.append("")
        detalle.append(row(nombre, money(c.remaining_amount), 34))

    if len(compras) > 1:
        lines.append(block(detalle))
    lines.append(
        f"<b>Te falta pagar {money(total(c.remaining_amount for c in compras))} "
        f"en cuotas.</b>"
    )
    lines.append(
        f"Cada mes se te van {money(total(c.installment for c in compras))} "
        f"solo en diferidos."
    )
    await message.answer("\n".join(lines))
