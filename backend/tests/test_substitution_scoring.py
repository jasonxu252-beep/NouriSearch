"""The ranking's arithmetic, checked against figures worked out by hand."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.domain.substitution import (
    FULL_CREDIT_CHANGE,
    GOALS,
    INCOMPLETE_PENALTY,
    Diet,
    Goal,
    ScoreWeights,
    blended_profile,
    combine_score,
    culinary_fit_score,
    goal_change,
    is_allowed_by_allergens,
    is_allowed_by_diet,
    moves_enough,
    nutrition_score,
    scaled_closeness,
    sensory_similarity,
)

WEIGHTS = ScoreWeights(nutrition=0.5, flavor=0.2, texture=0.1, culinary_fit=0.2)


def test_identical_profiles_are_a_perfect_match() -> None:
    assert sensory_similarity({"salty": 5}, {"salty": 5}) == 1.0


def test_profiles_sharing_nothing_score_zero() -> None:
    assert sensory_similarity({"salty": 5}, {"sweet": 5}) == 0.0


def test_soy_sauce_against_low_sodium_soy_sauce() -> None:
    # Above absent: soy sauce is salty 4 and savory 4, and low sodium is salty 3 and savory 4.
    # The overlap is 3 + 4 = 7, and the larger of each is 4 + 4 = 8.
    similarity = sensory_similarity({"salty": 5, "umami": 5}, {"salty": 4, "umami": 5})
    assert similarity == pytest.approx(0.875)


def test_salt_against_low_sodium_soy_sauce() -> None:
    # Salt is salty 4. Soy sauce is salty 3 and savory 4. The overlap is 3, and the larger of each
    # is 4 + 4 = 8.
    similarity = sensory_similarity({"salty": 5}, {"salty": 4, "umami": 5})
    assert similarity == pytest.approx(0.375)


@pytest.mark.parametrize(("a", "b"), [({}, {"salty": 5}), ({"salty": 5}, {}), ({}, {})])
def test_a_profile_nobody_assessed_gives_no_score_rather_than_zero(
    a: dict[str, float], b: dict[str, float]
) -> None:
    assert sensory_similarity(a, b) is None


PROFILES = st.dictionaries(
    st.sampled_from(["salty", "sweet", "sour", "umami"]), st.integers(2, 5), min_size=1
).map(lambda p: {k: float(v) for k, v in p.items()})


@given(PROFILES, PROFILES)
def test_similarity_is_symmetric_and_bounded(a: dict[str, float], b: dict[str, float]) -> None:
    forward = sensory_similarity(a, b)
    assert forward == sensory_similarity(b, a)
    assert forward is not None
    assert 0.0 <= forward <= 1.0


def test_half_salt_and_half_lemon_blends_their_profiles() -> None:
    # Salt is salty 4 above absent, and lemon is sour 4. Half of each is salty 2 and sour 2, or 3 on
    # the 1 to 5 scale. Against salt, the overlap is 2, and the larger of each is 4 + 2 = 6.
    blend = blended_profile([({"salty": 5.0}, 0.5), ({"sour": 5.0}, 0.5)])
    assert blend == {"salty": 3.0, "sour": 3.0}
    assert sensory_similarity({"salty": 5.0}, blend) == pytest.approx(1 / 3)


def test_a_blend_ignores_a_ratios_scale() -> None:
    assert blended_profile([({"salty": 4.0}, 5.0)]) == {"salty": 4.0}


def test_one_unassessed_part_leaves_the_whole_blend_unassessed() -> None:
    """The rest of a blend cannot speak for the part nobody has tasted."""
    assert blended_profile([({"salty": 5.0}, 0.5), ({}, 0.5)]) is None


def test_using_half_or_double_keeps_half_of_an_ingredients_effect() -> None:
    assert scaled_closeness(0.5) == 0.5
    assert scaled_closeness(2.0) == 0.5
    assert scaled_closeness(0.75) == 0.75


@pytest.mark.parametrize(("fit", "score"), [(1, 0.0), (3, 0.5), (5, 1.0), (None, None)])
def test_a_reviewers_fit_runs_from_zero_to_one(fit: int | None, score: float | None) -> None:
    assert culinary_fit_score(fit) == score


def test_a_goal_to_lower_counts_a_fall_as_progress() -> None:
    assert goal_change(GOALS[Goal.LESS_SODIUM], 435.0, 238.0) == pytest.approx(197 / 435)


def test_a_goal_to_lower_counts_a_rise_as_going_backward() -> None:
    assert goal_change(GOALS[Goal.LESS_SODIUM], 100.0, 120.0) == pytest.approx(-0.2)


def test_a_goal_to_raise_counts_a_rise_as_progress() -> None:
    assert goal_change(GOALS[Goal.MORE_PROTEIN], 10.0, 13.0) == pytest.approx(0.3)


def test_raising_from_nothing_is_progress_and_lowering_from_nothing_is_not() -> None:
    assert goal_change(GOALS[Goal.MORE_FIBER], 0.0, 1.0) == 1.0
    assert goal_change(GOALS[Goal.MORE_FIBER], 0.0, 0.0) == 0.0
    assert goal_change(GOALS[Goal.LESS_SODIUM], 0.0, 5.0) == 0.0


def test_a_swap_that_moves_the_wrong_way_is_not_offered() -> None:
    assert not moves_enough(-0.2, 100.0, 120.0, 100.0, 2300.0)


def test_a_change_too_small_to_notice_is_not_offered() -> None:
    assert not moves_enough(0.01, 100.0, 99.0, 100.0, 2300.0)


def test_a_change_that_barely_touches_the_daily_value_is_not_offered() -> None:
    # 10 g of protein rising 3% to 10.3 g moves 0.3 g in 100 g, 0.6% of a 50 g Daily Value. Per
    # 50 g of food, that is only 0.3%.
    assert moves_enough(0.03, 10.0, 10.3, 100.0, 50.0)
    assert not moves_enough(0.03, 10.0, 10.3, 50.0, 50.0)


def test_with_no_daily_value_the_share_of_the_dish_decides() -> None:
    assert moves_enough(0.03, 10.0, 9.7, 100.0, None)


def test_changing_half_the_dish_earns_full_nutrition_credit() -> None:
    assert FULL_CREDIT_CHANGE == 0.5
    assert nutrition_score(0.5, 0, 0) == 1.0
    assert nutrition_score(0.25, 0, 0) == 0.5
    assert nutrition_score(0.9, 0, 0) == 1.0


def test_a_new_high_mark_halves_the_credit_and_a_cleared_one_adds_to_it() -> None:
    assert nutrition_score(0.25, 0, 1) == 0.25
    assert nutrition_score(0.25, 1, 0) == pytest.approx(0.7)
    assert nutrition_score(0.5, 1, 0) == 1.0


def test_going_backward_earns_nothing_rather_than_a_negative_score() -> None:
    assert nutrition_score(-0.5, 0, 0) == 0.0


def test_a_fully_rated_candidate_is_a_plain_weighted_mean() -> None:
    # 0.5 * 0.8 + 0.2 * 0.5 + 0.1 * 1.0 + 0.2 * 0.75 = 0.75
    parts = combine_score(WEIGHTS, 0.8, 0.5, 1.0, 0.75)
    assert parts.total == pytest.approx(0.75)
    assert parts.completeness == 1.0


def test_missing_data_lowers_completeness_and_is_not_counted_as_zero() -> None:
    # Flavor and fit are missing, so 0.7 of the weight is known out of 1.0... here nutrition 0.5 and
    # texture 0.1 are known, 0.6 of 1.0. The known mean is 0.8, and the penalty is 0.2 * 0.4.
    parts = combine_score(WEIGHTS, 0.8, None, 0.8, None)
    assert parts.completeness == pytest.approx(0.6)
    assert parts.total == pytest.approx(0.8 * (1 - INCOMPLETE_PENALTY * 0.4))
    # Reading the same gaps as zero would give 0.5 * 0.8 + 0.1 * 0.8 = 0.48.
    assert parts.total > 0.48


def test_a_rated_candidate_beats_an_equally_good_unrated_one() -> None:
    rated = combine_score(WEIGHTS, 0.8, 0.8, 0.8, 0.8)
    unrated = combine_score(WEIGHTS, 0.8, None, None, None)
    assert rated.total > unrated.total
    assert unrated.total > 0


def test_a_much_better_unrated_candidate_can_still_beat_a_weak_rated_one() -> None:
    """Missing data is a mark down, not a disqualification."""
    assert (
        combine_score(WEIGHTS, 1.0, None, None, None).total
        > combine_score(WEIGHTS, 0.2, 0.2, 0.2, 0.2).total
    )


def test_every_part_of_the_score_is_returned() -> None:
    parts = combine_score(WEIGHTS, 0.8, 0.5, None, 0.75, preference=0.9)
    assert (parts.nutrition, parts.flavor, parts.texture, parts.culinary_fit, parts.preference) == (
        0.8,
        0.5,
        None,
        0.75,
        0.9,
    )


def test_texture_that_does_not_apply_costs_no_completeness() -> None:
    # Salt has no texture worth comparing, so only 0.9 of the weight is expected, and all is known.
    parts = combine_score(WEIGHTS, 0.8, 0.5, None, 0.75, texture_applies=False)
    assert parts.completeness == 1.0
    assert parts.total == pytest.approx((0.5 * 0.8 + 0.2 * 0.5 + 0.2 * 0.75) / 0.9)


def test_no_stated_preference_costs_nothing() -> None:
    """Nobody is marked down for not having an account."""
    assert combine_score(WEIGHTS, 0.8, 0.8, 0.8, 0.8).completeness == 1.0


def test_a_stated_preference_counts() -> None:
    liked = combine_score(WEIGHTS, 0.5, 0.5, 0.5, 0.5, preference=1.0)
    disliked = combine_score(WEIGHTS, 0.5, 0.5, 0.5, 0.5, preference=0.0)
    assert liked.total > 0.5 > disliked.total


def test_nothing_known_scores_zero_with_zero_completeness() -> None:
    parts = combine_score(WEIGHTS, None, None, None, None)
    assert parts.total == 0.0
    assert parts.completeness == 0.0


def test_closest_match_has_no_nutrition_part() -> None:
    weights = GOALS[Goal.CLOSEST_MATCH].weights
    assert GOALS[Goal.CLOSEST_MATCH].nutrient_key is None
    parts = combine_score(weights, None, 0.5, 0.5, 0.5)
    assert parts.total == pytest.approx(0.5)
    assert parts.completeness == 1.0


@pytest.mark.parametrize("goal", list(Goal))
def test_each_goals_required_weights_add_up(goal: Goal) -> None:
    weights = GOALS[goal].weights
    assert weights.nutrition + weights.flavor + weights.texture + weights.culinary_fit == (
        pytest.approx(1.0)
    )


@pytest.mark.parametrize(
    ("goal", "key", "direction"),
    [
        (Goal.LESS_SODIUM, "sodium", -1),
        (Goal.LESS_SATURATED_FAT, "saturated_fat", -1),
        (Goal.LESS_SUGAR, "total_sugars", -1),
        (Goal.FEWER_CALORIES, "energy", -1),
        (Goal.MORE_PROTEIN, "protein", 1),
        (Goal.MORE_FIBER, "fiber", 1),
    ],
)
def test_each_goal_moves_its_nutrient_the_right_way(goal: Goal, key: str, direction: int) -> None:
    assert GOALS[goal].nutrient_key == key
    assert GOALS[goal].direction == direction


def test_an_avoided_allergen_blocks_a_candidate() -> None:
    assert not is_allowed_by_allergens({"milk"}, {"milk", "eggs"})
    assert is_allowed_by_allergens({"milk"}, {"eggs"})
    assert is_allowed_by_allergens(set(), {"milk"})


@pytest.mark.parametrize(
    ("diet", "facts", "allowed"),
    [
        (Diet.ANY, {"meat_or_fish", "animal_derived"}, True),
        (Diet.VEGETARIAN, {"meat_or_fish", "animal_derived"}, False),
        (Diet.VEGETARIAN, {"animal_derived"}, True),
        (Diet.VEGETARIAN, set(), True),
        (Diet.VEGAN, {"meat_or_fish", "animal_derived"}, False),
        (Diet.VEGAN, {"animal_derived"}, False),
        (Diet.VEGAN, set(), True),
    ],
)
def test_diet_rules_foods_out(diet: Diet, facts: set[str], allowed: bool) -> None:
    assert is_allowed_by_diet(diet, facts) is allowed
