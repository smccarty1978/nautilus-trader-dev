"""Phase 8 -- promote the Phase 7 selection to FROZEN_RUNTIME_MODEL/ and
build the complete model_catalog.json across every fitted model in this
study (baseline + 7 ablations + 8 raw-count candidates)."""
from __future__ import annotations

import json
import shutil

from common import ARTIFACTS, RESULTS, ROOT, sha256_file

ALL_MODEL_IDS_IN_ORDER = [
    "F3_695_baseline",
    # Phase 2 family ablations (A_full_695 = the baseline above, reused not refit)
    "F3_live546_gbt_v1",  # Phase 2's "B_live546" ablation -- SAME 546-feature SET as the Phase 5
                          # candidate below, but registry/inventory column ORDER (not ranked order),
                          # a genuinely distinct artifact (different hash) kept for its own
                          # family-ablation role. See STUDY_REPORT.md #11 for why this is _v1 and
                          # the Phase 5 candidate is _v2, not a reuse of this one.
    "F3_ablation_C_f0only_gbt_v1", "F3_ablation_D_ohlcv_gbt_v1", "F3_ablation_E_pricelvl_gbt_v1",
    "F3_ablation_F_f0_ohlcv_gbt_v1", "F3_ablation_G_f0_pricelvl_gbt_v1",
    # Phase 5 raw-count candidates
    "F3_top25_gbt_v1", "F3_top40_gbt_v1", "F3_top60_gbt_v1", "F3_top80_gbt_v1",
    "F3_top100_gbt_v1", "F3_top150_gbt_v1", "F3_top250_gbt_v1", "F3_live546_gbt_v2",
]


def main() -> None:
    decision = json.loads((RESULTS / "selection_gate_decision.json").read_text())
    selected_id = decision["selected_model_id"]

    catalog = []
    for model_id in ALL_MODEL_IDS_IN_ORDER:
        model_dir = ARTIFACTS / model_id
        if not (model_dir / "model.joblib").exists():
            catalog.append({"model_id": model_id, "status": "NOT_TRAINED", "artifact_path": None})
            continue
        manifest = json.loads((model_dir / "manifest.json").read_text())
        gate_row = None
        if (RESULTS / "phase7_gate_results.csv").exists():
            import pandas as pd
            gdf = pd.read_csv(RESULTS / "phase7_gate_results.csv")
            hit = gdf[gdf["model_id"] == model_id]
            if not hit.empty:
                gate_row = hit.iloc[0]["status"]
        status = "frozen" if model_id == selected_id else ("gate_" + gate_row.lower() if gate_row else manifest.get("status", "candidate"))
        catalog.append({
            "model_id": model_id, "n_features": manifest["n_features"],
            "model_sha256": manifest["model_sha256"], "artifact_path": str(model_dir.relative_to(ROOT)),
            "status": status, "selection_verdict": ("SELECTED" if model_id == selected_id else
                                                     (gate_row or "not_a_raw_count_candidate")),
        })
    (RESULTS / "model_catalog.json").write_text(json.dumps({
        "study_decision": decision["decision"], "selected_model_id": selected_id,
        "models": catalog,
    }, indent=2))

    if selected_id is None:
        print(f"No model selected -- decision={decision['decision']}, skipping freeze promotion.")
        (RESULTS / "final_decision.json").write_text(json.dumps(decision, indent=2))
        return

    frozen_dir = ARTIFACTS / "FROZEN_RUNTIME_MODEL"
    frozen_dir.mkdir(parents=True, exist_ok=True)
    src_dir = ARTIFACTS / selected_id
    for fname in ("model.joblib", "feature_list.json", "manifest.json", "metrics_2025.json"):
        shutil.copyfile(src_dir / fname, frozen_dir / fname)
        assert sha256_file(src_dir / fname) == sha256_file(frozen_dir / fname)

    registry_bindings = {}
    feat_list = json.loads((src_dir / "feature_list.json").read_text())["ordered_features"]
    import pandas as pd
    inv = pd.read_csv(RESULTS / "f3_feature_inventory_v2.csv").set_index("name")
    for f in feat_list:
        if f in inv.index:
            registry_bindings[f] = {
                "in_registry": bool(inv.loc[f, "in_registry"]),
                "registry_match_kind": inv.loc[f, "registry_match_kind"],
                "status": inv.loc[f, "status"] if "status" in inv.columns else None,
                "live_tracker_exists": bool(inv.loc[f, "live_tracker_exists"]),
            }
    (frozen_dir / "registry_bindings.json").write_text(json.dumps(registry_bindings, indent=2))

    timing_bindings = {}
    for f in feat_list:
        if f in inv.index:
            timing_bindings[f] = {
                "timing_status": inv.loc[f, "timing_status"],
                "source_timeframe": inv.loc[f, "source_timeframe"] if "source_timeframe" in inv.columns else None,
                "snapshot_anchor": inv.loc[f, "snapshot_anchor"] if "snapshot_anchor" in inv.columns else None,
            }
    (frozen_dir / "feature_timing_bindings.json").write_text(json.dumps(timing_bindings, indent=2))

    gate_row = None
    if (RESULTS / "phase7_gate_results.csv").exists():
        gdf = pd.read_csv(RESULTS / "phase7_gate_results.csv")
        hit = gdf[gdf["model_id"] == selected_id]
        gate_row = hit.iloc[0].to_dict() if not hit.empty else None

    (frozen_dir / "selection_report.md").write_text(
        f"# Frozen runtime model selection\n\n"
        f"**Selected:** `{selected_id}` ({decision['selected_n_features']} features)\n"
        f"**Decision:** `{decision['decision']}`\n\n"
        f"## Gate results\n\n```json\n{json.dumps(gate_row, indent=2, default=str)}\n```\n\n"
        f"## Caveat (audit resolution #1)\n\n"
        f"This selection is validated against the 2025 ranking/selection population only. "
        f"It has NOT been shown to generalize to an unseen year -- 2026 was never touched by "
        f"this study, by design. A separate follow-on study is expected to re-check this "
        f"frozen selection before any live-deployment or production-parity claim.\n"
    )
    print(f"Frozen: {selected_id} -> {frozen_dir}")


if __name__ == "__main__":
    main()
