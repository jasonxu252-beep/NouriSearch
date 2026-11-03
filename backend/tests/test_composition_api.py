"""The food page's data and its simulations, end to end through HTTP."""

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import (
    Food,
    FoodHealthConsideration,
    FoodImage,
    FoodNutrient,
    FoodPortion,
    HealthConsideration,
    Recipe,
    RecipeComponent,
    Source,
)
from app.db.session import get_session
from app.domain.enums import (
    ConsiderationCategory,
    EvidenceLevel,
    FoodKind,
    Verification,
)
from app.ingest.knowledge import load_allergen_findings
from app.ingest.vocabulary import load_vocabulary
from app.main import create_app
from tests.factories import make_food, make_nutrient, make_recipe, make_source
from tests.test_fdc_loader import load_all
from tests.test_foods_api import add_named_food

pytestmark = pytest.mark.integration


@pytest.fixture
def client(session: Session) -> Iterator[TestClient]:
    app = create_app()

    def override() -> Iterator[Session]:
        yield session

    app.dependency_overrides[get_session] = override
    yield TestClient(app)


@pytest.fixture
def dish(session: Session) -> dict[str, Any]:
    """A small dish, stating its own sodium, with real USDA values per 100 g."""
    load_vocabulary(session)
    source = make_source(session)
    nutrient = make_nutrient(session)
    salt = make_food(session, "Salt, table", source, values={nutrient: 38800.0})
    tofu = make_food(session, "Tofu", source, values={nutrient: 7.0})
    food = make_food(
        session, "Mapo tofu", source, kind=FoodKind.PREPARED_DISH, values={nutrient: 395.0}
    )
    recipe = make_recipe(session, food, source, [(salt, 1.0), (tofu, 99.0)])
    session.add_all(
        [
            FoodPortion(
                food_id=food.id,
                description="Quantity not specified",
                gram_weight=50.0,
                is_household_measure=False,
                position=0,
                source_id=source.id,
            ),
            FoodPortion(
                food_id=food.id,
                description="1 cup",
                gram_weight=200.0,
                is_household_measure=True,
                position=1,
                source_id=source.id,
            ),
        ]
    )
    session.flush()
    components = session.execute(
        select(RecipeComponent.component_food_id, RecipeComponent.id).where(
            RecipeComponent.recipe_id == recipe.id
        )
    ).all()
    ids = {row[0]: row[1] for row in components}
    return {
        "food": food,
        "source": source,
        "nutrient": nutrient,
        "salt_component": ids[salt.id],
        "tofu_component": ids[tofu.id],
        "salt": salt,
        "tofu": tofu,
    }


def composition(client: TestClient, food_id: int) -> dict[str, Any]:
    response = client.get(f"/v1/foods/{food_id}/composition")
    assert response.status_code == 200, response.text
    return response.json()


def simulate(client: TestClient, food_id: int, *components: int) -> dict[str, Any]:
    response = client.post(
        f"/v1/foods/{food_id}/simulations",
        json={"edits": [{"type": "remove", "component_id": c} for c in components]},
    )
    assert response.status_code == 200, response.text
    return response.json()


def nutrient_row(body: dict[str, Any], key: str) -> dict[str, Any]:
    return next(n for n in body["nutrients"] if n["key"] == key)


def evaluation(body: dict[str, Any], serving_key: str) -> dict[str, Any]:
    return next(e for e in body["evaluations"] if e["serving_key"] == serving_key)


def serving_value(body: dict[str, Any], serving_key: str, nutrient: str) -> dict[str, Any]:
    return next(n for n in evaluation(body, serving_key)["nutrients"] if n["key"] == nutrient)


def test_a_missing_food_uses_the_shared_error_shape(client: TestClient, session: Session) -> None:
    load_vocabulary(session)
    for path in ("composition", "related"):
        response = client.get(f"/v1/foods/999999/{path}")
        assert response.status_code == 404
        assert response.json()["code"] == "not_found"
    response = client.post(
        "/v1/foods/999999/simulations", json={"edits": [{"type": "remove", "component_id": 1}]}
    )
    assert response.status_code == 404


def test_every_serving_is_offered_and_a_household_measure_is_the_default(
    client: TestClient, dish: dict[str, Any]
) -> None:
    body = composition(client, dish["food"].id)
    servings = {s["label"]: s for s in body["servings"]}
    assert list(servings) == ["Quantity not specified", "1 cup", "100 g"]
    assert servings["1 cup"]["is_default"] is True
    assert servings["Quantity not specified"]["is_default"] is False
    assert servings["100 g"]["is_default"] is False
    assert [s["is_default"] for s in body["servings"]].count(True) == 1


def test_a_food_with_no_household_measure_defaults_to_100_g(
    client: TestClient, dish: dict[str, Any]
) -> None:
    body = composition(client, dish["salt"].id)
    assert [(s["label"], s["is_default"]) for s in body["servings"]] == [("100 g", True)]


def test_a_placeholder_portion_is_never_the_default(
    client: TestClient, session: Session, dish: dict[str, Any]
) -> None:
    session.add(
        FoodPortion(
            food_id=dish["salt"].id,
            description="Quantity not specified",
            gram_weight=10.0,
            is_household_measure=False,
            position=0,
            source_id=dish["source"].id,
        )
    )
    session.flush()
    body = composition(client, dish["salt"].id)
    default = next(s for s in body["servings"] if s["is_default"])
    assert default["label"] == "100 g"


def test_marks_are_ready_for_every_serving(client: TestClient, dish: dict[str, Any]) -> None:
    body = composition(client, dish["food"].id)
    keys = [s["key"] for s in body["servings"]]
    assert [e["serving_key"] for e in body["evaluations"]] == keys

    # 395 mg per 100 g: 790 mg in 200 g is 34.3% of 2,300 mg. In 50 g it is 197.5 mg, or 8.6%.
    cup = serving_value(body, "portion-1", "sodium")
    assert cup["amount"] == pytest.approx(790.0)
    assert cup["percent_daily_value"] == pytest.approx(34.35, abs=0.01)
    assert cup["mark"] == "exclamation"
    small = serving_value(body, "portion-0", "sodium")
    assert small["percent_daily_value"] == pytest.approx(8.59, abs=0.01)
    assert small["mark"] == "green"


def test_unknown_values_get_the_question_mark_and_no_number(
    client: TestClient, dish: dict[str, Any]
) -> None:
    body = composition(client, dish["food"].id)
    value = serving_value(body, "portion-1", "vitamin_c")
    assert value == {
        "key": "vitamin_c",
        "amount": None,
        "percent_daily_value": None,
        "mark": "question",
    }
    row = nutrient_row(body, "vitamin_c")
    assert row["status"] == "unknown"
    assert row["amount_per_100g"] is None


def test_conclusions_carry_rules_facts_and_sources(
    client: TestClient, dish: dict[str, Any]
) -> None:
    body = composition(client, dish["food"].id)
    conclusions = evaluation(body, "portion-1")["conclusions"]
    assert {c["subject"] for c in conclusions} == {"sodium", "saturated_fat", "added_sugars"}

    sodium = next(c for c in conclusions if c["subject"] == "sodium")
    assert sodium["severity"] == "high"
    assert sodium["rules_triggered"] == [{"id": "nutrient.high_percent_daily_value", "version": 1}]
    assert sodium["uncertainty"] == "verified"
    assert "fda-percent-dv-guide" in sodium["sources"]
    assert {f["key"] for f in sodium["supporting_facts"]} >= {"serving", "daily_value", "threshold"}

    added = next(c for c in conclusions if c["subject"] == "added_sugars")
    assert added["severity"] == "undetermined"
    assert added["code"] == "nutrient.could_not_evaluate"


def test_every_cited_source_is_described(client: TestClient, dish: dict[str, Any]) -> None:
    body = composition(client, dish["food"].id)
    described = {s["key"] for s in body["sources"]}
    assert "fda-percent-dv-guide" in described
    cited = {body["source_key"]}
    for row in body["nutrients"]:
        cited.update(row["source_keys"])
        if row["daily_value_source_key"]:
            cited.add(row["daily_value_source_key"])
    for result in body["evaluations"]:
        for conclusion in result["conclusions"]:
            cited.update(conclusion["sources"])
    assert cited <= described


def test_the_contribution_matrix_is_ready_for_both_directions_of_highlighting(
    client: TestClient, dish: dict[str, Any]
) -> None:
    body = composition(client, dish["food"].id)
    cells = {(c["nutrient_key"], c["component_id"]): c for c in body["contributions"]}
    salt = cells["sodium", dish["salt_component"]]
    tofu = cells["sodium", dish["tofu_component"]]
    assert salt["status"] == "known"
    # 388 mg from salt and 6.93 mg from tofu.
    assert salt["amount"] == pytest.approx(388.0)
    assert salt["share"] == pytest.approx(388.0 / 394.93)
    assert tofu["share"] == pytest.approx(6.93 / 394.93)

    # Every ingredient appears for every nutrient, including where it has no data.
    assert len(body["contributions"]) == len(body["ingredients"]) * len(body["nutrients"])
    protein = cells["protein", dish["salt_component"]]
    assert protein["status"] == "no_data"
    assert protein["amount"] is None
    assert protein["share"] is None


def test_ingredient_rows_describe_the_recipe(client: TestClient, dish: dict[str, Any]) -> None:
    body = composition(client, dish["food"].id)
    assert body["recipe"]["raw_weight_g"] == pytest.approx(100.0)
    salt = next(i for i in body["ingredients"] if i["name"] == "Salt, table")
    assert salt["weight_g"] == 1.0
    assert salt["weight_share"] == pytest.approx(0.01)
    assert salt["has_own_recipe"] is False
    assert salt["excluded"] is False
    assert salt["considerations"] == []


def test_a_food_with_no_recipe_has_no_ingredients_and_still_has_values(
    client: TestClient, dish: dict[str, Any]
) -> None:
    body = composition(client, dish["salt"].id)
    assert body["recipe"] is None
    assert body["ingredients"] == []
    assert body["contributions"] == []
    assert nutrient_row(body, "sodium")["amount_per_100g"] == 38800.0


def test_additive_warnings_reach_the_ingredient(
    client: TestClient, session: Session, dish: dict[str, Any]
) -> None:
    """The sketch's Red 40. USDA's generic foods list no additives, so this is curated later."""
    source = dish["source"]
    red_40 = make_food(session, "Red 40", source, kind=FoodKind.ADDITIVE)
    consideration = HealthConsideration(
        key="artificial_color_red_40",
        name="Artificial color",
        category=ConsiderationCategory.ADDITIVE,
        explanation="Fixture text.",
    )
    session.add(consideration)
    session.flush()
    session.add(
        FoodHealthConsideration(
            food_id=red_40.id,
            health_consideration_id=consideration.id,
            source_id=source.id,
            context="Fixture context.",
            evidence_level=EvidenceLevel.EDITORIAL,
            verification=Verification.TYPICAL,
        )
    )
    candy = make_food(session, "Candy", source, kind=FoodKind.PREPARED_DISH)
    make_recipe(session, candy, source, [(red_40, 1.0)])

    ingredient = composition(client, candy.id)["ingredients"][0]

    assert ingredient["kind"] == "additive"
    assert ingredient["considerations"] == ["artificial_color_red_40"]


def test_images_carry_their_license_and_attribution(
    client: TestClient, session: Session, dish: dict[str, Any]
) -> None:
    session.add(
        FoodImage(
            food_id=dish["food"].id,
            position=0,
            url="https://example.org/mapo.jpg",
            license="CC-BY-4.0",
            attribution="A photographer",
            source_id=dish["source"].id,
        )
    )
    session.flush()
    assert composition(client, dish["food"].id)["images"] == [
        {
            "url": "https://example.org/mapo.jpg",
            "license": "CC-BY-4.0",
            "attribution": "A photographer",
        }
    ]


def test_an_unedited_composition_says_so(client: TestClient, dish: dict[str, Any]) -> None:
    body = composition(client, dish["food"].id)
    assert body["is_modified"] is False
    row = nutrient_row(body, "sodium")
    assert row["base_amount_per_100g"] is None
    assert row["delta_per_100g"] is None
    assert row["approximate"] is False


def test_removing_an_ingredient_recalculates_the_dish(
    client: TestClient, dish: dict[str, Any]
) -> None:
    body = simulate(client, dish["food"].id, dish["salt_component"])

    assert body["is_modified"] is True
    salt = next(i for i in body["ingredients"] if i["name"] == "Salt, table")
    assert salt["excluded"] is True
    row = nutrient_row(body, "sodium")
    # 395 mg in 100 g, less 388 mg from salt, leaves 7 mg in 99 g.
    assert row["amount_per_100g"] == pytest.approx(7.07, abs=0.01)
    assert row["base_amount_per_100g"] == 395.0
    assert row["delta_per_100g"] == pytest.approx(7.07 - 395.0, abs=0.01)
    assert row["status"] == "calculated"
    assert row["value_kind"] == "calculated"


def test_a_simulation_updates_the_marks(client: TestClient, dish: dict[str, Any]) -> None:
    assert serving_value(composition(client, dish["food"].id), "portion-1", "sodium")["mark"] == (
        "exclamation"
    )
    body = simulate(client, dish["food"].id, dish["salt_component"])
    assert serving_value(body, "portion-1", "sodium")["mark"] == "green"


def test_a_simulation_removes_the_ingredient_from_the_shares(
    client: TestClient, dish: dict[str, Any]
) -> None:
    body = simulate(client, dish["food"].id, dish["salt_component"])
    cells = [c for c in body["contributions"] if c["nutrient_key"] == "sodium"]
    assert [c["component_id"] for c in cells] == [dish["tofu_component"]]
    assert cells[0]["share"] == pytest.approx(1.0)


def test_removing_an_ingredient_with_no_value_makes_that_nutrient_unknown(
    client: TestClient, session: Session, dish: dict[str, Any]
) -> None:
    source = dish["source"]
    paste = make_food(session, "Doubanjiang", source)
    food = make_food(
        session,
        "Tofu with paste",
        source,
        kind=FoodKind.PREPARED_DISH,
        values={dish["nutrient"]: 500.0},
    )
    recipe = make_recipe(session, food, source, [(paste, 20.0), (dish["tofu"], 80.0)])
    component = session.scalar(
        select(RecipeComponent.id).where(
            RecipeComponent.recipe_id == recipe.id, RecipeComponent.component_food_id == paste.id
        )
    )
    assert component is not None

    row = nutrient_row(simulate(client, food.id, component), "sodium")

    assert row["status"] == "unknown"
    assert row["amount_per_100g"] is None
    assert row["missing_ingredients"] == ["Doubanjiang"]


def test_a_value_rebuilt_from_a_recipe_is_rebuilt_without_the_ingredient(
    client: TestClient, session: Session, dish: dict[str, Any]
) -> None:
    source = dish["source"]
    food = make_food(session, "Unstated dish", source, kind=FoodKind.PREPARED_DISH)
    recipe = make_recipe(session, food, source, [(dish["salt"], 1.0), (dish["tofu"], 99.0)])
    component = session.scalar(
        select(RecipeComponent.id).where(
            RecipeComponent.recipe_id == recipe.id,
            RecipeComponent.component_food_id == dish["salt"].id,
        )
    )
    assert component is not None

    row = nutrient_row(simulate(client, food.id, component), "sodium")

    assert row["status"] == "calculated"
    assert row["amount_per_100g"] == pytest.approx(7.0)
    assert row["base_amount_per_100g"] == pytest.approx(394.93)


def post_edits(client: TestClient, food_id: int, edits: list[dict[str, Any]]) -> dict[str, Any]:
    response = client.post(f"/v1/foods/{food_id}/simulations", json={"edits": edits})
    assert response.status_code == 200, response.text
    return response.json()


def test_scaling_an_ingredient_recalculates_the_dish_and_keeps_its_old_weight(
    client: TestClient, dish: dict[str, Any]
) -> None:
    body = post_edits(
        client,
        dish["food"].id,
        [{"type": "scale", "component_id": dish["salt_component"], "factor": 0.5}],
    )
    # 395 mg in 100 g, less half the salt's 388 mg, leaves 201 mg in 99.5 g.
    assert nutrient_row(body, "sodium")["amount_per_100g"] == pytest.approx(202.01, abs=0.01)
    salt = next(i for i in body["ingredients"] if i["name"] == "Salt, table")
    assert salt["edit"] == "scaled"
    assert salt["weight_g"] == 0.5
    assert salt["original_weight_g"] == 1.0
    assert salt["excluded"] is False
    # The shares follow the edited recipe: 194 mg from salt, 6.93 mg from tofu.
    cell = next(
        c
        for c in body["contributions"]
        if c["nutrient_key"] == "sodium" and c["component_id"] == dish["salt_component"]
    )
    assert cell["amount"] == pytest.approx(194.0)
    assert body["recipe"]["raw_weight_g"] == 99.5


def test_replacing_an_ingredient_swaps_its_row_values_and_marks(
    client: TestClient, session: Session, dish: dict[str, Any]
) -> None:
    substitute = make_food(session, "Lemon juice", dish["source"], values={dish["nutrient"]: 1.0})
    body = post_edits(
        client,
        dish["food"].id,
        [
            {
                "type": "replace",
                "component_id": dish["salt_component"],
                "replacements": [{"food_id": substitute.id, "ratio": 2.0}],
            }
        ],
    )

    # 395 mg less the salt's 388 mg plus 2 g at 1 mg per 100 g is 7.02 mg, in 101 g.
    row = nutrient_row(body, "sodium")
    assert row["amount_per_100g"] == pytest.approx(6.95, abs=0.01)
    assert row["base_amount_per_100g"] == 395.0
    assert row["status"] == "calculated"
    assert serving_value(body, "portion-1", "sodium")["mark"] == "green"

    salt = next(i for i in body["ingredients"] if i["name"] == "Salt, table")
    assert salt["edit"] == "replaced"
    assert salt["excluded"] is True
    assert salt["weight_share"] is None
    arrived = next(i for i in body["ingredients"] if i["name"] == "Lemon juice")
    assert arrived["edit"] == "added"
    assert arrived["excluded"] is False
    assert arrived["replaces_component_id"] == dish["salt_component"]
    assert arrived["weight_g"] == 2.0
    assert arrived["original_weight_g"] is None
    assert arrived["component_id"] < 0
    # New rows follow the ingredient they replace.
    names = [i["name"] for i in body["ingredients"]]
    assert names.index("Lemon juice") == names.index("Salt, table") + 1

    cells = {c["component_id"]: c for c in body["contributions"] if c["nutrient_key"] == "sodium"}
    assert dish["salt_component"] not in cells
    assert cells[arrived["component_id"]]["amount"] == pytest.approx(0.02)


def test_one_ingredient_can_become_several_through_the_api(
    client: TestClient, session: Session, dish: dict[str, Any]
) -> None:
    lemon = make_food(session, "Lemon juice", dish["source"], values={dish["nutrient"]: 1.0})
    body = post_edits(
        client,
        dish["food"].id,
        [
            {
                "type": "replace",
                "component_id": dish["salt_component"],
                "replacements": [
                    {"food_id": dish["salt"].id, "ratio": 0.5},
                    {"food_id": lemon.id, "ratio": 0.5},
                ],
            }
        ],
    )
    arrived = [i for i in body["ingredients"] if i["edit"] == "added"]
    assert [(i["name"], i["weight_g"]) for i in arrived] == [
        ("Salt, table", 0.5),
        ("Lemon juice", 0.5),
    ]
    assert len({i["component_id"] for i in arrived}) == 2
    # 395 mg less 388 mg plus 194 mg of salt and 0.005 mg of lemon, in the same 100 g.
    assert nutrient_row(body, "sodium")["amount_per_100g"] == pytest.approx(201.0, abs=0.01)


def test_adding_an_ingredient_adds_a_row_and_its_nutrients(
    client: TestClient, session: Session, dish: dict[str, Any]
) -> None:
    egg = make_food(session, "Egg", dish["source"], values={dish["nutrient"]: 142.0})
    body = post_edits(
        client, dish["food"].id, [{"type": "add", "food_id": egg.id, "weight_g": 50.0}]
    )

    # 395 mg plus 71 mg is 466 mg, in 150 g.
    assert nutrient_row(body, "sodium")["amount_per_100g"] == pytest.approx(310.67, abs=0.01)
    arrived = next(i for i in body["ingredients"] if i["name"] == "Egg")
    assert arrived["edit"] == "added"
    assert arrived["replaces_component_id"] is None
    assert body["ingredients"][-1]["name"] == "Egg"


def test_several_kinds_of_edit_apply_together(
    client: TestClient, session: Session, dish: dict[str, Any]
) -> None:
    egg = make_food(session, "Egg", dish["source"], values={dish["nutrient"]: 142.0})
    body = post_edits(
        client,
        dish["food"].id,
        [
            {"type": "remove", "component_id": dish["salt_component"]},
            {"type": "scale", "component_id": dish["tofu_component"], "factor": 2.0},
            {"type": "add", "food_id": egg.id, "weight_g": 2.0},
        ],
    )
    # 395 mg less 388 mg of salt, plus 6.93 mg more tofu and 2.84 mg of egg, is 16.77 mg in 200 g.
    assert nutrient_row(body, "sodium")["amount_per_100g"] == pytest.approx(8.385, abs=0.01)


def test_a_new_ingredient_with_no_value_leaves_that_nutrient_unknown_and_named(
    client: TestClient, session: Session, dish: dict[str, Any]
) -> None:
    mystery = make_food(session, "Coconut aminos", dish["source"])
    row = nutrient_row(
        post_edits(
            client,
            dish["food"].id,
            [
                {
                    "type": "replace",
                    "component_id": dish["salt_component"],
                    "replacements": [{"food_id": mystery.id, "ratio": 1.0}],
                }
            ],
        ),
        "sodium",
    )
    assert row["status"] == "unknown"
    assert row["amount_per_100g"] is None
    assert row["delta_per_100g"] is None
    assert row["missing_ingredients"] == ["Coconut aminos"]


def test_a_dish_with_a_rebuilt_value_is_rebuilt_from_its_new_ingredients(
    client: TestClient, session: Session, dish: dict[str, Any]
) -> None:
    source = dish["source"]
    food = make_food(session, "Unstated dish", source, kind=FoodKind.PREPARED_DISH)
    make_recipe(session, food, source, [(dish["salt"], 1.0), (dish["tofu"], 99.0)])
    component = session.scalar(
        select(RecipeComponent.id).where(
            RecipeComponent.component_food_id == dish["salt"].id,
            RecipeComponent.recipe_id
            == select(Recipe.id).where(Recipe.dish_id == food.id).scalar_subquery(),
        )
    )
    egg = make_food(session, "Egg", source, values={dish["nutrient"]: 142.0})
    row = nutrient_row(
        post_edits(
            client,
            food.id,
            [
                {
                    "type": "replace",
                    "component_id": component,
                    "replacements": [{"food_id": egg.id, "ratio": 1.0}],
                }
            ],
        ),
        "sodium",
    )
    # 99 g at 7 mg per 100 g is 6.93 mg, and 1 g of egg is 1.42 mg, in 100 g.
    assert row["status"] == "calculated"
    assert row["amount_per_100g"] == pytest.approx(8.35)


def test_ingredient_rows_and_the_dish_list_allergens_and_follow_edits(
    client: TestClient, session: Session, dish: dict[str, Any]
) -> None:
    load_allergen_findings(session)
    source = dish["source"]
    cheese = make_food(session, "Cheese, cheddar", source, values={dish["nutrient"]: 654.0})
    bread = make_food(session, "Plain slices", source, values={dish["nutrient"]: 400.0})
    food = make_food(
        session, "House melt", source, kind=FoodKind.PREPARED_DISH, values={dish["nutrient"]: 500.0}
    )
    recipe = make_recipe(session, food, source, [(cheese, 50.0), (bread, 50.0)])
    load_allergen_findings(session)
    component = session.scalar(
        select(RecipeComponent.id).where(
            RecipeComponent.recipe_id == recipe.id, RecipeComponent.component_food_id == cheese.id
        )
    )

    body = composition(client, food.id)
    assert [(a["key"], a["relation"], a["ingredient_names"]) for a in body["allergens"]] == [
        ("milk", "contains", ["Cheese, cheddar"])
    ]
    row = next(i for i in body["ingredients"] if i["name"] == "Cheese, cheddar")
    assert [(a["key"], a["relation"]) for a in row["allergens"]] == [("milk", "contains")]

    without = post_edits(client, food.id, [{"type": "remove", "component_id": component}])
    assert without["allergens"] == []

    tofu = dish["tofu"]
    swapped = post_edits(
        client,
        food.id,
        [
            {
                "type": "replace",
                "component_id": component,
                "replacements": [{"food_id": tofu.id, "ratio": 1.0}],
            }
        ],
    )
    assert [(a["key"], a["ingredient_names"]) for a in swapped["allergens"]] == [
        ("soybeans", ["Tofu"])
    ]


def test_a_name_that_states_an_allergen_keeps_it_through_edits(
    client: TestClient, session: Session, dish: dict[str, Any]
) -> None:
    """Removing the listed cheese from mac and cheese leaves a dish still sold as having cheese."""
    source = dish["source"]
    cheese = make_food(session, "Cheese, cheddar", source, values={dish["nutrient"]: 654.0})
    food = make_food(
        session,
        "Cheese melt",
        source,
        kind=FoodKind.PREPARED_DISH,
        values={dish["nutrient"]: 500.0},
    )
    recipe = make_recipe(session, food, source, [(cheese, 50.0), (dish["tofu"], 50.0)])
    load_allergen_findings(session)
    component = session.scalar(
        select(RecipeComponent.id).where(
            RecipeComponent.recipe_id == recipe.id, RecipeComponent.component_food_id == cheese.id
        )
    )
    body = post_edits(client, food.id, [{"type": "remove", "component_id": component}])
    assert "milk" in {a["key"] for a in body["allergens"]}


def test_a_food_with_nothing_found_lists_nothing_and_claims_nothing(
    client: TestClient, session: Session, dish: dict[str, Any]
) -> None:
    load_allergen_findings(session)
    body = composition(client, dish["salt"].id)
    assert body["allergens"] == []
    assert "free_of" not in str(body)


def test_a_simulation_writes_nothing(
    client: TestClient, session: Session, dish: dict[str, Any]
) -> None:
    def counts() -> tuple[int | None, ...]:
        return tuple(
            session.scalar(select(func.count()).select_from(model))
            for model in (Food, FoodNutrient, Recipe, RecipeComponent, FoodPortion, Source)
        )

    before = counts()
    simulate(client, dish["food"].id, dish["salt_component"])
    assert counts() == before
    # The next plain read is untouched too.
    body = composition(client, dish["food"].id)
    assert nutrient_row(body, "sodium")["amount_per_100g"] == 395.0
    assert len(body["ingredients"]) == 2


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"edits": []},
        {"edits": [{"type": "scale", "component_id": 1}]},
        {"edits": [{"type": "scale", "component_id": 1, "factor": 0}]},
        {"edits": [{"type": "scale", "component_id": 1, "factor": -1}]},
        {"edits": [{"type": "scale", "component_id": 1, "factor": 11}]},
        {"edits": [{"type": "remove"}]},
        {"edits": [{"type": "remove", "component_id": 1}, {"type": "remove", "component_id": 1}]},
        {
            "edits": [
                {"type": "remove", "component_id": 1},
                {"type": "scale", "component_id": 1, "factor": 2},
            ]
        },
        {"edits": [{"type": "replace", "component_id": 1, "replacements": []}]},
        {"edits": [{"type": "replace", "component_id": 1}]},
        {
            "edits": [
                {"type": "replace", "component_id": 1, "replacements": [{"food_id": 1, "ratio": 0}]}
            ]
        },
        {
            "edits": [
                {
                    "type": "replace",
                    "component_id": 1,
                    "replacements": [{"food_id": 1, "ratio": 21}],
                }
            ]
        },
        {
            "edits": [
                {
                    "type": "replace",
                    "component_id": 1,
                    "replacements": [{"food_id": 1, "ratio": 1}, {"food_id": 1, "ratio": 1}],
                }
            ]
        },
        {"edits": [{"type": "add", "food_id": 1}]},
        {"edits": [{"type": "add", "weight_g": 1}]},
        {"edits": [{"type": "add", "food_id": 1, "weight_g": 0}]},
        {"edits": [{"type": "add", "food_id": 1, "weight_g": 100001}]},
        {
            "edits": [
                {"type": "add", "food_id": 1, "weight_g": 1},
                {"type": "add", "food_id": 1, "weight_g": 2},
            ]
        },
        {"edits": [{"type": "explode", "component_id": 1}]},
    ],
)
def test_malformed_simulations_use_the_shared_error_shape(
    client: TestClient, dish: dict[str, Any], payload: dict[str, Any]
) -> None:
    response = client.post(f"/v1/foods/{dish['food'].id}/simulations", json=payload)
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_request"


def test_an_ingredient_from_another_food_is_rejected(
    client: TestClient, dish: dict[str, Any]
) -> None:
    response = client.post(
        f"/v1/foods/{dish['food'].id}/simulations",
        json={"edits": [{"type": "remove", "component_id": 999999}]},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_request"
    assert "999999" in response.json()["message"]


def test_a_recipe_cannot_exclude_everything(client: TestClient, dish: dict[str, Any]) -> None:
    response = client.post(
        f"/v1/foods/{dish['food'].id}/simulations",
        json={
            "edits": [
                {"type": "remove", "component_id": dish["salt_component"]},
                {"type": "remove", "component_id": dish["tofu_component"]},
            ]
        },
    )
    assert response.status_code == 422
    assert "every ingredient" in response.json()["message"]


@pytest.mark.parametrize(
    "edit",
    [
        {"type": "add", "food_id": 999999, "weight_g": 10.0},
        {
            "type": "replace",
            "component_id": "SALT",
            "replacements": [{"food_id": 999999, "ratio": 1.0}],
        },
    ],
)
def test_a_food_that_does_not_exist_cannot_be_brought_in(
    client: TestClient, dish: dict[str, Any], edit: dict[str, Any]
) -> None:
    if edit.get("component_id") == "SALT":
        edit = {**edit, "component_id": dish["salt_component"]}
    response = client.post(f"/v1/foods/{dish['food'].id}/simulations", json={"edits": [edit]})
    assert response.status_code == 422
    assert "999999" in response.json()["message"]


def test_nothing_can_be_added_to_a_food_without_a_recipe(
    client: TestClient, dish: dict[str, Any]
) -> None:
    response = client.post(
        f"/v1/foods/{dish['salt'].id}/simulations",
        json={"edits": [{"type": "add", "food_id": dish["tofu"].id, "weight_g": 10.0}]},
    )
    assert response.status_code == 422
    assert "no recipe" in response.json()["message"]


def test_a_food_without_a_recipe_cannot_be_edited(client: TestClient, dish: dict[str, Any]) -> None:
    response = client.post(
        f"/v1/foods/{dish['salt'].id}/simulations",
        json={"edits": [{"type": "remove", "component_id": 1}]},
    )
    assert response.status_code == 422


def related(client: TestClient, food_id: int, **params: Any) -> dict[str, Any]:
    response = client.get(f"/v1/foods/{food_id}/related", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def test_a_dish_is_similar_to_dishes_sharing_its_rarer_ingredients(
    client: TestClient, session: Session
) -> None:
    load_vocabulary(session)
    source = make_source(session)
    salt = make_food(session, "Salt", source)
    sprouts = make_food(session, "Mung bean sprouts", source)
    rice = make_food(session, "Rice", source)
    me = add_named_food(session, source, "Bibimbap", kind=FoodKind.PREPARED_DISH)
    make_recipe(session, me, source, [(salt, 1.0), (sprouts, 1.0)])
    shares_rare = add_named_food(session, source, "Sprout salad", kind=FoodKind.PREPARED_DISH)
    make_recipe(session, shares_rare, source, [(sprouts, 1.0)])
    shares_common = add_named_food(session, source, "Salty soup", kind=FoodKind.PREPARED_DISH)
    make_recipe(session, shares_common, source, [(salt, 1.0)])
    also_common = add_named_food(session, source, "Salted rice", kind=FoodKind.PREPARED_DISH)
    make_recipe(session, also_common, source, [(salt, 1.0), (rice, 1.0)])

    similar = related(client, me.id)["similar"]

    assert similar[0]["name"] == "Sprout salad"
    assert similar[0]["reason"] == "shares_ingredients"
    assert similar[0]["shared_ingredients"] == ["Mung bean sprouts"]
    assert {s["name"] for s in similar} == {"Sprout salad", "Salty soup", "Salted rice"}


def test_a_plain_food_is_similar_to_the_dishes_using_it(
    client: TestClient, session: Session
) -> None:
    load_vocabulary(session)
    source = make_source(session)
    salt = add_named_food(session, source, "Salt", group="seasonings")
    dish = add_named_food(session, source, "Salty soup", kind=FoodKind.PREPARED_DISH)
    make_recipe(session, dish, source, [(salt, 1.0)])

    similar = related(client, salt.id)["similar"]

    assert [(s["name"], s["reason"]) for s in similar] == [("Salty soup", "uses_this_food")]


def test_a_food_nothing_uses_falls_back_to_similar_names_in_its_group(
    client: TestClient, session: Session
) -> None:
    load_vocabulary(session)
    source = make_source(session)
    apple = add_named_food(session, source, "Apple, fuji", group="fruits")
    add_named_food(session, source, "Apple, gala", group="fruits")
    add_named_food(session, source, "Apple pie", group="sweets")

    similar = related(client, apple.id)["similar"]

    assert [(s["name"], s["reason"]) for s in similar] == [("Apple, gala", "similar_name")]


def test_explore_offers_the_rest_of_the_group_whole_foods_first(
    client: TestClient, session: Session
) -> None:
    load_vocabulary(session)
    source = make_source(session)
    me = add_named_food(session, source, "Apple, fuji", group="fruits")
    add_named_food(session, source, "A processed fruit", group="fruits", level="processed")
    add_named_food(session, source, "A whole fruit, raw", group="fruits", level="whole")
    add_named_food(session, source, "Spinach", group="vegetables", level="whole")

    explore = related(client, me.id)["explore"]

    assert [e["name"] for e in explore] == ["A whole fruit, raw", "A processed fruit"]
    assert {e["reason"] for e in explore} == {"same_group"}


def test_related_foods_hide_records_that_support_others(
    client: TestClient, session: Session
) -> None:
    load_vocabulary(session)
    source = make_source(session)
    me = add_named_food(session, source, "Rice", group="grains")
    add_named_food(session, source, "Rice, as ingredient", group="grains", discoverable=False)
    assert related(client, me.id) == {"similar": [], "explore": []}


def test_the_limit_applies(client: TestClient, session: Session) -> None:
    load_vocabulary(session)
    source = make_source(session)
    me = add_named_food(session, source, "Rice", group="grains")
    for i in range(4):
        add_named_food(session, source, f"Grain {i}", group="grains")
    assert len(related(client, me.id, limit=2)["explore"]) == 2


def test_real_sample_records_produce_a_complete_page(client: TestClient, session: Session) -> None:
    load_vocabulary(session)
    load_all(session)
    food_id = session.scalar(select(Food.id).where(Food.canonical_name == "Custard"))
    assert food_id is not None

    body = composition(client, food_id)

    assert body["recipe"]["label"] == "USDA survey recipe"
    assert body["recipe"]["moisture_change_pct"] == -10.0
    assert body["recipe"]["cooked_weight_g"] == pytest.approx(body["recipe"]["raw_weight_g"] * 0.9)
    assert len(body["nutrients"]) == 41
    assert "Eggs, Grade A, Large, egg whole" in {i["name"] for i in body["ingredients"]}
