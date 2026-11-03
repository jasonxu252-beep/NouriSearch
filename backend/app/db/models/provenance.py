"""Where facts come from."""

from datetime import date

from sqlalchemy import CheckConstraint, Date, Integer, SmallInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models._types import enum_type
from app.domain.enums import SourceTier


class Source(Base):
    __tablename__ = "source"
    __table_args__ = (CheckConstraint("priority >= 0", name="priority_not_negative"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(80), unique=True)
    publisher: Mapped[str] = mapped_column(String(160))
    title: Mapped[str] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)
    version: Mapped[str | None] = mapped_column(String(40))
    retrieved_on: Mapped[date | None] = mapped_column(Date)
    license: Mapped[str | None] = mapped_column(String(80))
    tier: Mapped[SourceTier] = mapped_column(enum_type(SourceTier))
    # When two sources give the same fact, the lower number wins.
    priority: Mapped[int] = mapped_column(SmallInteger, default=100)
