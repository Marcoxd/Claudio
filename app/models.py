"""Modelo de datos del bot de gastos."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.money import Money

# ---------------------------------------------------------------- constantes

KIND_EXPENSE = "expense"
KIND_INCOME = "income"

ACCOUNT_CASH = "cash"
ACCOUNT_DEBIT = "debit"
ACCOUNT_CREDIT = "credit"

STATUS_DONE = "done"
STATUS_PLANNED = "planned"

SPLIT_EQUAL = "equal"
SPLIT_ITEMS = "items"
SPLIT_CUSTOM = "custom"

BUFFER_USE = "use"       # saco plata del colchón -> queda deuda
BUFFER_REPAY = "repay"   # repongo plata al colchón
BUFFER_ADJUST = "adjust" # ajuste del monto total del colchón


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# ---------------------------------------------------------------- catálogos


class Category(Base, TimestampMixin):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    emoji: Mapped[str] = mapped_column(String(8), default="")
    kind: Mapped[str] = mapped_column(String(16), default=KIND_EXPENSE)
    is_essential: Mapped[bool] = mapped_column(Boolean, default=False)

    def label(self) -> str:
        return f"{self.emoji} {self.name}".strip()


class Person(Base, TimestampMixin):
    """Amigo/familiar con quien comparto gastos o a quien le debo."""

    __tablename__ = "people"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    telegram_username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Account(Base, TimestampMixin):
    """Medio de pago: efectivo, débito o tarjeta de crédito."""

    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    type: Mapped[str] = mapped_column(String(16), default=ACCOUNT_CASH)
    alias: Mapped[str | None] = mapped_column(String(64), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Solo tarjetas de crédito
    cut_day: Mapped[int | None] = mapped_column(Integer, nullable=True)   # día de corte
    due_day: Mapped[int | None] = mapped_column(Integer, nullable=True)   # día máximo de pago
    credit_limit: Mapped[Decimal | None] = mapped_column(Money, nullable=True)

    def is_credit(self) -> bool:
        return self.type == ACCOUNT_CREDIT


# ---------------------------------------------------------------- recurrentes


class FixedExpense(Base, TimestampMixin):
    """Gasto fijo mensual: arriendo, teléfono, internet, carro, préstamo…"""

    __tablename__ = "fixed_expenses"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(96))
    amount: Mapped[Decimal] = mapped_column(Money)
    due_day: Mapped[int] = mapped_column(Integer, default=1)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"), nullable=True)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    start_period: Mapped[str] = mapped_column(String(7))            # 'YYYY-MM'
    end_period: Mapped[str | None] = mapped_column(String(7), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Préstamos: a quién le debo y cuántas cuotas faltan
    lender_person_id: Mapped[int | None] = mapped_column(ForeignKey("people.id"), nullable=True)
    principal: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    installments_total: Mapped[int | None] = mapped_column(Integer, nullable=True)

    category: Mapped["Category | None"] = relationship(lazy="selectin")
    account: Mapped["Account | None"] = relationship(lazy="selectin")
    lender: Mapped["Person | None"] = relationship(lazy="selectin")


class RecurringIncome(Base, TimestampMixin):
    """Ingreso recurrente: sueldo."""

    __tablename__ = "recurring_incomes"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(96))
    amount: Mapped[Decimal] = mapped_column(Money)
    pay_day: Mapped[int] = mapped_column(Integer, default=30)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    start_period: Mapped[str] = mapped_column(String(7))
    end_period: Mapped[str | None] = mapped_column(String(7), nullable=True)

    account: Mapped["Account | None"] = relationship(lazy="selectin")


# ---------------------------------------------------------------- movimientos


class Transaction(Base, TimestampMixin):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), default=KIND_EXPENSE)
    status: Mapped[str] = mapped_column(String(16), default=STATUS_DONE)
    date: Mapped[dt.date] = mapped_column(Date, index=True)
    amount: Mapped[Decimal] = mapped_column(Money)          # total de la factura
    my_share: Mapped[Decimal | None] = mapped_column(Money, nullable=True)  # lo que me toca
    description: Mapped[str] = mapped_column(String(255), default="")
    merchant: Mapped[str | None] = mapped_column(String(128), nullable=True)

    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"), nullable=True)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"), nullable=True)
    fixed_expense_id: Mapped[int | None] = mapped_column(ForeignKey("fixed_expenses.id"), nullable=True)
    recurring_income_id: Mapped[int | None] = mapped_column(ForeignKey("recurring_incomes.id"), nullable=True)
    period: Mapped[str] = mapped_column(String(7), index=True)   # 'YYYY-MM' del gasto

    income_type: Mapped[str | None] = mapped_column(String(32), nullable=True)  # sueldo/asesoría/otro
    installments_total: Mapped[int] = mapped_column(Integer, default=1)
    source: Mapped[str] = mapped_column(String(16), default="manual")  # text|voice|photo|pdf|manual|fixed
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    category: Mapped["Category | None"] = relationship(lazy="selectin")
    account: Mapped["Account | None"] = relationship(lazy="selectin")
    items: Mapped[list["ReceiptItem"]] = relationship(
        back_populates="transaction", cascade="all, delete-orphan", lazy="selectin"
    )
    split: Mapped["Split | None"] = relationship(
        back_populates="transaction", cascade="all, delete-orphan",
        uselist=False, lazy="selectin",
    )
    installments: Mapped[list["Installment"]] = relationship(
        back_populates="transaction", cascade="all, delete-orphan", lazy="selectin"
    )

    def __init__(self, **kwargs):
        # Las relaciones de un objeto recién creado no quedan "cargadas" salvo
        # que alguien las toque. Después del flush, leer una sin cargar dispara
        # una consulta perezosa, y en async eso revienta con MissingGreenlet.
        # Inicializarlas aquí evita tener que acordarse en cada sitio.
        kwargs.setdefault("items", [])
        kwargs.setdefault("installments", [])
        kwargs.setdefault("split", None)
        super().__init__(**kwargs)

    def effective_amount(self) -> Decimal:
        """Lo que realmente me cuesta a mí (descontando lo que pagan otros)."""
        return self.my_share if self.my_share is not None else self.amount


class ReceiptItem(Base):
    __tablename__ = "receipt_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    transaction_id: Mapped[int] = mapped_column(
        ForeignKey("transactions.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(160))
    quantity: Mapped[Decimal] = mapped_column(Money, default=Decimal("1"))
    unit_price: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    total: Mapped[Decimal] = mapped_column(Money)
    kind: Mapped[str] = mapped_column(String(16), default="item")  # item|tax|tip|discount

    transaction: Mapped["Transaction"] = relationship(back_populates="items")


class Split(Base):
    """División de una factura entre varias personas."""

    __tablename__ = "splits"

    id: Mapped[int] = mapped_column(primary_key=True)
    transaction_id: Mapped[int] = mapped_column(
        ForeignKey("transactions.id", ondelete="CASCADE"), unique=True
    )
    mode: Mapped[str] = mapped_column(String(16), default=SPLIT_EQUAL)
    include_me: Mapped[bool] = mapped_column(Boolean, default=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    transaction: Mapped["Transaction"] = relationship(back_populates="split")
    shares: Mapped[list["SplitShare"]] = relationship(
        back_populates="split", cascade="all, delete-orphan", lazy="selectin"
    )


class SplitShare(Base):
    """Cuánto le toca a cada quien. person_id NULL = yo."""

    __tablename__ = "split_shares"

    id: Mapped[int] = mapped_column(primary_key=True)
    split_id: Mapped[int] = mapped_column(ForeignKey("splits.id", ondelete="CASCADE"), index=True)
    person_id: Mapped[int | None] = mapped_column(ForeignKey("people.id"), nullable=True)
    amount: Mapped[Decimal] = mapped_column(Money)
    settled: Mapped[bool] = mapped_column(Boolean, default=False)
    settled_at: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    item_ids: Mapped[str | None] = mapped_column(Text, nullable=True)  # CSV de receipt_items

    split: Mapped["Split"] = relationship(back_populates="shares")
    person: Mapped["Person | None"] = relationship(lazy="selectin")

    def is_mine(self) -> bool:
        return self.person_id is None


class Installment(Base):
    """Cuota de tarjeta: cae en un estado de cuenta (período) concreto."""

    __tablename__ = "installments"

    id: Mapped[int] = mapped_column(primary_key=True)
    transaction_id: Mapped[int] = mapped_column(
        ForeignKey("transactions.id", ondelete="CASCADE"), index=True
    )
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    number: Mapped[int] = mapped_column(Integer, default=1)
    count: Mapped[int] = mapped_column(Integer, default=1)
    amount: Mapped[Decimal] = mapped_column(Money)
    statement_period: Mapped[str] = mapped_column(String(7), index=True)  # 'YYYY-MM' del corte
    due_date: Mapped[dt.date] = mapped_column(Date)

    transaction: Mapped["Transaction"] = relationship(back_populates="installments")
    account: Mapped["Account"] = relationship(lazy="selectin")


class CardPayment(Base, TimestampMixin):
    """Pago hecho a una tarjeta de crédito."""

    __tablename__ = "card_payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    date: Mapped[dt.date] = mapped_column(Date)
    amount: Mapped[Decimal] = mapped_column(Money)
    statement_period: Mapped[str] = mapped_column(String(7), index=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    account: Mapped["Account"] = relationship(lazy="selectin")


class BufferMovement(Base, TimestampMixin):
    """Movimientos del colchón (plata que no es mía)."""

    __tablename__ = "buffer_movements"

    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[dt.date] = mapped_column(Date, index=True)
    direction: Mapped[str] = mapped_column(String(16))   # use|repay|adjust
    amount: Mapped[Decimal] = mapped_column(Money)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    transaction_id: Mapped[int | None] = mapped_column(
        ForeignKey("transactions.id", ondelete="SET NULL"), nullable=True
    )


class Settlement(Base, TimestampMixin):
    """Alguien me pagó (o le pagué) lo que debía de gastos compartidos."""

    __tablename__ = "settlements"

    id: Mapped[int] = mapped_column(primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("people.id"), index=True)
    date: Mapped[dt.date] = mapped_column(Date)
    amount: Mapped[Decimal] = mapped_column(Money)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    person: Mapped["Person"] = relationship(lazy="selectin")


class Draft(Base, TimestampMixin):
    """Captura pendiente de confirmar (sobrevive reinicios del proceso)."""

    __tablename__ = "drafts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    chat_id: Mapped[int] = mapped_column(Integer)
    message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    payload: Mapped[str] = mapped_column(Text)     # JSON
    state: Mapped[str] = mapped_column(String(32), default="review")


class Setting(Base):
    __tablename__ = "settings"
    __table_args__ = (UniqueConstraint("key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(64))
    value: Mapped[str] = mapped_column(Text, default="")
