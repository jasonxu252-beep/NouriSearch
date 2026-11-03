"""The daily amounts to compare a food against, for a person's age and sex.

The nutrient marks do not use these. A "High" mark applies the FDA's 20% line, which is defined only
for FDA Daily Values, so it stays the same whatever group is chosen. This changes what the bars and
percents compare with.
"""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.domain.enums import ReferenceKind, ReferencePopulation
from app.repositories.foods import SourceRecord, load_reference_values, load_sources


@dataclass(frozen=True, slots=True)
class ReferenceValue:
    nutrient_key: str
    amount: float
    unit: str
    kind: ReferenceKind
    source_key: str
    # True when no value exists for this group, so the general one applies instead.
    is_general: bool


@dataclass(frozen=True, slots=True)
class ReferenceIntakes:
    population: ReferencePopulation
    values: tuple[ReferenceValue, ...]
    sources: tuple[SourceRecord, ...]


def reference_intakes(session: Session, population: ReferencePopulation) -> ReferenceIntakes:
    records = load_reference_values(session, population)
    chosen = {record.nutrient_key: record for record in records if record.is_general}
    chosen.update({r.nutrient_key: r for r in records if not r.is_general})

    sources = load_sources(session, sorted({record.source_id for record in chosen.values()}))
    keys = {source.id: source.key for source in sources}
    return ReferenceIntakes(
        population=population,
        values=tuple(
            ReferenceValue(
                nutrient_key=record.nutrient_key,
                amount=record.amount,
                unit=record.unit,
                kind=record.kind,
                source_key=keys[record.source_id],
                is_general=record.is_general,
            )
            for record in chosen.values()
        ),
        sources=tuple(sources),
    )
