import unicodedata

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.domain.text import normalize_name, slugify


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Kung Pao Chicken", "kung pao chicken"),
        ("  Crème   Brûlée ", "creme brulee"),
        ("Bibimbap, Korean", "bibimbap korean"),
        ("Soy sauce (shoyu)", "soy sauce shoyu"),
        ("\uff2d\uff29\uff33\uff2f", "miso"),
        ("jalapeño", "jalapeno"),
    ],
)
def test_latin_names_fold_case_accents_width_and_punctuation(raw: str, expected: str) -> None:
    assert normalize_name(raw) == expected


@pytest.mark.parametrize(
    "name",
    [
        "麻婆豆腐",
        "鹹鴨蛋",
        "김치",
        "마파두부",
        "ビリヤニ",
        "キムチ",
        "がんもどき",
        "बिरयानी",
        "किमची",
    ],
)
def test_other_scripts_keep_every_letter_and_mark(name: str) -> None:
    assert normalize_name(name) == unicodedata.normalize("NFKC", name)


def test_japanese_voicing_marks_still_distinguish_words() -> None:
    assert normalize_name("がん") != normalize_name("かん")


def test_hindi_vowel_signs_are_not_dropped() -> None:
    assert normalize_name("बिरयानी") != "बरयन"


def test_slug_uses_hyphens() -> None:
    assert slugify("Bibimbap, Korean") == "bibimbap-korean"


@given(st.text())
def test_normalization_is_idempotent(value: str) -> None:
    once = normalize_name(value)
    assert normalize_name(once) == once
