"""Construcción del bot y del dispatcher."""
from __future__ import annotations

import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from app.bot.handlers import build_router
from app.bot.middlewares import AuthMiddleware, DbSessionMiddleware
from app.config import settings

log = logging.getLogger(__name__)

COMMANDS = [
    BotCommand(command="resumen", description="Cómo va el mes"),
    BotCommand(command="tarjetas", description="Cortes, cuotas y cuánto pagar"),
    BotCommand(command="corte", description="En qué mes cae lo que compres hoy"),
    BotCommand(command="diferidos", description="Cuánto falta de cada compra a cuotas"),
    BotCommand(command="fijos", description="Gastos fijos del mes"),
    BotCommand(command="deudas", description="Quién te debe"),
    BotCommand(command="colchon", description="El dinero que no es tuyo"),
    BotCommand(command="panel", description="Abrir el dashboard"),
    BotCommand(command="pregunta", description="Preguntar sobre tus finanzas"),
    BotCommand(command="exportar", description="Descargar el mes en CSV"),
    BotCommand(command="setup", description="Configurar el bot"),
    BotCommand(command="ayuda", description="Ejemplos de uso"),
]


def create_bot() -> Bot:
    if not settings.telegram_token:
        raise RuntimeError("Falta TELEGRAM_TOKEN")
    return Bot(
        token=settings.telegram_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


def create_dispatcher() -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())
    dp.update.outer_middleware(DbSessionMiddleware())
    dp.update.outer_middleware(AuthMiddleware())
    dp.include_router(build_router())
    return dp


async def setup_commands(bot: Bot) -> None:
    try:
        await bot.set_my_commands(COMMANDS)
    except Exception as exc:
        log.warning("No pude registrar los comandos: %s", exc)


async def run_polling() -> None:
    """Modo local: sin webhook, ideal para desarrollo."""
    from app.db import init_db

    logging.basicConfig(level=settings.log_level)
    await init_db()
    bot = create_bot()
    dp = create_dispatcher()
    await bot.delete_webhook(drop_pending_updates=True)
    await setup_commands(bot)
    log.info("%s escuchando (polling)…", settings.app_name)
    await dp.start_polling(bot)
