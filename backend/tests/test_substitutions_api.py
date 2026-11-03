"""Ranking swaps through HTTP, and using them. Excluded allergens must never appear."""

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import (
    Allergen,
    Cuisine,
    Food,
    FoodAllergen,
    FoodClassification,
    FoodCuisine,
    FoodPortion,
    FoodRole,
    FoodSensory,
    IngredientRole,
    Nutrient,
    RecipeComponent,
    SensoryAttribute,
    Source,
    SubstitutionComponent,
    SubstitutionOption,
)
from app.db.session import get_session
from app.domain.enums import (
    AllergenRelation,
    FoodClassificationKind,
    FoodKind,
    Verification,
)
from app.ingest.vocabulary import load_vocabulary
from app.main import create_app
from tests.factories import make_food, make_nutrient, make_recipe, make_source, make_substitution

pytestmark = pytest.mark.integration

ALLERGEN_KEYS = [
    "milk",
    "eggs",
    "fish",
    "crustacean_shellfish",
    "tree_nuts",
    "peanuts",
    "wheat",
    "soybeans",
    "sesame",
]


@pytest.fixture
def client(session: Session) -> Iterator[TestClient]:
    app = create_app()

    def override() -> Iterator[Session]:
        yield session

    app.dependency_overrides[get_session] = override
    yield TestClient(app)


class World:
    """A small dish, stating its own values, and helpers to give foods curated knowledge."""

    def __init__(self, session: Session) -> None:
        load_vocabulary(session)
        self.session = session
        self.source = make_source(session)
        self.editorial = session.scalar(select(Source).where(Source.key == "nourisearch-editorial"))
        assert self.editorial is not None
        self.sodium = make_nutrient(session, "sodium", "mg")
        self.saturated_fat = make_nutrient(session, "saturated_fat", "g")
        self.protein = make_nutrient(session, "protein", "g")
        self.salt = self.food("Salt, table", sodium=38800.0, saturated_fat=0.0, protein=0.0)
        self.sauce = self.food("Shoyu", sodium=5490.0, saturated_fat=0.0, protein=8.0)
        self.rice = self.food("White rice", sodium=1.0, saturated_fat=0.0, protein=2.7)
        # 1000 g holding 7,760 mg from salt, 2,745 mg from shoyu, and 9.5 mg from rice.
        self.dish = self.food(
            "House rice",
            kind=FoodKind.PREPARED_DISH,
            sodium=1051.45,
            saturated_fat=0.0,
            protein=6.6,
        )
        make_recipe(
            session,
            self.dish,
            self.source,
            [(self.salt, 20.0), (self.sauce, 50.0), (self.rice, 930.0)],
        )

    def food(self, name: str, kind: FoodKind = FoodKind.BASIC, **values: float | None) -> Food:
        nutrients = {
            getattr(self, key): amount for key, amount in values.items() if amount is not None
        }
        return make_food(self.session, name, self.source, kind=kind, values=nutrients)

    def component(self, food: Food) -> int:
        component_id = self.session.scalar(
            select(RecipeComponent.id).where(RecipeComponent.component_food_id == food.id)
        )
        assert component_id is not None
        return component_id

    def swap(
        self,
        from_food: Food,
        *to_foods: tuple[Food, float],
        fit: int | None = 4,
        note: str | None = "A note.",
        role: str | None = None,
        cuisine: str | None = None,
    ) -> SubstitutionOption:
        assert self.editorial is not None
        option = make_substitution(self.session, from_food, list(to_foods), self.editorial)
        option.culinary_fit = fit
        option.notes = note
        if role:
            option.role_id = self.session.scalar(
                select(IngredientRole.id).where(IngredientRole.key == role)
            )
        if cuisine:
            option.cuisine_id = self.session.scalar(
                select(Cuisine.id).where(Cuisine.key == cuisine)
            )
        self.session.flush()
        return option

    def allergen(
        self, food: Food, key: str, relation: AllergenRelation = AllergenRelation.CONTAINS
    ) -> None:
        assert self.editorial is not None
        allergen_id = self.session.scalar(select(Allergen.id).where(Allergen.key == key))
        assert allergen_id is not None
        self.session.add(
            FoodAllergen(
                food_id=food.id,
                allergen_id=allergen_id,
                source_id=self.editorial.id,
                relation=relation,
                verification=Verification.TYPICAL,
            )
        )
        self.session.flush()

    def role(self, food: Food, key: str, offered: bool = True) -> None:
        assert self.editorial is not None
        role_id = self.session.scalar(select(IngredientRole.id).where(IngredientRole.key == key))
        assert role_id is not None
        self.session.add(
            FoodRole(
                food_id=food.id, role_id=role_id, source_id=self.editorial.id, is_offered=offered
            )
        )
        self.session.flush()

    def sensory(self, food: Food, **attributes: int) -> None:
        assert self.editorial is not None
        for key, intensity in attributes.items():
            attribute_id = self.session.scalar(
                select(SensoryAttribute.id).where(SensoryAttribute.key == key)
            )
            assert attribute_id is not None
            self.session.add(
                FoodSensory(
                    food_id=food.id,
                    attribute_id=attribute_id,
                    source_id=self.editorial.id,
                    intensity=intensity,
                )
            )
        self.session.flush()

    def diet(self, food: Food, *kinds: FoodClassificationKind) -> None:
        assert self.editorial is not None
        for kind in kinds:
            self.session.add(
                FoodClassification(
                    food_id=food.id,
                    classification=kind,
                    source_id=self.editorial.id,
                    verification=Verification.TYPICAL,
                )
            )
        self.session.flush()


@pytest.fixture
def world(session: Session) -> World:
    return World(session)


def ranked(client: TestClient, world: World, food: Food, **body: Any) -> dict[str, Any]:
    response = client.post(
        f"/v1/foods/{world.dish.id}/substitutions",
        json={"component_id": world.component(food), "goal": "less_sodium", **body},
    )
    assert response.status_code == 200, response.text
    return response.json()


def option_foods(option: dict[str, Any]) -> list[str]:
    return [item["name"] for item in option["replacements"]]


def names_offered(body: dict[str, Any]) -> list[str]:
    return [name for option in body["options"] for name in option_foods(option)]


def replacement(body: dict[str, Any], name: str) -> dict[str, Any]:
    return next(option for option in body["options"] if option_foods(option) == [name])


def test_a_reviewed_swap_comes_with_its_hand_computed_effect(
    client: TestClient, world: World
) -> None:
    low = world.food("Shoyu, low sodium", sodium=3600.0, saturated_fat=0.0, protein=9.0)
    world.swap(world.sauce, (low, 1.0))

    option = replacement(ranked(client, world, world.sauce), "Shoyu, low sodium")

    # The 1000 g batch holds 10,514.5 mg. 50 g of shoyu holds 2,745 mg and its swap holds 1,800 mg,
    # so 945 mg leave: 9,569.5 mg in the same 1000 g.
    effect = option["goal_effect"]
    assert effect["nutrient_key"] == "sodium"
    assert effect["unit"] == "mg"
    assert effect["before_per_100g"] == pytest.approx(1051.45)
    assert effect["after_per_100g"] == pytest.approx(956.95)
    assert option["origin"] == "curated"
    assert option["verification"] == "typical"
    assert option["note"] == "A note."
    assert option["edit"] == {
        "type": "replace",
        "component_id": world.component(world.sauce),
        "replacements": [{"food_id": low.id, "ratio": 1.0}],
    }
    assert option["replacements"][0]["weight_g"] == 50.0


def test_the_response_exposes_every_part_of_the_score(client: TestClient, world: World) -> None:
    low = world.food("Shoyu, low sodium", sodium=3600.0)
    world.swap(world.sauce, (low, 1.0), fit=5)
    world.sensory(world.sauce, salty=5, umami=5)
    world.sensory(low, salty=4, umami=5)
    world.role(world.sauce, "sauce")

    scores = replacement(ranked(client, world, world.sauce), "Shoyu, low sodium")["scores"]

    # Sodium falls by 94.5 of 1051.45, or 0.0899, and half earns full credit, giving 0.1797.
    assert scores["nutrition"] == pytest.approx(0.0899 / 0.5, abs=0.001)
    # The profiles worked out in the scoring tests, and a fit of 5 out of 5.
    assert scores["flavor"] == pytest.approx(0.875)
    assert scores["culinary_fit"] == 1.0
    # A sauce has no texture to compare, so the rest of the weight is complete.
    assert scores["texture"] is None
    assert scores["preference"] is None
    assert scores["completeness"] == 1.0
    assert scores["total"] == pytest.approx(
        (0.5 * scores["nutrition"] + 0.2 * 0.875 + 0.2 * 1.0) / 0.9
    )


def test_using_the_returned_edit_reaches_the_same_value(client: TestClient, world: World) -> None:
    low = world.food("Shoyu, low sodium", sodium=3600.0)
    world.swap(world.sauce, (low, 1.0))
    option = replacement(ranked(client, world, world.sauce), "Shoyu, low sodium")

    response = client.post(
        f"/v1/foods/{world.dish.id}/simulations", json={"edits": [option["edit"]]}
    )

    assert response.status_code == 200
    body = response.json()
    sodium = next(n for n in body["nutrients"] if n["key"] == "sodium")
    assert sodium["amount_per_100g"] == pytest.approx(option["goal_effect"]["after_per_100g"])


def test_what_stays_from_the_original_reads_first(client: TestClient, world: World) -> None:
    # Salt has the lower ID here, so sorting by ID alone would put it first.
    world.swap(world.sauce, (world.salt, 0.01), (world.sauce, 0.5))
    both = next(
        o for o in ranked(client, world, world.sauce)["options"] if len(o["replacements"]) == 2
    )
    assert [item["name"] for item in both["replacements"]] == ["Shoyu", "Salt, table"]
    assert both["edit"]["replacements"][0]["food_id"] == world.sauce.id


def test_using_less_is_offered_with_its_reason_and_factor(client: TestClient, world: World) -> None:
    body = ranked(client, world, world.salt)
    half = next(o for o in body["options"] if o["scale_factor"] == 0.5)
    three_quarters = next(o for o in body["options"] if o["scale_factor"] == 0.75)

    assert half["origin"] == "use_less"
    assert half["replacements"] == []
    assert half["edit"] == {
        "type": "scale",
        "component_id": world.component(world.salt),
        "factor": 0.5,
    }
    # Half the salt takes 3,880 mg from 10,514.5 mg, leaving 6,634.5 mg in 990 g.
    assert half["goal_effect"]["after_per_100g"] == pytest.approx(670.15, abs=0.01)
    assert half["scores"]["flavor"] == 0.5
    assert three_quarters["scores"]["flavor"] == 0.75


def test_a_goal_to_raise_offers_using_more_and_not_less(
    client: TestClient, world: World, session: Session
) -> None:
    chicken = world.food("Chicken", protein=30.0)
    # 100 g of chicken holds 30 g and 100 g of rice holds 2.7 g, or 16.35 g per 100 g of the batch.
    dish = world.food("Chicken rice", kind=FoodKind.PREPARED_DISH, protein=16.35)
    make_recipe(session, dish, world.source, [(chicken, 100.0), (world.rice, 100.0)])
    component = session.scalar(
        select(RecipeComponent.id).where(RecipeComponent.component_food_id == chicken.id)
    )

    response = client.post(
        f"/v1/foods/{dish.id}/substitutions",
        json={"component_id": component, "goal": "more_protein"},
    )

    assert response.status_code == 200
    options = response.json()["options"]
    assert [(o["origin"], o["scale_factor"]) for o in options] == [("use_more", 1.5)]
    # Half as much again adds 50 g holding 15 g, so 47.7 g sit in 250 g.
    assert options[0]["goal_effect"]["after_per_100g"] == pytest.approx(19.08)


def test_an_option_going_the_wrong_way_is_not_offered(client: TestClient, world: World) -> None:
    higher = world.food("Very salty sauce", sodium=9000.0)
    world.swap(world.sauce, (higher, 1.0))
    assert "Very salty sauce" not in names_offered(ranked(client, world, world.sauce))


def test_reviewed_swaps_outrank_unreviewed_ones_whatever_the_numbers(
    client: TestClient, world: World
) -> None:
    reviewed = world.food("Reviewed sauce", sodium=4000.0)
    unreviewed = world.food("Unreviewed sauce", sodium=0.0)
    world.swap(world.sauce, (reviewed, 1.0), fit=1)
    world.role(world.sauce, "sauce")
    world.role(reviewed, "sauce")
    world.role(unreviewed, "sauce")

    body = ranked(client, world, world.sauce)
    names = names_offered(body)

    assert names.index("Reviewed sauce") < names.index("Unreviewed sauce")
    assert replacement(body, "Unreviewed sauce")["verification"] == "estimated"
    assert replacement(body, "Unreviewed sauce")["origin"] == "same_role"
    assert replacement(body, "Unreviewed sauce")["scores"]["culinary_fit"] is None


def test_same_role_means_the_same_role(client: TestClient, world: World) -> None:
    sauce_two = world.food("Other sauce", sodium=100.0)
    a_fat = world.food("A fat", sodium=0.0)
    world.role(world.sauce, "sauce")
    world.role(sauce_two, "sauce")
    world.role(a_fat, "cooking_fat")
    names = names_offered(ranked(client, world, world.sauce))
    assert "Other sauce" in names
    assert "A fat" not in names


def test_a_record_not_marked_as_offered_is_not_suggested(client: TestClient, world: World) -> None:
    other = world.food("Duplicate record", sodium=100.0)
    world.role(world.sauce, "sauce")
    world.role(other, "sauce", offered=False)
    assert "Duplicate record" not in names_offered(ranked(client, world, world.sauce))


def test_an_unreviewed_swap_tasting_nothing_alike_is_not_offered(
    client: TestClient, world: World
) -> None:
    sour = world.food("Sour sauce", sodium=0.0)
    unrated = world.food("Unrated sauce", sodium=0.0)
    world.role(world.sauce, "sauce")
    world.role(sour, "sauce")
    world.role(unrated, "sauce")
    world.sensory(world.sauce, salty=5)
    world.sensory(sour, sour=5)
    names = names_offered(ranked(client, world, world.sauce))
    assert "Sour sauce" not in names
    # Nobody has rated this one, which is a gap and not a reason to reject it.
    assert "Unrated sauce" in names


def test_an_unreviewed_swap_that_barely_helps_is_not_offered(
    client: TestClient, world: World
) -> None:
    # 50 g at 490 mg less per 100 g takes 24.5 mg from 1,051.45 mg per 100 g, just enough to count.
    # That earns 0.047 of nutrition credit and nothing else is known, so it scores far under 0.2.
    reviewed = world.food("Reviewed slight change", sodium=5000.0)
    unreviewed = world.food("Unreviewed slight change", sodium=5000.0)
    world.swap(world.sauce, (reviewed, 1.0), fit=None)
    world.role(world.sauce, "sauce")
    world.role(unreviewed, "sauce")
    names = names_offered(ranked(client, world, world.sauce))
    assert "Unreviewed slight change" not in names
    # Someone chose to list this one, so it stays and its low score speaks for it.
    assert "Reviewed slight change" in names


def test_a_reviewed_swap_tasting_different_is_kept_and_says_so(
    client: TestClient, world: World
) -> None:
    sour = world.food("Sour sauce", sodium=0.0)
    world.swap(world.sauce, (sour, 1.0))
    world.sensory(world.sauce, salty=5)
    world.sensory(sour, sour=5)
    option = replacement(ranked(client, world, world.sauce), "Sour sauce")
    assert {"code": "flavor_different", "nutrient_key": None} in option["reasons"]


def test_missing_sensory_data_lowers_completeness_and_says_so(
    client: TestClient, world: World
) -> None:
    rated = world.food("Rated", sodium=3000.0)
    unrated = world.food("Unrated", sodium=3000.0)
    world.swap(world.sauce, (rated, 1.0), fit=3)
    world.swap(world.sauce, (unrated, 1.0), fit=3)
    world.sensory(world.sauce, salty=5)
    world.sensory(rated, salty=5)

    body = ranked(client, world, world.sauce)

    with_data = replacement(body, "Rated")
    without = replacement(body, "Unrated")
    assert with_data["scores"]["flavor"] == 1.0
    assert without["scores"]["flavor"] is None
    assert without["scores"]["completeness"] < with_data["scores"]["completeness"]
    assert without["scores"]["total"] > 0
    assert {"code": "flavor_unknown", "nutrient_key": None} in without["reasons"]


def test_a_replacement_with_no_value_is_named_rather_than_guessed(
    client: TestClient, world: World
) -> None:
    mystery = world.food("Coconut aminos")
    world.swap(world.sauce, (mystery, 1.0))
    body = ranked(client, world, world.sauce)
    assert "Coconut aminos" not in names_offered(body)
    assert body["could_not_evaluate"] == ["Coconut aminos"]


def test_a_dish_with_no_value_for_the_goal_says_so_rather_than_ranking(
    client: TestClient, world: World
) -> None:
    make_nutrient(world.session, "fiber", "g")
    # Nothing here states fiber, and a recipe of unknowns has nothing to rebuild.
    body = ranked(client, world, world.salt, goal="more_fiber")
    assert body["unavailable_reason"] == "goal_unknown"
    assert body["options"] == []


def test_an_ingredient_with_no_weight_says_so(
    client: TestClient, world: World, session: Session
) -> None:
    pinch = world.food("Pepper", sodium=20.0)
    dish = world.food("Peppered dish", kind=FoodKind.PREPARED_DISH, sodium=100.0)
    make_recipe(session, dish, world.source, [(pinch, None), (world.rice, 100.0)])
    component = session.scalar(
        select(RecipeComponent.id).where(RecipeComponent.component_food_id == pinch.id)
    )
    response = client.post(
        f"/v1/foods/{dish.id}/substitutions",
        json={"component_id": component, "goal": "less_sodium"},
    )
    assert response.status_code == 200
    assert response.json()["unavailable_reason"] == "no_weight"
    assert response.json()["options"] == []


def test_a_swap_that_crosses_a_new_high_mark_says_so_and_scores_lower(
    client: TestClient, world: World, session: Session
) -> None:
    session.add(
        FoodPortion(
            food_id=world.dish.id,
            description="1 cup",
            gram_weight=200.0,
            is_household_measure=True,
            source_id=world.source.id,
        )
    )
    session.flush()
    fatty = world.food("Fatty sauce", sodium=1000.0, saturated_fat=50.0)
    plain = world.food("Plain sauce", sodium=1000.0, saturated_fat=0.0)
    world.swap(world.sauce, (fatty, 1.0), fit=3)
    world.swap(world.sauce, (plain, 1.0), fit=3)

    body = ranked(client, world, world.sauce)

    fat_option = replacement(body, "Fatty sauce")
    plain_option = replacement(body, "Plain sauce")
    # 50 g of fatty sauce holds 25 g of saturated fat, 2.5 g per 100 g, or 5 g in a 200 g cup: 25%.
    assert {"code": "mark_raised", "nutrient_key": "saturated_fat"} in fat_option["reasons"]
    assert fat_option["scores"]["nutrition"] < plain_option["scores"]["nutrition"]
    assert fat_option["scores"]["total"] < plain_option["scores"]["total"]


def test_a_swap_that_clears_the_mark_says_so(client: TestClient, world: World) -> None:
    """The sodium here is well over the 20% line per 100 g, and half the salt is not enough."""
    none = world.food("No-sodium seasoning", sodium=0.0)
    world.swap(world.salt, (none, 1.0))
    world.swap(world.sauce, (world.rice, 1.0))
    body = client.post(
        f"/v1/foods/{world.dish.id}/substitutions",
        json={
            "component_id": world.component(world.salt),
            "goal": "less_sodium",
            # With the shoyu also gone, only rice and this swap's zero remain.
            "edits": [{"type": "remove", "component_id": world.component(world.sauce)}],
        },
    ).json()
    option = replacement(body, "No-sodium seasoning")
    assert {"code": "mark_cleared", "nutrient_key": "sodium"} in option["reasons"]


def test_options_are_judged_against_the_dish_as_it_stands(client: TestClient, world: World) -> None:
    low = world.food("Shoyu, low sodium", sodium=3600.0)
    world.swap(world.sauce, (low, 1.0))
    alone = replacement(ranked(client, world, world.sauce), "Shoyu, low sodium")
    edited = replacement(
        ranked(
            client,
            world,
            world.sauce,
            edits=[{"type": "remove", "component_id": world.component(world.salt)}],
        ),
        "Shoyu, low sodium",
    )
    assert edited["goal_effect"]["before_per_100g"] < alone["goal_effect"]["before_per_100g"]
    # The salt's 7,760 mg left too, so 1,809.5 mg sit in 980 g.
    assert edited["goal_effect"]["after_per_100g"] == pytest.approx(184.64, abs=0.01)


def test_an_edit_on_the_same_ingredient_is_set_aside_to_rank_alternatives(
    client: TestClient, world: World
) -> None:
    low = world.food("Shoyu, low sodium", sodium=3600.0)
    world.swap(world.sauce, (low, 1.0))
    plain = replacement(ranked(client, world, world.sauce), "Shoyu, low sodium")
    after_removing = replacement(
        ranked(
            client,
            world,
            world.sauce,
            edits=[{"type": "remove", "component_id": world.component(world.sauce)}],
        ),
        "Shoyu, low sodium",
    )
    assert after_removing["goal_effect"] == plain["goal_effect"]


def test_a_swap_limited_to_a_cuisine_applies_only_to_that_cuisine(
    client: TestClient, world: World, session: Session
) -> None:
    low = world.food("Japanese sauce", sodium=3600.0)
    cuisine_id = session.scalar(select(Cuisine.id).limit(1))
    assert cuisine_id is not None
    key = session.scalar(select(Cuisine.key).where(Cuisine.id == cuisine_id))
    world.swap(world.sauce, (low, 1.0), cuisine=key)

    assert "Japanese sauce" not in names_offered(ranked(client, world, world.sauce))

    session.add(
        FoodCuisine(
            food_id=world.dish.id,
            cuisine_id=cuisine_id,
            source_id=world.source.id,
            verification=Verification.TYPICAL,
        )
    )
    session.flush()
    assert "Japanese sauce" in names_offered(ranked(client, world, world.sauce))


def test_a_swap_limited_to_a_role_applies_only_to_that_role(
    client: TestClient, world: World
) -> None:
    low = world.food("Role sauce", sodium=3600.0)
    world.swap(world.sauce, (low, 1.0), role="sauce")

    assert "Role sauce" not in names_offered(ranked(client, world, world.sauce))
    world.role(world.sauce, "sauce")
    assert "Role sauce" in names_offered(ranked(client, world, world.sauce))


@pytest.mark.parametrize("relation", [AllergenRelation.CONTAINS, AllergenRelation.MAY_CONTAIN])
def test_an_excluded_allergen_never_appears_in_a_reviewed_swap(
    client: TestClient, world: World, relation: AllergenRelation
) -> None:
    risky = world.food("Peanut-based sauce", sodium=100.0)
    fine = world.food("Other sauce", sodium=100.0)
    world.allergen(risky, "peanuts", relation)
    world.swap(world.sauce, (risky, 1.0))
    world.swap(world.sauce, (fine, 1.0))

    body = ranked(client, world, world.sauce, avoid_allergens=["peanuts"])

    assert names_offered(body) == ["Other sauce"]
    assert body["hidden_for_allergens"] == 1
    assert "Peanut-based" not in str(body)


def test_an_excluded_allergen_never_appears_as_one_part_of_a_replacement(
    client: TestClient, world: World
) -> None:
    risky = world.food("Sesame part", sodium=100.0)
    fine = world.food("Plain part", sodium=100.0)
    world.allergen(risky, "sesame")
    world.swap(world.sauce, (fine, 0.5), (risky, 0.5))

    body = ranked(client, world, world.sauce, avoid_allergens=["sesame"])

    assert "Plain part" not in names_offered(body)
    assert "Sesame part" not in names_offered(body)
    assert body["hidden_for_allergens"] == 1


def test_an_excluded_allergen_never_appears_among_same_role_foods(
    client: TestClient, world: World
) -> None:
    risky = world.food("Unreviewed risky sauce", sodium=100.0)
    world.allergen(risky, "soybeans")
    world.role(world.sauce, "sauce")
    world.role(risky, "sauce")
    body = ranked(client, world, world.sauce, avoid_allergens=["soybeans"])
    assert "Unreviewed risky sauce" not in names_offered(body)


def test_using_less_of_an_excluded_allergen_is_not_offered(
    client: TestClient, world: World
) -> None:
    """Half the allergen is still the allergen."""
    world.allergen(world.sauce, "wheat")
    body = ranked(client, world, world.sauce, avoid_allergens=["wheat"])
    assert body["options"] == []
    assert body["hidden_for_allergens"] == 2


def test_allergens_a_person_does_not_avoid_are_listed_on_the_option(
    client: TestClient, world: World
) -> None:
    risky = world.food("Soy sauce mix", sodium=100.0)
    world.allergen(risky, "soybeans")
    world.allergen(risky, "wheat", AllergenRelation.MAY_CONTAIN)
    world.swap(world.sauce, (risky, 1.0))
    option = replacement(ranked(client, world, world.sauce), "Soy sauce mix")
    assert {(a["key"], a["relation"]) for a in option["allergens"]} == {
        ("soybeans", "contains"),
        ("wheat", "may_contain"),
    }
    assert {a["name"] for a in option["allergens"]} == {"Soybeans", "Wheat"}


def test_contains_outranks_may_contain_across_sources(
    client: TestClient, world: World, session: Session
) -> None:
    both = world.food("Sauce with two findings", sodium=100.0)
    world.allergen(both, "milk", AllergenRelation.MAY_CONTAIN)
    derived = session.scalar(select(Source).where(Source.key == "nourisearch-derived-from-fdc"))
    assert derived is not None
    milk = session.scalar(select(Allergen.id).where(Allergen.key == "milk"))
    assert milk is not None
    session.add(
        FoodAllergen(
            food_id=both.id,
            allergen_id=milk,
            source_id=derived.id,
            relation=AllergenRelation.CONTAINS,
            verification=Verification.ESTIMATED,
        )
    )
    session.flush()
    world.swap(world.sauce, (both, 1.0))
    option = replacement(ranked(client, world, world.sauce), "Sauce with two findings")
    assert option["allergens"][0]["relation"] == "contains"


def test_no_response_ever_claims_a_food_is_free_of_an_allergen(
    client: TestClient, world: World, session: Session
) -> None:
    stated = world.food("Sauce stated free", sodium=100.0)
    world.allergen(stated, "milk", AllergenRelation.FREE_OF)
    world.swap(world.sauce, (stated, 1.0))
    option = replacement(ranked(client, world, world.sauce), "Sauce stated free")
    assert option["allergens"] == []
    assert "free_of" not in str(ranked(client, world, world.sauce))


@settings(
    max_examples=40, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None
)
@given(
    avoid=st.lists(st.sampled_from(ALLERGEN_KEYS), unique=True, max_size=4),
    food_allergens=st.lists(
        st.lists(st.sampled_from(ALLERGEN_KEYS), unique=True, max_size=3), min_size=6, max_size=6
    ),
    goal=st.sampled_from(["less_sodium", "closest_match", "more_protein"]),
    diet=st.sampled_from(["any", "vegetarian"]),
)
def test_no_combination_ever_offers_an_excluded_allergen(
    client: TestClient,
    world: World,
    session: Session,
    avoid: list[str],
    food_allergens: list[list[str]],
    goal: str,
    diet: str,
) -> None:
    savepoint = session.begin_nested()
    try:
        keys_by_name: dict[str, set[str]] = {}
        foods = []
        for index, allergens in enumerate(food_allergens):
            name = f"Candidate {index}"
            food = world.food(name, sodium=float(index * 100), protein=float(index * 3 + 10))
            for key in allergens:
                world.allergen(food, key)
            keys_by_name[name] = set(allergens)
            foods.append(food)
        world.role(world.sauce, "sauce")
        # Two reviewed swaps of one food each, one of two foods, and the rest by role.
        world.swap(world.sauce, (foods[0], 1.0))
        world.swap(world.sauce, (foods[1], 1.0))
        world.swap(world.sauce, (foods[2], 0.5), (foods[3], 0.5))
        world.role(foods[4], "sauce")
        world.role(foods[5], "sauce")
        sauce_allergens = {"wheat"}
        world.allergen(world.sauce, "wheat")

        body = ranked(client, world, world.sauce, goal=goal, avoid_allergens=avoid, diet=diet)

        for option in body["options"]:
            held = (
                set().union(*(keys_by_name[n] for n in option_foods(option)))
                if option["replacements"]
                else sauce_allergens
            )
            assert not held & set(avoid), (option, avoid)
            assert not {a["key"] for a in option["allergens"]} & set(avoid)
    finally:
        savepoint.rollback()


def test_an_unknown_allergen_is_refused_rather_than_silently_ignored(
    client: TestClient, world: World
) -> None:
    """Someone typing "peanut" must not believe they are protected."""
    response = client.post(
        f"/v1/foods/{world.dish.id}/substitutions",
        json={
            "component_id": world.component(world.sauce),
            "goal": "less_sodium",
            "avoid_allergens": ["peanut"],
        },
    )
    assert response.status_code == 422
    assert "peanut" in response.json()["message"]


def test_a_diet_filter_hides_what_does_not_fit(client: TestClient, world: World) -> None:
    meaty = world.food("Beef broth", sodium=100.0)
    milky = world.food("Milk sauce", sodium=100.0)
    plant = world.food("Plant sauce", sodium=100.0)
    world.diet(meaty, FoodClassificationKind.MEAT_OR_FISH, FoodClassificationKind.ANIMAL_DERIVED)
    world.diet(milky, FoodClassificationKind.ANIMAL_DERIVED)
    for food in (meaty, milky, plant):
        world.swap(world.sauce, (food, 1.0))

    assert set(names_offered(ranked(client, world, world.sauce))) == {
        "Beef broth",
        "Milk sauce",
        "Plant sauce",
    }

    vegetarian = ranked(client, world, world.sauce, diet="vegetarian")
    assert set(names_offered(vegetarian)) == {"Milk sauce", "Plant sauce"}
    assert vegetarian["hidden_for_diet"] == 1

    vegan = ranked(client, world, world.sauce, diet="vegan")
    assert set(names_offered(vegan)) == {"Plant sauce"}
    assert vegan["hidden_for_diet"] == 2


def test_closest_match_ranks_by_likeness_and_offers_no_scaling(
    client: TestClient, world: World
) -> None:
    close = world.food("Close sauce", sodium=9000.0)
    far = world.food("Far sauce", sodium=0.0)
    world.swap(world.sauce, (close, 1.0), fit=4)
    world.swap(world.sauce, (far, 1.0), fit=2)
    world.sensory(world.sauce, salty=5)
    world.sensory(close, salty=5)
    world.sensory(far, sour=5)

    body = ranked(client, world, world.sauce, goal="closest_match")

    assert names_offered(body) == ["Close sauce", "Far sauce"]
    assert body["nutrient_key"] is None
    first = body["options"][0]
    assert first["goal_effect"] is None
    assert first["scores"]["nutrition"] is None


def test_the_options_cite_their_sources(client: TestClient, world: World) -> None:
    low = world.food("Shoyu, low sodium", sodium=3600.0)
    world.swap(world.sauce, (low, 1.0))
    body = ranked(client, world, world.sauce)
    option = replacement(body, "Shoyu, low sodium")
    assert "nourisearch-editorial" in option["source_keys"]
    assert "test-usda" in option["source_keys"]
    described = {source["key"] for source in body["sources"]}
    assert set(option["source_keys"]) <= described


def test_the_serving_used_to_judge_marks_is_named(client: TestClient, world: World) -> None:
    assert ranked(client, world, world.sauce)["serving_label"] == "100 g"


def test_ranking_writes_nothing(client: TestClient, world: World, session: Session) -> None:
    low = world.food("Shoyu, low sodium", sodium=3600.0)
    world.swap(world.sauce, (low, 1.0))

    def counts() -> tuple[int | None, ...]:
        return tuple(
            session.scalar(select(func.count()).select_from(model))
            for model in (
                Food,
                RecipeComponent,
                SubstitutionOption,
                SubstitutionComponent,
                Nutrient,
            )
        )

    before = counts()
    ranked(client, world, world.sauce)
    assert counts() == before


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"component_id": 1},
        {"goal": "less_sodium"},
        {"component_id": 1, "goal": "more_vibes"},
        {"component_id": 1, "goal": "less_sodium", "diet": "carnivore"},
        {"component_id": 1, "goal": "less_sodium", "avoid_allergens": "milk"},
        {"component_id": 1, "goal": "less_sodium", "edits": [{"type": "explode"}]},
    ],
)
def test_malformed_requests_use_the_shared_error_shape(
    client: TestClient, world: World, body: dict[str, Any]
) -> None:
    response = client.post(f"/v1/foods/{world.dish.id}/substitutions", json=body)
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_request"


def test_an_ingredient_from_another_food_is_refused(client: TestClient, world: World) -> None:
    response = client.post(
        f"/v1/foods/{world.dish.id}/substitutions",
        json={"component_id": 999999, "goal": "less_sodium"},
    )
    assert response.status_code == 422
    assert "999999" in response.json()["message"]


def test_a_food_with_no_recipe_is_refused(client: TestClient, world: World) -> None:
    response = client.post(
        f"/v1/foods/{world.salt.id}/substitutions",
        json={"component_id": 1, "goal": "less_sodium"},
    )
    assert response.status_code == 422


def test_an_unknown_food_is_not_found(client: TestClient, world: World) -> None:
    response = client.post(
        "/v1/foods/999999/substitutions", json={"component_id": 1, "goal": "less_sodium"}
    )
    assert response.status_code == 404
