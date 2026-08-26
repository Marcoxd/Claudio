"""Resumen del mes, consultas libres y exportación."""
from __future__ import annotations

import csv
import io

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.services import ai
from app.services.dashboard_link import dashboard_url
from app.services.format import money, month_report_text
from app.services.periods import add_months, current_period, period_label
from app.services.reports import month_report

router = Router(name="reports")


@router.message(Command("resumen"))
@router.message(F.text == "📊 Resumen")
async def cmd_summary(message: Message, session: AsyncSession) -> None:
    report = await month_report(session, current_period())
    await message.answer(
        month_report_text(report, settings.owner_name)
        + f"\n\n📈 <a href=\"{dashboard_url()}\">Ver el panel completo</a>",
        disable_web_page_preview=True,
    )


@router.message(Command("mes"))
async def cmd_month(message: Message, session: AsyncSession) -> None:
    parts = (message.text or "").split()
    period = parts[1] if len(parts) > 1 else add_months(current_period(), -1)
    try:
        report = await month_report(session, period, materialize=period == current_period())
    except Exception:
        await message.answer("Uso: <code>/mes 2026-07</code>")
        return
    await message.answer(month_report_text(report))


@router.message(Command("pregunta"))
async def cmd_ask(message: Message, session: AsyncSession) -> None:
    question = (message.text or "").partition(" ")[2].strip()
    if not question:
        await message.answer(
            "Pregúntame algo sobre tus finanzas:\n"
            "<code>/pregunta ¿en qué se me fue la plata este mes?</code>"
        )
        return
    report = await month_report(session, current_period())
    context = "\n".join(
        [
            f"Mes: {period_label(report.period)}",
            f"Ingresos: {money(report.income_total)}",
            f"Gastos fijos: {money(report.fixed_total)} (pendiente {money(report.fixed_pending)})",
            f"Tarjetas a pagar este mes: {money(report.cards_due)}",
            f"Gastos variables pagados: {money(report.cash_variable)}",
            f"Compras con tarjeta del mes: {money(report.card_charged)}",
            f"Disponible para gastar: {money(report.available_to_spend)}",
            f"Me deben: {money(report.others_owe_me)}",
            "Por categoría: "
            + ", ".join(f"{c.name} {money(c.amount)}" for c in report.by_category[:12]),
            "Tarjetas: "
            + "; ".join(
                f"{s.account.name} debe {money(s.to_pay)} vence {s.due_date}"
                for s in report.statements
            ),
        ]
    )
    thinking = await message.answer("🤔 Revisando tus números…")
    answer = await ai.answer_question(question, context)
    await thinking.edit_text(answer)


@router.message(Command("exportar"))
async def cmd_export(message: Message, session: AsyncSession) -> None:
    """Exporta el mes a CSV para abrirlo en Excel."""
    parts = (message.text or "").split()
    period = parts[1] if len(parts) > 1 else current_period()
    report = await month_report(session, period, materialize=period == current_period())

    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow(
        ["Fecha", "Tipo", "Estado", "Descripción", "Comercio", "Categoría",
         "Medio de pago", "Total", "Mi parte", "Cuotas", "Origen"]
    )
    for tx in report.transactions:
        writer.writerow(
            [
                tx.date.isoformat(),
                "Ingreso" if tx.kind == "income" else "Gasto",
                "Pendiente" if tx.status == "planned" else "Hecho",
                tx.description,
                tx.merchant or "",
                tx.category.name if tx.category else "",
                tx.account.name if tx.account else "",
                f"{tx.amount:.2f}",
                f"{tx.effective_amount():.2f}",
                tx.installments_total,
                tx.source,
            ]
        )
    data = buffer.getvalue().encode("utf-8-sig")
    await message.answer_document(
        BufferedInputFile(data, filename=f"gastos-{period}.csv"),
        caption=f"📄 {period_label(period)} · {len(report.transactions)} movimientos",
    )
