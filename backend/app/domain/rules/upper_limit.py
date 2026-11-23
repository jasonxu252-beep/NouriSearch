"""Flags a serving that alone holds more than the National Academies' adult upper limit for a day.

A Tolerable Upper Intake Level is the most a person can take each day, from all sources, with no
expected risk of harm. Only limits that count food are used. The Academies set some limits for
supplements or synthetic forms alone, such as those for magnesium, niacin, folate, and vitamin E,
and preformed vitamin A only. Food values cannot be compared with those, so they are not loaded.
"""

from app.domain.enums import ConclusionSeverity, NutrientStatus, Uncertainty
from app.domain.rules.engine import Conclusion, RuleRef, ServingFact, SupportingFact

RULE = RuleRef("nutrient.above_upper_limit", 1)


def _conclusion(
    fact: ServingFact,
    amount: float | None,
    code: str,
    severity: ConclusionSeverity,
    message_key: str,
) -> Conclusion:
    limit = fact.upper_limit
    assert limit is not None
    facts = [SupportingFact("serving", fact.serving_g, "g")]
    if fact.amount_per_100g is not None:
        facts.append(SupportingFact("amount_per_100g", fact.amount_per_100g, fact.unit))
    if amount is not None:
        facts.append(SupportingFact("amount_per_serving", amount, fact.unit))
    facts.append(SupportingFact("upper_limit", limit, fact.unit))
    sources = set(fact.value_source_keys)
    if fact.upper_limit_source_key:
        sources.add(fact.upper_limit_source_key)
    params: dict[str, float | str] = {
        "serving": fact.serving_label,
        "limit": limit,
        "unit": fact.unit,
    }
    if amount is not None:
        params["amount"] = amount
    return Conclusion(
        code=code,
        severity=severity,
        subject=fact.nutrient_key,
        message_key=message_key,
        message_params=params,
        supporting_facts=tuple(facts),
        rules_triggered=(RULE,),
        sources=tuple(sorted(sources)),
        uncertainty=(
            Uncertainty.VERIFIED if fact.status is NutrientStatus.KNOWN else Uncertainty.INFERRED
        ),
        missing=fact.missing,
    )


def above_upper_limit(fact: ServingFact) -> Conclusion | None:
    """Applies to any nutrient with a food-inclusive upper limit, whatever its direction."""
    if fact.upper_limit is None:
        return None

    if fact.status is NutrientStatus.UNKNOWN or fact.amount_per_serving is None:
        return _conclusion(
            fact,
            None,
            "nutrient.could_not_evaluate",
            ConclusionSeverity.UNDETERMINED,
            "conclusion.could_not_evaluate.no_value",
        )
    amount = fact.amount_per_serving
    is_lower_bound = fact.status is NutrientStatus.LOWER_BOUND
    if amount > fact.upper_limit:
        return _conclusion(
            fact,
            amount,
            "nutrient.above_upper_limit",
            ConclusionSeverity.HIGH,
            "conclusion.above_upper_limit" + (".lower_bound" if is_lower_bound else ""),
        )
    # A floor under the limit says nothing, since the true amount could be over it.
    if is_lower_bound:
        return _conclusion(
            fact,
            amount,
            "nutrient.could_not_evaluate",
            ConclusionSeverity.UNDETERMINED,
            "conclusion.could_not_evaluate.lower_bound_limit",
        )
    return _conclusion(
        fact,
        amount,
        "nutrient.not_above_upper_limit",
        ConclusionSeverity.NOT_FLAGGED,
        "conclusion.not_above_upper_limit",
    )
