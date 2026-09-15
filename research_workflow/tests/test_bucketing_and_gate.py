"""chore/bucketing_and_gate: plan-bound gate freshness (A3), observed_seconds (A5), tracker staleness (A2)."""
from __future__ import annotations

import json
from pathlib import Path

from research_workflow.governed_controller_v2 import V2StudyController
from research_workflow.grammar.compiler import compile_study, load_spec

ROOT = Path(__file__).resolve().parents[2]
COMPOSITE = "c" * 64


def _write(path: Path, payload) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _controller(tmp_path: Path) -> V2StudyController:
    c = V2StudyController.__new__(V2StudyController)       # the freshness rules only; no lifecycle, no worktree
    c.study = tmp_path / "s"
    c.work = c.study / "_work" / "controller"
    c._is_collect = lambda: False
    return c


def _fp(plan_sha: str) -> dict:
    return {"compiled_plan": "x", "study_spec": "spec", "plan_spec_sha256": "spec", "plan_sha256": plan_sha,
            "plan_closure_composite": COMPOSITE, "execution_composite": COMPOSITE, "current_execution_composite": COMPOSITE}


def test_a3_plan_only_change_stales_every_plan_bound_gate_and_nothing_closure_bound(tmp_path):
    """Change only outcome.session_end: the closure composite is unchanged, the plan hash is not."""
    spec = load_spec(ROOT / "fixtures" / "parity" / "shape_b" / "study.yaml")
    a = compile_study(spec, repo_root=ROOT)
    spec["outcome"]["session_end"] = "ignore" if spec["outcome"].get("session_end") != "ignore" else "censor"
    b = compile_study(spec, repo_root=ROOT)
    assert a.ok and b.ok, (a.card(), b.card())
    assert a.plan.closure["composite_sha256"] == b.plan.closure["composite_sha256"]
    assert a.plan.plan_sha256 != b.plan.plan_sha256
    old, new = a.plan.plan_sha256, b.plan.plan_sha256

    c = _controller(tmp_path)
    s = c.study
    _write(s / "artifacts/experiment_authorization.json", {})
    _write(s / "audit/frozen_execution_manifest.json", {"plan_sha256": old, "frozen_execution_composite_sha256": COMPOSITE})
    _write(s / "audit/readiness.json", {"overall_status": "PASS", "execution_composite_sha256": COMPOSITE, "plan_sha256": old})
    _write(s / "audit/preflight.json", {"status": "CLEAR", "execution_composite_sha256": COMPOSITE, "plan_sha256": old})
    _write(c.work / "test_summary.json", {"status": "PASS", "execution_composite_sha256": COMPOSITE})
    for name in ("status.json", "contract_status.json"):
        _write(s / "audit" / name, {"verdict": "CLEAR", "audited_execution_composite_sha256": COMPOSITE})
    _write(s / "artifacts/preexec_audit_seal.json", {"composite_seal_hash": "h", "execution_manifest_composite_sha256": COMPOSITE,
                                                    "plan_sha256": old})
    smoke_card = _write(s / "artifacts/smoke_acceptance.json", {"status": "ACCEPTED"})
    c._write_receipt("smoke", {"status": "PASS", "outputs": [smoke_card]}, _fp(old))
    assert json.loads((c.work / "receipts/smoke.json").read_text())["plan_sha256"] == old

    gates = ("prepare", "readiness", "preflight", "tests", "causal_audit", "contract_audit", "seal", "smoke")
    assert {g: c._fresh_stage(g, _fp(old)) for g in gates} == {g: True for g in gates}
    after = {g: c._fresh_stage(g, _fp(new)) for g in gates}
    assert after == {"prepare": False, "readiness": False, "preflight": False, "tests": True, "causal_audit": True,
                     "contract_audit": True, "seal": False, "smoke": False}


def test_a3_receipt_without_a_plan_hash_is_not_current(tmp_path):
    c = _controller(tmp_path)
    out = _write(c.study / "artifacts/x.json", {})
    c._write_receipt("analyze", {"status": "PASS", "outputs": [out]}, _fp("p"))
    path = c.work / "receipts/analyze.json"
    body = json.loads(path.read_text())
    assert c._receipt_current("analyze", _fp("p"))
    body.pop("plan_sha256")
    path.write_text(json.dumps(body), encoding="utf-8")
    assert not c._receipt_current("analyze", _fp("p"))
