"""V8 on real data, adversarial: a DYNAMIC import (invisible to the compiler's static walk) of an out-of-key module,
executed inside the replay. The static derivation cannot put it in the key, so the smoke trace must halt.
Run only when no other partition child is alive (it perturbs research_workflow/host_runner.py for ~1 minute)."""
import json, os, subprocess, sys, time
from pathlib import Path
ROOT = Path(r"C:\Users\Scott McCarty\Projects\Nautilus Trader-collection_latency")
SP = Path(sys.argv[1]); SCR = SP / "r2_studies" / "studies"; STUDY = SCR / "controlled_feature_family_180s"; OUT = SP / "r2_g2.json"
sys.path.insert(0, str(ROOT)); os.chdir(ROOT)
from research_workflow.lifecycle_v2 import V2Lifecycle, V2Options, load_plan
rel = "research_workflow/host_runner.py"; p = ROOT / rel; original = p.read_text(encoding="utf-8")
probe = ("\n\ndef _r2_dynamic_probe():\n    import importlib\n    return importlib.import_module('research_workflow.' + 'audit_packets_v2')\n\n"
         "_r2_orig_run_plan_on_catalog = run_plan_on_catalog\n"
         "def run_plan_on_catalog(*a, **kw):\n    _r2_dynamic_probe()\n    return _r2_orig_run_plan_on_catalog(*a, **kw)\n")
CHILD = ("import sys, json; sys.path.insert(0, r'{root}')\nfrom pathlib import Path\n"
         "from research_workflow.lifecycle_v2 import V2Lifecycle, V2Options, LifecycleV2Error\n"
         "l = V2Lifecycle(Path(r'{study}'), repo_root=Path(r'{root}'), options=V2Options(execute=True, studies_root=Path(r'{scr}')))\n"
         "try:\n    print(json.dumps({{'ok': True, 'result': l.smoke()['status']}}))\n"
         "except LifecycleV2Error as exc:\n    print(json.dumps({{'ok': False, 'error': str(exc)[:300]}}))\n")
res = {}
try:
    p.write_text(original + probe, encoding="utf-8")
    l = V2Lifecycle(STUDY, repo_root=ROOT, options=V2Options(execute=True, studies_root=SCR)); l.compile(); l.prepare()
    (STUDY / "artifacts" / "preexec_audit_seal.json").write_text(json.dumps({"composite_seal_hash": "scratch-seal-g2", "execution_manifest_composite_sha256": "scratch-mfst-g2"}), encoding="utf-8")
    plan = load_plan(STUDY)
    res["audit_packets_in_replay_stage"] = "research_workflow/audit_packets_v2.py" in set(plan["closure"]["stages"]["replay"]["files"])
    r = subprocess.run([sys.executable, "-c", CHILD.format(root=ROOT, study=STUDY, scr=SCR)], cwd=str(ROOT), capture_output=True, text=True, timeout=1800)
    line = [x for x in r.stdout.splitlines() if x.startswith("{")]
    res["smoke"] = json.loads(line[-1]) if line else {"ok": False, "error": (r.stderr or r.stdout)[-400:]}
    td = json.loads((STUDY / "artifacts/replay_closure_trace.json").read_text(encoding="utf-8"))
    res["trace_verdict"], res["escapes"] = td["verdict"], td["escapes"]
    res["status"] = "DONE"
except Exception as exc:
    res["status"] = "FAILED"; res["error"] = repr(exc)
finally:
    p.write_text(original, encoding="utf-8")
    OUT.write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
print(json.dumps(res, default=str))
