"""What dishes are made of, and how preparation changes them."""

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models._types import Amount, Sourced, enum_type
from app.domain.enums import EffectDirection, EvidenceLevel, Verification


class IngredientRole(Base):
    """What an ingredient does in a dish, such as seasoning or primary protein."""

    __tablename__ = "ingredient_role"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(80), unique=True)
    name: Mapped[str] = mapped_column(String(160))


class Recipe(Sourced, Base):
    """One documented composition of a dish. A dish can have several, and one is the default."""

    __tablename__ = "recipe"
    __table_args__ = (
        CheckConstraint(
            "moisture_change_pct IS NULL OR moisture_change_pct > -100",
            name="moisture_change_leaves_weight",
        ),
        Index(
            "uq_recipe_default_per_dish",
            "dish_id",
            unique=True,
            postgresql_where=text("is_default"),
        ),
        Index("uq_recipe_identity", "dish_id", "source_id", "label", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dish_id: Mapped[int] = mapped_column(ForeignKey("food.id", ondelete="CASCADE"), index=True)
    label: Mapped[str] = mapped_column(Text)
    verification: Mapped[Verification] = mapped_column(enum_type(Verification))
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    # Percent of the ingredient weight gained or lost as water in preparation. Null when the source
    # does not say, in which case calculations assume the cooked weight equals the raw weight.
    moisture_change_pct: Mapped[float | None] = mapped_column(Amount)


class RecipeComponent(Base):
    """CONTAINS. Weight is optional, because many sources list ingredients without quantities."""

    __tablename__ = "recipe_component"
    __table_args__ = (
        CheckConstraint("weight_g IS NULL OR weight_g > 0", name="weight_positive_when_known"),
        Index("uq_recipe_component_position", "recipe_id", "position", unique=True),
        Index("ix_recipe_component_food_recipe", "component_food_id", "recipe_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    recipe_id: Mapped[int] = mapped_column(ForeignKey("recipe.id", ondelete="CASCADE"))
    component_food_id: Mapped[int] = mapped_column(ForeignKey("food.id", ondelete="RESTRICT"))
    position: Mapped[int] = mapped_column(SmallInteger)
    weight_g: Mapped[float | None] = mapped_column(Amount)
    display_amount: Mapped[str | None] = mapped_column(String(80))
    role_id: Mapped[int | None] = mapped_column(
        ForeignKey("ingredient_role.id", ondelete="RESTRICT"), index=True
    )
    is_optional: Mapped[bool] = mapped_column(Boolean, default=False)
    # USDA's code for how this ingredient's nutrients survive cooking. The factors themselves are in
    # a separate USDA table that is not loaded yet, so this keeps the link rather than losing it.
    retention_code: Mapped[int | None] = mapped_column(SmallInteger)


class PreparationMethod(Base):
    __tablename__ = "preparation_method"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(80), unique=True)
    name: Mapped[str] = mapped_column(String(160))


class RecipePreparation(Base):
    __tablename__ = "recipe_preparation"

    recipe_id: Mapped[int] = mapped_column(
        ForeignKey("recipe.id", ondelete="CASCADE"), primary_key=True
    )
    preparation_method_id: Mapped[int] = mapped_column(
        ForeignKey("preparation_method.id", ondelete="RESTRICT"), primary_key=True
    )


class PreparationEffect(Sourced, Base):
    """MODIFIES. How a method tends to change a nutrient, with a retention factor when known."""

    __tablename__ = "preparation_effect"
    __table_args__ = (
        CheckConstraint(
            "retention_factor IS NULL OR retention_factor >= 0", name="retention_not_negative"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    preparation_method_id: Mapped[int] = mapped_column(
        ForeignKey("preparation_method.id", ondelete="CASCADE"), index=True
    )
    nutrient_id: Mapped[int] = mapped_column(
        ForeignKey("nutrient.id", ondelete="CASCADE"), index=True
    )
    direction: Mapped[EffectDirection] = mapped_column(enum_type(EffectDirection))
    retention_factor: Mapped[float | None] = mapped_column(Amount)
    evidence_level: Mapped[EvidenceLevel] = mapped_column(enum_type(EvidenceLevel))
    notes: Mapped[str | None] = mapped_column(Text)
