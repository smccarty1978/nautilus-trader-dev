import json
from pathlib import Path

import pytest

from studies.model_semantics_migration.model_registry import load_registry, resolve_model


def test_direction_semantics_are_opposites():
    for model in load_registry()["models"]:
        if model["prevailing_regime"] == "bullish":
            assert model["target_flip_direction"] == "bearish"
            assert model["trade_direction"] == "short"
            assert "bearish" in model["positive_class_definition"]
            assert "+1" in model["candidate_regime_filter"]
        else:
            assert model["prevailing_regime"] == "bearish"
            assert model["target_flip_direction"] == "bullish"
            assert model["trade_direction"] == "long"
            assert "bullish" in model["positive_class_definition"]
            assert "-1" in model["candidate_regime_filter"]
        assert model["flip_confirmation"] == "confirmed"
        assert model["positive_class_index"] == 1


def test_only_strict_top103_is_production_valid():
    valid = [m["canonical_name"] for m in load_registry()["models"] if m["production_valid"]]
    assert valid == ["BEARISH_FADE_TO_BULLISH_FLIP_TOP103_GBT_V2"]


@pytest.mark.parametrize(
    ("legacy", "canonical"),
    [
        ("legacy_short_model", "BULLISH_FADE_TO_BEARISH_FLIP_TOP25_GBT_V1"),
        ("legacy_long_model", "BEARISH_FADE_TO_BULLISH_FLIP_TOP103_GBT_V2"),
        ("LONG_STRICT_top103_gbt_v2", "BEARISH_FADE_TO_BULLISH_FLIP_TOP103_GBT_V2"),
    ],
)
def test_legacy_alias_resolution(legacy, canonical):
    with pytest.warns(DeprecationWarning):
        assert resolve_model(legacy)["canonical_name"] == canonical


def test_prediction_report_is_bit_exact_when_present():
    path = Path(__file__).parents[1] / "prediction_reproduction_report.json"
    if not path.exists():
        pytest.skip("Run reproduce_predictions.py first")
    report = json.loads(path.read_text())
    assert report["overall_status"] == "PASS"
    assert all(row["max_abs_prediction_diff"] == 0.0 for row in report["models"])
