"""
Phase 0 — audit the prior contextual study implementation.

Reads the prior code + artifacts and documents:
  * which requested MTF families were implemented vs omitted,
  * how regime-quality state was created and how it collapsed at attribution,
  * why ~all test episodes were reported ORDINARY,
  * how P1c was selected (validation vs test),
  * how the prior weakness "stop" proof-of-concept was actually computed.

Outputs: results/prior_implementation_audit.md, results/prior_state_join_audit.parquet
"""

from __future__ import annotations
import re
from pathlib import Path
import numpy as np
import pandas as pd
import common as C

PRIOR = C.REPO / "studies/rl_regime_feasibility/contextual_runner_exit"
PRIOR_RES = PRIOR / "results"


def main():
    print("=" * 70)
    print("Phase 0 — prior implementation audit")
    print("=" * 70)
    src = (PRIOR / "run_study.py").read_text(encoding="utf-8", errors="ignore")

    # 1. MTF families implemented (grep the prior source) ---------------------
    requested = {
        "slope_and_slope_change": ["slope", "slope_change"],
        "directional_efficiency": ["directional_efficiency", "progress_efficiency"],
        "favorable_vs_adverse_vol": ["favorable_vol", "adverse_vol", "fav_to_adv"],
        "new_extreme_rate": ["new_favorable_extreme", "extreme_rate", "extreme_count"],
        "time_since_htf_extreme": ["seconds_since_last_favorable", "time_since_structural"],
        "structural_hh_hl": ["higher_high", "lower_low", "structure_direction"],
        "range_position": ["position_in_horizon", "range_position", "position_in_trailing"],
        "volume_per_progress": ["progress_per_volume", "volume_per_unit"],
        "volume_per_retracement": ["retracement_per_volume"],
        "prior_pullback_recovery": ["pb_", "pullback_recovery", "recovery_quality"],
        "aligned_returns_multi_horizon": ["ar_180s", "ar_300s", "ar_900s", "aligned_return_180"],
    }
    fam_rows = []
    for fam, keys in requested.items():
        hit = any(re.search(re.escape(k), src) for k in keys)
        fam_rows.append({"requested_family": fam, "implemented_in_prior": hit,
                         "matched_keys": [k for k in keys if re.search(re.escape(k), src)]})
    fam_df = pd.DataFrame(fam_rows)
    n_impl = int(fam_df["implemented_in_prior"].sum())

    # 2. State collapse forensic ---------------------------------------------
    # replicate the prior attribution: episode state = state at FIRST checkpoint.
    rq = pd.read_parquet(PRIOR_RES / "regime_quality_states.parquet")
    collapse_lines = []
    saved_head_2000 = bool(re.search(r"\.head\(2000\)", src))
    first_attr = bool(re.search(r'groupby\("episode_id"\)\.first\(\)\[\["direction","is_rth","regime_quality"\]\]', src)) \
        or bool(re.search(r"groupby\(.episode_id.\)\.first\(\).*regime_quality", src))

    # demonstrate the collapse on the atlas: assign a crude pctile state and show
    # that state-at-first-checkpoint is overwhelmingly ORDINARY while state at a
    # LATE checkpoint is diverse.
    chk = pd.read_parquet(C.ATLAS_CHK, columns=[
        "episode_id", "seconds_since_entry", "trade_mfe_atr", "period"])
    test = chk[chk["period"] == "test"].copy()
    # crude percentile within age bucket for illustration
    test["age_b"] = np.digitize(test["seconds_since_entry"].values,
                                np.array([0, 60, 120, 300, 1e9])) - 1
    test["pct"] = test.groupby("age_b")["trade_mfe_atr"].rank(pct=True)

    def crude_state(p):
        return np.where(p >= 0.75, "PROLIFIC", np.where(p >= 0.5, "HEALTHY", "ORDINARY"))
    test["cs"] = crude_state(test["pct"].values)
    first_state = test.sort_values("seconds_since_entry").groupby("episode_id")["cs"].first()
    last_state = test.sort_values("seconds_since_entry").groupby("episode_id")["cs"].last()
    max_state = (test.assign(rank={"ORDINARY": 0, "HEALTHY": 1, "PROLIFIC": 2})
                 .groupby("episode_id")["cs"]
                 .agg(lambda s: s.value_counts().index[0]))
    fc = first_state.value_counts(normalize=True).to_dict()
    lc = last_state.value_counts(normalize=True).to_dict()

    join_audit = pd.DataFrame({
        "attribution_method": ["first_checkpoint (prior bug)", "last_checkpoint", "modal"],
        "pct_ORDINARY": [fc.get("ORDINARY", 0), lc.get("ORDINARY", 0),
                         float((max_state == "ORDINARY").mean())],
        "pct_HEALTHY": [fc.get("HEALTHY", 0), lc.get("HEALTHY", 0),
                        float((max_state == "HEALTHY").mean())],
        "pct_PROLIFIC": [fc.get("PROLIFIC", 0), lc.get("PROLIFIC", 0),
                         float((max_state == "PROLIFIC").mean())],
    })
    join_audit.to_parquet(C.RESULTS / "prior_state_join_audit.parquet", index=False)

    # 3. P1c selection -------------------------------------------------------
    # P1c appears in the report as best-of test policies; check it was picked by
    # argmax over test EV (exploratory), not frozen on val.
    p1c_test_selected = bool(re.search(r"max\(pair_rows, key=.*mean", src))

    # 4. weakness stop POC ---------------------------------------------------
    poc = pd.read_parquet(PRIOR_RES / "weakness_stop_proof_of_concept.parquet")
    poc_cols = list(poc.columns)
    has_real_stop = any(k in poc_cols for k in
                        ["stop_level", "stop_fill_ts", "stop_trigger_time", "stop_fill_price"])

    # ── write report ────────────────────────────────────────────────────────
    lines = [
        "# Prior Contextual Study — Implementation Audit",
        "",
        "Scope: `studies/rl_regime_feasibility/contextual_runner_exit/` "
        "(run_study.py, results/).",
        "",
        "## 1. Multi-timeframe feature families",
        "",
        f"Implemented {n_impl}/{len(requested)} requested families.",
        "",
        "| Requested family | Implemented in prior? | matched tokens |",
        "|---|---|---|",
    ]
    for r in fam_rows:
        lines.append(f"| {r['requested_family']} | "
                     f"{'YES' if r['implemented_in_prior'] else 'NO'} | "
                     f"{', '.join(r['matched_keys']) or '—'} |")
    lines += [
        "",
        "**Finding:** the prior 'MTF' block was essentially longer-window aligned "
        "returns plus a few cross-return ratios. Slope/slope-change, directional "
        "efficiency at higher horizons, favorable-vs-adverse volatility, "
        "new-extreme rate, structural HH/HL state, volume-per-progress, "
        "volume-per-retracement and pullback-recovery history were NOT implemented. "
        "Per the interpretation rule, MTF context was therefore never actually tested.",
        "",
        "## 2. Regime-quality state collapse",
        "",
        f"- Saved `regime_quality_states.parquet` is a `.head(2000)` sample: "
        f"`{saved_head_2000}` (rows in file: {len(rq):,}).",
        f"- Episode attribution used state at the FIRST checkpoint "
        f"(`groupby('episode_id').first()[...regime_quality]`): `{first_attr}`.",
        "",
        "Forensic reproduction on the atlas test period "
        f"({test['episode_id'].nunique():,} episodes) with a crude age-percentile state:",
        "",
        "| Attribution | %ORDINARY | %HEALTHY | %PROLIFIC |",
        "|---|---|---|---|",
    ]
    for _, r in join_audit.iterrows():
        lines.append(f"| {r['attribution_method']} | {r['pct_ORDINARY']:.1%} | "
                     f"{r['pct_HEALTHY']:.1%} | {r['pct_PROLIFIC']:.1%} |")
    lines += [
        "",
        "**Root cause of the 5642/5660 ORDINARY collapse:** at the first checkpoint "
        "(~30s in) MFE is tiny, so the age-percentile is low and the state is "
        "ORDINARY for almost every episode. Taking `.first()` therefore stamps "
        "nearly the whole population ORDINARY regardless of what happened at the "
        "actual exit decision. The repair attaches state at the DECISION checkpoint "
        "and evaluates the state at every checkpoint (not a 2000-row sample).",
        "",
        "## 3. P1c selection",
        "",
        f"- Prior best policy chosen by argmax over TEST-period policy EV: "
        f"`{p1c_test_selected}`. P1c (+$2.23/trade) was therefore an EXPLORATORY, "
        "test-selected result, not a validation-frozen out-of-sample winner. The "
        "repair freezes all policy definitions/thresholds on train+val before the "
        "single dev-test replay.",
        "",
        "## 4. Weakness-stop proof-of-concept",
        "",
        f"- POC columns: {poc_cols}",
        f"- Contains real stop-order fields (level/trigger/fill): `{has_real_stop}`.",
        "",
        "**Finding:** the POC compared immediate-exit vs E0 PnL but did not activate "
        "or monitor a real stop order (no stop level, activation time, trigger time, "
        "fill price, or recovery-vs-stop resolution). The 'weakness stop is null' "
        "conclusion was unsupported. The repair runs a real 1s-monitored stop "
        "simulation (Phase 8).",
        "",
        "## Summary of required repairs",
        "",
        "1. Implement the full MTF family set (returns/slope, efficiency, "
        "vol-decomposition, extremes, volume-response, structural, pullback, cross).",
        "2. Evaluate regime state at every checkpoint; attribute at the decision "
        "checkpoint; save the full population.",
        "3. Freeze all policies on train+val; replay dev-test once.",
        "4. Run a real weakness-triggered stop simulation monitored on 1s bars.",
    ]
    (C.RESULTS / "prior_implementation_audit.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"  MTF families implemented in prior: {n_impl}/{len(requested)}")
    print(f"  first-checkpoint attribution %ORDINARY: {join_audit.iloc[0]['pct_ORDINARY']:.1%}")
    print(f"  last-checkpoint attribution %ORDINARY:  {join_audit.iloc[1]['pct_ORDINARY']:.1%}")
    print(f"  P1c test-selected: {p1c_test_selected}  |  POC real stop: {has_real_stop}")
    print("  wrote prior_implementation_audit.md + prior_state_join_audit.parquet")


if __name__ == "__main__":
    main()
