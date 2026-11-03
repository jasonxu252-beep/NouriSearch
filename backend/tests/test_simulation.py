"""Removing ingredients from a published value, checked against figures worked out by hand."""

import pytest

from app.domain.enums import NutrientStatus, ValueKind
from app.domain.nutrition.composition import ComponentNode, NutrientFact, nutrient_breakdown
from app.domain.nutrition.simulation import published_without

SODIUM = 1
SOURCE = 7


def node(component_id: int, name: str, weight: float | None, sodium: float | None) -> ComponentNode:
    facts = (
        {SODIUM: NutrientFact(sodium, SOURCE, ValueKind.ANALYTICAL)} if sodium is not None else {}
    )
    return ComponentNode(component_id, component_id, name, weight, facts)


def test_removing_salt_from_bibimbap() -> None:
    # USDA's recipe weighs 1765.8 g with 18 g of salt at 38,800 mg per 100 g, so salt holds
    # 6,984 mg. The published 435 mg per 100 g means the batch holds 7,681.2 mg, and 697.2 mg stay
    # in 1747.8 g.
    components = (
        node(1, "Salt, table", 18.0, 38800.0),
        node(2, "Everything else", 1747.8, 39.9),
    )
    result = published_without(nutrient_breakdown(components, SODIUM, 435.0), {1})

    assert result.status is NutrientStatus.CALCULATED
    assert result.amount_per_100g == pytest.approx(39.89, abs=0.01)
    assert result.gaps == ()
    assert result.approximate is False
    assert result.source_ids == frozenset({SOURCE})


def test_a_recipe_that_loses_water_converts_through_its_cooked_weight() -> None:
    # 1000 g raw cooks to 800 g at 500 mg per 100 g, so the batch holds 4,000 mg. Removing 100 g
    # holding 400 mg leaves 3,600 mg in 900 g raw, which cooks to 720 g.
    components = (node(1, "Soy sauce", 100.0, 400.0), node(2, "Rest", 900.0, 400.0))
    breakdown = nutrient_breakdown(components, SODIUM, 500.0, moisture_change_pct=-20.0)
    result = published_without(breakdown, {1}, moisture_change_pct=-20.0)
    assert result.amount_per_100g == pytest.approx(500.0)
    assert result.approximate is False


def test_water_also_follows_the_smaller_batch() -> None:
    # 1000 g raw at 80 g water per 100 g holds 800 g, and loses 200 g to reach 800 g cooked, which
    # is the published 75 g per 100 g. Removing 100 g holding 80 g of water leaves 720 g in 900 g
    # raw. That smaller batch loses 180 g, leaving 540 g of water in 720 g, or 75 g per 100 g.
    components = (node(1, "Broth", 100.0, 80.0), node(2, "Rest", 900.0, 80.0))
    breakdown = nutrient_breakdown(
        components, SODIUM, 75.0, moisture_change_pct=-20.0, is_water=True
    )
    result = published_without(breakdown, {1}, moisture_change_pct=-20.0, is_water=True)
    assert result.amount_per_100g == pytest.approx(75.0)


def test_several_ingredients_can_leave_at_once() -> None:
    components = (
        node(1, "Salt", 10.0, 1000.0),
        node(2, "Soy sauce", 10.0, 500.0),
        node(3, "Rice", 80.0, 0.0),
    )
    # The batch of 100 g holds 150 mg, and both sources leave.
    result = published_without(nutrient_breakdown(components, SODIUM, 150.0), {1, 2})
    assert result.amount_per_100g == pytest.approx(0.0)
    assert result.approximate is False


def test_removing_an_ingredient_with_no_value_leaves_the_result_unknown() -> None:
    """Nothing can be subtracted without knowing how much it held. A guess would mislead."""
    components = (node(1, "Doubanjiang", 20.0, None), node(2, "Tofu", 80.0, 7.0))
    result = published_without(nutrient_breakdown(components, SODIUM, 500.0), {1})
    assert result.status is NutrientStatus.UNKNOWN
    assert result.amount_per_100g is None
    assert result.gaps == ("Doubanjiang",)


def test_removing_an_ingredient_with_no_weight_leaves_the_result_unknown() -> None:
    components = (node(1, "Salt", None, 38800.0), node(2, "Tofu", 80.0, 7.0))
    result = published_without(nutrient_breakdown(components, SODIUM, 500.0), {1})
    assert result.status is NutrientStatus.UNKNOWN
    assert result.gaps == ("Salt",)


def test_any_unquantified_ingredient_blocks_a_number() -> None:
    """The plan: a recipe without weights gets qualitative comparisons only."""
    components = (node(1, "Salt", 10.0, 38800.0), node(2, "Tofu", None, 7.0))
    result = published_without(nutrient_breakdown(components, SODIUM, 500.0), {1})
    assert result.status is NutrientStatus.UNKNOWN
    assert result.amount_per_100g is None


def test_a_recipe_that_does_not_explain_the_published_value_is_approximate() -> None:
    # The recipe rebuilds to 200 mg against a published 100 mg, so it cannot be fully trusted.
    components = (node(1, "Salt", 10.0, 1000.0), node(2, "Rice", 90.0, 111.1))
    result = published_without(nutrient_breakdown(components, SODIUM, 100.0), {1})
    assert result.approximate is True


def test_subtracting_more_than_the_published_value_stops_at_zero_and_is_approximate() -> None:
    components = (node(1, "Salt", 10.0, 38800.0), node(2, "Rice", 90.0, 0.0))
    result = published_without(nutrient_breakdown(components, SODIUM, 100.0), {1})
    assert result.amount_per_100g == 0.0
    assert result.approximate is True


def test_an_excluded_ingredient_that_holds_none_only_changes_the_weight() -> None:
    components = (node(1, "Water", 50.0, 0.0), node(2, "Stock", 50.0, 200.0))
    result = published_without(nutrient_breakdown(components, SODIUM, 100.0), {1})
    assert result.amount_per_100g == pytest.approx(200.0)
    assert result.approximate is False


def test_it_needs_a_published_value() -> None:
    components = (node(1, "Salt", 10.0, 1000.0),)
    with pytest.raises(ValueError, match="published value"):
        published_without(nutrient_breakdown(components, SODIUM), {1})
