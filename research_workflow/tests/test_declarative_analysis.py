"""A study whose ANALYSIS is declared, not scripted.

Before this, the v2 analyze stage could emit only row counts, disposition counts and
roc_auc/pr_auc/brier -- any other statistic meant a study-local pandas script, which the
operating manual prohibits. These tests drive a train-only diagnostic study (no model, no
protected OOS) through the whole controller on the golden synthetic fixture and prove the
declared analysis artifacts are produced by composed registered operations with zero study
Python, and that a malformed pipeline is a typed capability gap rather than a runtime crash
half-way through writing artifacts.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "fixtures" / "golden"
NS = 1_000_000_000

ANALYSIS = {
    "source": "train",
    "steps": [
        {"id": "anchors", "op": "analysis.anchor.first_threshold_crossing",
         "params": {"by": {"column": "regime_direction",
                           "cases": {1: {"value": "f_close", "threshold": 100.5, "levels": {"high": 101.0}},
                                     -1: {"value": "f_close", "threshold": 100.5, "levels": {"high": 101.0}}}},
                    "group_by": ["regime_start_ns"], "order_by": "observation_ts",
                    "terminal": {"columns": ["flip_ts", "session_close_ts"], "reduce": "min", "unit": "ns"}}},
        {"id": "incidence", "op": "analysis.incidence.cumulative", "rows": "anchors",
         "params": {"horizons": [30, 60, 120], "resolved_column": "target_flip_within_horizon",
                    "duration_column": "time_to_flip_seconds", "observed_seconds_column": "observed_seconds",
                    "strata": ["regime_direction"]}},
        {"id": "decomposition", "op": "analysis.decomposition.buckets", "rows": "anchors",
         "params": {"resolved_column": "target_flip_within_horizon", "duration_column": "time_to_flip_seconds",
                    "observed_seconds_column": "observed_seconds", "negative_after_seconds": 60,
                    "buckets": [{"id": "late_61_120", "gt": 60, "lte": 120},
                                {"id": "no_event", "unresolved": True}]}},
        {"id": "controls", "op": "analysis.control.cell_matched", "inputs": {"anchors": "anchors"},
         "params": {"by": {"column": "regime_direction",
                           "cases": {1: {"value": "f_close", "threshold": 100.5}, -1: {"value": "f_close", "threshold": 100.5}}},
                    "group_by": ["regime_start_ns"], "strata": ["regime_direction"],
                    "order_by": "observation_ts", "min_n": 1}},
        {"id": "path", "op": "analysis.path.anchored_offsets", "inputs": {"anchors": "anchors"},
         "params": {"by": {"column": "regime_direction",
                           "cases": {1: {"value": "f_close", "threshold": 100.5, "levels": {"high": 101.0}},
                                     -1: {"value": "f_close", "threshold": 100.5, "levels": {"high": 101.0}}}},
                    "group_by": ["regime_start_ns"], "order_by": "observation_ts",
                    "offsets": [5, 10, 15], "max_offset_seconds": 60,
                    "terminal_column": "terminal_ts", "levels": ["high"], "time_unit": "ns"}},
        {"id": "subtypes", "op": "analysis.classify.precedence", "rows": "path",
         "params": {"output_column": "subtype", "rules": [
             {"label": "PATH_CENSORED", "when": [["path_censored", "eq", True]]},
             {"label": "COLLAPSED", "when": [["fell_below", "eq", True]]},
             {"label": "HELD", "when": []}]}},
    ],
    "artifacts": [
        {"name": "probe_incidence.json", "source": "incidence", "kind": "json"},
        {"name": "probe_decomposition.json", "source": "decomposition", "kind": "json"},
        {"name": "probe_controls.json", "source": "controls", "kind": "json"},
        {"name": "probe_subtypes.json", "source": "subtypes", "kind": "json"},
        {"name": "probe_anchors.parquet", "source": "anchors", "kind": "frame"},
        {"name": "probe_score_path.parquet", "source": "path", "kind": "observations"},
    ],
}


@pytest.fixture(scope="module")
def synthetic_bars():
    subprocess.run([sys.executable, str(GOLDEN / "build_golden_fixture.py")], check=True, cwd=str(ROOT), capture_output=True)
    from research_workflow.host.interfaces import BarView
    bars = [BarView(**b) for b in json.loads((GOLDEN / "bars.json").read_text(encoding="utf-8"))]
    return bars, json.loads((GOLDEN / "expected.json").read_text(encoding="utf-8"))


def _study(tmp_path: Path, analysis) -> Path:
    body = yaml.safe_load((GOLDEN / "study_flip.yaml").read_text(encoding="utf-8"))
    body["study"]["id"] = "declarative_analysis_probe"
    body["chronology"] = {"train": [2030], "dev": [], "prohibited": [], "authorized_dates": ["2030-01-01"]}
    body["analysis"] = analysis
    study = tmp_path / "studies" / "declarative_analysis_probe"
    study.mkdir(parents=True, exist_ok=True)
    (study / "study.yaml").write_text(yaml.safe_dump(body, sort_keys=False), encoding="utf-8")
    return study


def _write_audit(study: Path, kind: str) -> Path:
    frozen = json.loads((study / "audit" / "frozen_execution_manifest.json").read_text())["frozen_execution_composite_sha256"]
    name = "pass_01.md" if kind == "causal" else "contract_pass_01.md"
    block = {"verdict": "CLEAR", "audit_type": kind, "study": study.name, "auditor": f"{kind}-probe",
             "audited_execution_composite_sha256": frozen, "critical": 0, "warning": 0, "note": 1}
    p = study / "audit" / name
    p.write_text(f"# {kind} audit\n\n<!-- AUDIT_SUMMARY_V2_START -->\n{json.dumps(block)}\n<!-- AUDIT_SUMMARY_V2_END -->\n", encoding="utf-8")
    return p


def test_a_train_only_diagnostic_runs_compile_to_close_and_writes_its_declared_artifacts(tmp_path, synthetic_bars, monkeypatch):
    import pandas as pd
    from research_workflow.governed_controller_v2 import V2StudyController
    from research_workflow.lifecycle_v2 import V2Options, ingest_audit_report
    from research_workflow.tests.synthetic_primitives import SYNTHETIC_BINDINGS
    bars, expected = synthetic_bars
    study = _study(tmp_path, ANALYSIS)
    session = {"kind": "calendar", "session": "RTH", "rows": [[a * NS, b * NS] for a, b in expected["sessions"]]}
    opts = V2Options(execute=True, smoke_date="2030-01-01", datasets_dir=GOLDEN / "datasets", extra_bindings=SYNTHETIC_BINDINGS,
                     bar_source=lambda s, e: bars, session_table_spec=session, in_process_partitions=True,
                     closure={"outcome": "DECLARATIVE_ANALYSIS_PROVEN", "terminal_decision": "PLATFORM_PROBE"},
                     model_root=tmp_path / "model_store")
    monkeypatch.setattr(V2StudyController, "_worktree",
                        lambda self: {"path": str(ROOT), "branch": "test", "head": "0" * 40, "dirty_paths": [], "unsafe_dirty_paths": []})
    ctl = lambda: V2StudyController(study, options=opts, repo_root=ROOT)

    ctl().run(through="tests")
    ingest_audit_report(study, "causal", _write_audit(study, "causal"))
    ingest_audit_report(study, "contract", _write_audit(study, "contract"))
    card = ctl().run(through="close")
    assert card["STATUS"] != "BLOCKED", card

    # no protected period existed, and the lifecycle said so rather than pretending otherwise
    freeze = json.loads((study / "artifacts" / "train_experiment_freeze.json").read_text(encoding="utf-8"))
    assert freeze["status"] == "NO_PROTECTED_OOS" and freeze["protected_oos"] is False

    for name in [a["name"] for a in ANALYSIS["artifacts"]]:
        assert (study / "artifacts" / name).is_file(), name
    incidence = json.loads((study / "artifacts" / "probe_incidence.json").read_text(encoding="utf-8"))
    assert incidence["eligibility_rule"] == "resolved_at_or_before_h OR observed_for_at_least_h"
    assert set(incidence["populations"]) >= {"pooled"}
    anchors = pd.read_parquet(study / "artifacts" / "probe_anchors.parquet")
    assert len(anchors) > 0
    assert (anchors["observed_seconds"] >= 0).all()
    assert not anchors.duplicated(["regime_start_ns"]).any()      # one anchor per group, always
    subtypes = json.loads((study / "artifacts" / "probe_subtypes.json").read_text(encoding="utf-8"))
    assert subtypes["unclassified"] == 0                          # the catch-all rule really catches all
    assert sum(subtypes["counts"].values()) == len(anchors)

    summary = json.loads((study / "artifacts" / "experiment_analysis_v2.json").read_text(encoding="utf-8"))
    lineage = summary["declared_analysis"]
    assert lineage["source"] == "train" and lineage["years"] == [2030]
    assert lineage["ops"] == sorted({s["op"] for s in ANALYSIS["steps"]})
    assert len(lineage["artifacts"]) == len(ANALYSIS["artifacts"])
    assert all(a["sha256"] for a in lineage["artifacts"])
    assert lineage["analysis_identity_sha256"]

    from research_workflow.policy import scan_study_python
    assert scan_study_python(study) == []                          # zero study Python, still


@pytest.mark.parametrize("mutate,where", [
    (lambda a: a["steps"][0].__setitem__("op", "analysis.nope"), "analysis.steps[0].op"),
    (lambda a: a["steps"][1].__setitem__("rows", "path"), "analysis.steps[1].rows"),          # forward reference
    (lambda a: a["steps"][3].__setitem__("inputs", {}), "analysis.steps[3].inputs"),          # missing declared input
    (lambda a: a["artifacts"][0].__setitem__("source", "nope"), "analysis.artifacts[0].source"),
    (lambda a: a["artifacts"][0].__setitem__("name", "../escape.json"), "analysis.artifacts[0].name"),
    (lambda a: a.__setitem__("artifacts", []), "analysis.artifacts"),
    (lambda a: a.__setitem__("source", "oos"), "analysis.source"),                            # no dev years declared
])
def test_a_malformed_pipeline_is_a_typed_gap_at_compile_time(tmp_path, mutate, where):
    import copy
    from research_workflow.grammar.compiler import compile_study, load_spec
    from research_workflow.tests.synthetic_primitives import SYNTHETIC_BINDINGS
    analysis = copy.deepcopy(ANALYSIS)
    mutate(analysis)
    out = compile_study(load_spec(_study(tmp_path, analysis)), repo_root=ROOT,
                        datasets_dir=GOLDEN / "datasets", extra_bindings=SYNTHETIC_BINDINGS)
    assert not out.ok
    assert where in {g["where"] for g in out.gaps.to_dict()["gaps"]}, out.card()
