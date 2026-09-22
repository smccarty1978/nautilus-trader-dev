"""Acceptance proof: the requesting study's frozen surface compiles on this capability with the
partition-reuse key unchanged (d917443a...), using the REAL atlas study.yaml as the collection contract."""
import copy, json, sys, tempfile
from pathlib import Path
import yaml

ROOT = Path.cwd(); sys.path.insert(0, str(ROOT))
from research_workflow.grammar.compiler import compile_study, load_spec        # noqa: E402
from research_workflow.replay_closure import replay_plan_sha256                # noqa: E402

ATLAS = Path(r"C:\Users\Scott McCarty\Projects\Nautilus Trader-nq_mtf_regime_structural_geometry_atlas\studies\nq_mtf_regime_structural_geometry_atlas")
base = yaml.safe_load((ATLAS / "study.yaml").read_text(encoding="utf-8"))
work = Path(tempfile.mkdtemp())

# The frozen predictive-ranking feature surface: MTF directions, current 5m/15m/1h geometry,
# prior 5m/15m/1h geometry. Every entry is an existing metadata column of the audited atlas frame.
TF = ["5m", "15m", "1h"]
SURFACE = ["dir_1m", "atr_entry_1m", "checkpoint_seconds_since_flip"]
SURFACE += [f"dir_{t}" for t in TF]
SURFACE += [f"{p}_{t}" for t in TF for p in ("age_s", "bars", "start_price", "atr", "frozen_atr", "mfe_atr", "mae_atr", "pnl_atr",
                                             "retained", "highest_high", "lowest_low")]
SURFACE += [f"prior_{p}_{t}" for t in TF for p in ("dir", "start_price", "end_price", "frozen_atr", "duration_s", "bars",
                                                   "mfe_price", "mae_price", "mfe_atr", "mae_atr", "terminal_displacement_atr",
                                                   "rotation_seq")]
MODEL = {"mode": "train", "family": "lightgbm",
         "params": {"n_estimators": 300, "learning_rate": 0.05, "num_leaves": 31, "min_child_samples": 50,
                    "subsample": 0.8, "colsample_bytree": 0.8, "verbosity": -1, "random_state": 42},
         "validation": {"protocol": "validation.model_selection.random", "tuning_years": [2023],
                        "final_train_validation_years": [2024]},
         "feature_columns": SURFACE}


def compile_variant(name, body):
    d = work / name; d.mkdir(parents=True, exist_ok=True)
    body = copy.deepcopy(body); body["study"]["id"] = name
    (d / "study.yaml").write_text(yaml.safe_dump(body, sort_keys=False), encoding="utf-8")
    return compile_study(load_spec(d), repo_root=ROOT)


no_model = copy.deepcopy(base); no_model.pop("analysis", None); no_model["model"] = "none"
r0 = compile_variant("pr_no_model", no_model)
with_model = copy.deepcopy(no_model); with_model["model"] = MODEL
r1 = compile_variant("pr_with_model", with_model)

out = {"requested_surface_size": len(SURFACE), "atlas_reuse_key_from_probe": "d917443a59fdd79ea37a9dc3269d0c780f5d37583943c0d24452dc04b90b4578"}
out["no_model"] = {"ok": r0.ok, "replay_plan_sha256": (replay_plan_sha256(r0.plan.to_dict()) if r0.ok else None)}
out["with_model_feature_columns"] = {"ok": r1.ok, "card": (None if r1.ok else r1.card())}
if r1.ok:
    p1, p0 = r1.plan.to_dict(), r0.plan.to_dict()
    meta = {m["column"] for m in p1["columns"]["metadata"]}
    out["with_model_feature_columns"].update({
        "replay_plan_sha256": replay_plan_sha256(p1),
        "reuse_key_matches_atlas": replay_plan_sha256(p1) == out["atlas_reuse_key_from_probe"],
        "reuse_key_matches_no_model": replay_plan_sha256(p1) == replay_plan_sha256(p0),
        "plan_sha_differs_from_no_model": p1["plan_sha256"] != p0["plan_sha256"],
        "model_surface_size": len(p1["model"]["feature_columns"]),
        "surface_is_all_metadata": sorted(set(SURFACE) - meta) == [],
        "observation_sections_identical": all(p1[s] == p0[s] for s in ("streams", "trackers", "population", "triggers", "outcome", "columns", "warmup", "availability")),
        "collection_closure_identical": p1["closure"]["stages"] == p0["closure"]["stages"],
        "validation": p1["model"]["validation"],
        "first_10_inputs": p1["model"]["feature_columns"][:10]})
# refusal check on the real surface: an outcome column of THIS study
bad = copy.deepcopy(with_model); bad["model"] = {**MODEL, "feature_columns": SURFACE + ["terminal_gross_pnl_atr"]}
r2 = compile_variant("pr_leak", bad)
out["outcome_column_refused"] = {"ok": r2.ok, "message": (None if r2.ok else r2.card()["gaps"][0]["message"])}
print(json.dumps(out, indent=1, default=str)[:3000])
Path(sys.argv[1]).write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
