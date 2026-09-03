"""A2 (CRIT-2): (i) does perturbing each governance module's hash move the composite and its own
stage composite only? (ii) empirical omission hunt -- which repo modules are actually IMPORTED
while executing governed stages but are NOT hashed into the closure?"""
from __future__ import annotations
import hashlib, json, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import build_study, lifecycle, ROOT  # noqa

GOV = ["research_workflow/lifecycle_v2.py", "research_workflow/governed_controller_v2.py",
       "research_workflow/experiment.py", "research_workflow/tuning.py", "research_workflow/model_store.py",
       "research_workflow/audit_packets_v2.py", "research_workflow/policy.py", "research_workflow/locks.py",
       "research_workflow/dataset_v2.py", "features/trackers/host_bindings.py"]

import research_workflow.closure_hash as ch
_real = ch.hash_file_v2
results = []

with tempfile.TemporaryDirectory() as td:
    study = build_study(Path(td))
    lc = lifecycle(study, execute=True)
    lc.compile()
    plan = json.loads((study / "compiled_plan.json").read_text())
    base_comp = plan["closure"]["composite_sha256"]
    base_files = plan["closure"]["files"]
    stages = plan["closure"]["stages"]
    print("closure file_count:", plan["closure"]["file_count"], "composite:", base_comp[:16])
    print("stages:", {k: (len(v["files"]), v["composite_sha256"][:10]) for k, v in stages.items()})

    for mod in GOV:
        hashed = mod in base_files
        if not hashed:
            results.append({"module": mod, "in_closure": False, "composite_moved": None, "verdict": "NOT_HASHED"})
            continue
        def fake(p, _m=mod):
            v = _real(p)
            try:
                rel = Path(p).resolve().relative_to(ROOT).as_posix()
            except Exception:
                rel = str(p)
            return "deadbeef" + v[8:] if rel == _m else v
        ch.hash_file_v2 = fake
        import research_workflow.grammar.compiler as C
        try:
            out = C.compile_study(C.load_spec(study), repo_root=ROOT, datasets_dir=lc.opts.datasets_dir,
                                  extra_bindings=lc.opts.extra_bindings)
            newc = out.plan.closure["composite_sha256"]
            newstages = out.plan.closure["stages"]
            moved = [n for n in newstages if newstages[n]["composite_sha256"] != stages[n]["composite_sha256"]]
            results.append({"module": mod, "in_closure": True, "composite_moved": newc != base_comp,
                            "stages_moved": moved,
                            "verdict": "BLOCKED" if newc != base_comp and moved else "BYPASSED"})
        finally:
            ch.hash_file_v2 = _real

print(json.dumps(results, indent=1))

# ---- omission hunt -------------------------------------------------------
ch.hash_file_v2 = _real
with tempfile.TemporaryDirectory() as td:
    study = build_study(Path(td), "adv_omit")
    lc = lifecycle(study, execute=True)
    before = set(sys.modules)
    lc.compile(); lc.prepare(); lc.readiness(); lc.preflight()
    plan = json.loads((study / "compiled_plan.json").read_text())
    closure = set(plan["closure"]["files"])
    # run the audit packet + seal-adjacent surfaces too
    try:
        from research_workflow.audit_packets_v2 import causal_packet, contract_packet
        causal_packet(plan); contract_packet(plan)
    except Exception as e:
        print("packet:", e)
    imported = {}
    for name, m in list(sys.modules.items()):
        f = getattr(m, "__file__", None)
        if not f:
            continue
        try:
            rel = Path(f).resolve().relative_to(ROOT).as_posix()
        except Exception:
            continue
        if rel.startswith(("research_workflow/", "features/", "research/", "utils/", "backtests/", "indicators/", "strategies/")) \
           and "/tests/" not in rel and not rel.endswith("__init__.py"):
            imported[rel] = name
    missing = sorted(set(imported) - closure)
    print("\n=== imported-during-governed-stages but NOT hashed ===")
    for rel in missing:
        print(" ", rel)
    print("\nclosure size:", len(closure), " imported repo modules:", len(imported), " unhashed:", len(missing))
    Path(__file__).with_name("a2_omissions.json").write_text(json.dumps(
        {"closure": sorted(closure), "unhashed_imported": missing, "perturbation": results}, indent=1))
