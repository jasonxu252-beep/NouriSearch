"""The upper-limit rule, tested firing, not firing, and on missing data."""

import pytest

from app.domain.enums import (
    ConclusionSeverity,
    NutrientDirection,
    NutrientMark,
    NutrientStatus,
    Uncertainty,
)
from app.domain.rules.engine import RuleRef, ServingFact, evaluate, nutrient_mark
from app.domain.rules.percent_daily_value import high_percent_daily_value
from app.domain.rules.upper_limit import RULE, above_upper_limit
from app.ingest.vocabulary import read_bundle
from app.services.food_composition import RULES

# The adult (19 to 50) limits printed in Appendix J of the National Academies' 2019 sodium and
# potassium report, typed again here on purpose. Copper and choline are in milligrams.
PRINTED_ADULT_LIMITS = {
    "calcium": 2500,
    "iron": 45,
    "zinc": 40,
    "selenium": 400,
    "copper": 10,
    "manganese": 11,
    "iodine": 1100,
    "vitamin_c": 2000,
    "vitamin_d": 100,
    "vitamin_b6": 100,
    "choline": 3500,
}
# Their limits cover supplements, synthetic forms, or preformed vitamin A only, so food cannot be
# compared with them.
NOT_FOR_FOOD = {"magnesium", "niacin", "folate", "vitamin_e", "vitamin_a"}


def iron(
    amount_per_100g: float | None = 7.0,
    status: NutrientStatus = NutrientStatus.KNOWN,
    serving_g: float = 100.0,
    upper_limit: float | None = 45.0,
) -> ServingFact:
    return ServingFact(
        nutrient_key="iron",
        direction=NutrientDirection.ENCOURAGE,
        status=status,
        amount_per_100g=amount_per_100g,
        unit="mg",
        daily_value=18.0,
        daily_value_source_key="fda-daily-values",
        value_source_keys=("usda-fdc-sr-legacy-2018-04",),
        missing=("Mystery",) if status is NutrientStatus.LOWER_BOUND else (),
        serving_key="portion-0",
        serving_label="1 cup",
        serving_g=serving_g,
        upper_limit=upper_limit,
        upper_limit_source_key="nasem-dri-summary" if upper_limit else None,
    )


def test_a_serving_over_the_days_limit_fires_and_shows_its_working() -> None:
    # 30 mg per 100 g in 200 g is 60 mg, over the 45 mg adult limit.
    conclusion = above_upper_limit(iron(30.0, serving_g=200.0))
    assert conclusion is not None
    assert conclusion.severity is ConclusionSeverity.HIGH
    assert conclusion.code == "nutrient.above_upper_limit"
    assert conclusion.message_key == "conclusion.above_upper_limit"
    assert conclusion.message_params == {
        "serving": "1 cup",
        "limit": 45.0,
        "unit": "mg",
        "amount": pytest.approx(60.0),
    }
    facts = {fact.key: fact.value for fact in conclusion.supporting_facts}
    assert facts == {
        "serving": 200.0,
        "amount_per_100g": 30.0,
        "amount_per_serving": pytest.approx(60.0),
        "upper_limit": 45.0,
    }
    assert conclusion.rules_triggered == (RuleRef("nutrient.above_upper_limit", 1),)
    assert conclusion.sources == ("nasem-dri-summary", "usda-fdc-sr-legacy-2018-04")
    assert conclusion.uncertainty is Uncertainty.VERIFIED


def test_exactly_the_limit_is_not_over_it() -> None:
    conclusion = above_upper_limit(iron(45.0))
    assert conclusion is not None
    assert conclusion.severity is ConclusionSeverity.NOT_FLAGGED


def test_a_serving_under_the_limit_says_so() -> None:
    conclusion = above_upper_limit(iron())
    assert conclusion is not None
    assert conclusion.severity is ConclusionSeverity.NOT_FLAGGED
    assert conclusion.message_key == "conclusion.not_above_upper_limit"


def test_an_unknown_value_could_not_be_evaluated_and_is_never_called_fine() -> None:
    conclusion = above_upper_limit(iron(None, status=NutrientStatus.UNKNOWN))
    assert conclusion is not None
    assert conclusion.severity is ConclusionSeverity.UNDETERMINED
    assert conclusion.message_key == "conclusion.could_not_evaluate.no_value"


def test_a_floor_already_over_the_limit_fires() -> None:
    conclusion = above_upper_limit(iron(50.0, status=NutrientStatus.LOWER_BOUND))
    assert conclusion is not None
    assert conclusion.severity is ConclusionSeverity.HIGH
    assert conclusion.message_key == "conclusion.above_upper_limit.lower_bound"
    assert conclusion.uncertainty is Uncertainty.INFERRED
    assert conclusion.missing == ("Mystery",)


def test_a_floor_under_the_limit_cannot_decide() -> None:
    conclusion = above_upper_limit(iron(10.0, status=NutrientStatus.LOWER_BOUND))
    assert conclusion is not None
    assert conclusion.severity is ConclusionSeverity.UNDETERMINED
    assert conclusion.message_key == "conclusion.could_not_evaluate.lower_bound_limit"


def test_a_nutrient_with_no_food_limit_is_not_this_rules_business() -> None:
    assert above_upper_limit(iron(upper_limit=None)) is None


def test_crossing_a_limit_marks_even_a_nutrient_people_want_more_of() -> None:
    """The plan's mark table: exclamation also covers a value above an established upper limit."""
    fact = iron(30.0, serving_g=200.0)
    assert nutrient_mark(fact, evaluate([fact], RULES)) is NutrientMark.EXCLAMATION
    under = iron()
    assert nutrient_mark(under, evaluate([under], RULES)) is NutrientMark.GREEN


def test_both_rules_run_and_each_stays_in_its_lane() -> None:
    assert (high_percent_daily_value, above_upper_limit) == RULES
    # Iron is not a nutrient to limit, so the Daily Value rule says nothing about it.
    assert [c.rules_triggered for c in evaluate([iron()], RULES)] == [(RULE,)]


def test_every_loaded_limit_matches_the_printed_table() -> None:
    guides = read_bundle().reference_intakes.general_guides
    limits = {g.nutrient: g.amount for g in guides if g.kind == "ul"}
    assert limits == PRINTED_ADULT_LIMITS
    assert not NOT_FOR_FOOD & set(limits)
    assert {g.source for g in guides if g.kind == "ul"} == {"nasem-dri-summary"}
