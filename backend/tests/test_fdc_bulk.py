"""The USDA adapter, using record shapes copied from the real bulk files."""

import hashlib
import json
import ssl
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx2
import pytest

from app.integrations import fdc_bulk
from app.integrations.fdc_bulk import (
    DatasetIntegrityError,
    FdcDataset,
    download_dataset,
    parse_food,
    read_foods,
    verify_dataset,
)


def record(**overrides: Any) -> dict[str, Any]:
    return {"fdcId": 1, "description": "Test food", **overrides}


def nutrient(number: str, amount: float | None, derivation: str | None = None) -> dict[str, Any]:
    row: dict[str, Any] = {"nutrient": {"number": number}, "amount": amount}
    if derivation:
        row["foodNutrientDerivation"] = {"description": derivation}
    return row


def test_a_nutrient_row_with_no_amount_is_skipped_rather_than_read_as_zero() -> None:
    food = parse_food(
        record(foodNutrients=[nutrient("333", None), nutrient("307", 5.0)]), FdcDataset.FOUNDATION
    )
    assert [n.number for n in food.nutrients] == ["307"]


def test_a_stated_zero_is_kept() -> None:
    food = parse_food(record(foodNutrients=[nutrient("328", 0.0)]), FdcDataset.FNDDS)
    assert food.nutrients[0].amount == 0.0


def test_a_negative_amount_counts_as_unknown() -> None:
    """USDA's carbohydrate by difference for raw chicken drumstick, a real Foundation value."""
    food = parse_food(record(foodNutrients=[nutrient("205", -0.475)]), FdcDataset.FOUNDATION)
    assert food.nutrients == ()


def test_derivation_text_is_kept_verbatim() -> None:
    text = "Assumed zero (Insignificant amount or not naturally occurring in a food)"
    food = parse_food(record(foodNutrients=[nutrient("291", 0.0, text)]), FdcDataset.SR_LEGACY)
    assert food.nutrients[0].derivation == text


def test_portions_use_each_datasets_own_shape_in_the_sources_order() -> None:
    fndds = parse_food(
        record(
            foodPortions=[
                {
                    "portionDescription": "Quantity not specified",
                    "gramWeight": 121.0,
                    "sequenceNumber": 2,
                },
                {"portionDescription": "1 cup", "gramWeight": 162.0, "sequenceNumber": 1},
            ]
        ),
        FdcDataset.FNDDS,
    )
    assert [(p.description, p.gram_weight, p.position) for p in fndds.portions] == [
        ("1 cup", 162.0, 0),
        ("Quantity not specified", 121.0, 1),
    ]

    sr = parse_food(
        record(
            foodPortions=[
                {
                    "amount": 1.0,
                    "measureUnit": {"name": "undetermined"},
                    "modifier": "cup, chopped",
                    "gramWeight": 91.0,
                    "sequenceNumber": 1,
                }
            ]
        ),
        FdcDataset.SR_LEGACY,
    )
    assert sr.portions[0].description == "1 cup, chopped"

    foundation = parse_food(
        record(
            foodPortions=[
                {
                    "value": 2.0,
                    "amount": 2.0,
                    "measureUnit": {"name": "tablespoon"},
                    "modifier": "",
                    "gramWeight": 33.9,
                    "sequenceNumber": 1,
                }
            ]
        ),
        FdcDataset.FOUNDATION,
    )
    assert foundation.portions[0].description == "2 tablespoon"


def test_portions_without_a_usable_weight_or_repeats_are_dropped() -> None:
    food = parse_food(
        record(
            foodPortions=[
                {"portionDescription": "1 cup", "gramWeight": 162.0, "sequenceNumber": 1},
                {"portionDescription": "1 cup", "gramWeight": 170.0, "sequenceNumber": 2},
                {"portionDescription": "1 bowl", "gramWeight": 0, "sequenceNumber": 3},
            ]
        ),
        FdcDataset.FNDDS,
    )
    assert [p.description for p in food.portions] == ["1 cup"]


def test_moisture_change_comes_from_the_free_text_attribute() -> None:
    food = parse_food(
        record(foodAttributes=[{"value": "Soup"}, {"value": "Moisture change: -15.5%"}]),
        FdcDataset.FNDDS,
    )
    assert food.moisture_change_pct == -15.5


def test_a_food_with_no_moisture_attribute_stays_unknown_rather_than_zero() -> None:
    assert parse_food(record(), FdcDataset.FNDDS).moisture_change_pct is None
    stated = parse_food(record(foodAttributes=[{"value": "Moisture change: 0%"}]), FdcDataset.FNDDS)
    assert stated.moisture_change_pct == 0.0


def test_ingredients_keep_their_order_weight_and_retention_code() -> None:
    food = parse_food(
        record(
            inputFoods=[
                {
                    "ingredientCode": 2047,
                    "ingredientDescription": "Salt, table",
                    "ingredientWeight": 18,
                    "retentionCode": 0,
                    "sequenceNumber": 2,
                },
                {
                    "ingredientCode": 11457,
                    "ingredientDescription": "Spinach, raw",
                    "ingredientWeight": 270,
                    "retentionCode": 3776,
                    "sequenceNumber": 1,
                },
            ]
        ),
        FdcDataset.FNDDS,
    )
    first, second = food.ingredients
    assert (first.code, first.weight_g, first.retention_code) == ("11457", 270.0, 3776)
    # Zero means USDA applied no retention factor, which is different from a factor of zero.
    assert (second.code, second.position, second.retention_code) == ("2047", 1, None)


def test_a_missing_or_zero_ingredient_weight_means_unknown_quantity() -> None:
    food = parse_food(
        record(inputFoods=[{"ingredientCode": 1, "ingredientWeight": 0, "sequenceNumber": 1}]),
        FdcDataset.FNDDS,
    )
    assert food.ingredients[0].weight_g is None


def test_foundation_sample_lists_are_not_treated_as_ingredients() -> None:
    food = parse_food(
        record(inputFoods=[{"id": 10428, "foodDescription": "HUMMUS, SABRA CLASSIC"}]),
        FdcDataset.FOUNDATION,
    )
    assert food.ingredients == ()


def test_category_comes_from_the_right_field_per_dataset() -> None:
    sr = parse_food(record(foodCategory={"description": "Beef Products"}), FdcDataset.SR_LEGACY)
    fndds = parse_food(
        record(wweiaFoodCategory={"wweiaFoodCategoryDescription": "Rice"}), FdcDataset.FNDDS
    )
    assert (sr.category, fndds.category) == ("Beef Products", "Rice")


def _write_zip(path: Path, files: dict[str, object]) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, json.dumps(content))


def test_read_foods_handles_zip_and_plain_json(tmp_path: Path) -> None:
    document = {"SurveyFoods": [record(fdcId=7)]}
    archive = tmp_path / "foods.zip"
    _write_zip(archive, {"foods.json": document})
    plain = tmp_path / "foods.json"
    plain.write_text(json.dumps(document), encoding="utf-8")

    assert [f.fdc_id for f in read_foods(archive, FdcDataset.FNDDS)] == [7]
    assert [f.fdc_id for f in read_foods(plain, FdcDataset.FNDDS)] == [7]


def test_a_zip_holding_several_json_files_is_rejected(tmp_path: Path) -> None:
    archive = tmp_path / "foods.zip"
    _write_zip(archive, {"a.json": {}, "b.json": {}})
    with pytest.raises(ValueError, match="Expected one JSON file"):
        list(read_foods(archive, FdcDataset.FNDDS))


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def test_a_file_that_does_not_match_its_pin_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "foods.zip"
    path.write_bytes(b"real data")
    verify_dataset(path, _sha256(b"real data"))
    with pytest.raises(DatasetIntegrityError, match="pinned"):
        verify_dataset(path, _sha256(b"other data"))


def test_a_present_file_is_verified_and_never_downloaded_again(tmp_path: Path) -> None:
    (tmp_path / "foods.zip").write_bytes(b"real data")
    result = download_dataset("foods.zip", tmp_path, _sha256(b"real data"))
    assert result == tmp_path / "foods.zip"

    with pytest.raises(DatasetIntegrityError):
        download_dataset("foods.zip", tmp_path, _sha256(b"other data"))


@pytest.fixture
def fake_usda(monkeypatch: pytest.MonkeyPatch) -> Callable[[bytes], dict[str, Any]]:
    """Answers downloads locally, and records how the real client would have been created."""

    def install(body: bytes) -> dict[str, Any]:
        captured: dict[str, Any] = {}
        real_client = httpx2.Client

        def client(**kwargs: Any) -> httpx2.Client:
            captured.update(kwargs)
            transport = httpx2.MockTransport(lambda _: httpx2.Response(200, content=body))
            return real_client(transport=transport)

        monkeypatch.setattr(fdc_bulk.httpx2, "Client", client)
        return captured

    return install


def test_download_stores_a_verified_file(
    tmp_path: Path, fake_usda: Callable[[bytes], dict[str, Any]]
) -> None:
    fake_usda(b"real data")
    path = download_dataset("foods.zip", tmp_path / "raw", _sha256(b"real data"))
    assert path.read_bytes() == b"real data"
    assert list(path.parent.iterdir()) == [path]


def test_a_corrupt_download_leaves_nothing_behind(
    tmp_path: Path, fake_usda: Callable[[bytes], dict[str, Any]]
) -> None:
    fake_usda(b"truncated")
    with pytest.raises(DatasetIntegrityError):
        download_dataset("foods.zip", tmp_path, _sha256(b"real data"))
    assert list(tmp_path.iterdir()) == []


def test_downloads_always_check_certificates(
    tmp_path: Path, fake_usda: Callable[[bytes], dict[str, Any]]
) -> None:
    """Security software can re-sign HTTPS traffic. The fix is trust, never disabling checks."""
    captured = fake_usda(b"real data")
    download_dataset("foods.zip", tmp_path, _sha256(b"real data"))

    context = captured["verify"]
    assert isinstance(context, ssl.SSLContext)
    assert context.verify_mode is ssl.CERT_REQUIRED
    assert context.check_hostname is True
