"""Column helpers used across the schema."""

from enum import StrEnum

from sqlalchemy import Enum, ForeignKey, Integer, Numeric
from sqlalchemy.orm import Mapped, declared_attr, mapped_column

# USDA amounts range from micrograms to tens of thousands of milligrams per 100 g.
Amount = Numeric(14, 5, asdecimal=False)


def enum_type(enum_class: type[StrEnum]) -> Enum:
    """Stores the value as text with a CHECK constraint, so adding a value needs no type change."""
    return Enum(
        enum_class,
        native_enum=False,
        create_constraint=True,
        length=32,
        name=enum_class.__name__.lower(),
        values_callable=lambda e: [member.value for member in e],
    )


class Sourced:
    """A fact that cannot exist without a citation. Every knowledge table inherits this."""

    @declared_attr
    def source_id(cls) -> Mapped[int]:
        return mapped_column(
            Integer, ForeignKey("source.id", ondelete="RESTRICT"), nullable=False, index=True
        )
