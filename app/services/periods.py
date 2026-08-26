"""Utilidades de períodos mensuales ('YYYY-MM') y fechas."""
from __future__ import annotations

import calendar
import datetime as dt

from app.config import settings

MONTHS_ES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]


def today() -> dt.date:
    return dt.datetime.now(settings.tz).date()


def now() -> dt.datetime:
    return dt.datetime.now(settings.tz)


def period_of(date: dt.date) -> str:
    return f"{date.year:04d}-{date.month:02d}"


def current_period() -> str:
    return period_of(today())


def parse_period(period: str) -> tuple[int, int]:
    year, month = period.split("-")
    return int(year), int(month)


def add_months(period: str, months: int) -> str:
    year, month = parse_period(period)
    index = year * 12 + (month - 1) + months
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def period_diff(a: str, b: str) -> int:
    """Cuántos meses hay de `b` a `a` (a - b)."""
    ay, am = parse_period(a)
    by, bm = parse_period(b)
    return (ay * 12 + am) - (by * 12 + bm)


def clamp_day(year: int, month: int, day: int) -> dt.date:
    """Devuelve una fecha válida aunque el día no exista en ese mes (31 → 30/28)."""
    last = calendar.monthrange(year, month)[1]
    return dt.date(year, month, min(max(day, 1), last))


def period_bounds(period: str) -> tuple[dt.date, dt.date]:
    year, month = parse_period(period)
    last = calendar.monthrange(year, month)[1]
    return dt.date(year, month, 1), dt.date(year, month, last)


def period_label(period: str) -> str:
    year, month = parse_period(period)
    return f"{MONTHS_ES[month - 1].capitalize()} {year}"


def in_range(period: str, start: str, end: str | None) -> bool:
    if period < start:
        return False
    if end and period > end:
        return False
    return True
