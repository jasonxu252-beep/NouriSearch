"""The rules engine: versioned, pure functions over typed facts, with no database access.

Milestone 4 needs one rule for the nutrient marks, and milestone 6 adds the rest. Every result says
which rule produced it, which facts support it, who it cites, and what could not be evaluated. A
rule facing missing data says it could not evaluate. It never says there is no concern.
"""

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass

from app.domain.enums import (
    ConclusionSeverity,
    NutrientDirection,
    NutrientMark,
    NutrientStatus,
    Uncertainty,
)


@dataclass(frozen=True, slots=True)
class RuleRef:
    id: str
    version: int


@dataclass(frozen=True, slots=True)
class Threshold:
    """A limit a rule applies. It cannot exist without the source that states it."""

    value: float
    source_key: str


@dataclass(frozen=True, slots=True)
class ServingFact:
    """What is known about one nutrient in one serving of one food."""

    nutrient_key: str
    direction: NutrientDirection
    status: NutrientStatus
    amount_per_100g: float | None
    unit: str
    daily_value: float | None
    daily_value_source_key: str | None
    value_source_keys: tuple[str, ...]
    missing: tuple[str, ...]
    serving_key: str
    serving_label: str
    serving_g: float

    @property
    def amount_per_serving(self) -> float | None:
        if self.amount_per_100g is None:
            return None
        return self.amount_per_100g * self.serving_g / 100

    @property
    def percent_daily_value(self) -> float | None:
        amount = self.amount_per_serving
        if amount is None or not self.daily_value:
            return None
        return amount / self.daily_value * 100


@dataclass(frozen=True, slots=True)
class SupportingFact:
    key: str
    value: float | str
    unit: str | None = None


@dataclass(frozen=True, slots=True)
class Conclusion:
    code: str
    severity: ConclusionSeverity
    subject: str
    # A translated template, never generated text.
    message_key: str
    message_params: Mapping[str, float | str]
    supporting_facts: tuple[SupportingFact, ...]
    rules_triggered: tuple[RuleRef, ...]
    sources: tuple[str, ...]
    uncertainty: Uncertainty
    missing: tuple[str, ...]


Rule = Callable[[ServingFact], Conclusion | None]


def evaluate(facts: Iterable[ServingFact], rules: Sequence[Rule]) -> tuple[Conclusion, ...]:
    """Runs every rule over every fact. A rule returns None where it does not apply."""
    conclusions = (rule(fact) for fact in facts for rule in rules)
    return tuple(conclusion for conclusion in conclusions if conclusion is not None)


def nutrient_mark(fact: ServingFact, conclusions: Iterable[Conclusion]) -> NutrientMark:
    """Reduces a nutrient's conclusions to its mark.

    Green requires a value that is complete and known, because a green mark on missing data would
    falsely reassure. A lower bound that crosses a limit still earns the exclamation mark.
    """
    severities = {c.severity for c in conclusions if c.subject == fact.nutrient_key}
    if ConclusionSeverity.HIGH in severities:
        return NutrientMark.EXCLAMATION
    if ConclusionSeverity.UNDETERMINED in severities:
        return NutrientMark.QUESTION
    if fact.status in (NutrientStatus.UNKNOWN, NutrientStatus.LOWER_BOUND):
        return NutrientMark.QUESTION
    return NutrientMark.GREEN
