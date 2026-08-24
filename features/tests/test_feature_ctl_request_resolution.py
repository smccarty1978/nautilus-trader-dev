from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _request(name: str) -> dict:
    completed = subprocess.run(
        [sys.executable, "scripts/feature_ctl.py", "check", "--request", name],
        cwd=ROOT, check=True, capture_output=True, text=True,
    )
    return json.loads(completed.stdout)["requests"][0]


def test_new_timeframe_alias_resolves_to_existing_regime_building_block():
    resolved = _request("prior_3m_regime_efficiency")
    assert resolved["result"] == "EXISTING_CANONICAL_FEATURE"
    assert resolved["feature"] == "regime_efficiency"
    assert resolved["parameters"] == {"timeframe": "3m", "context": "prior", "bar_state": "completed"}
    # Cutover makes the canonical provider active; a recognised instance no
    # longer carries a staging-only execution status.
    assert "execution_status" not in resolved


def test_legacy_alias_and_genuinely_missing_request_are_distinguished():
    legacy = _request("prior_5m_regime_efficiency")
    assert legacy["resolution"] == "legacy_migration_guidance"
    assert legacy["result"] == "LEGACY_ALIAS"
    missing = _request("new_unsupported_feature")
    assert missing["result"] == "MISSING_CANONICAL_FEATURE"
    assert "canonical_name: new_unsupported_feature" in missing["yaml_template"]


def test_any_registered_physical_alias_is_normalized_before_a_new_definition_is_suggested():
    resolved = _request("arrival_vel_20s")
    assert resolved["result"] == "LEGACY_ALIAS"
    assert resolved["feature"] == "arrival_velocity"
    assert resolved["parameters"] == {"lookback": 20, "input_timeframe": "1s", "bar_state": "completed"}
    assert resolved["resolution"] == "legacy_migration_guidance"
