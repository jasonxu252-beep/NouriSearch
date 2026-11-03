"""The baseline food API, end to end through HTTP. The central rule: unknown stays unknown."""

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Food, FoodAlias, FoodGroup, FoodPortion, Source
from app.db.session import get_session
from app.domain.enums import FoodKind, ProcessingLevel
from app.domain.text import normalize_name
from app.ingest.vocabulary import load_vocabulary
from app.main import create_app
from tests.factories import make_food, make_nutrient, make_proxy, make_recipe, make_source
from tests.test_fdc_loader import load_all

pytestmark = pytest.mark.integration


@pytest.fixture
def client(session: Session) -> Iterator[TestClient]:
    app = create_app()

    def override() -> Iterator[Session]:
        yield session

    app.dependency_overrides[get_session] = override
    yield TestClient(app)


@pytest.fixture
def loaded(session: Session) -> Session:
    load_vocabulary(session)
    load_all(session)
    return session


def add_named_food(
    session: Session,
    source: Source,
    name: str,
    *,
    group: str | None = None,
    kind: FoodKind = FoodKind.BASIC,
    level: ProcessingLevel = ProcessingLevel.UNKNOWN,
    discoverable: bool = True,
) -> Food:
    food = make_food(session, name, source, kind=kind)
    food.processing_level = level
    food.classification_source_id = source.id
    food.is_discoverable = discoverable
    if group:
        food.food_group_id = session.scalar(select(FoodGroup.id).where(FoodGroup.key == group))
    session.add(
        FoodAlias(
            food_id=food.id,
            language="en",
            name=name,
            normalized_name=normalize_name(name),
            alias_type="source_label",
            source_id=source.id,
        )
    )
    session.flush()
    return food


def search(client: TestClient, **params: Any) -> dict[str, Any]:
    response = client.get("/v1/foods/search", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def result_names(body: dict[str, Any]) -> list[str]:
    return [r["name"] for r in body["results"]]


def test_matches_rank_from_exact_to_similar(client: TestClient, session: Session) -> None:
    load_vocabulary(session)
    source = make_source(session)
    add_named_food(session, source, "Soup, tomato rice")
    add_named_food(session, source, "Wild rice")
    add_named_food(session, source, "Rice, white, cooked")
    add_named_food(session, source, "Rice")
    add_named_food(session, source, "Rice cake")

    body = search(client, q="RICE")

    assert result_names(body)[:2] == ["Rice", "Rice cake"]
    assert [r["match"] for r in body["results"]][:3] == ["exact", "prefix", "prefix"]
    assert {r["match"] for r in body["results"]} == {"exact", "prefix", "word_prefix"}
    assert body["query"] == "rice"


def test_word_order_does_not_matter(client: TestClient, session: Session) -> None:
    load_vocabulary(session)
    source = make_source(session)
    add_named_food(session, source, "Soup, chicken noodle")
    add_named_food(session, source, "Chicken, roasted")

    body = search(client, q="chicken soup")

    assert result_names(body) == ["Soup, chicken noodle", "Chicken, roasted"]
    assert [r["match"] for r in body["results"]] == ["all_words", "similar"]


def test_a_misspelling_finds_the_food_and_says_it_was_only_similar(
    client: TestClient, session: Session
) -> None:
    load_vocabulary(session)
    add_named_food(session, make_source(session), "Broccoli, raw")

    body = search(client, q="brocoli")

    assert result_names(body) == ["Broccoli, raw"]
    assert body["results"][0]["match"] == "similar"


def test_accents_and_case_are_folded(client: TestClient, session: Session) -> None:
    load_vocabulary(session)
    add_named_food(session, make_source(session), "Jalapeno peppers")
    assert result_names(search(client, q="JALAPEÑO")) == ["Jalapeno peppers"]


@pytest.mark.parametrize("query", ["100%", "ri_e", "%", "_", "\\", "'; DROP TABLE food; --"])
def test_wildcards_and_quotes_are_plain_text(
    client: TestClient, session: Session, query: str
) -> None:
    load_vocabulary(session)
    add_named_food(session, make_source(session), "Rice")
    body = search(client, q=query)
    # "ri_e" normalizes to the two words "ri" and "e", which do match "Rice". Nothing else may.
    assert result_names(body) in ([], ["Rice"])
    assert session.scalar(select(func.count()).select_from(Food)) == 1


def test_a_query_of_only_punctuation_returns_nothing(client: TestClient, session: Session) -> None:
    load_vocabulary(session)
    add_named_food(session, make_source(session), "Rice")
    assert search(client, q="!!!") == {"query": "", "results": [], "has_more": False}


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"q": ""},
        {"q": "x" * 201},
        {"q": "rice", "limit": 0},
        {"q": "rice", "limit": 51},
        {"q": "rice", "type": "nope"},
    ],
)
def test_invalid_searches_use_the_shared_error_shape(
    client: TestClient, params: dict[str, Any]
) -> None:
    response = client.get("/v1/foods/search", params=params)
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_request"


def test_paging(client: TestClient, session: Session) -> None:
    load_vocabulary(session)
    source = make_source(session)
    for suffix in "abc":
        add_named_food(session, source, f"Rice {suffix}")

    first = search(client, q="rice", limit=2)
    second = search(client, q="rice", limit=2, offset=2)

    assert result_names(first) == ["Rice a", "Rice b"]
    assert first["has_more"] is True
    assert result_names(second) == ["Rice c"]
    assert second["has_more"] is False


def test_records_that_support_others_stay_out_of_search(
    client: TestClient, session: Session
) -> None:
    load_vocabulary(session)
    source = make_source(session)
    add_named_food(session, source, "Rice, cooked")
    add_named_food(session, source, "Rice, cooked, as ingredient", discoverable=False)
    assert result_names(search(client, q="rice cooked")) == ["Rice, cooked"]


@pytest.fixture
def filter_foods(session: Session) -> Session:
    load_vocabulary(session)
    source = make_source(session)
    add_named_food(session, source, "Rice apple raw", group="fruits", level=ProcessingLevel.WHOLE)
    add_named_food(
        session,
        source,
        "Rice apple dried",
        group="fruits",
        level=ProcessingLevel.MINIMALLY_PROCESSED,
    )
    add_named_food(
        session, source, "Rice juice", group="beverages", level=ProcessingLevel.PROCESSED
    )
    add_named_food(session, source, "Rice spinach", group="vegetables", level=ProcessingLevel.WHOLE)
    add_named_food(session, source, "Rice beef", group="meat", level=ProcessingLevel.WHOLE)
    add_named_food(session, source, "Rice beans", group="legumes", level=ProcessingLevel.UNKNOWN)
    add_named_food(session, source, "Rice grain", group="grains", level=ProcessingLevel.UNKNOWN)
    dish = add_named_food(
        session,
        source,
        "Rice bowl",
        group="mixed_dishes",
        kind=FoodKind.PREPARED_DISH,
        level=ProcessingLevel.PROCESSED,
    )
    salt = add_named_food(session, source, "Rice salt", group="seasonings")
    make_recipe(session, dish, source, [(salt, 1.0)])
    return session


@pytest.mark.parametrize(
    ("food_type", "expected"),
    [
        ("whole_foods", {"Rice apple raw", "Rice apple dried", "Rice spinach", "Rice beef"}),
        ("fruits", {"Rice apple raw", "Rice apple dried"}),
        ("vegetables", {"Rice spinach"}),
        # Proteins is a parent group, so it must take in its children.
        ("proteins", {"Rice beef", "Rice beans"}),
        ("grains", {"Rice grain"}),
        ("dishes", {"Rice bowl"}),
        ("ingredients", {"Rice salt"}),
    ],
)
def test_each_filter_excludes_everything_else(
    client: TestClient, filter_foods: Session, food_type: str, expected: set[str]
) -> None:
    assert set(result_names(search(client, q="rice", type=food_type))) == expected


def test_no_filter_returns_every_kind(client: TestClient, filter_foods: Session) -> None:
    assert len(search(client, q="rice", type="all")["results"]) == 9


def read_food(client: TestClient, food_id: int) -> dict[str, Any]:
    response = client.get(f"/v1/foods/{food_id}")
    assert response.status_code == 200, response.text
    return response.json()


def nutrients_of(body: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {n["key"]: n for n in body["nutrients"]}


def test_a_missing_food_uses_the_shared_error_shape(client: TestClient, session: Session) -> None:
    load_vocabulary(session)
    response = client.get("/v1/foods/999999")
    assert response.status_code == 404
    assert response.json() == {"code": "not_found", "message": "Food 999999 was not found."}


def test_a_food_with_no_data_reports_every_nutrient_as_unknown_never_zero(
    client: TestClient, loaded: Session
) -> None:
    """USDA withdrew the "Milk, human" profile, so it is a real food with no values at all."""
    milk = loaded.scalar(select(Food).where(Food.canonical_name == "Milk, human"))
    assert milk is not None

    body = read_food(client, milk.id)

    assert len(body["nutrients"]) == 41, "every tracked nutrient appears, so absence is visible"
    for nutrient in body["nutrients"]:
        assert nutrient["status"] == "unknown", nutrient["key"]
        assert nutrient["amount_per_100g"] is None, nutrient["key"]
        assert nutrient["value_kind"] is None, nutrient["key"]
        assert nutrient["source_keys"] == []


def test_a_stated_zero_is_a_known_zero_with_its_provenance(
    client: TestClient, loaded: Session
) -> None:
    salt = loaded.scalar(select(Food).where(Food.canonical_name == "Salt, table"))
    assert salt is not None

    vitamin_d = nutrients_of(read_food(client, salt.id))["vitamin_d"]

    assert vitamin_d["status"] == "known"
    assert vitamin_d["amount_per_100g"] == 0.0
    assert vitamin_d["value_kind"] == "assumed_zero"
    assert vitamin_d["derivation"].startswith("Assumed zero")


def test_published_values_and_their_sources_reach_the_client(
    client: TestClient, loaded: Session
) -> None:
    bibimbap = loaded.scalar(select(Food).where(Food.canonical_name == "Bibimbap, Korean"))
    assert bibimbap is not None

    body = read_food(client, bibimbap.id)
    sodium = nutrients_of(body)["sodium"]

    assert sodium["status"] == "known"
    assert sodium["amount_per_100g"] == 435.0
    assert sodium["daily_value"] == 2300.0
    assert sodium["source_keys"] == ["usda-fdc-fndds-2024-10"]
    assert sodium["daily_value_source_key"] == "fda-daily-values"
    assert body["recipe_label"] == "USDA survey recipe"
    assert body["portions"] == [
        {"description": "1 cup", "gram_weight": 162.0, "is_household_measure": True},
        {
            "description": "Quantity not specified",
            "gram_weight": 121.0,
            "is_household_measure": False,
        },
    ]


def test_every_cited_source_is_described(client: TestClient, loaded: Session) -> None:
    bibimbap = loaded.scalar(select(Food).where(Food.canonical_name == "Bibimbap, Korean"))
    assert bibimbap is not None

    body = read_food(client, bibimbap.id)

    described = {s["key"] for s in body["sources"]}
    cited = {body["source_key"], body["processing_level_source_key"]}
    for nutrient in body["nutrients"]:
        cited.update(nutrient["source_keys"])
        if nutrient["daily_value_source_key"]:
            cited.add(nutrient["daily_value_source_key"])
    assert cited == described


def test_only_added_sugars_has_a_daily_value(client: TestClient, loaded: Session) -> None:
    """The FDA sets a Daily Value for added sugars and none for total sugars."""
    bibimbap = loaded.scalar(select(Food).where(Food.canonical_name == "Bibimbap, Korean"))
    assert bibimbap is not None

    nutrients = nutrients_of(read_food(client, bibimbap.id))

    assert nutrients["total_sugars"]["status"] == "known"
    assert nutrients["total_sugars"]["unit"] == "g"
    assert nutrients["total_sugars"]["daily_value"] is None
    # USDA has no added-sugar values, so there is a Daily Value but nothing to compare with it.
    assert nutrients["added_sugars"]["daily_value"] == 50.0
    assert nutrients["added_sugars"]["status"] == "unknown"
    assert nutrients["added_sugars"]["amount_per_100g"] is None


def build_dish(session: Session) -> tuple[Food, dict[str, Any]]:
    """A dish that states no sodium itself, with named gaps in its ingredients."""
    load_vocabulary(session)
    source = make_source(session)
    sodium = make_nutrient(session, "sodium")
    protein = make_nutrient(session, "protein", "g")
    salt = make_food(session, "Salt, table", source, values={sodium: 38800.0, protein: 0.0})
    return (
        make_food(session, "Mapo tofu", source, kind=FoodKind.PREPARED_DISH),
        {"source": source, "salt": salt, "sodium": sodium, "protein": protein},
    )


def test_a_complete_recipe_supplies_a_calculated_value(
    client: TestClient, session: Session
) -> None:
    dish, parts = build_dish(session)
    tofu = make_food(session, "Tofu", parts["source"], values={parts["sodium"]: 7.0})
    make_recipe(session, dish, parts["source"], [(parts["salt"], 1.0), (tofu, 99.0)])

    sodium = nutrients_of(read_food(client, dish.id))["sodium"]

    assert sodium["status"] == "calculated"
    # (388 mg + 6.93 mg) in 100 g.
    assert sodium["amount_per_100g"] == pytest.approx(394.93)
    assert sodium["value_kind"] == "calculated"
    assert sodium["missing_ingredients"] == []


def test_cooking_losses_concentrate_a_calculated_value(
    client: TestClient, session: Session
) -> None:
    dish, parts = build_dish(session)
    tofu = make_food(session, "Tofu", parts["source"], values={parts["sodium"]: 7.0})
    make_recipe(
        session,
        dish,
        parts["source"],
        [(parts["salt"], 1.0), (tofu, 99.0)],
        moisture_change_pct=-20.0,
    )

    sodium = nutrients_of(read_food(client, dish.id))["sodium"]

    # The same 394.93 mg, now in the 80 g left after cooking.
    assert sodium["amount_per_100g"] == pytest.approx(493.66, abs=0.01)


def test_a_recipe_with_a_gap_is_a_lower_bound_that_names_the_gap(
    client: TestClient, session: Session
) -> None:
    dish, parts = build_dish(session)
    paste = make_food(session, "Doubanjiang", parts["source"])
    make_recipe(session, dish, parts["source"], [(parts["salt"], 1.0), (paste, 20.0)])

    sodium = nutrients_of(read_food(client, dish.id))["sodium"]

    assert sodium["status"] == "lower_bound"
    # 388 mg known, in a 21 g recipe.
    assert sodium["amount_per_100g"] == pytest.approx(1847.6, abs=0.1)
    assert sodium["missing_ingredients"] == ["Doubanjiang"]


def test_a_partial_total_of_zero_stays_unknown_rather_than_at_least_zero(
    client: TestClient, session: Session
) -> None:
    dish, parts = build_dish(session)
    paste = make_food(session, "Doubanjiang", parts["source"])
    make_recipe(session, dish, parts["source"], [(parts["salt"], 1.0), (paste, 20.0)])

    protein = nutrients_of(read_food(client, dish.id))["protein"]

    # Salt's zero is real, but the paste could hold any amount.
    assert protein["status"] == "unknown"
    assert protein["amount_per_100g"] is None
    assert protein["missing_ingredients"] == ["Doubanjiang"]


def test_an_unquantified_ingredient_blocks_a_number_and_says_why(
    client: TestClient, session: Session
) -> None:
    dish, parts = build_dish(session)
    make_recipe(session, dish, parts["source"], [(parts["salt"], None)])

    sodium = nutrients_of(read_food(client, dish.id))["sodium"]

    assert sodium["status"] == "unknown"
    assert sodium["amount_per_100g"] is None
    assert sodium["missing_ingredients"] == ["Salt, table"]


def test_a_borrowed_value_is_labeled_as_an_estimate(client: TestClient, session: Session) -> None:
    load_vocabulary(session)
    source = make_source(session)
    sodium = make_nutrient(session, "sodium")
    mackerel = make_food(session, "Fish, mackerel, salted", source, values={sodium: 4450.0})
    salted_fish = make_food(session, "Chinese-style salted fish", source)
    make_proxy(session, salted_fish, mackerel, source)

    value = nutrients_of(read_food(client, salted_fish.id))["sodium"]

    assert value["status"] == "estimated"
    assert value["amount_per_100g"] == 4450.0


def test_portions_come_back_in_order(client: TestClient, session: Session) -> None:
    load_vocabulary(session)
    source = make_source(session)
    food = make_food(session, "Rice", source)
    session.add_all(
        [
            FoodPortion(
                food_id=food.id,
                description="Second",
                gram_weight=2.0,
                position=1,
                source_id=source.id,
            ),
            FoodPortion(
                food_id=food.id,
                description="First",
                gram_weight=1.0,
                position=0,
                source_id=source.id,
            ),
        ]
    )
    session.flush()
    assert [p["description"] for p in read_food(client, food.id)["portions"]] == ["First", "Second"]
