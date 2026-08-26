#!/usr/bin/env python3
"""Revisa que todo esté listo antes de arrancar el bot.

    python scripts/verificar.py

Comprueba la configuración, que el token de Telegram sea válido, que la clave
de Gemini responda y que la base de datos esté accesible. Dice exactamente qué
falta y cómo conseguirlo.
"""
from __future__ import annotations

import asyncio
import sys

VERDE, ROJO, AMARILLO, GRIS, FIN = "\033[32m", "\033[31m", "\033[33m", "\033[90m", "\033[0m"

problemas: list[str] = []


def ok(texto: str, detalle: str = "") -> None:
    print(f"  {VERDE}✓{FIN} {texto}" + (f" {GRIS}{detalle}{FIN}" if detalle else ""))


def falla(texto: str, arreglo: str) -> None:
    print(f"  {ROJO}✗{FIN} {texto}")
    print(f"    {GRIS}→ {arreglo}{FIN}")
    problemas.append(texto)


def aviso(texto: str, detalle: str = "") -> None:
    print(f"  {AMARILLO}!{FIN} {texto}" + (f" {GRIS}{detalle}{FIN}" if detalle else ""))


async def revisar_telegram(token: str) -> None:
    if not token:
        falla(
            "Falta TELEGRAM_TOKEN",
            "Habla con @BotFather en Telegram, /newbot, y pega el token en .env",
        )
        return
    import httpx

    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(f"https://api.telegram.org/bot{token}/getMe")
        datos = r.json()
        if datos.get("ok"):
            bot = datos["result"]
            ok("Telegram responde", f"@{bot['username']} · {bot['first_name']}")
        else:
            falla(
                f"Telegram rechazó el token ({datos.get('description')})",
                "Revisa que lo hayas copiado completo, sin espacios",
            )
    except Exception as exc:
        falla(
            f"No pude hablar con Telegram: {exc.__class__.__name__}",
            f"{str(exc)[:100]} — revisa tu conexión, o el proxy si estás en una red corporativa",
        )


async def revisar_gemini(clave: str, modelo: str) -> None:
    if not clave:
        aviso(
            "Sin GEMINI_API_KEY: el bot funciona, pero solo con texto",
            "las fotos, los PDFs y las notas de voz necesitan la clave",
        )
        print(f"    {GRIS}→ Consíguela gratis en https://aistudio.google.com/apikey{FIN}")
        return
    try:
        from google import genai
        from google.genai import types

        cliente = genai.Client(api_key=clave)
        r = await cliente.aio.models.generate_content(
            model=modelo,
            contents=[types.Part.from_text(text="Responde solo con: listo")],
            config=types.GenerateContentConfig(max_output_tokens=10, temperature=0),
        )
        if r.text:
            ok("Gemini responde", f"modelo {modelo}")
        else:
            aviso("Gemini contestó vacío", "puede ser un límite momentáneo")
    except Exception as exc:
        mensaje = str(exc)
        if "API_KEY_INVALID" in mensaje or "API key not valid" in mensaje:
            falla("La clave de Gemini no es válida",
                  "Genera otra en https://aistudio.google.com/apikey")
        elif "RESOURCE_EXHAUSTED" in mensaje or "429" in mensaje:
            aviso("Se agotó la cuota gratuita de Gemini por ahora",
                  "el bot cae al parser de texto mientras tanto")
        else:
            falla(f"Gemini falló ({exc.__class__.__name__}): {mensaje[:120]}",
                  "Revisa la clave y que el modelo exista")


async def revisar_base() -> None:
    from app.db import engine, init_db

    try:
        await init_db()
        motor = "SQLite" if engine.url.drivername.startswith("sqlite") else "Postgres"
        ok("Base de datos lista", motor)
    except Exception as exc:
        falla(f"No pude abrir la base ({exc.__class__.__name__}): {str(exc)[:120]}",
              "Revisa DATABASE_URL en .env")


async def main() -> int:
    from app.config import settings

    print(f"\n  Revisando {settings.app_name}\n")

    if settings.dashboard_token in ("", "cambia-esto"):
        falla("DASHBOARD_TOKEN sigue con el valor de ejemplo",
              "Pon algo largo y aleatorio: quien tenga ese enlace ve tus finanzas")
    else:
        ok("Token del panel configurado")

    if settings.telegram_webhook_secret in ("", "cambia-esto"):
        if settings.base_url.startswith("https://"):
            falla("TELEGRAM_WEBHOOK_SECRET sigue con el valor de ejemplo",
                  "Ponle algo largo: sin eso cualquiera puede escribirle a tu webhook")
        else:
            aviso("TELEGRAM_WEBHOOK_SECRET sin cambiar",
                  "no importa en local, sí al publicarlo")

    await revisar_telegram(settings.telegram_token)
    await revisar_gemini(settings.gemini_api_key, settings.gemini_model)
    await revisar_base()

    if settings.base_url.startswith("https://"):
        ok("Modo webhook", settings.base_url)
    else:
        aviso("BASE_URL no es https", "en local usa `python run_bot.py` (polling)")

    if settings.allowed_ids:
        ok(f"{len(settings.allowed_ids)} usuario(s) autorizados")
    else:
        aviso("Sin ALLOWED_USER_IDS",
              "el primero que escriba /start queda como dueño")

    print()
    if problemas:
        print(f"  {ROJO}Falta resolver {len(problemas)}:{FIN}")
        for p in problemas:
            print(f"    · {p}")
        print()
        return 1
    print(f"  {VERDE}Todo listo.{FIN} Arranca con:  python run_bot.py\n")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
