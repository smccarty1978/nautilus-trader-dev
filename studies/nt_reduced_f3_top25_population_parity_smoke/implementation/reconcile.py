"""Phases 5-7 -- candidate/feature/score/trigger/trade parity reconciliation
between the offline March 2025 reference and the live NT run(s)."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

import common as C

FEATURE_TOL_ABS = 1e-6
FEATURE_TOL_REL = 1e-6
SCORE_TOL = 1e-9


def load_offline():
    return pd.read_parquet(C.RESULTS / "offline_candidates_march_2025.parquet")


def load_live(variant_dir: Path) -> pd.DataFrame:
    df = pd.read_parquet(variant_dir / "candidates.parquet")
    if len(df) == 0:
        return df
    return df


def candidate_population_parity(offline: pd.DataFrame, live: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """FIX (reconciliation-gate bug): compares against `final_candidate_eligible`
    (established_regime_gate AND decision_rth AND valid_fill), NOT raw
    `established_regime_gate` alone. The offline reference's population IS
    already established+RTH+valid-fill (entry_surface.py's own funnel) --
    comparing it against raw established_regime_gate silently compares two
    different denominators (an earlier bug: 90,973 raw established_regime_gate
    candidates vs the offline reference's 15,983 -- not actually comparable,
    since the live count included every session, not just RTH)."""
    off_established = offline[["regime_start_ns", "checkpoint_index", "observation_time"]].copy()
    off_established["key"] = list(zip(off_established["regime_start_ns"], off_established["checkpoint_index"]))
    off_keys = set(off_established["key"])

    live_established = live[live["final_candidate_eligible"] == True].copy()  # noqa: E712
    if len(live_established):
        live_established["key"] = list(zip(live_established["regime_start_ns"], live_established["checkpoint_index"]))
        live_keys = set(live_established["key"])
    else:
        live_keys = set()

    both = off_keys & live_keys
    off_only = off_keys - live_keys
    live_only = live_keys - off_keys

    off_dupe = off_established["key"].duplicated().sum()
    live_dupe = live_established["key"].duplicated().sum() if len(live_established) else 0

    rows = []
    for k in sorted(off_only):
        rows.append({"regime_start_ns": k[0], "checkpoint_index": k[1], "bucket": "offline_only"})
    for k in sorted(live_only):
        rows.append({"regime_start_ns": k[0], "checkpoint_index": k[1], "bucket": "live_only"})
    for k in sorted(both):
        rows.append({"regime_start_ns": k[0], "checkpoint_index": k[1], "bucket": "offline_and_live"})

    n_total_offline = len(off_keys)
    explained_agreement = len(both) / n_total_offline if n_total_offline else float("nan")

    summary = {
        "n_offline_established": len(off_keys), "n_live_established": len(live_keys),
        "n_both": len(both), "n_offline_only": len(off_only), "n_live_only": len(live_only),
        "n_offline_duplicate_keys": int(off_dupe), "n_live_duplicate_keys": int(live_dupe),
        "explained_candidate_key_agreement_pct": explained_agreement,
    }
    return pd.DataFrame(rows), summary


def feature_and_score_parity(offline: pd.DataFrame, live: pd.DataFrame, feat_list: list[str]) -> tuple[pd.DataFrame, dict, pd.DataFrame, dict]:
    live_established = live[live["final_candidate_eligible"] == True].copy()  # noqa: E712
    off = offline.copy()
    off["key"] = list(zip(off["regime_start_ns"], off["checkpoint_index"]))
    live_established["key"] = list(zip(live_established["regime_start_ns"], live_established["checkpoint_index"]))
    merged = off.merge(live_established, on="key", suffixes=("_off", "_live"), how="inner")

    feat_rows = []
    for f in feat_list:
        off_col, live_col = f"{f}_off", f"feat__{f}"
        if off_col not in merged.columns:
            off_col = f  # unsuffixed if no name collision
        if live_col not in merged.columns:
            feat_rows.append({"feature": f, "rows_compared": 0, "note": "live column not found"})
            continue
        off_v = pd.to_numeric(merged[off_col], errors="coerce")
        live_v = pd.to_numeric(merged[live_col], errors="coerce")
        both_avail = off_v.notna() & live_v.notna()
        both_null = off_v.isna() & live_v.isna()
        null_mask_disagree = (off_v.isna() != live_v.isna()).sum()
        diffs = (off_v - live_v).abs()
        max_abs = float(diffs[both_avail].max()) if both_avail.any() else float("nan")
        mean_abs = float(diffs[both_avail].mean()) if both_avail.any() else float("nan")
        rel = diffs[both_avail] / off_v[both_avail].abs().clip(lower=1e-9)
        max_rel = float(rel.max()) if both_avail.any() else float("nan")
        exact_matches = int((diffs[both_avail] <= FEATURE_TOL_ABS).sum())
        first_mismatch_idx = diffs[both_avail & (diffs > FEATURE_TOL_ABS)].index
        first_mismatch_key = merged.loc[first_mismatch_idx[0], "key"] if len(first_mismatch_idx) else None
        feat_rows.append({
            "feature": f, "rows_compared": int(both_avail.sum()), "exact_matches": exact_matches,
            "null_mask_disagreements": int(null_mask_disagree), "max_abs_diff": max_abs,
            "mean_abs_diff": mean_abs, "max_rel_diff": max_rel,
            "first_mismatch_candidate_key": str(first_mismatch_key) if first_mismatch_key else None,
        })
    feat_df = pd.DataFrame(feat_rows)
    feat_summary = {
        "n_features": len(feat_list),
        "pct_cells_within_tolerance": (
            feat_df["exact_matches"].sum() / feat_df["rows_compared"].sum()
            if feat_df["rows_compared"].sum() else float("nan")),
        "n_features_with_any_null_mask_disagreement": int((feat_df["null_mask_disagreements"] > 0).sum()),
    }

    off_score = pd.to_numeric(merged["score_off"] if "score_off" in merged else merged["score"], errors="coerce")
    live_score = pd.to_numeric(merged["score_live"] if "score_live" in merged else merged["score"], errors="coerce")
    both_avail = off_score.notna() & live_score.notna()
    score_rows = pd.DataFrame({"key": merged["key"], "score_off": off_score, "score_live": live_score,
                               "abs_diff": (off_score - live_score).abs()})
    score_summary = {
        "n_compared": int(both_avail.sum()),
        "max_abs_score_diff": float(score_rows.loc[both_avail, "abs_diff"].max()) if both_avail.any() else float("nan"),
        "mean_abs_score_diff": float(score_rows.loc[both_avail, "abs_diff"].mean()) if both_avail.any() else float("nan"),
        "score_pearson_corr": float(off_score[both_avail].corr(live_score[both_avail])) if both_avail.sum() > 1 else float("nan"),
        "score_rank_corr": float(off_score[both_avail].corr(live_score[both_avail], method="spearman")) if both_avail.sum() > 1 else float("nan"),
    }
    return feat_df, feat_summary, score_rows, score_summary


def trigger_trade_parity(offline: pd.DataFrame, live: pd.DataFrame, trades_off: pd.DataFrame,
                         trades_live: pd.DataFrame, variant: str) -> pd.DataFrame:
    trig_col_off = "r5_trigger" if variant == "R5" else "r2_5_trigger"
    trig_col_live = "r5_trigger" if variant == "R5" else "r2_5_trigger"

    off_trig = offline[offline[trig_col_off]].copy()
    off_trig["key"] = list(zip(off_trig["regime_start_ns"], off_trig["checkpoint_index"]))
    live_est = live[live["final_candidate_eligible"] == True].copy()  # noqa: E712
    if len(live_est) and trig_col_live in live_est.columns:
        live_trig = live_est[live_est[trig_col_live] == True].copy()  # noqa: E712
        live_trig["key"] = list(zip(live_trig["regime_start_ns"], live_trig["checkpoint_index"]))
    else:
        live_trig = pd.DataFrame(columns=["key"])

    off_keys, live_keys = set(off_trig["key"]), set(live_trig["key"]) if len(live_trig) else set()
    rows = []
    for k in sorted(off_keys & live_keys):
        rows.append({"key": k, "bucket": "A_same_trigger"})
    for k in sorted(off_keys - live_keys):
        rows.append({"key": k, "bucket": "C_offline_only"})
    for k in sorted(live_keys - off_keys):
        rows.append({"key": k, "bucket": "D_live_only"})

    trades_off_r = trades_off[trades_off["variant"] == variant] if len(trades_off) else trades_off
    n_off_trades, n_live_trades = len(trades_off_r), len(trades_live)
    rows.append({"key": None, "bucket": "trade_count_summary",
                "offline_trades": n_off_trades, "live_trades": n_live_trades})
    return pd.DataFrame(rows)


def march_filter_waterfall(live: pd.DataFrame, offline_count: int) -> dict:
    """Sequential funnel exactly as required: raw checkpoints ->
    established_regime_gate -> decision_rth -> fill_rth -> valid_fill ->
    final candidates. NOTE: `final_candidate_eligible` itself (per its own
    exact formula, established_regime_gate AND decision_rth AND valid_fill)
    does NOT gate on fill_rth -- so the fully-cumulative-through-fill_rth
    count below and the actual final_candidate_eligible count can differ.
    Both are reported explicitly, not silently conflated."""
    n_raw = len(live)
    n_established = int((live["established_regime_gate"] == True).sum())  # noqa: E712
    after_established = live[live["established_regime_gate"] == True]  # noqa: E712
    n_decision_rth = int((after_established["decision_rth"] == True).sum())  # noqa: E712
    after_decision_rth = after_established[after_established["decision_rth"] == True]  # noqa: E712
    n_fill_rth = int((after_decision_rth["fill_rth"] == True).sum())  # noqa: E712
    after_fill_rth = after_decision_rth[after_decision_rth["fill_rth"] == True]  # noqa: E712
    n_valid_fill_cumulative_with_fill_rth = int((after_fill_rth["valid_fill"] == True).sum())  # noqa: E712
    n_final_candidate_eligible = int((live["final_candidate_eligible"] == True).sum())  # noqa: E712

    return {
        "stage_raw_checkpoints": n_raw,
        "stage_established_regime_gate": n_established,
        "stage_decision_rth": n_decision_rth,
        "stage_fill_rth": n_fill_rth,
        "stage_valid_fill_cumulative_through_fill_rth": n_valid_fill_cumulative_with_fill_rth,
        "final_candidate_eligible_actual_formula": n_final_candidate_eligible,
        "note": ("final_candidate_eligible uses established_regime_gate AND decision_rth AND "
                "valid_fill (NOT fill_rth) per the exact required formula -- "
                "stage_valid_fill_cumulative_through_fill_rth is a stricter, fully-sequential "
                "count shown for the waterfall only, and may be <= final_candidate_eligible_actual_formula."),
        "offline_reference_count": offline_count,
        "matches_offline": n_final_candidate_eligible == offline_count,
        "difference": n_final_candidate_eligible - offline_count,
    }


def main(only_variants: tuple[str, ...] = ("R5", "R2.5")) -> None:
    offline = load_offline()
    feat_list = json.loads(C.FEATURE_SETS_PATH.read_text())["F3_top25_gbt_v1"]["features"]

    all_pop_rows, all_pop_summary = [], {}
    all_feat_rows, all_score_rows = [], []
    all_trig_rows = []
    all_waterfalls = {}

    trades_off = pd.read_parquet(C.RESULTS / "offline_trades_march_2025.parquet")

    for variant, variant_dir_name in (("R5", "R5"), ("R2.5", "R2.5")):
        if variant not in only_variants:
            print(f"SKIP {variant}: not in only_variants={only_variants}")
            continue
        variant_dir = C.WORK / "nt_runs" / "full_march" / variant_dir_name
        if not (variant_dir / "candidates.parquet").exists():
            print(f"SKIP {variant}: no NT run output found at {variant_dir}")
            continue
        live = load_live(variant_dir)
        trades_live = pd.read_parquet(variant_dir / "trades.parquet")

        pop_df, pop_summary = candidate_population_parity(offline, live)
        pop_df["variant"] = variant
        all_pop_rows.append(pop_df)
        all_pop_summary[variant] = pop_summary

        feat_df, feat_summary, score_df, score_summary = feature_and_score_parity(offline, live, feat_list)
        feat_df["variant"] = variant
        score_df["variant"] = variant
        all_feat_rows.append(feat_df)
        all_score_rows.append(score_df)
        all_pop_summary[f"{variant}_feature_summary"] = feat_summary
        all_pop_summary[f"{variant}_score_summary"] = score_summary

        trig_df = trigger_trade_parity(offline, live, trades_off, trades_live, variant)
        trig_df["variant"] = variant
        all_trig_rows.append(trig_df)

        all_waterfalls[variant] = march_filter_waterfall(live, len(offline))

    if all_pop_rows:
        pd.concat(all_pop_rows, ignore_index=True).to_csv(C.RESULTS / "candidate_population_parity.csv", index=False)
    (C.RESULTS / "candidate_population_parity_summary.json").write_text(json.dumps(all_pop_summary, indent=2, default=str))
    if all_feat_rows:
        pd.concat(all_feat_rows, ignore_index=True).to_csv(C.RESULTS / "feature_parity.csv", index=False)
    if all_score_rows:
        pd.concat(all_score_rows, ignore_index=True).to_csv(C.RESULTS / "score_parity.csv", index=False)
    if all_trig_rows:
        pd.concat(all_trig_rows, ignore_index=True).to_csv(C.RESULTS / "trigger_trade_parity.csv", index=False)
    if all_waterfalls:
        (C.RESULTS / "march_filter_waterfall.json").write_text(json.dumps(all_waterfalls, indent=2, default=str))

    print(json.dumps(all_pop_summary, indent=2, default=str))
    print("--- March filter waterfall ---")
    print(json.dumps(all_waterfalls, indent=2, default=str))


if __name__ == "__main__":
    import sys
    variants = tuple(sys.argv[1:]) if len(sys.argv) > 1 else ("R5",)
    main(only_variants=variants)
