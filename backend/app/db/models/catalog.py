"""Foods and how they are named, grouped, classified, and pictured."""

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, SmallInteger, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models._types import Amount, Sourced, enum_type
from app.domain.enums import AliasType, ExternalSystem, FoodKind, ProcessingLevel, Verification


class FoodGroup(Base):
    __tablename__ = "food_group"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(80), unique=True)
    name: Mapped[str] = mapped_column(String(160))
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("food_group.id", ondelete="RESTRICT"), index=True
    )


class Food(Sourced, Base):
    """A food, dish, packaged product, or additive. Any of them can be an ingredient."""

    __tablename__ = "food"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(200), unique=True)
    kind: Mapped[FoodKind] = mapped_column(enum_type(FoodKind), index=True)
    canonical_name: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    food_group_id: Mapped[int | None] = mapped_column(
        ForeignKey("food_group.id", ondelete="RESTRICT"), index=True
    )
    processing_level: Mapped[ProcessingLevel] = mapped_column(
        enum_type(ProcessingLevel), default=ProcessingLevel.UNKNOWN, index=True
    )


class FoodAlias(Sourced, Base):
    """A name for a food in one language. Machine translations are labeled by their alias type."""

    __tablename__ = "food_alias"
    __table_args__ = (
        CheckConstraint("language ~ '^[a-z]{2,3}(-[A-Za-z0-9]+)*$'", name="language_is_bcp47"),
        CheckConstraint("length(normalized_name) > 0", name="normalized_name_not_empty"),
        Index("uq_food_alias_identity", "food_id", "language", "normalized_name", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    food_id: Mapped[int] = mapped_column(ForeignKey("food.id", ondelete="CASCADE"), index=True)
    language: Mapped[str] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(Text)
    normalized_name: Mapped[str] = mapped_column(Text)
    alias_type: Mapped[AliasType] = mapped_column(enum_type(AliasType))


class FoodExternalRef(Base):
    """Identifiers in outside systems. A pointer to a record, not a claim about the food."""

    __tablename__ = "food_external_ref"

    food_id: Mapped[int] = mapped_column(ForeignKey("food.id", ondelete="CASCADE"), index=True)
    system: Mapped[ExternalSystem] = mapped_column(enum_type(ExternalSystem), primary_key=True)
    external_id: Mapped[str] = mapped_column(String(80), primary_key=True)


class FoodPortion(Sourced, Base):
    """A household serving and its weight, such as one cup at 162 g."""

    __tablename__ = "food_portion"
    __table_args__ = (
        CheckConstraint("gram_weight > 0", name="gram_weight_positive"),
        Index("uq_food_portion_identity", "food_id", "description", "source_id", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    food_id: Mapped[int] = mapped_column(ForeignKey("food.id", ondelete="CASCADE"), index=True)
    description: Mapped[str] = mapped_column(Text)
    gram_weight: Mapped[float] = mapped_column(Amount)
    # A named household measure, such as "1 cup", rather than "Quantity not specified".
    is_household_measure: Mapped[bool] = mapped_column(server_default=text("true"))


class FoodImage(Sourced, Base):
    """Licensing is required, because every displayed image must be attributable."""

    __tablename__ = "food_image"
    __table_args__ = (Index("uq_food_image_position", "food_id", "position", unique=True),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    food_id: Mapped[int] = mapped_column(ForeignKey("food.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(SmallInteger, default=0)
    url: Mapped[str] = mapped_column(Text)
    license: Mapped[str] = mapped_column(String(80))
    attribution: Mapped[str] = mapped_column(Text)


class Cuisine(Base):
    """A culinary tradition, hierarchical so Sichuan can sit under Chinese."""

    __tablename__ = "cuisine"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(80), unique=True)
    name: Mapped[str] = mapped_column(String(160))
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("cuisine.id", ondelete="RESTRICT"), index=True
    )


class FoodCuisine(Sourced, Base):
    """BELONGS_TO. A culinary classification of the food, never a statement about people."""

    __tablename__ = "food_cuisine"
    __table_args__ = (Index("ix_food_cuisine_cuisine", "cuisine_id", "food_id"),)

    food_id: Mapped[int] = mapped_column(
        ForeignKey("food.id", ondelete="CASCADE"), primary_key=True
    )
    cuisine_id: Mapped[int] = mapped_column(
        ForeignKey("cuisine.id", ondelete="RESTRICT"), primary_key=True
    )
    source_id: Mapped[int] = mapped_column(
        ForeignKey("source.id", ondelete="RESTRICT"), primary_key=True
    )
    verification: Mapped[Verification] = mapped_column(enum_type(Verification))
