"""Food search, the food detail page's data, and what-if simulations."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from app.api.errors import ErrorResponse, InvalidRequestError, NotFoundError
from app.db.session import get_session
from app.domain.enums import (
    AllergenRelation,
    ConclusionSeverity,
    FoodKind,
    FoodTypeFilter,
    NutrientMark,
    NutrientStatus,
    ProcessingLevel,
    RelatedReason,
    SearchMatch,
    Uncertainty,
    ValueKind,
    Verification,
)
from app.domain.nutrition.composition import ContributionStatus
from app.domain.nutrition.simulation import (
    AddEdit,
    Edit,
    IngredientEdit,
    InvalidEdit,
    RemoveEdit,
    ReplaceEdit,
    ReplacementFood,
    ScaleEdit,
)
from app.domain.substitution import Diet, Goal
from app.services.food_composition import FoodComposition, food_composition
from app.services.foods import FoodNotFound, food_detail, related_foods, search_foods
from app.services.substitutions import (
    ReasonCode,
    SubstitutionCandidate,
    SubstitutionOrigin,
    UnavailableReason,
    rank_substitutions,
)

router = APIRouter(prefix="/v1/foods", tags=["foods"])


class _FromRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class FoodSearchResult(_FromRecord):
    id: int
    slug: str
    name: str
    kind: FoodKind
    food_group: str | None
    processing_level: ProcessingLevel
    source_key: str
    match: SearchMatch


class FoodSearchResponse(_FromRecord):
    query: str
    results: list[FoodSearchResult]
    has_more: bool


class PortionResponse(_FromRecord):
    description: str
    gram_weight: float
    is_household_measure: bool


class NutrientResponse(_FromRecord):
    key: str
    name: str
    unit: str
    status: NutrientStatus
    amount_per_100g: float | None
    value_kind: ValueKind | None
    derivation: str | None
    daily_value: float | None
    daily_value_source_key: str | None
    source_keys: list[str]
    missing_ingredients: list[str]


class SourceResponse(_FromRecord):
    key: str
    publisher: str
    title: str
    url: str | None
    version: str | None
    license: str | None


class FoodDetailResponse(_FromRecord):
    id: int
    slug: str
    name: str
    description: str | None
    kind: FoodKind
    food_group_key: str | None
    food_group_name: str | None
    processing_level: ProcessingLevel
    processing_level_source_key: str | None
    source_key: str
    recipe_label: str | None
    portions: list[PortionResponse]
    nutrients: list[NutrientResponse]
    sources: list[SourceResponse]


class ImageResponse(_FromRecord):
    url: str
    license: str
    attribution: str


class RecipeResponse(_FromRecord):
    label: str
    moisture_change_pct: float
    raw_weight_g: float | None
    cooked_weight_g: float | None


class ServingResponse(_FromRecord):
    key: str
    label: str
    grams: float
    is_household_measure: bool
    is_default: bool


class IngredientAllergenResponse(_FromRecord):
    key: str
    relation: AllergenRelation
    verification: Verification


class DishAllergenResponse(_FromRecord):
    key: str
    name: str
    relation: AllergenRelation
    verification: Verification
    ingredient_names: list[str]


class IngredientResponse(_FromRecord):
    component_id: int
    food_id: int
    name: str
    kind: FoodKind
    weight_g: float | None
    weight_share: float | None
    has_own_recipe: bool
    excluded: bool
    edit: IngredientEdit
    original_weight_g: float | None
    replaces_component_id: int | None
    allergens: list[IngredientAllergenResponse]
    considerations: list[str]


class ContributionResponse(_FromRecord):
    nutrient_key: str
    component_id: int
    status: ContributionStatus
    amount: float | None
    share: float | None
    estimated: bool


class CompositionNutrientResponse(_FromRecord):
    key: str
    name: str
    unit: str
    category: str
    direction: str
    status: NutrientStatus
    amount_per_100g: float | None
    base_amount_per_100g: float | None
    delta_per_100g: float | None
    approximate: bool
    value_kind: ValueKind | None
    derivation: str | None
    daily_value: float | None
    daily_value_source_key: str | None
    source_keys: list[str]
    missing_ingredients: list[str]


class ServingNutrientResponse(_FromRecord):
    key: str
    amount: float | None
    percent_daily_value: float | None
    mark: NutrientMark


class RuleResponse(_FromRecord):
    id: str
    version: int


class SupportingFactResponse(_FromRecord):
    key: str
    value: float | str
    unit: str | None


class ConclusionResponse(_FromRecord):
    code: str
    severity: ConclusionSeverity
    subject: str
    message_key: str
    message_params: dict[str, float | str]
    supporting_facts: list[SupportingFactResponse]
    rules_triggered: list[RuleResponse]
    sources: list[str]
    uncertainty: Uncertainty
    missing: list[str]


class ServingEvaluationResponse(_FromRecord):
    serving_key: str
    nutrients: list[ServingNutrientResponse]
    conclusions: list[ConclusionResponse]


class FoodCompositionResponse(_FromRecord):
    id: int
    slug: str
    name: str
    description: str | None
    kind: FoodKind
    food_group_key: str | None
    food_group_name: str | None
    processing_level: ProcessingLevel
    processing_level_source_key: str | None
    source_key: str
    is_modified: bool
    high_percent_daily_value: float
    images: list[ImageResponse]
    recipe: RecipeResponse | None
    servings: list[ServingResponse]
    allergens: list[DishAllergenResponse]
    ingredients: list[IngredientResponse]
    nutrients: list[CompositionNutrientResponse]
    contributions: list[ContributionResponse]
    evaluations: list[ServingEvaluationResponse]
    sources: list[SourceResponse]


class RemoveIngredientEdit(BaseModel):
    type: Literal["remove"]
    component_id: int

    def to_domain(self) -> Edit:
        return RemoveEdit(self.component_id)


class ScaleIngredientEdit(BaseModel):
    type: Literal["scale"]
    component_id: int
    factor: Annotated[float, Field(gt=0, le=10)]

    def to_domain(self) -> Edit:
        return ScaleEdit(self.component_id, self.factor)


class ReplacementItem(BaseModel):
    food_id: int
    # Grams of this food per gram of the ingredient it replaces.
    ratio: Annotated[float, Field(gt=0, le=20)]


class ReplaceIngredientEdit(BaseModel):
    type: Literal["replace"]
    component_id: int
    replacements: Annotated[list[ReplacementItem], Field(min_length=1, max_length=8)]

    @field_validator("replacements")
    @classmethod
    def foods_are_distinct(cls, replacements: list[ReplacementItem]) -> list[ReplacementItem]:
        ids = [item.food_id for item in replacements]
        if len(ids) != len(set(ids)):
            raise ValueError("Each replacement food can appear once.")
        return replacements

    def to_domain(self) -> Edit:
        return ReplaceEdit(
            self.component_id,
            tuple(ReplacementFood(item.food_id, item.ratio) for item in self.replacements),
        )


class AddIngredientEdit(BaseModel):
    type: Literal["add"]
    food_id: int
    weight_g: Annotated[float, Field(gt=0, le=100_000)]

    def to_domain(self) -> Edit:
        return AddEdit(self.food_id, self.weight_g)


IngredientEditRequest = Annotated[
    RemoveIngredientEdit | ScaleIngredientEdit | ReplaceIngredientEdit | AddIngredientEdit,
    Field(discriminator="type"),
]


def _check_edits_are_distinct(edits: list[IngredientEditRequest]) -> list[IngredientEditRequest]:
    components = [e.component_id for e in edits if not isinstance(e, AddIngredientEdit)]
    if len(components) != len(set(components)):
        raise ValueError("Each ingredient can be edited once.")
    added = [e.food_id for e in edits if isinstance(e, AddIngredientEdit)]
    if len(added) != len(set(added)):
        raise ValueError("Each food can be added once.")
    return edits


class SimulationRequest(BaseModel):
    edits: Annotated[list[IngredientEditRequest], Field(min_length=1, max_length=100)]

    @field_validator("edits")
    @classmethod
    def edits_are_distinct(cls, edits: list[IngredientEditRequest]) -> list[IngredientEditRequest]:
        return _check_edits_are_distinct(edits)


class SubstitutionRequest(BaseModel):
    component_id: int
    goal: Goal
    avoid_allergens: Annotated[list[str], Field(max_length=20)] = []
    diet: Diet = Diet.ANY
    # What has already been changed, so options are judged against the dish as it now stands.
    edits: Annotated[list[IngredientEditRequest], Field(max_length=100)] = []

    @field_validator("edits")
    @classmethod
    def edits_are_distinct(cls, edits: list[IngredientEditRequest]) -> list[IngredientEditRequest]:
        return _check_edits_are_distinct(edits)


class ScoreResponse(_FromRecord):
    """Every part of the ranking. A null part has no data, which lowers completeness."""

    nutrition: float | None
    flavor: float | None
    texture: float | None
    culinary_fit: float | None
    preference: float | None
    total: float
    completeness: float


class GoalEffectResponse(_FromRecord):
    nutrient_key: str
    unit: str
    before_per_100g: float
    after_per_100g: float
    approximate: bool


class ReasonResponse(_FromRecord):
    code: ReasonCode
    nutrient_key: str | None


class ReplacementResponse(_FromRecord):
    food_id: int
    name: str
    ratio: float
    weight_g: float


class CandidateAllergenResponse(_FromRecord):
    key: str
    name: str
    relation: AllergenRelation
    verification: Verification


class SubstitutionOptionResponse(BaseModel):
    key: str
    origin: SubstitutionOrigin
    # Send this back to the simulation endpoint to apply the swap.
    edit: IngredientEditRequest
    replacements: list[ReplacementResponse]
    scale_factor: float | None
    goal_effect: GoalEffectResponse | None
    scores: ScoreResponse
    reasons: list[ReasonResponse]
    allergens: list[CandidateAllergenResponse]
    note: str | None
    verification: Verification
    source_keys: list[str]


class SubstitutionsResponse(BaseModel):
    food_id: int
    component_id: int
    goal: Goal
    nutrient_key: str | None
    serving_label: str
    unavailable_reason: UnavailableReason | None
    options: list[SubstitutionOptionResponse]
    hidden_for_allergens: int
    hidden_for_diet: int
    could_not_evaluate: list[str]
    sources: list[SourceResponse]


class RelatedFoodResponse(_FromRecord):
    id: int
    slug: str
    name: str
    kind: FoodKind
    food_group: str | None
    reason: RelatedReason
    shared_ingredients: list[str]


class RelatedFoodsResponse(_FromRecord):
    similar: list[RelatedFoodResponse]
    explore: list[RelatedFoodResponse]


def _composition_response(composition: FoodComposition) -> FoodCompositionResponse:
    return FoodCompositionResponse.model_validate(composition)


def _edit_request(edit: Edit) -> IngredientEditRequest:
    if isinstance(edit, ScaleEdit):
        return ScaleIngredientEdit(type="scale", component_id=edit.component_id, factor=edit.factor)
    if isinstance(edit, ReplaceEdit):
        return ReplaceIngredientEdit(
            type="replace",
            component_id=edit.component_id,
            replacements=[
                ReplacementItem(food_id=item.food_id, ratio=item.ratio)
                for item in edit.replacements
            ],
        )
    raise ValueError(f"Rankings never offer this kind of edit: {edit!r}")


def _option_response(candidate: SubstitutionCandidate) -> SubstitutionOptionResponse:
    return SubstitutionOptionResponse(
        key=candidate.key,
        origin=candidate.origin,
        edit=_edit_request(candidate.edit),
        replacements=[ReplacementResponse.model_validate(r) for r in candidate.replacements],
        scale_factor=candidate.scale_factor,
        goal_effect=(
            GoalEffectResponse.model_validate(candidate.goal_effect)
            if candidate.goal_effect
            else None
        ),
        scores=ScoreResponse.model_validate(candidate.scores),
        reasons=[ReasonResponse.model_validate(r) for r in candidate.reasons],
        allergens=[CandidateAllergenResponse.model_validate(a) for a in candidate.allergens],
        note=candidate.note,
        verification=candidate.verification,
        source_keys=list(candidate.source_keys),
    )


@router.get("/search")
def search(
    session: Annotated[Session, Depends(get_session)],
    q: Annotated[str, Query(min_length=1, max_length=200, description="Food name to find.")],
    food_type: Annotated[
        FoodTypeFilter, Query(alias="type", description="Excludes every other kind of food.")
    ] = FoodTypeFilter.ALL,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    offset: Annotated[int, Query(ge=0, le=10_000)] = 0,
) -> FoodSearchResponse:
    page = search_foods(session, q, food_type, limit, offset)
    return FoodSearchResponse.model_validate(page)


@router.get("/{food_id}", responses={404: {"model": ErrorResponse}})
def read_food(
    food_id: int, session: Annotated[Session, Depends(get_session)]
) -> FoodDetailResponse:
    """Lists every tracked nutrient. A value nobody knows is null with an `unknown` status."""
    try:
        detail = food_detail(session, food_id)
    except FoodNotFound as exc:
        raise NotFoundError("Food", food_id) from exc
    return FoodDetailResponse.model_validate(detail)


@router.get("/{food_id}/composition", responses={404: {"model": ErrorResponse}})
def read_composition(
    food_id: int, session: Annotated[Session, Depends(get_session)]
) -> FoodCompositionResponse:
    """Everything the food page shows, including marks for every serving."""
    try:
        return _composition_response(food_composition(session, food_id))
    except FoodNotFound as exc:
        raise NotFoundError("Food", food_id) from exc


@router.post(
    "/{food_id}/simulations",
    responses={404: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
def simulate(
    food_id: int,
    request: SimulationRequest,
    session: Annotated[Session, Depends(get_session)],
) -> FoodCompositionResponse:
    """Returns the composition with these edits applied. Writes nothing."""
    edits = [edit.to_domain() for edit in request.edits]
    try:
        return _composition_response(food_composition(session, food_id, edits))
    except FoodNotFound as exc:
        raise NotFoundError("Food", food_id) from exc
    except InvalidEdit as exc:
        raise InvalidRequestError(str(exc)) from exc


@router.post(
    "/{food_id}/substitutions",
    responses={404: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
def substitutions(
    food_id: int,
    request: SubstitutionRequest,
    session: Annotated[Session, Depends(get_session)],
) -> SubstitutionsResponse:
    """Ranks what could replace one ingredient for a goal. Writes nothing.

    Foods holding an avoided allergen never appear, including through a recipe or as one part of a
    replacement. An option is not a statement that a food is free of an allergen: USDA lists no
    allergens, so these findings come from names and recipes, and only a label can confirm them.
    """
    try:
        results = rank_substitutions(
            session,
            food_id,
            request.component_id,
            request.goal,
            request.avoid_allergens,
            request.diet,
            [edit.to_domain() for edit in request.edits],
        )
    except FoodNotFound as exc:
        raise NotFoundError("Food", food_id) from exc
    except InvalidEdit as exc:
        raise InvalidRequestError(str(exc)) from exc
    return SubstitutionsResponse(
        food_id=results.food_id,
        component_id=results.component_id,
        goal=results.goal,
        nutrient_key=results.nutrient_key,
        serving_label=results.serving_label,
        unavailable_reason=results.unavailable_reason,
        options=[_option_response(option) for option in results.options],
        hidden_for_allergens=results.hidden_for_allergens,
        hidden_for_diet=results.hidden_for_diet,
        could_not_evaluate=list(results.could_not_evaluate),
        sources=[SourceResponse.model_validate(source) for source in results.sources],
    )


@router.get("/{food_id}/related", responses={404: {"model": ErrorResponse}})
def read_related(
    food_id: int,
    session: Annotated[Session, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=24)] = 6,
) -> RelatedFoodsResponse:
    try:
        return RelatedFoodsResponse.model_validate(related_foods(session, food_id, limit))
    except FoodNotFound as exc:
        raise NotFoundError("Food", food_id) from exc
