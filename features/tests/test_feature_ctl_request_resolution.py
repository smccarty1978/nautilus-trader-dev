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
    assert resolved["result"] == "PENDING_PROVIDER_CUTOVER"
    assert resolved["feature"] == "regime_efficiency"
    assert resolved["parameters"] == {"timeframe": "3m", "context": "prior", "bar_state": "completed"}


def test_legacy_alias_and_genuinely_missing_request_are_distinguished():
    legacy = _request("prior_5m_regime_efficiency")
    assert legacy["resolution"] == "legacy_alias"
    missing = _request("new_unsupported_feature")
    assert missing["result"] == "MISSING_CANONICAL_FEATURE"
    assert "canonical_name: new_unsupported_feature" in missing["yaml_template"]
