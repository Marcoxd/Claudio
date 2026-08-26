"""Teclados inline del bot."""
from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from app.services.format import money


def _rows(buttons: list[InlineKeyboardButton], per_row: int = 2) -> list[list[InlineKeyboardButton]]:
    return [buttons[i : i + per_row] for i in range(0, len(buttons), per_row)]


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📊 Resumen"), KeyboardButton(text="💳 Tarjetas")],
            [KeyboardButton(text="🏠 Fijos"), KeyboardButton(text="🤝 Deudas")],
            [KeyboardButton(text="🛏️ Colchón"), KeyboardButton(text="📈 Panel")],
        ],
        resize_keyboard=True,
        input_field_placeholder="Escribe un gasto, manda una foto o una nota de voz…",
    )


def draft_actions(draft_id: int, has_items: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text="✅ Guardar", callback_data=f"d:save:{draft_id}"),
            InlineKeyboardButton(text="🗑 Descartar", callback_data=f"d:del:{draft_id}"),
        ],
        [
            InlineKeyboardButton(text="🏷️ Categoría", callback_data=f"d:cat:{draft_id}"),
            InlineKeyboardButton(text="💳 Medio de pago", callback_data=f"d:acc:{draft_id}"),
        ],
        [
            InlineKeyboardButton(text="👥 Dividir cuenta", callback_data=f"d:split:{draft_id}"),
            InlineKeyboardButton(text="🧾 Diferir", callback_data=f"d:inst:{draft_id}"),
        ],
    ]
    if has_items:
        rows.append(
            [InlineKeyboardButton(text="🧺 Ver ítems", callback_data=f"d:items:{draft_id}")]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def pick_list(prefix: str, draft_id: int, options: list[tuple[int, str]], per_row: int = 2,
              back: bool = True) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(text=label[:28], callback_data=f"{prefix}:{draft_id}:{oid}")
        for oid, label in options
    ]
    rows = _rows(buttons, per_row)
    if back:
        rows.append(
            [InlineKeyboardButton(text="⬅️ Volver", callback_data=f"d:back:{draft_id}")]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def installments_menu(draft_id: int) -> InlineKeyboardMarkup:
    options = [1, 3, 6, 9, 12, 18, 24]
    buttons = [
        InlineKeyboardButton(
            text="Corriente" if n == 1 else f"{n} meses",
            callback_data=f"d:setinst:{draft_id}:{n}",
        )
        for n in options
    ]
    rows = _rows(buttons, 3)
    rows.append([InlineKeyboardButton(text="⬅️ Volver", callback_data=f"d:back:{draft_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def split_menu(draft_id: int, has_items: bool) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="➗ Partes iguales", callback_data=f"s:equal:{draft_id}")],
    ]
    if has_items:
        rows.append(
            [InlineKeyboardButton(text="🧺 Por ítems de la factura", callback_data=f"s:items:{draft_id}")]
        )
    rows.append(
        [InlineKeyboardButton(text="🚫 Sin dividir", callback_data=f"s:none:{draft_id}")]
    )
    rows.append([InlineKeyboardButton(text="⬅️ Volver", callback_data=f"d:back:{draft_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def people_picker(draft_id: int, people: list[tuple[int, str]], selected: set[int],
                  mode: str = "equal") -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(
            text=("✅ " if pid in selected else "▫️ ") + name[:20],
            callback_data=f"s:tog:{draft_id}:{pid}:{mode}",
        )
        for pid, name in people
    ]
    rows = _rows(buttons, 2)
    rows.append([InlineKeyboardButton(text="➕ Agregar persona", callback_data=f"s:new:{draft_id}:{mode}")])
    rows.append(
        [
            InlineKeyboardButton(text="✔️ Listo", callback_data=f"s:done:{draft_id}:{mode}"),
            InlineKeyboardButton(text="⬅️ Volver", callback_data=f"d:back:{draft_id}"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def item_assign(draft_id: int, items: list[dict], index: int,
                people: list[tuple[int, str]], assigned: list[int | None]) -> InlineKeyboardMarkup:
    """Asigna el ítem `index` a una o varias personas (o a mí)."""
    buttons = [
        InlineKeyboardButton(
            text=("✅ " if None in assigned else "▫️ ") + "Yo",
            callback_data=f"i:tog:{draft_id}:{index}:me",
        )
    ]
    buttons += [
        InlineKeyboardButton(
            text=("✅ " if pid in assigned else "▫️ ") + name[:16],
            callback_data=f"i:tog:{draft_id}:{index}:{pid}",
        )
        for pid, name in people
    ]
    rows = _rows(buttons, 2)
    nav = []
    if index > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"i:go:{draft_id}:{index - 1}"))
    nav.append(InlineKeyboardButton(text=f"{index + 1}/{len(items)}", callback_data="noop"))
    if index < len(items) - 1:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"i:go:{draft_id}:{index + 1}"))
    rows.append(nav)
    rows.append([InlineKeyboardButton(text="✔️ Calcular división", callback_data=f"i:done:{draft_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def card_actions(statements) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"💵 Pagar {s.account.name} ({money(s.to_pay)})",
                callback_data=f"c:pay:{s.account.id}:{s.period}",
            )
        ]
        for s in statements
        if s.to_pay > 0
    ]
    rows.append([InlineKeyboardButton(text="📅 Próximos meses", callback_data="c:future")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def fixed_list(pending) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"✅ Pagué {tx.description[:20]} ({money(tx.amount)})",
                callback_data=f"f:paid:{tx.id}",
            )
        ]
        for tx in pending[:10]
    ]
    rows.append([InlineKeyboardButton(text="➕ Nuevo gasto fijo", callback_data="f:new")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def debts_actions(balances) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"✅ {b.person.name} me pagó {money(b.owes_me)}",
                callback_data=f"p:settle:{b.person.id}",
            )
        ]
        for b in balances[:10]
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows or [[InlineKeyboardButton(text="Sin deudas 🎉", callback_data="noop")]])


def confirm(action: str, arg: str = "", label: str = "Confirmar") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=f"✅ {label}", callback_data=f"{action}:{arg}"),
                InlineKeyboardButton(text="❌ Cancelar", callback_data="cancel"),
            ]
        ]
    )
