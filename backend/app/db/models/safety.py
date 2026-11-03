"""Allergens and contextual health considerations."""

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models._types import Sourced, enum_type
from app.domain.enums import (
    AllergenRelation,
    ConsiderationCategory,
    EvidenceLevel,
    FoodClassificationKind,
    Verification,
)


class Allergen(Sourced, Base):
    __tablename__ = "allergen"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(80), unique=True)
    name: Mapped[str] = mapped_column(String(160))
    is_us_major: Mapped[bool] = mapped_column(Boolean, default=False)


class FoodAllergen(Sourced, Base):
    """CONTAINS, MAY_CONTAIN, or FREE_OF. No row means the app does not know."""

    __tablename__ = "food_allergen"

    food_id: Mapped[int] = mapped_column(
        ForeignKey("food.id", ondelete="CASCADE"), primary_key=True
    )
    allergen_id: Mapped[int] = mapped_column(
        ForeignKey("allergen.id", ondelete="RESTRICT"), primary_key=True, index=True
    )
    source_id: Mapped[int] = mapped_column(
        ForeignKey("source.id", ondelete="RESTRICT"), primary_key=True
    )
    relation: Mapped[AllergenRelation] = mapped_column(enum_type(AllergenRelation))
    verification: Mapped[Verification] = mapped_column(enum_type(Verification))


class HealthConsideration(Base):
    """A documented concern, phrased once and shared by every food it applies to."""

    __tablename__ = "health_consideration"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(80), unique=True)
    name: Mapped[str] = mapped_column(Text)
    category: Mapped[ConsiderationCategory] = mapped_column(enum_type(ConsiderationCategory))
    explanation: Mapped[str] = mapped_column(Text)


class FoodHealthConsideration(Sourced, Base):
    """Ties a concern to one specific food, with the context that makes it apply."""

    __tablename__ = "food_health_consideration"

    food_id: Mapped[int] = mapped_column(
        ForeignKey("food.id", ondelete="CASCADE"), primary_key=True
    )
    health_consideration_id: Mapped[int] = mapped_column(
        ForeignKey("health_consideration.id", ondelete="RESTRICT"), primary_key=True, index=True
    )
    source_id: Mapped[int] = mapped_column(
        ForeignKey("source.id", ondelete="RESTRICT"), primary_key=True
    )
    context: Mapped[str] = mapped_column(Text)
    evidence_level: Mapped[EvidenceLevel] = mapped_column(enum_type(EvidenceLevel))
    verification: Mapped[Verification] = mapped_column(enum_type(Verification))


class FoodClassification(Sourced, Base):
    """Facts about what a food is, such as being a source of added sugar."""

    __tablename__ = "food_classification"

    food_id: Mapped[int] = mapped_column(
        ForeignKey("food.id", ondelete="CASCADE"), primary_key=True
    )
    classification: Mapped[FoodClassificationKind] = mapped_column(
        enum_type(FoodClassificationKind), primary_key=True, index=True
    )
    source_id: Mapped[int] = mapped_column(
        ForeignKey("source.id", ondelete="RESTRICT"), primary_key=True
    )
    verification: Mapped[Verification] = mapped_column(enum_type(Verification))
    rule_note: Mapped[str | None] = mapped_column(String(200))
