"""Conciliación: cruzar un estado de cuenta contra lo que ya está registrado.

La lógica de emparejar es pura y no toca la base de datos, para poder probarla
con casos reales sin depender del banco ni de la IA.
"""
from __future__ import annotations

import datetime as dt
import unicodedata
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    ACCOUNT_CREDIT,
    KIND_EXPENSE,
    Account,
    CardPayment,
    Installment,
    Transaction,
)
from app.money import D, ZERO, total

TOLERANCIA = D("0.15")      # centavos de redondeo del banco
DIAS_CERCA = 4              # margen de fecha para dar por buena una coincidencia


@dataclass
class Movimiento:
    """Una fila del estado de cuenta."""

    date: dt.date
    description: str
    amount: Decimal
    kind: str = "consumo"          # consumo | pago | cuota | interes | otro
    installment: str = ""
    deferred_balance: Decimal = ZERO


@dataclass
class Registro:
    """Algo que ya está en la base y podría corresponder a una fila."""

    id: int
    date: dt.date
    description: str
    amount: Decimal
    kind: str = "gasto"            # gasto | cuota | pago
    transaction_id: int | None = None


@dataclass
class Par:
    registro: Registro
    movimiento: Movimiento

    @property
    def diferencia(self) -> Decimal:
        return D(self.movimiento.amount - self.registro.amount)

    @property
    def cuadra(self) -> bool:
        return self.diferencia == 0


@dataclass
class Conciliacion:
    pares: list[Par] = field(default_factory=list)
    faltan: list[Movimiento] = field(default_factory=list)     # en el estado, no registrado
    sobran: list[Registro] = field(default_factory=list)       # registrado, no en el estado
    pagos: list[Movimiento] = field(default_factory=list)      # abonos del período

    @property
    def cuadran(self) -> list[Par]:
        return [p for p in self.pares if p.cuadra]

    @property
    def difieren(self) -> list[Par]:
        return [p for p in self.pares if not p.cuadra]

    @property
    def total_faltante(self) -> Decimal:
        return total(m.amount for m in self.faltan)

    @property
    def total_sobrante(self) -> Decimal:
        return total(r.amount for r in self.sobran)

    @property
    def descuadre(self) -> Decimal:
        """Cuánto se corrige el gasto del período si aceptas todo lo del banco."""
        return D(
            self.total_faltante
            - self.total_sobrante
            + total(p.diferencia for p in self.pares)
        )

    @property
    def revisado(self) -> int:
        return len(self.pares) + len(self.faltan) + len(self.sobran)


def _plano(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", (texto or "").lower())
        if unicodedata.category(c) != "Mn"
    ).strip()


def _parecidos(a: str, b: str) -> bool:
    """¿Los nombres se parecen? «kiwy» ↔ «COMERCIAL KYWI SA»."""
    x, y = _plano(a), _plano(b)
    if not x or not y:
        return False
    if x in y or y in x:
        return True
    palabras_x = {p for p in x.split() if len(p) > 3}
    palabras_y = {p for p in y.split() if len(p) > 3}
    return bool(palabras_x & palabras_y)


def conciliar(
    movimientos: list[Movimiento],
    registros: list[Registro],
    tolerancia: Decimal = TOLERANCIA,
) -> Conciliacion:
    """Cruza las dos listas.

    Empareja en dos pasadas: primero los montos idénticos, después los que
    difieren dentro de la tolerancia. Así un monto repetido no se lleva por
    delante la coincidencia exacta de otro.
    """
    resultado = Conciliacion()
    pendientes = [m for m in movimientos if m.kind not in ("pago", "interes", "otro")]
    resultado.pagos = [m for m in movimientos if m.kind == "pago"]

    libres_mov = list(range(len(pendientes)))
    libres_reg = list(range(len(registros)))
    usados_mov: set[int] = set()
    usados_reg: set[int] = set()

    for exacto in (True, False):
        for i in libres_reg:
            if i in usados_reg:
                continue
            registro = registros[i]
            mejor: tuple[int, Decimal, int, bool] | None = None
            for j in libres_mov:
                if j in usados_mov:
                    continue
                movimiento = pendientes[j]
                diferencia = abs(D(movimiento.amount - registro.amount))
                if exacto and diferencia != 0:
                    continue
                if not exacto and diferencia > tolerancia:
                    continue
                distancia = abs((movimiento.date - registro.date).days)
                similar = _parecidos(registro.description, movimiento.description)
                candidato = (j, diferencia, distancia, similar)
                if mejor is None or (diferencia, not similar, distancia) < (
                    mejor[1], not mejor[3], mejor[2]
                ):
                    mejor = candidato
            if mejor:
                usados_mov.add(mejor[0])
                usados_reg.add(i)
                resultado.pares.append(Par(registro, pendientes[mejor[0]]))

    resultado.faltan = [m for j, m in enumerate(pendientes) if j not in usados_mov]
    resultado.sobran = [r for i, r in enumerate(registros) if i not in usados_reg]
    resultado.pares.sort(key=lambda p: p.movimiento.date)
    resultado.faltan.sort(key=lambda m: m.date)
    return resultado


# ------------------------------------------------------------- desde la base


async def registros_del_periodo(
    session: AsyncSession,
    account: Account,
    desde: dt.date,
    hasta: dt.date,
    statement_period: str | None = None,
) -> list[Registro]:
    """Lo que ya tengo cargado para ese corte: compras del período y cuotas."""
    filas = (
        await session.execute(
            select(Transaction).where(
                Transaction.account_id == account.id,
                Transaction.kind == KIND_EXPENSE,
                Transaction.date >= desde,
                Transaction.date <= hasta,
            )
        )
    ).scalars().all()

    registros = [
        Registro(
            id=t.id, date=t.date, description=t.description,
            amount=D(t.amount), kind="gasto", transaction_id=t.id,
        )
        for t in filas
        if t.installments_total <= 1
    ]

    if statement_period:
        cuotas = (
            await session.execute(
                select(Installment)
                .options(selectinload(Installment.transaction))
                .where(
                    Installment.account_id == account.id,
                    Installment.statement_period == statement_period,
                    Installment.count > 1,
                )
            )
        ).scalars().all()
        registros += [
            Registro(
                id=c.id,
                date=c.transaction.date if c.transaction else desde,
                description=(c.transaction.description if c.transaction else "Cuota"),
                amount=D(c.amount), kind="cuota", transaction_id=c.transaction_id,
            )
            for c in cuotas
        ]
    return registros


async def pagos_registrados(
    session: AsyncSession, account: Account, statement_period: str
) -> Decimal:
    filas = (
        await session.execute(
            select(CardPayment.amount).where(
                CardPayment.account_id == account.id,
                CardPayment.statement_period == statement_period,
            )
        )
    ).scalars().all()
    return total(filas)


async def buscar_tarjeta(session: AsyncSession, nombre: str) -> Account | None:
    """Encuentra la tarjeta por el nombre que usa el banco, con tolerancia."""
    tarjetas = (
        await session.execute(
            select(Account).where(
                Account.type == ACCOUNT_CREDIT, Account.active.is_(True)
            )
        )
    ).scalars().all()
    if not tarjetas:
        return None
    objetivo = _plano(nombre)
    for tarjeta in tarjetas:
        if _plano(tarjeta.name) == objetivo:
            return tarjeta
    for tarjeta in tarjetas:
        if objetivo and _parecidos(tarjeta.name, nombre):
            return tarjeta
    return tarjetas[0] if len(tarjetas) == 1 else None
