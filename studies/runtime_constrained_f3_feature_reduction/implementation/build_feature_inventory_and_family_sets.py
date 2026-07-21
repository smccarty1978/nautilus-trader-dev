"""Phase 3 step 1 (run early, needed by Phase 2 family ablations too):
regenerate the F3 feature inventory against the CURRENT features/registry.py
(reusing nt_live_scoring_infra_prereqs' own `classify()` logic verbatim, not
re-implemented) -- writes to THIS study's own results/, never overwrites the
frozen prereqs study's f3_feature_inventory.csv.

Also derives the family-based feature lists needed for Phase 2's ablations
A-G and Phase 4's 546-live-ready candidate pool.
"""
from __future__ import annotations

import json

import pandas as pd

from common import SRC_STUDY, RESULTS, classify_feature, sha256_obj

F0_FAMILY = "regime_median_center_slope_alignment"


def main() -> None:
    feature_sets = json.loads((SRC_STUDY / "_work" / "feature_sets.json").read_text())
    f3 = feature_sets["F3_volume_delta_plus_price_levels"]
    f0_set = set(feature_sets["F0_existing_only"])
    assert len(f3) == 695

    rows = [classify_feature(name, f0_set) for name in f3]
    inv = pd.DataFrame(rows)
    inv.to_csv(RESULTS / "f3_feature_inventory_v2.csv", index=False)

    n_registered = int(inv["in_registry"].sum())
    n_live_tracker = int(inv["live_tracker_exists"].sum())
    by_family = inv.groupby("family").size().sort_values(ascending=False).to_dict()

    # F0 is registered+has an implementation now (MedianCenterTracker), but
    # remains EXCLUDED from all primary candidates in this study per the
    # explicit user decision + SPEC guardrails (retraining only uses F0's
    # EXISTING offline pandas columns for the Phase 2 "C" ablation, never
    # tracker-sourced values, and never as part of any 546-pool candidate).
    live546 = inv[(inv["family"] != F0_FAMILY) & (inv["live_tracker_exists"])]["name"].tolist()
    ohlcv_est_delta = inv[inv["family"] == "ohlcv_est_delta"]["name"].tolist()
    price_level_context = inv[inv["family"] == "price_level_context"]["name"].tolist()
    f0_existing = inv[inv["family"] == F0_FAMILY]["name"].tolist()

    summary = {
        "n_f3_features": len(f3),
        "n_in_registry": n_registered,
        "n_live_tracker_exists": n_live_tracker,
        "note_registry_change_since_prereqs_study": (
            "F0's 149 features are now in_registry=True with live_tracker_exists=True "
            "(MedianCenterTracker, status=provisional) -- excluded here from `live546` by "
            "FAMILY name, not by live_tracker_exists, since that flag alone no longer "
            "distinguishes them post-registration. See SPEC.md Verified Facts + audit resolutions."
        ),
        "by_family": by_family,
        "n_live546": len(live546), "n_ohlcv_est_delta": len(ohlcv_est_delta),
        "n_price_level_context": len(price_level_context), "n_f0_existing": len(f0_existing),
    }
    (RESULTS / "f3_feature_inventory_v2_summary.json").write_text(json.dumps(summary, indent=2))

    family_sets = {
        "A_full_695": f3,
        "B_live546": live546,
        "C_f0_only_149": f0_existing,
        "D_ohlcv_est_delta_214": ohlcv_est_delta,
        "E_price_level_context_332": price_level_context,
        "F_f0_plus_ohlcv": f0_existing + ohlcv_est_delta,
        "G_f0_plus_price_level": f0_existing + price_level_context,
    }
    hashes = {k: sha256_obj(v) for k, v in family_sets.items()}
    (RESULTS / "family_ablation_feature_sets.json").write_text(
        json.dumps({"feature_sets": family_sets, "sha256": hashes}, indent=2))

    print(json.dumps(summary, indent=2))
    print("family set sizes:", {k: len(v) for k, v in family_sets.items()})


if __name__ == "__main__":
    main()
