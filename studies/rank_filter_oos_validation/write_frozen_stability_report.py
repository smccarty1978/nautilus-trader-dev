"""Compute the required cross-period summary stats and write final_report.md
for the frozen-policy stability audit. Purely descriptive/diagnostic --
does not select a preferred threshold or modify either policy."""
import numpy as np
import pandas as pd
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
AUDIT_DIR = PROJECT_ROOT / "studies/rank_filter_oos_validation/results/frozen_stability_audit"
BLOCK_ORDER = ["2021", "2022", "2023", "2024", "2025_JanFeb", "2025_MarMay", "2025_JunDec", "2026_JanApr29"]
CATALOG_BUG_BLOCKS = {"2021", "2022", "2023", "2024"}


def cross_period_summary(pm: pd.DataFrame, policy: str) -> dict:
    sub = pm[pm["policy"] == policy].set_index("block").reindex(BLOCK_ORDER)
    lifts = sub["ev_lift_vs_r0"]
    n_pos = int((lifts > 0).sum())
    n_neg = int((lifts <= 0).sum())
    median_lift = float(lifts.median())
    worst_idx = lifts.idxmin()
    worst_val = float(lifts.min())
    std = float(lifts.std())
    return {
        "n_positive": n_pos, "n_negative": n_neg, "n_total": len(lifts),
        "median_lift": median_lift, "worst_period": worst_idx, "worst_lift": worst_val,
        "std": std, "lifts_by_block": lifts.to_dict(),
    }


def baseline_environment_correlation(pm: pd.DataFrame, policy: str) -> float:
    r0 = pm[pm["policy"] == "R0"].set_index("block").reindex(BLOCK_ORDER)["ev_per_eligible_signal"]
    pol = pm[pm["policy"] == policy].set_index("block").reindex(BLOCK_ORDER)["ev_lift_vs_r0"]
    if r0.isna().any() or pol.isna().any() or r0.std() == 0 or pol.std() == 0:
        return float("nan")
    return float(np.corrcoef(r0.values, pol.values)[0, 1])


def fmt_block_table(pm: pd.DataFrame, mr: pd.DataFrame, td: pd.DataFrame, policy: str) -> str:
    sub = pm[pm["policy"] == policy].set_index("block").reindex(BLOCK_ORDER)
    mr_sub = mr[mr["policy"] == policy].set_index("block").reindex(BLOCK_ORDER)
    td_sub = td[td["policy"] == policy].set_index("block").reindex(BLOCK_ORDER)
    lines = ["| block | eligible | filled | EV lift vs R0 | net PnL Δ | max DD Δ | matched-random p | largest avoided loss | largest skipped winner | lift excl top1 | lift excl top2 |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for b in BLOCK_ORDER:
        r = sub.loc[b]
        m = mr_sub.loc[b] if b in mr_sub.index else None
        t = td_sub.loc[b] if b in td_sub.index else None
        caveat = " *" if b in CATALOG_BUG_BLOCKS else ""
        lines.append(
            f"| {b}{caveat} | {int(r['eligible_signals'])} | {int(r['filled_trades'])} | "
            f"${r['ev_lift_vs_r0']:+.2f} | ${r['net_pnl_change_vs_r0']:+,.0f} | "
            f"n/a | {m['empirical_p_value']:.3f} | ${r['largest_avoided_loss']:+,.0f} | "
            f"${r['largest_skipped_winner']:+,.0f} | ${t['lift_excl_top1_avoided_loss']:+.2f} | "
            f"${t['lift_excl_top2_avoided_losses']:+.2f} |"
        )
    return "\n".join(lines)


def run():
    pm = pd.read_parquet(AUDIT_DIR / "period_metrics.parquet")
    rr = pd.read_parquet(AUDIT_DIR / "period_runner_retention.parquet")
    dd = pd.read_parquet(AUDIT_DIR / "period_drawdown_metrics.parquet")
    mr = pd.read_parquet(AUDIT_DIR / "period_matched_random.parquet")
    td = pd.read_parquet(AUDIT_DIR / "tail_dependence.parquet")

    # fold drawdown-change into pm-like lookup for the table
    dd_pivot = dd.set_index(["block", "policy"])["drawdown_change_vs_r0"]

    r2_summary = cross_period_summary(pm, "R2")
    r4_summary = cross_period_summary(pm, "R4")
    r2_corr = baseline_environment_correlation(pm, "R2")
    r4_corr = baseline_environment_correlation(pm, "R4")

    r4_runner_top10 = rr[(rr["policy"] == "R4") & (rr["tier"] == "top10")].set_index("block").reindex(BLOCK_ORDER)["runner_pnl_retention"]
    r2_runner_top10 = rr[(rr["policy"] == "R2") & (rr["tier"] == "top10")].set_index("block").reindex(BLOCK_ORDER)["runner_pnl_retention"]

    r4_mr = mr[mr["policy"] == "R4"].set_index("block").reindex(BLOCK_ORDER)["empirical_p_value"]
    r2_mr = mr[mr["policy"] == "R2"].set_index("block").reindex(BLOCK_ORDER)["empirical_p_value"]
    r4_mr_pass = int((r4_mr <= 0.10).sum())
    r2_mr_pass = int((r2_mr <= 0.10).sum())

    worst_r2_str = f"{r2_summary['worst_period']}, ${r2_summary['worst_lift']:+.2f}"
    worst_r4_str = f"{r4_summary['worst_period']}, ${r4_summary['worst_lift']:+.2f}"

    header = f"""NEW FORWARD DATA AVAILABLE:
NO

POLICIES FROZEN:
YES

R2 POSITIVE PERIODS:
{r2_summary['n_positive']}/{r2_summary['n_total']}

R4 POSITIVE PERIODS:
{r4_summary['n_positive']}/{r4_summary['n_total']}

R2 MEDIAN PERIOD LIFT:
${r2_summary['median_lift']:+.2f}

R4 MEDIAN PERIOD LIFT:
${r4_summary['median_lift']:+.2f}

R2 WORST PERIOD:
{worst_r2_str}

R4 WORST PERIOD:
{worst_r4_str}

R4 RUNNER RETENTION:
{r4_runner_top10.mean():.4f} average across periods (range {r4_runner_top10.min():.4f}-{r4_runner_top10.max():.4f}); see Section 3

R4 MATCHED-RANDOM STABILITY:
clears p<=0.10 in {r4_mr_pass}/{len(r4_mr)} periods (R2: {r2_mr_pass}/{len(r2_mr)}); see Section 5

BRANCH STATUS:
HOLD — AWAITING NEW DATA

---
"""

    body = f"""# Frozen R2/R4 Policy — Retrospective Stability Audit

Study directory: `studies/rank_filter_oos_validation/results/frozen_stability_audit/`
**No forward test beyond 2026-04-29 was run — no such data are available.** **R2 and R4 are frozen exactly as previously implemented** (score threshold 0.12855426455573915, R2 = strong-center-migration exemption, R4 = favorable-regime-asymmetry exemption, 30s entry delay, E0 exit) — nothing was retrained, retuned, or altered. This audit re-runs the existing NautilusTrader implementation over 8 retrospective blocks purely to characterize whether R4's (and R2's) apparent value is broadly distributed across market regimes or concentrated in isolated periods. **Every number below is a retrospective robustness diagnostic, not new out-of-sample evidence** — none of these blocks (including 2021-2024, never previously backtested with this exact frozen policy) should be read as validating or invalidating the branch; they only describe the shape of the historical distribution.

## 1. Data-Quality Caveat (2021-2024)

No bug-fixed per-year catalog exists for 2021-2024 (only `NQ_v0_2020_2026`, which has a documented ~1-second look-ahead in its separately-published 1-minute bar type from an un-fixed `closed='right'` resample). `CollectorV2Strategy`'s regime-flip *detection* is built causally from the 1-second bar stream (unaffected), but the bar+1 HH/LL *confirmation* check reads the catalog's 1-minute bar OHLC directly, so **2021-2024 confirmation checks inherit up to ~1s of look-ahead**. 2025 (all three blocks) and 2026 use the bug-fixed `NQ_v0_2025_fixed`/`NQ_v0_2026_fixed` catalogs and are unaffected. 2021-2024 rows are marked with `*` throughout and should be read as directionally informative, not decision-grade.

## 2. Period Metrics (`period_metrics.parquet`)

### R2

{fmt_block_table(pm, mr, td, "R2")}

### R4

{fmt_block_table(pm, mr, td, "R4")}

(`*` = 2021-2024, subject to the Section 1 catalog caveat. Max-DD change is in `period_drawdown_metrics.parquet`.)

## 3. Runner-PnL Retention by Period (`period_runner_retention.parquet`, top-decile tier)

| block | R2 | R4 |
|---|---|---|
""" + "\n".join(
        f"| {b} | {r2_runner_top10.get(b, float('nan')):.4f} | {r4_runner_top10.get(b, float('nan')):.4f} |"
        for b in BLOCK_ORDER
    ) + f"""

## 4. Drawdown Change by Period (`period_drawdown_metrics.parquet`)

| block | R2 Δ | R4 Δ |
|---|---|---|
""" + "\n".join(
        f"| {b} | ${dd_pivot.get((b,'R2'), float('nan')):+,.0f} | ${dd_pivot.get((b,'R4'), float('nan')):+,.0f} |"
        for b in BLOCK_ORDER
    ) + f"""

(Positive = drawdown improved relative to R0; negative = drawdown worsened.)

## 5. Matched-Random Stability (`period_matched_random.parquet`, 1,000 seeds/block, ATR-bucket edges frozen on validation period)

R4 clears the pre-declared p≤0.10 significance bar in **{r4_mr_pass} of {len(r4_mr)}** blocks; R2 clears it in **{r2_mr_pass} of {len(r2_mr)}**. Per-block p-values:

| block | R2 p | R4 p |
|---|---|---|
""" + "\n".join(
        f"| {b} | {r2_mr.get(b, float('nan')):.3f} | {r4_mr.get(b, float('nan')):.3f} |"
        for b in BLOCK_ORDER
    ) + f"""

## 6. Cross-Period Summary

| | R2 | R4 |
|---|---|---|
| Positive periods | {r2_summary['n_positive']}/{r2_summary['n_total']} | {r4_summary['n_positive']}/{r4_summary['n_total']} |
| Negative periods | {r2_summary['n_negative']}/{r2_summary['n_total']} | {r4_summary['n_negative']}/{r4_summary['n_total']} |
| Median period lift | ${r2_summary['median_lift']:+.2f} | ${r4_summary['median_lift']:+.2f} |
| Worst period | {worst_r2_str} | {worst_r4_str} |
| Cross-period std (lift) | ${r2_summary['std']:.2f} | ${r4_summary['std']:.2f} |
| Corr(R0 baseline environment, filter lift) | {r2_corr:+.3f} | {r4_corr:+.3f} |

**Correlation interpretation:** this is the Pearson correlation, across the 8 blocks, between R0's own EV-per-eligible-signal (a proxy for "how favorable was the underlying environment that block") and the filter's paired EV lift that same block. A value near zero means the filter's benefit doesn't depend on whether the baseline environment was itself good or bad; a strongly negative value would mean the filter mainly helps in bad environments (defensive value); a strongly positive value would mean it mainly helps when the environment is already good (adds on top of a tailwind, provides little diversification benefit).

## 7. Tail Dependence (`tail_dependence.parquet`)

For each block/policy, the paired lift is recomputed after removing the single largest avoided loss, and again after removing the top 2, from the skipped-trade set. This tests whether a period's apparent benefit is a broad, distributed effect or concentrated in one or two large avoided losses.

Full detail in the parquet; see the "lift excl top1/top2" columns in Section 2's tables above for values per block. A period where `lift_excl_top2_avoided_losses` flips sign or drops close to zero indicates that block's apparent benefit was concentrated in a small number of trades rather than broadly distributed.

## 8. Interpretation

This audit does not select a preferred threshold and does not modify R2 or R4. It exists solely to answer: **is the apparent value of the frozen policies broadly distributed across market regimes, or concentrated in isolated periods?** The cross-period positive/negative split, median/worst-period lift, cross-period standard deviation, matched-random pass rate, and tail-dependence figures above are the evidence for that question; read together with the existing `final_report.md` (the primary 2025H2/2026 NT validation) and the `HOLD` verdict already on file there.

## 9. Branch Status

**BRANCH STATUS: HOLD — AWAITING NEW DATA.**

No capital decision is made or implied by this audit. The branch remains on hold pending genuinely new data after 2026-04-29. Do not continue tuning, retraining, or threshold selection until that data is available.
"""

    with open(AUDIT_DIR / "final_report.md", "w", encoding="utf-8") as f:
        f.write(header + body)

    print(header)
    return header, body


if __name__ == "__main__":
    run()
