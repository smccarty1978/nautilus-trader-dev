"""Reading 2 real-data gates (attempt 2: every smoke runs in a child process -- NT's Rust logger cannot start twice
in one interpreter; attempt 1 aborted at phase B for that reason).

cff  = scratch copy of controlled_feature_family_180s (NQ 2024, 35 instances) windowed to 2024-03-01..2024-03-31 so a
       replay is minutes, reuse declared.  A: baseline.  B (V3): the live iteration-2 shape -- study text edit plus a
       statement appended to research/analysis/diagnostic_ops.py AND research_workflow/lifecycle_v2.py -- must REUSE,
       shadow (the same single partition, i.e. a forced full recompute) must be byte-identical.  D (V1-r): a bound
       provider module perturbed -> REFUSED.  F (V7a): compiler.py perturbed, plan unchanged -> reuse permitted.
       G (V8): research_workflow/host_runner.py made to import an out-of-key module -> smoke REJECTED with
       REPLAY_CLOSURE_ESCAPE.  Every perturbed file is restored (marker file + finally).
es   = scratch copy of es_180s_model_c_portability, TRAIN 2020+2021 recomputed under this branch (V4-r) and compared
       with the live sealed partitions; the partition children's replay traces give P2 (no compiler module traced).
"""
import json, os, shutil, subprocess, sys, time, traceback
from pathlib import Path
import yaml

ROOT = Path(r"C:\Users\Scott McCarty\Projects\Nautilus Trader-collection_latency")
SP = Path(sys.argv[1]); SCR = SP / "r2_studies" / "studies"; OUT = SP / "r2_realdata.json"; MARK = SP / "r2_perturbed.json"
sys.path.insert(0, str(ROOT)); os.chdir(ROOT)
from research_workflow.lifecycle_v2 import V2Lifecycle, V2Options, load_plan

RES = {"phases": [], "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
def save(): OUT.write_text(json.dumps(RES, indent=1, default=str), encoding="utf-8")
def phase(name, **kw): RES["phases"].append({"phase": name, **kw}); save()
def timed(fn):
    t0 = time.perf_counter(); r = fn(); return r, time.perf_counter() - t0
def seal(study, tag):
    (study / "artifacts").mkdir(exist_ok=True)
    (study / "artifacts" / "preexec_audit_seal.json").write_text(json.dumps({"composite_seal_hash": f"scratch-seal-{tag}", "execution_manifest_composite_sha256": f"scratch-mfst-{tag}"}), encoding="utf-8")
def lc(study): return V2Lifecycle(study, repo_root=ROOT, options=V2Options(execute=True, studies_root=SCR))
def write_spec(study, mut):
    body = yaml.safe_load((study / "study.yaml").read_text(encoding="utf-8")); mut(body)
    (study / "study.yaml").write_text(yaml.safe_dump(body, sort_keys=False), encoding="utf-8")
SMOKE_CHILD = ("import sys, json; sys.path.insert(0, r'{root}')\n"
               "from pathlib import Path\nfrom research_workflow.lifecycle_v2 import V2Lifecycle, V2Options, LifecycleV2Error\n"
               "l = V2Lifecycle(Path(r'{study}'), repo_root=Path(r'{root}'), options=V2Options(execute=True, studies_root=Path(r'{scr}')))\n"
               "try:\n    print(json.dumps({{'ok': True, 'result': l.smoke()}}))\n"
               "except LifecycleV2Error as exc:\n    print(json.dumps({{'ok': False, 'error': str(exc)[:300]}}))\n")
def smoke_child(study):
    r = subprocess.run([sys.executable, "-c", SMOKE_CHILD.format(root=ROOT, study=study, scr=SCR)], cwd=str(ROOT), capture_output=True, text=True, timeout=3600)
    line = [l for l in r.stdout.splitlines() if l.startswith("{")]
    return json.loads(line[-1]) if line else {"ok": False, "error": (r.stderr or r.stdout)[-400:]}
def cps(study, tag, smoke=True):
    l = lc(study); l.compile(); l.prepare(); seal(study, tag)
    sm = smoke_child(study) if smoke else None
    if smoke and not sm.get("ok"): raise RuntimeError("SMOKE FAILED: " + str(sm))
    return l, load_plan(study)
def manifest(study, y): return json.loads((study / "_work/controller/partitions/train" / str(y) / "manifest.json").read_text(encoding="utf-8"))
def trace_doc(study): return json.loads((study / "artifacts/replay_closure_trace.json").read_text(encoding="utf-8"))
def fresh(src, sid):
    dst = SCR / sid
    if dst.exists(): shutil.rmtree(dst)
    dst.mkdir(parents=True)
    for f in ("study.yaml", "research_decision.yaml", "SPEC.md"):
        if (src / f).exists(): shutil.copy2(src / f, dst / f)
    return dst

perturbed = {}
def perturb(rel, text):
    p = ROOT / rel; perturbed[rel] = p.read_text(encoding="utf-8"); MARK.write_text(json.dumps(perturbed), encoding="utf-8")
    p.write_text(perturbed[rel] + text, encoding="utf-8")
def restore(rel):
    (ROOT / rel).write_text(perturbed.pop(rel), encoding="utf-8"); MARK.write_text(json.dumps(perturbed), encoding="utf-8")
if MARK.exists():   # a previous aborted attempt left files perturbed
    for rel, txt in json.loads(MARK.read_text(encoding="utf-8")).items():
        (ROOT / rel).write_text(txt, encoding="utf-8")
    MARK.unlink()

try:
    cff = fresh(Path(r"C:\Users\Scott McCarty\Projects\Nautilus Trader-controlled_feature_family_180s\studies\controlled_feature_family_180s"), "controlled_feature_family_180s")
    write_spec(cff, lambda b: (b["chronology"].__setitem__("windows", ["2024-03-01..2024-03-31"]), b["chronology"].__setitem__("partition_reuse", "replay_closure")))
    l, plan_a = cps(cff, "a")
    r, t_coll = timed(l.collection); l.reconcile()
    m = manifest(cff, 2024); td = trace_doc(cff)
    phase("cff_A_baseline", plan=plan_a["plan_sha256"], replay_stage_files=len(plan_a["closure"]["stages"]["replay"]["files"]),
          manifest_files=plan_a["closure"]["file_count"], collection_wall_s=t_coll, rows=m["rows"], candidates_sha=m["candidates_sha256"],
          observations_sha=m["observations_sha256"], result=r.get("partition_reuse"), smoke_verdict=td["verdict"],
          partition_trace_files=(td["runs"][-1]["traced_repo_files"] if td["runs"][-1]["kind"] == "partition" else None))
    base = (m["candidates_sha256"], m["observations_sha256"])

    perturb("research/analysis/diagnostic_ops.py", "\n_R2_LIVE_CASE_PROBE = 1\n")
    perturb("research_workflow/lifecycle_v2.py", "\n_R2_LIVE_CASE_PROBE = 1\n")
    write_spec(cff, lambda b: b["study"].__setitem__("question", b["study"]["question"] + " (analysis-only iteration 2; R2 phase B)"))
    l, plan_b = cps(cff, "b")
    preview = l.partition_reuse_preview("train")
    r, t_coll = timed(l.collection); rc_ = l.reconcile()
    shadow = json.loads((cff / "_work/controller/partition_reuse_shadow.json").read_text(encoding="utf-8"))
    m2 = manifest(cff, 2024)
    phase("cff_B_live_case_shape_V3", plan=plan_b["plan_sha256"], plan_changed=plan_b["plan_sha256"] != plan_a["plan_sha256"],
          manifest_changed=plan_b["closure"]["composite_sha256"] != plan_a["closure"]["composite_sha256"],
          replay_stage_same=plan_b["closure"]["stages"]["replay"]["composite_sha256"] == plan_a["closure"]["stages"]["replay"]["composite_sha256"],
          would_reuse=preview["would_reuse"], reasons=[(p["id"], p["reason"]) for p in preview["partitions"]], collection_wall_s=t_coll,
          result=r.get("partition_reuse"), served_identical=(m2["candidates_sha256"], m2["observations_sha256"]) == base,
          shadow={k: shadow.get(k) for k in ("selected", "status", "shadow_elapsed_s", "comparison")}, reconcile=rc_["status"])
    restore("research/analysis/diagnostic_ops.py"); restore("research_workflow/lifecycle_v2.py")

    perturb("features/trackers/generic_arrival.py", "\n_R2_PROBE = 1\n")
    l, plan_d = cps(cff, "d")
    pv = l.partition_reuse_preview("train")
    phase("cff_D_replay_module_V1r", replay_stage_changed=plan_d["closure"]["stages"]["replay"]["composite_sha256"] != plan_a["closure"]["stages"]["replay"]["composite_sha256"],
          would_reuse=pv["would_reuse"], reasons=[(p["id"], p["reason"]) for p in pv["partitions"]])
    restore("features/trackers/generic_arrival.py")

    perturb("research_workflow/grammar/compiler.py", "\n_R2_PROBE = 1\n")
    l, plan_f = cps(cff, "f")
    pv = l.partition_reuse_preview("train")
    phase("cff_F_compiler_only_V7a", manifest_changed=plan_f["closure"]["composite_sha256"] != plan_a["closure"]["composite_sha256"],
          replay_stage_same=plan_f["closure"]["stages"]["replay"]["composite_sha256"] == plan_a["closure"]["stages"]["replay"]["composite_sha256"],
          would_reuse=pv["would_reuse"], reasons=[(p["id"], p["reason"]) for p in pv["partitions"]])
    restore("research_workflow/grammar/compiler.py")

    perturb("research_workflow/host_runner.py", "\nimport research_workflow.audit_packets_v2 as _r2_escape_probe  # noqa\n")
    l = lc(cff); l.compile(); l.prepare(); seal(cff, "g")
    sm = smoke_child(cff)
    td = trace_doc(cff)
    phase("cff_G_trace_halt_V8", smoke_result=sm, trace_verdict=td["verdict"], escapes=td["escapes"])
    restore("research_workflow/host_runner.py")

    es = fresh(Path(r"C:\Users\Scott McCarty\Projects\Nautilus Trader-es_180s_model_c_portability\studies\es_180s_model_c_portability"), "es_180s_model_c_portability")
    write_spec(es, lambda b: (b["chronology"].__setitem__("train", [2020, 2021]), b["chronology"].__setitem__("partition_reuse", "replay_closure")))
    l, plan_e = cps(es, "a")
    r, t_coll = timed(l.collection); l.reconcile()
    live = {y: json.load(open(rf"C:\Users\SCOTTM~1\AppData\Local\Temp\claude\C--Users-Scott-McCarty-Projects-Nautilus-Trader\c15e87fe-0a12-4f13-b4f8-b76a8289f455\scratchpad\snap_es\{y}\manifest.json")) for y in (2020, 2021)}
    cmp = {}
    for y in (2020, 2021):
        m = manifest(es, y); tr = json.loads((es / "_work/controller/partitions/train" / str(y) / "replay_trace.json").read_text(encoding="utf-8"))
        cmp[y] = {"identical_to_live_sealed": (m["candidates_sha256"], m["observations_sha256"]) == (live[y]["candidates_sha256"], live[y]["observations_sha256"]),
                  "elapsed_s": m["elapsed_s"], "rows": m["rows"], "child_trace_verdict": tr["verdict"], "child_traced_files": tr["traced_repo_files"],
                  "compiler_modules_traced": [f for f in tr["traced_repo_files"] if f in ("research_workflow/grammar/compiler.py", "research_workflow/grammar/expansion.py", "research_workflow/lifecycle_v2.py", "research/analysis/diagnostic_ops.py")]}
    phase("es_V4r_P2", collection_wall_s=t_coll, replay_stage_files=len(plan_e["closure"]["stages"]["replay"]["files"]), manifest_files=plan_e["closure"]["file_count"], years=cmp,
          union_size=len(trace_doc(es)["union"]))
    RES["status"] = "DONE"
except Exception:
    RES["status"] = "FAILED"; RES["error"] = traceback.format_exc()
finally:
    for rel in list(perturbed):
        restore(rel)
    if MARK.exists(): MARK.unlink()
    RES["finished_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()); save()
