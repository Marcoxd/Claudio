#!/usr/bin/env python3
"""Conversa con el bot sin Telegram, para probarlo o para hacer una demo.

Levanta el bot de verdad —los mismos routers, middlewares y estados— con una
sesión de Telegram simulada. Lo que escribes entra como un mensaje real.

    python scripts/simular.py                 # conversación interactiva
    python scripts/simular.py --guion         # una demo de corrido
    python scripts/simular.py --base demo.db  # sobre otra base

Sin GEMINI_API_KEY interpreta el texto con el parser de reglas; las fotos y
las notas de voz no se pueden simular.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import os
import re
import sys
from typing import Any

GRIS, AZUL, VERDE, NEGRITA, FIN = "\033[90m", "\033[94m", "\033[32m", "\033[1m", "\033[0m"

USUARIO = 424242
GUION = [
    "/start",
    "almuerzo 12.50 con la visa",
    "gasolina 25",
    "tv 899 diferido a 12 meses con la visa",
    "me pagaron 450 de asesoría",
    "/resumen",
    "/corte",
    "/diferidos",
    "/tarjetas",
]


def _limpiar(html: str) -> str:
    texto = re.sub(r"<br\s*/?>", "\n", html or "")
    texto = re.sub(r"</?(b|i|u|s|code|pre|a|tg-spoiler)[^>]*>", "", texto)
    return (
        texto.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
    )


def _pintar_bot(texto: str, botones: list[list[str]] | None) -> None:
    print(f"\n{VERDE}┌ bot{FIN}")
    for linea in _limpiar(texto).split("\n"):
        print(f"{VERDE}│{FIN} {linea}")
    if botones:
        for fila in botones:
            print(f"{VERDE}│{FIN} {GRIS}[ " + " ] [ ".join(fila) + f" ]{FIN}")
    print(f"{VERDE}└{FIN}")


class SesionFalsa:
    """Intercepta las llamadas a la API de Telegram y las imprime."""

    def __init__(self) -> None:
        self.contador = 1000
        self.ultimo_teclado: list[list[Any]] | None = None
        self.mensajes: dict[int, Any] = {}
        self.silencio = False

    async def __call__(self, bot, method, timeout=None):
        return await self.make_request(bot, method, timeout)

    async def make_request(self, bot, method, timeout=None):
        from aiogram.types import Chat, Message, User

        nombre = type(method).__name__
        self.contador += 1

        if nombre in ("SendMessage", "SendDocument", "EditMessageText"):
            texto = getattr(method, "text", None) or getattr(method, "caption", "") or ""
            if nombre == "SendDocument":
                doc = getattr(method, "document", None)
                texto = f"[archivo: {getattr(doc, 'filename', 'documento')}] {texto}"
            markup = getattr(method, "reply_markup", None)
            botones = None
            if markup is not None and getattr(markup, "inline_keyboard", None):
                botones = [[b.text for b in fila] for fila in markup.inline_keyboard]
                self.ultimo_teclado = markup.inline_keyboard
            if not self.silencio:
                _pintar_bot(texto, botones)
            mensaje = Message(
                message_id=self.contador,
                date=dt.datetime.now(),
                chat=Chat(id=USUARIO, type="private"),
                from_user=User(id=1, is_bot=True, first_name="Bot"),
                text=_limpiar(texto)[:4000],
            )
            self.mensajes[self.contador] = mensaje
            return mensaje

        if nombre in ("EditMessageReplyMarkup",):
            markup = getattr(method, "reply_markup", None)
            if markup is not None and getattr(markup, "inline_keyboard", None):
                self.ultimo_teclado = markup.inline_keyboard
                if not self.silencio:
                    print(f"{VERDE}│{FIN} {GRIS}[ " + " ] [ ".join(
                        b.text for fila in markup.inline_keyboard for b in fila
                    ) + f" ]{FIN}")
            return True

        if nombre == "AnswerCallbackQuery":
            aviso = getattr(method, "text", None)
            if aviso and not self.silencio:
                print(f"{GRIS}   ↑ {aviso}{FIN}")
            return True

        if nombre == "GetMe":
            return User(id=1, is_bot=True, first_name="Kuri", username="kuri_bot")

        return True

    async def stream_content(self, *a, **k):
        if False:
            yield b""

    async def close(self):
        return None


async def _enviar(dp, bot, sesion, texto: str) -> None:
    from aiogram.types import Chat, Message, Update, User

    sesion.contador += 1
    actualizacion = Update(
        update_id=sesion.contador,
        message=Message(
            message_id=sesion.contador,
            date=dt.datetime.now(),
            chat=Chat(id=USUARIO, type="private"),
            from_user=User(id=USUARIO, is_bot=False, first_name="Marco"),
            text=texto,
        ),
    )
    await dp.feed_update(bot, actualizacion)


async def _tocar(dp, bot, sesion, indice: int) -> None:
    """Pulsa el botón número `indice` (1-based) del último teclado."""
    from aiogram.types import CallbackQuery, Update, User

    planos = [b for fila in (sesion.ultimo_teclado or []) for b in fila]
    if not 1 <= indice <= len(planos):
        print(f"{GRIS}   (no hay botón {indice}){FIN}")
        return
    boton = planos[indice - 1]
    print(f"{AZUL}› [{boton.text}]{FIN}")
    sesion.contador += 1
    mensaje = list(sesion.mensajes.values())[-1] if sesion.mensajes else None
    actualizacion = Update(
        update_id=sesion.contador,
        callback_query=CallbackQuery(
            id=str(sesion.contador),
            from_user=User(id=USUARIO, is_bot=False, first_name="Marco"),
            chat_instance="sim",
            data=boton.callback_data,
            message=mensaje,
        ),
    )
    await dp.feed_update(bot, actualizacion)


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="data/simulacion.db")
    parser.add_argument("--guion", action="store_true", help="corre una demo de corrido")
    parser.add_argument("--limpiar", action="store_true", help="empieza de cero")
    args = parser.parse_args()

    if args.limpiar and os.path.exists(args.base):
        os.remove(args.base)
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///./{args.base}"
    os.environ.setdefault("TELEGRAM_TOKEN", "0:simulado")
    os.environ.setdefault("ALLOWED_USER_IDS", str(USUARIO))

    from aiogram import Bot
    from aiogram.client.default import DefaultBotProperties
    from aiogram.enums import ParseMode

    from app.bot.main import create_dispatcher
    from app.config import settings
    from app.db import init_db

    await init_db()
    sesion = SesionFalsa()
    bot = Bot(token="0:simulado",
              default=DefaultBotProperties(parse_mode=ParseMode.HTML),
              session=sesion)
    dp = create_dispatcher()

    modo = "Gemini" if settings.ai_enabled else "reglas locales (sin GEMINI_API_KEY)"
    print(f"\n{NEGRITA}Simulador de {settings.app_name}{FIN}  {GRIS}base {args.base} · "
          f"interpretación: {modo}{FIN}")

    if args.guion:
        for texto in GUION:
            print(f"\n{AZUL}› {texto}{FIN}")
            await _enviar(dp, bot, sesion, texto)
            if texto.startswith(("almuerzo", "gasolina", "tv ", "me pagaron")):
                await _tocar(dp, bot, sesion, 1)   # Guardar
        print(f"\n{GRIS}Fin de la demo.{FIN}\n")
        return 0

    print(f"{GRIS}Escribe como si fuera Telegram. «1», «2»… pulsan los botones. "
          f"«salir» termina.{FIN}")
    while True:
        try:
            entrada = input(f"\n{AZUL}› {FIN}").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not entrada:
            continue
        if entrada.lower() in ("salir", "exit", "quit"):
            break
        if entrada.isdigit():
            await _tocar(dp, bot, sesion, int(entrada))
        else:
            await _enviar(dp, bot, sesion, entrada)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
