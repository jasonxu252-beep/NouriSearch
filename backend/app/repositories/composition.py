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
               rc.retention_code,
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
               rc.retention_code,
               t.depth + 1,
               t.path || rc.component_food_id
        FROM tree t
        JOIN recipe r ON r.dish_id = t.food_id AND r.is_default
        JOIN recipe_component rc ON rc.recipe_id = r.id
        WHERE t.depth < 8 AND NOT rc.component_food_id = ANY(t.path)
    )
    SELECT t.component_id, t.parent_component_id, t.food_id, f.canonical_name,
           t.weight_g, t.position, t.retention_code, own.moisture_change_pct
    FROM tree t
    JOIN food f ON f.id = t.food_id
    LEFT JOIN recipe own ON own.dish_id = t.food_id AND own.is_default
    ORDER BY t.depth, t.position
    """
)

# One value per food and nutrient: the most trusted source wins.
_FACTS_SQL = text(
    """
    SELECT DISTINCT ON (fn.food_id, fn.nutrient_id)
           fn.food_id, fn.nutrient_id, fn.amount_per_100g, fn.source_id, fn.value_kind,
           fn.derivation
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

_DEFAULT_RECIPE_SQL = text(
    "SELECT id, label, moisture_change_pct FROM recipe WHERE dish_id = :dish_id AND is_default"
)

_FOOD_NODES_SQL = text(
    """
    SELECT f.id, f.canonical_name, r.id, r.moisture_change_pct
    FROM food f
    LEFT JOIN recipe r ON r.dish_id = f.id AND r.is_default
    WHERE f.id = ANY(:food_ids)
    """
)


@dataclass(frozen=True, slots=True)
class DefaultRecipe:
    id: int
    label: str
    # Zero when the source does not state a change, which assumes no water gained or lost.
    moisture_change_pct: float


@dataclass(frozen=True, slots=True)
class _Row:
    component_id: int
    parent_component_id: int | None
    food_id: int
    name: str
    weight_g: float | None
    position: int
    retention_code: int | None
    moisture_change_pct: float


def _read_direct_facts(
    session: Session, food_ids: list[int], nutrient_ids: list[int] | None
) -> dict[int, dict[int, NutrientFact]]:
    facts: dict[int, dict[int, NutrientFact]] = defaultdict(dict)
    rows = session.execute(_FACTS_SQL, {"food_ids": food_ids, "nutrient_ids": nutrient_ids})
    for food_id, nutrient_id, amount, source_id, value_kind, derivation in rows:
        facts[food_id][nutrient_id] = NutrientFact(
            float(amount), source_id, ValueKind(value_kind), derivation=derivation
        )
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
                        fact.amount_per_100g,
                        fact.source_id,
                        fact.value_kind,
                        estimated=True,
                        derivation=fact.derivation,
                    )
    return facts


def load_default_recipe(session: Session, dish_id: int) -> DefaultRecipe | None:
    row = session.execute(_DEFAULT_RECIPE_SQL, {"dish_id": dish_id}).first()
    if row is None:
        return None
    return DefaultRecipe(row[0], row[1], float(row[2] or 0.0))


def load_composition(
    session: Session, dish_id: int, nutrient_ids: Collection[int] | None = None
) -> tuple[ComponentNode, ...]:
    """Loads a dish's default recipe as a tree, with nutrient facts on every node."""
    rows = [
        _Row(
            r[0],
            r[1],
            r[2],
            r[3],
            float(r[4]) if r[4] is not None else None,
            r[5],
            r[6],
            float(r[7] or 0.0),
        )
        for r in session.execute(_TREE_SQL, {"dish_id": dish_id})
    ]
    facts = load_facts(session, {row.food_id for row in rows}, nutrient_ids)

    # A sub-recipe reached along two paths returns its rows twice. They are one recipe.
    children_of: dict[int | None, list[_Row]] = defaultdict(list)
    seen: set[tuple[int | None, int]] = set()
    for row in rows:
        edge = (row.parent_component_id, row.component_id)
        if edge not in seen:
            seen.add(edge)
            children_of[row.parent_component_id].append(row)

    def build(row: _Row) -> ComponentNode:
        return ComponentNode(
            component_id=row.component_id,
            food_id=row.food_id,
            name=row.name,
            weight_g=row.weight_g,
            facts=facts.get(row.food_id, {}),
            children=tuple(build(child) for child in children_of.get(row.component_id, [])),
            moisture_change_pct=row.moisture_change_pct,
            retention_code=row.retention_code,
        )

    return tuple(build(row) for row in children_of.get(None, []))


def load_food_nodes(
    session: Session, food_ids: Collection[int], nutrient_ids: Collection[int] | None = None
) -> dict[int, ComponentNode]:
    """Loads foods an edit could bring into a recipe. Weight and ID belong to the edit that does."""
    ids = list(food_ids)
    if not ids:
        return {}
    facts = load_facts(session, ids, nutrient_ids)
    nodes: dict[int, ComponentNode] = {}
    for food_id, name, recipe_id, moisture in session.execute(_FOOD_NODES_SQL, {"food_ids": ids}):
        nodes[food_id] = ComponentNode(
            component_id=0,
            food_id=food_id,
            name=name,
            weight_g=None,
            facts=facts.get(food_id, {}),
            children=load_composition(session, food_id, nutrient_ids) if recipe_id else (),
            moisture_change_pct=float(moisture or 0.0),
        )
    return nodes
