"""The daily amounts a person's age and sex call for."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.domain.enums import ReferenceKind, ReferencePopulation
from app.services.reference_intakes import reference_intakes

router = APIRouter(prefix="/v1/reference-intakes", tags=["reference intakes"])


class _FromRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ReferenceValueResponse(_FromRecord):
    nutrient_key: str
    amount: float
    unit: str
    kind: ReferenceKind
    source_key: str
    is_general: bool


class ReferenceSourceResponse(_FromRecord):
    key: str
    publisher: str
    title: str
    url: str | None


class ReferenceIntakesResponse(_FromRecord):
    population: ReferencePopulation
    values: list[ReferenceValueResponse]
    sources: list[ReferenceSourceResponse]


@router.get("")
def read_reference_intakes(
    session: Annotated[Session, Depends(get_session)],
    population: Annotated[
        ReferencePopulation, Query(description="The age and sex group to compare with.")
    ] = ReferencePopulation.GENERAL_LABEL,
) -> ReferenceIntakesResponse:
    """A nutrient with no reference at all, such as total sugars, is simply not listed."""
    return ReferenceIntakesResponse.model_validate(reference_intakes(session, population))
