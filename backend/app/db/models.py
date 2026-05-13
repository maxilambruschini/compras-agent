"""SQLAlchemy ORM models stub — Task 1 minimal version.

This stub provides Base and SenderAllowlist so conftest.py can import without
ModuleNotFoundError during Task 1 pytest collection. Task 2 replaces this with
the full Invoice + InvoiceLineItem + complete SenderAllowlist schema.
"""
from sqlalchemy import Boolean, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class SenderAllowlist(Base):
    __tablename__ = "sender_allowlist"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    phone_number: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
