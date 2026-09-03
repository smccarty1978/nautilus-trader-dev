"""A4 (CRIT-3): model-identity attacks against research_workflow.model_store.authenticate_model.
Uses a throwaway model_root and a throwaway git repo -- the real store is never touched."""
from __future__ import annotations
import json, hashlib, shutil, subprocess, sys, tempfile
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT))
import research_workflow.model_store as MS  # noqa
from research_workflow.model_store import (ModelLineage, ModelStoreError, authenticate_model, store_model,  # noqa
                                           _recompute_legacy_v1_train_freeze_id, model_dir)
from research.analysis.identity import canonical_sha256  # noqa

res = []


def t(name, fn, expect_reject=True):
    try:
        out = fn()
        res.append({"case": name, "outcome": "AUTHENTICATED " + json.dumps(out, default=str)[:160],
                    "verdict": "BYPASSED" if expect_reject else "OK"})
    except Exception as exc:
        res.append({"case": name, "outcome": type(exc).__name__ + ": " + str(exc)[:220],
                    "verdict": "BLOCKED" if expect_reject else "UNEXPECTED_REJECT"})


def git(repo, *a):
    return subprocess.run(["git", *a], cwd=str(repo), capture_output=True, text=True)


TD = Path(tempfile.mkdtemp())
MR = TD / "model_root"
rng = np.random.default_rng(7)
N, FEATS = 400, ["f_a", "f_b", "f_c"]
frame = pd.DataFrame({c: rng.normal(size=N) for c in FEATS})
y = (frame["f_a"] + 0.3 * rng.normal(size=N) > 0).astype(int)

from research.analysis.modeling import _build_estimator
est = _build_estimator("lightgbm", 42, {"n_estimators": 20, "max_depth": 2, "num_leaves": 4, "learning_rate": 0.1, "verbosity": -1})
est.fit(frame[FEATS], y)


def mk_lineage(**over):
    base = dict(study_id="adv_model_study", cell_id="primary", direction="both", target_arm="tp1_sl1",
                fold_id="final", config_id="C00", seed=42, ordered_inputs=list(FEATS),
                feature_contract_sha256=hashlib.sha256(json.dumps(list(FEATS)).encode()).hexdigest(),
                preprocessing_contract_sha256="identity",
                target_contract_sha256="t" * 64, target_frame_identity="p" * 64,
                training_population_identity="p" * 64, train_years=[2029, 2030], validation_years=[],
                hyperparameters={"n_estimators": 20}, family="lightgbm", model_role="primary")
    base.update(over)
    return ModelLineage(**base)


lin = mk_lineage()
MODEL_ID = hashlib.sha256(json.dumps(lin.__dict__, sort_keys=True, default=str).encode()).hexdigest()
store_model(model_id=MODEL_ID, estimator=est, lineage=lin, tier="registry", selection_status="selected",
            metrics={}, golden_train_frame=frame[FEATS], model_root=MR, golden_rows=N)
print("stored", MODEL_ID[:16])

t("control: freshly stored v2 model authenticates",
  lambda: authenticate_model(MODEL_ID, model_root=MR), expect_reject=False)

# --- 1. copy under another id, editing manifest.model_id to match the new dir ---
alt = "1" * 64
shutil.copytree(model_dir(MODEL_ID, MR), model_dir(alt, MR))
mp = model_dir(alt, MR) / "manifest.json"
m = json.loads(mp.read_text()); m["model_id"] = alt
mp.write_text(json.dumps(m, indent=1))
t("copied model dir under a new id with manifest.model_id edited to match",
  lambda: authenticate_model(alt, model_root=MR))

# --- 2. corrupt the canonical bytes ---
alt2 = "2" * 64
shutil.copytree(model_dir(MODEL_ID, MR), model_dir(alt2, MR))
m2p = model_dir(alt2, MR) / "manifest.json"
m2 = json.loads(m2p.read_text()); m2["model_id"] = alt2
m2p.write_text(json.dumps(m2, indent=1))
canon = model_dir(alt2, MR) / "canonical" / m2["canonical"]["path"]
canon.write_bytes(canon.read_bytes() + b"\n# tampered\n")
t("corrupted canonical bytes", lambda: authenticate_model(alt2, model_root=MR))

# --- 3. edit the golden expected scores ---
alt3 = "3" * 64
shutil.copytree(model_dir(MODEL_ID, MR), model_dir(alt3, MR))
m3p = model_dir(alt3, MR) / "manifest.json"
m3 = json.loads(m3p.read_text()); m3["model_id"] = alt3
m3p.write_text(json.dumps(m3, indent=1))
gp = model_dir(alt3, MR) / "golden" / "expected.json"
g = json.loads(gp.read_text()); g["expected_scores"][0] = 0.123456
gp.write_text(json.dumps(g))
t("tampered golden expected.json", lambda: authenticate_model(alt3, model_root=MR))

# --- 4. reorder ordered_inputs (model_id recomputed so identity still matches) ---
lin_r = mk_lineage(ordered_inputs=["f_c", "f_a", "f_b"])
rid = hashlib.sha256(json.dumps(lin_r.__dict__, sort_keys=True, default=str).encode()).hexdigest()
store_model(model_id=rid, estimator=est, lineage=lin_r, tier="registry", selection_status="selected",
            metrics={}, golden_train_frame=frame[["f_c", "f_a", "f_b"]], model_root=MR, golden_rows=N)
# now silently reorder ordered_inputs in the STORED manifest without touching model_id
rp = model_dir(rid, MR) / "manifest.json"
r = json.loads(rp.read_text()); r["lineage"]["ordered_inputs"] = ["f_a", "f_b", "f_c"]
rp.write_text(json.dumps(r, indent=1))
t("ordered_inputs reordered in the stored manifest after the id was fixed",
  lambda: authenticate_model(rid, model_root=MR))

# --- 5. every legacy identity_rule with a fabricated legacy_registry_record ---
for rule in ("legacy_v1_immutable_unrecomputable", "legacy_v1_committed_registry",
             "legacy_v1_train_freeze", "totally_made_up_rule", None):
    aid = hashlib.sha256(("rule" + str(rule)).encode()).hexdigest()
    shutil.copytree(model_dir(MODEL_ID, MR), model_dir(aid, MR))
    p = model_dir(aid, MR) / "manifest.json"
    mm = json.loads(p.read_text())
    mm["model_id"] = aid
    if rule is None:
        mm.pop("identity_rule", None)
    else:
        mm["identity_rule"] = rule
    mm["legacy_registry_record"] = {"arm": "long_lightgbm", "runtime_identity_sha256": "9" * 64,
                                    "train_freeze_path": "studies/fake/artifacts/train_experiment_freeze.json",
                                    "train_freeze_sha256": "8" * 64}
    p.write_text(json.dumps(mm, indent=1))
    t("identity_rule=" + str(rule) + " with a fabricated legacy_registry_record",
      lambda a=aid: authenticate_model(a, model_root=MR, repo_root=ROOT))

# --- 6. ledger tier reuse ---
lin_l = mk_lineage(cell_id="ledger_cell")
lid = hashlib.sha256(json.dumps(lin_l.__dict__, sort_keys=True, default=str).encode()).hexdigest()
store_model(model_id=lid, estimator=est, lineage=lin_l, tier="ledger", selection_status="candidate",
            metrics={}, golden_train_frame=frame[FEATS], model_root=MR, golden_rows=N)
t("ledger-tier / candidate model reused for scoring", lambda: authenticate_model(lid, model_root=MR))

# --- 7. expect mismatch ---
t("expect study_id mismatch", lambda: authenticate_model(MODEL_ID, model_root=MR, expect={"study_id": "some_other"}))
t("expect target_arm mismatch", lambda: authenticate_model(MODEL_ID, model_root=MR, expect={"target_arm": "tp2_sl2"}))
t("expect direction mismatch", lambda: authenticate_model(MODEL_ID, model_root=MR, expect={"direction": "long"}))
t("expect matching (control)", lambda: authenticate_model(MODEL_ID, model_root=MR,
                                                          expect={"study_id": "adv_model_study", "target_arm": "tp1_sl1"}),
  expect_reject=False)

# --- 8. preprocessing declared non-identity ---
pid = "4" * 64
shutil.copytree(model_dir(MODEL_ID, MR), model_dir(pid, MR))
pp = model_dir(pid, MR) / "manifest.json"
pm = json.loads(pp.read_text()); pm["model_id"] = pid
pm["lineage"]["preprocessing_contract_sha256"] = "standard_scaler_v1"
pp.write_text(json.dumps(pm, indent=1))
t("manifest declares non-identity preprocessing", lambda: authenticate_model(pid, model_root=MR))

# ================= ADJACENT: fabricate a legacy_v1_train_freeze authority =================
repo = TD / "fakerepo"
(repo / "studies").mkdir(parents=True)
git(repo, "init", "-q"); git(repo, "config", "user.email", "a@b.c"); git(repo, "config", "user.name", "a")
(repo / "README.md").write_text("x\n", encoding="utf-8")
git(repo, "add", "-A"); git(repo, "commit", "-qm", "init")

FAKE_STUDY = "totally_fabricated_v1_study"
ARM = "long_lightgbm"
FIT_ID = "f" * 64
freeze = {"schema_version": 1, "study_id": FAKE_STUDY, "provenance": "TRAIN_ONLY",
          "model_hashes": {ARM: FIT_ID}, "feature_sets": {"lightgbm": list(FEATS)},
          "generated_at_utc": "2026-01-01T00:00:00+00:00"}
freeze["freeze_sha256"] = canonical_sha256({k: v for k, v in freeze.items()
                                            if k not in ("generated_at_utc", "freeze_sha256")})
fdir = repo / "studies" / FAKE_STUDY / "artifacts"
fdir.mkdir(parents=True)
freeze_rel = "studies/" + FAKE_STUDY + "/artifacts/train_experiment_freeze.json"
(repo / freeze_rel).write_text(json.dumps(freeze, indent=1), encoding="utf-8")

fake_id = _recompute_legacy_v1_train_freeze_id(FAKE_STUDY, ARM, FIT_ID, freeze["freeze_sha256"])
lin_f = mk_lineage(study_id=FAKE_STUDY, fit_identity_sha256=FIT_ID, ordered_inputs=list(FEATS))
store_model(model_id=fake_id, estimator=est, lineage=lin_f, tier="registry", selection_status="selected",
            metrics={}, golden_train_frame=frame[FEATS], model_root=MR, golden_rows=N,
            identity_rule="legacy_v1_train_freeze",
            legacy_registry_record={"arm": ARM, "train_freeze_path": freeze_rel,
                                    "train_freeze_sha256": hashlib.sha256((repo / freeze_rel).read_bytes()).hexdigest()})
t("ADJACENT: fabricated but self-consistent TRAIN freeze, NOT in git at all",
  lambda: authenticate_model(fake_id, model_root=MR, repo_root=repo))
git(repo, "add", freeze_rel)
print("freeze ls-files:", git(repo, "ls-files", freeze_rel).stdout.strip())
t("ADJACENT: same fabricated freeze after `git add` ONLY (never committed)",
  lambda: authenticate_model(fake_id, model_root=MR, repo_root=repo))

# ADJACENT: committed freeze whose bytes are then rewritten in the working tree
git(repo, "commit", "-qm", "freeze")
freeze2 = dict(freeze)
freeze2["model_hashes"] = {ARM: "e" * 64}          # a DIFFERENT fit is now vouched for
freeze2.pop("freeze_sha256")
freeze2["freeze_sha256"] = canonical_sha256({k: v for k, v in freeze2.items()
                                             if k not in ("generated_at_utc", "freeze_sha256")})
(repo / freeze_rel).write_text(json.dumps(freeze2, indent=1), encoding="utf-8")
fake_id2 = _recompute_legacy_v1_train_freeze_id(FAKE_STUDY, ARM, "e" * 64, freeze2["freeze_sha256"])
lin_f2 = mk_lineage(study_id=FAKE_STUDY, fit_identity_sha256="e" * 64, cell_id="swapped")
store_model(model_id=fake_id2, estimator=est, lineage=lin_f2, tier="registry", selection_status="selected",
            metrics={}, golden_train_frame=frame[FEATS], model_root=MR, golden_rows=N,
            identity_rule="legacy_v1_train_freeze",
            legacy_registry_record={"arm": ARM, "train_freeze_path": freeze_rel,
                                    "train_freeze_sha256": hashlib.sha256((repo / freeze_rel).read_bytes()).hexdigest()})
print("HEAD freeze_sha256:", json.loads(git(repo, "show", "HEAD:" + freeze_rel).stdout)["freeze_sha256"][:16],
      "worktree:", freeze2["freeze_sha256"][:16])
t("ADJACENT: committed freeze rewritten in the working tree to vouch for a different fit",
  lambda: authenticate_model(fake_id2, model_root=MR, repo_root=repo))
# does the rule check the STUDY'S OWN SEAL? there is none in this fabricated study:
print("fabricated study has a seal:", (repo / "studies" / FAKE_STUDY / "artifacts" / "preexec_audit_seal.json").is_file())

# ADJACENT: fabricated legacy_v1_committed_registry record
reg_rel = "studies/model_registry"
(repo / reg_rel).mkdir(parents=True, exist_ok=True)
cid = "5" * 64
shutil.copytree(model_dir(MODEL_ID, MR), model_dir(cid, MR))
cp = model_dir(cid, MR) / "manifest.json"
cm = json.loads(cp.read_text()); cm["model_id"] = cid
cm["identity_rule"] = "legacy_v1_committed_registry"
cm["legacy_registry_record"] = {"runtime_identity_sha256": "7" * 64}
cp.write_text(json.dumps(cm, indent=1))
(repo / reg_rel / (cid + ".json")).write_text(json.dumps({
    "model_id": cid, "study_id": "adv_model_study", "runtime_identity_sha256": "7" * 64,
    "artifact_sha256": cm["canonical"]["byte_sha256"],
    "native_booster_sha256": cm["canonical"]["byte_sha256"]}, indent=1), encoding="utf-8")
git(repo, "add", reg_rel)
t("ADJACENT: fabricated studies/model_registry record, `git add` only (never committed)",
  lambda: authenticate_model(cid, model_root=MR, repo_root=repo))

print(json.dumps(res, indent=1))
Path(__file__).with_name("a4_results.json").write_text(json.dumps({"results": res, "tmp": str(TD)}, indent=1))
print("\nBYPASSED:", json.dumps([r for r in res if r["verdict"] in ("BYPASSED", "UNEXPECTED_REJECT")], indent=1))
