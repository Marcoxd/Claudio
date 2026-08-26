"""Conciliar el estado de cuenta del banco con lo que tienes registrado."""
from __future__ import annotations

import datetime as dt
import json
import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    KIND_EXPENSE,
    STATUS_DONE,
    Account,
    CardPayment,
    Category,
    Transaction,
)
from app.money import D, ZERO
from app.services import ai
from app.services.capture import build_context, delete_draft, load_draft, save_draft
from app.services.cards import build_installments, statement_period_for
from app.services.fallback import guess_category
from app.services.format import block, date_es, money, row
from app.services.periods import period_label, today
from app.services.reconcile import (
    Movimiento,
    buscar_tarjeta,
    conciliar,
    registros_del_periodo,
)

log = logging.getLogger(__name__)
router = Router(name="reconcile")

MAX_MB = 18
MIMES = {
    "application/pdf": "application/pdf",
    "image/jpeg": "image/jpeg",
    "image/png": "image/png",
    "image/webp": "image/webp",
}


class Conciliar(StatesGroup):
    esperando = State()


def _fecha(texto: str, por_defecto: dt.date | None = None) -> dt.date | None:
    try:
        return dt.date.fromisoformat(texto)
    except (ValueError, TypeError):
        return por_defecto


@router.message(Command("conciliar"))
async def cmd_conciliar(message: Message, state: FSMContext) -> None:
    await state.set_state(Conciliar.esperando)
    await message.answer(
        "<b>Conciliar estado de cuenta</b>\n\n"
        "Mándame el PDF del estado de cuenta de tu tarjeta —o una foto de las "
        "páginas con el detalle— y te digo:\n\n"
        "· qué consumos ya tenías registrados\n"
        "· cuáles cobró el banco y no anotaste\n"
        "· cuáles anotaste y no aparecen (suelen ser de la otra tarjeta, o "
        "posteriores al corte)\n\n"
        "De paso te ofrezco corregir el día de corte y de pago con lo que diga "
        "el propio estado.\n\n"
        "<i>Escribe /cancelar si te arrepentiste.</i>"
    )


@router.message(Command("cancelar"), Conciliar.esperando)
async def cmd_cancelar(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Listo, cancelado.")


@router.message(Conciliar.esperando, F.document | F.photo)
async def on_statement(message: Message, state: FSMContext, session: AsyncSession, bot: Bot) -> None:
    if message.photo:
        archivo, mime = message.photo[-1], "image/jpeg"
    else:
        archivo = message.document
        mime = MIMES.get((archivo.mime_type or "").lower())
        if not mime:
            await message.answer("Solo puedo leer PDF o imágenes.")
            return
    if archivo.file_size and archivo.file_size > MAX_MB * 1024 * 1024:
        await message.answer(f"El archivo pasa de {MAX_MB} MB.")
        return

    aviso = await message.answer("Leyendo el estado de cuenta… esto tarda un poco.")
    try:
        datos = (await bot.download(archivo.file_id)).read()
        estado = await ai.parse_statement(datos, mime, await build_context(session))
    except Exception as exc:
        log.exception("Error leyendo el estado de cuenta")
        await aviso.edit_text(f"No pude leerlo. {exc}")
        await state.clear()
        return

    await state.clear()
    tarjeta = await buscar_tarjeta(session, estado.card_name)
    if tarjeta is None:
        await aviso.edit_text(
            f"Leí el estado de <b>{estado.card_name or 'la tarjeta'}</b> pero no sé "
            "a cuál de las tuyas corresponde.\n"
            "Créala con /nuevatarjeta y vuelve a mandármelo."
        )
        return

    corte = _fecha(estado.period_end)
    inicio = _fecha(estado.period_start)
    vence = _fecha(estado.due_date)
    if corte is None:
        await aviso.edit_text("No encontré la fecha de corte en el documento.")
        return
    if inicio is None:
        inicio = corte - dt.timedelta(days=30)

    periodo = f"{corte.year:04d}-{corte.month:02d}"
    movimientos = []
    for linea in estado.lines:
        fecha = _fecha(linea.date, corte)
        if not linea.amount:
            continue
        movimientos.append(
            Movimiento(
                date=fecha, description=linea.description[:80],
                amount=D(linea.amount), kind=linea.kind,
                installment=linea.installment,
                deferred_balance=D(linea.deferred_balance),
            )
        )

    registros = await registros_del_periodo(session, tarjeta, inicio, corte, periodo)
    resultado = conciliar(movimientos, registros)

    payload = {
        "account_id": tarjeta.id,
        "period": periodo,
        "cut_day": corte.day,
        "due_day": vence.day if vence else None,
        "due_date": vence.isoformat() if vence else None,
        "total_due": float(estado.total_due or 0),
        "faltan": [
            {"date": m.date.isoformat(), "description": m.description,
             "amount": float(m.amount), "installment": m.installment}
            for m in resultado.faltan
        ],
        "pagos": [
            {"date": m.date.isoformat(), "description": m.description,
             "amount": float(m.amount)}
            for m in resultado.pagos
        ],
        "sobran": [
            {"description": r.description, "amount": float(r.amount)}
            for r in resultado.sobran
        ],
        "difieren": [
            {"description": p.registro.description,
             "mio": float(p.registro.amount), "banco": float(p.movimiento.amount),
             "transaction_id": p.registro.transaction_id}
            for p in resultado.difieren
        ],
    }
    borrador = await save_draft(
        session, message.from_user.id, message.chat.id, payload, state="conciliacion"
    )

    await aviso.delete()
    await message.answer(
        _resumen(estado, tarjeta, corte, vence, resultado, periodo),
        reply_markup=_botones(borrador.id, resultado, tarjeta, corte, vence),
    )


def _resumen(estado, tarjeta, corte, vence, resultado, periodo) -> str:
    lineas = [
        f"<b>{tarjeta.name}</b> · corte de {period_label(periodo).lower()}",
        f"Cierra el {date_es(corte)}"
        + (f", lo pagas el {date_es(vence)}" if vence else ""),
    ]
    if estado.total_due:
        lineas.append(f"Total a pagar: <b>{money(estado.total_due)}</b>")
    lineas += ["", f"Revisé {resultado.revisado} movimientos.", ""]

    lineas.append(
        block(
            [
                row("Ya los tenías", str(len(resultado.cuadran))),
                row("Con diferencia", str(len(resultado.difieren))),
                row("No registrados", str(len(resultado.faltan))),
                row("Sin respaldo", str(len(resultado.sobran))),
            ]
        )
    )

    if resultado.faltan:
        cuantos = len(resultado.faltan)
        encabezado = (
            f"<b>Te falta 1 consumo por {money(resultado.total_faltante)}</b>"
            if cuantos == 1
            else f"<b>Te faltan {cuantos} por {money(resultado.total_faltante)}</b>"
        )
        lineas += ["", encabezado]
        for m in resultado.faltan[:8]:
            etiqueta = f"{date_es(m.date)} {m.description[:24]}"
            if m.installment:
                etiqueta += f" ({m.installment})"
            lineas.append(f"  {etiqueta} · {money(m.amount)}")
        if len(resultado.faltan) > 8:
            lineas.append(f"  …y {len(resultado.faltan) - 8} más")

    if resultado.difieren:
        lineas += ["", "<b>El banco cobró distinto</b>"]
        for p in resultado.difieren[:6]:
            signo = "más" if p.diferencia > 0 else "menos"
            lineas.append(
                f"  {p.registro.description[:22]}: anotaste {money(p.registro.amount)}, "
                f"cobró {money(p.movimiento.amount)} "
                f"({money(abs(p.diferencia))} de {signo})"
            )

    if resultado.sobran:
        lineas += ["", f"<b>Anotaste {len(resultado.sobran)} que no están en este corte</b>",
                   "<i>Suelen ser de otra tarjeta o compras posteriores al corte.</i>"]
        for r in resultado.sobran[:6]:
            lineas.append(f"  {r.description[:26]} · {money(r.amount)}")
        if len(resultado.sobran) > 6:
            lineas.append(f"  …y {len(resultado.sobran) - 6} más")

    if resultado.pagos:
        from app.money import total as suma
        lineas += ["", f"Pagos del período: {money(suma(p.amount for p in resultado.pagos))}"]

    if resultado.descuadre:
        direccion = "sube" if resultado.descuadre > 0 else "baja"
        lineas += ["", f"Si aceptas todo lo del banco, tu gasto del corte "
                       f"{direccion} <b>{money(abs(resultado.descuadre))}</b>."]
    return "\n".join(lineas)[:4000]


def _botones(draft_id, resultado, tarjeta, corte, vence) -> InlineKeyboardMarkup:
    filas = []
    if resultado.faltan:
        cuantos = len(resultado.faltan)
        filas.append([
            InlineKeyboardButton(
                text=("Agregar el que falta" if cuantos == 1
                      else f"Agregar los {cuantos} que faltan"),
                callback_data=f"k:add:{draft_id}",
            )
        ])
    if resultado.difieren:
        filas.append([
            InlineKeyboardButton(
                text="Corregir montos con los del banco",
                callback_data=f"k:fix:{draft_id}",
            )
        ])
    if vence and (tarjeta.cut_day != corte.day or tarjeta.due_day != vence.day):
        filas.append([
            InlineKeyboardButton(
                text=f"Fijar corte {corte.day} y pago {vence.day}",
                callback_data=f"k:dates:{draft_id}",
            )
        ])
    if resultado.pagos:
        filas.append([
            InlineKeyboardButton(text="Registrar los pagos", callback_data=f"k:pay:{draft_id}")
        ])
    filas.append([InlineKeyboardButton(text="Cerrar", callback_data=f"k:close:{draft_id}")])
    return InlineKeyboardMarkup(inline_keyboard=filas)


async def _cargar(callback: CallbackQuery, session: AsyncSession):
    draft_id = int(callback.data.split(":")[2])
    borrador, payload = await load_draft(session, draft_id)
    if borrador is None:
        await callback.answer("Esa conciliación ya no está disponible.", show_alert=True)
        return None, None, None
    tarjeta = await session.get(Account, payload["account_id"])
    return borrador, payload, tarjeta


@router.callback_query(F.data.startswith("k:add:"))
async def cb_add(callback: CallbackQuery, session: AsyncSession) -> None:
    borrador, payload, tarjeta = await _cargar(callback, session)
    if borrador is None:
        return
    from sqlalchemy import select

    cats = {c.name: c for c in (await session.execute(select(Category))).scalars().all()}
    nombres = list(cats)

    creados = ZERO
    for item in payload.get("faltan", []):
        fecha = dt.date.fromisoformat(item["date"])
        tx = Transaction(
            kind=KIND_EXPENSE, status=STATUS_DONE, date=fecha,
            period=f"{fecha.year:04d}-{fecha.month:02d}",
            amount=D(item["amount"]), description=item["description"][:200],
            category_id=cats[guess_category(item["description"], nombres)].id,
            account_id=tarjeta.id, source="pdf",
            notes=f"Agregado al conciliar el corte {payload['period']}",
        )
        session.add(tx)
        await session.flush()
        for cuota in build_installments(tx, tarjeta, 1):
            session.add(cuota)
        creados = D(creados + D(item["amount"]))

    cuantos = len(payload.get("faltan", []))
    payload["faltan"] = []
    borrador.payload = json.dumps(payload, ensure_ascii=False)
    await session.flush()
    await callback.message.answer(
        f"Agregué {cuantos} "
        + ("consumo" if cuantos == 1 else "consumos")
        + f" por <b>{money(creados)}</b> a {tarjeta.name}.\n"
        "<i>Revisa las categorías en el panel: las puse por el nombre del comercio.</i>"
    )
    await callback.answer("Agregados")


@router.callback_query(F.data.startswith("k:fix:"))
async def cb_fix(callback: CallbackQuery, session: AsyncSession) -> None:
    borrador, payload, tarjeta = await _cargar(callback, session)
    if borrador is None:
        return
    corregidos = 0
    for item in payload.get("difieren", []):
        if not item.get("transaction_id"):
            continue
        tx = await session.get(Transaction, item["transaction_id"])
        if tx is None:
            continue
        tx.amount = D(item["banco"])
        corregidos += 1
    payload["difieren"] = []
    borrador.payload = json.dumps(payload, ensure_ascii=False)
    await session.flush()
    await callback.message.answer(
        f"Corregí {corregidos} montos con los del banco."
        if corregidos
        else "No había montos que corregir."
    )
    await callback.answer("Corregidos")


@router.callback_query(F.data.startswith("k:dates:"))
async def cb_dates(callback: CallbackQuery, session: AsyncSession) -> None:
    borrador, payload, tarjeta = await _cargar(callback, session)
    if borrador is None:
        return
    tarjeta.cut_day = payload["cut_day"]
    tarjeta.due_day = payload["due_day"]
    await session.flush()
    hoy = today()
    periodo = statement_period_for(hoy, tarjeta.cut_day)
    await callback.message.answer(
        f"<b>{tarjeta.name}</b>: corte el {tarjeta.cut_day}, pago el {tarjeta.due_day}.\n\n"
        f"Con eso, lo que compres hoy entra al corte de "
        f"{period_label(periodo).lower()}."
    )
    await callback.answer("Fechas actualizadas")


@router.callback_query(F.data.startswith("k:pay:"))
async def cb_pay(callback: CallbackQuery, session: AsyncSession) -> None:
    borrador, payload, tarjeta = await _cargar(callback, session)
    if borrador is None:
        return
    registrados = ZERO
    for item in payload.get("pagos", []):
        session.add(
            CardPayment(
                account_id=tarjeta.id,
                date=dt.date.fromisoformat(item["date"]),
                amount=D(item["amount"]),
                statement_period=payload["period"],
                note=item["description"][:120],
            )
        )
        registrados = D(registrados + D(item["amount"]))
    payload["pagos"] = []
    borrador.payload = json.dumps(payload, ensure_ascii=False)
    await session.flush()
    await callback.message.answer(
        f"Registré {money(registrados)} en pagos al corte {payload['period']}."
    )
    await callback.answer("Pagos registrados")


@router.callback_query(F.data.startswith("k:close:"))
async def cb_close(callback: CallbackQuery, session: AsyncSession) -> None:
    borrador, _, _ = await _cargar(callback, session)
    if borrador is not None:
        await delete_draft(session, borrador)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer("Listo")
