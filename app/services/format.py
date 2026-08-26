"""Formato de textos y montos para Telegram y el dashboard."""
from __future__ import annotations

import datetime as dt

from app.config import settings
from app.money import D
from app.services.periods import MONTHS_ES, period_label

BAR_FULL = "█"
BAR_EMPTY = "░"


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


def bar(pct: float, width: int = 10) -> str:
    pct = max(0.0, min(100.0, pct))
    filled = round(width * pct / 100)
    return BAR_FULL * filled + BAR_EMPTY * (width - filled)


def pct(part, whole) -> float:
    part, whole = D(part), D(whole)
    if whole == 0:
        return 0.0
    return float(part / whole * 100)


def draft_summary(payload: dict, category_name: str, account_name: str,
                  people_names: list[str] | None = None) -> str:
    kind_icon = "💰" if payload["kind"] == "income" else "💸"
    kind_word = "Ingreso" if payload["kind"] == "income" else "Gasto"
    date = dt.date.fromisoformat(payload["date"])
    lines = [
        f"{kind_icon} <b>{kind_word}</b>  <code>{money(payload['amount'])}</code>",
        f"📝 {payload['description']}",
    ]
    if payload.get("merchant"):
        lines.append(f"🏪 {payload['merchant']}")
    lines.append(f"📅 {long_date_es(date)}")
    if category_name:
        lines.append(f"🏷️ {category_name}")
    if account_name:
        lines.append(f"💳 {account_name}")
    if int(payload.get("installments") or 1) > 1:
        n = int(payload["installments"])
        cuota = D(payload["amount"]) / n
        lines.append(f"🧾 Diferido a {n} meses · {money(cuota)}/mes")
    items = payload.get("items") or []
    if items:
        lines.append(f"\n🧺 <b>{len(items)} ítems detectados</b>")
        for item in items[:12]:
            lines.append(f"  • {item['name']} — {money(item['total'])}")
        if len(items) > 12:
            lines.append(f"  … y {len(items) - 12} más")
    if people_names:
        lines.append(f"\n👥 Dividido con: {', '.join(people_names)}")
    if payload.get("buffer_direction") == "use":
        lines.append(f"\n🛏️ Sale del {settings.buffer_name.lower()}")
    elif payload.get("buffer_direction") == "repay":
        lines.append(f"\n🛏️ Repone el {settings.buffer_name.lower()}")
    conf = float(payload.get("confidence") or 0)
    if conf and conf < 0.6:
        lines.append("\n⚠️ <i>No estoy muy seguro, revisa el monto.</i>")
    return "\n".join(lines)


def month_report_text(report, name: str = "") -> str:
    from app.services.reports import MonthReport

    assert isinstance(report, MonthReport)
    header = f"📊 <b>{period_label(report.period)}</b>"
    if name:
        header = f"{header} · {name}"

    available = report.available_to_spend
    icon = "🟢" if available > 0 else "🔴"
    lines = [
        header,
        "",
        f"💰 Ingresos          <code>{money(report.income_total)}</code>",
        f"🏠 Fijos             <code>{money(report.fixed_total)}</code>"
        + (f"  (pendiente {money(report.fixed_pending)})" if report.fixed_pending else ""),
        f"💳 Tarjetas a pagar  <code>{money(report.cards_due)}</code>"
        + (f"  (pagado {money(report.cards_paid)})" if report.cards_paid else ""),
        f"🛒 Variables         <code>{money(report.cash_variable)}</code>",
        "",
        f"{icon} <b>Disponible para gastar: {money(available)}</b>",
    ]
    if report.income_total > 0:
        used = pct(report.committed + report.cash_variable, report.income_total)
        lines.append(f"<code>{bar(used)}</code> {used:.0f}% del ingreso comprometido")

    if report.by_category:
        lines.append("\n🏷️ <b>Por categoría</b>")
        top = report.by_category[:8]
        biggest = top[0].amount if top else 0
        for line in top:
            share = pct(line.amount, biggest or 1)
            lines.append(f"{line.label[:22]:<24} <code>{money(line.amount):>10}</code> {bar(share, 6)}")

    if report.statements:
        lines.append("\n💳 <b>Tarjetas</b>")
        for s in report.statements:
            flag = "⚠️" if s.is_overdue else ("🔔" if 0 <= s.days_left <= 5 else "•")
            lines.append(
                f"{flag} {s.account.name}: <b>{money(s.to_pay)}</b> "
                f"vence {date_es(s.due_date)}"
            )

    if report.others_owe_me > 0:
        lines.append(f"\n🤝 Te deben <b>{money(report.others_owe_me)}</b> de gastos compartidos")

    if report.buffer and report.buffer.total > 0:
        b = report.buffer
        lines.append(
            f"\n🛏️ <b>{b.name}</b>: {money(b.available)} disponible"
            + (f" · debes reponer {money(b.debt)}" if b.debt > 0 else "")
        )
    return "\n".join(lines)
