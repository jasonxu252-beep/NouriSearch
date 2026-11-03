"""Food search, the food detail page's data, and what-if simulations."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from app.api.errors import ErrorResponse, InvalidRequestError, NotFoundError
from app.db.session import get_session
from app.domain.enums import (
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
)
from app.domain.nutrition.composition import ContributionStatus
from app.services.food_composition import FoodComposition, InvalidEdit, food_composition
from app.services.foods import FoodNotFound, food_detail, related_foods, search_foods

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


class IngredientResponse(_FromRecord):
    component_id: int
    food_id: int
    name: str
    kind: FoodKind
    weight_g: float | None
    weight_share: float | None
    has_own_recipe: bool
    excluded: bool
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
    ingredients: list[IngredientResponse]
    nutrients: list[CompositionNutrientResponse]
    contributions: list[ContributionResponse]
    evaluations: list[ServingEvaluationResponse]
    sources: list[SourceResponse]


class RemoveIngredientEdit(BaseModel):
    type: Literal["remove"]
    component_id: int


class SimulationRequest(BaseModel):
    edits: Annotated[list[RemoveIngredientEdit], Field(min_length=1, max_length=100)]

    @field_validator("edits")
    @classmethod
    def components_are_distinct(
        cls, edits: list[RemoveIngredientEdit]
    ) -> list[RemoveIngredientEdit]:
        ids = [edit.component_id for edit in edits]
        if len(ids) != len(set(ids)):
            raise ValueError("Each ingredient can be edited once.")
        return edits


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
    excluded = [edit.component_id for edit in request.edits]
    try:
        return _composition_response(food_composition(session, food_id, excluded))
    except FoodNotFound as exc:
        raise NotFoundError("Food", food_id) from exc
    except InvalidEdit as exc:
        raise InvalidRequestError(str(exc)) from exc


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
