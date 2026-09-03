"""A9 (WARN F2/F3: zero-python + --execute-authorized gate), A10 (deliverables = paths actually
written), plus a full-lifecycle import trace feeding A2's closure-omission hunt."""
from __future__ import annotations
import json, os, sys, tempfile, shutil
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import build_study, lifecycle, ROOT, GOLDEN  # noqa

res = []


def t(name, fn, expect_reject=True):
    try:
        out = fn()
        res.append({"case": name, "outcome": f"RETURNED {str(out)[:180]}", "verdict": "BYPASSED" if expect_reject else "OK"})
    except Exception as exc:
        res.append({"case": name, "outcome": f"{type(exc).__name__}: {str(exc)[:220]}",
                    "verdict": "BLOCKED" if expect_reject else "UNEXPECTED_REJECT"})


from research_workflow.governed_controller_v2 import V2StudyController
from research_workflow.lifecycle_v2 import V2Options, ingest_audit_report
from research_workflow.tests.synthetic_primitives import SYNTHETIC_BINDINGS
from research_workflow.host.interfaces import BarView

V2StudyController._worktree = lambda self: {"path": str(ROOT), "branch": "adv", "head": "0" * 40, "dirty_paths": [], "unsafe_dirty_paths": []}
V2StudyController._check_writer_lease = lambda self: None   # never touch the real leases dir


def _write_audit(study, kind, auditor):
    frozen = json.loads((study / "audit" / "frozen_execution_manifest.json").read_text())["frozen_execution_composite_sha256"]
    name = "pass_01.md" if kind == "causal" else "contract_pass_01.md"
    block = {"verdict": "CLEAR", "audit_type": kind, "study": study.name, "auditor": auditor,
             "audited_execution_composite_sha256": frozen, "critical": 0, "warning": 0, "note": 1}
    p = study / "audit" / name
    p.write_text("# " + kind + "\n\n<!-- AUDIT_SUMMARY_V2_START -->\n" + json.dumps(block) + "\n<!-- AUDIT_SUMMARY_V2_END -->\n", encoding="utf-8")
    return p


def opts(execute):
    bars = [BarView(**b) for b in json.loads((GOLDEN / "bars.json").read_text())]
    expected = json.loads((GOLDEN / "expected.json").read_text())
    NS = 1_000_000_000
    session = {"kind": "calendar", "session": "RTH", "rows": [[a * NS, b * NS] for a, b in expected["sessions"]]}
    return V2Options(execute=execute, smoke_date="2030-01-01", datasets_dir=GOLDEN / "datasets",
                     extra_bindings=SYNTHETIC_BINDINGS, bar_source=lambda s, e: bars,
                     session_table_spec=session, in_process_partitions=True,
                     closure={"outcome": "SYNTHETIC_FLOW_COMPLETE", "terminal_decision": "PLATFORM_V2_FLOW_PROVEN"})


TD = tempfile.mkdtemp()
study = build_study(Path(TD), "adv_e2e")

# FINDING N3: V2Options carries no model_root, so lifecycle_v2.fit() -> model_store.store_model()
# writes into the operator's REAL durable model store for any run, including a throwaway one.
# Redirect it here so this attack script cannot pollute the shared store.
import research_workflow.roots as _roots
_TMP_MODEL_ROOT = Path(TD) / "model_root"
_roots.resolve_model_root = lambda *a, **k: _TMP_MODEL_ROOT

# ---------- A9: zero-study-python variants ----------
from research_workflow.policy import scan_study_python, STUDY_PYTHON_EXCEPTIONS
probes = {"helpers.py": "x=1\n", "sub/nested/deep.py": "y=2\n", "note.ipynb": "{}\n", "SHOUT.PY": "z=3\n",
          "_work2/hidden.py": "w=4\n", "runs_x/sneak.py": "v=5\n", "_work/ok.py": "ignored\n",
          "runs/ok2.py": "ignored\n", "compiled.pyc": "junk", "pkg/__init__.py": "\n"}
for rel, body in probes.items():
    p = study / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
found = [f.replace("\\", "/") for f in scan_study_python(study)]
print("scan_study_python ->", json.dumps(found, indent=1))
print("STUDY_PYTHON_EXCEPTIONS:", STUDY_PYTHON_EXCEPTIONS)
should_catch = [r for r in probes if r.endswith((".py", ".PY", ".ipynb")) and not r.startswith(("_work/", "runs/"))]
missed = [r for r in should_catch if r not in found]
res.append({"case": "A9 scan_study_python catches every planted .py/.PY/.ipynb outside _work/ and runs/",
            "outcome": "found=" + str(found) + " missed=" + str(missed), "verdict": "BLOCKED" if not missed else "BYPASSED"})

lc = lifecycle(study, execute=False)
lc.compile()
lc.prepare()
t("A9 readiness with planted study Python", lambda: lc.readiness())
rj = json.loads((study / "audit" / "readiness.json").read_text())
print("R10:", json.dumps([c for c in rj["checks"] if c["id"] == "R10_zero_study_python"]))

sy = (study / "study.yaml").read_text()
(study / "study.yaml").write_text(sy.replace("study: {id: adv_e2e,", "study: {id: adv_e2e, python_exception: \"self-granted\","), encoding="utf-8")
t("A9 study.yaml self-declared python_exception is honoured", lambda: lifecycle(study).compile())
(study / "study.yaml").write_text(sy, encoding="utf-8")

for rel in probes:
    p = study / rel
    if p.is_file():
        p.unlink()
for d in ("sub", "_work2", "runs_x", "pkg", "_work", "runs"):
    shutil.rmtree(study / d, ignore_errors=True)

# ---------- A9: --execute gate ----------
ctl_noexec = lambda: V2StudyController(study, options=opts(False), repo_root=ROOT)
ctl_exec = lambda: V2StudyController(study, options=opts(True), repo_root=ROOT)
card = ctl_exec().run(through="tests")
print("tests card:", card["STATUS"], card.get("actions_executed"))
ctl_exec().run(through="seal")
ingest_audit_report(study, "causal", _write_audit(study, "causal", "auditor_a"))
ctl_exec().run(through="seal")
ingest_audit_report(study, "contract", _write_audit(study, "contract", "auditor_b"))
card = ctl_exec().run(through="seal")
print("seal card:", card["STATUS"], card.get("state"))

lock = study / "_work" / "controller" / "run.lock"
for stage in ("smoke", "collection", "reconcile", "merge", "fit", "freeze", "oos", "analyze", "close"):
    c = ctl_noexec().run(through=stage)
    r = {"STATUS": c.get("STATUS"), "state": c.get("state"), "blocker_code": c.get("blocker_code"),
         "reason": str(c.get("reason"))[:140], "actions": c.get("actions_executed"), "lock_exists": lock.exists()}
    bad = bool(r["STATUS"] == "OK" and r["actions"])
    res.append({"case": "A9 controller run(through=" + stage + ") WITHOUT --execute-authorized",
                "outcome": json.dumps(r), "verdict": "BYPASSED" if bad else "BLOCKED"})

lcn = lifecycle(study, execute=False)
for leaf in ("smoke", "collection", "reconcile", "merge", "fit", "freeze", "oos", "analyze", "close"):
    t("A9 direct V2Lifecycle." + leaf + "() WITHOUT execute", lambda l=leaf: getattr(lcn, l)())

# ---------- full run with execute, tracing imports ----------
for through in ("merge", "freeze", "analyze", "close"):
    card = ctl_exec().run(through=through)
    print("run through=" + through + ":", card["STATUS"], card.get("state"), str(card.get("reason"))[:160])
    if card["STATUS"] != "OK":
        print(json.dumps(card, indent=1, default=str)[:3000])
        break

plan = json.loads((study / "compiled_plan.json").read_text())
closure = set(plan["closure"]["files"])
imported = {}
for name, m in list(sys.modules.items()):
    f = getattr(m, "__file__", None)
    if not f:
        continue
    try:
        rel = Path(f).resolve().relative_to(ROOT).as_posix()
    except Exception:
        continue
    if rel.startswith(("research_workflow/", "features/", "research/", "utils/", "backtests/", "indicators/", "strategies/", "scripts/")) \
       and "/tests/" not in rel and not rel.endswith("__init__.py"):
        imported[rel] = name
unhashed = sorted(set(imported) - closure)
print("\n=== FULL-LIFECYCLE unhashed-but-imported ===")
for r in unhashed:
    print(" ", r)

# ---------- A10 ----------
from research_workflow.audit_packets_v2 import deliverables_for_plan
dl = deliverables_for_plan(plan)
print("\n=== deliverables_for_plan ===")
print(json.dumps(dl, indent=1)[:5000])
flat = []


def walk(o):
    if isinstance(o, str):
        flat.append(o)
    elif isinstance(o, dict):
        for v in o.values():
            walk(v)
    elif isinstance(o, (list, tuple)):
        for v in o:
            walk(v)


walk(dl)
missing_on_disk = []
for pth in sorted(set(flat)):
    if not (pth.endswith(".json") or pth.endswith(".parquet") or pth.endswith(".md")):
        continue
    p = Path(pth) if os.path.isabs(pth) else (study / pth)
    if not p.exists():
        missing_on_disk.append(pth)
print("\ndeliverable paths NOT present after a full golden run:", json.dumps(missing_on_disk, indent=1))
res.append({"case": "A10 every deliverable path exists after a full golden run",
            "outcome": "missing=" + str(missing_on_disk), "verdict": "BLOCKED" if not missing_on_disk else "BYPASSED"})

print("\n=== RESULTS ===")
print(json.dumps(res, indent=1))
Path(__file__).with_name("a9_a10_results.json").write_text(json.dumps(
    {"results": res, "unhashed_imported_full_lifecycle": unhashed, "deliverables": dl,
     "deliverable_paths_missing": missing_on_disk, "study_tmp": TD,
     "zero_python_found": found}, indent=1, default=str))
print("\nBYPASSED:", json.dumps([r for r in res if r["verdict"] in ("BYPASSED", "UNEXPECTED_REJECT")], indent=1))
