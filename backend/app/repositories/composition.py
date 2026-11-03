"""Reads dish composition and nutrient facts into plain domain objects."""

from collections import defaultdict
from collections.abc import Collection, Mapping
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.domain.enums import ValueKind
from app.domain.nutrition.composition import ComponentNode, NutrientFact

# Follows each dish's default recipe downward. The path check stops cycles in bad data from
# looping, and the depth limit bounds the work.
_TREE_SQL = text(
    """
    WITH RECURSIVE tree AS (
        SELECT rc.id AS component_id,
               NULL::integer AS parent_component_id,
               rc.component_food_id AS food_id,
               rc.weight_g,
               rc.position,
               1 AS depth,
               ARRAY[r.dish_id, rc.component_food_id] AS path
        FROM recipe r
        JOIN recipe_component rc ON rc.recipe_id = r.id
        WHERE r.dish_id = :dish_id AND r.is_default

        UNION ALL

        SELECT rc.id,
               t.component_id,
               rc.component_food_id,
               rc.weight_g,
               rc.position,
               t.depth + 1,
               t.path || rc.component_food_id
        FROM tree t
        JOIN recipe r ON r.dish_id = t.food_id AND r.is_default
        JOIN recipe_component rc ON rc.recipe_id = r.id
        WHERE t.depth < 8 AND NOT rc.component_food_id = ANY(t.path)
    )
    SELECT t.component_id, t.parent_component_id, t.food_id, f.canonical_name,
           t.weight_g, t.position
    FROM tree t
    JOIN food f ON f.id = t.food_id
    ORDER BY t.depth, t.position
    """
)

# One value per food and nutrient: the most trusted source wins.
_FACTS_SQL = text(
    """
    SELECT DISTINCT ON (fn.food_id, fn.nutrient_id)
           fn.food_id, fn.nutrient_id, fn.amount_per_100g, fn.source_id, fn.value_kind
    FROM food_nutrient fn
    JOIN source s ON s.id = fn.source_id
    WHERE fn.food_id = ANY(:food_ids)
      AND (CAST(:nutrient_ids AS integer[]) IS NULL OR fn.nutrient_id = ANY(:nutrient_ids))
    ORDER BY fn.food_id, fn.nutrient_id, s.priority, s.id
    """
)

_PROXIES_SQL = text(
    "SELECT food_id, proxy_food_id FROM nutrient_proxy WHERE food_id = ANY(:food_ids)"
)


@dataclass(frozen=True, slots=True)
class _Row:
    component_id: int
    parent_component_id: int | None
    food_id: int
    name: str
    weight_g: float | None
    position: int


def _read_direct_facts(
    session: Session, food_ids: list[int], nutrient_ids: list[int] | None
) -> dict[int, dict[int, NutrientFact]]:
    facts: dict[int, dict[int, NutrientFact]] = defaultdict(dict)
    rows = session.execute(_FACTS_SQL, {"food_ids": food_ids, "nutrient_ids": nutrient_ids})
    for food_id, nutrient_id, amount, source_id, value_kind in rows:
        facts[food_id][nutrient_id] = NutrientFact(float(amount), source_id, ValueKind(value_kind))
    return facts


def load_facts(
    session: Session,
    food_ids: Collection[int],
    nutrient_ids: Collection[int] | None = None,
) -> Mapping[int, Mapping[int, NutrientFact]]:
    """Returns the best value per food and nutrient.

    A food's own values always win. Values borrowed through a proxy only fill gaps, and they are
    marked as estimates so no caller can mistake them for measurements.
    """
    ids = list(food_ids)
    if not ids:
        return {}
    wanted = list(nutrient_ids) if nutrient_ids is not None else None
    facts = _read_direct_facts(session, ids, wanted)

    proxies = {row[0]: row[1] for row in session.execute(_PROXIES_SQL, {"food_ids": ids})}
    if proxies:
        borrowed = _read_direct_facts(session, list(set(proxies.values())), wanted)
        for food_id, proxy_id in proxies.items():
            for nutrient_id, fact in borrowed.get(proxy_id, {}).items():
                if nutrient_id not in facts[food_id]:
                    facts[food_id][nutrient_id] = NutrientFact(
                        fact.amount_per_100g, fact.source_id, fact.value_kind, estimated=True
                    )
    return facts


def load_composition(
    session: Session, dish_id: int, nutrient_ids: Collection[int] | None = None
) -> tuple[ComponentNode, ...]:
    """Loads a dish's default recipe as a tree, with nutrient facts on every node."""
    rows = [
        _Row(r[0], r[1], r[2], r[3], float(r[4]) if r[4] is not None else None, r[5])
        for r in session.execute(_TREE_SQL, {"dish_id": dish_id})
    ]
    facts = load_facts(session, {row.food_id for row in rows}, nutrient_ids)

    children_of: dict[int | None, list[_Row]] = defaultdict(list)
    for row in rows:
        children_of[row.parent_component_id].append(row)

    def build(row: _Row) -> ComponentNode:
        return ComponentNode(
            component_id=row.component_id,
            food_id=row.food_id,
            name=row.name,
            weight_g=row.weight_g,
            facts=facts.get(row.food_id, {}),
            children=tuple(build(child) for child in children_of.get(row.component_id, [])),
        )

    return tuple(build(row) for row in children_of.get(None, []))
