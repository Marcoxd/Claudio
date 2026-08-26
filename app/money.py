"""Tipo monetario exacto: se guarda en centavos (entero) y se usa como Decimal."""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable

from sqlalchemy import BigInteger
from sqlalchemy.types import TypeDecorator

CENT = Decimal("0.01")
ZERO = Decimal("0.00")


def D(value) -> Decimal:
    """Convierte cualquier cosa razonable a Decimal con 2 decimales."""
    if value is None:
        return ZERO
    if isinstance(value, Decimal):
        d = value
    else:
        d = Decimal(str(value).strip().replace(",", "."))
    return d.quantize(CENT, rounding=ROUND_HALF_UP)


def total(values: Iterable) -> Decimal:
    out = ZERO
    for v in values:
        out += D(v)
    return out


def split_evenly(amount: Decimal, parts: int) -> list[Decimal]:
    """Reparte un monto en `parts` partes sin perder ni un centavo."""
    if parts <= 0:
        return []
    amount = D(amount)
    cents = int(amount * 100)
    base, extra = divmod(abs(cents), parts)
    sign = -1 if cents < 0 else 1
    shares = [Decimal(base * sign) / 100 for _ in range(parts)]
    for i in range(extra):
        shares[i] += Decimal(sign) / 100
    return [D(s) for s in shares]


def prorate(amount: Decimal, weights: list[Decimal]) -> list[Decimal]:
    """Reparte `amount` proporcionalmente a `weights`, cuadrando el último centavo."""
    amount = D(amount)
    w_total = total(weights)
    if w_total == 0:
        return split_evenly(amount, len(weights)) if weights else []
    out: list[Decimal] = []
    acc = ZERO
    for w in weights[:-1]:
        part = D(amount * D(w) / w_total)
        out.append(part)
        acc += part
    out.append(D(amount - acc))
    return out


class Money(TypeDecorator):
    """Columna de dinero. Persiste centavos como entero; expone Decimal."""

    impl = BigInteger
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return int(D(value) * 100)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return D(Decimal(value) / 100)
