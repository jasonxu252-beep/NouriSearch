"""The rules engine and its first rule, tested firing, not firing, and on missing data."""

import ast
from pathlib import Path

import pytest

from app.domain.enums import (
    ConclusionSeverity,
    NutrientDirection,
    NutrientMark,
    NutrientStatus,
    Uncertainty,
)
from app.domain.rules.engine import RuleRef, ServingFact, evaluate, nutrient_mark
from app.domain.rules.percent_daily_value import (
    HIGH_PERCENT_DAILY_VALUE,
    RULE,
    high_percent_daily_value,
)
from app.ingest.vocabulary import read_bundle


def sodium(
    amount_per_100g: float | None = 435.0,
    status: NutrientStatus = NutrientStatus.KNOWN,
    serving_g: float = 162.0,
    daily_value: float | None = 2300.0,
    direction: NutrientDirection = NutrientDirection.LIMIT,
    missing: tuple[str, ...] = (),
) -> ServingFact:
    """Bibimbap's published sodium and its "1 cup" serving, both real USDA figures."""
    return ServingFact(
        nutrient_key="sodium",
        direction=direction,
        status=status,
        amount_per_100g=amount_per_100g,
        unit="mg",
        daily_value=daily_value,
        daily_value_source_key="fda-daily-values" if daily_value else None,
        value_source_keys=("usda-fdc-fndds-2024-10",),
        missing=missing,
        serving_key="portion-0",
        serving_label="1 cup",
        serving_g=serving_g,
    )


def test_a_serving_at_or_above_the_line_fires() -> None:
    conclusion = high_percent_daily_value(sodium())
    assert conclusion is not None
    assert conclusion.severity is ConclusionSeverity.HIGH
    assert conclusion.code == "nutrient.high_percent_daily_value"
    assert conclusion.message_key == "conclusion.high_percent_daily_value"
    # 435 mg per 100 g in 162 g is 704.7 mg, which is 30.6% of 2,300 mg.
    assert conclusion.message_params["percent"] == pytest.approx(30.64, abs=0.01)
    assert conclusion.message_params["serving"] == "1 cup"


def test_exactly_twenty_percent_counts_as_high() -> None:
    """The FDA says 20% or more. 460 mg is exactly 20% of 2,300 mg."""
    conclusion = high_percent_daily_value(sodium(amount_per_100g=460.0, serving_g=100.0))
    assert conclusion is not None
    assert conclusion.severity is ConclusionSeverity.HIGH


def test_just_below_the_line_does_not_fire() -> None:
    conclusion = high_percent_daily_value(sodium(amount_per_100g=459.9, serving_g=100.0))
    assert conclusion is not None
    assert conclusion.severity is ConclusionSeverity.NOT_FLAGGED
    assert conclusion.code == "nutrient.not_high_percent_daily_value"


def test_the_serving_decides_the_result() -> None:
    """The plan's example. Bibimbap's sodium is high per cup, and not per 100 g."""
    per_cup = high_percent_daily_value(sodium(serving_g=162.0))
    per_100g = high_percent_daily_value(sodium(serving_g=100.0))
    assert per_cup is not None and per_cup.severity is ConclusionSeverity.HIGH
    assert per_100g is not None and per_100g.severity is ConclusionSeverity.NOT_FLAGGED


def test_nutrients_that_are_not_limited_do_not_fire() -> None:
    fact = sodium(direction=NutrientDirection.ENCOURAGE)
    assert high_percent_daily_value(fact) is None


@pytest.mark.parametrize(
    "fact",
    [
        sodium(amount_per_100g=None, status=NutrientStatus.UNKNOWN),
        sodium(amount_per_100g=None, status=NutrientStatus.UNKNOWN, missing=("Doubanjiang",)),
    ],
)
def test_a_missing_value_cannot_be_evaluated_and_is_never_no_concern(fact: ServingFact) -> None:
    conclusion = high_percent_daily_value(fact)
    assert conclusion is not None
    assert conclusion.severity is ConclusionSeverity.UNDETERMINED
    assert conclusion.code == "nutrient.could_not_evaluate"
    assert conclusion.message_key == "conclusion.could_not_evaluate.no_value"
    assert conclusion.missing == fact.missing


def test_a_missing_daily_value_cannot_be_evaluated() -> None:
    conclusion = high_percent_daily_value(sodium(daily_value=None))
    assert conclusion is not None
    assert conclusion.severity is ConclusionSeverity.UNDETERMINED
    assert conclusion.message_key == "conclusion.could_not_evaluate.no_daily_value"


def test_a_floor_already_above_the_line_still_fires() -> None:
    """The known part alone crosses the line, so the gaps can only make it higher."""
    conclusion = high_percent_daily_value(
        sodium(status=NutrientStatus.LOWER_BOUND, missing=("Doubanjiang",))
    )
    assert conclusion is not None
    assert conclusion.severity is ConclusionSeverity.HIGH
    assert conclusion.message_key == "conclusion.high_percent_daily_value.lower_bound"
    assert conclusion.uncertainty is Uncertainty.INFERRED
    assert conclusion.missing == ("Doubanjiang",)


def test_a_floor_below_the_line_decides_nothing() -> None:
    conclusion = high_percent_daily_value(
        sodium(amount_per_100g=10.0, status=NutrientStatus.LOWER_BOUND, missing=("Doubanjiang",))
    )
    assert conclusion is not None
    assert conclusion.severity is ConclusionSeverity.UNDETERMINED
    assert conclusion.message_key == "conclusion.could_not_evaluate.lower_bound"
    assert conclusion.missing == ("Doubanjiang",)


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (NutrientStatus.KNOWN, Uncertainty.VERIFIED),
        (NutrientStatus.CALCULATED, Uncertainty.INFERRED),
        (NutrientStatus.ESTIMATED, Uncertainty.INFERRED),
        (NutrientStatus.LOWER_BOUND, Uncertainty.INFERRED),
    ],
)
def test_only_a_stated_value_counts_as_verified(
    status: NutrientStatus, expected: Uncertainty
) -> None:
    conclusion = high_percent_daily_value(sodium(status=status))
    assert conclusion is not None
    assert conclusion.uncertainty is expected


def test_a_conclusion_carries_its_rule_facts_and_sources() -> None:
    conclusion = high_percent_daily_value(sodium())
    assert conclusion is not None
    assert conclusion.rules_triggered == (RuleRef("nutrient.high_percent_daily_value", 1),)
    assert conclusion.rules_triggered == (RULE,)
    assert set(conclusion.sources) == {
        "fda-percent-dv-guide",
        "fda-daily-values",
        "usda-fdc-fndds-2024-10",
    }
    facts = {fact.key: fact.value for fact in conclusion.supporting_facts}
    assert facts["amount_per_100g"] == 435.0
    assert facts["daily_value"] == 2300.0
    assert facts["serving"] == 162.0
    assert facts["threshold"] == 20.0


def test_the_threshold_cites_a_source_that_exists() -> None:
    assert HIGH_PERCENT_DAILY_VALUE.source_key in {s.key for s in read_bundle().sources}


def test_evaluate_runs_every_rule_over_every_fact_and_skips_what_does_not_apply() -> None:
    facts = [sodium(), sodium(direction=NutrientDirection.NEUTRAL)]
    assert len(evaluate(facts, [high_percent_daily_value])) == 1


@pytest.mark.parametrize(
    ("fact", "expected"),
    [
        (sodium(), NutrientMark.EXCLAMATION),
        (sodium(serving_g=100.0), NutrientMark.GREEN),
        (sodium(amount_per_100g=0.0), NutrientMark.GREEN),
        (sodium(amount_per_100g=None, status=NutrientStatus.UNKNOWN), NutrientMark.QUESTION),
        (sodium(status=NutrientStatus.LOWER_BOUND), NutrientMark.EXCLAMATION),
        (sodium(amount_per_100g=1.0, status=NutrientStatus.LOWER_BOUND), NutrientMark.QUESTION),
        (sodium(daily_value=None), NutrientMark.QUESTION),
        # No rule applies to these, so only the completeness of the value matters.
        (sodium(direction=NutrientDirection.NEUTRAL), NutrientMark.GREEN),
        (
            sodium(
                amount_per_100g=None,
                status=NutrientStatus.UNKNOWN,
                direction=NutrientDirection.NEUTRAL,
            ),
            NutrientMark.QUESTION,
        ),
        (
            sodium(status=NutrientStatus.LOWER_BOUND, direction=NutrientDirection.NEUTRAL),
            NutrientMark.QUESTION,
        ),
    ],
)
def test_nutrient_marks(fact: ServingFact, expected: NutrientMark) -> None:
    conclusions = evaluate([fact], [high_percent_daily_value])
    assert nutrient_mark(fact, conclusions) is expected


def test_a_green_mark_never_lands_on_missing_data() -> None:
    """The plan's reason for a third mark: green on missing data would falsely reassure."""
    for status in (NutrientStatus.UNKNOWN, NutrientStatus.LOWER_BOUND):
        for direction in NutrientDirection:
            for amount in (None, 0.0, 1.0):
                fact = sodium(amount_per_100g=amount, status=status, direction=direction)
                mark = nutrient_mark(fact, evaluate([fact], [high_percent_daily_value]))
                assert mark is not NutrientMark.GREEN, (status, direction, amount)


def test_a_percent_is_never_invented() -> None:
    assert sodium(amount_per_100g=None).percent_daily_value is None
    assert sodium(daily_value=None).percent_daily_value is None
    assert sodium(amount_per_100g=0.0).percent_daily_value == 0.0


FORBIDDEN_IN_DOMAIN = ("app.db", "app.api", "app.repositories", "app.services", "app.integrations")
FORBIDDEN_LIBRARIES = ("sqlalchemy", "fastapi", "httpx2", "psycopg", "starlette")


def test_the_domain_core_imports_no_infrastructure() -> None:
    """The plan's boundary: rules and calculations must be testable with nothing running."""
    root = Path(__file__).resolve().parents[1] / "app" / "domain"
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                assert not name.startswith(FORBIDDEN_IN_DOMAIN), f"{path}: {name}"
                assert not name.startswith(FORBIDDEN_LIBRARIES), f"{path}: {name}"
