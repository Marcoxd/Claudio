"""Interpretación de texto, notas de voz, fotos y PDFs con Gemini (Google AI Studio).

Si no hay `GEMINI_API_KEY`, el bot sigue funcionando con un parser de texto
básico por reglas (ver `fallback.py`).
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Literal

from pydantic import BaseModel, Field

from app.config import settings

log = logging.getLogger(__name__)

_client = None


def client():
    global _client
    if _client is None:
        from google import genai

        _client = genai.Client(api_key=settings.gemini_api_key)
    return _client


# ----------------------------------------------------------------- esquemas


class ParsedItem(BaseModel):
    name: str = ""
    quantity: float = 1
    unit_price: float = 0
    total: float = 0
    kind: Literal["item", "tax", "tip", "discount"] = "item"


class ParsedCapture(BaseModel):
    kind: Literal["expense", "income", "unknown"] = "expense"
    amount: float = 0
    currency: str = "USD"
    date: str = ""                      # YYYY-MM-DD; vacío = hoy
    description: str = ""
    merchant: str = ""
    category: str = ""                  # debe salir de la lista dada
    account: str = ""                   # medio de pago mencionado
    income_type: str = ""               # sueldo | asesoramiento | extra | otro
    installments: int = 1               # diferido a N meses
    people: list[str] = Field(default_factory=list)
    split_mode: Literal["", "equal", "items"] = ""
    is_buffer: bool = False             # ¿usó/repuso el colchón?
    buffer_direction: Literal["", "use", "repay"] = ""
    items: list[ParsedItem] = Field(default_factory=list)
    notes: str = ""
    confidence: float = 0.5


SYSTEM = """Eres el motor de extracción de un bot de finanzas personales en español (Ecuador, moneda USD).
Recibes texto libre, una transcripción de voz, la foto de un recibo o un PDF de factura.
Devuelves SIEMPRE un único JSON con el gasto o ingreso detectado.

Reglas:
- `amount` es el TOTAL de la factura (con impuestos y propina incluidos), en números, sin símbolos.
- Si el texto es un ingreso ("me pagaron", "cobré", "sueldo", "asesoría"), usa kind="income".
- `date` en formato YYYY-MM-DD. Si no se menciona fecha, usa la fecha de hoy que te doy.
- `category` DEBE ser exactamente una de las categorías de la lista. Si ninguna encaja, usa "Otros".
- `account` debe coincidir con uno de los medios de pago de la lista si se menciona
  (ej: "con la visa", "en efectivo", "con débito"). Si no se menciona, déjalo vacío.
- `installments`: si dice "diferido a 6", "a 12 meses", "6 cuotas", pon ese número. Si no, 1.
- `people`: nombres de otras personas mencionadas para dividir la cuenta.
  Si dice "con Juan y Pedro", pon ["Juan","Pedro"] y split_mode="equal".
  Si dice "yo pagué solo lo mío" o pide separar por productos, usa split_mode="items".
- Colchón: si menciona "colchón", "el dinero que no es mío", "saqué del colchón" → is_buffer=true
  con buffer_direction="use"; si dice "repuse", "devolví al colchón" → "repay".
- En recibos y facturas extrae TODOS los ítems de la lista de productos en `items`,
  con su cantidad y precio. IVA, propina/servicio y descuentos van como ítems aparte
  con kind="tax", "tip" o "discount".
- En facturas ecuatorianas: "SUBTOTAL", "IVA 15%", "VALOR TOTAL", "RUC", "RAZÓN SOCIAL".
  El emisor (la tienda) va en `merchant`, no el cliente.
- `confidence` entre 0 y 1 según qué tan seguro estás del monto total.
- Si no logras identificar un monto, devuelve kind="unknown" y amount=0.
"""


def _context_block(ctx: dict) -> str:
    return (
        f"Fecha de hoy: {ctx.get('today')}\n"
        f"Moneda: {ctx.get('currency', 'USD')}\n"
        f"Categorías disponibles: {', '.join(ctx.get('categories', []))}\n"
        f"Medios de pago: {', '.join(ctx.get('accounts', []))}\n"
        f"Personas conocidas: {', '.join(ctx.get('people', [])) or '(ninguna)'}\n"
    )


async def _generate(parts: list, ctx: dict) -> ParsedCapture:
    from google.genai import types

    config = types.GenerateContentConfig(
        system_instruction=SYSTEM,
        response_mime_type="application/json",
        response_schema=ParsedCapture,
        temperature=0.1,
    )
    contents = [types.Part.from_text(text=_context_block(ctx))] + parts
    response = await client().aio.models.generate_content(
        model=settings.gemini_model,
        contents=contents,
        config=config,
    )
    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, ParsedCapture):
        return parsed
    text = (response.text or "").strip()
    if text.startswith("```"):
        text = text.strip("`").split("\n", 1)[-1]
    return ParsedCapture.model_validate(json.loads(text))


async def _safe(coro_factory, ctx: dict, fallback_text: str = "") -> ParsedCapture:
    from app.services.fallback import parse_text_rules

    if not settings.ai_enabled:
        return parse_text_rules(fallback_text, ctx)
    for attempt in range(3):
        try:
            return await coro_factory()
        except Exception as exc:  # cuota agotada, red, JSON inválido…
            log.warning("Gemini falló (intento %s): %s", attempt + 1, exc)
            if attempt < 2:
                await asyncio.sleep(1.5 * (attempt + 1))
    return parse_text_rules(fallback_text, ctx)


async def parse_text(text: str, ctx: dict) -> ParsedCapture:
    from google.genai import types

    return await _safe(
        lambda: _generate([types.Part.from_text(text=f"Mensaje del usuario:\n{text}")], ctx),
        ctx,
        fallback_text=text,
    )


async def parse_audio(data: bytes, mime_type: str, ctx: dict) -> ParsedCapture:
    from google.genai import types

    prompt = (
        "Esta es una nota de voz. Transcríbela mentalmente y extrae el gasto o "
        "ingreso que describe. Pon la transcripción en `notes`."
    )
    return await _safe(
        lambda: _generate(
            [
                types.Part.from_text(text=prompt),
                types.Part.from_bytes(data=data, mime_type=mime_type),
            ],
            ctx,
        ),
        ctx,
    )


async def parse_document(data: bytes, mime_type: str, ctx: dict, caption: str = "") -> ParsedCapture:
    from google.genai import types

    prompt = (
        "Este archivo es un recibo o factura. Extrae el total, el comercio, la fecha "
        "y TODOS los ítems con sus precios."
    )
    if caption:
        prompt += f"\nEl usuario además escribió: {caption}"
    return await _safe(
        lambda: _generate(
            [
                types.Part.from_text(text=prompt),
                types.Part.from_bytes(data=data, mime_type=mime_type),
            ],
            ctx,
        ),
        ctx,
        fallback_text=caption,
    )


async def answer_question(question: str, context_text: str) -> str:
    """Responde preguntas libres sobre las finanzas del usuario (/pregunta)."""
    if not settings.ai_enabled:
        return "Necesito una GEMINI_API_KEY configurada para responder preguntas."
    from google.genai import types

    try:
        response = await client().aio.models.generate_content(
            model=settings.gemini_model,
            contents=[
                types.Part.from_text(
                    text=f"Datos financieros actuales:\n{context_text}\n\nPregunta: {question}"
                )
            ],
            config=types.GenerateContentConfig(
                system_instruction=(
                    "Eres un asesor financiero personal, directo y breve. Respondes en "
                    "español con cifras concretas basadas SOLO en los datos dados. "
                    "Máximo 6 líneas. Usa el símbolo $ para los montos."
                ),
                temperature=0.3,
            ),
        )
        return (response.text or "").strip() or "No pude generar una respuesta."
    except Exception as exc:
        log.warning("Gemini falló respondiendo: %s", exc)
        return f"No pude consultar el modelo ahora mismo ({exc.__class__.__name__})."
