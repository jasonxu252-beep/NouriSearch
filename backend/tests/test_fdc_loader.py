"""The USDA loader, against a small cut of real records from each bulk file.

tests/data/fdc_sample.json holds real USDA records (CC0), trimmed to the fields and nutrients these
tests read. tests/test_usda_ingest.py runs the same loader over the complete files.
"""

import json
from collections.abc import Iterable
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.db.models import (
    Food,
    FoodAlias,
    FoodNutrient,
    FoodPortion,
    Nutrient,
    NutrientProxy,
    Recipe,
    RecipeComponent,
    Source,
)
from app.domain.enums import AliasType, ProcessingLevel, ValueKind
from app.ingest.fdc_loader import LOAD_ORDER, RECIPE_LABEL, load_dataset
from app.ingest.fdc_rules import CLASSIFICATION_SOURCE_KEY, FdcMappings
from app.ingest.vocabulary import load_vocabulary
from app.integrations.fdc_bulk import FdcDataset, FdcFood, parse_food
from app.repositories.composition import load_facts
from tests.factories import make_food, make_recipe

pytestmark = pytest.mark.integration

SAMPLE_PATH = Path(__file__).parent / "data" / "fdc_sample.json"
MAPPINGS = FdcMappings.load()


def sample_foods() -> dict[FdcDataset, list[FdcFood]]:
    raw = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
    return {
        dataset: [parse_food(record, dataset) for record in raw[dataset.value]]
        for dataset in LOAD_ORDER
    }


def load_all(session: Session, foods: dict[FdcDataset, list[FdcFood]] | None = None) -> None:
    for dataset, records in (foods or sample_foods()).items():
        load_dataset(session, records, dataset, MAPPINGS)


@pytest.fixture
def loaded(session: Session) -> Session:
    load_vocabulary(session)
    load_all(session)
    return session


def food_named(session: Session, name: str, source_key: str | None = None) -> Food:
    query = select(Food).where(Food.canonical_name == name)
    if source_key:
        query = query.join(Source, Source.id == Food.source_id).where(Source.key == source_key)
    food = session.scalar(query)
    assert food is not None, name
    return food


def value_of(session: Session, food: Food, nutrient_key: str) -> FoodNutrient | None:
    return session.scalar(
        select(FoodNutrient)
        .join(Nutrient)
        .where(FoodNutrient.food_id == food.id, Nutrient.key == nutrient_key)
    )


SNAPSHOTS = {
    "food": """SELECT id, slug, kind, canonical_name, food_group_id, processing_level,
               classification_source_id, is_discoverable, source_id FROM food""",
    "food_external_ref": "SELECT food_id, system, external_id FROM food_external_ref",
    "food_nutrient": """SELECT food_id, nutrient_id, source_id, amount_per_100g, value_kind,
                        derivation FROM food_nutrient""",
    "food_portion": """SELECT food_id, description, gram_weight, is_household_measure, position,
                       source_id FROM food_portion""",
    "recipe": """SELECT id, dish_id, label, verification, source_id, is_default,
                 moisture_change_pct FROM recipe""",
    "recipe_component": """SELECT recipe_id, component_food_id, position, weight_g,
                           retention_code, is_optional FROM recipe_component""",
    "food_alias": "SELECT food_id, language, name, normalized_name, alias_type FROM food_alias",
    "nutrient_proxy": "SELECT food_id, proxy_food_id, source_id FROM nutrient_proxy",
}


def snapshot(session: Session) -> dict[str, list[tuple[Any, ...]]]:
    """Everything the loader writes, sorted, leaving out row IDs of sets it replaces."""
    return {
        table: sorted(
            (tuple(row) for row in session.execute(text(query))),
            key=lambda row: tuple(str(value) for value in row),
        )
        for table, query in SNAPSHOTS.items()
    }


def test_loading_twice_changes_nothing(session: Session) -> None:
    load_vocabulary(session)
    load_all(session)
    first = snapshot(session)
    assert all(first.values()), "every table should have rows, or this test proves nothing"

    load_all(session)

    assert snapshot(session) == first


def test_a_renamed_usda_food_stays_the_same_food(session: Session) -> None:
    load_vocabulary(session)
    foods = sample_foods()
    load_all(session, foods)
    original = food_named(session, "Salt, table")
    food_id, slug = original.id, original.slug

    renamed = [
        replace(f, description="Salt, table, iodized") if f.description == "Salt, table" else f
        for f in foods[FdcDataset.SR_LEGACY]
    ]
    load_all(session, {**foods, FdcDataset.SR_LEGACY: renamed})
    session.expire_all()

    food = session.get_one(Food, food_id)
    assert food.canonical_name == "Salt, table, iodized"
    assert food.slug == slug, "links to the food keep working"
    assert session.scalar(select(func.count()).where(Food.canonical_name == "Salt, table")) == 0
    aliases = session.scalars(select(FoodAlias.name).where(FoodAlias.food_id == food_id)).all()
    assert aliases == ["Salt, table, iodized"]


def test_values_and_recipes_gone_from_the_data_are_removed(session: Session) -> None:
    load_vocabulary(session)
    foods = sample_foods()
    load_all(session, foods)
    bibimbap = food_named(session, "Bibimbap, Korean")
    assert session.scalar(select(Recipe).where(Recipe.dish_id == bibimbap.id)) is not None

    without_details = [
        replace(f, nutrients=(), portions=(), ingredients=())
        if f.description == "Bibimbap, Korean"
        else f
        for f in foods[FdcDataset.FNDDS]
    ]
    load_all(session, {**foods, FdcDataset.FNDDS: without_details})

    assert session.scalar(select(Recipe).where(Recipe.dish_id == bibimbap.id)) is None
    assert value_of(session, bibimbap, "sodium") is None
    assert session.scalar(select(func.count()).where(FoodPortion.food_id == bibimbap.id)) == 0


def test_a_failed_load_changes_nothing(session: Session) -> None:
    load_vocabulary(session)
    foods = sample_foods()
    load_all(session, foods)
    before = snapshot(session)

    broken = [
        replace(f, description=f"{f.description}, renamed") for f in foods[FdcDataset.FOUNDATION]
    ]
    # Too large for the column, so the load fails after it has already renamed the foods.
    impossible = replace(foods[FdcDataset.FOUNDATION][0].nutrients[0], amount=10.0**12)
    broken[0] = replace(broken[0], nutrients=(impossible,))
    with pytest.raises(DBAPIError), session.begin_nested():
        load_dataset(session, broken, FdcDataset.FOUNDATION, MAPPINGS)

    session.expire_all()
    assert snapshot(session) == before


def test_loading_without_the_vocabulary_explains_what_is_missing(session: Session) -> None:
    with pytest.raises(LookupError, match="Load the vocabulary first"):
        load_dataset(session, [], FdcDataset.FNDDS, MAPPINGS)


def test_absent_values_stay_absent_and_stated_zeros_stay_zero(loaded: Session) -> None:
    # USDA withdrew this profile and publishes no values for it, so nothing is stored.
    human_milk = food_named(loaded, "Milk, human")
    count = select(func.count()).where(FoodNutrient.food_id == human_milk.id)
    assert loaded.scalar(count) == 0

    bibimbap = food_named(loaded, "Bibimbap, Korean")
    vitamin_d = value_of(loaded, bibimbap, "vitamin_d")
    assert vitamin_d is not None
    assert vitamin_d.amount_per_100g == 0.0
    # FNDDS gives no derivation, so this zero is reported as stated and not as assumed or measured.
    assert vitamin_d.value_kind is ValueKind.SOURCE_REPORTED


def test_the_assumed_zero_label_survives(loaded: Session) -> None:
    salt = food_named(loaded, "Salt, table")
    vitamin_d = value_of(loaded, salt, "vitamin_d")
    assert vitamin_d is not None
    assert vitamin_d.amount_per_100g == 0.0
    assert vitamin_d.value_kind is ValueKind.ASSUMED_ZERO
    assert vitamin_d.derivation is not None
    assert vitamin_d.derivation.startswith("Assumed zero")


def test_negative_usda_values_are_stored_as_unknown(loaded: Session) -> None:
    chicken = food_named(loaded, "Chicken, drumstick, meat and skin, raw")
    assert value_of(loaded, chicken, "carbohydrate") is None
    assert value_of(loaded, chicken, "protein") is not None


def test_recipes_record_usdas_label_moisture_and_retention(loaded: Session) -> None:
    custard = food_named(loaded, "Custard")
    recipe = loaded.scalar(select(Recipe).where(Recipe.dish_id == custard.id))
    assert recipe is not None
    assert recipe.label == RECIPE_LABEL
    assert recipe.is_default is True
    assert recipe.moisture_change_pct == -10.0

    with_retention = loaded.scalar(
        select(func.count()).where(RecipeComponent.retention_code.is_not(None))
    )
    assert with_retention is not None
    assert with_retention > 0


def test_a_curated_default_recipe_is_not_displaced(session: Session) -> None:
    load_vocabulary(session)
    foods = sample_foods()
    load_all(session, foods)
    dal = food_named(session, "Dal")
    existing = session.scalars(select(Recipe).where(Recipe.dish_id == dal.id)).all()
    assert len(existing) == 1
    source = session.get_one(Source, dal.source_id)

    # A curated recipe takes over as the default, then USDA reloads.
    existing[0].is_default = False
    session.flush()
    curated = make_recipe(session, dal, source, [], label="Family recipe")
    load_all(session, foods)
    session.expire_all()

    recipes = {
        r.label: r.is_default
        for r in session.scalars(select(Recipe).where(Recipe.dish_id == dal.id))
    }
    assert recipes == {"Family recipe": True, RECIPE_LABEL: False}
    assert curated.is_default is True


def test_a_food_with_one_ingredient_has_no_breakdown(loaded: Session) -> None:
    """Kung pao chicken's only ingredient is the restaurant record for the same dish."""
    kung_pao = food_named(loaded, "Kung pao chicken")
    assert loaded.scalar(select(Recipe).where(Recipe.dish_id == kung_pao.id)) is None
    assert value_of(loaded, kung_pao, "sodium") is not None


def components_of(session: Session, dish: Food) -> list[Food]:
    return list(
        session.scalars(
            select(Food)
            .join(RecipeComponent, RecipeComponent.component_food_id == Food.id)
            .join(Recipe, Recipe.id == RecipeComponent.recipe_id)
            .where(Recipe.dish_id == dish.id)
            .order_by(RecipeComponent.position)
        )
    )


def names(foods: Iterable[Food]) -> list[str]:
    return [food.canonical_name for food in foods]


def test_a_recipe_uses_the_record_usda_names(loaded: Session) -> None:
    """Code 1123 is both SR's "Egg, whole, raw, fresh" and Foundation's Grade A egg."""
    assert "Eggs, Grade A, Large, egg whole" in names(
        components_of(loaded, food_named(loaded, "Custard"))
    )


def test_a_number_only_foundation_has_still_resolves(loaded: Session) -> None:
    components = names(components_of(loaded, food_named(loaded, "Yogurt, nonfat milk, plain")))
    assert "Yogurt, plain, nonfat" in components


def test_an_ingredient_with_no_record_stays_in_the_recipe_as_unknown(loaded: Session) -> None:
    oat_milk = food_named(loaded, "Oat milk")
    placeholder = next(
        c for c in components_of(loaded, oat_milk) if c.canonical_name == "Vitamin D as ingredient"
    )
    assert placeholder.is_discoverable is False
    assert placeholder.processing_level is ProcessingLevel.UNKNOWN
    assert loaded.scalar(select(func.count()).where(FoodNutrient.food_id == placeholder.id)) == 0


def test_foundation_gaps_are_filled_from_the_same_food_and_marked_as_estimates(
    loaded: Session,
) -> None:
    foundation = food_named(loaded, "Eggs, Grade A, Large, egg whole")
    standard = food_named(loaded, "Egg, whole, raw, fresh")
    proxy = loaded.get_one(NutrientProxy, foundation.id)
    assert proxy.proxy_food_id == standard.id
    derived = loaded.scalar(select(Source.id).where(Source.key == CLASSIFICATION_SOURCE_KEY))
    assert proxy.source_id == derived

    vitamin_c = loaded.scalar(select(Nutrient.id).where(Nutrient.key == "vitamin_c"))
    protein = loaded.scalar(select(Nutrient.id).where(Nutrient.key == "protein"))
    assert vitamin_c is not None and protein is not None
    facts = load_facts(loaded, [foundation.id])[foundation.id]
    assert facts[vitamin_c].estimated is True
    # Foundation's own measurement wins wherever it has one: 12.4 g, against 12.6 g in SR Legacy.
    assert facts[protein].estimated is False
    assert facts[protein].amount_per_100g == pytest.approx(12.4)


def test_classifications_cite_the_project_and_never_usda(loaded: Session) -> None:
    derived = loaded.scalar(select(Source.id).where(Source.key == CLASSIFICATION_SOURCE_KEY))
    uncited = loaded.scalar(
        select(func.count()).where(
            Food.processing_level != ProcessingLevel.UNKNOWN,
            Food.classification_source_id != derived,
        )
    )
    assert uncited == 0
    apple = food_named(loaded, "Apple, raw")
    assert apple.processing_level is ProcessingLevel.WHOLE
    assert apple.classification_source_id == derived


def test_support_records_stay_out_of_discovery_but_keep_their_data(loaded: Session) -> None:
    record = food_named(loaded, "Cheese and Queso as ingredient")
    assert record.is_discoverable is False
    assert value_of(loaded, record, "sodium") is not None


def test_every_food_gets_its_english_name_as_an_alias(loaded: Session) -> None:
    foods = loaded.scalar(select(func.count()).select_from(Food))
    aliases = loaded.scalar(
        select(func.count()).where(
            FoodAlias.language == "en", FoodAlias.alias_type == AliasType.SOURCE_LABEL
        )
    )
    assert aliases == foods


def test_portions_keep_the_sources_order(loaded: Session) -> None:
    bibimbap = food_named(loaded, "Bibimbap, Korean")
    portions = loaded.execute(
        select(FoodPortion.description, FoodPortion.gram_weight, FoodPortion.is_household_measure)
        .where(FoodPortion.food_id == bibimbap.id)
        .order_by(FoodPortion.position)
    ).all()
    assert [tuple(p) for p in portions] == [
        ("1 cup", 162.0, True),
        ("Quantity not specified", 121.0, False),
    ]


def test_loader_does_not_touch_foods_it_did_not_load(loaded: Session) -> None:
    source = loaded.scalar(select(Source).where(Source.key == "nourisearch-editorial"))
    assert source is not None
    curated = make_food(loaded, "Salted duck egg", source)
    load_all(loaded)
    loaded.expire_all()
    assert loaded.get_one(Food, curated.id).canonical_name == "Salted duck egg"
