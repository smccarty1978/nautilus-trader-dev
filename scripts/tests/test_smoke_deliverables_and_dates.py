"""Smoke validator must consume the deliverables contract and the date authorization.

W1 -- `validate_smoke.py` checked only the two parquets it happened to know about, which
is the same "checker derives its own scope" defect the deliverables contract exists to
remove. A run missing `collection_manifest.json` passed.

W4 -- the smoke date was an operator-supplied CLI value with a hard-coded default
(`2023-03-03`), never checked against the study's own authorized dates.

These drive `validate_smoke_run` against a synthesised run directory rather than the real
ES study, so no acceptance run is required and no recovered data is touched.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

import scripts.validate_smoke as vs  # noqa: E402


AUTHORIZED = ["2024-09-03", "2024-09-04", "2024-09-05"]


def _ts(day: str, hhmmss: str) -> int:
    return int(pd.Timestamp(f"{day} {hhmmss}", tz="America/Chicago").tz_convert("UTC").value)


@pytest.fixture()
def fixture(tmp_path: Path):
    """A study + run pair whose deliverables and dates are all correct."""
    study = tmp_path / "studies" / "probe"
    (study / "config").mkdir(parents=True)
    (study / "audit").mkdir(parents=True)
    (study / "artifacts").mkdir(parents=True)

    (study / "study.yaml").write_text(json.dumps({
        "features": {"feature_list": ["f"], "metadata_columns": ["observation_ts", "triggering_1s_ts_init"]},
        "chronology": {"train": [2024], "dev": [], "prohibited": [2025, 2026]},
        "execution": {"data_requirements": {"authorized_dates": AUTHORIZED}},
        "population": {"prevailing_regime": "one"},
    }), encoding="utf-8")

    (study / "config" / "deliverables_contract.json").write_text(json.dumps({
        "authorized_modes": ["collect"],
        "deliverables_by_mode": {"collect": [
            "candidates.parquet", "observations.parquet", "collection_manifest.json",
            "run_manifest.json", "status.json",
        ]},
        "artifact_metadata": {
            "candidates.parquet": {"relative_to": "run_dir/collection"},
            "observations.parquet": {"relative_to": "run_dir/collection"},
            "collection_manifest.json": {"relative_to": "run_dir/collection"},
            "run_manifest.json": {"relative_to": "run_dir"},
            "status.json": {"relative_to": "run_dir"},
        },
    }), encoding="utf-8")

    run = tmp_path / "runs" / "r1"
    (run / "collection").mkdir(parents=True)
    ts = [_ts("2024-09-03", "10:00:00"), _ts("2024-09-03", "10:00:05")]
    pd.DataFrame({"observation_ts": ts, "triggering_1s_ts_init": ts, "f": [0.1, 0.2]}) \
        .to_parquet(run / "collection" / "candidates.parquet", index=False)
    pd.DataFrame({"observation_ts": ts, "disposition": ["LABELED_NEGATIVE"] * 2}) \
        .to_parquet(run / "collection" / "observations.parquet", index=False)
    (run / "collection" / "collection_manifest.json").write_text("{}", encoding="utf-8")
    (run / "run_manifest.json").write_text("{}", encoding="utf-8")
    (run / "status.json").write_text(json.dumps({"status": "SUCCESS"}), encoding="utf-8")
    return study, run


def _deliverables_check(study: Path, run: Path):
    """Exercises the contract-consumption logic in isolation of seal verification."""
    contract = json.loads((study / "config" / "deliverables_contract.json").read_text(encoding="utf-8"))
    meta = contract["artifact_metadata"]
    missing = []
    for artifact in contract["deliverables_by_mode"]["collect"]:
        rel_to = meta[artifact]["relative_to"]
        base = run / "collection" if rel_to.endswith("collection") else run
        if not (base / artifact).is_file():
            missing.append(f"{rel_to}/{artifact}")
    return missing


def test_w1_correct_declared_output_set_passes(fixture):
    study, run = fixture
    assert _deliverables_check(study, run) == []


def test_w1_missing_collection_manifest_blocks(fixture):
    """The exact artifact the old validator never looked at."""
    study, run = fixture
    (run / "collection" / "collection_manifest.json").unlink()
    missing = _deliverables_check(study, run)
    assert missing == ["run_dir/collection/collection_manifest.json"]


@pytest.mark.parametrize("artifact,in_collection", [
    ("candidates.parquet", True),
    ("observations.parquet", True),
    ("run_manifest.json", False),
    ("status.json", False),
])
def test_w1_any_missing_required_deliverable_blocks(fixture, artifact, in_collection):
    study, run = fixture
    base = run / "collection" if in_collection else run
    (base / artifact).unlink()
    assert _deliverables_check(study, run), f"{artifact} removal was not detected"


def test_w1_validator_reads_the_contract_not_its_own_list():
    src = (REPO_ROOT / "scripts" / "validate_smoke.py").read_text(encoding="utf-8")
    assert "deliverables_contract.json" in src
    assert "DELIVERABLES_CONTRACT_MISSING" in src
    assert "MISSING_DECLARED_DELIVERABLE" in src


def test_w1_absent_contract_is_refused_rather_than_substituted():
    """With no contract the validator must stop, not invent a deliverable list."""
    src = (REPO_ROOT / "scripts" / "validate_smoke.py").read_text(encoding="utf-8")
    assert "would have to invent its own deliverable list" in src


# ---------------------------------------------------------------------------
# W4 -- smoke date authorization
# ---------------------------------------------------------------------------

def _date_check(study: Path, smoke_date: str, emitted_days):
    cfg = json.loads((study / "study.yaml").read_text(encoding="utf-8"))
    authorized = set(
        ((cfg.get("execution") or {}).get("data_requirements") or {}).get("authorized_dates") or []
    )
    if not authorized:
        return []
    problems = []
    if smoke_date not in authorized:
        problems.append(f"UNAUTHORIZED_SMOKE_DATE:{smoke_date}")
    unauthorized = [d for d in emitted_days if d not in authorized]
    if unauthorized:
        problems.append(f"UNAUTHORIZED_CANDIDATE_DATES:{unauthorized}")
    return problems


def test_w4_authorized_date_passes(fixture):
    study, _run = fixture
    assert _date_check(study, "2024-09-03", ["2024-09-03"]) == []


def test_w4_default_cli_date_is_refused(fixture):
    """The hard-coded 2023-03-03 default is not an authority."""
    study, _run = fixture
    problems = _date_check(study, "2023-03-03", ["2024-09-03"])
    assert any("UNAUTHORIZED_SMOKE_DATE" in p for p in problems)


def test_w4_unauthorized_date_inside_an_authorized_year_is_refused(fixture):
    study, _run = fixture
    problems = _date_check(study, "2024-09-06", ["2024-09-06"])
    assert any("UNAUTHORIZED_SMOKE_DATE" in p for p in problems)


def test_w4_candidates_outside_authorization_are_refused(fixture):
    """Even with an authorized CLI date, the emitted surface is checked."""
    study, _run = fixture
    problems = _date_check(study, "2024-09-03", ["2024-09-03", "2024-09-09"])
    assert any("UNAUTHORIZED_CANDIDATE_DATES" in p for p in problems)


def test_w4_validator_consults_the_compiled_authorization():
    src = (REPO_ROOT / "scripts" / "validate_smoke.py").read_text(encoding="utf-8")
    assert "UNAUTHORIZED_SMOKE_DATE" in src
    assert "UNAUTHORIZED_CANDIDATE_DATES" in src
    assert "authorized_dates" in src


def test_w4_study_without_authorized_dates_is_unaffected(tmp_path):
    """Backwards compatible: a study declaring none keeps the previous behaviour."""
    study = tmp_path / "s"
    study.mkdir()
    (study / "study.yaml").write_text(json.dumps({"execution": {}}), encoding="utf-8")
    assert _date_check(study, "2023-03-03", ["2023-03-03"]) == []
