"""What happens to a recipe and its published values when ingredients change. Pure: no database.

Four edits exist: remove, scale, replace, and add. All of them reduce to one comparison between the
recipe before and after, so each one follows the same rule about missing data and the same formula.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum

from app.domain.enums import NutrientStatus
from app.domain.nutrition.composition import (
    ComponentNode,
    Contribution,
    ContributionStatus,
    NutrientBreakdown,
    adjusted_per_100g,
    cooked_weight,
)

# A rebuild further than this from the published value means the recipe does not fully explain it,
# so an edit to that recipe is shown as approximate. The simulation benchmark tests this line by
# making swaps USDA itself publishes and comparing the results.
APPROXIMATE_ABOVE_REBUILD_ERROR = 0.10

_COUNTABLE = (ContributionStatus.KNOWN, ContributionStatus.CALCULATED)


class InvalidEdit(ValueError):
    """An edit that cannot apply to this recipe, such as removing an ingredient it does not have."""


@dataclass(frozen=True, slots=True)
class RemoveEdit:
    component_id: int


@dataclass(frozen=True, slots=True)
class ScaleEdit:
    component_id: int
    factor: float


@dataclass(frozen=True, slots=True)
class ReplacementFood:
    food_id: int
    # Grams of this food per gram of the ingredient it replaces.
    ratio: float


@dataclass(frozen=True, slots=True)
class ReplaceEdit:
    component_id: int
    replacements: tuple[ReplacementFood, ...]


@dataclass(frozen=True, slots=True)
class AddEdit:
    food_id: int
    weight_g: float


Edit = RemoveEdit | ScaleEdit | ReplaceEdit | AddEdit


class IngredientEdit(StrEnum):
    NONE = "none"
    REMOVED = "removed"
    REPLACED = "replaced"
    SCALED = "scaled"
    ADDED = "added"


@dataclass(frozen=True, slots=True)
class EditedIngredient:
    """One row of the ingredient list after edits, including rows that left the recipe."""

    node: ComponentNode
    edit: IngredientEdit
    original_weight_g: float | None
    # Which original ingredient this one took the place of, when it arrived through a replacement.
    replaces_component_id: int | None = None

    @property
    def is_in_recipe(self) -> bool:
        return self.edit not in (IngredientEdit.REMOVED, IngredientEdit.REPLACED)


@dataclass(frozen=True, slots=True)
class EditedRecipe:
    rows: tuple[EditedIngredient, ...]

    @property
    def components(self) -> tuple[ComponentNode, ...]:
        return tuple(row.node for row in self.rows if row.is_in_recipe)

    @property
    def is_modified(self) -> bool:
        return any(row.edit is not IngredientEdit.NONE for row in self.rows)


def _scaled_weight(weight_g: float | None, factor: float) -> float | None:
    return weight_g * factor if weight_g is not None else None


def apply_edits(
    components: Sequence[ComponentNode],
    edits: Sequence[Edit],
    foods: Mapping[int, ComponentNode],
) -> EditedRecipe:
    """Builds the recipe that results from these edits.

    `foods` holds a node for every food the edits bring in, in any weight. A new ingredient has no
    recipe row, so it takes a negative ID, which only means something inside this one result.
    """
    known = {node.component_id for node in components}
    by_component: dict[int, Edit] = {}
    additions: list[AddEdit] = []
    for edit in edits:
        if isinstance(edit, AddEdit):
            additions.append(edit)
            continue
        if edit.component_id not in known:
            raise InvalidEdit(f"This recipe has no ingredient {edit.component_id}.")
        if edit.component_id in by_component:
            raise InvalidEdit(f"Ingredient {edit.component_id} is edited twice.")
        by_component[edit.component_id] = edit

    next_id = -1

    def arriving(food_id: int, weight_g: float | None) -> ComponentNode:
        nonlocal next_id
        food = foods.get(food_id)
        if food is None:
            raise InvalidEdit(f"No food {food_id} exists.")
        node = replace(food, component_id=next_id, weight_g=weight_g)
        next_id -= 1
        return node

    rows: list[EditedIngredient] = []
    for node in components:
        change = by_component.get(node.component_id)
        original = node.weight_g
        if isinstance(change, ScaleEdit):
            scaled = replace(node, weight_g=_scaled_weight(original, change.factor))
            rows.append(EditedIngredient(scaled, IngredientEdit.SCALED, original))
        elif isinstance(change, RemoveEdit):
            rows.append(EditedIngredient(node, IngredientEdit.REMOVED, original))
        elif isinstance(change, ReplaceEdit):
            rows.append(EditedIngredient(node, IngredientEdit.REPLACED, original))
            rows.extend(
                EditedIngredient(
                    arriving(item.food_id, _scaled_weight(original, item.ratio)),
                    IngredientEdit.ADDED,
                    None,
                    replaces_component_id=node.component_id,
                )
                for item in change.replacements
            )
        else:
            rows.append(EditedIngredient(node, IngredientEdit.NONE, original))
    rows.extend(
        EditedIngredient(arriving(add.food_id, add.weight_g), IngredientEdit.ADDED, None)
        for add in additions
    )

    recipe = EditedRecipe(tuple(rows))
    if edits and not recipe.components:
        raise InvalidEdit("A recipe cannot lose every ingredient.")
    return recipe


@dataclass(frozen=True, slots=True)
class SimulatedValue:
    status: NutrientStatus
    amount_per_100g: float | None
    approximate: bool
    source_ids: frozenset[int]
    gaps: tuple[str, ...]


def _changes(
    before: NutrientBreakdown, after: NutrientBreakdown
) -> tuple[list[Contribution], list[Contribution]]:
    """What left the recipe and what entered it. A scaled ingredient appears in both."""
    old = {c.component.component_id: c for c in before.contributions}
    new = {c.component.component_id: c for c in after.contributions}
    leaving = [
        c
        for component_id, c in old.items()
        if component_id not in new or new[component_id].component.weight_g != c.component.weight_g
    ]
    entering = [
        c
        for component_id, c in new.items()
        if component_id not in old or old[component_id].component.weight_g != c.component.weight_g
    ]
    return leaving, entering


def published_after_edits(
    before: NutrientBreakdown,
    after: NutrientBreakdown,
    moisture_change_pct: float = 0.0,
    is_water: bool = False,
) -> SimulatedValue:
    """Moves a published value by what the edits changed, keeping USDA's cooking adjustments.

    Nothing can be subtracted or added without knowing how much an ingredient holds. If a changed
    ingredient has no value or no stated weight, the new value is unknown and the ingredient is
    named. Ingredients the edits did not touch cannot affect the result this way.
    """
    published = before.published_per_100g
    if published is None:
        raise ValueError("This calculation needs a published value.")

    leaving, entering = _changes(before, after)
    changed = [*leaving, *entering]
    unknown = tuple(
        dict.fromkeys(
            c.component.name for c in changed if c.status not in _COUNTABLE or c.amount is None
        )
    )
    raw_weight = before.recipe_weight_g
    new_weight = after.recipe_weight_g
    if unknown or raw_weight is None or new_weight is None:
        return SimulatedValue(NutrientStatus.UNKNOWN, None, False, frozenset(), unknown)

    amount_delta = sum(c.amount or 0.0 for c in entering) - sum(c.amount or 0.0 for c in leaving)
    if is_water:
        # A batch of a different size also loses or gains a different amount of water in cooking.
        amount_delta += moisture_change_pct / 100 * (new_weight - raw_weight)

    total = published * cooked_weight(raw_weight, moisture_change_pct) / 100 + amount_delta
    error = before.rebuild_error
    moved = any(c.amount for c in changed)
    return SimulatedValue(
        NutrientStatus.CALCULATED,
        adjusted_per_100g(published, raw_weight, new_weight, amount_delta, moisture_change_pct),
        # Subtracting more than the published value holds means the recipe and value disagree, and
        # a value borrowed from a similar food is only as close as that food is.
        approximate=total < 0
        or any(c.estimated for c in entering)
        or (moved and (error is None or error > APPROXIMATE_ABOVE_REBUILD_ERROR)),
        source_ids=frozenset(
            s for c in (*before.contributions, *after.contributions) for s in c.source_ids
        ),
        gaps=(),
    )
