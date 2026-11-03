"""Traverses the knowledge model from one nutrient in one dish.

Answers: which ingredients supply this nutrient, which other dishes share them, which substitutions
would lower it, and which sources support each step.
"""

from dataclasses import dataclass

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.db.models import Food, Nutrient, Source
from app.domain.nutrition.composition import NutrientBreakdown, nutrient_breakdown
from app.repositories.composition import load_composition, load_facts

_SHARED_DISHES_SQL = text(
    """
    SELECT f.id, f.canonical_name, array_agg(DISTINCT cf.canonical_name) AS shared
    FROM recipe_component rc
    JOIN recipe r ON r.id = rc.recipe_id AND r.is_default
    JOIN food f ON f.id = r.dish_id
    JOIN food cf ON cf.id = rc.component_food_id
    WHERE rc.component_food_id = ANY(:ingredient_ids) AND r.dish_id <> :dish_id
    GROUP BY f.id, f.canonical_name
    ORDER BY count(DISTINCT rc.component_food_id) DESC, f.canonical_name
    LIMIT :limit
    """
)

_OPTIONS_SQL = text(
    """
    SELECT so.id, so.from_food_id, so.source_id, so.verification, so.notes,
           sc.to_food_id, sc.ratio_by_weight, f.canonical_name
    FROM substitution_option so
    JOIN substitution_component sc ON sc.option_id = so.id
    JOIN food f ON f.id = sc.to_food_id
    WHERE so.from_food_id = ANY(:ingredient_ids)
    ORDER BY so.id, sc.to_food_id
    """
)


@dataclass(frozen=True, slots=True)
class SharedDish:
    food_id: int
    name: str
    shared_ingredients: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LowerNutrientSubstitution:
    option_id: int
    from_food_id: int
    from_name: str
    replacement_names: tuple[str, ...]
    # Change to the whole recipe, in the nutrient's unit. Negative means less of the nutrient.
    recipe_amount_delta: float
    source_id: int
    verification: str
    notes: str | None


@dataclass(frozen=True, slots=True)
class NutrientTrace:
    dish_id: int
    dish_name: str
    nutrient_key: str
    nutrient_unit: str
    breakdown: NutrientBreakdown
    shared_dishes: tuple[SharedDish, ...]
    substitutions: tuple[LowerNutrientSubstitution, ...]
    sources: tuple[Source, ...]


class TraceTargetNotFound(LookupError):
    pass


def _lower_substitutions(
    session: Session,
    breakdown: NutrientBreakdown,
    nutrient_id: int,
) -> list[LowerNutrientSubstitution]:
    """Keeps options that are known to lower the nutrient. Unknown effects are left out."""
    quantified = {
        c.component.food_id: c
        for c in breakdown.contributions
        if c.amount is not None and c.component.weight_g is not None
    }
    if not quantified:
        return []

    options: dict[int, list[tuple[int, float, str, int, str, str | None, int]]] = {}
    params = {"ingredient_ids": list(quantified)}
    for row in session.execute(_OPTIONS_SQL, params):
        option_id, from_food, source_id, verification, notes, to_food, ratio, to_name = row
        options.setdefault(option_id, []).append(
            (to_food, float(ratio), to_name, source_id, verification, notes, from_food)
        )

    replacement_facts = load_facts(
        session,
        {part[0] for parts in options.values() for part in parts},
        [nutrient_id],
    )

    results = []
    for option_id, parts in options.items():
        from_food = parts[0][6]
        contribution = quantified[from_food]
        original_weight = contribution.component.weight_g
        original_amount = contribution.amount
        if original_weight is None or original_amount is None:
            continue

        new_amount = 0.0
        known = True
        for to_food, ratio, *_ in parts:
            fact = replacement_facts.get(to_food, {}).get(nutrient_id)
            if fact is None:
                known = False
                break
            new_amount += original_weight * ratio * fact.amount_per_100g / 100
        if not known or new_amount >= original_amount:
            continue

        results.append(
            LowerNutrientSubstitution(
                option_id=option_id,
                from_food_id=from_food,
                from_name=contribution.component.name,
                replacement_names=tuple(part[2] for part in parts),
                recipe_amount_delta=new_amount - original_amount,
                source_id=parts[0][3],
                verification=parts[0][4],
                notes=parts[0][5],
            )
        )
    results.sort(key=lambda s: s.recipe_amount_delta)
    return results


def trace_nutrient(
    session: Session, dish_id: int, nutrient_key: str, shared_limit: int = 10
) -> NutrientTrace:
    dish = session.get(Food, dish_id)
    nutrient = session.scalar(select(Nutrient).where(Nutrient.key == nutrient_key))
    if dish is None or nutrient is None:
        raise TraceTargetNotFound(f"Dish {dish_id} or nutrient {nutrient_key!r} does not exist.")

    published = load_facts(session, [dish_id], [nutrient.id]).get(dish_id, {}).get(nutrient.id)
    components = load_composition(session, dish_id, [nutrient.id])
    breakdown = nutrient_breakdown(
        components,
        nutrient.id,
        published.amount_per_100g if published and not published.estimated else None,
    )

    contributors = [
        c.component.food_id for c in breakdown.contributions if c.amount and c.amount > 0
    ]
    shared: list[SharedDish] = []
    if contributors:
        rows = session.execute(
            _SHARED_DISHES_SQL,
            {"ingredient_ids": contributors, "dish_id": dish_id, "limit": shared_limit},
        )
        shared = [SharedDish(r[0], r[1], tuple(r[2])) for r in rows]

    substitutions = _lower_substitutions(session, breakdown, nutrient.id)

    source_ids = {s for c in breakdown.contributions for s in c.source_ids}
    source_ids.update(s.source_id for s in substitutions)
    if published:
        source_ids.add(published.source_id)
    sources = session.scalars(select(Source).where(Source.id.in_(source_ids))).all()

    return NutrientTrace(
        dish_id=dish.id,
        dish_name=dish.canonical_name,
        nutrient_key=nutrient.key,
        nutrient_unit=nutrient.unit,
        breakdown=breakdown,
        shared_dishes=tuple(shared),
        substitutions=tuple(substitutions),
        sources=tuple(sources),
    )
