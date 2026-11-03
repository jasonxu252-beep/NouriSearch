"""Editing a recipe and its published values, checked against figures worked out by hand."""

from collections.abc import Collection, Sequence

import pytest

from app.domain.enums import NutrientStatus, ValueKind
from app.domain.nutrition.composition import ComponentNode, NutrientFact, nutrient_breakdown
from app.domain.nutrition.simulation import (
    AddEdit,
    Edit,
    IngredientEdit,
    InvalidEdit,
    RemoveEdit,
    ReplaceEdit,
    ReplacementFood,
    ScaleEdit,
    SimulatedValue,
    apply_edits,
    published_after_edits,
)

SODIUM = 1
SOURCE = 7
OTHER_SOURCE = 8


def node(
    component_id: int,
    name: str,
    weight: float | None,
    sodium: float | None,
    estimated: bool = False,
) -> ComponentNode:
    facts = (
        {SODIUM: NutrientFact(sodium, SOURCE, ValueKind.ANALYTICAL, estimated=estimated)}
        if sodium is not None
        else {}
    )
    return ComponentNode(component_id, component_id, name, weight, facts)


def simulated(
    components: Sequence[ComponentNode],
    edits: Sequence[Edit],
    published: float,
    moisture: float = 0.0,
    is_water: bool = False,
    foods: Collection[ComponentNode] = (),
) -> SimulatedValue:
    before = nutrient_breakdown(components, SODIUM, published, moisture, is_water)
    final = apply_edits(components, edits, {f.food_id: f for f in foods}).components
    after = nutrient_breakdown(final, SODIUM, None, moisture, is_water)
    return published_after_edits(before, after, moisture, is_water)


def removing(*component_ids: int) -> list[Edit]:
    return [RemoveEdit(component_id) for component_id in component_ids]


def test_removing_salt_from_bibimbap() -> None:
    # USDA's recipe weighs 1765.8 g with 18 g of salt at 38,800 mg per 100 g, so salt holds
    # 6,984 mg. The published 435 mg per 100 g means the batch holds 7,681.2 mg, and 697.2 mg stay
    # in 1747.8 g.
    components = (
        node(1, "Salt, table", 18.0, 38800.0),
        node(2, "Everything else", 1747.8, 39.9),
    )
    result = simulated(components, removing(1), 435.0)

    assert result.status is NutrientStatus.CALCULATED
    assert result.amount_per_100g == pytest.approx(39.89, abs=0.01)
    assert result.gaps == ()
    assert result.approximate is False
    assert result.source_ids == frozenset({SOURCE})


def test_a_recipe_that_loses_water_converts_through_its_cooked_weight() -> None:
    # 1000 g raw cooks to 800 g at 500 mg per 100 g, so the batch holds 4,000 mg. Removing 100 g
    # holding 400 mg leaves 3,600 mg in 900 g raw, which cooks to 720 g.
    components = (node(1, "Soy sauce", 100.0, 400.0), node(2, "Rest", 900.0, 400.0))
    result = simulated(components, removing(1), 500.0, moisture=-20.0)
    assert result.amount_per_100g == pytest.approx(500.0)
    assert result.approximate is False


def test_water_also_follows_the_smaller_batch() -> None:
    # 1000 g raw at 80 g water per 100 g holds 800 g, and loses 200 g to reach 800 g cooked, which
    # is the published 75 g per 100 g. Removing 100 g holding 80 g of water leaves 720 g in 900 g
    # raw. That smaller batch loses 180 g, leaving 540 g of water in 720 g, or 75 g per 100 g.
    components = (node(1, "Broth", 100.0, 80.0), node(2, "Rest", 900.0, 80.0))
    result = simulated(components, removing(1), 75.0, moisture=-20.0, is_water=True)
    assert result.amount_per_100g == pytest.approx(75.0)


def test_several_ingredients_can_leave_at_once() -> None:
    components = (
        node(1, "Salt", 10.0, 1000.0),
        node(2, "Soy sauce", 10.0, 500.0),
        node(3, "Rice", 80.0, 0.0),
    )
    # The batch of 100 g holds 150 mg, and both sources leave.
    result = simulated(components, removing(1, 2), 150.0)
    assert result.amount_per_100g == pytest.approx(0.0)
    assert result.approximate is False


def test_removing_an_ingredient_with_no_value_leaves_the_result_unknown() -> None:
    """Nothing can be subtracted without knowing how much it held. A guess would mislead."""
    components = (node(1, "Doubanjiang", 20.0, None), node(2, "Tofu", 80.0, 7.0))
    result = simulated(components, removing(1), 500.0)
    assert result.status is NutrientStatus.UNKNOWN
    assert result.amount_per_100g is None
    assert result.gaps == ("Doubanjiang",)


def test_removing_an_ingredient_with_no_weight_leaves_the_result_unknown() -> None:
    components = (node(1, "Salt", None, 38800.0), node(2, "Tofu", 80.0, 7.0))
    result = simulated(components, removing(1), 500.0)
    assert result.status is NutrientStatus.UNKNOWN
    assert result.gaps == ("Salt",)


def test_any_unquantified_ingredient_blocks_a_number() -> None:
    """The plan: a recipe without weights gets qualitative comparisons only."""
    components = (node(1, "Salt", 10.0, 38800.0), node(2, "Tofu", None, 7.0))
    result = simulated(components, removing(1), 500.0)
    assert result.status is NutrientStatus.UNKNOWN
    assert result.amount_per_100g is None


def test_a_recipe_that_does_not_explain_the_published_value_is_approximate() -> None:
    # The recipe rebuilds to 200 mg against a published 100 mg, so it cannot be fully trusted.
    components = (node(1, "Salt", 10.0, 1000.0), node(2, "Rice", 90.0, 111.1))
    result = simulated(components, removing(1), 100.0)
    assert result.approximate is True


def test_subtracting_more_than_the_published_value_stops_at_zero_and_is_approximate() -> None:
    components = (node(1, "Salt", 10.0, 38800.0), node(2, "Rice", 90.0, 0.0))
    result = simulated(components, removing(1), 100.0)
    assert result.amount_per_100g == 0.0
    assert result.approximate is True


def test_an_excluded_ingredient_that_holds_none_only_changes_the_weight() -> None:
    components = (node(1, "Water", 50.0, 0.0), node(2, "Stock", 50.0, 200.0))
    result = simulated(components, removing(1), 100.0)
    assert result.amount_per_100g == pytest.approx(200.0)
    assert result.approximate is False


def test_it_needs_a_published_value() -> None:
    components = (node(1, "Salt", 10.0, 1000.0),)
    breakdown = nutrient_breakdown(components, SODIUM)
    with pytest.raises(ValueError, match="published value"):
        published_after_edits(breakdown, breakdown)


def test_using_half_the_salt_in_bibimbap() -> None:
    # The plan's example. The batch of 1765.8 g holds 7,681.2 mg at the published 435 mg per 100 g.
    # Half of the salt's 6,984 mg leaves, so 4,189.2 mg stay in 1756.8 g, or 238.46 mg per 100 g.
    components = (
        node(1, "Salt, table", 18.0, 38800.0),
        node(2, "Everything else", 1747.8, 39.9),
    )
    result = simulated(components, [ScaleEdit(1, 0.5)], 435.0)
    assert result.status is NutrientStatus.CALCULATED
    assert result.amount_per_100g == pytest.approx(238.46, abs=0.01)
    assert result.approximate is False


def test_using_more_of_an_ingredient_adds_what_it_holds() -> None:
    # 100 g at 100 mg per 100 g holds 100 mg. Doubling 10 g at 500 mg per 100 g adds 50 mg, so
    # 150 mg sit in 110 g.
    components = (node(1, "Sauce", 10.0, 500.0), node(2, "Rest", 90.0, 55.56))
    result = simulated(components, [ScaleEdit(1, 2.0)], 100.0)
    assert result.amount_per_100g == pytest.approx(136.36, abs=0.01)


def test_swapping_soy_sauce_for_low_sodium_soy_sauce() -> None:
    # Real USDA values: 5,490 and 3,600 mg per 100 g. A 1000 g batch at 300 mg per 100 g holds
    # 3,000 mg, and 50 g of sauce holds 2,745 mg. The swap holds 1,800 mg, so 945 mg fewer, which
    # leaves 2,055 mg in the same 1000 g.
    components = (node(1, "Soy sauce", 50.0, 5490.0), node(2, "Rest", 950.0, 26.84))
    low_sodium = node(70, "Soy sauce, low sodium", None, 3600.0)
    result = simulated(
        components,
        [ReplaceEdit(1, (ReplacementFood(70, 1.0),))],
        300.0,
        foods=[low_sodium],
    )
    assert result.status is NutrientStatus.CALCULATED
    assert result.amount_per_100g == pytest.approx(205.5, abs=0.01)
    assert result.approximate is False


def test_one_ingredient_can_become_several() -> None:
    # 20 g of salt at 38,800 mg per 100 g holds 7,760 mg of the batch's 8,000 mg. It becomes 10 g of
    # salt, holding 3,880 mg, and 10 g of lemon juice at 1 mg per 100 g, holding 0.1 mg. That leaves
    # 4,120.1 mg in the same 1000 g.
    components = (node(1, "Salt", 20.0, 38800.0), node(2, "Rest", 980.0, 24.49))
    salt = node(60, "Salt", None, 38800.0)
    lemon = node(61, "Lemon juice", None, 1.0)
    result = simulated(
        components,
        [ReplaceEdit(1, (ReplacementFood(60, 0.5), ReplacementFood(61, 0.5)))],
        800.0,
        foods=[salt, lemon],
    )
    assert result.amount_per_100g == pytest.approx(412.01, abs=0.01)


def test_a_replacement_of_a_different_weight_changes_the_batch_too() -> None:
    # 1000 g raw cooks to 800 g at 500 mg per 100 g, holding 4,000 mg. 100 g at 400 mg per 100 g
    # holds 400 mg, and its replacement of 200 g at 100 mg per 100 g holds 200 mg. So 3,800 mg sit
    # in 1100 g raw, which cooks to 880 g, or 431.82 mg per 100 g.
    components = (node(1, "Sauce", 100.0, 400.0), node(2, "Rest", 900.0, 400.0))
    lighter = node(70, "Lighter sauce", None, 100.0)
    result = simulated(
        components,
        [ReplaceEdit(1, (ReplacementFood(70, 2.0),))],
        500.0,
        moisture=-20.0,
        foods=[lighter],
    )
    assert result.amount_per_100g == pytest.approx(431.82, abs=0.01)


def test_adding_an_ingredient_adds_its_weight_and_what_it_holds() -> None:
    # 100 g at 100 mg per 100 g holds 100 mg. 25 g at 40 mg per 100 g adds 10 mg: 110 mg in 125 g.
    components = (node(1, "Rest", 100.0, 100.0),)
    tofu = node(70, "Tofu", None, 40.0)
    result = simulated(components, [AddEdit(70, 25.0)], 100.0, foods=[tofu])
    assert result.amount_per_100g == pytest.approx(88.0)


def test_water_follows_a_replacement_of_a_different_weight() -> None:
    # 1000 g raw at 80 g water per 100 g holds 800 g and loses 200 g in cooking, leaving 600 g in
    # 800 g. Swapping 100 g holding 80 g of water for 200 g holding 180 g adds 100 g, and the larger
    # batch loses 20 g more, so 680 g of water sit in 880 g cooked.
    components = (node(1, "Sauce", 100.0, 80.0), node(2, "Rest", 900.0, 80.0))
    thin = node(70, "Thin sauce", None, 90.0)
    result = simulated(
        components,
        [ReplaceEdit(1, (ReplacementFood(70, 2.0),))],
        75.0,
        moisture=-20.0,
        is_water=True,
        foods=[thin],
    )
    assert result.amount_per_100g == pytest.approx(77.27, abs=0.01)


def test_a_replacement_with_no_value_leaves_the_result_unknown_and_names_it() -> None:
    components = (node(1, "Soy sauce", 10.0, 5490.0), node(2, "Rest", 90.0, 0.0))
    mystery = node(70, "Coconut aminos", None, None)
    result = simulated(
        components, [ReplaceEdit(1, (ReplacementFood(70, 1.0),))], 549.0, foods=[mystery]
    )
    assert result.status is NutrientStatus.UNKNOWN
    assert result.amount_per_100g is None
    assert result.gaps == ("Coconut aminos",)


def test_an_added_ingredient_with_no_value_leaves_the_result_unknown() -> None:
    components = (node(1, "Rest", 100.0, 100.0),)
    mystery = node(70, "Coconut aminos", None, None)
    result = simulated(components, [AddEdit(70, 10.0)], 100.0, foods=[mystery])
    assert result.status is NutrientStatus.UNKNOWN
    assert result.gaps == ("Coconut aminos",)


def test_a_scaled_ingredient_with_no_value_leaves_the_result_unknown_and_is_named_once() -> None:
    components = (node(1, "Doubanjiang", 20.0, None), node(2, "Tofu", 80.0, 7.0))
    result = simulated(components, [ScaleEdit(1, 0.5)], 500.0)
    assert result.status is NutrientStatus.UNKNOWN
    assert result.gaps == ("Doubanjiang",)


def test_a_scaled_ingredient_with_no_weight_stays_unknown() -> None:
    components = (node(1, "Salt", None, 38800.0), node(2, "Tofu", 80.0, 7.0))
    result = simulated(components, [ScaleEdit(1, 0.5)], 500.0)
    assert result.status is NutrientStatus.UNKNOWN
    assert result.amount_per_100g is None


def test_a_gap_in_an_ingredient_the_edit_did_not_touch_does_not_block_the_change() -> None:
    """The published value already includes it, and the edit moves that value by a known amount."""
    components = (
        node(1, "Salt", 10.0, 1000.0),
        node(2, "Soy sauce", 10.0, 5000.0),
        node(3, "Mystery", 80.0, None),
    )
    result = simulated(components, removing(1), 700.0)
    assert result.status is NutrientStatus.CALCULATED
    # 700 mg in 100 g, less 100 mg, is 600 mg in 90 g. The partial rebuild cannot vouch for that.
    assert result.amount_per_100g == pytest.approx(666.67, abs=0.01)
    assert result.approximate is True


def test_a_replacement_borrowing_a_value_makes_the_result_approximate() -> None:
    components = (node(1, "Sauce", 10.0, 1000.0), node(2, "Rest", 90.0, 0.0))
    borrowed = node(70, "Similar sauce", None, 500.0, estimated=True)
    result = simulated(
        components, [ReplaceEdit(1, (ReplacementFood(70, 1.0),))], 100.0, foods=[borrowed]
    )
    assert result.amount_per_100g == pytest.approx(50.0)
    assert result.approximate is True


def test_the_sources_of_what_arrived_are_cited() -> None:
    components = (node(1, "Sauce", 10.0, 1000.0), node(2, "Rest", 90.0, 0.0))
    other = ComponentNode(
        70,
        70,
        "From another dataset",
        None,
        {SODIUM: NutrientFact(500.0, OTHER_SOURCE, ValueKind.ANALYTICAL)},
    )
    result = simulated(
        components, [ReplaceEdit(1, (ReplacementFood(70, 1.0),))], 100.0, foods=[other]
    )
    assert result.source_ids == frozenset({SOURCE, OTHER_SOURCE})


@pytest.mark.parametrize("rebuilt_share", [0.91, 1.09])
def test_a_rebuild_within_ten_percent_is_not_approximate(rebuilt_share: float) -> None:
    components = (
        node(1, "Salt", 10.0, 500.0),
        node(2, "Rice", 90.0, (rebuilt_share * 100 - 50) / 0.9),
    )
    result = simulated(components, removing(1), 100.0)
    assert result.approximate is False


def test_a_rebuild_past_ten_percent_is_approximate() -> None:
    components = (node(1, "Salt", 10.0, 500.0), node(2, "Rice", 90.0, 61.2 / 0.9))
    result = simulated(components, removing(1), 100.0)
    assert result.approximate is True


def test_edits_describe_each_row_of_the_result() -> None:
    components = (
        node(1, "Salt", 18.0, 38800.0),
        node(2, "Soy sauce", 10.0, 5490.0),
        node(3, "Oil", 20.0, 0.0),
        node(4, "Rice", 100.0, 1.0),
    )
    foods = {70: node(70, "Low sodium soy sauce", None, 3600.0), 71: node(71, "Egg", None, 142.0)}
    recipe = apply_edits(
        components,
        [
            ScaleEdit(1, 0.5),
            ReplaceEdit(2, (ReplacementFood(70, 1.5),)),
            RemoveEdit(3),
            AddEdit(71, 50.0),
        ],
        foods,
    )

    assert [(r.node.name, r.edit, r.node.weight_g, r.original_weight_g) for r in recipe.rows] == [
        ("Salt", IngredientEdit.SCALED, 9.0, 18.0),
        ("Soy sauce", IngredientEdit.REPLACED, 10.0, 10.0),
        ("Low sodium soy sauce", IngredientEdit.ADDED, 15.0, None),
        ("Oil", IngredientEdit.REMOVED, 20.0, 20.0),
        ("Rice", IngredientEdit.NONE, 100.0, 100.0),
        ("Egg", IngredientEdit.ADDED, 50.0, None),
    ]
    assert recipe.rows[2].replaces_component_id == 2
    assert recipe.rows[5].replaces_component_id is None
    assert recipe.is_modified is True
    assert [n.name for n in recipe.components] == [
        "Salt",
        "Low sodium soy sauce",
        "Rice",
        "Egg",
    ]
    new_ids = [recipe.rows[2].node.component_id, recipe.rows[5].node.component_id]
    assert new_ids == [-1, -2]


def test_no_edits_leave_the_recipe_as_it_was() -> None:
    components = (node(1, "Salt", 18.0, 38800.0),)
    recipe = apply_edits(components, [], {})
    assert recipe.is_modified is False
    assert recipe.components == components


@pytest.mark.parametrize(
    ("edits", "message"),
    [
        ([RemoveEdit(9)], "no ingredient 9"),
        ([ScaleEdit(9, 0.5)], "no ingredient 9"),
        ([ReplaceEdit(9, (ReplacementFood(70, 1.0),))], "no ingredient 9"),
        ([RemoveEdit(1), ScaleEdit(1, 0.5)], "edited twice"),
        ([ReplaceEdit(1, (ReplacementFood(99, 1.0),))], "No food 99"),
        ([AddEdit(99, 10.0)], "No food 99"),
        ([RemoveEdit(1), RemoveEdit(2)], "every ingredient"),
    ],
)
def test_edits_that_cannot_apply_are_refused(edits: list[Edit], message: str) -> None:
    components = (node(1, "Salt", 18.0, 38800.0), node(2, "Rice", 100.0, 1.0))
    foods = {70: node(70, "Replacement", None, 1.0)}
    with pytest.raises(InvalidEdit, match=message):
        apply_edits(components, edits, foods)


def test_a_recipe_can_lose_everything_it_had_if_something_arrives() -> None:
    components = (node(1, "Salt", 18.0, 38800.0),)
    foods = {70: node(70, "Replacement", None, 1.0)}
    recipe = apply_edits(components, [ReplaceEdit(1, (ReplacementFood(70, 1.0),))], foods)
    assert [n.name for n in recipe.components] == ["Replacement"]
