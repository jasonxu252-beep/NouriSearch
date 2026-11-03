"""Baseline food search and the food detail read."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.api.errors import ErrorResponse, NotFoundError
from app.db.session import get_session
from app.domain.enums import (
    FoodKind,
    FoodTypeFilter,
    NutrientStatus,
    ProcessingLevel,
    SearchMatch,
    ValueKind,
)
from app.services.foods import FoodNotFound, food_detail, search_foods

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
