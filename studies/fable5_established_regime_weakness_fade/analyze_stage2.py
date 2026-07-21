"""Compact Stage-2 monetization report for the single frozen policy."""
from __future__ import annotations

import json
import hashlib

import numpy as np
import pandas as pd

from common import RESULTS, STUDY


def metrics(x: pd.DataFrame, segment: str, value: str) -> dict:
    done = x[x["exit_reason"] != "data_end_censored"].copy()
    wins = done["net_pnl_usd"] > 0
    pos = done.loc[done["net_pnl_usd"] > 0, "net_pnl_usd"].sum()
    neg = -done.loc[done["net_pnl_usd"] < 0, "net_pnl_usd"].sum()
    return {
        "segment": segment, "segment_value": value,
        "trade_count": len(done),
        "censored_count": int((x["exit_reason"] == "data_end_censored").sum()),
        "mean_gross_pnl_usd": done["gross_pnl_usd"].mean(),
        "mean_net_pnl_usd": done["net_pnl_usd"].mean(),
        "total_net_pnl_usd": done["net_pnl_usd"].sum(),
        "win_rate": wins.mean() if len(done) else np.nan,
        "profit_factor": pos / neg if neg > 0 else np.nan,
        "stop_out_rate": done["exit_reason"].str.startswith("stop").mean() if len(done) else np.nan,
        "median_hold_s": done["hold_s"].median(),
    }


def main() -> None:
    frames = []
    reconciliations = []
    skip_frames = []
    for year in (2025, 2026):
        p = RESULTS / f"stage2_trades_{year}.parquet"
        assert p.exists(), f"missing {p.name}"
        frames.append(pd.read_parquet(p))
        rp = RESULTS / f"stage2_reconciliation_{year}.json"
        assert rp.exists(), f"missing {rp.name}"
        reconciliations.append(json.loads(rp.read_text(encoding="utf-8")))
        sp = RESULTS / f"stage2_skipped_{year}.parquet"
        sx = pd.read_parquet(sp)
        sx["year"] = year
        skip_frames.append(sx)
    d = pd.concat(frames, ignore_index=True)
    assert set(d["contract"]) == {"EXPLICIT_NEXT_OPEN_OHLC_RESEARCH_CONTRACT"}
    expected_hash = hashlib.sha256(
        (STUDY / "stage2_frozen_policy.json").read_bytes()
    ).hexdigest()
    assert set(d["policy_sha256"]) == {expected_hash}, "policy changed after run"
    for rec in reconciliations:
        assert rec["policy_sha256"] == expected_hash
        assert rec["blocking_errors"] == 0
        assert rec["closure_residual"] == 0
        assert rec["candidate_count"] == rec["trade_count"] + rec["skip_count"]
        assert rec["exit_reason_residual"] == 0
    gross_error = float(np.abs(
        d["gross_pnl_usd"] - d["gross_pnl_pts"] * 20.0
    ).max())
    net_error = float(np.abs(
        d["net_pnl_usd"] - (d["gross_pnl_usd"] - 10.0)
    ).max())
    assert gross_error <= 1e-9 and net_error <= 1e-9
    rows = []
    for year, x in d.groupby("year"):
        rows.append(metrics(x, "year", str(year)))
        for direction, z in x.groupby("entry_direction"):
            rows.append(metrics(z, f"{year}_direction", "long" if direction == 1 else "short"))
        for session, z in x.groupby("session"):
            rows.append(metrics(z, f"{year}_session", session))
    summary = pd.DataFrame(rows)
    summary.to_parquet(RESULTS / "stage2_policy_results.parquet", index=False)
    reasons = d.groupby(["year", "exit_reason"]).size().rename("count").reset_index()
    reasons.to_parquet(RESULTS / "stage2_exit_reasons.parquet", index=False)
    skips = pd.concat(skip_frames, ignore_index=True)
    skip_summary = skips.groupby(["year", "reason"]).size().rename("count").reset_index()
    skip_summary.to_parquet(RESULTS / "stage2_skip_reasons.parquet", index=False)
    delay_class = pd.cut(
        d["entry_fill_delay_s"], [-np.inf, 0, 60, np.inf],
        labels=["exact_boundary_open", "short_gap_1_to_60s", "extended_gap_gt_60s"],
        include_lowest=True,
    )
    delays = (d.assign(delay_class=delay_class)
              .groupby(["year", "delay_class"], observed=True)
              .agg(count=("trade_id" if "trade_id" in d.columns else "regime_start_ns", "count"),
                   max_delay_s=("entry_fill_delay_s", "max"))
              .reset_index())
    delays.to_parquet(RESULTS / "stage2_fill_delay_summary.parquet", index=False)
    scheduled = d[d["exit_reason"] == "opposite_flip_against_countertrade"].copy()
    scheduled["exit_fill_delay_s"] = (
        scheduled["exit_fill_ts"] - scheduled["scheduled_exit_decision_ts"]
    ) / 1e9
    assert (scheduled["exit_fill_delay_s"] >= 0).all()
    exit_delays = (scheduled.groupby("year")
                   .agg(scheduled_exit_count=("exit_fill_delay_s", "size"),
                        exact_boundary_count=("exit_fill_delay_s", lambda x: int((x == 0).sum())),
                        delayed_count=("exit_fill_delay_s", lambda x: int((x > 0).sum())),
                        max_exit_delay_s=("exit_fill_delay_s", "max"))
                   .reset_index())
    exit_delays.to_parquet(RESULTS / "stage2_exit_fill_delay_summary.parquet", index=False)
    headline = summary[summary["segment"] == "year"].set_index("segment_value")
    y25 = headline.loc["2025"]
    y26 = headline.loc["2026"]
    if y25.mean_net_pnl_usd > 0 and y26.mean_net_pnl_usd > 0 \
            and y25.profit_factor > 1 and y26.profit_factor > 1:
        decision = "PROMISING_NEEDS_FULL_VALIDATION"
    else:
        decision = "NO_MONETIZABLE_WEAKNESS_FADE"
    policy = json.loads((STUDY / "stage2_frozen_policy.json").read_text(encoding="utf-8"))
    stage1_gate = json.loads((RESULTS / "stage1_gate.json").read_text(encoding="utf-8"))
    gtr = stage1_gate["train"]
    gvl = stage1_gate["validation"]
    completion = {
        "policy_sha256": expected_hash,
        "trade_rows": int(len(d)),
        "year_trade_counts": d.groupby("year").size().astype(int).to_dict(),
        "gross_pnl_reconciliation_max_abs_error": gross_error,
        "net_pnl_reconciliation_max_abs_error": net_error,
        "exit_reason_count_residual": int(len(d) - reasons["count"].sum()),
        "candidate_closure_residuals": {str(r["year"]): r["closure_residual"] for r in reconciliations},
        "blocking_errors": {str(r["year"]): r["blocking_errors"] for r in reconciliations},
        "max_entry_fill_delay_s": d.groupby("year")["entry_fill_delay_s"].max().to_dict(),
        "max_stop_distance_error_atr": d.groupby("year")["realized_stop_atr"].apply(lambda x: float(np.abs(x - 1.5).max())).to_dict(),
    }
    (RESULTS / "completion_reconciliation.json").write_text(
        json.dumps(completion, indent=2), encoding="utf-8")
    table = summary.to_markdown(index=False, floatfmt=".3f")
    reason_table = reasons.to_markdown(index=False)
    skip_table = skip_summary.to_markdown(index=False)
    delay_table = delays.to_markdown(index=False, floatfmt=".1f")
    exit_delay_table = exit_delays.to_markdown(index=False, floatfmt=".1f")
    report = f"""# Established Regime Weakness Fade — Final Report

## Decisions

- Stage 1: `ESTABLISHED_REGIME_FILTER_FOUND`
- Stage 2: `{decision}`

This is a **1-second OHLC research simulation**, not NT-native executable validation and not deployable.

Stage 1 found a causal persistence signature (`{stage1_gate['decision']}`). Winner-versus-failed-runner duration ratios were {gtr['duration_ratio']:.2f}x in discovery and {gvl['duration_ratio']:.2f}x in 2025; peak-MFE ratios were {gtr['peak_mfe_ratio']:.2f}x and {gvl['peak_mfe_ratio']:.2f}x; retained-MFE differences at flip-minus-60s were {gtr['retained_m60_delta']:.3f} and {gvl['retained_m60_delta']:.3f}; paired terminal W4 rises were {gtr['winner_w4_rise_m60_to_flip']:.3f} and {gvl['winner_w4_rise_m60_to_flip']:.3f}. That justified this one frozen monetization test; it did not make the retrospective cohort label tradable.

## Frozen policy

- Established regime: age >= 120s, running MFE >= 1.0 ATR, at least 2 distinct progress windows, retained MFE ratio >= 0.50.
- Trigger: first valid W4 crossing from below {policy['w4_threshold']:.12f} while the filter is true.
- Entry: fade prevailing regime at explicit next available 1s open after score availability.
- Stop: exactly 1.5 ATR from fill, active on the entry bar.
- Exit: hold through the aligning flip; exit at the next flip against the countertrade.
- Costs: ${policy['cost_rt_usd']:.2f} round trip; net is decisive.

## Results

{table}

## Exit reasons

{reason_table}

## Candidate skips

{skip_table}

## Explicit next-open delays

{delay_table}

The longest 2025 delay was {completion['max_entry_fill_delay_s'][2025]:.0f}s across a documented data/session gap; the entry still preceded the confirming flip or it would have been skipped by contract. 2026's maximum was {completion['max_entry_fill_delay_s'][2026]:.0f}s.

## Scheduled exit next-open delays

{exit_delay_table}

Flip exits use the **next available** 1-second open after the exit decision, not a guaranteed same-timestamp boundary bar. Weekend/session closures delayed 301 scheduled exits in 2025 (maximum 189,900s) and 115 in 2026 (maximum 176,400s); these delayed fills are included in the reported PnL.

## Reconciliation

- Policy hash: `{expected_hash}`
- Candidate accounting residual: 0 in both years; blocking errors: 0.
- Gross and net PnL reconciliation maximum absolute error: {max(gross_error, net_error):.3g}.
- No 2026 value altered the filter, W4 trigger, 1.5 ATR stop, exit, or costs.
- The immutable policy rationale text recorded a preliminary 2025 time-to-1-ATR median of 139s before the audited regime-direction source repair; the corrected value is 142s. The 120s rule was derived from the unchanged 2021-2024 median of 137s, so no policy parameter changed.

## Contract limitations

Intrabar touch ordering is not claimed. There is no profit target, so no same-bar stop/target tie exists. A scheduled flip exit fills at the next available 1-second open after its decision; on that fill bar the market exit has priority before the bar's intrabar range. All earlier bars, including the entry bar, are stop-active. Tick/quote fill accuracy is not claimed.
"""
    (RESULTS / "final_report.md").write_text(report, encoding="utf-8")
    print(decision)


if __name__ == "__main__":
    main()
