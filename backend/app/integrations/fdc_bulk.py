"""Adapter for USDA FoodData Central bulk files.

USDA's JSON shape stops here. Everything past this module sees these small types, so a change in
the file format touches one place.
"""

import hashlib
import json
import re
import ssl
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

import httpx2
import structlog

log = structlog.get_logger()

DOWNLOAD_BASE = "https://fdc.nal.usda.gov/fdc-datasets/"

_MOISTURE_CHANGE = re.compile(r"^\s*Moisture change:\s*(-?\d+(?:\.\d+)?)\s*%\s*$")


class DatasetIntegrityError(ValueError):
    """A dataset file is not the one this version of the project was tested against."""


class FdcDataset(StrEnum):
    FOUNDATION = "foundation"
    SR_LEGACY = "sr_legacy"
    FNDDS = "fndds"


@dataclass(frozen=True, slots=True)
class FdcNutrient:
    number: str
    amount: float
    derivation: str | None


@dataclass(frozen=True, slots=True)
class FdcPortion:
    description: str
    gram_weight: float
    position: int


@dataclass(frozen=True, slots=True)
class FdcIngredient:
    position: int
    code: str
    description: str
    weight_g: float | None
    retention_code: int | None


@dataclass(frozen=True, slots=True)
class FdcFood:
    dataset: FdcDataset
    fdc_id: int
    description: str
    category: str | None
    ndb_number: str | None
    food_code: str | None
    moisture_change_pct: float | None
    nutrients: tuple[FdcNutrient, ...]
    portions: tuple[FdcPortion, ...]
    ingredients: tuple[FdcIngredient, ...]


def _nutrients(raw: dict[str, Any]) -> tuple[FdcNutrient, ...]:
    """Skips rows with no amount, so absent data never becomes zero.

    USDA calculates carbohydrate by difference, which comes out slightly negative for ten Foundation
    meats and fish. A negative amount is not a real value, so it counts as unknown too.
    """
    rows = []
    for entry in raw.get("foodNutrients") or []:
        amount = entry.get("amount")
        number = (entry.get("nutrient") or {}).get("number")
        if amount is None or number is None or amount < 0:
            continue
        derivation = (entry.get("foodNutrientDerivation") or {}).get("description")
        rows.append(FdcNutrient(str(number), float(amount), derivation))
    return tuple(rows)


def _portion_description(portion: dict[str, Any]) -> str:
    """FNDDS has a ready description. SR Legacy and Foundation store amount, unit, and modifier."""
    described = portion.get("portionDescription")
    if described:
        return str(described).strip()

    amount = portion.get("amount") or portion.get("value")
    unit = (portion.get("measureUnit") or {}).get("name")
    modifier = str(portion.get("modifier") or "").strip()
    parts = [f"{float(amount):g}"] if amount else []
    if unit and unit != "undetermined":
        parts.append(str(unit))
    if modifier:
        parts.append(modifier)
    return " ".join(parts)


def _portions(raw: dict[str, Any]) -> tuple[FdcPortion, ...]:
    ordered = sorted(raw.get("foodPortions") or [], key=lambda p: p.get("sequenceNumber") or 0)
    rows: list[FdcPortion] = []
    seen: set[str] = set()
    for portion in ordered:
        weight = portion.get("gramWeight")
        description = _portion_description(portion)
        if not weight or weight <= 0 or not description or description in seen:
            continue
        seen.add(description)
        rows.append(FdcPortion(description, float(weight), len(rows)))
    return tuple(rows)


def _ingredients(raw: dict[str, Any]) -> tuple[FdcIngredient, ...]:
    """Only FNDDS rows carry an ingredient code. Foundation lists its measured samples instead."""
    rows = []
    entries = raw.get("inputFoods") or []
    ordered = sorted(entries, key=lambda i: i.get("sequenceNumber") or 0)
    for position, entry in enumerate(ordered):
        code = entry.get("ingredientCode")
        if code is None:
            continue
        weight = entry.get("ingredientWeight")
        description = entry.get("ingredientDescription") or entry.get("foodDescription") or ""
        rows.append(
            FdcIngredient(
                position,
                str(code),
                str(description).strip(),
                float(weight) if weight and weight > 0 else None,
                # Zero means USDA applied no retention factor to this ingredient.
                entry.get("retentionCode") or None,
            )
        )
    return tuple(rows)


def _moisture_change(raw: dict[str, Any]) -> float | None:
    """FNDDS states how much water a recipe gains or loses in a free-text attribute."""
    for attribute in raw.get("foodAttributes") or []:
        match = _MOISTURE_CHANGE.match(str(attribute.get("value") or ""))
        if match:
            return float(match.group(1))
    return None


def parse_food(raw: dict[str, Any], dataset: FdcDataset) -> FdcFood:
    category_record = raw.get("foodCategory") or raw.get("wweiaFoodCategory") or {}
    category = category_record.get("description") or category_record.get(
        "wweiaFoodCategoryDescription"
    )
    ndb = raw.get("ndbNumber")
    code = raw.get("foodCode")
    return FdcFood(
        dataset=dataset,
        fdc_id=int(raw["fdcId"]),
        description=str(raw["description"]).strip(),
        category=str(category) if category else None,
        ndb_number=str(ndb) if ndb is not None else None,
        food_code=str(code) if code is not None else None,
        moisture_change_pct=_moisture_change(raw),
        nutrients=_nutrients(raw),
        portions=_portions(raw),
        ingredients=_ingredients(raw),
    )


def read_foods(path: Path, dataset: FdcDataset) -> Iterator[FdcFood]:
    """Reads a USDA JSON file, or a zip holding one. The top level has one key: the food list."""
    if path.suffix == ".zip":
        with zipfile.ZipFile(path) as archive:
            names = [n for n in archive.namelist() if n.endswith(".json")]
            if len(names) != 1:
                raise ValueError(f"Expected one JSON file in {path.name}, found {names}.")
            with archive.open(names[0]) as handle:
                document = json.load(handle)
    else:
        with path.open(encoding="utf-8") as handle:
            document = json.load(handle)

    foods = document[next(iter(document))]
    for raw in foods:
        yield parse_food(raw, dataset)


def verify_dataset(path: Path, sha256: str) -> None:
    """Fails unless the file matches its pin, so every ingest uses the data the tests measured."""
    with path.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    if digest != sha256:
        raise DatasetIntegrityError(
            f"{path.name} has hash {digest}, but {sha256} is pinned. If USDA republished this "
            "file, delete it, review the new data, and update the pin in fdc_mappings.yaml."
        )


def download_dataset(file_name: str, directory: Path, sha256: str) -> Path:
    """Downloads one USDA archive unless present, and verifies it either way.

    TLS is checked against the system's trust store. Run this on the host where security software
    inspects HTTPS traffic, because containers do not trust that software's certificate.
    """
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / file_name
    if target.exists():
        verify_dataset(target, sha256)
        return target

    partial = target.with_suffix(".partial")
    url = DOWNLOAD_BASE + file_name
    log.info("fdc_download_started", url=url)
    with (
        httpx2.Client(
            verify=ssl.create_default_context(), timeout=120, follow_redirects=True
        ) as client,
        client.stream("GET", url) as response,
        partial.open("wb") as output,
    ):
        response.raise_for_status()
        for chunk in response.iter_bytes():
            output.write(chunk)
    try:
        verify_dataset(partial, sha256)
    except DatasetIntegrityError:
        partial.unlink()
        raise
    partial.replace(target)
    log.info("fdc_download_finished", file=file_name, bytes=target.stat().st_size)
    return target
