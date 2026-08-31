"""Dashboard web y API de solo lectura."""
from __future__ import annotations

import csv
import datetime as dt
import io
import secrets
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import SessionLocal
from app.services import ai
from app.services.capture import _match_account, _match_category, build_context
from app.models import (
    ACCOUNT_CREDIT,
    KIND_EXPENSE,
    KIND_INCOME,
    Account,
    Category,
    FixedExpense,
    Transaction,
)
from app.money import D, ZERO
from app.services import buffer as buffer_service
from app.services.cards import (
    build_installments,
    card_balance,
    cut_day_of,
    deferred_purchases,
    future_commitments,
    place_purchase,
    statement_window,
)
from app.services.format import money, pct, period_short
from app.services.periods import add_months, current_period, period_label, period_of, today
from app.services.reports import cashflow, month_report, recent_transactions
from app.services.splits import balances

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
TEMPLATES.env.filters["money"] = money
TEMPLATES.env.filters["mes"] = period_short

router = APIRouter()

COOKIE = "panel_token"


async def get_session() -> AsyncSession:
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


def check_token(request: Request, t: str | None = Query(default=None)) -> str:
    provided = t or request.cookies.get(COOKIE, "")
    if not secrets.compare_digest(provided, settings.dashboard_token):
        raise HTTPException(status_code=401, detail="Enlace no válido")
    return provided


@router.get("/health")
async def health() -> dict:
    return {"ok": True, "app": settings.app_name}


@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    response: Response,
    period: str | None = None,
    token: str = Depends(check_token),
    session: AsyncSession = Depends(get_session),
):
    period = period or current_period()
    report = await month_report(session, period)
    flow = await cashflow(session, months=6, end=period)
    debts = await balances(session)
    recent = await recent_transactions(session, limit=25)
    statement_of = {
        tx.id: tx.installments[0].statement_period for tx in recent if tx.installments
    }
    buffer_state = await buffer_service.state(session)

    cards = []
    for summary in report.statements:
        card = summary.account
        used = await card_balance(session, card)
        window = statement_window(summary.period, cut_day_of(card))
        hoy = place_purchase(card, today(), ZERO, 1)
        cards.append(
            {
                "name": card.name,
                "to_pay": summary.to_pay,
                "charges": summary.charges,
                "paid": summary.paid,
                "others": summary.others_share,
                "cut": summary.cut_date,
                "due": summary.due_date,
                "cut_day": card.cut_day,
                "due_day": card.due_day,
                "window": window,
                "days_left": summary.days_left,
                "overdue": summary.is_overdue,
                "limit": card.credit_limit,
                "used": used,
                "used_pct": pct(used, card.credit_limit) if card.credit_limit else None,
                "future": await future_commitments(session, card, period, months=6),
                "today_cut": hoy.cut_date if hoy else None,
                "today_due": hoy.due_date if hoy else None,
                "movements": [
                    {
                        "date": i.transaction.date if i.transaction else summary.cut_date,
                        "label": (i.transaction.description if i.transaction else "Movimiento"),
                        "installment": f"{i.number}/{i.count}" if i.count > 1 else "",
                        "amount": i.amount,
                    }
                    for i in summary.installments
                ],
            }
        )

    diferidos = [
        {
            "label": d.transaction.description,
            "card": d.account.name,
            "paid": d.paid,
            "count": d.count,
            "installment": d.installment,
            "remaining": d.remaining_amount,
            "total": d.total,
            "pct": pct(d.paid, d.count),
        }
        for d in await deferred_purchases(session, period)
    ]

    categories_all = (
        await session.execute(select(Category).order_by(Category.kind, Category.name))
    ).scalars().all()
    accounts_all = (
        await session.execute(
            select(Account).where(Account.active.is_(True)).order_by(Account.name)
        )
    ).scalars().all()

    top = report.by_category[:10]
    biggest = top[0].amount if top else ZERO
    categories = [
        {
            "label": c.name,
            "amount": c.amount,
            "pct": pct(c.amount, biggest or 1),
            "share": pct(c.amount, report.real_expenses or 1),
            "essential": c.essential,
        }
        for c in top
    ]

    context = {
        "request": request,
        "app_name": settings.app_name,
        "tagline": settings.app_tagline,
        "owner": settings.owner_name,
        "period": period,
        "period_label": period_label(period),
        "prev_period": add_months(period, -1),
        "next_period": add_months(period, 1),
        "is_current": period == current_period(),
        "r": report,
        "cards": cards,
        "deferred": diferidos,
        "categories": categories,
        "flow": flow,
        "debts": debts,
        "recent": recent,
        "statement_of": statement_of,
        "buffer": buffer_state,
        "chart": _line_chart(flow),
        "token": token,
        "today_iso": today().isoformat(),
        "current_year": today().year,
        "app_version": settings.app_version,
        "all_categories": categories_all,
        "all_accounts": accounts_all,
    }
    context.pop("request", None)
    page = TEMPLATES.TemplateResponse(request, "dashboard.html", context)
    page.set_cookie(COOKIE, token, httponly=True, samesite="lax", max_age=60 * 60 * 24 * 365)
    return page


@router.get("/api/resumen")
async def api_summary(
    period: str | None = None,
    token: str = Depends(check_token),
    session: AsyncSession = Depends(get_session),
) -> dict:
    period = period or current_period()
    r = await month_report(session, period)
    return {
        "period": period,
        "ingresos": float(r.income_total),
        "fijos": float(r.fixed_total),
        "tarjetas_a_pagar": float(r.cards_due),
        "variables": float(r.cash_variable),
        "disponible": float(r.available_to_spend),
        "gasto_real": float(r.real_expenses),
        "me_deben": float(r.others_owe_me),
        "colchon": {
            "total": float(r.buffer.total),
            "disponible": float(r.buffer.available),
            "por_reponer": float(r.buffer.debt),
        }
        if r.buffer
        else None,
        "por_categoria": [
            {"categoria": c.name, "monto": float(c.amount)} for c in r.by_category
        ],
        "tarjetas": [
            {
                "nombre": s.account.name,
                "a_pagar": float(s.to_pay),
                "vence": s.due_date.isoformat(),
            }
            for s in r.statements
        ],
    }


@router.post("/tareas/recordatorios")
@router.get("/tareas/recordatorios")
async def run_reminders(
    token: str = Depends(check_token),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Llamado por un cron externo (p. ej. cron-job.org) una vez al día.

    Manda por Telegram los avisos de tarjetas por vencer y fijos pendientes.
    De paso mantiene despierto el servicio en planes gratuitos.
    """
    from app.bot.middlewares import get_owner_id
    from app.services.reminders import build_reminder

    text = await build_reminder(session)
    if not text:
        return {"sent": False, "reason": "nada que avisar"}

    owner = await get_owner_id(session)
    targets = sorted(settings.allowed_ids | ({owner} if owner else set()))
    if not targets:
        return {"sent": False, "reason": "sin destinatarios"}

    from app.bot.main import create_bot

    bot = create_bot()
    try:
        for chat_id in targets:
            await bot.send_message(chat_id, text)
    finally:
        await bot.session.close()
    return {"sent": True, "targets": len(targets)}


def _redirect_to(period: str | None, token: str) -> RedirectResponse:
    url = f"/?t={token}" + (f"&period={period}" if period else "")
    return RedirectResponse(url, status_code=303)


@router.post("/tarjetas/nueva")
async def create_card(
    period: str | None = Form(default=None),
    name: str = Form(...),
    cut_day: int = Form(...),
    due_day: int = Form(...),
    credit_limit: str = Form(default=""),
    token: str = Depends(check_token),
    session: AsyncSession = Depends(get_session),
) -> RedirectResponse:
    limit = D(credit_limit) if credit_limit.strip() else None
    session.add(
        Account(
            name=name.strip()[:64],
            type=ACCOUNT_CREDIT,
            cut_day=max(1, min(31, cut_day)),
            due_day=max(1, min(31, due_day)),
            credit_limit=limit,
        )
    )
    await session.flush()
    return _redirect_to(period, token)


@router.post("/fijos/nuevo")
async def create_fixed(
    period: str | None = Form(default=None),
    name: str = Form(...),
    amount: str = Form(...),
    due_day: int = Form(...),
    category_id: str = Form(default=""),
    account_id: str = Form(default=""),
    token: str = Depends(check_token),
    session: AsyncSession = Depends(get_session),
) -> RedirectResponse:
    session.add(
        FixedExpense(
            name=name.strip()[:96],
            amount=D(amount),
            due_day=max(1, min(31, due_day)),
            category_id=int(category_id) if category_id else None,
            account_id=int(account_id) if account_id else None,
            start_period=period or current_period(),
        )
    )
    await session.flush()
    return _redirect_to(period, token)


@router.post("/movimientos/nuevo")
async def create_transaction(
    period: str | None = Form(default=None),
    kind: str = Form(...),
    date: str = Form(...),
    description: str = Form(...),
    amount: str = Form(...),
    category_id: str = Form(default=""),
    account_id: str = Form(default=""),
    installments: int = Form(default=1),
    token: str = Depends(check_token),
    session: AsyncSession = Depends(get_session),
) -> RedirectResponse:
    parsed_date = dt.date.fromisoformat(date)
    account = await session.get(Account, int(account_id)) if account_id else None
    kind = KIND_INCOME if kind == "income" else KIND_EXPENSE

    tx = Transaction(
        kind=kind,
        date=parsed_date,
        amount=D(amount),
        description=description.strip()[:255],
        category_id=int(category_id) if category_id else None,
        account_id=account.id if account else None,
        period=period_of(parsed_date),
        installments_total=max(1, installments) if kind == KIND_EXPENSE else 1,
        source="manual",
    )
    session.add(tx)
    await session.flush()

    if account and account.type == ACCOUNT_CREDIT and kind == KIND_EXPENSE:
        for inst in build_installments(tx, account, tx.installments_total):
            session.add(inst)
        await session.flush()

    return _redirect_to(period, token)


@router.post("/movimientos/{transaction_id}/borrar")
async def delete_transaction(
    transaction_id: int,
    period: str | None = Form(default=None),
    token: str = Depends(check_token),
    session: AsyncSession = Depends(get_session),
) -> RedirectResponse:
    tx = await session.get(Transaction, transaction_id)
    if tx is not None:
        await session.delete(tx)
        await session.flush()
    return _redirect_to(period, token)


@router.post("/movimientos/{transaction_id}/categoria")
async def update_transaction_category(
    transaction_id: int,
    category_id: int | None = Form(default=None),
    period: str | None = Form(default=None),
    token: str = Depends(check_token),
    session: AsyncSession = Depends(get_session),
) -> RedirectResponse:
    tx = await session.get(Transaction, transaction_id)
    if tx is not None:
        tx.category_id = category_id if category_id and category_id > 0 else None
        await session.flush()
    return _redirect_to(period, token)


@router.get("/exportar")
async def export_transactions(
    tipo: str = Query(default="mes"),
    period: str | None = Query(default=None),
    date: str | None = Query(default=None),
    year: int | None = Query(default=None),
    token: str = Depends(check_token),
    session: AsyncSession = Depends(get_session),
) -> Response:
    stmt = select(Transaction).order_by(Transaction.date.asc(), Transaction.id.asc())

    if tipo in ("dia", "day", "date") and date:
        try:
            d = dt.date.fromisoformat(date)
            stmt = stmt.where(Transaction.date == d)
            filename = f"movimientos_{date}.csv"
        except ValueError:
            raise HTTPException(status_code=400, detail="Formato de fecha inválido")
    elif tipo in ("ano", "año", "year") and year:
        start_d = dt.date(year, 1, 1)
        end_d = dt.date(year, 12, 31)
        stmt = stmt.where(Transaction.date >= start_d, Transaction.date <= end_d)
        filename = f"movimientos_{year}.csv"
    elif tipo in ("todo", "all"):
        filename = f"movimientos_todo_{today().isoformat()}.csv"
    else:  # mes
        p = period or current_period()
        stmt = stmt.where(Transaction.period == p)
        filename = f"movimientos_{p}.csv"

    rows = (await session.execute(stmt)).scalars().all()

    output = io.StringIO()
    output.write("\ufeff")  # BOM UTF-8 para compatibilidad nativa con Excel
    writer = csv.writer(output, delimiter=";", quoting=csv.QUOTE_MINIMAL)

    writer.writerow([
        "ID",
        "Fecha",
        "Tipo",
        "Descripción",
        "Monto Total ($)",
        "Mi Parte ($)",
        "Categoría",
        "Medio de Pago",
        "Cuotas",
        "Comercio",
        "Período",
        "Notas",
    ])

    for t in rows:
        tipo_str = "Gasto" if t.kind == KIND_EXPENSE else "Ingreso"
        cat_str = t.category.name if t.category else ""
        acc_str = t.account.name if t.account else ""
        mi_parte = float(t.my_share) if t.my_share is not None else float(t.amount)
        writer.writerow([
            t.id,
            t.date.isoformat(),
            tipo_str,
            t.description,
            f"{float(t.amount):.2f}",
            f"{mi_parte:.2f}",
            cat_str,
            acc_str,
            t.installments_total,
            t.merchant or "",
            t.period,
            t.notes or "",
        ])

    csv_bytes = output.getvalue().encode("utf-8-sig")
    return Response(
        content=csv_bytes,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-cache",
        },
    )


@router.post("/api/scan")
async def scan_receipt(
    file: UploadFile = File(...),
    token: str = Depends(check_token),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Escanea una imagen o PDF de factura con Gemini y devuelve los campos para autocompletar el formulario."""
    mime_type = file.content_type or "image/jpeg"
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Archivo vacío")

    ctx = await build_context(session)
    parsed = await ai.parse_document(data, mime_type, ctx)

    cat_id = await _match_category(session, parsed.category, parsed.kind)
    acc_id = await _match_account(session, parsed.account)

    return {
        "ok": True,
        "kind": parsed.kind,
        "amount": float(parsed.amount),
        "description": parsed.description or parsed.merchant or "Compra",
        "merchant": parsed.merchant or "",
        "date": parsed.date or today().isoformat(),
        "category_id": cat_id,
        "account_id": acc_id,
        "installments": parsed.installments or 1,
        "notes": parsed.notes or "",
        "items": [
            {
                "name": it.name,
                "quantity": it.quantity,
                "unit_price": it.unit_price,
                "total": it.total,
            }
            for it in parsed.items
        ],
    }


@router.get("/salir")
async def logout() -> RedirectResponse:
    response = RedirectResponse("/")
    response.delete_cookie(COOKIE)
    return response


# ------------------------------------------------------------------ gráfico


def _line_chart(flow: list[dict], width: int = 720, height: int = 220) -> dict:
    """Geometría del gráfico de ingresos vs gastos (SVG renderizado en la plantilla)."""
    pad_l, pad_r, pad_t, pad_b = 8, 8, 16, 28
    inner_w = width - pad_l - pad_r
    inner_h = height - pad_t - pad_b
    if not flow:
        return {"width": width, "height": height, "points": [], "grid": [], "max": 0}

    top = max([max(row["income"], row["expenses"]) for row in flow] + [1])
    step = inner_w / max(1, len(flow) - 1) if len(flow) > 1 else inner_w

    def y(value: float) -> float:
        return pad_t + inner_h - (value / top) * inner_h

    points = []
    for i, row in enumerate(flow):
        x = pad_l + i * step
        points.append(
            {
                "x": round(x, 1),
                "income_y": round(y(row["income"]), 1),
                "expense_y": round(y(row["expenses"]), 1),
                "label": period_label(row["period"]).split(" ")[0][:3],
                "period": row["period"],
                "income": row["income"],
                "expenses": row["expenses"],
                "net": row["net"],
            }
        )

    grid = [
        {"y": round(y(top * f), 1), "value": top * f}
        for f in (0, 0.5, 1.0)
    ]
    return {
        "width": width,
        "height": height,
        "points": points,
        "grid": grid,
        "max": top,
        "income_path": " ".join(
            f"{'M' if i == 0 else 'L'}{p['x']},{p['income_y']}" for i, p in enumerate(points)
        ),
        "expense_path": " ".join(
            f"{'M' if i == 0 else 'L'}{p['x']},{p['expense_y']}" for i, p in enumerate(points)
        ),
        "baseline": round(y(0), 1),
    }
