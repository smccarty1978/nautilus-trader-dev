"""Test support for the Research Supervisor black-box proof (packet section 8): no data replay, no model tokens.

* ``python research_workflow/tests/supervisor_support.py worker <packet.md>`` -- the ``scripted`` provider's worker: reads the
  packet, performs the role's deterministic stand-in action on the SYNTHETIC study (golden fixture) and writes the result
  card THROUGH THE CLI (``research study result``), exactly as a real worker would.
* ``python research_workflow/tests/supervisor_support.py controller --study <dir> --through <stage> ...`` -- the controller
  job for a synthetic study: the real :class:`V2StudyController` with the golden synthetic bindings (the same options
  ``test_lifecycle_v2`` uses), run as a detached subprocess by the supervisor.
* ``python research_workflow/tests/supervisor_support.py merge_under_lock --repo <dir> --branch <b>`` -- the multiprocess
  main-merge lock race helper.
* :func:`make_repo` -- a throwaway canonical repo + machine-local config for one test.

Scenario knobs come from ``NT_SUP_TEST_PLAN`` (JSON): ``gap_first`` (first design run emits a MISSING_CAPABILITY handoff),
``semantic_first`` (first design run stops with SCIENTIFIC_SEMANTIC_DECISION_REQUIRED until a USER_DECISION answer exists),
``auto_merge`` (declare autonomy_decisions.platform_merge: auto_if_green), ``worker_sleep_s`` (delay before acting),
``declare_vocab`` (the design worker declares ``terminal_decisions: {PLATFORM_V2_FLOW_PROVEN: ...}`` so the closure vocabulary is
enforced), ``undeclared_decision`` (the analysis worker names a terminal_decision outside that vocabulary).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "fixtures" / "golden"
NS = 1_000_000_000
CAPABILITY_MARKER = "research_workflow/host/triggers.py"


def _git(args: List[str], cwd: Path) -> str:
    r = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed in {cwd}: {r.stderr.strip()[:300]}")
    return r.stdout.strip()


def _commit_all(wt: Path, msg: str) -> str:
    _git(["add", "-A"], wt)
    if _git(["status", "--porcelain"], wt):
        _git(["commit", "-q", "-m", msg], wt)
    return _git(["rev-parse", "HEAD"], wt)


def compiling_spec(study_id: str) -> str:
    spec = (GOLDEN / "study_barrier.yaml").read_text(encoding="utf-8")
    spec = spec.replace("id: golden_barrier", f"id: {study_id}").replace("chronology: {train: [2030], dev: [], prohibited: []}",
                                                                          "chronology: {train: [2029, 2030], dev: [2031], prohibited: [], authorized_dates: ['2030-01-01']}")
    return spec.replace("model: none", "model:\n  family: lightgbm\n  params: {n_estimators: 20, max_depth: 2, num_leaves: 4, learning_rate: 0.1, verbosity: -1}\n"
                                       "  validation: {protocol: model_selection.random, tuning_years: [2029, 2030], final_train_validation_years: []}")


def gap_spec(study_id: str) -> str:
    return (GOLDEN / "study_add.yaml").read_text(encoding="utf-8").replace("id: golden_add", f"id: {study_id}")


def _plan() -> Dict[str, Any]:
    try:
        return json.loads(os.environ.get("NT_SUP_TEST_PLAN") or "{}")
    except ValueError:
        return {}


def _result(packet_path: Path, cwd: Path, *args: str) -> None:
    cmd = [sys.executable, str(ROOT / "scripts" / "research.py"), "study", "result", "--packet", str(packet_path), *args]
    r = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, encoding="utf-8", errors="replace")
    sys.stdout.write(r.stdout); sys.stderr.write(r.stderr)
    if r.returncode != 0:
        raise SystemExit(r.returncode)


def _compile(study_dir: Path):
    from research_workflow.grammar import compile_study, load_spec
    from research_workflow.tests.synthetic_primitives import SYNTHETIC_BINDINGS
    return compile_study(load_spec(study_dir), repo_root=ROOT, datasets_dir=GOLDEN / "datasets", extra_bindings=SYNTHETIC_BINDINGS)


def cmd_worker(ns: argparse.Namespace) -> int:
    from research_workflow.supervisor.packets import read_packet
    packet_path = Path(ns.packet)
    packet = read_packet(packet_path)
    plan = _plan()
    if plan.get("worker_sleep_s"):
        time.sleep(float(plan["worker_sleep_s"]))
    stype = packet["session_type"]; study_dir = Path(packet["study_dir"]); wt = Path(packet["expected_worktree"]); sid = packet["study_id"]
    if stype == "STUDY_DESIGN_COMPILE":
        answers = sorted((study_dir / "_work" / "handoff").glob("USER_DECISION_*.json")) if (study_dir / "_work" / "handoff").is_dir() else []
        if plan.get("semantic_first") and not answers:
            _result(packet_path, wt, "--status", "BLOCKED", "--blocker-code", "SCIENTIFIC_SEMANTIC_DECISION_REQUIRED",
                    "--notes", "direction convention for the flip target is not declared and no autonomy policy covers it")
            return 0
        if plan.get("auto_merge"):
            dec = study_dir / "research_decision.yaml"
            text = dec.read_text(encoding="utf-8")
            if "platform_merge:" not in text:
                dec.write_text(text.rstrip("\n") + "\n  platform_merge: auto_if_green\n", encoding="utf-8")
        if plan.get("declare_vocab"):
            dec = study_dir / "research_decision.yaml"
            text = dec.read_text(encoding="utf-8")
            if "terminal_decisions: {}" in text:
                dec.write_text(text.replace("terminal_decisions: {}", "terminal_decisions:\n  PLATFORM_V2_FLOW_PROVEN: the synthetic flow completed end to end\n"
                                            "  PLATFORM_V2_FLOW_BROKEN: a synthetic stage failed"), encoding="utf-8")
        capability_present = (wt / CAPABILITY_MARKER).is_file()
        if plan.get("gap_first") and not capability_present:
            (study_dir / "study.yaml").write_text(gap_spec(sid), encoding="utf-8")
            out = _compile(study_dir)
            assert not out.ok, "gap spec unexpectedly compiled"
            from research_workflow.handoff import write_capability_gap_handoff
            write_capability_gap_handoff(study_dir, out.gaps.to_dict(), repo_root=wt)
            head = _commit_all(wt, f"study({sid}): CAPABILITY_GAP_HANDOFF")
            _result(packet_path, wt, "--status", "BLOCKED", "--blocker-code", "CAPABILITY_GAP", "--commit", head,
                    "--artifact", str(study_dir / "CAPABILITY_GAP_HANDOFF.json"), "--next-state", "CAPABILITY_GAP")
            return 0
        (study_dir / "study.yaml").write_text(compiling_spec(sid), encoding="utf-8")
        out = _compile(study_dir)
        assert out.ok, f"compile failed: {out.gaps.to_dict() if not out.ok else ''}"
        out.plan.write(study_dir / "compiled_plan.json")
        head = _commit_all(wt, f"study({sid}): compiled_plan")
        _result(packet_path, wt, "--status", "DONE", "--commit", head, "--artifact", str(study_dir / "compiled_plan.json"), "--next-state", "COMPILED")
        return 0
    if stype == "CAPABILITY_IMPLEMENTATION":
        marker = wt / CAPABILITY_MARKER
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("# synthetic capability: triggers.add (scripted worker)\n", encoding="utf-8")
        head = _commit_all(wt, "feat(triggers): synthetic add trigger (scripted capability worker)")
        _result(packet_path, wt, "--status", "DONE", "--commit", head, "--changed-file", CAPABILITY_MARKER,
                "--tests-json", json.dumps({"command": "scripted", "new_failures": 0, "known": 0, "fixed": 0}), "--extra-json", json.dumps({"cap_generate_check": "clean"}))
        return 0
    if stype in ("CAUSAL_AUDIT", "CONTRACT_AUDIT"):
        kind = "causal" if stype == "CAUSAL_AUDIT" else "contract"
        extra = packet["extra"]
        block = {"verdict": "CLEAR", "audit_type": kind, "study": sid, "auditor": packet["auditor"], "audited_execution_composite_sha256": extra["frozen_composite"],
                 "critical": 0, "warning": 0, "note": 1}
        report = Path(extra["report_path"])
        report.write_text(f"# {kind} audit (scripted)\n\nReviewed packet {extra.get('audit_packet')}.\n\n<!-- AUDIT_SUMMARY_V2_START -->\n{json.dumps(block)}\n<!-- AUDIT_SUMMARY_V2_END -->\n",
                          encoding="utf-8")
        _result(packet_path, wt, "--status", "DONE", "--report", str(report))
        return 0
    if stype == "ANALYSIS_DECISION":
        art = study_dir / "artifacts"; art.mkdir(parents=True, exist_ok=True)
        decision = "NOT_IN_THE_DECLARED_VOCABULARY" if plan.get("undeclared_decision") else "PLATFORM_V2_FLOW_PROVEN"
        dec = {"outcome": "SYNTHETIC_FLOW_COMPLETE", "terminal_decision": decision, "rationale": "scripted analysis worker", "evidence": ["artifacts/experiment_analysis_v2.json"]}
        (art / "analysis_decision.json").write_text(json.dumps(dec, indent=2) + "\n", encoding="utf-8")
        (art / "analysis_decision.md").write_text("# analysis decision (scripted)\n", encoding="utf-8")
        head = _commit_all(wt, f"study({sid}): analysis decision")
        _result(packet_path, wt, "--status", "DONE", "--commit", head, "--artifact", str(art / "analysis_decision.json"))
        return 0
    _result(packet_path, wt, "--status", "DONE", "--notes", f"scripted no-op for {stype}")
    return 0


def cmd_controller(ns: argparse.Namespace) -> int:
    from research_workflow.governed_controller_v2 import V2StudyController
    from research_workflow.host.interfaces import BarView
    from research_workflow.lifecycle_v2 import V2Options
    from research_workflow.tests.synthetic_primitives import SYNTHETIC_BINDINGS
    if not (GOLDEN / "bars.json").is_file():
        subprocess.run([sys.executable, str(GOLDEN / "build_golden_fixture.py")], check=True, cwd=str(ROOT), capture_output=True)
    bars = [BarView(**b) for b in json.loads((GOLDEN / "bars.json").read_text(encoding="utf-8"))]
    expected = json.loads((GOLDEN / "expected.json").read_text(encoding="utf-8"))
    session = {"kind": "calendar", "session": "RTH", "rows": [[a * NS, b * NS] for a, b in expected["sessions"]]}
    model_root = os.environ.get("NT_RESEARCH_TEST_MODEL_ROOT")
    assert model_root, "NT_RESEARCH_TEST_MODEL_ROOT must isolate the model store"
    closure = {"outcome": ns.closure_outcome, "terminal_decision": ns.closure_decision} if ns.closure_outcome else None
    opts = V2Options(execute=bool(ns.execute_authorized), smoke_date="2030-01-01", datasets_dir=GOLDEN / "datasets", extra_bindings=SYNTHETIC_BINDINGS,
                     bar_source=lambda s, e: bars, session_table_spec=session, in_process_partitions=True, closure=closure, model_root=Path(model_root))
    study = Path(ns.study).resolve()
    wt = Path(os.environ.get("NT_SUP_TEST_WORKTREE") or _git(["rev-parse", "--show-toplevel"], study))
    info = {"path": str(wt), "branch": _git(["rev-parse", "--abbrev-ref", "HEAD"], wt), "head": _git(["rev-parse", "HEAD"], wt), "dirty_paths": [], "unsafe_dirty_paths": []}
    V2StudyController._worktree = lambda self: dict(info)   # synthetic study lives in a throwaway repo, not this one
    card = V2StudyController(study, options=opts, repo_root=ROOT).run(through=ns.through)
    print(json.dumps({k: card.get(k) for k in ("STATUS", "state", "stage", "blocker_code", "actions_executed")}, default=str))
    return 0


def cmd_merge_under_lock(ns: argparse.Namespace) -> int:
    """Race helper: wait for the main-merge lock, merge ``branch`` into main, release. Prints one JSON line."""
    from research_workflow.supervisor.resources import MainMergeLock
    repo = Path(ns.repo)
    deadline = time.time() + 60
    while True:
        lock = MainMergeLock(ns.branch, "race_test")
        with lock as ok:
            if ok:
                if ns.hold_s:
                    time.sleep(float(ns.hold_s))
                assert not (repo / ".git" / "MERGE_HEAD").exists(), "another merge was in progress under the lock"
                subprocess.run(["git", "merge", "--no-ff", ns.branch, "-m", f"merge {ns.branch}"], cwd=str(repo), check=True, capture_output=True)
                print(json.dumps({"merged": ns.branch, "head": _git(["rev-parse", "HEAD"], repo), "pid": os.getpid()}))
                return 0
        if time.time() > deadline:
            print(json.dumps({"error": "LOCK_TIMEOUT", "holder": lock.holder}))
            return 2
        time.sleep(0.05)


def make_repo(tmp_path: Path) -> Dict[str, Any]:
    """A throwaway canonical repo on ``main`` plus a machine-local config; returns the env a test must set."""
    repo = tmp_path / "repo"; repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=str(repo), check=True)
    for k, v in (("user.name", "sup-test"), ("user.email", "sup-test@example.com"), ("commit.gpgsign", "false")):
        subprocess.run(["git", "config", k, v], cwd=str(repo), check=True)
    (repo / "README.md").write_text("synthetic canonical repo for supervisor tests\n", encoding="utf-8")
    (repo / "research_workflow").mkdir(); (repo / "research_workflow" / "README.md").write_text("platform placeholder\n", encoding="utf-8")
    _commit_all(repo, "init")
    home = tmp_path / "nt_research"; home.mkdir()
    (home / "leases").mkdir(); (tmp_path / "worktrees").mkdir(); (tmp_path / "model_store").mkdir()
    cfg = home / "config.yaml"
    cfg.write_text(f"catalog_roots: []\nmodel_root: {(tmp_path / 'model_store').as_posix()}\nleases_dir: {(home / 'leases').as_posix()}\n"
                   f"worktree_root: {(tmp_path / 'worktrees').as_posix()}\n", encoding="utf-8")
    env = {"NT_RESEARCH_CONFIG": str(cfg), "NT_RESEARCH_SUPERVISOR_HOME": str(home), "NT_RESEARCH_SUPERVISOR_NO_TOAST": "1",
           "NT_RESEARCH_TEST_MODEL_ROOT": str(tmp_path / "model_store"), "NT_RESEARCH_MODEL_ROOT": str(tmp_path / "model_store")}
    return {"repo": repo, "home": home, "env": env}


def controller_command() -> List[str]:
    return [sys.executable, str(Path(__file__).resolve()), "controller", "--study", "{study}", "--through", "{through}"]


def scripted_worker_command() -> List[str]:
    return [sys.executable, str(Path(__file__).resolve()), "worker"]


def main(argv: Optional[List[str]] = None) -> int:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("worker"); w.add_argument("packet"); w.set_defaults(fn=cmd_worker)
    c = sub.add_parser("controller"); c.add_argument("--study", required=True); c.add_argument("--through", default="seal"); c.add_argument("--json", action="store_true")
    c.add_argument("--max-runtime", type=float, default=600); c.add_argument("--execute-authorized", action="store_true")
    c.add_argument("--closure-outcome"); c.add_argument("--closure-decision"); c.set_defaults(fn=cmd_controller)
    m = sub.add_parser("merge_under_lock"); m.add_argument("--repo", required=True); m.add_argument("--branch", required=True); m.add_argument("--hold-s", type=float, default=0.5)
    m.set_defaults(fn=cmd_merge_under_lock)
    ns = ap.parse_args(argv)
    return ns.fn(ns)


if __name__ == "__main__":
    raise SystemExit(main())
