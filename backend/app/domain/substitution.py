"""Scoring ingredient swaps by goal. Pure: no database, no network.

The score is made of parts a person can check, and every part is returned with the result. A part
with no data is left out and lowers a completeness score, so a missing flavor profile is never read
as a bad one, and a food nobody has rated cannot outrank one that is rated just as well.
"""

from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum


class Goal(StrEnum):
    LESS_SODIUM = "less_sodium"
    LESS_SATURATED_FAT = "less_saturated_fat"
    LESS_SUGAR = "less_sugar"
    FEWER_CALORIES = "fewer_calories"
    MORE_PROTEIN = "more_protein"
    MORE_FIBER = "more_fiber"
    # No nutrient to move: the nearest stand-in, for someone avoiding what an ingredient contains.
    CLOSEST_MATCH = "closest_match"


class Diet(StrEnum):
    ANY = "any"
    VEGETARIAN = "vegetarian"
    VEGAN = "vegan"


@dataclass(frozen=True, slots=True)
class ScoreWeights:
    nutrition: float
    flavor: float
    texture: float
    culinary_fit: float
    preference: float = 0.1


@dataclass(frozen=True, slots=True)
class GoalSpec:
    # Null for a goal with no nutrient to move.
    nutrient_key: str | None
    # -1 when lower is the aim and 1 when higher is.
    direction: int
    weights: ScoreWeights


# Nutrition leads for every nutrient goal, because moving that value is the point of asking. Taste
# weighs most where a swap changes a dish's main flavor, as with sugar.
GOALS: Mapping[Goal, GoalSpec] = {
    Goal.LESS_SODIUM: GoalSpec("sodium", -1, ScoreWeights(0.5, 0.2, 0.1, 0.2)),
    Goal.LESS_SATURATED_FAT: GoalSpec("saturated_fat", -1, ScoreWeights(0.5, 0.2, 0.1, 0.2)),
    Goal.LESS_SUGAR: GoalSpec("total_sugars", -1, ScoreWeights(0.5, 0.25, 0.05, 0.2)),
    Goal.FEWER_CALORIES: GoalSpec("energy", -1, ScoreWeights(0.5, 0.2, 0.1, 0.2)),
    Goal.MORE_PROTEIN: GoalSpec("protein", 1, ScoreWeights(0.6, 0.1, 0.1, 0.2)),
    Goal.MORE_FIBER: GoalSpec("fiber", 1, ScoreWeights(0.6, 0.1, 0.1, 0.2)),
    Goal.CLOSEST_MATCH: GoalSpec(None, 0, ScoreWeights(0.0, 0.5, 0.2, 0.3)),
}

# Moving a dish's value by half earns full credit, so a swap that halves the sodium scores 1.
FULL_CREDIT_CHANGE = 0.5
# Smaller moves are not offered: under 2% of the dish's value, or half a percent of the Daily Value
# in a serving, nobody would notice the difference.
MIN_CHANGE_SHARE = 0.02
MIN_PERCENT_DAILY_VALUE = 0.5
# A rated food beats an equally good unrated one by this much at most.
INCOMPLETE_PENALTY = 0.2
# A swap nobody has reviewed must taste at least this much like the original to be offered.
MIN_UNREVIEWED_FLAVOR = 0.25
# An unreviewed idea scoring below this is noise, like garlic to raise a dish's protein. A reviewed
# swap has already been judged worth listing, so it stays.
MIN_UNREVIEWED_SCORE = 0.2
# A swap that crosses into a new high Daily Value mark keeps this share of its nutrition credit, and
# one that clears a mark gains the bonus.
NEW_MARK_KEEPS = 0.5
CLEARED_MARK_BONUS = 0.2

# Soft and liquid ingredients have no texture worth comparing.
TEXTURE_ROLES = frozenset(
    {
        "primary_protein",
        "cured_meat",
        "vegetable",
        "cooked_grain",
        "noodle",
        "bread",
        "flatbread",
        "root_starch",
        "garnish",
    }
)

SCALE_LESS = (0.5, 0.75)
SCALE_MORE = (1.5,)


def is_allowed_by_diet(diet: Diet, classifications: Collection[str]) -> bool:
    """Diet facts only rule foods out. A food in the swap list has been assessed for them."""
    if diet is Diet.VEGAN:
        return not {"meat_or_fish", "animal_derived"} & set(classifications)
    if diet is Diet.VEGETARIAN:
        return "meat_or_fish" not in classifications
    return True


def is_allowed_by_allergens(avoid: Collection[str], found: Collection[str]) -> bool:
    """Anything found counts, "may contain" included. A person avoiding it decides on less."""
    return not set(avoid) & set(found)


def sensory_similarity(a: Mapping[str, float], b: Mapping[str, float]) -> float | None:
    """How alike two profiles are, from 0 to 1, or None if either has not been assessed.

    Intensities run from 2 to 5, with 1 meaning an attribute is absent, so 1 is subtracted to give a
    real zero. The score is the summed overlap over the summed maximum, so two foods sharing no
    attribute score 0 and identical foods score 1.
    """
    if not a or not b:
        return None
    overlap = 0.0
    largest = 0.0
    for attribute in a.keys() | b.keys():
        left = max(a.get(attribute, 1.0) - 1.0, 0.0)
        right = max(b.get(attribute, 1.0) - 1.0, 0.0)
        overlap += min(left, right)
        largest += max(left, right)
    return overlap / largest if largest else 1.0


def blended_profile(
    parts: Iterable[tuple[Mapping[str, float], float]],
) -> Mapping[str, float] | None:
    """A mix's profile: each attribute's strength above absent, averaged by the mix's weights.

    Any part with no profile leaves the whole blend unassessed, since the rest cannot speak for it.
    """
    items = list(parts)
    total = sum(ratio for _, ratio in items)
    if not items or total <= 0 or any(not profile for profile, _ in items):
        return None
    blended: dict[str, float] = {}
    for profile, ratio in items:
        for attribute, intensity in profile.items():
            blended[attribute] = blended.get(attribute, 0.0) + (intensity - 1.0) * ratio / total
    return {attribute: value + 1.0 for attribute, value in blended.items()}


def scaled_closeness(factor: float) -> float:
    """Using half as much keeps half of an ingredient's effect, and so does using twice as much."""
    return min(factor, 1 / factor)


def culinary_fit_score(fit: int | None) -> float | None:
    """A reviewer's 1 to 5 as a 0 to 1 score."""
    return (fit - 1) / 4 if fit is not None else None


def goal_change(spec: GoalSpec, before: float, after: float) -> float:
    """The share of the dish's value that moved the right way. Negative means the wrong way."""
    if before <= 0:
        # From nothing, a rise is progress of unknown size and a fall is impossible.
        return 1.0 if spec.direction > 0 and after > before else 0.0
    return spec.direction * (after - before) / before


def moves_enough(
    change: float,
    before: float,
    after: float,
    serving_g: float | None,
    daily_value: float | None,
) -> bool:
    if change < MIN_CHANGE_SHARE:
        return False
    if serving_g is None or not daily_value:
        return True
    percent = abs(after - before) * serving_g / 100 / daily_value * 100
    return percent >= MIN_PERCENT_DAILY_VALUE


def nutrition_score(change: float, marks_cleared: int, marks_raised: int) -> float:
    """Full credit at half the dish's value, then adjusted for how the rules judge the result."""
    score = min(max(change, 0.0) / FULL_CREDIT_CHANGE, 1.0)
    if marks_raised:
        score *= NEW_MARK_KEEPS
    if marks_cleared:
        score += CLEARED_MARK_BONUS
    return min(score, 1.0)


@dataclass(frozen=True, slots=True)
class ScoreParts:
    nutrition: float | None
    flavor: float | None
    texture: float | None
    culinary_fit: float | None
    # Filled in once the account milestone stores preferences.
    preference: float | None
    total: float
    # The share of the applicable weight that had data behind it.
    completeness: float


def combine_score(
    weights: ScoreWeights,
    nutrition: float | None,
    flavor: float | None,
    texture: float | None,
    culinary_fit: float | None,
    preference: float | None = None,
    texture_applies: bool = True,
) -> ScoreParts:
    """Weighs what is known and scales the result by how much was known.

    Preference counts only when someone has stated one, so nobody is marked down for not having an
    account. Texture counts only for ingredients where it matters.
    """
    applicable: list[tuple[float, float | None]] = [
        (weights.nutrition, nutrition),
        (weights.flavor, flavor),
        (weights.culinary_fit, culinary_fit),
    ]
    if texture_applies:
        applicable.append((weights.texture, texture))
    if preference is not None:
        applicable.append((weights.preference, preference))

    applicable_weight = sum(weight for weight, _ in applicable)
    known = [(weight, value) for weight, value in applicable if value is not None]
    known_weight = sum(weight for weight, _ in known)
    if known_weight <= 0:
        return ScoreParts(nutrition, flavor, texture, culinary_fit, preference, 0.0, 0.0)

    mean = sum(weight * value for weight, value in known) / known_weight
    completeness = known_weight / applicable_weight
    return ScoreParts(
        nutrition,
        flavor,
        texture,
        culinary_fit,
        preference,
        total=mean * (1 - INCOMPLETE_PENALTY * (1 - completeness)),
        completeness=completeness,
    )
