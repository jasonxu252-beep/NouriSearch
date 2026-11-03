"""Ranks what could replace an ingredient, following the plan's five steps.

1. Generate candidates: reviewed swaps first, then same-role foods, plus using less or more.
2. Filter by hard constraints: allergens, diet, and role. A violating candidate never appears.
3. Evaluate the resulting dish through the simulation and the rules.
4. Score by goal, returning every part of the score.
5. Keep unknowns honest: missing data lowers completeness and is never read as zero.
"""

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum

from sqlalchemy.orm import Session

from app.domain.enums import (
    AllergenRelation,
    FoodClassificationKind,
    NutrientDirection,
    NutrientMark,
    Verification,
)
from app.domain.nutrition.composition import (
    WATER_KEY,
    ComponentNode,
    NutrientBreakdown,
    NutrientFact,
    nutrient_breakdown,
)
from app.domain.nutrition.simulation import (
    AddEdit,
    Edit,
    InvalidEdit,
    ReplaceEdit,
    ReplacementFood,
    ScaleEdit,
    apply_edits,
)
from app.domain.rules.engine import ServingFact, evaluate, nutrient_mark
from app.domain.substitution import (
    GOALS,
    MIN_UNREVIEWED_FLAVOR,
    MIN_UNREVIEWED_SCORE,
    SCALE_LESS,
    SCALE_MORE,
    TEXTURE_ROLES,
    Diet,
    Goal,
    ScoreParts,
    blended_profile,
    combine_score,
    culinary_fit_score,
    goal_change,
    is_allowed_by_allergens,
    is_allowed_by_diet,
    moves_enough,
    nutrition_score,
    scaled_closeness,
    sensory_similarity,
)
from app.repositories.composition import (
    DefaultRecipe,
    load_composition,
    load_default_recipe,
    load_facts,
    load_food_nodes,
)
from app.repositories.foods import (
    NutrientRecord,
    SourceRecord,
    load_food,
    load_nutrient_catalog,
    load_portions,
    load_sources,
)
from app.repositories.substitutions import (
    AllergenFinding,
    OfferedFood,
    SensoryProfile,
    load_allergen_findings,
    load_allergen_names,
    load_diet_classifications,
    load_food_role,
    load_options,
    load_same_role_foods,
    load_sensory_profiles,
)
from app.services.food_composition import RULES, Serving, build_servings, resolve_edited_value
from app.services.foods import FoodNotFound, ResolvedValue, resolve_value

# Enough to choose from without filling a small popup.
MAX_OPTIONS = 8
# Unreviewed pairings are a fallback, so only the best few are shown.
MAX_SAME_ROLE = 3

_SENSORY_CLOSE = 0.6
_SENSORY_DIFFERENT = 0.3
# A rise under this share of the Daily Value in a serving is not worth mentioning.
_SIDE_EFFECT_PERCENT = 1.0
_DIET_KINDS = (
    FoodClassificationKind.MEAT_OR_FISH.value,
    FoodClassificationKind.ANIMAL_DERIVED.value,
)
_NO_SENSORY = SensoryProfile({}, {})


class SubstitutionOrigin(StrEnum):
    # A swap in the curated list.
    CURATED = "curated"
    # The same role and food group, which no one has reviewed as a pairing.
    SAME_ROLE = "same_role"
    USE_LESS = "use_less"
    USE_MORE = "use_more"


class UnavailableReason(StrEnum):
    # The ingredient has no stated weight, so no swap can be calculated.
    NO_WEIGHT = "no_weight"
    # Nobody knows this dish's value for the goal's nutrient, so no swap can be judged.
    GOAL_UNKNOWN = "goal_unknown"


class ReasonCode(StrEnum):
    FLAVOR_CLOSE = "flavor_close"
    FLAVOR_DIFFERENT = "flavor_different"
    FLAVOR_UNKNOWN = "flavor_unknown"
    TEXTURE_CLOSE = "texture_close"
    TEXTURE_DIFFERENT = "texture_different"
    TEXTURE_UNKNOWN = "texture_unknown"
    MARK_CLEARED = "mark_cleared"
    MARK_RAISED = "mark_raised"
    SIDE_EFFECT = "side_effect"


@dataclass(frozen=True, slots=True)
class Reason:
    code: ReasonCode
    # The nutrient a mark or a side effect concerns.
    nutrient_key: str | None = None


@dataclass(frozen=True, slots=True)
class ReplacementInfo:
    food_id: int
    name: str
    ratio: float
    weight_g: float


@dataclass(frozen=True, slots=True)
class GoalEffect:
    nutrient_key: str
    unit: str
    before_per_100g: float
    after_per_100g: float
    # The recipe does not fully explain the published value, so this is only an approximation.
    approximate: bool


@dataclass(frozen=True, slots=True)
class CandidateAllergen:
    key: str
    name: str
    relation: AllergenRelation
    verification: Verification


@dataclass(frozen=True, slots=True)
class SubstitutionCandidate:
    key: str
    origin: SubstitutionOrigin
    edit: Edit
    replacements: tuple[ReplacementInfo, ...]
    scale_factor: float | None
    goal_effect: GoalEffect | None
    scores: ScoreParts
    reasons: tuple[Reason, ...]
    allergens: tuple[CandidateAllergen, ...]
    note: str | None
    verification: Verification
    source_keys: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SubstitutionResults:
    food_id: int
    component_id: int
    goal: Goal
    nutrient_key: str | None
    serving_label: str
    unavailable_reason: UnavailableReason | None
    options: tuple[SubstitutionCandidate, ...]
    # Counted, not named: naming a hidden food would make it appear after all.
    hidden_for_allergens: int
    hidden_for_diet: int
    # Foods with no value for the goal's nutrient, so nothing can be said about them.
    could_not_evaluate: tuple[str, ...]
    sources: tuple[SourceRecord, ...]


@dataclass(frozen=True, slots=True)
class _Draft:
    key: str
    origin: SubstitutionOrigin
    edit: Edit
    replacements: tuple[ReplacementInfo, ...]
    scale_factor: float | None
    culinary_fit: int | None
    note: str | None
    verification: Verification
    source_id: int | None


@dataclass(frozen=True, slots=True)
class _Dish:
    """A dish with everything needed to value it under any set of edits."""

    components: tuple[ComponentNode, ...]
    recipe: DefaultRecipe
    # Only the nutrients that can change the answer.
    nutrients: tuple[NutrientRecord, ...]
    facts: Mapping[int, NutrientFact]
    full: Mapping[int, NutrientBreakdown]
    serving: Serving
    foods: Mapping[int, ComponentNode]

    def values(self, edits: Sequence[Edit]) -> dict[str, tuple[ResolvedValue, bool]]:
        if not edits:
            return {
                n.key: (resolve_value(n, self.facts.get(n.id), self.components, self.recipe), False)
                for n in self.nutrients
            }
        final = apply_edits(self.components, edits, self.foods).components
        return {
            n.key: resolve_edited_value(
                n, self.facts.get(n.id), self.full[n.id], final, self.recipe.moisture_change_pct
            )
            for n in self.nutrients
        }

    def high_marks(self, values: Mapping[str, tuple[ResolvedValue, bool]]) -> set[str]:
        """The nutrients the rules flag in the default serving, the same marks the page shows."""
        facts = [
            ServingFact(
                nutrient_key=n.key,
                direction=n.direction,
                status=values[n.key][0].status,
                amount_per_100g=values[n.key][0].amount,
                unit=n.unit,
                daily_value=n.daily_value,
                daily_value_source_key=None,
                value_source_keys=(),
                missing=values[n.key][0].gaps,
                serving_key=self.serving.key,
                serving_label=self.serving.label,
                serving_g=self.serving.grams,
            )
            for n in self.nutrients
        ]
        conclusions = evaluate(facts, RULES)
        return {
            fact.nutrient_key
            for fact in facts
            if nutrient_mark(fact, conclusions) is NutrientMark.EXCLAMATION
        }


def _edited_component(edit: Edit) -> int | None:
    return None if isinstance(edit, AddEdit) else edit.component_id


def _foods_in(edits: Collection[Edit]) -> set[int]:
    food_ids: set[int] = set()
    for edit in edits:
        if isinstance(edit, AddEdit):
            food_ids.add(edit.food_id)
        elif isinstance(edit, ReplaceEdit):
            food_ids.update(item.food_id for item in edit.replacements)
    return food_ids


def _curated_drafts(
    session: Session, target: ComponentNode, dish_id: int, role: str | None
) -> list[_Draft]:
    drafts = []
    weight = target.weight_g or 0.0
    for option in load_options(session, target.food_id, dish_id):
        if option.required_role and option.required_role != role:
            continue
        # What stays from the original reads first: salt and lemon juice, not lemon juice and salt.
        targets = sorted(option.targets, key=lambda item: item.food_id != target.food_id)
        drafts.append(
            _Draft(
                key=f"option-{option.id}",
                origin=SubstitutionOrigin.CURATED,
                edit=ReplaceEdit(
                    target.component_id,
                    tuple(ReplacementFood(t.food_id, t.ratio) for t in targets),
                ),
                replacements=tuple(
                    ReplacementInfo(t.food_id, t.name, t.ratio, weight * t.ratio) for t in targets
                ),
                scale_factor=None,
                culinary_fit=option.culinary_fit,
                note=option.notes,
                verification=option.verification,
                source_id=option.source_id,
            )
        )
    return drafts


def _same_role_drafts(
    target: ComponentNode, foods: Sequence[OfferedFood], reviewed: Collection[int]
) -> list[_Draft]:
    weight = target.weight_g or 0.0
    return [
        _Draft(
            key=f"food-{food.id}",
            origin=SubstitutionOrigin.SAME_ROLE,
            edit=ReplaceEdit(target.component_id, (ReplacementFood(food.id, 1.0),)),
            replacements=(ReplacementInfo(food.id, food.name, 1.0, weight),),
            scale_factor=None,
            culinary_fit=None,
            note=None,
            verification=Verification.ESTIMATED,
            source_id=food.source_id,
        )
        for food in foods
        if food.id not in reviewed
    ]


def _scale_drafts(target: ComponentNode, direction: int) -> list[_Draft]:
    if direction == 0:
        return []
    factors = SCALE_LESS if direction < 0 else SCALE_MORE
    origin = SubstitutionOrigin.USE_LESS if direction < 0 else SubstitutionOrigin.USE_MORE
    return [
        _Draft(
            key=f"scale-{factor}",
            origin=origin,
            edit=ScaleEdit(target.component_id, factor),
            replacements=(),
            scale_factor=factor,
            culinary_fit=None,
            note=None,
            verification=Verification.TYPICAL,
            source_id=None,
        )
        for factor in factors
    ]


def _draft_foods(draft: _Draft, target: ComponentNode) -> list[int]:
    """The foods a draft leaves in the dish. Using less keeps the original ingredient."""
    if draft.replacements:
        return [item.food_id for item in draft.replacements]
    return [target.food_id]


def _sensory_reason(
    score: float | None,
    close: ReasonCode,
    different: ReasonCode,
    unknown: ReasonCode,
) -> Reason | None:
    if score is None:
        return Reason(unknown)
    if score >= _SENSORY_CLOSE:
        return Reason(close)
    if score < _SENSORY_DIFFERENT:
        return Reason(different)
    return None


def _similarity(
    draft: _Draft,
    target: ComponentNode,
    profiles: Mapping[int, SensoryProfile],
) -> tuple[float | None, float | None]:
    """Flavor and texture likeness. Using less of a food keeps its character at lower strength."""
    if draft.scale_factor is not None:
        return scaled_closeness(draft.scale_factor), None
    own = profiles.get(target.food_id, _NO_SENSORY)
    parts = [(profiles.get(r.food_id, _NO_SENSORY), r.ratio) for r in draft.replacements]
    flavor = blended_profile((profile.flavor, ratio) for profile, ratio in parts)
    texture = blended_profile((profile.texture, ratio) for profile, ratio in parts)
    return (
        sensory_similarity(own.flavor, flavor) if flavor else None,
        sensory_similarity(own.texture, texture) if texture else None,
    )


def _candidate_allergens(
    food_ids: Sequence[int],
    findings: Mapping[int, Mapping[str, AllergenFinding]],
    names: Mapping[str, str],
) -> tuple[CandidateAllergen, ...]:
    merged: dict[str, AllergenFinding] = {}
    for food_id in food_ids:
        for key, finding in findings.get(food_id, {}).items():
            current = merged.get(key)
            if current is None or (
                current.relation is not AllergenRelation.CONTAINS
                and finding.relation is AllergenRelation.CONTAINS
            ):
                merged[key] = finding
    return tuple(
        CandidateAllergen(key, name, merged[key].relation, merged[key].verification)
        for key, name in names.items()
        if key in merged
    )


def _side_effects(
    dish: _Dish,
    goal_key: str | None,
    before: Mapping[str, tuple[ResolvedValue, bool]],
    after: Mapping[str, tuple[ResolvedValue, bool]],
) -> list[Reason]:
    reasons = []
    for nutrient in dish.nutrients:
        if nutrient.key == goal_key or not nutrient.daily_value:
            continue
        old = before[nutrient.key][0].amount
        new = after[nutrient.key][0].amount
        if old is None or new is None or new <= old:
            continue
        percent = (new - old) * dish.serving.grams / 100 / nutrient.daily_value * 100
        if percent >= _SIDE_EFFECT_PERCENT:
            reasons.append(Reason(ReasonCode.SIDE_EFFECT, nutrient.key))
    return reasons


def _is_limit(nutrient: NutrientRecord) -> bool:
    return nutrient.direction is NutrientDirection.LIMIT


def rank_substitutions(
    session: Session,
    food_id: int,
    component_id: int,
    goal: Goal,
    avoid_allergens: Collection[str] = (),
    diet: Diet = Diet.ANY,
    edits: Sequence[Edit] = (),
) -> SubstitutionResults:
    """Ranks replacements for one ingredient, in the dish as it stands after any other edits."""
    food = load_food(session, food_id)
    if food is None:
        raise FoodNotFound(food_id)
    recipe = load_default_recipe(session, food_id)
    if recipe is None:
        raise InvalidEdit(f"Food {food_id} has no recipe to edit.")

    allergen_names = load_allergen_names(session)
    unknown_allergens = set(avoid_allergens) - set(allergen_names)
    if unknown_allergens:
        raise InvalidEdit(f"Unknown allergens: {sorted(unknown_allergens)}.")

    spec = GOALS[goal]
    nutrients = tuple(
        n for n in load_nutrient_catalog(session) if _is_limit(n) or n.key == spec.nutrient_key
    )
    nutrient_ids = [n.id for n in nutrients]
    components = load_composition(session, food_id, nutrient_ids)
    target = next((node for node in components if node.component_id == component_id), None)
    if target is None:
        raise InvalidEdit(f"This recipe has no ingredient {component_id}.")

    servings = build_servings(load_portions(session, food_id))
    serving = next(s for s in servings if s.is_default)

    def results(
        unavailable: UnavailableReason | None = None,
        options: tuple[SubstitutionCandidate, ...] = (),
        hidden_allergens: int = 0,
        hidden_diet: int = 0,
        gaps: tuple[str, ...] = (),
        source_ids: Collection[int] = (),
    ) -> SubstitutionResults:
        return SubstitutionResults(
            food_id=food_id,
            component_id=component_id,
            goal=goal,
            nutrient_key=spec.nutrient_key,
            serving_label=serving.label,
            unavailable_reason=unavailable,
            options=options,
            hidden_for_allergens=hidden_allergens,
            hidden_for_diet=hidden_diet,
            could_not_evaluate=gaps,
            sources=tuple(load_sources(session, sorted(source_ids))) if source_ids else (),
        )

    if target.weight_g is None:
        return results(UnavailableReason.NO_WEIGHT)

    role = load_food_role(session, target.food_id)
    role_key = role.role if role else None

    # Step 1: generate candidates, reviewed swaps first.
    drafts = _curated_drafts(session, target, food_id, role_key)
    reviewed = {d.replacements[0].food_id for d in drafts if len(d.replacements) == 1}
    same_role = load_same_role_foods(session, role, target.food_id) if role else []
    drafts += _same_role_drafts(target, same_role, reviewed)
    drafts += _scale_drafts(target, spec.direction)

    # Step 2: filter by hard constraints.
    other_edits = tuple(e for e in edits if _edited_component(e) != component_id)
    candidate_foods = {f for d in drafts for f in _draft_foods(d, target)}
    findings = load_allergen_findings(session, candidate_foods | {target.food_id})
    classifications = load_diet_classifications(session, candidate_foods, _DIET_KINDS)
    hidden_allergens = 0
    hidden_diet = 0
    allowed: list[_Draft] = []
    for draft in drafts:
        kept = _draft_foods(draft, target)
        found = {key for f in kept for key in findings.get(f, {})}
        if not is_allowed_by_allergens(avoid_allergens, found):
            hidden_allergens += 1
        elif not all(is_allowed_by_diet(diet, classifications.get(f, set())) for f in kept):
            hidden_diet += 1
        else:
            allowed.append(draft)

    # Step 3: evaluate the resulting dish.
    facts = load_facts(session, [food_id], nutrient_ids).get(food_id, {})
    moisture = recipe.moisture_change_pct
    full = {
        n.id: nutrient_breakdown(
            components,
            n.id,
            facts[n.id].amount_per_100g if n.id in facts and not facts[n.id].estimated else None,
            moisture,
            n.key == WATER_KEY,
        )
        for n in nutrients
    }
    brought_in = {f for d in allowed for f in _draft_foods(d, target)} | _foods_in(other_edits)
    dish = _Dish(
        components,
        recipe,
        nutrients,
        facts,
        full,
        serving,
        load_food_nodes(
            session, brought_in - {target.food_id} | _replacing_itself(allowed), nutrient_ids
        ),
    )
    baseline = dish.values(other_edits)
    baseline_marks = dish.high_marks(baseline)

    goal_nutrient = next((n for n in nutrients if n.key == spec.nutrient_key), None)
    before = baseline[goal_nutrient.key][0].amount if goal_nutrient else None
    if goal_nutrient and before is None:
        return results(UnavailableReason.GOAL_UNKNOWN)

    profiles = load_sensory_profiles(session, candidate_foods | {target.food_id})
    texture_applies = role_key in TEXTURE_ROLES
    gaps: list[str] = []
    scored: list[tuple[_Draft, ScoreParts, GoalEffect | None, tuple[Reason, ...], set[int]]] = []
    for draft in allowed:
        after = dish.values([*other_edits, draft.edit])
        value: ResolvedValue | None = None
        approximate = False
        change: float | None = None
        if goal_nutrient and before is not None:
            value, approximate = after[goal_nutrient.key]
            if value.amount is None:
                gaps.extend(value.gaps)
                continue
            change = goal_change(spec, before, value.amount)
            if not moves_enough(
                change, before, value.amount, serving.grams, goal_nutrient.daily_value
            ):
                continue

        flavor, texture = _similarity(draft, target, profiles)
        if (
            draft.origin is SubstitutionOrigin.SAME_ROLE
            and flavor is not None
            and flavor < MIN_UNREVIEWED_FLAVOR
        ):
            continue

        # Step 4: score by goal, on how the rules judge the resulting dish.
        marks = dish.high_marks(after)
        cleared = baseline_marks - marks
        raised = marks - baseline_marks
        applies = texture_applies and draft.scale_factor is None
        parts = combine_score(
            spec.weights,
            nutrition_score(change, len(cleared), len(raised)) if change is not None else None,
            flavor,
            texture,
            culinary_fit_score(draft.culinary_fit),
            texture_applies=applies,
        )
        if draft.origin is not SubstitutionOrigin.CURATED and parts.total < MIN_UNREVIEWED_SCORE:
            continue
        reasons = [Reason(ReasonCode.MARK_CLEARED, key) for key in sorted(cleared)]
        reasons += [Reason(ReasonCode.MARK_RAISED, key) for key in sorted(raised)]
        reasons += _side_effects(dish, spec.nutrient_key, baseline, after)
        reasons += [
            reason
            for reason in (
                _sensory_reason(
                    flavor,
                    ReasonCode.FLAVOR_CLOSE,
                    ReasonCode.FLAVOR_DIFFERENT,
                    ReasonCode.FLAVOR_UNKNOWN,
                )
                if draft.scale_factor is None
                else None,
                _sensory_reason(
                    texture,
                    ReasonCode.TEXTURE_CLOSE,
                    ReasonCode.TEXTURE_DIFFERENT,
                    ReasonCode.TEXTURE_UNKNOWN,
                )
                if applies
                else None,
            )
            if reason is not None
        ]
        effect = (
            GoalEffect(
                goal_nutrient.key,
                goal_nutrient.unit,
                before,
                value.amount,
                approximate,
            )
            if goal_nutrient
            and before is not None
            and value is not None
            and value.amount is not None
            else None
        )
        cited = set(value.source_ids) if value else set()
        if draft.source_id is not None:
            cited.add(draft.source_id)
        scored.append((draft, parts, effect, tuple(reasons), cited))

    # A pairing nobody has reviewed never outranks one somebody has, whatever its numbers say.
    scored.sort(key=lambda item: (item[0].origin is SubstitutionOrigin.SAME_ROLE, -item[1].total))
    same_role_seen = 0
    chosen = []
    for item in scored:
        if item[0].origin is SubstitutionOrigin.SAME_ROLE:
            same_role_seen += 1
            if same_role_seen > MAX_SAME_ROLE:
                continue
        chosen.append(item)
    chosen = chosen[:MAX_OPTIONS]

    source_ids: set[int] = set().union(*(item[4] for item in chosen)) if chosen else set()
    sources = load_sources(session, sorted(source_ids)) if source_ids else []
    source_keys = {source.id: source.key for source in sources}
    options = tuple(
        SubstitutionCandidate(
            key=draft.key,
            origin=draft.origin,
            edit=draft.edit,
            replacements=draft.replacements,
            scale_factor=draft.scale_factor,
            goal_effect=effect,
            scores=parts,
            reasons=reasons,
            allergens=_candidate_allergens(_draft_foods(draft, target), findings, allergen_names),
            note=draft.note,
            verification=draft.verification,
            source_keys=tuple(sorted(source_keys[s] for s in cited)),
        )
        for draft, parts, effect, reasons, cited in chosen
    )
    return replace(
        results(None, options, hidden_allergens, hidden_diet, tuple(dict.fromkeys(gaps))),
        sources=tuple(sources),
    )


def _replacing_itself(drafts: Sequence[_Draft]) -> set[int]:
    """A swap can keep part of the original, as half the salt and half lemon juice does."""
    return {item.food_id for draft in drafts for item in draft.replacements}
