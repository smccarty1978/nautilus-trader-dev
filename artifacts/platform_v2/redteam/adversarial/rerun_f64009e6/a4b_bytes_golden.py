"""A4b: reach the canonical-bytes and golden checks by tampering IN PLACE (same model_id, so the
identity recompute still passes and cannot mask the byte/golden checks)."""
from __future__ import annotations
import hashlib, json, shutil, sys, tempfile
from pathlib import Path
import numpy as np, pandas as pd

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT))
from research_workflow.model_store import ModelLineage, authenticate_model, store_model, model_dir  # noqa
from research.analysis.modeling import _build_estimator  # noqa

res = []


def t(name, fn, expect_reject=True):
    try:
        out = fn()
        res.append({"case": name, "outcome": "AUTHENTICATED " + json.dumps(out, default=str)[:140],
                    "verdict": "BYPASSED" if expect_reject else "OK"})
    except Exception as exc:
        res.append({"case": name, "outcome": type(exc).__name__ + ": " + str(exc)[:220],
                    "verdict": "BLOCKED" if expect_reject else "UNEXPECTED_REJECT"})


TD = Path(tempfile.mkdtemp())
MR = TD / "mr"
rng = np.random.default_rng(11)
FEATS = ["f_a", "f_b", "f_c"]
frame = pd.DataFrame({c: rng.normal(size=400) for c in FEATS})
y = (frame["f_a"] > 0).astype(int)
est = _build_estimator("lightgbm", 42, {"n_estimators": 20, "max_depth": 2, "num_leaves": 4, "learning_rate": 0.1, "verbosity": -1})
est.fit(frame[FEATS], y)


def fresh(tag):
    lin = ModelLineage(study_id="adv_b", cell_id=tag, direction="both", target_arm="tp1_sl1", fold_id="final",
                       config_id="C00", seed=42, ordered_inputs=list(FEATS),
                       feature_contract_sha256=hashlib.sha256(json.dumps(list(FEATS)).encode()).hexdigest(),
                       preprocessing_contract_sha256="identity", target_contract_sha256="t" * 64,
                       target_frame_identity="p" * 64, training_population_identity="p" * 64,
                       train_years=[2029], validation_years=[], hyperparameters={}, family="lightgbm",
                       model_role="primary")
    mid = hashlib.sha256(json.dumps(lin.__dict__, sort_keys=True, default=str).encode()).hexdigest()
    store_model(model_id=mid, estimator=est, lineage=lin, tier="registry", selection_status="selected",
                metrics={}, golden_train_frame=frame[FEATS], model_root=MR, golden_rows=400)
    return mid


m0 = fresh("control")
t("control authenticates", lambda: authenticate_model(m0, model_root=MR), expect_reject=False)

m1 = fresh("bytes")
d = model_dir(m1, MR)
man = json.loads((d / "manifest.json").read_text())
c = d / "canonical" / man["canonical"]["path"]
c.write_bytes(c.read_bytes() + b"\n")
t("canonical bytes corrupted in place (model_id untouched)", lambda: authenticate_model(m1, model_root=MR))

m2 = fresh("bytes_and_sha")
d = model_dir(m2, MR)
man = json.loads((d / "manifest.json").read_text())
c = d / "canonical" / man["canonical"]["path"]
c.write_bytes(c.read_bytes() + b"\n")
man["canonical"]["byte_sha256"] = hashlib.sha256(c.read_bytes()).hexdigest()
(d / "manifest.json").write_text(json.dumps(man, indent=1))
t("canonical bytes corrupted AND byte_sha256 updated (id no longer recomputes? / golden must catch)",
  lambda: authenticate_model(m2, model_root=MR))

m3 = fresh("golden")
d = model_dir(m3, MR)
gp = d / "golden" / "expected.json"
g = json.loads(gp.read_text()); g["expected_scores"][0] = float(g["expected_scores"][0]) + 0.5
gp.write_text(json.dumps(g))
t("golden expected.json edited in place (model_id untouched)", lambda: authenticate_model(m3, model_root=MR))

m4 = fresh("golden_and_sha")
d = model_dir(m4, MR)
man = json.loads((d / "manifest.json").read_text())
gp = d / "golden" / "expected.json"
g = json.loads(gp.read_text()); g["expected_scores"][0] = float(g["expected_scores"][0]) + 0.5
gp.write_text(json.dumps(g))
man["golden"]["expected_sha256"] = hashlib.sha256(gp.read_bytes()).hexdigest()
(d / "manifest.json").write_text(json.dumps(man, indent=1))
t("golden expected.json edited AND expected_sha256 refreshed", lambda: authenticate_model(m4, model_root=MR))

m5 = fresh("goldenframe")
d = model_dir(m5, MR)
fr = pd.read_parquet(d / "golden" / "frame.parquet")
fr.iloc[0, 0] = float(fr.iloc[0, 0]) + 3.0
fr.to_parquet(d / "golden" / "frame.parquet", index=False)
t("golden frame.parquet mutated in place", lambda: authenticate_model(m5, model_root=MR))

m6 = fresh("swapmodel")
d = model_dir(m6, MR)
man = json.loads((d / "manifest.json").read_text())
other = _build_estimator("lightgbm", 7, {"n_estimators": 20, "max_depth": 2, "num_leaves": 4, "learning_rate": 0.3, "verbosity": -1})
other.fit(frame[FEATS], (frame["f_b"] > 0).astype(int))
from research_workflow.model_store import save_canonical
tmpdir = Path(tempfile.mkdtemp()) / "canon"
newc = save_canonical(other, "lightgbm", tmpdir)
shutil.copyfile(tmpdir / newc["path"], d / "canonical" / man["canonical"]["path"])
man["canonical"]["byte_sha256"] = newc["byte_sha256"]
man["canonical"]["logical_sha256"] = newc.get("logical_sha256")
(d / "manifest.json").write_text(json.dumps(man, indent=1))
t("DIFFERENT model swapped into canonical/ with byte_sha256 refreshed (golden must catch it)",
  lambda: authenticate_model(m6, model_root=MR))

print(json.dumps(res, indent=1))
Path(__file__).with_name("a4b_results.json").write_text(json.dumps({"results": res, "tmp": str(TD)}, indent=1))
print("\nBYPASSED:", json.dumps([r for r in res if r["verdict"] in ("BYPASSED", "UNEXPECTED_REJECT")], indent=1))

# ---- A4c: full self-consistent model substitution (regenerate golden too) ----
m7 = fresh("full_swap")
d = model_dir(m7, MR)
man = json.loads((d / "manifest.json").read_text())
before = authenticate_model(m7, model_root=MR)
import research_workflow.model_store as _MS
tmp2 = Path(tempfile.mkdtemp()) / "canon2"
newc = save_canonical(other, "lightgbm", tmp2)
shutil.copyfile(tmp2 / newc["path"], d / "canonical" / man["canonical"]["path"])
man["canonical"]["byte_sha256"] = newc["byte_sha256"]
man["canonical"]["logical_sha256"] = newc.get("logical_sha256")
(d / "manifest.json").write_text(json.dumps(man, indent=1))
fr = pd.read_parquet(d / "golden" / "frame.parquet")
scorer = _MS.load_canonical(man, d)
newscores = [float(v) for v in scorer.scores(fr)]
gp = d / "golden" / "expected.json"
g = json.loads(gp.read_text()); g["expected_scores"] = newscores
gp.write_text(json.dumps(g))
man["golden"]["expected_sha256"] = hashlib.sha256(gp.read_bytes()).hexdigest()
(d / "manifest.json").write_text(json.dumps(man, indent=1))
after = None
try:
    after = authenticate_model(m7, model_root=MR)
except Exception as exc:
    after = type(exc).__name__ + ": " + str(exc)[:200]
print("\nA4c FULL SUBSTITUTION")
print(" model_id unchanged:", m7[:16])
print(" canonical sha before:", before["canonical_sha256"][:16], "after:", man["canonical"]["byte_sha256"][:16])
print(" authenticate_model after substitution ->", json.dumps(after, default=str)[:260])
