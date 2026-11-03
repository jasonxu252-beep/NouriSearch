"""Nutrients, their values in foods, and intake references.

A missing row in `food_nutrient` means the value is unknown. The amount column is required and
has no default, so the database cannot quietly turn missing data into zero.
"""

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, SmallInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models._types import Amount, Sourced, enum_type
from app.domain.enums import NutrientCategory, NutrientDirection, ReferenceKind, ValueKind


class Nutrient(Base):
    __tablename__ = "nutrient"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(80), unique=True)
    name: Mapped[str] = mapped_column(String(160))
    unit: Mapped[str] = mapped_column(String(16))
    category: Mapped[NutrientCategory] = mapped_column(enum_type(NutrientCategory))
    direction: Mapped[NutrientDirection] = mapped_column(enum_type(NutrientDirection))
    display_order: Mapped[int] = mapped_column(SmallInteger)
    summary: Mapped[str | None] = mapped_column(Text)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("nutrient.id", ondelete="RESTRICT"), index=True
    )


class NutrientSourceCode(Base):
    """Maps outside codes to a nutrient, since USDA stores total sugars under two numbers."""

    __tablename__ = "nutrient_source_code"

    system: Mapped[str] = mapped_column(String(32), primary_key=True)
    code: Mapped[str] = mapped_column(String(32), primary_key=True)
    nutrient_id: Mapped[int] = mapped_column(
        ForeignKey("nutrient.id", ondelete="CASCADE"), index=True
    )
    # When one food has two codes for a nutrient, the lower number wins.
    preference: Mapped[int] = mapped_column(SmallInteger, default=0)


class NutrientTranslation(Sourced, Base):
    __tablename__ = "nutrient_translation"

    nutrient_id: Mapped[int] = mapped_column(
        ForeignKey("nutrient.id", ondelete="CASCADE"), primary_key=True
    )
    language: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str] = mapped_column(Text)


class FoodNutrient(Sourced, Base):
    """CONTRIBUTES_TO. An amount per 100 g, from one source."""

    __tablename__ = "food_nutrient"
    __table_args__ = (
        CheckConstraint("amount_per_100g >= 0", name="amount_not_negative"),
        Index("ix_food_nutrient_nutrient_amount", "nutrient_id", "amount_per_100g"),
    )

    food_id: Mapped[int] = mapped_column(
        ForeignKey("food.id", ondelete="CASCADE"), primary_key=True
    )
    nutrient_id: Mapped[int] = mapped_column(
        ForeignKey("nutrient.id", ondelete="RESTRICT"), primary_key=True
    )
    source_id: Mapped[int] = mapped_column(
        ForeignKey("source.id", ondelete="RESTRICT"), primary_key=True
    )
    amount_per_100g: Mapped[float] = mapped_column(Amount, nullable=False)
    value_kind: Mapped[ValueKind] = mapped_column(enum_type(ValueKind))
    # USDA's own derivation text, kept verbatim for traceability.
    derivation: Mapped[str | None] = mapped_column(Text)


class NutrientProxy(Sourced, Base):
    """Borrows values from a similar food when none exist. Readers must label these as estimates."""

    __tablename__ = "nutrient_proxy"
    __table_args__ = (CheckConstraint("food_id <> proxy_food_id", name="proxy_is_another_food"),)

    food_id: Mapped[int] = mapped_column(
        ForeignKey("food.id", ondelete="CASCADE"), primary_key=True
    )
    proxy_food_id: Mapped[int] = mapped_column(
        ForeignKey("food.id", ondelete="RESTRICT"), index=True
    )
    rationale: Mapped[str] = mapped_column(Text)


class NutrientReferenceValue(Sourced, Base):
    """Daily Values and Dietary Reference Intakes, by population when they vary."""

    __tablename__ = "nutrient_reference_value"
    __table_args__ = (
        CheckConstraint("amount >= 0", name="amount_not_negative"),
        Index(
            "uq_nutrient_reference_identity",
            "nutrient_id",
            "kind",
            "population",
            "source_id",
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nutrient_id: Mapped[int] = mapped_column(
        ForeignKey("nutrient.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[ReferenceKind] = mapped_column(enum_type(ReferenceKind))
    # A stable key, such as "general_label" or "adult_19_50_female".
    population: Mapped[str] = mapped_column(String(40))
    amount: Mapped[float] = mapped_column(Amount)
    notes: Mapped[str | None] = mapped_column(Text)
