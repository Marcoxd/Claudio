"""Dashboard web y API de solo lectura."""
from __future__ import annotations

import secrets
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import SessionLocal
from app.money import ZERO
from app.services import buffer as buffer_service
from app.services.cards import card_balance, future_commitments
from app.services.format import money, pct
from app.services.periods import add_months, current_period, period_label
from app.services.reports import cashflow, month_report, recent_transactions
from app.services.splits import balances

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
TEMPLATES.env.filters["money"] = money

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
    buffer_state = await buffer_service.state(session)

    cards = []
    for summary in report.statements:
        card = summary.account
        used = await card_balance(session, card)
        cards.append(
            {
                "name": card.name,
                "to_pay": summary.to_pay,
                "charges": summary.charges,
                "paid": summary.paid,
                "others": summary.others_share,
                "cut": summary.cut_date,
                "due": summary.due_date,
                "days_left": summary.days_left,
                "overdue": summary.is_overdue,
                "limit": card.credit_limit,
                "used": used,
                "used_pct": pct(used, card.credit_limit) if card.credit_limit else None,
                "future": await future_commitments(session, card, period, months=6),
            }
        )

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
        "categories": categories,
        "flow": flow,
        "debts": debts,
        "recent": recent,
        "buffer": buffer_state,
        "chart": _line_chart(flow),
        "token": token,
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
