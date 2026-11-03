"""Loads sources, nutrients, and controlled vocabularies from validated YAML files.

Files are checked before anything is written, and loading twice leaves the same result.
"""

from datetime import date
from pathlib import Path
from typing import Any, Self

import structlog
import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db.models import (
    Allergen,
    Cuisine,
    FoodGroup,
    IngredientRole,
    Nutrient,
    NutrientReferenceValue,
    NutrientSourceCode,
    PreparationMethod,
    SensoryAttribute,
    Source,
)
from app.domain.enums import (
    NutrientCategory,
    NutrientDirection,
    ReferenceKind,
    SensoryKind,
    SourceTier,
)

log = structlog.get_logger()

CURATED_DIR = Path(__file__).resolve().parents[2] / "data" / "curated"
FDC_SYSTEM = "fdc"
DV_SOURCE_KEY = "fda-daily-values"
ALLERGEN_SOURCE_KEY = "fda-major-allergens"
GENERAL_LABEL_POPULATION = "general_label"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SourceEntry(_Strict):
    key: str
    publisher: str
    title: str
    url: str | None = None
    version: str | None = None
    retrieved_on: date | None = None
    license: str | None = None
    tier: SourceTier
    priority: int = Field(default=100, ge=0)


class NutrientEntry(_Strict):
    key: str
    name: str
    unit: str
    category: NutrientCategory
    direction: NutrientDirection
    parent: str | None = None
    fdc_codes: list[str]
    dv: float | None = Field(default=None, ge=0)


class NamedEntry(_Strict):
    key: str
    name: str
    parent: str | None = None


class SensoryEntry(_Strict):
    key: str
    name: str
    kind: SensoryKind


class Vocabularies(_Strict):
    allergens: list[NamedEntry]
    cuisines: list[NamedEntry]
    food_groups: list[NamedEntry]
    ingredient_roles: list[NamedEntry]
    preparation_methods: list[NamedEntry]
    sensory_attributes: list[SensoryEntry]


class CuratedBundle(_Strict):
    """Everything in the curated files, cross-checked as one unit."""

    sources: list[SourceEntry]
    nutrients: list[NutrientEntry]
    vocabularies: Vocabularies

    @model_validator(mode="after")
    def check_references(self) -> Self:
        for label, keys in (
            ("source", [s.key for s in self.sources]),
            ("nutrient", [n.key for n in self.nutrients]),
            ("allergen", [e.key for e in self.vocabularies.allergens]),
            ("cuisine", [e.key for e in self.vocabularies.cuisines]),
            ("food group", [e.key for e in self.vocabularies.food_groups]),
        ):
            duplicates = {k for k in keys if keys.count(k) > 1}
            if duplicates:
                raise ValueError(f"Duplicate {label} keys: {sorted(duplicates)}")

        source_keys = {s.key for s in self.sources}
        for required in (DV_SOURCE_KEY, ALLERGEN_SOURCE_KEY):
            if required not in source_keys:
                raise ValueError(f"Missing required source: {required}")

        nutrient_keys = {n.key for n in self.nutrients}
        for nutrient in self.nutrients:
            if nutrient.parent and nutrient.parent not in nutrient_keys:
                raise ValueError(f"Nutrient {nutrient.key} has unknown parent {nutrient.parent}")

        codes = [code for n in self.nutrients for code in n.fdc_codes]
        duplicate_codes = {c for c in codes if codes.count(c) > 1}
        if duplicate_codes:
            raise ValueError(f"USDA codes mapped twice: {sorted(duplicate_codes)}")
        return self


def read_bundle(directory: Path = CURATED_DIR) -> CuratedBundle:
    def read(name: str) -> Any:
        with (directory / name).open(encoding="utf-8") as handle:
            return yaml.safe_load(handle)

    return CuratedBundle(
        sources=read("sources.yaml"),
        nutrients=read("nutrients.yaml"),
        vocabularies=read("vocabularies.yaml"),
    )


def _upsert_by_key(session: Session, model: type[Any], rows: list[dict[str, Any]]) -> None:
    """Inserts or updates rows by their stable key."""
    if not rows:
        return
    statement = insert(model).values(rows)
    updates = {column: statement.excluded[column] for column in rows[0] if column not in ("key",)}
    session.execute(statement.on_conflict_do_update(index_elements=["key"], set_=updates))


def _key_map(session: Session, model: type[Any]) -> dict[str, int]:
    return {row.key: row.id for row in session.execute(select(model.key, model.id))}


def _upsert_tree(session: Session, model: type[Any], entries: list[NamedEntry]) -> None:
    """Parents first, then a second pass links children, so file order does not matter."""
    _upsert_by_key(
        session, model, [{"key": e.key, "name": e.name, "parent_id": None} for e in entries]
    )
    ids = _key_map(session, model)
    for entry in entries:
        if entry.parent:
            session.get_one(model, ids[entry.key]).parent_id = ids[entry.parent]
    session.flush()


def load_vocabulary(session: Session, bundle: CuratedBundle | None = None) -> dict[str, int]:
    """Loads the curated vocabulary into the session's transaction. Returns row counts."""
    data = bundle or read_bundle()

    _upsert_by_key(session, Source, [s.model_dump() for s in data.sources])
    source_ids = _key_map(session, Source)

    _upsert_by_key(
        session,
        Nutrient,
        [
            {
                "key": n.key,
                "name": n.name,
                "unit": n.unit,
                "category": n.category,
                "direction": n.direction,
                "display_order": order,
                "parent_id": None,
            }
            for order, n in enumerate(data.nutrients)
        ],
    )
    nutrient_ids = _key_map(session, Nutrient)
    for entry in data.nutrients:
        if entry.parent:
            session.get_one(Nutrient, nutrient_ids[entry.key]).parent_id = nutrient_ids[
                entry.parent
            ]
    session.flush()

    code_rows = [
        {
            "system": FDC_SYSTEM,
            "code": code,
            "nutrient_id": nutrient_ids[n.key],
            "preference": preference,
        }
        for n in data.nutrients
        for preference, code in enumerate(n.fdc_codes)
    ]
    code_statement = insert(NutrientSourceCode).values(code_rows)
    session.execute(
        code_statement.on_conflict_do_update(
            index_elements=["system", "code"],
            set_={
                "nutrient_id": code_statement.excluded.nutrient_id,
                "preference": code_statement.excluded.preference,
            },
        )
    )

    dv_rows = [
        {
            "nutrient_id": nutrient_ids[n.key],
            "kind": ReferenceKind.DV,
            "population": GENERAL_LABEL_POPULATION,
            "amount": n.dv,
            "source_id": source_ids[DV_SOURCE_KEY],
        }
        for n in data.nutrients
        if n.dv is not None
    ]
    dv_statement = insert(NutrientReferenceValue).values(dv_rows)
    session.execute(
        dv_statement.on_conflict_do_update(
            index_elements=["nutrient_id", "kind", "population", "source_id"],
            set_={"amount": dv_statement.excluded.amount},
        )
    )

    vocab = data.vocabularies
    _upsert_by_key(
        session,
        Allergen,
        [
            {
                "key": a.key,
                "name": a.name,
                "is_us_major": True,
                "source_id": source_ids[ALLERGEN_SOURCE_KEY],
            }
            for a in vocab.allergens
        ],
    )
    _upsert_tree(session, Cuisine, vocab.cuisines)
    _upsert_tree(session, FoodGroup, vocab.food_groups)
    _upsert_by_key(
        session, IngredientRole, [{"key": e.key, "name": e.name} for e in vocab.ingredient_roles]
    )
    _upsert_by_key(
        session,
        PreparationMethod,
        [{"key": e.key, "name": e.name} for e in vocab.preparation_methods],
    )
    _upsert_by_key(
        session,
        SensoryAttribute,
        [{"key": e.key, "name": e.name, "kind": e.kind} for e in vocab.sensory_attributes],
    )

    counts = {
        "sources": len(data.sources),
        "nutrients": len(data.nutrients),
        "daily_values": len(dv_rows),
        "usda_codes": len(code_rows),
        "allergens": len(vocab.allergens),
        "cuisines": len(vocab.cuisines),
    }
    log.info("vocabulary_loaded", **counts)
    return counts
