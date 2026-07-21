"""Runtime parity checks, per SPEC.md: regime-transition parity (exact),
trigger-condition parity (exact), score/ATR parity (exact by construction,
since no live rescoring occurs -- verified by re-derivation, not assumed).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
STUDY = HERE.parent
sys.path.insert(0, str(HERE))
import common as C  # noqa: E402

for p in (ROOT / "studies" / "CODEX_5_X_weakness_atlas_repair",
         ROOT / "studies" / "short_rth_pure_flip_score_entry_policy"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
from CODEX_5_X_common import RAW_1S  # noqa: E402
from CODEX_5_X_run_established_fade import canonical_regime_timeline  # noqa: E402
from trigger_logic import build_trigger_flags  # noqa: E402

TRIG_COL = {"T1": "trig_B_top2.5", "T2": "trig_C30_top5", "T3": "trig_B_top5"}
SCORE_COL = "score_F3_volume_delta_plus_price_levels__gbt_raw"


def regime_transition_parity(variant_label: str) -> dict:
    """Live NT flip stream (this run's own strategy.flips output) vs. the
    offline canonical regime timeline, over the full loaded year (matches
    fable5_nt_short_rth_policy_a's flip_parity methodology)."""
    nt_flips = pd.read_parquet(C.WORK / "nt_runs" / variant_label / "flips.parquet")
    raw = pd.read_parquet(RAW_1S[2025], columns=["open", "high", "low", "close", "volume"])
    timeline = canonical_regime_timeline(2025, raw)
    off = timeline[["regime_start_ns", "direction"]].rename(columns={"regime_start_ns": "flip_ts"})
    off_set = set(zip(off["flip_ts"].astype("int64"), off["direction"].astype(int)))
    nt_set = (set(zip(nt_flips["flip_ts"].astype("int64"), nt_flips["direction"].astype(int)))
             if len(nt_flips) else set())
    only_off, only_nt = off_set - nt_set, nt_set - off_set
    return {"variant": variant_label, "offline_flips": len(off_set), "nt_flips": len(nt_set),
           "matched": len(off_set & nt_set), "only_offline": len(only_off), "only_nt": len(only_nt),
           "exact_match": len(only_off) == 0 and len(only_nt) == 0,
           "mismatch_examples": [{"flip_ts": int(ts), "direction": int(d)}
                                 for ts, d in sorted(only_off | only_nt)[:10]]}


def trigger_condition_parity(variant_label: str) -> dict:
    """Re-derives the trigger condition fresh from the stored score column
    (using the already-tested trigger_logic.build_trigger_flags) and
    confirms it reproduces EXACTLY the (regime_start_ns, signal_decision_ts)
    pairs used to build this variant's NT schedule -- proof that the frozen
    schedule is a faithful, reproducible function of the causal score
    stream, not a re-scoring of the model itself (SPEC.md finding 2)."""
    trig_col = TRIG_COL[variant_label]
    scored = pd.read_parquet(
        ROOT / "studies" / "short_rth_pure_flip_prediction_enriched" / "_work" / "scored_dev_2025.parquet",
        columns=["regime_start_ns", "observation_time", SCORE_COL])
    cutoffs = json.loads(
        (ROOT / "studies" / "short_rth_pure_flip_score_entry_policy" / "_work" / "cutoffs.json")
        .read_text(encoding="utf-8"))
    tagged = build_trigger_flags(scored, SCORE_COL, cutoffs)
    tagged["month"] = pd.to_datetime(tagged["observation_time"], unit="ns", utc=True).dt.strftime("%Y-%m")

    triggered = tagged[tagged[trig_col] & (tagged["month"] == C.SELECTED_MONTH)]
    first_per_regime = (triggered.sort_values(["regime_start_ns", "observation_time"], kind="stable")
                       .groupby("regime_start_ns", as_index=False).first())
    rederived_set = set(zip(first_per_regime["regime_start_ns"].astype("int64"),
                            first_per_regime["observation_time"].astype("int64")))

    sched = pd.read_parquet(C.schedule_path(variant_label))
    sched_set = set(zip(sched["regime_start_ns"].astype("int64"), sched["signal_decision_ts"].astype("int64")))

    return {"variant": variant_label, "rederived_count": len(rederived_set),
           "schedule_count": len(sched_set), "matched": len(rederived_set & sched_set),
           "only_rederived": len(rederived_set - sched_set), "only_schedule": len(sched_set - rederived_set),
           "exact_match": rederived_set == sched_set}


def atr_and_score_parity(variant_label: str) -> dict:
    """ATR and score are frozen values carried through unchanged from the
    same source file used to build the schedule -- no live rescoring
    occurs, so this is verified by construction (a join-and-compare against
    the source, not an independent recomputation of the model itself,
    which SPEC.md finding 2/3 establishes is out of scope for this POC)."""
    trig_col = TRIG_COL[variant_label]
    src = pd.read_parquet(
        ROOT / "studies" / "short_rth_pure_flip_score_entry_policy" / "_work"
        / f"schedule_{trig_col}_2025.parquet",
        columns=["regime_start_ns", "observation_time", "atr_at_entry", SCORE_COL])
    sched = pd.read_parquet(C.schedule_path(variant_label))
    merged = sched.merge(src, left_on=["regime_start_ns", "signal_decision_ts"],
                         right_on=["regime_start_ns", "observation_time"], how="left", validate="one_to_one")
    atr_diff = (merged["atr_at_checkpoint"] - merged["atr_at_entry"]).abs()
    return {"variant": variant_label, "n_rows": len(merged),
           "max_atr_abs_diff": float(atr_diff.max()) if len(atr_diff) else np.nan,
           "atr_exact_match": bool((atr_diff < 1e-9).all()) if len(atr_diff) else True,
           "any_unmatched_rows": bool(merged[SCORE_COL].isna().any())}


def main() -> None:
    regime_rows, trigger_rows, atr_rows = [], [], []
    for label in C.VARIANTS:
        regime_rows.append(regime_transition_parity(label))
        trigger_rows.append(trigger_condition_parity(label))
        atr_rows.append(atr_and_score_parity(label))

    pd.DataFrame(regime_rows).to_csv(C.PHASE2 / "regime_runtime_parity.csv", index=False)
    pd.DataFrame(trigger_rows).to_csv(C.PHASE2 / "trigger_runtime_parity.csv", index=False)
    pd.DataFrame(atr_rows).to_csv(C.PHASE2 / "score_runtime_parity.csv", index=False)

    all_exact = (all(r["exact_match"] for r in regime_rows)
                and all(r["exact_match"] for r in trigger_rows)
                and all(r["atr_exact_match"] and not r["any_unmatched_rows"] for r in atr_rows))
    print("Regime parity:", pd.DataFrame(regime_rows)[["variant", "exact_match", "matched"]].to_string(index=False))
    print("\nTrigger parity:", pd.DataFrame(trigger_rows)[["variant", "exact_match", "matched"]].to_string(index=False))
    print("\nATR/score parity:", pd.DataFrame(atr_rows)[["variant", "atr_exact_match", "any_unmatched_rows"]].to_string(index=False))
    print(f"\nALL PARITY CHECKS EXACT: {all_exact}")
    if not all_exact:
        raise SystemExit("PARITY FAILURE -- see CSVs for details")


if __name__ == "__main__":
    main()
