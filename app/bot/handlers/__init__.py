"""Registro de todos los routers del bot."""
from aiogram import Router

from app.bot.handlers import (
    buffer as buffer_handlers,
    cards as cards_handlers,
    capture as capture_handlers,
    common,
    drafts,
    fixed as fixed_handlers,
    people,
    reports as reports_handlers,
    setup as setup_handlers,
)


def build_router() -> Router:
    router = Router(name="root")
    router.include_router(common.router)
    router.include_router(setup_handlers.router)
    router.include_router(reports_handlers.router)
    router.include_router(cards_handlers.router)
    router.include_router(fixed_handlers.router)
    router.include_router(buffer_handlers.router)
    router.include_router(people.router)
    router.include_router(drafts.router)
    router.include_router(capture_handlers.router)   # catch-all al final
    return router
