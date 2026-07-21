"""Phase 1 -- inventory all 695 F3 features against the central feature
registry, correcting the initial scout-pass claim (both `repo-scout` and
`contract-checker` reported "almost none of F3 is registered" / "~90
total registry entries") -- verified directly and found substantially
wrong: `features/registry.py` has 502 entries, and 546/695 (78.6%) of F3
trace to registered, `status="verified"` implementations with genuine
live NT-callback trackers (`features/trackers/price_levels.py`,
`features/trackers/ohlcv_delta.py` -- both expose `update`/`update_1m` +
`calculate` methods, not pandas-batch wrappers). The real, concrete gap
is F0's 149 "existing" features (regime/median-center slope/alignment),
which are 0% registered and trace to pandas-batch-only code in
`studies/regime_sequence_chop_context/build_median_centers.py`
(`compute_rolling_slopes`, `.shift(N)` -- vectorized, no live equivalent
anywhere).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RESULTS = HERE / "results"
RESULTS.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT))

from features.registry import FEATURE_REGISTRY  # noqa: E402

ENRICHED_RETRAIN = ROOT / "studies" / "short_rth_enriched_volume_level_retrain"
DUMMY_SUFFIX_RE = re.compile(r"(.+)__(ABOVE|BELOW|TOUCH|UNAVAILABLE)$")

F0_SOURCE = {
    "source_script": "studies/regime_sequence_chop_context/build_median_centers.py",
    "source_function": "build_median_centers_df / compute_rolling_slopes",
    "notes": "pandas-batch rolling-window computation (df['x'].shift(N), rolling slopes on 1s data); "
             "no live NT-callback tracker exists anywhere in the repo for this family.",
}

# Phase 3's feature-timing causal spec (results/feature_timing_causal_spec.md,
# "Open item not independently verified in this pass") explicitly discloses
# that `regime_starts`' own construction (canonical_regime_timeline /
# timeline_from_flips) was not traced to the same depth as the feature
# trackers. Per SPEC.md's own Phase 3 rule ("Any feature family whose timing
# cannot be confirmed causal within this phase is flagged as
# TIMING_UNVERIFIED in the Phase 1 inventory, not silently assumed
# correct"), every regime-relative (A4) feature must carry that flag --
# added here after the completion-gate audit caught it being silently
# omitted despite the disclosure already existing in the spec doc.
_TIMING_UNVERIFIED_NAMES = {
    "regime_available", "regime_vol_sum", "regime_est_delta_sum",
    "regime_est_delta_ratio", "regime_est_abs_delta_sum", "regime_elapsed_seconds",
    "regime_volume_per_second", "regime_price_change_atr", "regime_range_atr",
    "regime_volume_per_atr_moved", "regime_abs_delta_per_atr_moved",
    "regime_first_half_est_delta_ratio", "regime_second_half_est_delta_ratio",
    "regime_late_minus_early_delta_ratio", "regime_first_half_vol",
    "regime_second_half_vol", "regime_late_vs_early_vol_ratio",
}


def classify(name: str, f0_set: set) -> dict:
    row = {"name": name, "in_f0": name in f0_set,
           "timing_status": "TIMING_UNVERIFIED" if name in _TIMING_UNVERIFIED_NAMES else "verified"}
    if name in FEATURE_REGISTRY:
        d = FEATURE_REGISTRY[name]
        # `live_tracker_exists` must not be conflated with `in_registry`: a
        # registered feature with status="verified" but no `implementation`
        # set (e.g. the 5 hand-written `context`-family entries) is
        # registered metadata WITHOUT a live tracker -- flagged separately
        # rather than silently defaulting live_tracker_exists=False without
        # a distinguishing reason (completion-gate audit Note).
        row.update({
            "in_registry": True, "registry_match_kind": "exact",
            "status": d.status, "family": d.family,
            "source_timeframe": d.source_timeframe, "update_anchor": d.update_anchor,
            "snapshot_anchor": d.snapshot_anchor, "warmup": d.warmup,
            "null_policy": d.null_policy, "implementation": d.implementation,
            "live_tracker_exists": bool(d.implementation),
            "registered_without_implementation": d.status == "verified" and not d.implementation,
            "source_script": d.implementation or "UNRESOLVED",
            "source_function": "n/a (class-based tracker)",
        })
        return row

    m = DUMMY_SUFFIX_RE.match(name)
    if m and m.group(1) in FEATURE_REGISTRY:
        base = m.group(1)
        d = FEATURE_REGISTRY[base]
        row.update({
            "in_registry": True, "registry_match_kind": f"one_hot_dummy_of:{base}",
            "status": d.status, "family": d.family,
            "source_timeframe": d.source_timeframe, "update_anchor": d.update_anchor,
            "snapshot_anchor": d.snapshot_anchor, "warmup": d.warmup,
            "null_policy": d.null_policy, "implementation": d.implementation,
            "live_tracker_exists": bool(d.implementation),
            "registered_without_implementation": d.status == "verified" and not d.implementation,
            "source_script": d.implementation or "UNRESOLVED",
            "source_function": "n/a (one-hot expansion of registered categorical base)",
        })
        return row

    if name in f0_set:
        row.update({
            "in_registry": False, "registry_match_kind": "none", "status": "unregistered",
            "family": "regime_median_center_slope_alignment",
            "source_timeframe": "1s->1m/5m/15m/30m rolling", "update_anchor": "UNRESOLVED",
            "snapshot_anchor": "UNRESOLVED", "warmup": "UNRESOLVED", "null_policy": "UNRESOLVED",
            "implementation": "", "live_tracker_exists": False, "registered_without_implementation": False,
            **F0_SOURCE,
        })
        return row

    row.update({
        "in_registry": False, "registry_match_kind": "none", "status": "unregistered",
        "family": "UNRESOLVED", "source_timeframe": "UNRESOLVED", "update_anchor": "UNRESOLVED",
        "snapshot_anchor": "UNRESOLVED", "warmup": "UNRESOLVED", "null_policy": "UNRESOLVED",
        "implementation": "", "live_tracker_exists": False, "registered_without_implementation": False,
        "source_script": "UNRESOLVED", "source_function": "UNRESOLVED",
    })
    return row


def main() -> None:
    feature_sets = json.loads((ENRICHED_RETRAIN / "_work" / "feature_sets.json").read_text(encoding="utf-8"))
    f3 = feature_sets["F3_volume_delta_plus_price_levels"]
    f0_set = set(feature_sets["F0_existing_only"])
    if len(f3) != 695:
        raise RuntimeError(f"expected 695 F3 features, found {len(f3)}")

    rows = [classify(name, f0_set) for name in f3]
    inv = pd.DataFrame(rows)
    inv.to_csv(RESULTS / "f3_feature_inventory.csv", index=False)

    n_registered = int(inv["in_registry"].sum())
    n_live_tracker = int(inv["live_tracker_exists"].sum())
    n_timing_unverified = int((inv["timing_status"] == "TIMING_UNVERIFIED").sum())
    summary = {
        "n_f3_features": len(f3),
        "n_in_registry": n_registered,
        "n_not_in_registry": len(f3) - n_registered,
        "n_live_tracker_exists": n_live_tracker,
        "n_live_tracker_missing": len(f3) - n_live_tracker,
        "pct_live_tracker_exists": round(n_live_tracker / len(f3), 4),
        "n_timing_unverified": n_timing_unverified,
        "timing_unverified_names": sorted(inv[inv["timing_status"] == "TIMING_UNVERIFIED"]["name"].tolist()),
        "by_family": inv.groupby("family").size().sort_values(ascending=False).to_dict(),
        "by_registry_match_kind": inv["registry_match_kind"].value_counts().to_dict(),
        "unresolved_features": inv[inv["source_script"] == "UNRESOLVED"]["name"].tolist(),
    }
    (RESULTS / "f3_feature_inventory_summary.json").write_text(
        json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
