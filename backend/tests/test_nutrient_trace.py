"""The knowledge model's acceptance test: tracing sodium through a dish, using real USDA values."""

import pytest
from sqlalchemy.orm import Session

from app.db.models import Food, Nutrient, Source
from app.domain.enums import FoodKind
from app.domain.nutrition.composition import ContributionStatus
from app.repositories.composition import load_composition, load_facts
from app.services.nutrient_trace import TraceTargetNotFound, trace_nutrient
from tests.factories import (
    make_food,
    make_nutrient,
    make_proxy,
    make_recipe,
    make_source,
    make_substitution,
)

pytestmark = pytest.mark.integration


def build_soy_beef_dish(session: Session) -> tuple[Food, Food, Food, Nutrient, Source]:
    """USDA sodium per 100 g: shoyu 5490, low-sodium shoyu 3600, salt 38800."""
    source = make_source(session)
    sodium = make_nutrient(session)
    shoyu = make_food(session, "Soy sauce, shoyu", source, values={sodium: 5490.0})
    low_sodium = make_food(session, "Soy sauce, shoyu, low sodium", source, values={sodium: 3600.0})
    beef = make_food(session, "Beef, cooked", source, values={sodium: 67.0})
    dish = make_food(session, "Beef with soy-based sauce", source, kind=FoodKind.PREPARED_DISH)
    make_recipe(session, dish, source, [(beef, 400.0), (shoyu, 40.0)])
    return dish, shoyu, low_sodium, sodium, source


def test_trace_ranks_contributors_with_amounts_and_shares(session: Session) -> None:
    dish, _, _, _, _ = build_soy_beef_dish(session)
    trace = trace_nutrient(session, dish.id, "sodium")

    assert trace.dish_name == "Beef with soy-based sauce"
    assert trace.nutrient_unit == "mg"
    first, second = trace.breakdown.contributions
    assert first.component.name == "Soy sauce, shoyu"
    assert first.amount == pytest.approx(2196)
    assert first.share == pytest.approx(2196 / 2464)
    assert second.component.name == "Beef, cooked"
    assert second.amount == pytest.approx(268)


def test_trace_finds_other_dishes_sharing_the_contributors(session: Session) -> None:
    dish, shoyu, _, _, source = build_soy_beef_dish(session)
    other = make_food(session, "Shrimp with lobster sauce", source, kind=FoodKind.PREPARED_DISH)
    make_recipe(session, other, source, [(shoyu, 10.0)])
    unrelated = make_food(session, "Fruit salad", source, kind=FoodKind.PREPARED_DISH)
    make_recipe(session, unrelated, source, [(make_food(session, "Apple", source), 100.0)])

    trace = trace_nutrient(session, dish.id, "sodium")

    assert [d.name for d in trace.shared_dishes] == ["Shrimp with lobster sauce"]
    assert trace.shared_dishes[0].shared_ingredients == ("Soy sauce, shoyu",)


def test_trace_finds_substitutions_that_lower_the_nutrient(session: Session) -> None:
    dish, shoyu, low_sodium, _, source = build_soy_beef_dish(session)
    make_substitution(session, shoyu, [(low_sodium, 1.0)], source)

    trace = trace_nutrient(session, dish.id, "sodium")

    assert len(trace.substitutions) == 1
    substitution = trace.substitutions[0]
    assert substitution.from_name == "Soy sauce, shoyu"
    assert substitution.replacement_names == ("Soy sauce, shoyu, low sodium",)
    # 40 g at 3600 mg per 100 g, instead of 40 g at 5490 mg per 100 g.
    assert substitution.recipe_amount_delta == pytest.approx(1440 - 2196)


def test_substitutions_that_raise_the_nutrient_are_excluded(session: Session) -> None:
    dish, shoyu, _, sodium, source = build_soy_beef_dish(session)
    salt = make_food(session, "Salt, table", source, values={sodium: 38800.0})
    make_substitution(session, shoyu, [(salt, 1.0)], source)
    assert trace_nutrient(session, dish.id, "sodium").substitutions == ()


def test_substitutions_with_an_unknown_effect_are_excluded(session: Session) -> None:
    dish, shoyu, _, _, source = build_soy_beef_dish(session)
    no_data = make_food(session, "House tamari", source)
    make_substitution(session, shoyu, [(no_data, 1.0)], source)
    assert trace_nutrient(session, dish.id, "sodium").substitutions == ()


def test_one_ingredient_can_be_replaced_by_several(session: Session) -> None:
    dish, shoyu, low_sodium, sodium, source = build_soy_beef_dish(session)
    water = make_food(session, "Water", source, values={sodium: 4.0})
    make_substitution(session, shoyu, [(low_sodium, 0.5), (water, 0.5)], source)

    substitution = trace_nutrient(session, dish.id, "sodium").substitutions[0]

    assert set(substitution.replacement_names) == {"Soy sauce, shoyu, low sodium", "Water"}
    assert substitution.recipe_amount_delta == pytest.approx(720 + 0.8 - 2196)


def test_trace_returns_the_sources_behind_each_step(session: Session) -> None:
    dish, shoyu, low_sodium, sodium, source = build_soy_beef_dish(session)
    editorial = make_source(session, "test-editorial", priority=90)
    make_substitution(session, shoyu, [(low_sodium, 1.0)], editorial)

    trace = trace_nutrient(session, dish.id, "sodium")

    assert {s.key for s in trace.sources} == {source.key, editorial.key}
    assert sodium.key == trace.nutrient_key


def test_missing_ingredient_data_stays_unknown_through_the_database(session: Session) -> None:
    source = make_source(session)
    sodium = make_nutrient(session)
    salt = make_food(session, "Salt, table", source, values={sodium: 38800.0})
    paste = make_food(session, "Doubanjiang", source)
    dish = make_food(session, "Mapo tofu", source, kind=FoodKind.PREPARED_DISH)
    make_recipe(session, dish, source, [(salt, 1.0), (paste, 20.0)])

    breakdown = trace_nutrient(session, dish.id, "sodium").breakdown

    assert breakdown.is_lower_bound is True
    assert breakdown.missing_names == ("Doubanjiang",)
    assert breakdown.known_total == pytest.approx(388)


def test_proxy_values_fill_gaps_and_are_marked_as_estimates(session: Session) -> None:
    source = make_source(session)
    sodium = make_nutrient(session)
    protein = make_nutrient(session, "protein", "g")
    mackerel = make_food(
        session, "Fish, mackerel, salted", source, values={sodium: 4450.0, protein: 18.5}
    )
    salted_fish = make_food(session, "Chinese-style salted fish", source, values={protein: 20.0})
    make_proxy(session, salted_fish, mackerel, source)

    facts = load_facts(session, [salted_fish.id])[salted_fish.id]

    assert facts[sodium.id].amount_per_100g == 4450.0
    assert facts[sodium.id].estimated is True
    # The food's own value wins over its proxy.
    assert facts[protein.id].amount_per_100g == 20.0
    assert facts[protein.id].estimated is False


def test_estimated_dish_values_are_not_treated_as_published(session: Session) -> None:
    source = make_source(session)
    sodium = make_nutrient(session)
    mackerel = make_food(session, "Fish, mackerel, salted", source, values={sodium: 4450.0})
    dish = make_food(session, "Salted fish fried rice", source, kind=FoodKind.PREPARED_DISH)
    make_proxy(session, dish, mackerel, source)
    make_recipe(session, dish, source, [(mackerel, 10.0)])

    breakdown = trace_nutrient(session, dish.id, "sodium").breakdown

    assert breakdown.published_per_100g is None


def test_most_trusted_source_wins_when_two_give_a_value(session: Session) -> None:
    usda = make_source(session, "test-usda", priority=20)
    label = make_source(session, "test-label", priority=50)
    sodium = make_nutrient(session)
    food = make_food(session, "Miso", usda, values={sodium: 3728.0})
    from app.db.models import FoodNutrient
    from app.domain.enums import ValueKind

    session.add(
        FoodNutrient(
            food_id=food.id,
            nutrient_id=sodium.id,
            source_id=label.id,
            amount_per_100g=3000.0,
            value_kind=ValueKind.LABEL,
        )
    )
    session.flush()

    fact = load_facts(session, [food.id])[food.id][sodium.id]

    assert fact.amount_per_100g == 3728.0
    assert fact.source_id == usda.id


def test_nested_recipes_load_as_a_tree(session: Session) -> None:
    source = make_source(session)
    sodium = make_nutrient(session)
    salt = make_food(session, "Salt, table", source, values={sodium: 38800.0})
    spinach_raw = make_food(session, "Spinach, raw", source, values={sodium: 79.0})
    cooked = make_food(session, "Spinach, cooked, as ingredient", source)
    make_recipe(session, cooked, source, [(spinach_raw, 99.0), (salt, 1.0)])
    dish = make_food(session, "Bibimbap", source, kind=FoodKind.PREPARED_DISH)
    make_recipe(session, dish, source, [(cooked, 270.0)])

    components = load_composition(session, dish.id, [sodium.id])

    assert [c.name for c in components] == ["Spinach, cooked, as ingredient"]
    assert {c.name for c in components[0].children} == {"Spinach, raw", "Salt, table"}
    breakdown = trace_nutrient(session, dish.id, "sodium").breakdown
    assert breakdown.contributions[0].status is ContributionStatus.CALCULATED
    # 270 g of a recipe holding 78.2 mg + 388 mg per 100 g.
    assert breakdown.contributions[0].amount == pytest.approx((78.21 + 388) * 2.7)


def test_a_sub_recipe_reached_along_two_paths_counts_once(session: Session) -> None:
    source = make_source(session)
    sodium = make_nutrient(session)
    salt = make_food(session, "Salt, table", source, values={sodium: 38800.0})
    stock = make_food(session, "Stock base", source)
    make_recipe(session, stock, source, [(salt, 10.0)])
    sauce = make_food(session, "Sauce", source)
    make_recipe(session, sauce, source, [(stock, 100.0)])
    dish = make_food(session, "Stew", source, kind=FoodKind.PREPARED_DISH)
    make_recipe(session, dish, source, [(sauce, 50.0), (sauce, 50.0)])

    components = load_composition(session, dish.id, [sodium.id])

    assert len(components) == 2
    for component in components:
        assert [child.name for child in component.children] == ["Stock base"]
        assert [leaf.name for leaf in component.children[0].children] == ["Salt, table"]


def test_a_traced_dish_accounts_for_its_moisture_change(session: Session) -> None:
    source = make_source(session)
    sodium = make_nutrient(session)
    salt = make_food(session, "Salt, table", source, values={sodium: 38800.0})
    dish = make_food(session, "Reduced broth", source, kind=FoodKind.PREPARED_DISH)
    make_recipe(session, dish, source, [(salt, 1.0)], moisture_change_pct=-50.0)

    breakdown = trace_nutrient(session, dish.id, "sodium").breakdown

    assert breakdown.calculated_per_100g == pytest.approx(77600)


def test_cycles_in_bad_data_terminate(session: Session) -> None:
    source = make_source(session)
    make_nutrient(session)
    first = make_food(session, "Sauce A", source)
    second = make_food(session, "Sauce B", source)
    make_recipe(session, first, source, [(second, 10.0)])
    make_recipe(session, second, source, [(first, 10.0)])

    breakdown = trace_nutrient(session, first.id, "sodium").breakdown

    assert breakdown.known_total == 0
    assert breakdown.is_lower_bound is True


def test_unknown_targets_raise_a_clear_error(session: Session) -> None:
    source = make_source(session)
    food = make_food(session, "Salt, table", source)
    make_nutrient(session)
    with pytest.raises(TraceTargetNotFound):
        trace_nutrient(session, food.id, "not_a_nutrient")
    with pytest.raises(TraceTargetNotFound):
        trace_nutrient(session, 999_999, "sodium")
