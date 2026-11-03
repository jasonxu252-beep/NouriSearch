"""Nutrient arithmetic, using USDA's published values for bibimbap and dal where realistic."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.domain.enums import ValueKind
from app.domain.nutrition.composition import (
    ComponentNode,
    ContributionStatus,
    NutrientFact,
    adjusted_per_100g,
    nutrient_breakdown,
)

SODIUM = 1
SOURCE = 7


def fact(amount: float, estimated: bool = False) -> NutrientFact:
    return NutrientFact(amount, SOURCE, ValueKind.ANALYTICAL, estimated)


def node(
    name: str,
    weight: float | None,
    sodium: float | None = None,
    children: tuple[ComponentNode, ...] = (),
    component_id: int = 0,
) -> ComponentNode:
    facts = {SODIUM: fact(sodium)} if sodium is not None else {}
    return ComponentNode(component_id, hash(name) % 1000, name, weight, facts, children)


BIBIMBAP = (
    node("Mung bean sprouts", 186.0, 10.0),
    node("Summer squash", 196.0, 6.0),
    node("Asian mushroom", 72.0, 117.0),
    node("Spinach", 270.0, 126.0),
    node("Red chili pepper", 30.0, 9.0),
    node("Salt, table", 18.0, 38800.0),
    node("Sesame oil", 28.0, 0.0),
    node("Cucumber", 301.0, 2.0),
    node("White rice", 316.0, 1.0),
    node("Beef top round", 226.8, 67.0),
    node("Carrots", 122.0, 69.0),
)


def test_bibimbap_rebuilds_close_to_the_published_usda_value() -> None:
    breakdown = nutrient_breakdown(BIBIMBAP, SODIUM, published_per_100g=435.0)
    assert breakdown.recipe_weight_g == pytest.approx(1765.8)
    assert breakdown.calculated_per_100g == pytest.approx(435, abs=1)
    assert breakdown.rebuild_error is not None
    assert breakdown.rebuild_error < 0.01
    assert breakdown.is_lower_bound is False


def test_contributors_are_ranked_and_salt_dominates_bibimbap_sodium() -> None:
    breakdown = nutrient_breakdown(BIBIMBAP, SODIUM)
    top = breakdown.contributions[0]
    assert top.component.name == "Salt, table"
    assert top.amount == pytest.approx(6984)
    assert top.share == pytest.approx(0.909, abs=0.001)
    assert sum(c.share or 0 for c in breakdown.contributions) == pytest.approx(1.0)


def test_a_known_zero_counts_as_known_and_not_as_missing() -> None:
    breakdown = nutrient_breakdown([node("Sesame oil", 28.0, 0.0)], SODIUM)
    assert breakdown.contributions[0].status is ContributionStatus.KNOWN
    assert breakdown.contributions[0].amount == 0
    assert breakdown.is_lower_bound is False


def test_missing_value_is_unknown_never_zero() -> None:
    breakdown = nutrient_breakdown(
        [node("Salt", 10.0, 38800.0), node("Mystery paste", 40.0)], SODIUM
    )
    missing = next(c for c in breakdown.contributions if c.component.name == "Mystery paste")
    assert missing.status is ContributionStatus.NO_DATA
    assert missing.amount is None
    assert breakdown.is_lower_bound is True
    assert breakdown.missing_names == ("Mystery paste",)
    # The total reports what is known, and the flag says it is a floor.
    assert breakdown.known_total == pytest.approx(3880)


def test_all_values_missing_gives_no_number_at_all() -> None:
    breakdown = nutrient_breakdown([node("A", 10.0), node("B", 20.0)], SODIUM)
    assert breakdown.calculated_per_100g is None
    assert breakdown.per_100g is None
    assert breakdown.is_lower_bound is True


def test_unquantified_ingredients_are_listed_and_block_a_per_100g_figure() -> None:
    breakdown = nutrient_breakdown([node("Salt", None, 38800.0), node("Rice", 100.0, 1.0)], SODIUM)
    assert breakdown.unquantified_names == ("Salt",)
    assert breakdown.recipe_weight_g is None
    assert breakdown.calculated_per_100g is None
    assert breakdown.is_lower_bound is True


def test_published_value_wins_for_display_and_rebuilt_value_is_the_fallback() -> None:
    components = [node("Lentils", 96.0, 2.0), node("Salt", 0.8, 38800.0), node("Ghee", 4.0, 2.0)]
    published = nutrient_breakdown(components, SODIUM, published_per_100g=309.0)
    assert published.per_100g == 309.0
    assert published.calculated_per_100g == pytest.approx(310, abs=1)
    assert nutrient_breakdown(components, SODIUM).per_100g == pytest.approx(310, abs=1)


def test_nested_recipe_supplies_a_value_when_the_ingredient_has_none() -> None:
    sauce = node(
        "Sauce",
        50.0,
        children=(node("Soy sauce", 20.0, 5490.0), node("Water", 80.0, 4.0)),
    )
    breakdown = nutrient_breakdown([sauce], SODIUM)
    contribution = breakdown.contributions[0]
    assert contribution.status is ContributionStatus.CALCULATED
    # Half of the 100 g sauce recipe: (1098 mg + 3.2 mg) / 2.
    assert contribution.amount == pytest.approx(550.6)


def test_an_ingredient_with_its_own_value_is_not_double_counted_through_its_recipe() -> None:
    spinach = node("Spinach", 100.0, 126.0, children=(node("Salt", 1.0, 38800.0),))
    breakdown = nutrient_breakdown([spinach], SODIUM)
    assert breakdown.contributions[0].status is ContributionStatus.KNOWN
    assert breakdown.contributions[0].amount == pytest.approx(126)


def test_nested_recipe_with_a_gap_is_a_partial_lower_bound() -> None:
    sauce = node(
        "Sauce",
        100.0,
        children=(node("Soy sauce", 50.0, 5490.0), node("House paste", 50.0)),
    )
    breakdown = nutrient_breakdown([sauce], SODIUM)
    assert breakdown.contributions[0].status is ContributionStatus.PARTIAL
    assert breakdown.is_lower_bound is True
    assert breakdown.missing_names == ("Sauce",)


def test_estimates_are_flagged_through_nesting() -> None:
    estimated = ComponentNode(1, 1, "Salted fish", 20.0, {SODIUM: fact(4450.0, estimated=True)})
    parent = ComponentNode(2, 2, "Fried rice mix", 100.0, {}, (estimated,))
    breakdown = nutrient_breakdown([parent], SODIUM)
    assert breakdown.contributions[0].estimated is True


def test_halving_the_salt_in_bibimbap_nearly_halves_its_sodium() -> None:
    adjusted = adjusted_per_100g(
        published_per_100g=435.0,
        original_weight_g=1765.8,
        new_weight_g=1756.8,
        amount_delta=-3492.0,
    )
    assert adjusted == pytest.approx(238.4, abs=0.1)


def test_cooking_concentrates_a_rebuilt_value() -> None:
    components = [node("Salt", 1.0, 38800.0), node("Water", 99.0, 4.0)]
    raw = nutrient_breakdown(components, SODIUM)
    # 391.96 mg in 100 g raw, then in the 80 g left after losing 20% of the weight as water.
    cooked = nutrient_breakdown(components, SODIUM, moisture_change_pct=-20.0)
    assert raw.calculated_per_100g == pytest.approx(391.96)
    assert cooked.calculated_per_100g == pytest.approx(489.95)


def test_gaining_water_dilutes_a_rebuilt_value() -> None:
    components = [node("Rice", 100.0, 10.0)]
    cooked = nutrient_breakdown(components, SODIUM, moisture_change_pct=25.0)
    assert cooked.calculated_per_100g == pytest.approx(8.0)


def test_moisture_changes_neither_an_ingredients_amount_nor_its_share() -> None:
    components = [node("Salt", 1.0, 38800.0), node("Water", 99.0, 4.0)]
    raw = nutrient_breakdown(components, SODIUM)
    cooked = nutrient_breakdown(components, SODIUM, moisture_change_pct=-20.0)
    assert cooked.known_total == raw.known_total
    assert [c.share for c in cooked.contributions] == [c.share for c in raw.contributions]


def test_water_itself_leaves_with_the_moisture_change() -> None:
    # 90 g of water in 100 g raw. Losing 20 g leaves 70 g of water in the 80 g that remain.
    components = [node("Broth", 100.0, 90.0)]
    cooked = nutrient_breakdown(components, SODIUM, moisture_change_pct=-20.0, is_water=True)
    assert cooked.calculated_per_100g == pytest.approx(87.5)


def test_water_cannot_be_lost_past_zero() -> None:
    components = [node("Rice", 100.0, 10.0)]
    cooked = nutrient_breakdown(components, SODIUM, moisture_change_pct=-20.0, is_water=True)
    assert cooked.calculated_per_100g == 0.0


def test_a_nested_recipe_uses_its_own_cooked_weight() -> None:
    sauce = ComponentNode(
        1,
        1,
        "Reduced sauce",
        50.0,
        {},
        (node("Soy sauce", 20.0, 5490.0), node("Water", 80.0, 4.0)),
        moisture_change_pct=-50.0,
    )
    breakdown = nutrient_breakdown([sauce], SODIUM)
    # The 100 g recipe holds 1101.2 mg and cooks down to 50 g, so 50 g of sauce holds all of it.
    assert breakdown.contributions[0].amount == pytest.approx(1101.2)


def test_an_ingredients_own_value_still_wins_over_its_cooked_recipe() -> None:
    sauce = ComponentNode(
        1,
        1,
        "Reduced sauce",
        50.0,
        {SODIUM: fact(1000.0)},
        (node("Soy sauce", 20.0, 5490.0),),
        moisture_change_pct=-50.0,
    )
    assert nutrient_breakdown([sauce], SODIUM).contributions[0].amount == pytest.approx(500.0)


def test_an_edit_converts_through_the_cooked_weight() -> None:
    # 1000 g raw cooks to 800 g at 500 mg per 100 g, so the batch holds 4000 mg. Taking out 400 mg
    # and 1 g of raw weight leaves 3600 mg in 799.2 g.
    adjusted = adjusted_per_100g(
        published_per_100g=500.0,
        original_weight_g=1000.0,
        new_weight_g=999.0,
        amount_delta=-400.0,
        moisture_change_pct=-20.0,
    )
    assert adjusted == pytest.approx(450.45, abs=0.01)


def test_an_edit_with_no_moisture_change_matches_the_plain_formula() -> None:
    assert adjusted_per_100g(500.0, 1000.0, 999.0, -400.0) == pytest.approx(
        (500.0 * 1000.0 / 100 - 400.0) / 999.0 * 100
    )


def test_adjustment_cannot_go_below_zero() -> None:
    assert adjusted_per_100g(10.0, 100.0, 100.0, -500.0) == 0.0


def test_adjustment_rejects_impossible_weights() -> None:
    with pytest.raises(ValueError, match="positive"):
        adjusted_per_100g(10.0, 0.0, 100.0, 0.0)


amounts = st.floats(min_value=0, max_value=50_000, allow_nan=False)
weights = st.floats(min_value=0.1, max_value=5_000, allow_nan=False)
ingredients = st.lists(st.tuples(weights, st.one_of(st.none(), amounts)), min_size=1, max_size=20)


@given(ingredients)
def test_total_equals_the_sum_of_known_contributions(
    items: list[tuple[float, float | None]],
) -> None:
    components = [node(f"item-{i}", w, a) for i, (w, a) in enumerate(items)]
    breakdown = nutrient_breakdown(components, SODIUM)
    expected = sum(w * a / 100 for w, a in items if a is not None)
    assert breakdown.known_total == pytest.approx(expected)


@given(ingredients)
def test_lower_bound_flag_is_set_exactly_when_something_is_missing(
    items: list[tuple[float, float | None]],
) -> None:
    components = [node(f"item-{i}", w, a) for i, (w, a) in enumerate(items)]
    breakdown = nutrient_breakdown(components, SODIUM)
    assert breakdown.is_lower_bound == any(a is None for _, a in items)


@given(ingredients)
def test_shares_never_exceed_one_and_order_is_descending(
    items: list[tuple[float, float | None]],
) -> None:
    components = [node(f"item-{i}", w, a) for i, (w, a) in enumerate(items)]
    breakdown = nutrient_breakdown(components, SODIUM)
    known = [c.amount for c in breakdown.contributions if c.amount is not None]
    assert known == sorted(known, reverse=True)
    for contribution in breakdown.contributions:
        if contribution.share is not None:
            assert 0 <= contribution.share <= 1 + 1e-9
