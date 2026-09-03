"""NEW ATTACK N2 (pass 03): W-1 residual. The fix (a) added an OPTIONAL `expect.canonical_sha256`
and (b) records `model_canonical_sha256` in the TRAIN freeze. Question: does the DEFAULT governed
OOS path detect an estimator substituted AFTER the TRAIN freeze? Runs the real golden lifecycle
into a tmp model_root, freezes, substitutes a different LightGBM booster (refreshing canonical
byte_sha256 + golden expected + expected_sha256 so every self-consistency check passes), then runs
oos() and compares the reported OOS metrics."""
from __future__ import annotations
import hashlib, json, shutil, sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import build_study, GOLDEN, ROOT  # noqa

import pandas as pd  # noqa
from research_workflow.lifecycle_v2 import V2Lifecycle, V2Options  # noqa
from research_workflow.tests.synthetic_primitives import SYNTHETIC_BINDINGS  # noqa
from research_workflow.host.interfaces import BarView  # noqa

res = []


def rec(case, outcome, verdict):
    res.append({"case": case, "outcome": str(outcome)[:400], "verdict": verdict})
    print(f"[{verdict}] {case}\n    {str(outcome)[:400]}")


TD = Path(tempfile.mkdtemp())
MR = TD / "model_root"          # NEVER the real store
study = build_study(TD, "n2_subst")

bars = [BarView(**b) for b in json.loads((GOLDEN / "bars.json").read_text())]
expected = json.loads((GOLDEN / "expected.json").read_text())
NS = 1_000_000_000
session = {"kind": "calendar", "session": "RTH", "rows": [[a * NS, b * NS] for a, b in expected["sessions"]]}
opts = V2Options(execute=True, smoke_date="2030-01-01", datasets_dir=GOLDEN / "datasets",
                 extra_bindings=SYNTHETIC_BINDINGS, bar_source=lambda s, e: bars,
                 session_table_spec=session, in_process_partitions=True, model_root=MR,
                 closure={"outcome": "SYNTHETIC_FLOW_COMPLETE", "terminal_decision": "PLATFORM_V2_FLOW_PROVEN"})
lc = V2Lifecycle(study, repo_root=ROOT, options=opts)


def audit(kind, auditor):
    frozen = json.loads((study / "audit" / "frozen_execution_manifest.json").read_text())["frozen_execution_composite_sha256"]
    name = "pass_01.md" if kind == "causal" else "contract_pass_01.md"
    block = {"verdict": "CLEAR", "audit_type": kind, "study": study.name, "auditor": auditor,
             "audited_execution_composite_sha256": frozen, "critical": 0, "warning": 0, "note": 1}
    p = study / "audit" / name
    p.write_text("# " + kind + "\n\n<!-- AUDIT_SUMMARY_V2_START -->\n" + json.dumps(block) + "\n<!-- AUDIT_SUMMARY_V2_END -->\n", encoding="utf-8")
    from research_workflow.lifecycle_v2 import ingest_audit_report
    ingest_audit_report(study, kind, p)


lc.compile(); lc.prepare(); lc.readiness(); lc.preflight(); lc.tests()
audit("causal", "a"); audit("contract", "b")
lc.seal(); lc.smoke(); lc.collection(); lc.reconcile(); lc.merge(); lc.fit(); lc.freeze()

models = json.loads((study / "artifacts" / "experiment_models.json").read_text())
mid = models["model_id"]
freeze = json.loads((study / "artifacts" / "train_experiment_freeze.json").read_text())
print("\nTRAIN freeze model_hashes:", freeze.get("model_hashes"))
print("TRAIN freeze model_canonical_sha256:", freeze.get("model_canonical_sha256"))

# ---- W-5 re-check: nothing landed in the REAL store ----
from research_workflow.roots import resolve_model_root
real = Path(resolve_model_root()) / "models" / mid
rec("N2-pre V2Options.model_root keeps the fit out of the operator's real store",
    f"model {mid[:16]} in tmp store: {(MR / 'models' / mid).is_dir()}; in REAL store: {real.exists()}",
    "BLOCKED" if (MR / "models" / mid).is_dir() and not real.exists() else "BYPASSED")

# ---- baseline OOS ----
lc.oos(); lc.analyze()
ANALYZE = study / "artifacts" / "experiment_analysis_v2.json"
oos_before = json.loads(ANALYZE.read_text())
m_before = oos_before.get("oos_metrics")
print("\nOOS metrics BEFORE substitution:", json.dumps(m_before))

# ---- substitute a DIFFERENT estimator, self-consistently, under the unchanged model_id ----
import research_workflow.model_store as MS
from research.analysis.modeling import _build_estimator
d = MS.model_dir(mid, MR)
man = json.loads((d / "manifest.json").read_text())
sha_before = man["canonical"]["byte_sha256"]

train_frame = pd.read_parquet(study / "_work" / "controller" / "merged" / "observations.parquet") \
    if (study / "_work" / "controller" / "merged" / "observations.parquet").is_file() else None
gf = pd.read_parquet(d / "golden" / "frame.parquet")
feats = list(man["lineage"]["ordered_inputs"])
other = _build_estimator("lightgbm", 7, {"n_estimators": 30, "max_depth": 3, "num_leaves": 8,
                                         "learning_rate": 0.4, "verbosity": -1})
# fit the impostor on an INVERTED label so its scores are visibly different
y = (gf[feats[0]] > gf[feats[0]].median()).astype(int)
if y.nunique() < 2:
    y = pd.Series([i % 2 for i in range(len(gf))], index=gf.index)
other.fit(gf[feats], 1 - y)

tmpc = TD / "canon2"
newc = MS.save_canonical(other, man["canonical"].get("family", man["lineage"].get("family", "lightgbm")), tmpc)
shutil.copyfile(tmpc / newc["path"], d / "canonical" / man["canonical"]["path"])
man["canonical"]["byte_sha256"] = newc["byte_sha256"]
man["canonical"]["logical_sha256"] = newc.get("logical_sha256")
(d / "manifest.json").write_text(json.dumps(man, indent=1))
scorer = MS.load_canonical(man, d)
gp = d / "golden" / "expected.json"
g = json.loads(gp.read_text())
g["expected_scores"] = [float(v) for v in scorer.scores(gf)]
gp.write_text(json.dumps(g))
man["golden"]["expected_sha256"] = hashlib.sha256(gp.read_bytes()).hexdigest()
(d / "manifest.json").write_text(json.dumps(man, indent=1))
print("\ncanonical byte_sha256:", sha_before[:16], "->", man["canonical"]["byte_sha256"][:16],
      " model_id unchanged:", mid[:16])

# ---- re-run the GOVERNED oos stage on the substituted model ----
try:
    lc.analyze()
    oos_after = json.loads(ANALYZE.read_text())
    m_after = oos_after.get("oos_metrics")
    changed = json.dumps(m_after) != json.dumps(m_before)
    rec("N2a governed analyze() (OOS scoring) after a post-freeze estimator substitution (default expect: study_id only)",
        f"COMPLETED; metrics_changed={changed} before={json.dumps(m_before)} after={json.dumps(m_after)} "
        f"auth_canonical={oos_after.get('model_authentication', {}).get('canonical_sha256', '')[:16]}",
        "BYPASSED")
except Exception as exc:
    rec("N2a governed analyze() (OOS scoring) after a post-freeze estimator substitution",
        f"{type(exc).__name__}: {exc}", "BLOCKED")

# ---- does anything compare the freeze's model_canonical_sha256 back? ----
fz = json.loads((study / "artifacts" / "train_experiment_freeze.json").read_text())
cur = json.loads((MS.model_dir(mid, MR) / "manifest.json").read_text())["canonical"]["byte_sha256"]
rec("N2b TRAIN freeze records the pre-substitution canonical sha (durable evidence exists)",
    f"freeze.model_canonical_sha256={fz.get('model_canonical_sha256')} current_store_canonical={cur[:16]}...",
    "BLOCKED" if fz.get("model_canonical_sha256", {}).get("primary") not in (None, cur) else "BYPASSED")

# ---- the declared-expect enforcement path (the actual W-1 fix) ----
try:
    MS.authenticate_model(mid, expect={"study_id": "n2_subst", "canonical_sha256": sha_before}, model_root=MR)
    rec("N2c authenticate_model with expect.canonical_sha256 = the pre-substitution sha", "AUTHENTICATED", "BYPASSED")
except Exception as exc:
    rec("N2c authenticate_model with expect.canonical_sha256 = the pre-substitution sha",
        f"{type(exc).__name__}: {exc}", "BLOCKED")

print("\n=== RESULTS ===")
print(json.dumps(res, indent=1))
Path(__file__).with_name("n2_results.json").write_text(json.dumps(
    {"results": res, "tmp": str(TD), "oos_before": m_before, "canonical_before": sha_before,
     "canonical_after": man["canonical"]["byte_sha256"], "freeze_model_canonical_sha256": fz.get("model_canonical_sha256")}, indent=1))
print("\nBYPASSED:", json.dumps([r for r in res if r["verdict"] == "BYPASSED"], indent=1))
