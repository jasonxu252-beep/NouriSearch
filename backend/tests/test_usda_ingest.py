"""The complete USDA files, loaded for real. These are Milestone 3's acceptance tests.

The datasets are pinned by hash, so every number here is exact for those files. If a figure moves,
a join or a calculation changed, and that should be understood before updating the expected value.
"""

import json
import zipfile
from collections.abc import Iterator
from typing import Any

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, func, make_url, select, text
from sqlalchemy.orm import Session

from app.db.models import (
    Allergen,
    Food,
    FoodAllergen,
    FoodRole,
    RecipeComponent,
    Source,
    SubstitutionOption,
)
from app.domain.enums import AllergenRelation
from app.domain.substitution import Goal
from app.ingest.fdc_loader import LOAD_ORDER, download_all, ingest_fdc
from app.ingest.fdc_rules import FdcMappings
from app.ingest.knowledge import load_curated_knowledge, load_knowledge, read_substitutions
from app.ingest.vocabulary import load_vocabulary
from app.integrations.fdc_bulk import FdcDataset, read_foods
from app.services.nutrient_trace import trace_nutrient
from app.services.rebuild_benchmark import NutrientRebuild, run_rebuild_benchmark
from app.services.simulation_benchmark import SwapBenchmark, run_simulation_benchmark
from app.services.substitutions import rank_substitutions
from tests.conftest import BACKEND_DIR, alembic_config
from tests.test_health import client_for

pytestmark = [pytest.mark.integration, pytest.mark.usda]

DATA_DIR = BACKEND_DIR.parent / "data" / "raw"
MAPPINGS = FdcMappings.load()

# Dishes, median error, within 10%, within 25%. Measured on the pinned files.
EXPECTED_PLAIN = {
    "sodium": (2732, 0.0044, 0.832, 0.955),
    "protein": (2728, 0.0027, 0.850, 0.974),
    "total_fat": (2728, 0.0030, 0.835, 0.966),
    "saturated_fat": (2696, 0.0023, 0.848, 0.975),
    "vitamin_c": (1946, 0.0329, 0.750, 0.921),
    "fiber": (2356, 0.0312, 0.770, 0.961),
    "energy": (2734, 0.0045, 0.853, 0.975),
    "water": (2733, 0.0007, 0.907, 0.968),
}
EXPECTED_MOISTURE_ADJUSTED = {
    "sodium": (2732, 0.0021, 0.947, 0.968),
    "protein": (2728, 0.0012, 0.997, 0.999),
    "total_fat": (2728, 0.0012, 0.983, 0.990),
    "saturated_fat": (2696, 0.0013, 0.983, 0.999),
    "vitamin_c": (1946, 0.0226, 0.707, 0.901),
    "fiber": (2356, 0.0192, 0.905, 0.989),
    "energy": (2734, 0.0022, 0.997, 1.000),
    "water": (2733, 0.0004, 1.000, 1.000),
}


@pytest.fixture(scope="module")
def usda_engine(database_url: str) -> Iterator[Engine]:
    """A separate database holding the full load, so other tests keep their small, clean one."""
    url = make_url(database_url)
    name = f"{url.database}_usda"
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    target = url.set(database=name).render_as_string(hide_password=False)
    command.upgrade(alembic_config(target), "head")

    engine = create_engine(target)
    with Session(engine) as session, session.begin():
        load_vocabulary(session)
    ingest_fdc(engine, DATA_DIR)
    with Session(engine) as session, session.begin():
        load_knowledge(session)
    yield engine
    engine.dispose()
    with admin.connect() as connection:
        connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    admin.dispose()


@pytest.fixture
def session(usda_engine: Engine) -> Iterator[Session]:
    with Session(usda_engine) as db_session:
        yield db_session


@pytest.fixture
def client(usda_engine: Engine) -> TestClient:
    return client_for(usda_engine)


@pytest.fixture(scope="module")
def benchmark(usda_engine: Engine) -> dict[str, NutrientRebuild]:
    with Session(usda_engine) as session:
        return {result.nutrient_key: result for result in run_rebuild_benchmark(session)}


def scalar(session: Session, sql: str, **params: Any) -> Any:
    return session.execute(text(sql), params).scalar()


def raw_records(dataset: FdcDataset) -> list[dict[str, Any]]:
    path = DATA_DIR / MAPPINGS.dataset_files[dataset]
    with zipfile.ZipFile(path) as archive, archive.open(archive.namelist()[0]) as handle:
        document = json.load(handle)
    return document[next(iter(document))]


def food_id(session: Session, name: str, source_key: str = "usda-fdc-fndds-2024-10") -> int:
    found = session.scalar(
        select(Food.id)
        .join(Source, Source.id == Food.source_id)
        .where(Food.canonical_name == name, Source.key == source_key)
    )
    assert found is not None, name
    return found


def test_every_pinned_file_matches_its_hash() -> None:
    assert set(download_all(DATA_DIR, MAPPINGS)) == set(FdcDataset)


def test_every_usda_category_is_mapped_to_a_group() -> None:
    for dataset in LOAD_ORDER:
        path = DATA_DIR / MAPPINGS.dataset_files[dataset]
        known = MAPPINGS.wweia_groups if dataset is FdcDataset.FNDDS else MAPPINGS.sr_groups
        categories = {food.category for food in read_foods(path, dataset)}
        assert categories <= set(known), f"Unmapped in {dataset}: {categories - set(known)}"


def test_row_counts(session: Session) -> None:
    # 5,432 + 7,793 + 424 USDA records, plus the 9 ingredients USDA cites but never lists.
    assert scalar(session, "SELECT count(*) FROM food") == 13_658
    assert scalar(session, "SELECT count(*) FROM food WHERE slug LIKE '%-input-%'") == 9
    assert scalar(session, "SELECT count(*) FROM food_nutrient") == 421_567
    # 2,790 foods with at least 3 ingredients, plus 1,039 with exactly 2.
    assert scalar(session, "SELECT count(*) FROM recipe") == 3_829
    # 18,584 ingredient rows, less the 1,602 that are a food's only ingredient.
    assert scalar(session, "SELECT count(*) FROM recipe_component") == 16_982
    assert scalar(session, "SELECT count(*) FROM nutrient_proxy") == 212


def test_ingest_is_idempotent(usda_engine: Engine) -> None:
    """A full second load must leave every row the loader writes exactly as it was."""
    checks = {
        "food": "SELECT md5(string_agg(t::text, '|' ORDER BY id)) FROM food t",
        "food_external_ref": """SELECT md5(string_agg(t::text, '|' ORDER BY system, external_id))
                                FROM food_external_ref t""",
        "food_nutrient": """SELECT md5(string_agg(
                                concat_ws(',', food_id, nutrient_id, source_id, amount_per_100g,
                                          value_kind, derivation),
                                '|' ORDER BY food_id, nutrient_id, source_id))
                            FROM food_nutrient""",
        "food_portion": """SELECT md5(string_agg(
                               concat_ws(',', food_id, description, gram_weight, position),
                               '|' ORDER BY food_id, position)) FROM food_portion""",
        "recipe": "SELECT md5(string_agg(t::text, '|' ORDER BY id)) FROM recipe t",
        "recipe_component": """SELECT md5(string_agg(
                                   concat_ws(',', recipe_id, component_food_id, position, weight_g,
                                             retention_code),
                                   '|' ORDER BY recipe_id, position)) FROM recipe_component""",
        "food_alias": """SELECT md5(string_agg(
                             concat_ws(',', food_id, language, normalized_name),
                             '|' ORDER BY food_id, language, normalized_name)) FROM food_alias""",
        "nutrient_proxy": """SELECT md5(string_agg(
                                 concat_ws(',', food_id, proxy_food_id), '|' ORDER BY food_id))
                             FROM nutrient_proxy""",
    }

    def fingerprints() -> dict[str, str]:
        with Session(usda_engine) as session:
            return {table: scalar(session, sql) for table, sql in checks.items()}

    before = fingerprints()
    ingest_fdc(usda_engine, DATA_DIR)
    assert fingerprints() == before


@pytest.mark.parametrize(
    ("variant", "expected"),
    [("plain", EXPECTED_PLAIN), ("moisture_adjusted", EXPECTED_MOISTURE_ADJUSTED)],
)
def test_rebuild_benchmark_has_not_regressed(
    benchmark: dict[str, NutrientRebuild],
    variant: str,
    expected: dict[str, tuple[int, float, float, float]],
) -> None:
    for key, (dishes, median, within_10, within_25) in expected.items():
        stats = getattr(benchmark[key], variant)
        assert stats.dishes == dishes, key
        assert stats.median_error == pytest.approx(median, abs=0.0001), key
        assert stats.within_10_percent == pytest.approx(within_10, abs=0.001), key
        assert stats.within_25_percent == pytest.approx(within_25, abs=0.001), key


@pytest.mark.parametrize(
    "key", ["sodium", "protein", "total_fat", "saturated_fat", "fiber", "energy"]
)
def test_usdas_moisture_change_explains_most_of_the_error_in_conserved_nutrients(
    benchmark: dict[str, NutrientRebuild], key: str
) -> None:
    """The plan's hypothesis, tested. Cooking concentrates what water leaves behind."""
    result = benchmark[key]
    assert result.moisture_adjusted.within_10_percent is not None
    assert result.plain.within_10_percent is not None
    assert result.moisture_adjusted.within_10_percent > result.plain.within_10_percent + 0.10


def test_the_moisture_arithmetic_predicts_water_itself(
    benchmark: dict[str, NutrientRebuild],
) -> None:
    """Water is what moisture change is about, so it is the sharpest check of the arithmetic."""
    assert benchmark["water"].moisture_adjusted.within_10_percent == pytest.approx(1.0, abs=0.001)


def test_retention_explains_what_moisture_does_not_in_vitamin_c(
    benchmark: dict[str, NutrientRebuild],
) -> None:
    """Where USDA applied a retention factor, the published value sits below the rebuilt one."""
    result = benchmark["vitamin_c"]
    assert result.retention_ratio_with_factor is not None
    assert result.retention_ratio_without_factor is not None
    assert result.retention_ratio_with_factor < 0.95
    assert result.retention_ratio_without_factor == pytest.approx(1.0, abs=0.01)


@pytest.mark.parametrize("key", ["sodium", "protein", "total_fat"])
def test_retention_factors_do_not_touch_stable_nutrients(
    benchmark: dict[str, NutrientRebuild], key: str
) -> None:
    result = benchmark[key]
    assert result.retention_ratio_with_factor == pytest.approx(1.0, abs=0.01)
    assert result.retention_ratio_without_factor == pytest.approx(1.0, abs=0.01)


@pytest.mark.parametrize(
    ("key", "minimum_dishes", "minimum_within_10"),
    [
        ("sodium", 1400, 0.93),
        ("protein", 1400, 0.99),
        ("total_fat", 2600, 0.98),
        ("saturated_fat", 2500, 0.98),
        ("energy", 1400, 0.99),
        ("water", 1400, 0.999),
    ],
)
def test_full_recursion_reaches_the_published_values_on_its_own(
    benchmark: dict[str, NutrientRebuild], key: str, minimum_dishes: int, minimum_within_10: float
) -> None:
    """With published values on nested ingredients removed, only the recursion can get there."""
    stats = benchmark[key].fully_recursive
    assert stats.dishes >= minimum_dishes
    assert stats.within_10_percent is not None
    assert stats.within_10_percent >= minimum_within_10


def test_no_recipe_nests_deeper_than_the_traversal_limit_and_none_loops(session: Session) -> None:
    deepest, looped = session.execute(
        text(
            """
            WITH RECURSIVE t AS (
                SELECT r.dish_id AS root, rc.component_food_id AS food, 1 AS depth,
                       ARRAY[r.dish_id, rc.component_food_id] AS path, false AS looped
                FROM recipe r JOIN recipe_component rc ON rc.recipe_id = r.id
                UNION ALL
                SELECT t.root, rc.component_food_id, t.depth + 1, t.path || rc.component_food_id,
                       rc.component_food_id = ANY(t.path)
                FROM t
                JOIN recipe r ON r.dish_id = t.food
                JOIN recipe_component rc ON rc.recipe_id = r.id
                WHERE NOT t.looped AND t.depth < 20
            )
            SELECT max(depth), bool_or(looped) FROM t
            """
        )
    ).one()
    assert deepest <= 8
    assert looped is False


def test_no_value_is_invented_or_lost(session: Session) -> None:
    """Every stored value, and every stored zero, must trace to a number in USDA's own file."""
    codes = {
        row[0]: (row[1], row[2])
        for row in session.execute(
            text("SELECT code, nutrient_id, preference FROM nutrient_source_code")
        )
    }
    for dataset in LOAD_ORDER:
        expected_rows = expected_zeros = 0
        for record in raw_records(dataset):
            best: dict[int, tuple[int, float]] = {}
            for entry in record["foodNutrients"]:
                mapped = codes.get(entry["nutrient"].get("number"))
                amount = entry.get("amount")
                if mapped is None or amount is None or amount < 0:
                    continue
                nutrient_id, preference = mapped
                if nutrient_id not in best or preference < best[nutrient_id][0]:
                    best[nutrient_id] = (preference, amount)
            expected_rows += len(best)
            expected_zeros += sum(amount == 0 for _, amount in best.values())

        stored = session.execute(
            text(
                """
                SELECT count(*), count(*) FILTER (WHERE amount_per_100g = 0)
                FROM food_nutrient fn JOIN source s ON s.id = fn.source_id
                WHERE s.key = :key
                """
            ),
            {"key": MAPPINGS.dataset_sources[dataset]},
        ).one()
        assert tuple(stored) == (expected_rows, expected_zeros), dataset


def test_a_food_with_no_usda_values_is_unknown_through_the_api(
    client: TestClient, session: Session
) -> None:
    body = client.get(f"/v1/foods/{food_id(session, 'Milk, human')}").json()
    assert {n["status"] for n in body["nutrients"]} == {"unknown"}
    assert {n["amount_per_100g"] for n in body["nutrients"]} == {None}


def test_negative_usda_carbohydrate_is_unknown_through_the_api(
    client: TestClient, session: Session
) -> None:
    chicken = food_id(
        session, "Chicken, drumstick, meat and skin, raw", "usda-fdc-foundation-2026-10"
    )
    body = client.get(f"/v1/foods/{chicken}").json()
    carbohydrate = next(n for n in body["nutrients"] if n["key"] == "carbohydrate")
    assert carbohydrate["status"] in ("unknown", "estimated")
    assert (carbohydrate["amount_per_100g"] or 0) >= 0


def test_what_usda_does_not_publish_is_unknown_or_shows_its_working(
    client: TestClient, session: Session
) -> None:
    body = client.get(f"/v1/foods/{food_id(session, 'Bibimbap, Korean')}").json()
    nutrients = {n["key"]: n for n in body["nutrients"]}

    # No USDA file has a code for these, so nothing could ever supply a number.
    for key in ("added_sugars", "chromium", "chloride"):
        assert nutrients[key]["status"] == "unknown", key
        assert nutrients[key]["amount_per_100g"] is None, key

    # FNDDS publishes no manganese, but some ingredients do, so recursion supplies a floor.
    manganese = nutrients["manganese"]
    assert manganese["status"] == "lower_bound"
    assert manganese["amount_per_100g"] > 0
    assert manganese["missing_ingredients"], "a lower bound names what it could not count"
    assert manganese["source_keys"], "a rebuilt value still cites its sources"

    # Nothing but a real statement from a source can read as zero.
    for nutrient in body["nutrients"]:
        if nutrient["amount_per_100g"] == 0:
            assert nutrient["status"] == "known", nutrient["key"]
            assert nutrient["source_keys"], nutrient["key"]


def test_bibimbap_matches_the_figures_in_the_plan(session: Session) -> None:
    trace = trace_nutrient(session, food_id(session, "Bibimbap, Korean"), "sodium")
    top = trace.breakdown.contributions[0]
    assert top.component.name == "Salt, table"
    assert top.share == pytest.approx(0.91, abs=0.01)
    assert trace.breakdown.published_per_100g == 435.0
    assert trace.breakdown.calculated_per_100g == pytest.approx(435, abs=5)
    assert trace.shared_dishes, "other dishes use salt too"


def bibimbap_composition(client: TestClient, session: Session) -> dict[str, Any]:
    response = client.get(f"/v1/foods/{food_id(session, 'Bibimbap, Korean')}/composition")
    assert response.status_code == 200, response.text
    return response.json()


def test_the_serving_changes_the_mark_on_real_data(client: TestClient, session: Session) -> None:
    """The plan's example: bibimbap's sodium is high per cup, and not per 100 g."""
    body = bibimbap_composition(client, session)
    servings = {s["label"]: s for s in body["servings"]}
    assert servings["1 cup"]["grams"] == 162.0
    assert servings["1 cup"]["is_default"] is True
    assert servings["Quantity not specified"]["grams"] == 121.0

    def sodium(label: str) -> dict[str, Any]:
        result = next(e for e in body["evaluations"] if e["serving_key"] == servings[label]["key"])
        return next(n for n in result["nutrients"] if n["key"] == "sodium")

    assert sodium("1 cup")["mark"] == "exclamation"
    assert sodium("1 cup")["percent_daily_value"] == pytest.approx(30.6, abs=0.1)
    assert sodium("Quantity not specified")["mark"] == "exclamation"
    assert sodium("Quantity not specified")["percent_daily_value"] == pytest.approx(22.9, abs=0.1)
    assert sodium("100 g")["mark"] == "green"
    assert sodium("100 g")["percent_daily_value"] == pytest.approx(18.9, abs=0.1)


def test_the_highlight_data_agrees_with_the_plans_figure_for_salt(
    client: TestClient, session: Session
) -> None:
    body = bibimbap_composition(client, session)
    salt = next(i for i in body["ingredients"] if i["name"] == "Salt, table")
    cell = next(
        c
        for c in body["contributions"]
        if c["nutrient_key"] == "sodium" and c["component_id"] == salt["component_id"]
    )
    assert cell["share"] == pytest.approx(0.91, abs=0.01)
    assert len(body["ingredients"]) == 11


def test_excluding_salt_from_real_bibimbap_clears_the_mark(
    client: TestClient, session: Session
) -> None:
    body = bibimbap_composition(client, session)
    salt = next(i for i in body["ingredients"] if i["name"] == "Salt, table")

    response = client.post(
        f"/v1/foods/{body['id']}/simulations",
        json={"edits": [{"type": "remove", "component_id": salt["component_id"]}]},
    )
    assert response.status_code == 200, response.text
    edited = response.json()

    row = next(n for n in edited["nutrients"] if n["key"] == "sodium")
    # The batch of 1765.8 g holds 7,681.2 mg. Salt's 18 g at 38,800 mg per 100 g held 6,984 mg,
    # which leaves 697.2 mg in 1747.8 g.
    assert row["base_amount_per_100g"] == 435.0
    assert row["amount_per_100g"] == pytest.approx(39.89, abs=0.01)
    assert row["approximate"] is False
    cup = next(s for s in edited["servings"] if s["is_default"])
    result = next(e for e in edited["evaluations"] if e["serving_key"] == cup["key"])
    assert next(n for n in result["nutrients"] if n["key"] == "sodium")["mark"] == "green"


def test_a_food_with_no_usda_values_is_all_question_marks(
    client: TestClient, session: Session
) -> None:
    response = client.get(f"/v1/foods/{food_id(session, 'Milk, human')}/composition")
    body = response.json()
    for result in body["evaluations"]:
        assert {n["mark"] for n in result["nutrients"]} == {"question"}
        assert {n["amount"] for n in result["nutrients"]} == {None}
        assert {n["percent_daily_value"] for n in result["nutrients"]} == {None}


def test_related_foods_work_on_real_data(client: TestClient, session: Session) -> None:
    dish = food_id(session, "Bibimbap, Korean")
    related = client.get(f"/v1/foods/{dish}/related").json()
    assert related["similar"], "bibimbap shares ingredients with other dishes"
    assert related["similar"][0]["shared_ingredients"]
    assert related["explore"]
    assert dish not in {r["id"] for r in related["similar"] + related["explore"]}

    plain = food_id(session, "Salt, table", "usda-fdc-sr-legacy-2018-04")
    used = client.get(f"/v1/foods/{plain}/related").json()
    assert {r["reason"] for r in used["similar"]} == {"uses_this_food"}


def test_kung_pao_chicken_has_values_but_no_breakdown(client: TestClient, session: Session) -> None:
    body = client.get(f"/v1/foods/{food_id(session, 'Kung pao chicken')}").json()
    assert body["recipe_label"] is None
    assert next(n for n in body["nutrients"] if n["key"] == "sodium")["status"] == "known"


def test_search_finds_real_foods(client: TestClient) -> None:
    body = client.get("/v1/foods/search", params={"q": "bibimbap"}).json()
    assert [r["name"] for r in body["results"]] == ["Bibimbap, Korean"]

    plain = client.get("/v1/foods/search", params={"q": "broccoli"}).json()
    assert plain["results"][0]["name"] == "Broccoli, raw"
    assert plain["results"][0]["processing_level"] == "whole"

    misspelled = client.get("/v1/foods/search", params={"q": "brocoli"}).json()
    assert misspelled["results"][0]["name"] == "Broccoli, raw"


def test_filters_do_what_the_plan_says_on_real_data(client: TestClient) -> None:
    def names(query: str, food_type: str) -> list[str]:
        params = {"q": query, "type": food_type, "limit": 50}
        return [r["name"] for r in client.get("/v1/foods/search", params=params).json()["results"]]

    def juices(foods: list[str]) -> list[str]:
        # "Canned, juice pack" is fruit packed in juice, which is still fruit.
        return [n for n in foods if "juice" in n.casefold() and "juice pack" not in n.casefold()]

    # USDA's fruit category includes juices. These filters must not.
    assert names("apple", "fruits")
    assert juices(names("apple", "fruits")) == []
    assert juices(names("apple", "whole_foods")) == []

    # Raw eggs count as a protein, even though USDA files them with dairy.
    assert "Egg, whole, raw, fresh" in names("egg whole raw", "proteins")
    assert "Egg, whole, raw, fresh" in names("egg whole raw", "whole_foods")

    # Cookies sit in USDA's baked products, next to bread.
    assert not [n for n in names("cookies", "grains") if "cookie" in n.casefold()]

    # A raw apple is not a dish, even though USDA builds it from three varieties.
    assert "Apple, raw" not in names("apple raw", "dishes")
    assert "Apple, raw" in names("apple raw", "whole_foods")
    assert "Bibimbap, Korean" in names("bibimbap", "dishes")


def test_baby_foods_and_ingredient_records_stay_out_of_general_search(client: TestClient) -> None:
    body = client.get("/v1/foods/search", params={"q": "as ingredient", "limit": 50}).json()
    assert not [r for r in body["results"] if r["name"].endswith("as ingredient")]


def test_whole_means_the_description_supports_it(session: Session) -> None:
    """Spot checks over the real data for the classifier's conservative promise."""
    bad = session.execute(
        text(
            """
            SELECT canonical_name FROM food
            WHERE processing_level = 'whole'
              AND (canonical_name ILIKE '%juice%'
                   OR canonical_name ILIKE '%canned%'
                   OR canonical_name ILIKE '%cookie%'
                   OR canonical_name ILIKE '%sauce%')
            """
        )
    ).all()
    assert bad == []


# Pairs, within 10% overall, within 10% when the recipe rebuilds within 10%, and when it does not.
EXPECTED_SWAPS = {
    "sodium": (20231, 0.930, 0.962, 0.325),
    "protein": (19888, 0.991, 0.993, 0.822),
    "total_fat": (19890, 0.983, 0.990, 0.738),
    "saturated_fat": (19556, 0.985, 0.990, 0.826),
    "vitamin_c": (12511, 0.750, 0.869, 0.587),
    "fiber": (13638, 0.949, 0.969, 0.839),
    "energy": (20251, 0.981, 0.986, 0.393),
    "water": (20252, 0.999, 0.999, 1.000),
}


@pytest.fixture(scope="module")
def swap_benchmark(usda_engine: Engine) -> dict[str, SwapBenchmark]:
    with Session(usda_engine) as session:
        return {r.nutrient_key: r for r in run_simulation_benchmark(session)}


@pytest.mark.parametrize("key", list(EXPECTED_SWAPS))
def test_simulated_swaps_match_the_swaps_usda_publishes(
    swap_benchmark: dict[str, SwapBenchmark], key: str
) -> None:
    pairs, close, within, beyond = EXPECTED_SWAPS[key]
    result = swap_benchmark[key]
    line = result.by_line["0.10"]
    assert result.pairs == pairs
    assert result.close == pytest.approx(close, abs=0.001)
    assert line.within_line_close == pytest.approx(within, abs=0.001)
    assert line.beyond_line_close == pytest.approx(beyond, abs=0.001)


def test_the_approximate_label_separates_trustworthy_results_from_the_rest(
    swap_benchmark: dict[str, SwapBenchmark],
) -> None:
    """The evidence behind the 10% line: rebuild error predicts how far a simulation can drift."""
    for key in ("sodium", "protein", "total_fat", "saturated_fat", "energy", "fiber", "vitamin_c"):
        line = swap_benchmark[key].by_line["0.10"]
        assert line.within_line_close is not None
        assert line.beyond_line_close is not None
        assert line.within_line_close > line.beyond_line_close, key


def test_every_curated_record_is_the_food_it_claims_to_be(session: Session) -> None:
    result = load_curated_knowledge(session, read_substitutions())
    session.rollback()
    assert result.missing_records == ()


def test_each_swaps_replacement_has_the_values_its_goals_need(session: Session) -> None:
    """The record a swap points to needs values, or the swap could never be judged."""
    rows = session.execute(
        text(
            """
            SELECT DISTINCT f.canonical_name
            FROM substitution_component sc
            JOIN food f ON f.id = sc.to_food_id
            WHERE NOT EXISTS (
                SELECT 1 FROM food_nutrient fn JOIN nutrient n ON n.id = fn.nutrient_id
                WHERE fn.food_id = f.id AND n.key = 'sodium')
            """
        )
    ).all()
    assert rows == []


def test_most_recipe_ingredient_uses_have_curated_knowledge(session: Session) -> None:
    total = scalar(session, "SELECT count(*) FROM recipe_component")
    reviewed = scalar(
        session,
        """
        SELECT count(*) FROM recipe_component rc
        WHERE EXISTS (
            SELECT 1 FROM substitution_option o WHERE o.from_food_id = rc.component_food_id)
        """,
    )
    roled = scalar(
        session,
        """
        SELECT count(*) FROM recipe_component rc
        WHERE EXISTS (SELECT 1 FROM food_role r WHERE r.food_id = rc.component_food_id)
        """,
    )
    assert reviewed / total > 0.40
    assert roled / total > 0.55


# Words the rules do not use, so this reads each food a second, independent way. Each is a plain
# sign of the allergen, and a replacement carrying one in its name or its recipe must not appear.
_PLAIN_SIGNS = {
    "milk": ("milk", "cheese", "butter", "cream", "yogurt", "whey"),
    "eggs": ("egg", "mayonnaise"),
    "fish": ("fish", "tuna", "salmon", "anchov"),
    "crustacean_shellfish": ("shrimp", "crab", "lobster"),
    "tree_nuts": ("almond", "walnut", "cashew", "pecan", "pistachio"),
    "peanuts": ("peanut",),
    "wheat": ("wheat", "flour", "bread", "pasta", "noodle"),
    "soybeans": ("soy", "tofu", "tempeh", "miso"),
    "sesame": ("sesame", "tahini"),
}
# Words that hold a sign's letters and mean something else. Each one was read by hand against every
# food in the data, which is how this check found ice creams and triticale flour with no finding.
# Add to this only after reading the food, because a real miss would land here too.
_NOT_SIGNS = (
    # Plant milks, yogurts, and butters, and words holding "butter" or "cream".
    "coconut milk",
    "almond milk",
    "soy milk",
    "soymilk",
    "oat milk",
    "rice milk",
    "soy yogurt",
    "tofu yogurt",
    "peanut butter",
    "almond butter",
    "cashew butter",
    "nut butter",
    "seed butter",
    "sesame butter",
    "fruit butter",
    "cocoa butter",
    "butternut",
    "butterhead",
    "butterbur",
    "butterfish",
    "milkfish",
    "cream style",
    "cream of tartar",
    "cream of rice",
    "cream soda",
    "creamy",
    # Words holding "egg", "soy", "miso", "crab", or "fish" that are not those foods.
    "eggplant",
    "veggie",
    "semisoft",
    "crabapple",
    "goldfish",
    "crayfish",
    "jellyfish",
    "cuttlefish",
    "shellfish",
    "salmonberr",
    # Words holding "wheat" or "bread", and flours from something else.
    "buckwheat flour",
    "buckwheat",
    "breadfruit",
    "breadnut",
    "sweetbread",
    "spoonbread",
    "rice noodle",
    "rice flour",
    "corn flour",
    "corn and soy flour",
    "amaranth, flour",
    "arrowroot flour",
    "carob flour",
    "chickpea flour",
    "millet flour",
    "peanut flour",
    "potato flour",
    "quinoa flour",
    "sesame flour",
    "sorghum flour",
    "sorghum, flour",
    "soy flour",
)


def _shows_sign(name: str, allergen: str) -> bool:
    lowered = name.lower()
    for wrong in _NOT_SIGNS:
        lowered = lowered.replace(wrong, "")
    return any(sign in lowered for sign in _PLAIN_SIGNS[allergen])


@pytest.fixture(scope="module")
def ingredients_with_options(usda_engine: Engine) -> list[tuple[int, int]]:
    """One real use of every ingredient the swap list knows."""
    with Session(usda_engine) as session:
        rows = session.execute(
            text(
                """
                SELECT DISTINCT ON (rc.component_food_id) r.dish_id, rc.id
                FROM recipe_component rc
                JOIN recipe r ON r.id = rc.recipe_id AND r.is_default
                WHERE rc.weight_g IS NOT NULL
                  AND EXISTS (
                    SELECT 1 FROM food_role fr WHERE fr.food_id = rc.component_food_id)
                ORDER BY rc.component_food_id, r.dish_id
                """
            )
        ).all()
    assert len(rows) > 50
    return [(row[0], row[1]) for row in rows]


@pytest.fixture(scope="module")
def what_each_food_holds(usda_engine: Engine) -> dict[int, list[str]]:
    """Every name inside each offered food, read straight from recipes and not from the findings."""
    with Session(usda_engine) as session:
        rows = session.execute(
            text(
                """
                WITH RECURSIVE tree AS (
                    SELECT f.id AS root, f.id AS food_id, ARRAY[f.id] AS path FROM food f
                    WHERE f.id IN (SELECT food_id FROM food_role)
                    UNION ALL
                    SELECT t.root, rc.component_food_id, t.path || rc.component_food_id
                    FROM tree t
                    JOIN recipe r ON r.dish_id = t.food_id
                    JOIN recipe_component rc ON rc.recipe_id = r.id
                    WHERE NOT rc.component_food_id = ANY(t.path)
                )
                SELECT t.root, f.canonical_name FROM tree t JOIN food f ON f.id = t.food_id
                """
            )
        ).all()
    holds: dict[int, list[str]] = {}
    for root, name in rows:
        holds.setdefault(root, []).append(name)
    return holds


@pytest.mark.parametrize("allergen", list(_PLAIN_SIGNS))
def test_excluded_allergens_never_appear_for_any_ingredient_in_real_data(
    session: Session,
    ingredients_with_options: list[tuple[int, int]],
    what_each_food_holds: dict[int, list[str]],
    allergen: str,
) -> None:
    """The acceptance test: every ingredient the swap list knows, for each allergen alone.

    The closest match offers the most replacements, because no nutrition goal narrows it.
    """
    offered = 0
    for dish_id, component_id in ingredients_with_options:
        results = rank_substitutions(session, dish_id, component_id, Goal.CLOSEST_MATCH, [allergen])
        for option in results.options:
            assert allergen not in {a.key for a in option.allergens}, option.key
            for item in option.replacements:
                offered += 1
                for name in what_each_food_holds.get(item.food_id, [item.name]):
                    assert not _shows_sign(name, allergen), (allergen, item.name, name)
    assert offered > 100


@pytest.mark.parametrize("goal", [Goal.LESS_SODIUM, Goal.MORE_PROTEIN])
def test_avoiding_all_nine_leaves_nothing_holding_any_of_them(
    session: Session,
    ingredients_with_options: list[tuple[int, int]],
    what_each_food_holds: dict[int, list[str]],
    goal: Goal,
) -> None:
    """Nutrition goals add using less or more, which must respect the list too."""
    for dish_id, component_id in ingredients_with_options:
        results = rank_substitutions(session, dish_id, component_id, goal, list(_PLAIN_SIGNS))
        for option in results.options:
            assert option.allergens == (), option.key
            for item in option.replacements:
                for name in what_each_food_holds.get(item.food_id, [item.name]):
                    for allergen in _PLAIN_SIGNS:
                        assert not _shows_sign(name, allergen), (allergen, item.name, name)


def test_real_foods_with_plain_signs_have_findings(session: Session) -> None:
    """Every food whose own name shows a plain sign has that allergen on record, nine times over."""
    allergen_ids = {row[0]: row[1] for row in session.execute(select(Allergen.key, Allergen.id))}
    foods = session.execute(select(Food.id, Food.canonical_name)).all()
    found: dict[tuple[int, int], bool] = {
        (row[0], row[1]): True
        for row in session.execute(select(FoodAllergen.food_id, FoodAllergen.allergen_id))
    }
    unnoticed = [
        (name, key)
        for food_id, name in foods
        for key, allergen_id in allergen_ids.items()
        if _shows_sign(name, key) and (food_id, allergen_id) not in found
    ]
    # A few names hold a sign's letters in another sense. Each one here was read by hand.
    assert unnoticed == []


def test_real_findings_never_claim_a_food_is_free_of_anything(session: Session) -> None:
    claims = session.scalar(
        select(func.count())
        .select_from(FoodAllergen)
        .where(FoodAllergen.relation == AllergenRelation.FREE_OF)
    )
    assert claims == 0


def test_real_bibimbap_has_the_allergens_its_recipe_shows(
    client: TestClient, session: Session
) -> None:
    body = bibimbap_composition(client, session)
    found = {a["key"]: a for a in body["allergens"]}
    assert found["sesame"]["relation"] == "contains"
    assert found["sesame"]["ingredient_names"] == ["Oil, sesame, salad or cooking"]


def test_a_real_swap_updates_values_and_ingredients_through_the_api(
    client: TestClient, session: Session
) -> None:
    """The milestone's first acceptance line, on real bibimbap."""
    dish = food_id(session, "Bibimbap, Korean")
    salt = next(
        i
        for i in bibimbap_composition(client, session)["ingredients"]
        if i["name"] == "Salt, table"
    )
    ranked = client.post(
        f"/v1/foods/{dish}/substitutions",
        json={"component_id": salt["component_id"], "goal": "less_sodium"},
    ).json()
    half = next(o for o in ranked["options"] if o["scale_factor"] == 0.5)
    assert half["goal_effect"]["before_per_100g"] == 435.0
    # The figure in the plan.
    assert half["goal_effect"]["after_per_100g"] == pytest.approx(238.46, abs=0.01)
    assert {"code": "mark_cleared", "nutrient_key": "sodium"} in half["reasons"]

    applied = client.post(f"/v1/foods/{dish}/simulations", json={"edits": [half["edit"]]}).json()
    sodium = next(n for n in applied["nutrients"] if n["key"] == "sodium")
    assert sodium["amount_per_100g"] == pytest.approx(238.46, abs=0.01)
    salt_after = next(i for i in applied["ingredients"] if i["name"] == "Salt, table")
    assert salt_after["weight_g"] == 9.0
    assert salt_after["original_weight_g"] == 18.0


def test_soy_sauce_has_its_low_sodium_swap_on_real_data(session: Session) -> None:
    """Real USDA values in the plan: 5,490 and 3,600 mg per 100 g."""
    component = session.execute(
        text(
            """
            SELECT r.dish_id, rc.id FROM recipe_component rc
            JOIN recipe r ON r.id = rc.recipe_id AND r.is_default
            JOIN food f ON f.id = rc.component_food_id
            WHERE f.canonical_name = 'Soy sauce made from soy and wheat (shoyu)'
            ORDER BY r.dish_id LIMIT 1
            """
        )
    ).one()
    results = rank_substitutions(session, component[0], component[1], Goal.LESS_SODIUM)
    names = [item.name for option in results.options for item in option.replacements]
    assert "Soy sauce made from soy and wheat (shoyu), low sodium" in names


def test_curated_data_stays_loaded_and_can_be_repeated(usda_engine: Engine) -> None:
    def counts(session: Session) -> tuple[int | None, ...]:
        return tuple(
            session.scalar(select(func.count()).select_from(model))
            for model in (FoodAllergen, FoodRole, SubstitutionOption, RecipeComponent)
        )

    with Session(usda_engine) as session:
        before = counts(session)
    with Session(usda_engine) as session, session.begin():
        load_knowledge(session)
    with Session(usda_engine) as session:
        assert counts(session) == before
