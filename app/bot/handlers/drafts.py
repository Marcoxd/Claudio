"""Confirmación y edición de borradores, y división de cuentas."""
from __future__ import annotations

import logging
from decimal import Decimal

from aiogram import F, Router
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards import (
    draft_actions,
    installments_menu,
    item_assign,
    people_picker,
    pick_list,
    split_menu,
)
from app.models import Account, Category, Draft, Person
from app.money import D, split_evenly, total
from app.services.capture import commit_draft, delete_draft, load_draft, update_draft
from app.services.format import money
from app.services.render import describe_draft

log = logging.getLogger(__name__)
router = Router(name="drafts")

AWAIT_PERSON = "await_person"


async def _refresh(callback: CallbackQuery, session: AsyncSession, draft: Draft, payload: dict) -> None:
    text, has_items = await describe_draft(session, payload)
    await callback.message.edit_text(text, reply_markup=draft_actions(draft.id, has_items))


async def _get(callback: CallbackQuery, session: AsyncSession):
    draft_id = int(callback.data.split(":")[2])
    draft, payload = await load_draft(session, draft_id)
    if draft is None:
        await callback.answer("Ese borrador ya no existe.", show_alert=True)
        return None, None
    return draft, payload


# ------------------------------------------------------------------ guardar


@router.callback_query(F.data.startswith("d:save:"))
async def cb_save(callback: CallbackQuery, session: AsyncSession) -> None:
    draft, payload = await _get(callback, session)
    if draft is None:
        return
    tx = await commit_draft(session, payload)
    await delete_draft(session, draft)

    lines = [f"✅ Guardado · <code>{money(tx.amount)}</code> · {tx.description}"]
    if tx.split and tx.my_share is not None:
        lines.append(f"👤 Te toca <b>{money(tx.my_share)}</b>")
        ids = [s.person_id for s in tx.split.shares if s.person_id is not None]
        names = {
            p.id: p.name
            for p in (
                await session.execute(select(Person).where(Person.id.in_(ids)))
            ).scalars().all()
        }
        for share in tx.split.shares:
            if share.person_id is not None:
                lines.append(
                    f"   • {names.get(share.person_id, 'Alguien')} debe {money(share.amount)}"
                )
    if tx.installments:
        first = tx.installments[0]
        if first.count > 1:
            lines.append(
                f"💳 {first.count} cuotas de {money(first.amount)} "
                f"desde el corte {first.statement_period}"
            )
        else:
            lines.append(f"💳 Entra al corte {first.statement_period} "
                         f"(vence {first.due_date.strftime('%d/%m')})")
    await callback.message.edit_text("\n".join(lines))
    await callback.answer("Guardado")


@router.callback_query(F.data.startswith("d:del:"))
async def cb_delete(callback: CallbackQuery, session: AsyncSession) -> None:
    draft, _ = await _get(callback, session)
    if draft is None:
        return
    await delete_draft(session, draft)
    await callback.message.edit_text("🗑 Descartado.")
    await callback.answer()


@router.callback_query(F.data.startswith("d:back:"))
async def cb_back(callback: CallbackQuery, session: AsyncSession) -> None:
    draft, payload = await _get(callback, session)
    if draft is None:
        return
    draft.state = "review"
    await _refresh(callback, session, draft, payload)
    await callback.answer()


# ------------------------------------------------------------------ editar


@router.callback_query(F.data.startswith("d:cat:"))
async def cb_pick_category(callback: CallbackQuery, session: AsyncSession) -> None:
    draft, payload = await _get(callback, session)
    if draft is None:
        return
    cats = (
        await session.execute(
            select(Category).where(Category.kind == payload["kind"]).order_by(Category.name)
        )
    ).scalars().all()
    await callback.message.edit_reply_markup(
        reply_markup=pick_list("d:setcat", draft.id, [(c.id, c.label()) for c in cats])
    )
    await callback.answer()


@router.callback_query(F.data.startswith("d:setcat:"))
async def cb_set_category(callback: CallbackQuery, session: AsyncSession) -> None:
    _, _, draft_id, cat_id = callback.data.split(":")
    draft, payload = await load_draft(session, int(draft_id))
    if draft is None:
        await callback.answer("Borrador vencido", show_alert=True)
        return
    payload["category_id"] = int(cat_id)
    await update_draft(session, draft, payload)
    await _refresh(callback, session, draft, payload)
    await callback.answer("Categoría actualizada")


@router.callback_query(F.data.startswith("d:acc:"))
async def cb_pick_account(callback: CallbackQuery, session: AsyncSession) -> None:
    draft, payload = await _get(callback, session)
    if draft is None:
        return
    accounts = (
        await session.execute(
            select(Account).where(Account.active.is_(True)).order_by(Account.type, Account.name)
        )
    ).scalars().all()
    labels = [
        (a.id, ("💳 " if a.is_credit() else "💵 ") + a.name) for a in accounts
    ]
    await callback.message.edit_reply_markup(
        reply_markup=pick_list("d:setacc", draft.id, labels)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("d:setacc:"))
async def cb_set_account(callback: CallbackQuery, session: AsyncSession) -> None:
    _, _, draft_id, account_id = callback.data.split(":")
    draft, payload = await load_draft(session, int(draft_id))
    if draft is None:
        await callback.answer("Borrador vencido", show_alert=True)
        return
    payload["account_id"] = int(account_id)
    await update_draft(session, draft, payload)
    await _refresh(callback, session, draft, payload)
    await callback.answer("Medio de pago actualizado")


@router.callback_query(F.data.startswith("d:inst:"))
async def cb_installments(callback: CallbackQuery, session: AsyncSession) -> None:
    draft, payload = await _get(callback, session)
    if draft is None:
        return
    await callback.message.edit_reply_markup(reply_markup=installments_menu(draft.id))
    await callback.answer()


@router.callback_query(F.data.startswith("d:setinst:"))
async def cb_set_installments(callback: CallbackQuery, session: AsyncSession) -> None:
    _, _, draft_id, count = callback.data.split(":")
    draft, payload = await load_draft(session, int(draft_id))
    if draft is None:
        await callback.answer("Borrador vencido", show_alert=True)
        return
    payload["installments"] = int(count)
    await update_draft(session, draft, payload)
    await _refresh(callback, session, draft, payload)
    await callback.answer(f"Diferido a {count} meses" if int(count) > 1 else "Corriente")


@router.callback_query(F.data.startswith("d:items:"))
async def cb_show_items(callback: CallbackQuery, session: AsyncSession) -> None:
    draft, payload = await _get(callback, session)
    if draft is None:
        return
    lines = ["🧺 <b>Ítems del recibo</b>", ""]
    for item in payload.get("items") or []:
        tag = {"tax": "🧾", "tip": "🫱", "discount": "🔻"}.get(item["kind"], "•")
        qty = f"{item['quantity']:g}× " if float(item.get("quantity") or 1) != 1 else ""
        lines.append(f"{tag} {qty}{item['name']} — {money(item['total'])}")
    lines.append(f"\n<b>Total: {money(payload['amount'])}</b>")
    await callback.message.answer("\n".join(lines))
    await callback.answer()


# ------------------------------------------------------------------ dividir


@router.callback_query(F.data.startswith("d:split:"))
async def cb_split_menu(callback: CallbackQuery, session: AsyncSession) -> None:
    draft, payload = await _get(callback, session)
    if draft is None:
        return
    has_items = bool([i for i in (payload.get("items") or []) if i["kind"] == "item"])
    await callback.message.edit_reply_markup(reply_markup=split_menu(draft.id, has_items))
    await callback.answer()


async def _people_options(session: AsyncSession) -> list[tuple[int, str]]:
    rows = (
        await session.execute(
            select(Person).where(Person.active.is_(True)).order_by(Person.name)
        )
    ).scalars().all()
    return [(p.id, p.name) for p in rows]


@router.callback_query(F.data.startswith("s:equal:"))
async def cb_split_equal(callback: CallbackQuery, session: AsyncSession) -> None:
    draft, payload = await _get(callback, session)
    if draft is None:
        return
    payload["split_mode"] = "equal"
    payload.pop("assign", None)
    await update_draft(session, draft, payload)
    people = await _people_options(session)
    if not people:
        draft.state = f"{AWAIT_PERSON}:equal"
        await session.flush()
        await callback.message.edit_text(
            "👥 ¿Con quién dividiste? Mándame los nombres separados por coma.\n"
            "<i>Ej: Ana, Luis</i>"
        )
        await callback.answer()
        return
    await callback.message.edit_reply_markup(
        reply_markup=people_picker(draft.id, people, set(payload.get("people_ids") or []))
    )
    await callback.answer()


@router.callback_query(F.data.startswith("s:tog:"))
async def cb_toggle_person(callback: CallbackQuery, session: AsyncSession) -> None:
    _, _, draft_id, person_id, mode = callback.data.split(":")
    draft, payload = await load_draft(session, int(draft_id))
    if draft is None:
        await callback.answer("Borrador vencido", show_alert=True)
        return
    selected = set(payload.get("people_ids") or [])
    pid = int(person_id)
    selected.symmetric_difference_update({pid})
    payload["people_ids"] = sorted(selected)
    await update_draft(session, draft, payload)
    people = await _people_options(session)
    await callback.message.edit_reply_markup(
        reply_markup=people_picker(draft.id, people, selected, mode)
    )
    n = len(selected) + (1 if payload.get("include_me", True) else 0)
    if n:
        await callback.answer(f"{money(D(payload['amount']) / n)} cada uno")
    else:
        await callback.answer()


@router.callback_query(F.data.startswith("s:new:"))
async def cb_new_person(callback: CallbackQuery, session: AsyncSession) -> None:
    _, _, draft_id, mode = callback.data.split(":")
    draft, payload = await load_draft(session, int(draft_id))
    if draft is None:
        await callback.answer("Borrador vencido", show_alert=True)
        return
    draft.state = f"{AWAIT_PERSON}:{mode}"
    await session.flush()
    await callback.message.answer(
        "✍️ Mándame el nombre (o varios separados por coma) de quienes se suman."
    )
    await callback.answer()


@router.callback_query(F.data.startswith("s:none:"))
async def cb_split_none(callback: CallbackQuery, session: AsyncSession) -> None:
    draft, payload = await _get(callback, session)
    if draft is None:
        return
    payload["split_mode"] = ""
    payload["people_ids"] = []
    payload.pop("assign", None)
    await update_draft(session, draft, payload)
    await _refresh(callback, session, draft, payload)
    await callback.answer("Sin dividir")


@router.callback_query(F.data.startswith("s:done:"))
async def cb_split_done(callback: CallbackQuery, session: AsyncSession) -> None:
    _, _, draft_id, mode = callback.data.split(":")
    draft, payload = await load_draft(session, int(draft_id))
    if draft is None:
        await callback.answer("Borrador vencido", show_alert=True)
        return
    if mode == "items":
        await _start_item_assignment(callback, session, draft, payload)
        return
    ids = payload.get("people_ids") or []
    if not ids:
        await callback.answer("Elige al menos una persona", show_alert=True)
        return
    payload["split_mode"] = "equal"
    await update_draft(session, draft, payload)
    await _refresh(callback, session, draft, payload)
    parts = split_evenly(D(payload["amount"]), len(ids) + 1)
    await callback.answer(f"Te toca {money(parts[0])}")


# --------------------------------------------------------- división por ítems


async def _start_item_assignment(callback, session, draft, payload) -> None:
    people = await _people_options(session)
    if not people:
        draft.state = f"{AWAIT_PERSON}:items"
        await session.flush()
        await callback.message.edit_text(
            "👥 Primero dime con quiénes estabas (nombres separados por coma)."
        )
        await callback.answer()
        return
    payload["split_mode"] = "items"
    payload.setdefault("assign", {})
    await update_draft(session, draft, payload)
    await _show_item(callback.message, session, draft, payload, 0, edit=True)
    await callback.answer()


async def _show_item(message, session, draft, payload, index: int, edit: bool = False) -> None:
    items = [i for i in (payload.get("items") or []) if i["kind"] == "item"]
    if not items:
        await message.answer("Este recibo no tiene ítems para dividir.")
        return
    index = max(0, min(index, len(items) - 1))
    item = items[index]
    assigned = payload.get("assign", {}).get(str(index), [])
    people = await _people_options(session)
    names = {str(pid): name for pid, name in people}
    who = ", ".join("Yo" if a == "me" else names.get(str(a), "?") for a in assigned) or "nadie aún"
    text = (
        f"🧺 <b>Ítem {index + 1} de {len(items)}</b>\n\n"
        f"<b>{item['name']}</b>\n"
        f"{money(item['total'])}\n\n"
        f"👤 Asignado a: <i>{who}</i>\n\n"
        f"<i>Los impuestos y la propina se reparten solos según lo que consumió cada quien.</i>"
    )
    parsed_assigned = [None if a == "me" else int(a) for a in assigned]
    markup = item_assign(draft.id, items, index, people, parsed_assigned)
    if edit:
        await message.edit_text(text, reply_markup=markup)
    else:
        await message.answer(text, reply_markup=markup)


@router.callback_query(F.data.startswith("i:go:"))
async def cb_item_go(callback: CallbackQuery, session: AsyncSession) -> None:
    _, _, draft_id, index = callback.data.split(":")
    draft, payload = await load_draft(session, int(draft_id))
    if draft is None:
        await callback.answer("Borrador vencido", show_alert=True)
        return
    await _show_item(callback.message, session, draft, payload, int(index), edit=True)
    await callback.answer()


@router.callback_query(F.data.startswith("i:tog:"))
async def cb_item_toggle(callback: CallbackQuery, session: AsyncSession) -> None:
    _, _, draft_id, index, who = callback.data.split(":")
    draft, payload = await load_draft(session, int(draft_id))
    if draft is None:
        await callback.answer("Borrador vencido", show_alert=True)
        return
    assign = payload.setdefault("assign", {})
    current = assign.setdefault(str(index), [])
    key = "me" if who == "me" else int(who)
    if key in current:
        current.remove(key)
    else:
        current.append(key)
    await update_draft(session, draft, payload)
    await _show_item(callback.message, session, draft, payload, int(index), edit=True)
    await callback.answer()


@router.callback_query(F.data.startswith("i:done:"))
async def cb_item_done(callback: CallbackQuery, session: AsyncSession) -> None:
    draft, payload = await _get(callback, session)
    if draft is None:
        return
    assign = {k: v for k, v in (payload.get("assign") or {}).items() if v}
    if not assign:
        await callback.answer("Asigna al menos un ítem", show_alert=True)
        return
    payload["assign"] = assign
    payload["split_mode"] = "items"
    payload["people_ids"] = sorted(
        {int(p) for values in assign.values() for p in values if p != "me"}
    )
    await update_draft(session, draft, payload)

    preview = _preview_items_split(payload, await _people_options(session))
    text, has_items = await describe_draft(session, payload)
    await callback.message.edit_text(
        text + "\n\n" + preview, reply_markup=draft_actions(draft.id, has_items)
    )
    await callback.answer()


def _preview_items_split(payload: dict, people: list[tuple[int, str]]) -> str:
    """Cálculo previo (mismo criterio que `splits.items_split`)."""
    items = [i for i in (payload.get("items") or []) if i["kind"] == "item"]
    names = {pid: name for pid, name in people}
    subtotals: dict[object, Decimal] = {}
    for index, participants in (payload.get("assign") or {}).items():
        position = int(index)
        if position >= len(items) or not participants:
            continue
        parts = split_evenly(D(items[position]["total"]), len(participants))
        for participant, part in zip(participants, parts):
            key = "me" if participant == "me" else int(participant)
            subtotals[key] = D(subtotals.get(key, D(0)) + part)
    if not subtotals:
        return ""
    base = total(subtotals.values())
    extra = D(D(payload["amount"]) - base)
    lines = ["🧮 <b>División por ítems</b>"]
    for key, value in subtotals.items():
        share = D(value + (extra * value / base if base else D(0)))
        who = "Yo" if key == "me" else names.get(key, "?")
        lines.append(f"  • {who}: <b>{money(share)}</b>")
    if extra:
        lines.append(f"  <i>(impuestos y propina prorrateados: {money(extra)})</i>")
    return "\n".join(lines)


# ------------------------------------------- alta rápida de personas por texto


@router.message(F.text & ~F.text.startswith("/"))
async def on_person_names(message: Message, session: AsyncSession) -> None:
    """Solo actúa si hay un borrador esperando nombres; si no, deja pasar."""
    draft = (
        await session.execute(
            select(Draft)
            .where(Draft.user_id == message.from_user.id,
                   Draft.state.startswith(AWAIT_PERSON))
            .order_by(Draft.id.desc())
        )
    ).scalars().first()
    if draft is None:
        raise SkipHandler

    mode = draft.state.split(":", 1)[1] if ":" in draft.state else "equal"
    _, payload = await load_draft(session, draft.id)
    names = [n.strip().title() for n in message.text.replace(" y ", ",").split(",") if n.strip()]
    ids = set(payload.get("people_ids") or [])
    for name in names:
        person = (
            await session.execute(select(Person).where(Person.name.ilike(name)))
        ).scalar_one_or_none()
        if person is None:
            person = Person(name=name)
            session.add(person)
            await session.flush()
        ids.add(person.id)
    payload["people_ids"] = sorted(ids)
    payload["split_mode"] = mode
    draft.state = "review"
    await update_draft(session, draft, payload)

    if mode == "items":
        await _show_item(message, session, draft, payload, 0)
        return
    text, has_items = await describe_draft(session, payload)
    await message.answer(text, reply_markup=draft_actions(draft.id, has_items))
