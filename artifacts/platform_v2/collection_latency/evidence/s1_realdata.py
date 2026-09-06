"""S1 real-data validation on a scratch copy of es_180s_model_c_portability (ES_1S_V2_GLOBEX, TRAIN 2020+2021).

Phases: A baseline collection (reuse declared, nothing to reuse) -> B analysis-only spec change (V2/V5/V6, shadow every_run)
-> C second text change with shadow sampled (V6) -> D real replay-module perturbation (V1, preview only)
-> E live-case shape: research/analysis/diagnostic_ops.py perturbation (V3 as escalated, preview only).
Writes results JSON to the scratchpad; touches nothing under any live study. Repo files perturbed in D/E are restored.
"""
import json, os, shutil, sys, time, traceback
from pathlib import Path
import yaml

ROOT = Path(r"C:\Users\Scott McCarty\Projects\Nautilus Trader-collection_latency")
SRC = Path(r"C:\Users\Scott McCarty\Projects\Nautilus Trader-es_180s_model_c_portability\studies\es_180s_model_c_portability")
SP = Path(sys.argv[1]); SCR = SP / "s1_studies"; STUDY = SCR / "studies" / "es_180s_model_c_portability"
OUT = SP / "s1_realdata.json"
sys.path.insert(0, str(ROOT)); os.chdir(ROOT)
from research_workflow.lifecycle_v2 import V2Lifecycle, V2Options, load_plan

RES = {"phases": [], "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
def save(): OUT.write_text(json.dumps(RES, indent=1, default=str), encoding="utf-8")
def phase(name, **kw):
    RES["phases"].append({"phase": name, **kw}); save()

def write_spec(mut):
    body = yaml.safe_load((STUDY / "study.yaml").read_text(encoding="utf-8")); mut(body)
    (STUDY / "study.yaml").write_text(yaml.safe_dump(body, sort_keys=False), encoding="utf-8")

def seal(tag):
    (STUDY / "artifacts").mkdir(exist_ok=True)
    (STUDY / "artifacts" / "preexec_audit_seal.json").write_text(json.dumps(
        {"composite_seal_hash": f"scratch-seal-{tag}", "execution_manifest_composite_sha256": f"scratch-mfst-{tag}"}), encoding="utf-8")

def lc():
    return V2Lifecycle(STUDY, repo_root=ROOT, options=V2Options(execute=True, studies_root=SCR / "studies"))

def shas():
    out = {}
    for y in (2020, 2021):
        m = json.loads((STUDY / "_work/controller/partitions/train" / str(y) / "manifest.json").read_text(encoding="utf-8"))
        out[y] = {"candidates": m["candidates_sha256"], "observations": m["observations_sha256"], "plan": m["plan_sha256"], "elapsed_s": m.get("elapsed_s"), "rows": m["rows"]}
    return out

def timed(fn):
    t0 = time.perf_counter(); r = fn(); return r, time.perf_counter() - t0

def compile_prepare_seal(tag):
    l = lc(); l.compile(); l.prepare(); seal(tag); return l, load_plan(STUDY)

if STUDY.exists(): shutil.rmtree(STUDY)
STUDY.mkdir(parents=True)
for f in ("study.yaml", "research_decision.yaml", "SPEC.md"):
    if (SRC / f).exists(): shutil.copy2(SRC / f, STUDY / f)
write_spec(lambda b: (b["chronology"].__setitem__("train", [2020, 2021]), b["chronology"].__setitem__("partition_reuse", "replay_closure")))

perturbed = {}
try:
    # -- A: baseline ------------------------------------------------------------------------------
    l, plan = compile_prepare_seal("a")
    sm, t_smoke = timed(l.smoke)
    trace = json.loads((STUDY / "artifacts/replay_closure_trace.json").read_text(encoding="utf-8"))
    r, t_coll = timed(l.collection)
    rc, t_rec = timed(l.reconcile)
    phase("A_baseline", plan_sha256=plan["plan_sha256"], collection_closure=plan["closure"]["stages"]["collection"]["composite_sha256"],
          smoke_s=t_smoke, smoke_trace_verdict=trace["verdict"], smoke_traced_files=len(trace["traced_repo_files"]),
          preloaded_outside=trace["preloaded_repo_files_outside_closure"], collection_wall_s=t_coll, result=r.get("partition_reuse"),
          shas=shas(), reconcile_s=t_rec, receipt=json.loads((STUDY / "_work/controller/train_partition_reuse.json").read_text(encoding="utf-8")))
    base = shas()

    # -- B: analysis-only (study text) change, shadow every_run -------------------------------------
    write_spec(lambda b: b["study"].__setitem__("question", b["study"]["question"] + " (rephrased after collection; S1 phase B)"))
    l, plan_b = compile_prepare_seal("b")
    preview = l.partition_reuse_preview("train")
    r, t_coll = timed(l.collection)
    rc, t_rec = timed(l.reconcile)
    shadow = json.loads((STUDY / "_work/controller/partition_reuse_shadow.json").read_text(encoding="utf-8"))
    recon = json.loads((STUDY / "_work/controller/reconcile.json").read_text(encoding="utf-8"))
    phase("B_analysis_only_every_run", plan_sha256=plan_b["plan_sha256"], plan_changed=plan_b["plan_sha256"] != plan["plan_sha256"],
          collection_closure_same=plan_b["closure"]["stages"]["collection"]["composite_sha256"] == plan["closure"]["stages"]["collection"]["composite_sha256"],
          would_reuse=preview["would_reuse"], collection_wall_s=t_coll, result=r.get("partition_reuse"), served_bytes_identical=shas() == base,
          shadow={k: shadow.get(k) for k in ("selected", "status", "shadow_elapsed_s", "comparison")}, reconcile_s=t_rec, reconcile_passed=recon["passed"],
          reattested=recon["partition_reuse"])

    # -- C: another text change, shadow sampled ------------------------------------------------------
    write_spec(lambda b: (b["study"].__setitem__("question", b["study"]["question"] + " (phase C)"), b["chronology"].__setitem__("partition_reuse_shadow", "sampled")))
    l, plan_c = compile_prepare_seal("c")
    r, t_coll = timed(l.collection)
    rc, t_rec = timed(l.reconcile)
    shadow = json.loads((STUDY / "_work/controller/partition_reuse_shadow.json").read_text(encoding="utf-8"))
    phase("C_analysis_only_sampled", plan_sha256=plan_c["plan_sha256"], collection_wall_s=t_coll, result=r.get("partition_reuse"),
          served_bytes_identical=shas() == base, shadow={k: shadow.get(k) for k in ("selected", "status", "shadow_elapsed_s")}, reconcile_s=t_rec)

    # -- D: real replay module perturbation (V1) -- preview only --------------------------------------
    for tag, rel in (("D_replay_module_perturbed", "features/trackers/generic_arrival.py"),
                     ("E_live_case_shape_diagnostic_ops", "research/analysis/diagnostic_ops.py")):
        p = ROOT / rel; perturbed[rel] = p.read_text(encoding="utf-8")
        p.write_text(perturbed[rel] + "\n_S1_REPLAY_CLOSURE_PROBE = 1\n", encoding="utf-8")
        l, plan_x = compile_prepare_seal(tag)
        preview = l.partition_reuse_preview("train")
        phase(tag, file=rel, collection_closure_changed=plan_x["closure"]["stages"]["collection"]["composite_sha256"] != plan["closure"]["stages"]["collection"]["composite_sha256"],
              would_reuse=preview["would_reuse"], reasons=[(x["id"], x["reason"]) for x in preview["partitions"]])
        p.write_text(perturbed.pop(rel), encoding="utf-8")
    RES["status"] = "DONE"
except Exception:
    RES["status"] = "FAILED"; RES["error"] = traceback.format_exc()
finally:
    for rel, txt in perturbed.items():
        (ROOT / rel).write_text(txt, encoding="utf-8")
    RES["finished_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()); save()
