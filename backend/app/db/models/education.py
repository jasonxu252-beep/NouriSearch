"""What nutrients do in the body, and the effects of too little or too much."""

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models._types import Sourced, enum_type
from app.domain.enums import EffectContext, EffectType, EvidenceLevel


class HealthFunction(Base):
    __tablename__ = "health_function"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(80), unique=True)
    name: Mapped[str] = mapped_column(Text)


class NutrientFunction(Sourced, Base):
    """HAS_HEALTH_FUNCTION."""

    __tablename__ = "nutrient_function"

    nutrient_id: Mapped[int] = mapped_column(
        ForeignKey("nutrient.id", ondelete="CASCADE"), primary_key=True
    )
    health_function_id: Mapped[int] = mapped_column(
        ForeignKey("health_function.id", ondelete="RESTRICT"), primary_key=True
    )
    source_id: Mapped[int] = mapped_column(
        ForeignKey("source.id", ondelete="RESTRICT"), primary_key=True
    )
    evidence_level: Mapped[EvidenceLevel] = mapped_column(enum_type(EvidenceLevel))


class HealthEffect(Base):
    __tablename__ = "health_effect"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(80), unique=True)
    name: Mapped[str] = mapped_column(Text)


class NutrientHealthEffect(Sourced, Base):
    """HAS_INADEQUACY_CONSEQUENCE and its counterpart for excess, separated by context."""

    __tablename__ = "nutrient_health_effect"

    nutrient_id: Mapped[int] = mapped_column(
        ForeignKey("nutrient.id", ondelete="CASCADE"), primary_key=True
    )
    health_effect_id: Mapped[int] = mapped_column(
        ForeignKey("health_effect.id", ondelete="RESTRICT"), primary_key=True
    )
    context: Mapped[EffectContext] = mapped_column(enum_type(EffectContext), primary_key=True)
    source_id: Mapped[int] = mapped_column(
        ForeignKey("source.id", ondelete="RESTRICT"), primary_key=True
    )
    effect_type: Mapped[EffectType] = mapped_column(
        enum_type(EffectType), default=EffectType.CONSEQUENCE
    )
    evidence_level: Mapped[EvidenceLevel] = mapped_column(enum_type(EvidenceLevel))
    wording_note: Mapped[str | None] = mapped_column(String(200))
