"""Loads what USDA does not supply: allergen findings, and the curated ingredient swaps.

Both run after USDA foods are loaded, because they refer to those foods. Loading twice leaves the
same result, since each run replaces only the rows that this project's own sources own.
"""

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Self

import structlog
import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from app.db.models import (
    Allergen,
    Food,
    FoodAllergen,
    FoodClassification,
    FoodExternalRef,
    FoodRole,
    FoodSensory,
    IngredientRole,
    Recipe,
    RecipeComponent,
    SensoryAttribute,
    Source,
    SubstitutionComponent,
    SubstitutionOption,
)
from app.domain.allergens import AllergenRecipeNode, derive_allergens
from app.domain.enums import (
    AllergenRelation,
    ExternalSystem,
    FoodClassificationKind,
    SensoryKind,
    Verification,
)
from app.ingest.vocabulary import CURATED_DIR

log = structlog.get_logger()

SUBSTITUTIONS_PATH = CURATED_DIR / "substitutions.yaml"
DERIVED_SOURCE_KEY = "nourisearch-derived-from-fdc"
DIET_RULE_NOTE = "Hand assessment in substitutions.yaml."


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FoodRecordRef(_Strict):
    system: ExternalSystem
    id: str
    # Repeated from USDA so a shifted ID fails loudly rather than swapping in another food.
    name: str


class CuratedFood(_Strict):
    key: str
    role: str
    diet: str = Field(pattern="^(vegan|vegetarian|omnivore)$")
    contains: tuple[str, ...] = ()
    may_contain: tuple[str, ...] = ()
    flavor: dict[str, int] = Field(default_factory=dict)
    texture: dict[str, int] = Field(default_factory=dict)
    records: tuple[FoodRecordRef, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def intensities_are_in_range(self) -> Self:
        for attribute, intensity in (*self.flavor.items(), *self.texture.items()):
            # 1 would mean "absent", which leaving the attribute out already says.
            if not 2 <= intensity <= 5:
                raise ValueError(f"{self.key}: {attribute} must be from 2 to 5.")
        if set(self.contains) & set(self.may_contain):
            raise ValueError(f"{self.key}: an allergen cannot be in both lists.")
        return self


class SwapTarget(_Strict):
    food: str
    ratio: float = Field(gt=0, le=20)


class CuratedSwap(_Strict):
    # The key names the from-food in `foods`.
    from_: str = Field(alias="from")
    to: tuple[SwapTarget, ...] = Field(min_length=1)
    fit: int = Field(ge=1, le=5)
    note: str = Field(min_length=1)


class SubstitutionFile(_Strict):
    source: str
    foods: tuple[CuratedFood, ...]
    swaps: tuple[CuratedSwap, ...]

    @model_validator(mode="after")
    def references_resolve(self) -> Self:
        keys = [food.key for food in self.foods]
        duplicates = {key for key in keys if keys.count(key) > 1}
        if duplicates:
            raise ValueError(f"Duplicate food keys: {sorted(duplicates)}")
        records = [(r.system, r.id) for food in self.foods for r in food.records]
        repeated = {record for record in records if records.count(record) > 1}
        if repeated:
            raise ValueError(f"USDA records listed twice: {sorted(repeated)}")
        known = set(keys)
        for swap in self.swaps:
            names = [swap.from_, *(target.food for target in swap.to)]
            unknown = [name for name in names if name not in known]
            if unknown:
                raise ValueError(f"A swap names unknown foods: {unknown}")
            targets = [target.food for target in swap.to]
            if len(targets) != len(set(targets)):
                raise ValueError(f"A swap from {swap.from_} names a food twice.")
        return self


def read_substitutions(path: Path = SUBSTITUTIONS_PATH) -> SubstitutionFile:
    with path.open(encoding="utf-8") as handle:
        return SubstitutionFile.model_validate(yaml.safe_load(handle))


def _key_map(session: Session, model: type[Allergen] | type[IngredientRole]) -> dict[str, int]:
    return {row[0]: row[1] for row in session.execute(select(model.key, model.id))}


def _source_id(session: Session, key: str) -> int:
    source_id = session.scalar(select(Source.id).where(Source.key == key))
    if source_id is None:
        raise ValueError(f"The vocabulary has no source {key}. Load it first.")
    return source_id


def load_allergen_findings(session: Session) -> int:
    """Replaces allergen findings from names and recipes, for every food."""
    source_id = _source_id(session, DERIVED_SOURCE_KEY)
    allergen_ids = _key_map(session, Allergen)

    components: dict[int, list[int]] = defaultdict(list)
    rows = session.execute(
        select(Recipe.dish_id, RecipeComponent.component_food_id).join(
            RecipeComponent, RecipeComponent.recipe_id == Recipe.id
        )
    )
    for dish_id, food_id in rows:
        components[dish_id].append(food_id)
    nodes = {
        food_id: AllergenRecipeNode(food_id, name, tuple(components.get(food_id, ())))
        for food_id, name in session.execute(select(Food.id, Food.canonical_name))
    }

    session.execute(delete(FoodAllergen).where(FoodAllergen.source_id == source_id))
    findings = [
        {
            "food_id": food_id,
            "allergen_id": allergen_ids[key],
            "source_id": source_id,
            "relation": relation,
            "verification": Verification.ESTIMATED,
        }
        for food_id, found in derive_allergens(nodes).items()
        for key, relation in found.items()
    ]
    if findings:
        session.execute(insert(FoodAllergen), findings)
    return len(findings)


@dataclass(frozen=True, slots=True)
class CuratedLoadResult:
    foods: int
    swaps: int
    # Records in the curated file that this database does not hold. Empty on a full USDA load.
    missing_records: tuple[str, ...]


def _record_ids(
    session: Session, data: SubstitutionFile
) -> tuple[dict[tuple[ExternalSystem, str], int], list[str], list[str]]:
    wanted = [r for food in data.foods for r in food.records]
    rows = session.execute(
        select(
            FoodExternalRef.system,
            FoodExternalRef.external_id,
            FoodExternalRef.food_id,
            Food.canonical_name,
        )
        .join(Food, Food.id == FoodExternalRef.food_id)
        .where(FoodExternalRef.system.in_({r.system for r in wanted}))
        .where(FoodExternalRef.external_id.in_({r.id for r in wanted}))
    ).all()
    found = {(row[0], row[1]): (row[2], row[3]) for row in rows}
    ids: dict[tuple[ExternalSystem, str], int] = {}
    missing: list[str] = []
    mismatched: list[str] = []
    for record in wanted:
        hit = found.get((record.system, record.id))
        if hit is None:
            missing.append(f"{record.system.value}:{record.id} {record.name}")
        elif hit[1] != record.name:
            mismatched.append(
                f"{record.system.value}:{record.id} is {hit[1]!r}, not {record.name!r}"
            )
        else:
            ids[(record.system, record.id)] = hit[0]
    return ids, missing, mismatched


def _food_ids(food: CuratedFood, ids: dict[tuple[ExternalSystem, str], int]) -> Sequence[int]:
    resolved = [ids.get((record.system, record.id)) for record in food.records]
    return [food_id for food_id in resolved if food_id is not None]


def load_curated_knowledge(
    session: Session, data: SubstitutionFile | None = None
) -> CuratedLoadResult:
    """Replaces this file's roles, sensory data, allergen assessments, and swaps.

    A food the database does not hold is skipped and reported, so a small test load still works. A
    name that no longer matches is an error, because that ID now means a different food.
    """
    data = data or read_substitutions()
    source_id = _source_id(session, data.source)
    ids, missing, mismatched = _record_ids(session, data)
    if mismatched:
        raise ValueError(f"Curated food records no longer match USDA: {mismatched}")

    role_ids = _key_map(session, IngredientRole)
    allergen_ids = _key_map(session, Allergen)
    attributes = {
        row[0]: (row[1], row[2])
        for row in session.execute(
            select(SensoryAttribute.key, SensoryAttribute.id, SensoryAttribute.kind)
        )
    }

    for model in (FoodRole, FoodSensory, FoodAllergen, FoodClassification, SubstitutionOption):
        session.execute(delete(model).where(model.source_id == source_id))

    offered: dict[str, int] = {}
    members: dict[str, Sequence[int]] = {}
    for food in data.foods:
        food_ids = _food_ids(food, ids)
        members[food.key] = food_ids
        first = ids.get((food.records[0].system, food.records[0].id))
        if first is not None:
            offered[food.key] = first
        for food_id in food_ids:
            session.add(
                FoodRole(
                    food_id=food_id,
                    role_id=role_ids[food.role],
                    source_id=source_id,
                    is_offered=food_id == first,
                )
            )
            for kind, profile in (
                (SensoryKind.FLAVOR, food.flavor),
                (SensoryKind.TEXTURE, food.texture),
            ):
                for attribute, intensity in profile.items():
                    attribute_id, attribute_kind = attributes[attribute]
                    if attribute_kind is not kind:
                        raise ValueError(f"{food.key}: {attribute} is not a {kind.value}.")
                    session.add(
                        FoodSensory(
                            food_id=food_id,
                            attribute_id=attribute_id,
                            source_id=source_id,
                            intensity=intensity,
                        )
                    )
            for relation, keys in (
                (AllergenRelation.CONTAINS, food.contains),
                (AllergenRelation.MAY_CONTAIN, food.may_contain),
            ):
                for key in keys:
                    session.add(
                        FoodAllergen(
                            food_id=food_id,
                            allergen_id=allergen_ids[key],
                            source_id=source_id,
                            relation=relation,
                            verification=Verification.TYPICAL,
                        )
                    )
            for kind_of_food in _diet_classifications(food.diet):
                session.add(
                    FoodClassification(
                        food_id=food_id,
                        classification=kind_of_food,
                        source_id=source_id,
                        verification=Verification.TYPICAL,
                        rule_note=DIET_RULE_NOTE,
                    )
                )
    session.flush()

    swaps_loaded = 0
    for swap in data.swaps:
        targets = [(offered.get(target.food), target.ratio) for target in swap.to]
        if any(food_id is None for food_id, _ in targets):
            continue
        for from_food_id in members[swap.from_]:
            option = SubstitutionOption(
                from_food_id=from_food_id,
                verification=Verification.TYPICAL,
                culinary_fit=swap.fit,
                notes=swap.note,
                source_id=source_id,
            )
            session.add(option)
            session.flush()
            for to_food_id, ratio in targets:
                session.add(
                    SubstitutionComponent(
                        option_id=option.id, to_food_id=to_food_id, ratio_by_weight=ratio
                    )
                )
            swaps_loaded += 1
    session.flush()

    result = CuratedLoadResult(len(data.foods), swaps_loaded, tuple(missing))
    log.info(
        "curated_knowledge_loaded",
        foods=result.foods,
        swaps=result.swaps,
        missing_records=len(result.missing_records),
    )
    return result


def _diet_classifications(diet: str) -> tuple[FoodClassificationKind, ...]:
    if diet == "omnivore":
        return (FoodClassificationKind.MEAT_OR_FISH, FoodClassificationKind.ANIMAL_DERIVED)
    if diet == "vegetarian":
        return (FoodClassificationKind.ANIMAL_DERIVED,)
    return ()


def load_knowledge(session: Session) -> None:
    """Everything that follows a USDA load. A curated swap's allergens build on the name rules."""
    count = load_allergen_findings(session)
    log.info("allergen_findings_loaded", findings=count)
    load_curated_knowledge(session)
