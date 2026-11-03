"""Flags a nutrient to limit when one serving reaches the FDA's "high" line."""

from app.domain.enums import ConclusionSeverity, NutrientDirection, NutrientStatus, Uncertainty
from app.domain.rules.engine import Conclusion, RuleRef, ServingFact, SupportingFact, Threshold

RULE = RuleRef("nutrient.high_percent_daily_value", 1)

# The FDA treats 20% of the Daily Value or more per serving as high.
HIGH_PERCENT_DAILY_VALUE = Threshold(20.0, "fda-percent-dv-guide")


def _sources(fact: ServingFact) -> tuple[str, ...]:
    keys = {HIGH_PERCENT_DAILY_VALUE.source_key, *fact.value_source_keys}
    if fact.daily_value_source_key:
        keys.add(fact.daily_value_source_key)
    return tuple(sorted(keys))


def _supporting_facts(fact: ServingFact, percent: float | None) -> tuple[SupportingFact, ...]:
    facts = [SupportingFact("serving", fact.serving_g, "g")]
    if fact.amount_per_100g is not None:
        facts.append(SupportingFact("amount_per_100g", fact.amount_per_100g, fact.unit))
    if fact.daily_value is not None:
        facts.append(SupportingFact("daily_value", fact.daily_value, fact.unit))
    if percent is not None:
        facts.append(SupportingFact("percent_daily_value", percent, "%"))
    facts.append(SupportingFact("threshold", HIGH_PERCENT_DAILY_VALUE.value, "%"))
    return tuple(facts)


def _conclusion(
    fact: ServingFact,
    percent: float | None,
    code: str,
    severity: ConclusionSeverity,
    message_key: str,
) -> Conclusion:
    params: dict[str, float | str] = {
        "serving": fact.serving_label,
        "threshold": HIGH_PERCENT_DAILY_VALUE.value,
    }
    if percent is not None:
        params["percent"] = percent
    return Conclusion(
        code=code,
        severity=severity,
        subject=fact.nutrient_key,
        message_key=message_key,
        message_params=params,
        supporting_facts=_supporting_facts(fact, percent),
        rules_triggered=(RULE,),
        sources=_sources(fact),
        # Only a value a source states outright counts as verified.
        uncertainty=(
            Uncertainty.VERIFIED if fact.status is NutrientStatus.KNOWN else Uncertainty.INFERRED
        ),
        missing=fact.missing,
    )


def high_percent_daily_value(fact: ServingFact) -> Conclusion | None:
    if fact.direction is not NutrientDirection.LIMIT:
        return None

    def could_not_evaluate(reason: str, percent: float | None = None) -> Conclusion:
        return _conclusion(
            fact,
            percent,
            "nutrient.could_not_evaluate",
            ConclusionSeverity.UNDETERMINED,
            f"conclusion.could_not_evaluate.{reason}",
        )

    if fact.status is NutrientStatus.UNKNOWN or fact.amount_per_100g is None:
        return could_not_evaluate("no_value")
    percent = fact.percent_daily_value
    if percent is None:
        return could_not_evaluate("no_daily_value")

    is_lower_bound = fact.status is NutrientStatus.LOWER_BOUND
    if percent >= HIGH_PERCENT_DAILY_VALUE.value:
        return _conclusion(
            fact,
            percent,
            "nutrient.high_percent_daily_value",
            ConclusionSeverity.HIGH,
            "conclusion.high_percent_daily_value" + (".lower_bound" if is_lower_bound else ""),
        )
    # A floor below the line says nothing, since the true value could be above it.
    if is_lower_bound:
        return could_not_evaluate("lower_bound", percent)
    return _conclusion(
        fact,
        percent,
        "nutrient.not_high_percent_daily_value",
        ConclusionSeverity.NOT_FLAGGED,
        "conclusion.not_high_percent_daily_value",
    )
