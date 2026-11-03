"""Loads normalized USDA foods into PostgreSQL. Safe to run repeatedly.

Foods are matched by their FDC ID and updated in place, so curated data pointing at them stays valid
even if USDA renames one. Values, portions, recipes, and aliases belong to one dataset version, so
they are replaced as a set in one transaction, and readers never see a partial load.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import psycopg
import structlog
from sqlalchemy import CursorResult, Engine, select, text
from sqlalchemy.orm import Session

from app.db.models import FoodGroup, NutrientSourceCode, Source
from app.domain.enums import AliasType, ExternalSystem, FoodKind, Verification
from app.domain.text import normalize_name, slugify
from app.ingest.fdc_rules import (
    CLASSIFICATION_SOURCE_KEY,
    FdcMappings,
    IngredientRecord,
    food_group_key,
    food_kind,
    is_discoverable,
    is_household_measure,
    processing_level,
    resolve_ingredient,
    value_kind,
)
from app.ingest.vocabulary import FDC_SYSTEM
from app.integrations.fdc_bulk import (
    FdcDataset,
    FdcFood,
    FdcIngredient,
    download_dataset,
    read_foods,
)

log = structlog.get_logger()

RECIPE_LABEL = "USDA survey recipe"
_MAX_SLUG_NAME = 180

# FNDDS loads last because its recipes cite foods from the other two.
LOAD_ORDER = (FdcDataset.FOUNDATION, FdcDataset.SR_LEGACY, FdcDataset.FNDDS)

_SAME_FOOD_RATIONALE = (
    "USDA gives this Foundation record and an SR Legacy record the same number for the same food. "
    "SR Legacy's value fills a gap Foundation has not measured."
)


@dataclass(frozen=True, slots=True)
class LoadCounts:
    foods: int
    nutrient_values: int
    portions: int
    recipes: int
    recipe_components: int
    placeholder_ingredients: int


def food_slug(description: str, fdc_id: int) -> str:
    return f"{slugify(description)[:_MAX_SLUG_NAME].strip('-')}-{fdc_id}"


def _copy_to_temp(
    session: Session, table: str, columns: str, rows: Iterable[Sequence[Any]]
) -> None:
    """Streams rows into a temporary table through COPY, the fastest path into PostgreSQL."""
    raw = session.connection().connection.dbapi_connection
    if raw is None:
        raise RuntimeError("No database connection is available.")
    with cast("psycopg.Connection[Any]", raw).cursor() as cursor:
        cursor.execute(f"CREATE TEMP TABLE {table} ({columns}) ON COMMIT DROP")
        with cursor.copy(f"COPY {table} FROM STDIN") as copy:
            for row in rows:
                copy.write_row(row)


def _rows_affected(session: Session, statement: str) -> int:
    result = session.execute(text(statement))
    return int(cast("CursorResult[Any]", result).rowcount)


def _load_nutrient_codes(session: Session) -> dict[str, tuple[int, int]]:
    rows = session.execute(
        select(
            NutrientSourceCode.code, NutrientSourceCode.nutrient_id, NutrientSourceCode.preference
        ).where(NutrientSourceCode.system == FDC_SYSTEM)
    )
    return {code: (nutrient_id, preference) for code, nutrient_id, preference in rows}


def _nutrient_rows(
    foods: Sequence[FdcFood],
    food_ids: Mapping[int, int],
    codes: Mapping[str, tuple[int, int]],
    source_id: int,
) -> Iterable[tuple[int, int, int, float, str, str | None]]:
    """One row per food and nutrient. Where a food has two codes, the preferred code wins."""
    for food in foods:
        best: dict[int, tuple[int, float, str | None]] = {}
        for nutrient in food.nutrients:
            mapped = codes.get(nutrient.number)
            if mapped is None:
                continue
            nutrient_id, preference = mapped
            current = best.get(nutrient_id)
            if current is None or preference < current[0]:
                best[nutrient_id] = (preference, nutrient.amount, nutrient.derivation)
        for nutrient_id, (_, amount, derivation) in best.items():
            yield (
                food_ids[food.fdc_id],
                nutrient_id,
                source_id,
                amount,
                value_kind(derivation).value,
                derivation,
            )


def _upsert_foods(
    session: Session,
    foods: Sequence[FdcFood],
    source_id: int,
    classification_source_id: int,
    mappings: FdcMappings,
) -> dict[int, int]:
    """Returns food IDs by FDC ID. A food's slug is set once, so links to it keep working."""
    group_ids = {row[0]: row[1] for row in session.execute(select(FoodGroup.key, FoodGroup.id))}

    def rows() -> Iterable[tuple[Any, ...]]:
        for food in foods:
            group = food_group_key(food.dataset, food.category, food.description, mappings)
            kind = food_kind(
                food.dataset,
                food.category,
                food.description,
                group,
                len(food.ingredients),
                mappings,
            )
            yield (
                food.fdc_id,
                food_slug(food.description, food.fdc_id),
                kind.value,
                food.description,
                group_ids.get(group) if group else None,
                processing_level(food.description, kind, group).value,
                is_discoverable(food.description, group),
                source_id,
                classification_source_id,
            )

    _copy_to_temp(
        session,
        "tmp_food",
        "fdc_id int, slug text, kind text, canonical_name text, food_group_id int, "
        "processing_level text, is_discoverable boolean, source_id int, "
        "classification_source_id int",
        rows(),
    )
    fdc = {"fdc": ExternalSystem.FDC.value}
    updated = session.execute(
        text(
            """
            UPDATE food f SET
                kind = t.kind,
                canonical_name = t.canonical_name,
                food_group_id = t.food_group_id,
                processing_level = t.processing_level,
                is_discoverable = t.is_discoverable,
                source_id = t.source_id,
                classification_source_id = t.classification_source_id
            FROM tmp_food t
            JOIN food_external_ref r ON r.system = :fdc AND r.external_id = t.fdc_id::text
            WHERE f.id = r.food_id
            RETURNING t.fdc_id, f.id
            """
        ),
        fdc,
    )
    food_ids = {row[0]: row[1] for row in updated}
    inserted = session.execute(
        text(
            """
            INSERT INTO food (slug, kind, canonical_name, food_group_id, processing_level,
                              is_discoverable, source_id, classification_source_id)
            SELECT slug, kind, canonical_name, food_group_id, processing_level,
                   is_discoverable, source_id, classification_source_id
            FROM tmp_food t
            WHERE NOT EXISTS (
                SELECT 1 FROM food_external_ref r
                WHERE r.system = :fdc AND r.external_id = t.fdc_id::text
            )
            RETURNING id, slug
            """
        ),
        fdc,
    )
    new_ids = {row[1]: row[0] for row in inserted}
    session.execute(text("DROP TABLE tmp_food"))

    for food in foods:
        new_id = new_ids.get(food_slug(food.description, food.fdc_id))
        if new_id is not None:
            food_ids[food.fdc_id] = new_id
    return food_ids


def _upsert_external_refs(
    session: Session, foods: Sequence[FdcFood], food_ids: Mapping[int, int]
) -> None:
    def rows() -> Iterable[tuple[int, str, str]]:
        for food in foods:
            food_id = food_ids[food.fdc_id]
            yield (food_id, ExternalSystem.FDC.value, str(food.fdc_id))
            # Both datasets use NDB numbers, and share many of them, so each has its own system.
            if food.dataset is FdcDataset.SR_LEGACY and food.ndb_number:
                yield (food_id, ExternalSystem.NDB_NUMBER.value, food.ndb_number)
            if food.dataset is FdcDataset.FOUNDATION and food.ndb_number:
                yield (food_id, ExternalSystem.FOUNDATION_NDB.value, food.ndb_number)
            if food.dataset is FdcDataset.FNDDS and food.food_code:
                yield (food_id, ExternalSystem.FNDDS_CODE.value, food.food_code)

    _copy_to_temp(session, "tmp_ref", "food_id int, system text, external_id text", rows())
    session.execute(
        text(
            """
            INSERT INTO food_external_ref (food_id, system, external_id)
            SELECT food_id, system, external_id FROM tmp_ref
            ON CONFLICT (system, external_id) DO UPDATE SET food_id = EXCLUDED.food_id
            """
        )
    )
    session.execute(text("DROP TABLE tmp_ref"))


def _replace_nutrients(
    session: Session, foods: Sequence[FdcFood], food_ids: Mapping[int, int], source_id: int
) -> int:
    session.execute(text("DELETE FROM food_nutrient WHERE source_id = :s"), {"s": source_id})
    codes = _load_nutrient_codes(session)
    _copy_to_temp(
        session,
        "tmp_nutrient",
        "food_id int, nutrient_id int, source_id int, amount float8, value_kind text, "
        "derivation text",
        _nutrient_rows(foods, food_ids, codes, source_id),
    )
    count = _rows_affected(
        session,
        """
        INSERT INTO food_nutrient (food_id, nutrient_id, source_id, amount_per_100g,
                                   value_kind, derivation)
        SELECT food_id, nutrient_id, source_id, amount, value_kind, derivation
        FROM tmp_nutrient
        """,
    )
    session.execute(text("DROP TABLE tmp_nutrient"))
    return count


def _replace_portions(
    session: Session, foods: Sequence[FdcFood], food_ids: Mapping[int, int], source_id: int
) -> int:
    session.execute(text("DELETE FROM food_portion WHERE source_id = :s"), {"s": source_id})

    def rows() -> Iterable[tuple[int, str, float, bool, int, int]]:
        for food in foods:
            for portion in food.portions:
                yield (
                    food_ids[food.fdc_id],
                    portion.description,
                    portion.gram_weight,
                    is_household_measure(portion.description),
                    portion.position,
                    source_id,
                )

    _copy_to_temp(
        session,
        "tmp_portion",
        "food_id int, description text, gram_weight float8, is_household boolean, "
        "position int, source_id int",
        rows(),
    )
    count = _rows_affected(
        session,
        """
        INSERT INTO food_portion (food_id, description, gram_weight, is_household_measure,
                                  position, source_id)
        SELECT food_id, description, gram_weight, is_household, position, source_id
        FROM tmp_portion
        """,
    )
    session.execute(text("DROP TABLE tmp_portion"))
    return count


@dataclass(frozen=True, slots=True)
class _IngredientRecords:
    sr: Mapping[str, IngredientRecord]
    foundation: Mapping[str, IngredientRecord]
    fndds: Mapping[str, IngredientRecord]

    def resolve(self, ingredient: FdcIngredient) -> int | None:
        return resolve_ingredient(
            ingredient.description,
            self.sr.get(ingredient.code),
            self.foundation.get(ingredient.code),
            self.fndds.get(ingredient.code),
        )


def _load_ingredient_records(session: Session) -> _IngredientRecords:
    by_system: dict[str, dict[str, IngredientRecord]] = {
        ExternalSystem.NDB_NUMBER.value: {},
        ExternalSystem.FOUNDATION_NDB.value: {},
        ExternalSystem.FNDDS_CODE.value: {},
    }
    rows = session.execute(
        text(
            """
            SELECT r.system, r.external_id, r.food_id, f.canonical_name
            FROM food_external_ref r
            JOIN food f ON f.id = r.food_id
            WHERE r.system = ANY(CAST(:systems AS text[]))
            """
        ),
        {"systems": list(by_system)},
    )
    for system, code, food_id, name in rows:
        by_system[system][code] = IngredientRecord(food_id, normalize_name(name))
    return _IngredientRecords(
        sr=by_system[ExternalSystem.NDB_NUMBER.value],
        foundation=by_system[ExternalSystem.FOUNDATION_NDB.value],
        fndds=by_system[ExternalSystem.FNDDS_CODE.value],
    )


def _ensure_placeholders(
    session: Session,
    foods: Sequence[FdcFood],
    records: _IngredientRecords,
    source_id: int,
) -> dict[str, int]:
    """USDA sometimes cites an ingredient with no record in any file, such as "Iron as ingredient".
    It stays in the recipe as a food with no nutrient values, so the dish reports it as unknown
    rather than dropping it. Returns the placeholder food IDs by ingredient code."""
    missing: dict[str, str] = {}
    for food in foods:
        for ingredient in food.ingredients:
            if records.resolve(ingredient) is None:
                missing.setdefault(ingredient.code, ingredient.description or "Unnamed ingredient")
    placeholders: dict[str, int] = {}
    for code, description in missing.items():
        slug = f"{slugify(description)[:_MAX_SLUG_NAME].strip('-')}-input-{code}"
        food_id = session.execute(
            text(
                """
                INSERT INTO food (slug, kind, canonical_name, processing_level,
                                  is_discoverable, source_id)
                VALUES (:slug, :kind, :name, 'unknown', false, :source)
                ON CONFLICT (slug) DO UPDATE SET canonical_name = EXCLUDED.canonical_name
                RETURNING id
                """
            ),
            {"slug": slug, "kind": FoodKind.BASIC.value, "name": description, "source": source_id},
        ).scalar_one()
        placeholders[code] = food_id
    return placeholders


def _replace_recipes(
    session: Session,
    foods: Sequence[FdcFood],
    food_ids: Mapping[int, int],
    source_id: int,
) -> tuple[int, int, int]:
    """Creates recipes for foods with two or more ingredients.

    A single-ingredient entry only points USDA at another record, such as a restaurant food. That is
    not a breakdown, so the dish reports having no ingredient data.
    """
    composed = [food for food in foods if len(food.ingredients) >= 2]
    records = _load_ingredient_records(session)
    placeholders = _ensure_placeholders(session, composed, records, source_id)

    session.execute(
        text(
            """
            DELETE FROM recipe
            WHERE source_id = :source AND label = :label
              AND NOT (dish_id = ANY(CAST(:dishes AS integer[])))
            """
        ),
        {
            "source": source_id,
            "label": RECIPE_LABEL,
            "dishes": [food_ids[food.fdc_id] for food in composed],
        },
    )
    _copy_to_temp(
        session,
        "tmp_recipe",
        "dish_id int, label text, verification text, source_id int, moisture float8",
        (
            (
                food_ids[food.fdc_id],
                RECIPE_LABEL,
                Verification.SOURCE_DOCUMENTED.value,
                source_id,
                food.moisture_change_pct,
            )
            for food in composed
        ),
    )
    # A curated recipe may already be a dish's default. USDA's then stays as a second recipe.
    recipe_ids = {
        row[0]: row[1]
        for row in session.execute(
            text(
                """
                INSERT INTO recipe (dish_id, label, verification, source_id, moisture_change_pct,
                                    is_default)
                SELECT t.dish_id, t.label, t.verification, t.source_id, t.moisture,
                       NOT EXISTS (
                           SELECT 1 FROM recipe other
                           WHERE other.dish_id = t.dish_id AND other.is_default
                       )
                FROM tmp_recipe t
                ON CONFLICT (dish_id, source_id, label) DO UPDATE SET
                    verification = EXCLUDED.verification,
                    moisture_change_pct = EXCLUDED.moisture_change_pct
                RETURNING dish_id, id
                """
            )
        )
    }
    session.execute(text("DROP TABLE tmp_recipe"))

    session.execute(
        text("DELETE FROM recipe_component WHERE recipe_id = ANY(CAST(:ids AS integer[]))"),
        {"ids": list(recipe_ids.values())},
    )

    def component_rows() -> Iterable[tuple[int, int, int, float | None, int | None]]:
        for food in composed:
            recipe_id = recipe_ids[food_ids[food.fdc_id]]
            for ingredient in food.ingredients:
                yield (
                    recipe_id,
                    records.resolve(ingredient) or placeholders[ingredient.code],
                    ingredient.position,
                    ingredient.weight_g,
                    ingredient.retention_code,
                )

    _copy_to_temp(
        session,
        "tmp_component",
        "recipe_id int, component_food_id int, position int, weight_g float8, retention_code int",
        component_rows(),
    )
    components = _rows_affected(
        session,
        """
        INSERT INTO recipe_component (recipe_id, component_food_id, position, weight_g,
                                      retention_code, is_optional)
        SELECT recipe_id, component_food_id, position, weight_g, retention_code, false
        FROM tmp_component
        """,
    )
    session.execute(text("DROP TABLE tmp_component"))
    return len(recipe_ids), components, len(placeholders)


def _link_same_food_records(session: Session, source_id: int) -> int:
    """Lets SR Legacy fill the gaps in a Foundation record for the same food.

    A proxy marks every borrowed value as an estimate, so it can never pass for a measurement.
    """
    session.execute(text("DELETE FROM nutrient_proxy WHERE source_id = :s"), {"s": source_id})
    result = session.execute(
        text(
            """
            INSERT INTO nutrient_proxy (food_id, proxy_food_id, rationale, source_id)
            SELECT foundation.food_id, sr.food_id, :rationale, :source
            FROM food_external_ref foundation
            JOIN food_external_ref sr
              ON sr.external_id = foundation.external_id AND sr.system = :sr_system
            WHERE foundation.system = :foundation_system
            """
        ),
        {
            "rationale": _SAME_FOOD_RATIONALE,
            "source": source_id,
            "sr_system": ExternalSystem.NDB_NUMBER.value,
            "foundation_system": ExternalSystem.FOUNDATION_NDB.value,
        },
    )
    return int(cast("CursorResult[Any]", result).rowcount)


def refresh_aliases(session: Session, source_id: int) -> int:
    """Makes each food's English name its alias, which later multilingual search builds on."""
    session.execute(
        text("DELETE FROM food_alias WHERE source_id = :s AND alias_type = :t"),
        {"s": source_id, "t": AliasType.SOURCE_LABEL.value},
    )
    rows = session.execute(
        text("SELECT id, canonical_name FROM food WHERE source_id = :s"), {"s": source_id}
    ).all()
    _copy_to_temp(
        session,
        "tmp_alias",
        "food_id int, name text, normalized_name text, source_id int",
        ((r[0], r[1], normalize_name(r[1]) or r[1], source_id) for r in rows),
    )
    session.execute(
        text(
            """
            INSERT INTO food_alias (food_id, language, name, normalized_name, alias_type, source_id)
            SELECT food_id, 'en', name, normalized_name, :alias_type, source_id FROM tmp_alias
            ON CONFLICT (food_id, language, normalized_name) DO NOTHING
            """
        ),
        {"alias_type": AliasType.SOURCE_LABEL.value},
    )
    session.execute(text("DROP TABLE tmp_alias"))
    return len(rows)


def _source_id(session: Session, key: str) -> int:
    source_id = session.scalar(select(Source.id).where(Source.key == key))
    if source_id is None:
        raise LookupError(f"Source {key!r} is missing. Load the vocabulary first.")
    return source_id


def load_dataset(
    session: Session, foods: Sequence[FdcFood], dataset: FdcDataset, mappings: FdcMappings
) -> LoadCounts:
    """Loads one dataset inside the caller's transaction."""
    source_id = _source_id(session, mappings.dataset_sources[dataset])
    classification_source_id = _source_id(session, CLASSIFICATION_SOURCE_KEY)

    food_ids = _upsert_foods(session, foods, source_id, classification_source_id, mappings)
    _upsert_external_refs(session, foods, food_ids)
    nutrient_values = _replace_nutrients(session, foods, food_ids, source_id)
    portions = _replace_portions(session, foods, food_ids, source_id)

    recipes = components = placeholders = 0
    if dataset is FdcDataset.SR_LEGACY:
        _link_same_food_records(session, classification_source_id)
    if dataset is FdcDataset.FNDDS:
        recipes, components, placeholders = _replace_recipes(session, foods, food_ids, source_id)
    refresh_aliases(session, source_id)

    counts = LoadCounts(len(foods), nutrient_values, portions, recipes, components, placeholders)
    log.info(
        "fdc_dataset_loaded",
        dataset=dataset.value,
        foods=counts.foods,
        nutrient_values=counts.nutrient_values,
        portions=counts.portions,
        recipes=counts.recipes,
        recipe_components=counts.recipe_components,
        placeholder_ingredients=counts.placeholder_ingredients,
    )
    return counts


def download_all(data_dir: Path, mappings: FdcMappings) -> dict[FdcDataset, Path]:
    return {
        dataset: download_dataset(
            mappings.dataset_files[dataset], data_dir, mappings.dataset_hashes[dataset]
        )
        for dataset in LOAD_ORDER
    }


def ingest_fdc(engine: Engine, data_dir: Path) -> dict[FdcDataset, LoadCounts]:
    """Loads every dataset, each in its own transaction. The vocabulary must be loaded first."""
    mappings = FdcMappings.load()
    paths = download_all(data_dir, mappings)
    counts = {}
    for dataset in LOAD_ORDER:
        foods = list(read_foods(paths[dataset], dataset))
        with Session(engine) as session, session.begin():
            counts[dataset] = load_dataset(session, foods, dataset, mappings)
    # The planner still has the old table sizes after a bulk load, and would skip the search index.
    with engine.begin() as connection:
        connection.execute(
            text("ANALYZE food, food_alias, food_nutrient, food_portion, recipe, recipe_component")
        )
    return counts
