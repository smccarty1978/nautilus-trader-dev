"""Supervisor V1 efficiency closeout (2026-09-06): the bounded auditor brief, worker metrics, and the one-loop-per-study resume.

Why: the first real validation's auditors spent 68/54 (causal) and 48/42 (contract) turns re-discovering the repository.
The brief derives everything mechanically once; these tests pin that it carries the auditor's EXACT checklist subset
(coverage not weakened), the closure delta, the prior findings, and that the supervisor records turns/cost per worker."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research_workflow.supervisor import audit_brief as AB  # noqa: E402
from research_workflow.supervisor import providers as PR  # noqa: E402

CHECKLIST = (ROOT / "docs" / "CAUSAL_CHECKLIST.md").read_text(encoding="utf-8")
RULE_RE = re.compile(r"^- \*\*([A-H]\d+)\.\*\*", re.MULTILINE)
ALL_RULES = set(RULE_RE.findall(CHECKLIST))
CAUSAL_RULES = {r for r in ALL_RULES if r[0] in "ABFGH" or r in ("C1", "C2", "C3")}
CONTRACT_RULES = {r for r in ALL_RULES if r[0] in "DE" or r == "C4"}


def test_checklist_subset_is_exact_and_verbatim():
    """Every rule the checklist assigns to a role is in that role's brief, none of the other role's, and each rule's
    text is byte-identical to the checklist (no restated / drifted rules)."""
    assert ALL_RULES == CAUSAL_RULES | CONTRACT_RULES and not (CAUSAL_RULES & CONTRACT_RULES)
    for kind, owned in (("causal", CAUSAL_RULES), ("contract", CONTRACT_RULES)):
        sub = AB.checklist_subset(CHECKLIST, kind)
        assert set(RULE_RE.findall(sub)) == owned, kind
        assert "## Severity definitions" in sub and "| `CRITICAL` |" in sub
        for rule in owned:
            m = re.search(r"^- \*\*" + rule + r"\.\*\*.*?(?=^- \*\*|^## |\Z)", CHECKLIST, re.MULTILINE | re.DOTALL)
            assert m and m.group(0).strip() in sub, f"{kind}: rule {rule} not verbatim"
    assert "C4" in AB.checklist_subset(CHECKLIST, "contract") and "C4" not in RULE_RE.findall(AB.checklist_subset(CHECKLIST, "causal"))


def test_doc_section_extracts_one_section():
    text = "# T\n\n## 16. A\nx\n\n## 17. Timestamps\n\n- one\n- two\n\n---\n\n## 18. B\ny\n"
    sec = AB.doc_section(text, "## 17.")
    assert sec.startswith("## 17. Timestamps") and "- two" in sec and "## 18." not in sec and "x" not in sec
    assert AB.doc_section(text, "## 99.") == ""


def test_closure_delta_names_only_changed_added_removed():
    cur = {"frozen_execution_composite_sha256": "new", "files": {"a.py": "1", "b.py": "2", "c.py": "3"}}
    old = {"frozen_execution_composite_sha256": "old", "files": {"a.py": "1", "b.py": "9", "d.py": "4"}}
    d = AB.closure_delta(cur, old)
    assert d["comparable"] and d["prior_composite"] == "old"
    assert [c["file"] for c in d["changed"]] == ["b.py"] and d["added"] == ["c.py"] and d["removed"] == ["d.py"]
    assert AB.closure_delta(cur, None)["comparable"] is False


def test_prior_findings_extraction_covers_both_report_styles():
    causal = "## Prior findings adjudicated\n| # | Finding | Status |\n| N1 | zero-lead | NOT FIXED |\n## Notes\n- NOTE: **[B9] `x.py:1` -- inert lookback.**\nprose\n### [A1] `y.py:2` -- defect\n"
    contract = "| Requirement | Verdict |\n| Closure covers | WARNING | W-4 |\n| SPEC bound | PASS | - |\n## W-4 -- the walk covers collection only\n## Notes\n"
    c = AB.prior_findings(causal); k = AB.prior_findings(contract)
    assert any(l.startswith("| N1 |") for l in c) and any("[B9]" in l for l in c) and any(l.startswith("### [A1]") for l in c) and not any(l == "prose" for l in c)
    assert any("W-4 |" in l for l in k) and any(l.startswith("## W-4") for l in k) and not any("| PASS |" in l for l in k)
    assert AB.summary_block("x <!-- AUDIT_SUMMARY_V2_START --> {\"verdict\": \"CLEAR\", \"note\": 2} <!-- AUDIT_SUMMARY_V2_END -->")["note"] == 2


def _study(tmp_path: Path) -> tuple[Path, Path]:
    wt = tmp_path / "wt"; study = wt / "studies" / "s1"
    (study / "audit").mkdir(parents=True); (study / "_work" / "controller").mkdir(parents=True); (study / "artifacts").mkdir()
    (wt / "docs").mkdir()
    (wt / "docs" / "CAUSAL_CHECKLIST.md").write_text(CHECKLIST, encoding="utf-8")
    (wt / "docs" / "RESEARCH_WORKFLOW.md").write_text("## 17. Timestamps\n\n- bars are close-stamped\n\n## 18. x\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=str(wt), check=True)
    manifest = {"frozen_execution_composite_sha256": "c" * 64, "plan_sha256": "p" * 64, "spec_sha256": "s" * 64, "file_count": 2, "hash_algorithm": "v2",
                "files": {"research_workflow/a.py": "aa", "features/b.py": "bb"}, "stages": {"collection": {"files": ["research_workflow/a.py", "features/b.py"]}}}
    (study / "audit" / "frozen_execution_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (study / "audit" / "preflight.json").write_text(json.dumps({"status": "CLEAR", "check_outcomes": {"X": "PASSED"}, "required_checks": ["X"], "leaked_outcome_columns": [],
                                                                 "execution_composite_sha256": "c" * 64}), encoding="utf-8")
    (study / "audit" / "readiness.json").write_text(json.dumps({"overall_status": "PASS", "checks": [{"id": "R1", "passed": True}], "execution_composite_sha256": "c" * 64}), encoding="utf-8")
    (study / "_work" / "controller" / "test_summary.json").write_text(json.dumps({"status": "PASS", "counts": {"passed": 3, "failed": 0}, "execution_composite_sha256": "c" * 64, "files": ["t"]}), encoding="utf-8")
    (study / "_work" / "controller" / "status.json").write_text(json.dumps({"STATUS": "OK", "state": "NEEDS_CAUSAL_AUDIT", "stage": "causal_audit", "fingerprints": {"execution_composite": "c" * 64}}), encoding="utf-8")
    packet = {"packet_version": 2, "worktree_dirty_paths": [], "deliverables_by_stage": {"compile": ["compiled_plan.json"], "prepare": ["audit/frozen_execution_manifest.json"]},
              "closure": {"stages": manifest["stages"]}}
    (study / "_work" / "controller" / "audit_packet_causal.json").write_text(json.dumps(packet), encoding="utf-8")
    (study / "_work" / "controller" / "audit_packet_contract.json").write_text(json.dumps({**packet, "audit_type": "contract"}), encoding="utf-8")
    return wt, study


def test_brief_pass_one_and_pass_two_with_closure_delta_and_prior_findings(tmp_path):
    wt, study = _study(tmp_path)
    out = tmp_path / "sup"
    m1 = AB.build_audit_brief(kind="causal", study_id="s1", study_dir=study, worktree=wt, task_id="001", audit_packet=study / "_work" / "controller" / "audit_packet_causal.json",
                              report_path=out / "001.report.md", auditor="lookahead-auditor:001", frozen_composite="c" * 64, out_path=out / "001.brief.md",
                              manifest_snapshot=out / "001.manifest.json")
    text1 = (out / "001.brief.md").read_text(encoding="utf-8")
    assert m1["pass"] == 1 and (out / "001.manifest.json").is_file() and m1["closure_changed"] == [] and m1["prior_report"] is None
    assert "pass 01" in text1 and "first pass of this kind" in text1 and "this is pass 01" in text1
    assert "- **A1.**" in text1 and "- **C4.**" not in text1 and "## 17. Timestamps" in text1 and "bars are close-stamped" in text1
    assert "preflight: CLEAR (1/1" in text1 and "readiness: PASS (R1=pass" in text1 and "tests: PASS 3 passed / 0 failed" in text1
    assert "Do not run Python" in text1 and "Do not reopen unchanged files" in text1 and "Do NOT read WORKFLOW.md" in text1
    assert m1["brief_bytes"] < 16_000, m1["brief_bytes"]   # the brief itself stays small (checklist subset + facts)
    # pass 2: one closure file changed, a prior report with findings exists
    manifest = json.loads((study / "audit" / "frozen_execution_manifest.json").read_text(encoding="utf-8"))
    manifest["files"]["features/b.py"] = "b2"; manifest["frozen_execution_composite_sha256"] = "d" * 64
    (study / "audit" / "frozen_execution_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (study / "audit" / "pass_01.md").write_text("# pass 1\n\n- NOTE: **[B9] `features/b.py:3` -- inert lookback.**\n\n<!-- AUDIT_SUMMARY_V2_START -->\n"
                                               + json.dumps({"verdict": "CLEAR", "critical": 0, "warning": 0, "note": 1, "auditor": "lookahead-auditor:001",
                                                             "audited_execution_composite_sha256": "c" * 64}) + "\n<!-- AUDIT_SUMMARY_V2_END -->\n", encoding="utf-8")
    m2 = AB.build_audit_brief(kind="causal", study_id="s1", study_dir=study, worktree=wt, task_id="002", audit_packet=study / "_work" / "controller" / "audit_packet_causal.json",
                              report_path=out / "002.report.md", auditor="lookahead-auditor:002", frozen_composite="d" * 64, out_path=out / "002.brief.md",
                              manifest_snapshot=out / "002.manifest.json", prior_manifest=out / "001.manifest.json", prior_source_commit="0123456789abcdef")
    text2 = (out / "002.brief.md").read_text(encoding="utf-8")
    assert m2["pass"] == 2 and m2["closure_changed"] == ["features/b.py"] and m2["prior_composite"] == "c" * 64
    assert "1 changed, 0 added, 0 removed" in text2 and "- changed: `features/b.py` bb -> b2" in text2 and "git diff 0123456789ab..HEAD" in text2
    assert "prior report `audit/pass_01.md`: verdict CLEAR" in text2 and "[B9]" in text2 and "Adjudicate every prior finding" in text2
    # contract brief: C4/D/E, the deliverable existence table, section 6.2 reference
    (study / "audit" / "status.json").write_text(json.dumps({"verdict": "CLEAR", "auditor": "lookahead-auditor:002", "audited_execution_composite_sha256": "d" * 64}), encoding="utf-8")
    m3 = AB.build_audit_brief(kind="contract", study_id="s1", study_dir=study, worktree=wt, task_id="003", audit_packet=study / "_work" / "controller" / "audit_packet_contract.json",
                              report_path=out / "003.report.md", auditor="contract-checker:003", frozen_composite="d" * 64, out_path=out / "003.brief.md",
                              manifest_snapshot=out / "003.manifest.json")
    text3 = (out / "003.brief.md").read_text(encoding="utf-8")
    assert "- **C4.**" in text3 and "- **D1.**" in text3 and "- **A1.**" not in text3 and m3["pass"] == 1
    assert "| compile | `compiled_plan.json` | NO | - |" in text3 and "| prepare | `audit/frozen_execution_manifest.json` | yes |" in text3
    assert "audit/status.json: verdict=CLEAR auditor=`lookahead-auditor:002`" in text3 and "so its absence is not a finding" in text3


def test_worker_metrics_parse_the_claude_json_result(tmp_path):
    log = tmp_path / "w.log"
    result = {"type": "result", "num_turns": 12, "total_cost_usd": 0.91, "duration_ms": 65000, "duration_api_ms": 60000, "is_error": False, "subtype": "success",
              "stop_reason": "end_turn", "usage": {"input_tokens": 5, "cache_read_input_tokens": 500000, "cache_creation_input_tokens": 40000, "output_tokens": 9000},
              "permission_denials": [{"tool_name": "Bash", "tool_input": {"command": "python -c 'x'"}}], "modelUsage": {"claude-opus-5": {}}}
    log.write_text("noise\n" + json.dumps({"type": "system", "num_turns": 1}) + "\n" + json.dumps(result) + "\n", encoding="utf-8")
    m = PR.worker_metrics({"provider": "claude", "log_path": str(log)})
    assert m["num_turns"] == 12 and m["total_cost_usd"] == 0.91 and m["cache_read_input_tokens"] == 500000 and m["permission_denials"] == 1
    assert m["denied_commands"] == ["python -c 'x'"] and m["models"] == ["claude-opus-5"]
    assert PR.worker_metrics({"provider": "scripted", "log_path": str(log)}) is None
    assert PR.worker_metrics({"provider": "claude", "log_path": str(tmp_path / "missing.log")}) is None


def test_finish_worker_records_metrics_and_aggregates_counters(tmp_path, monkeypatch):
    from research_workflow.supervisor import state as S
    from research_workflow.supervisor.core import Supervisor
    monkeypatch.setenv("NT_RESEARCH_SUPERVISOR_HOME", str(tmp_path / "home"))
    S.save_state(S.new_state(study_id="s", question_path=None, question_sha256=None, platform_commit=None, provider="claude", study_branch="study/s",
                             study_worktree=str(tmp_path), repo_root=str(tmp_path), execute_authorized=False))
    sup = Supervisor("s")
    log = sup.dir / "logs" / "t.log"
    log.write_text(json.dumps({"num_turns": 7, "total_cost_usd": 0.5, "usage": {}, "permission_denials": [{}, {}]}) + "\n", encoding="utf-8")
    aw = {"task_id": "t", "session_type": "CAUSAL_AUDIT", "session_id": "x", "provider": "claude", "log_path": str(log), "attempt_key": "k", "result_path": str(tmp_path / "r.json"),
          "started_at_utc": "2026-09-06T00:00:00+00:00", "brief_bytes": 1234, "audit_packet_bytes": 20000}
    sup.state["active_worker"] = aw
    sup._finish_worker(aw, status="DONE", reason=None, card={"commits": []})
    rec = sup.state["worker_history"][-1]
    assert rec["metrics"]["num_turns"] == 7 and rec["brief_bytes"] == 1234 and rec["audit_packet_bytes"] == 20000 and rec["wall_s"] is not None
    assert sup.state["counters"]["worker_turns"] == 7 and sup.state["counters"]["worker_cost_usd"] == 0.5 and sup.state["counters"]["worker_permission_denials"] == 2


def test_max_budget_flag_is_applied_only_when_probed_and_requested():
    probe = {"provider": "claude", "AVAILABLE": True, "HEADLESS_SUPPORTED": True, "WRITE_SUPPORTED": True, "READ_ONLY_SUPPORTED": True, "binary": "claude",
             "flags": {"-p": True, "--output-format": True, "--allowedTools": True, "--max-budget-usd": True}}
    base = dict(packet_path=Path("p.md"), worktree=Path("."), read_only=True, results_dir=Path("."), session_id="s", probe=probe)
    assert "--max-budget-usd" not in PR.build_command("claude", **base)
    cmd = PR.build_command("claude", **base, max_budget_usd=4)
    assert cmd[cmd.index("--max-budget-usd") + 1] == "4.0"
    probe["flags"]["--max-budget-usd"] = False
    assert "--max-budget-usd" not in PR.build_command("claude", **base, max_budget_usd=4)


def test_resume_does_not_spawn_a_second_loop_when_one_is_alive(tmp_path, monkeypatch, capsys):
    """One loop per study: `supervise resume` while the detached loop is alive must not detach another (two loops ticking one
    state could launch a stage twice)."""
    from research_workflow.supervisor import cli as supervisor_cli
    from research_workflow.supervisor import state as S
    monkeypatch.setenv("NT_RESEARCH_SUPERVISOR_HOME", str(tmp_path / "home"))
    S.save_state(S.new_state(study_id="s", question_path=None, question_sha256=None, platform_commit=None, provider="scripted", study_branch="study/s",
                             study_worktree=str(tmp_path), repo_root=str(tmp_path), execute_authorized=False))
    (S.study_state_dir("s") / "pid").write_text(str(__import__("os").getpid()), encoding="utf-8")   # this test process stands in for the live loop
    spawned = []
    monkeypatch.setattr(supervisor_cli, "_detach_loop", lambda repo_root, sid: spawned.append(sid) or {"loop_pid": 1, "loop_alive": True})
    rc = supervisor_cli.cmd_supervise(argparse.Namespace(cmd="resume", study_id="s", no_detach=False), ROOT)
    card = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert rc == 0 and card["loop_alive"] is True and "LOOP_ALREADY_ALIVE" in card["note"] and spawned == []
    assert S.load_state("s")["stopped"] is False
    (S.study_state_dir("s") / "pid").write_text("999999999", encoding="utf-8")                        # dead loop: resume detaches a fresh one
    supervisor_cli.cmd_supervise(argparse.Namespace(cmd="resume", study_id="s", no_detach=False), ROOT)
    assert spawned == ["s"]
