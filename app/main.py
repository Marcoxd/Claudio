"""Aplicación web: dashboard + webhook de Telegram."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from aiogram.types import Update
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.staticfiles import StaticFiles

from app.bot.main import create_bot, create_dispatcher, setup_commands
from app.config import settings
from app.db import init_db
from app.web.api import router as web_router

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger(__name__)

WEBHOOK_PATH = "/telegram/webhook"


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    app.state.bot = None
    app.state.dp = None
    if settings.telegram_token:
        app.state.bot = create_bot()
        app.state.dp = create_dispatcher()
        await setup_commands(app.state.bot)
        if settings.base_url.startswith("https://"):
            url = settings.base_url.rstrip("/") + WEBHOOK_PATH
            try:
                await app.state.bot.set_webhook(
                    url,
                    secret_token=settings.telegram_webhook_secret,
                    drop_pending_updates=False,
                    allowed_updates=["message", "callback_query", "edited_message"],
                )
                log.info("Webhook configurado en %s", url)
            except Exception as exc:
                log.error("No pude configurar el webhook: %s", exc)
        else:
            log.warning(
                "BASE_URL no es https, no configuro webhook. "
                "Usa `python run_bot.py` para desarrollo local."
            )
    else:
        log.warning("Sin TELEGRAM_TOKEN: solo se sirve el dashboard.")

    yield

    if app.state.bot:
        await app.state.bot.session.close()


app = FastAPI(
    title=f"{settings.app_name} — finanzas personales",
    docs_url=None,
    redoc_url=None,
    lifespan=lifespan,
)

app.mount(
    "/static",
    StaticFiles(directory=str(Path(__file__).parent / "web" / "static")),
    name="static",
)
app.include_router(web_router)


@app.post(WEBHOOK_PATH, include_in_schema=False)
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str = Header(default=""),
) -> dict:
    if x_telegram_bot_api_secret_token != settings.telegram_webhook_secret:
        raise HTTPException(status_code=403, detail="secret inválido")
    if not request.app.state.dp:
        raise HTTPException(status_code=503, detail="bot no inicializado")
    update = Update.model_validate(await request.json(), context={"bot": request.app.state.bot})
    await request.app.state.dp.feed_update(request.app.state.bot, update)
    return {"ok": True}
