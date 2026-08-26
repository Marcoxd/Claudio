"""Formato de textos y montos para Telegram y el dashboard."""
from __future__ import annotations

import datetime as dt

from app.config import settings
from app.money import D
from app.services.periods import MONTHS_ES, period_label

def money(value, sign: bool = False) -> str:
    v = D(value)
    text = f"{abs(v):,.2f}"
    if settings.locale_decimal_comma:
        text = text.replace(",", "_").replace(".", ",").replace("_", ".")
    prefix = "-" if v < 0 else ("+" if sign and v > 0 else "")
    return f"{prefix}{settings.currency_symbol}{text}"


def date_es(value: dt.date) -> str:
    return f"{value.day} {MONTHS_ES[value.month - 1][:3]}"


def long_date_es(value: dt.date) -> str:
    return f"{value.day} de {MONTHS_ES[value.month - 1]} de {value.year}"


def pct(part, whole) -> float:
    part, whole = D(part), D(whole)
    if whole == 0:
        return 0.0
    return float(part / whole * 100)


def row(label: str, value: str, width: int = 30) -> str:
    """Fila alineada en monoespaciado para Telegram."""
    label = label[: width - len(value) - 2]
    return f"{label}{' ' * max(1, width - len(label) - len(value))}{value}"


def period_short(period: str) -> str:
    """'2026-09' → 'sep 26'."""
    year, month = period.split("-")
    return f"{MONTHS_ES[int(month) - 1][:3]} {year[2:]}"


def block(rows: list[str]) -> str:
    """Bloque monoespaciado (Telegram alinea las columnas dentro de <pre>)."""
    return "<pre>" + "\n".join(rows) + "</pre>"


def placement_text(placement, account_name: str = "") -> str:
    """Explica en qué corte cae una compra con tarjeta."""
    if placement is None:
        return ""
    if placement.is_deferred:
        return (
            f"{placement.count} cuotas de {money(placement.installment_amount)}, "
            f"del corte de {period_label(placement.period).lower()} "
            f"al de {period_label(placement.last_period).lower()}.\n"
            f"La primera la pagas el {date_es(placement.due_date)}."
        )
    return (
        f"Va al corte del {date_es(placement.cut_date)}"
        f"{f' de {account_name}' if account_name else ''}, "
        f"lo pagas el {date_es(placement.due_date)}."
    )


def draft_summary(payload: dict, category_name: str, account_name: str,
                  people_names: list[str] | None = None) -> str:
    kind_word = "Ingreso" if payload["kind"] == "income" else "Gasto"
    date = dt.date.fromisoformat(payload["date"])

    lines = [
        f"<b>{payload['description']}</b>",
        f"<b>{money(payload['amount'])}</b> · {kind_word.lower()}",
        "",
    ]
    detail = []
    if payload.get("merchant"):
        detail.append(payload["merchant"])
    detail.append(long_date_es(date))
    if category_name:
        detail.append(category_name)
    if account_name:
        detail.append(account_name)
    lines.append(" · ".join(detail))

    if payload.get("placement"):
        lines += ["", payload["placement"]]
    elif int(payload.get("installments") or 1) > 1:
        n = int(payload["installments"])
        lines.append(f"Diferido a {n} meses · {money(D(payload['amount']) / n)} al mes")

    items = payload.get("items") or []
    if items:
        lines.append("")
        lines.append(f"<b>{len(items)} ítems</b>")
        lines.append(
            block([row(i["name"][:22], money(i["total"]), 32) for i in items[:12]])
        )
        if len(items) > 12:
            lines.append(f"…y {len(items) - 12} más")

    if people_names:
        lines.append("")
        quienes = ", ".join(people_names)
        if payload.get("include_me", True):
            partes = len(people_names) + 1
            lines.append(
                f"Dividido con {quienes} · te tocan "
                f"{money(D(payload['amount']) / partes)}"
            )
        else:
            lines.append(f"Es de {quienes}: lo pagaste tú, pero no es gasto tuyo.")

    if payload.get("buffer_direction") == "use":
        lines.append(f"\nSale del {settings.buffer_name.lower()}")
    elif payload.get("buffer_direction") == "repay":
        lines.append(f"\nRepone el {settings.buffer_name.lower()}")

    conf = float(payload.get("confidence") or 0)
    if conf and conf < 0.6:
        lines.append("\n<i>No estoy seguro del monto, revísalo.</i>")
    return "\n".join(lines)


def month_report_text(report, name: str = "") -> str:
    from app.services.reports import MonthReport

    assert isinstance(report, MonthReport)
    available = report.available_to_spend

    lines = [
        f"<b>{period_label(report.period)}</b>" + (f" · {name}" if name else ""),
        "",
        "Te queda para gastar",
        f"<b>{money(available)}</b>",
        "",
        block(
            [
                row("Ingresos", money(report.income_total)),
                row("Fijos", money(report.fixed_total)),
                row("Tarjetas", money(report.cards_due)),
                row("Variables", money(report.cash_variable)),
            ]
        ),
    ]
    if report.fixed_pending > 0:
        lines.append(f"<i>Te faltan {money(report.fixed_pending)} de fijos por pagar.</i>")
    if report.card_charged != report.cards_due:
        lines.append(
            f"<i>Compraste {money(report.card_charged)} con tarjeta este mes; "
            f"eso cae en cortes posteriores.</i>"
        )

    if report.by_category:
        lines += [
            "",
            "<b>En qué se te va</b>",
            block([row(c.name, money(c.amount)) for c in report.by_category[:8]]),
        ]

    pendientes = [s for s in report.statements if s.to_pay > 0]
    if pendientes:
        lines += ["", "<b>Tarjetas</b>"]
        for s in pendientes:
            if s.is_overdue:
                when = f"venció el {date_es(s.due_date)}"
            elif s.days_left == 0:
                when = "vence hoy"
            else:
                when = f"vence {date_es(s.due_date)}"
            lines.append(f"{s.account.name} · <b>{money(s.to_pay)}</b> · {when}")

    if report.others_owe_me > 0:
        lines += ["", f"Te deben <b>{money(report.others_owe_me)}</b> de gastos compartidos."]

    if report.buffer and report.buffer.total > 0:
        b = report.buffer
        text = f"{b.name}: <b>{money(b.available)}</b> disponible"
        if b.debt > 0:
            text += f", te falta reponer {money(b.debt)}"
        lines += ["", text]
    return "\n".join(lines)
