"""Which ingredients can stand in for others, and the sensory data used to rank them."""

from sqlalchemy import CheckConstraint, ForeignKey, Integer, SmallInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models._types import Amount, Sourced, enum_type
from app.domain.enums import SensoryKind, Verification


class SubstitutionOption(Sourced, Base):
    """CAN_SUBSTITUTE_FOR, optionally limited to one role or cuisine.

    An option owns its replacement components, because one ingredient may be replaced by several.
    """

    __tablename__ = "substitution_option"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    from_food_id: Mapped[int] = mapped_column(ForeignKey("food.id", ondelete="CASCADE"), index=True)
    role_id: Mapped[int | None] = mapped_column(
        ForeignKey("ingredient_role.id", ondelete="RESTRICT"), index=True
    )
    cuisine_id: Mapped[int | None] = mapped_column(
        ForeignKey("cuisine.id", ondelete="RESTRICT"), index=True
    )
    verification: Mapped[Verification] = mapped_column(enum_type(Verification))
    notes: Mapped[str | None] = mapped_column(Text)


class SubstitutionComponent(Base):
    __tablename__ = "substitution_component"
    __table_args__ = (CheckConstraint("ratio_by_weight > 0", name="ratio_positive"),)

    option_id: Mapped[int] = mapped_column(
        ForeignKey("substitution_option.id", ondelete="CASCADE"), primary_key=True
    )
    to_food_id: Mapped[int] = mapped_column(
        ForeignKey("food.id", ondelete="RESTRICT"), primary_key=True, index=True
    )
    # Grams of replacement per gram of the original ingredient.
    ratio_by_weight: Mapped[float] = mapped_column(Amount)


class SensoryAttribute(Base):
    __tablename__ = "sensory_attribute"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(80), unique=True)
    name: Mapped[str] = mapped_column(String(160))
    kind: Mapped[SensoryKind] = mapped_column(enum_type(SensoryKind))


class FoodSensory(Sourced, Base):
    __tablename__ = "food_sensory"
    __table_args__ = (CheckConstraint("intensity BETWEEN 1 AND 5", name="intensity_in_range"),)

    food_id: Mapped[int] = mapped_column(
        ForeignKey("food.id", ondelete="CASCADE"), primary_key=True
    )
    attribute_id: Mapped[int] = mapped_column(
        ForeignKey("sensory_attribute.id", ondelete="RESTRICT"), primary_key=True, index=True
    )
    source_id: Mapped[int] = mapped_column(
        ForeignKey("source.id", ondelete="RESTRICT"), primary_key=True
    )
    intensity: Mapped[int] = mapped_column(SmallInteger)
