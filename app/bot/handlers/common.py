"""Comandos básicos: /start, /ayuda, /panel, /id."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards import main_menu
from app.config import settings
from app.services.dashboard_link import dashboard_url

router = Router(name="common")


def welcome_text() -> str:
    return (
        f"<b>{settings.app_name}</b> — {settings.app_tagline}\n\n"
        "Anótame tus gastos como te salga natural:\n\n"
        "<i>almuerzo 12.50 con la visa</i>\n"
        "una nota de voz\n"
        "la foto del recibo\n"
        "el PDF de la factura\n\n"
        "Yo saco el monto, la categoría, el medio de pago, los diferidos y con "
        "quién dividiste la cuenta.\n\n"
        "<b>Comandos</b>\n"
        "/resumen — cómo va el mes\n"
        "/tarjetas — cortes, cuotas y cuánto pagar\n"
        "/corte — en qué mes cae lo que compres hoy\n"
        "/diferidos — cuánto falta de cada compra a cuotas\n"
        "/fijos — arriendo, internet, préstamos…\n"
        "/deudas — quién te debe de las salidas\n"
        "/colchon — el dinero que no es tuyo\n"
        "/panel — el dashboard\n"
        "/setup — configurar todo paso a paso\n"
        "/ayuda — ejemplos de uso"
    )


HELP = """<b>Cómo hablarme</b>

<b>Gastos</b>
<code>almuerzo 12.50</code>
<code>gasolina 25 con la visa</code>
<code>tv 899 diferido a 12 meses con diners</code>
<code>ayer supermaxi 84.30 débito</code>

<b>Ingresos</b>
<code>me pagaron 450 de asesoría</code>
<code>sueldo 1200</code>

<b>Cuentas compartidas</b>
<code>cena 96 con Ana y Luis</code> — divide en partes iguales.
Si el gasto no es tuyo —lo pagaste tú pero es de ellos— destilda <b>Yo</b> en la
lista de personas y no te cuenta como gasto propio.
Mándame la foto del recibo y toca <b>Dividir cuenta → por ítems</b> para marcar
qué consumió cada quien: el IVA y la propina se reparten solos.

<b>Colchón</b>
<code>saqué 100 del colchón</code>
<code>repuse 50 al colchón</code>

<b>Tarjetas</b>
/tarjetas te dice cuánto pagar en cada corte y cuándo vence; desde ahí puedes
ver los movimientos de un corte o cambiarle las fechas.
/corte te dice, para cada tarjeta, en qué mes va a caer lo que compres hoy.
/nuevatarjeta agrega una.
/diferidos te dice cuánto falta de cada compra a cuotas.

Al anotar un gasto con tarjeta te digo al instante a qué corte entra y cuándo
lo pagas, antes de que confirmes. Los diferidos se reparten mes a mes solos.

<b>Recibos</b>
Foto o PDF: leo comercio, fecha, total e ítems. Puedes mandar la foto con un
texto al pie, por ejemplo <i>«con la visa, dividido con Ana»</i>.
"""


@router.message(CommandStart())
async def cmd_start(message: Message, session: AsyncSession) -> None:
    await message.answer(welcome_text(), reply_markup=main_menu())


@router.message(Command("ayuda", "help"))
async def cmd_help(message: Message) -> None:
    await message.answer(HELP)


@router.message(Command("id"))
async def cmd_id(message: Message) -> None:
    await message.answer(
        f"Tu ID de Telegram: <code>{message.from_user.id}</code>\n"
        f"Chat: <code>{message.chat.id}</code>"
    )


@router.message(Command("panel"))
@router.message(F.text == "Panel")
async def cmd_panel(message: Message) -> None:
    await message.answer(
        f"<b>Tu panel</b>\n{dashboard_url()}\n\n"
        "<i>Guárdalo en favoritos. El enlace lleva tu token: no lo compartas.</i>",
        disable_web_page_preview=True,
    )


@router.callback_query(lambda c: c.data in {"noop", "cancel"})
async def cb_noop(callback: CallbackQuery) -> None:
    if callback.data == "cancel":
        await callback.message.edit_text("Cancelado.")
    await callback.answer()
