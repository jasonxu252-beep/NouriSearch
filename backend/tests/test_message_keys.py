"""Conclusions reach the page as message keys, so every key a rule can send needs a template."""

import json
import re
from pathlib import Path

from app.domain.rules import percent_daily_value

ROOT = Path(__file__).resolve().parents[2]
CATALOG = json.loads((ROOT / "frontend" / "src" / "i18n" / "en.json").read_text(encoding="utf-8"))


def test_every_conclusion_the_rule_can_send_has_a_template() -> None:
    source = Path(percent_daily_value.__file__).read_text(encoding="utf-8")
    keys = set(re.findall(r'"(conclusion\.[a-z_.]+)"', source))
    reasons = set(re.findall(r'could_not_evaluate\("([a-z_]+)"', source))
    expected = {
        "conclusion.high_percent_daily_value",
        "conclusion.high_percent_daily_value.lower_bound",
        "conclusion.not_high_percent_daily_value",
        "conclusion.could_not_evaluate.no_value",
        "conclusion.could_not_evaluate.no_daily_value",
        "conclusion.could_not_evaluate.lower_bound",
    }
    assert keys <= expected
    assert {f"conclusion.could_not_evaluate.{reason}" for reason in reasons} <= expected
    assert expected <= set(CATALOG)


def test_every_template_receives_the_parameters_it_uses() -> None:
    for key, template in CATALOG.items():
        if key.startswith("conclusion."):
            used = set(re.findall(r"\{(\w+)\}", template))
            assert used <= {"serving", "percent", "threshold"}, key
