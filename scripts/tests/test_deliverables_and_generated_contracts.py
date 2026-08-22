"""Deliverables ownership and generated-contract integrity (Findings F1, F2).

F1 -- the SPEC declared ``candidates.parquet, scores.parquet, triggers.parquet,
metrics.json`` for a study that only ran **collect** mode. Collect mode cannot produce the
last three at all, and the one artifact carrying the study's labels
(``observations.parquet``) was not declared. The contract-checker passed regardless: with
no machine-readable deliverable set to consume, it assembled its own checklist and
verified the implementation against that. A check that derives its own scope cannot detect
scope loss.

F2 -- the generated study tests compared baked literals to identical baked literals::

    assert "nautilustrader" == "nautilustrader"
    assert expected_sha256 == "f5cddfd9..."      # both sides the same literal

They passed unconditionally and would have kept passing if every artifact in the study had
been deleted.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]

from research.engines.deliverables_engine import (  # noqa: E402
    KNOWN_ARTIFACT_PRODUCERS,
    MODE_DELIVERABLES,
    DeliverableContractError,
    artifact_modes,
    compile_deliverables_contract,
    modes_for_operation,
    required_deliverables_for_mode,
)


# ---------------------------------------------------------------------------
# F1 -- deliverables are mode-partitioned and reachable
# ---------------------------------------------------------------------------

def test_collect_mode_declares_only_what_collect_produces():
    """F1.1 -- the historical four-item list is not what collect mode emits."""
    c = compile_deliverables_contract(["collect"])
    declared = set(required_deliverables_for_mode(c, "collect"))

    assert "candidates.parquet" in declared
    assert "observations.parquet" in declared, (
        "the observation surface carries the labels and is contractually required"
    )
    for unproducible in ("scores.parquet", "triggers.parquet", "metrics.json"):
        assert unproducible not in declared, (
            f"{unproducible} cannot be produced by collect mode and must not be declared"
        )


def test_declaring_an_unreachable_deliverable_is_refused_at_compile_time():
    """F1.2 -- the earliest deterministic stage refuses it, not a post-run discovery."""
    with pytest.raises(DeliverableContractError, match="UNREACHABLE_DELIVERABLE"):
        compile_deliverables_contract(
            ["collect"],
            declared_overrides={"collect": ["candidates.parquet", "scores.parquet"]},
        )


def test_declaring_an_artifact_with_no_producer_is_refused():
    with pytest.raises(DeliverableContractError, match="UNKNOWN_DELIVERABLE"):
        compile_deliverables_contract(
            ["collect"], declared_overrides={"collect": ["imaginary.parquet"]}
        )


def test_unknown_mode_is_refused():
    with pytest.raises(DeliverableContractError, match="UNKNOWN_MODE"):
        compile_deliverables_contract(["teleport"])


def test_unauthorized_mode_cannot_be_queried():
    """An artifact belonging to a mode the study may not run is out of scope, not missing."""
    c = compile_deliverables_contract(["collect"])
    with pytest.raises(DeliverableContractError, match="MODE_NOT_AUTHORIZED"):
        required_deliverables_for_mode(c, "analysis")


def test_every_declared_artifact_maps_to_its_own_mode():
    """The producer registry and the per-mode lists cannot disagree."""
    for mode, artifacts in MODE_DELIVERABLES.items():
        for a in artifacts:
            assert a in KNOWN_ARTIFACT_PRODUCERS, f"{a} has no producer"
            assert mode in artifact_modes(a), (
                f"{a} is listed under {mode} but produced by {artifact_modes(a)}"
            )


def test_modes_are_derived_from_the_operation_kind():
    """Modes come from the operation, not from a new spec field that would rehash studies."""
    assert modes_for_operation("train_evaluate") == ["collect"]
    assert modes_for_operation("unknown_future_kind") == ["collect"]


def test_contract_records_a_producer_and_location_for_each_artifact():
    c = compile_deliverables_contract(["collect"])
    for a in c["deliverables_by_mode"]["collect"]:
        meta = c["artifact_metadata"][a]
        assert meta["producer"]
        assert meta["relative_to"]


# ---------------------------------------------------------------------------
# F2 -- generated contract tests load artifacts and can actually fail
# ---------------------------------------------------------------------------

STUDY_YAML = """
study:
  id: f2_generated_contract_probe
  type: flip_prediction
  risk_tier: 2
  description: Fixture study used to prove generated contract tests detect drift.
operation:
  kind: train_evaluate
  target_metric: roc_auc
instrument:
  symbol: ES
  venue: XCME
population:
  type: regime_state
  prevailing_regime: both
  session: RTH
target:
  type: flip
  event: prevailing_1m_regime_transition
  direction: both
  horizon_seconds: 300
features:
  source: verified_registry_numeric_universe
  feature_list:
  - latest_1m_wick_imbalance
  timing_contract: verified
model:
  mode: scoring
  family: HistGradientBoostingClassifier
chronology:
  train: [2024]
  dev: []
  prohibited: [2025, 2026]
execution:
  runtime: nautilustrader
  progress_seconds: 60
  bounded: true
"""


@pytest.fixture(scope="module")
def generated_study(tmp_path_factory):
    """Scaffolds a real study via the factory so the generated tests are the real ones."""
    out = tmp_path_factory.mktemp("f2_studies")
    cfg = out / "study.yaml"
    cfg.write_text(STUDY_YAML, encoding="utf-8")

    res = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "create_study.py"),
         "--config", str(cfg), "--out-dir", str(out)],
        capture_output=True, text=True, cwd=str(REPO_ROOT),
    )
    study_dir = out / "f2_generated_contract_probe"
    if res.returncode != 0 or not study_dir.exists():
        pytest.fail(f"create_study failed: {res.stdout}\n{res.stderr}")
    return study_dir


def _run_generated_tests(study_dir: Path):
    return subprocess.run(
        [sys.executable, "-m", "pytest", str(study_dir / "tests" / "test_study_contracts.py"),
         "-q", "-p", "no:cacheprovider"],
        capture_output=True, text=True, cwd=str(REPO_ROOT),
    )


def test_generated_tests_contain_no_literal_self_comparison(generated_study: Path):
    """F2.1 -- the tautology shapes are gone from the generator's output."""
    src = (generated_study / "tests" / "test_study_contracts.py").read_text(encoding="utf-8")
    assert 'assert "nautilustrader" == "nautilustrader"' not in src
    # No assertion may compare a value to itself.
    for line in src.splitlines():
        s = line.strip()
        if s.startswith("assert ") and " == " in s:
            lhs, rhs = s[len("assert "):].split(" == ", 1)
            rhs = rhs.split(",")[0].strip()
            assert lhs.strip() != rhs, f"self-comparing assertion: {s}"


def test_generated_tests_load_real_artifacts(generated_study: Path):
    """F2.2 -- the tests read from disk, so deleting an artifact breaks them."""
    src = (generated_study / "tests" / "test_study_contracts.py").read_text(encoding="utf-8")
    assert "read_text" in src
    assert "compiled_study.json" in src
    assert "config" in src


def test_generated_tests_pass_on_the_freshly_compiled_study(generated_study: Path):
    res = _run_generated_tests(generated_study)
    assert res.returncode == 0, f"generated tests failed on a clean study:\n{res.stdout}\n{res.stderr}"


@pytest.mark.parametrize("mutation", ["feature_list", "horizon", "session", "chronology"])
def test_generated_tests_detect_artifact_drift(generated_study, tmp_path, mutation):
    """F2.3 -- mutation regression: changing one authority makes a generated test fail.

    This is the property the old generator lacked entirely. Each mutation edits exactly one
    artifact and leaves the others alone, so a passing suite would mean the tests are not
    reading the artifact they claim to bind.
    """
    import shutil

    work = tmp_path / f"mutant_{mutation}"
    shutil.copytree(generated_study, work)
    cfg_dir = work / "config"

    if mutation == "feature_list":
        # Feature hash no longer matches the ordered list it is derived from.
        fc = json.loads((cfg_dir / "feature_contract.json").read_text(encoding="utf-8"))
        fc["feature_list"] = ["some_other_feature"]
        (cfg_dir / "feature_contract.json").write_text(json.dumps(fc, indent=2), encoding="utf-8")
    elif mutation == "horizon":
        tc = json.loads((cfg_dir / "target_contract.json").read_text(encoding="utf-8"))
        tc["horizon_seconds"] = 999
        (cfg_dir / "target_contract.json").write_text(json.dumps(tc, indent=2), encoding="utf-8")
    elif mutation == "session":
        pc = json.loads((cfg_dir / "population_contract.json").read_text(encoding="utf-8"))
        pc["session"] = "ETH"
        (cfg_dir / "population_contract.json").write_text(json.dumps(pc, indent=2), encoding="utf-8")
    elif mutation == "chronology":
        ec = json.loads((cfg_dir / "execution_contract.json").read_text(encoding="utf-8"))
        ec["chronology"]["train"] = [2019]
        (cfg_dir / "execution_contract.json").write_text(json.dumps(ec, indent=2), encoding="utf-8")

    res = _run_generated_tests(work)
    assert res.returncode != 0, (
        f"generated tests passed despite a '{mutation}' mutation -- they are not reading "
        f"the artifact they claim to bind:\n{res.stdout}"
    )


def test_generated_tests_detect_a_deleted_config_artifact(generated_study, tmp_path):
    """Deleting an authority must break the suite, not silently skip it."""
    import shutil

    work = tmp_path / "mutant_deleted"
    shutil.copytree(generated_study, work)
    (work / "config" / "target_contract.json").unlink()
    assert _run_generated_tests(work).returncode != 0


def test_generated_study_spec_md_matches_the_deliverables_contract(generated_study: Path):
    """F1.3 -- SPEC prose is rendered from the contract, so the two cannot drift."""
    dc = json.loads((generated_study / "config" / "deliverables_contract.json").read_text(encoding="utf-8"))
    spec_md = (generated_study / "SPEC.md").read_text(encoding="utf-8")
    for artifacts in dc["deliverables_by_mode"].values():
        for a in artifacts:
            assert a in spec_md
    for unproducible in ("scores.parquet", "triggers.parquet", "metrics.json"):
        assert unproducible not in spec_md, (
            f"SPEC still declares {unproducible}, which collect mode cannot produce"
        )


def test_compile_study_materializes_standalone_deliverables_contract(tmp_path: Path):
    """The canonical compile stage, not a hand edit, creates contract authority."""
    import shutil
    from scripts.compile_study import compile_study

    source = REPO_ROOT / "studies" / "Codex_clean_maturity_flip_rolling_5m_productivity"
    study = tmp_path / source.name
    shutil.copytree(source, study)
    contract_path = study / "config" / "deliverables_contract.json"
    contract_path.unlink(missing_ok=True)

    assert compile_study(study) == 0
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    assert contract == compile_deliverables_contract(["collect"])
