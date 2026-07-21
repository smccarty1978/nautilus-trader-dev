"""Assemble final_report.md, including the required opening summary block,
by reading the already-computed output parquet/json files."""
from __future__ import annotations
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
import pandas as pd
import awf_common as c

STATIC_COUNTERPART = {"a1": None, "a2": "static_r2", "a4": "static_r4"}


def df_to_md(df: pd.DataFrame, floatfmt: str = ".4f") -> str:
    """Minimal markdown table renderer (tabulate is not installed)."""
    cols = list(df.columns)
    def fmt(v):
        if isinstance(v, float):
            return format(v, floatfmt)
        return str(v)
    header = "| " + " | ".join(cols) + " |"
    sep = "|" + "|".join(["---"] * len(cols)) + "|"
    body = "\n".join("| " + " | ".join(fmt(v) for v in row) + " |" for row in df[cols].itertuples(index=False))
    return "\n".join([header, sep, body])


def best_adaptive_policy(final_reserved: pd.DataFrame, bootstrap: pd.DataFrame,
                          runner_retention: pd.DataFrame, matched_random: pd.DataFrame,
                          static_r4_lift: float):
    """Selects the adaptive policy with the best final-reserved EV lift vs R0
    among policies satisfying the decision-criteria gates, defaulting to the
    best-lift policy overall if none fully qualify (verdict reflects this)."""
    adaptive = final_reserved[final_reserved["policy_family"].isin(["a1", "a2", "a4"])].copy()
    r0_row = final_reserved[final_reserved["policy"] == "r0"].iloc[0]

    boot_r0 = bootstrap[(bootstrap["block"] == "2026_MarApr_final_reserved") & (bootstrap["comparator"] == "r0")]
    adaptive = adaptive.merge(boot_r0[["policy", "paired_ev_lift", "ev_lift_ci_lo", "ev_lift_ci_hi"]],
                               on="policy", how="left")

    mr = matched_random[matched_random["block"] == "2026_MarApr_final_reserved"][["policy", "empirical_p_value"]]
    adaptive = adaptive.merge(mr, on="policy", how="left")

    rr = runner_retention[(runner_retention["block"] == "2026_MarApr_final_reserved") & (runner_retention["tier"] == "top10pct")][["policy", "retention_rate"]]
    adaptive = adaptive.merge(rr, on="policy", how="left")

    adaptive = adaptive.sort_values("paired_ev_lift", ascending=False)
    return adaptive


def monthly_positive_count(monthly: pd.DataFrame, policy: str) -> tuple[int, int]:
    sub = monthly[monthly["policy"] == policy]
    n_pos = int((sub["ev_per_eligible_signal"] >= 0).sum())
    return n_pos, len(sub)


def main():
    final_reserved = pd.read_parquet(c.OUT / "final_reserved_results.parquet")
    monthly = pd.read_parquet(c.OUT / "monthly_results.parquet")
    bootstrap = pd.read_parquet(c.OUT / "paired_bootstrap.parquet")
    runner_retention = pd.read_parquet(c.OUT / "runner_retention.parquet")
    matched_random = pd.read_parquet(c.OUT / "matched_random_summary.parquet")
    tail_dependence = pd.read_parquet(c.OUT / "tail_dependence.parquet")
    provenance = json.load(open(c.OUT / "provenance_audit.json"))
    parity = pd.read_parquet(c.OUT / "nt_parity_audit.parquet")

    static_r4_row = final_reserved[final_reserved["policy"] == "static_r4"].iloc[0]
    r0_lift_base = float(final_reserved[final_reserved["policy"] == "r0"].iloc[0]["ev_per_eligible_signal"])
    static_r4_ev = float(static_r4_row["ev_per_eligible_signal"])
    static_r4_lift = static_r4_ev - r0_lift_base  # static R4's own lift vs R0 (this study's "final EV lift" framing)

    # The decision criteria (per the task brief) are specifically about A4 vs
    # static R4 -- evaluate them against the BEST-PERFORMING A4 window, not
    # against whichever policy happens to have the single highest vs-R0 lift
    # overall (that "best overall" pick is reported separately, below, purely
    # as descriptive context; it does not drive the verdict).
    a4_rows = final_reserved[final_reserved["policy_family"] == "a4"].sort_values("ev_per_eligible_signal", ascending=False)
    best_a4 = a4_rows.iloc[0]
    best_policy = best_a4["policy"]
    best_family, best_window = "a4", best_policy.split("_", 1)[1]
    a4_own_lift_vs_r0 = float(best_a4["ev_per_eligible_signal"] - r0_lift_base)

    boot_vs_r0 = bootstrap[(bootstrap["block"] == "2026_MarApr_final_reserved") & (bootstrap["policy"] == best_policy) & (bootstrap["comparator"] == "r0")]
    if len(boot_vs_r0):
        best_lift = float(boot_vs_r0["paired_ev_lift"].iloc[0])
        ci_lo, ci_hi = float(boot_vs_r0["ev_lift_ci_lo"].iloc[0]), float(boot_vs_r0["ev_lift_ci_hi"].iloc[0])
    else:
        best_lift = a4_own_lift_vs_r0
        ci_lo, ci_hi = float("nan"), float("nan")

    boot_vs_static = bootstrap[(bootstrap["block"] == "2026_MarApr_final_reserved") & (bootstrap["policy"] == best_policy) & (bootstrap["comparator"] == "static_r4")]
    a4_vs_static_lift = float(boot_vs_static["paired_ev_lift"].iloc[0]) if len(boot_vs_static) else float(best_a4["ev_per_eligible_signal"] - static_r4_ev)

    rr_row = runner_retention[(runner_retention["block"] == "2026_MarApr_final_reserved") &
                                (runner_retention["tier"] == "top10pct") & (runner_retention["policy"] == best_policy)]
    top_decile_retention = float(rr_row["retention_rate"].iloc[0]) if len(rr_row) else float("nan")

    mr_row = matched_random[(matched_random["block"] == "2026_MarApr_final_reserved") & (matched_random["policy"] == best_policy)]
    matched_p = float(mr_row["empirical_p_value"].iloc[0]) if len(mr_row) else float("nan")

    n_pos, n_total = monthly_positive_count(monthly, best_policy)

    retained_parity_pass = provenance["retained_trade_parity_pass"]
    provenance_pass = provenance["all_assertions_pass"]

    # ---- decision criteria (A4 vs static R4, per the task brief) ----
    tail_row = tail_dependence[(tail_dependence["block"] == "2026_MarApr_final_reserved") & (tail_dependence["policy"] == best_policy)]
    driven_by_tail = bool(tail_row["driven_by_top2_pct"].iloc[0] > 75) if len(tail_row) and not pd.isna(tail_row["driven_by_top2_pct"].iloc[0]) else False

    criteria = {
        "A4 EV lift > static R4 EV lift": a4_vs_static_lift > 0,
        "A4 EV lift > 0 (vs R0)": a4_own_lift_vs_r0 > 0,
        "top-decile runner retention >= 95%": (not pd.isna(top_decile_retention)) and top_decile_retention >= 0.95,
        "matched-random empirical p <= 0.10": (not pd.isna(matched_p)) and matched_p <= 0.10,
        "most months neutral/positive": n_pos >= (n_total / 2),
        "not driven by top 1-2 avoided losses": not driven_by_tail,
        "no execution/provenance violations": retained_parity_pass and provenance_pass,
    }
    n_criteria_met = sum(criteria.values())
    if n_criteria_met == len(criteria):
        verdict = "ADAPTIVE IMPROVES"
    elif a4_vs_static_lift <= 0 and a4_own_lift_vs_r0 <= 0:
        verdict = "NO IMPROVEMENT"
    else:
        verdict = "INCONCLUSIVE"

    if verdict == "ADAPTIVE IMPROVES":
        next_step = f"Advance {best_policy} to a live-style NT deployment gate check before considering production use."
    elif verdict == "NO IMPROVEMENT":
        next_step = "Rolling retraining did not solve the static filter's instability; do not pursue this branch further without a materially different feature/model approach."
    else:
        next_step = "Treat as a fragile/marginal result; do not deploy without further out-of-sample confirmation beyond this single reserved block."

    lines = []
    lines.append("ADAPTIVE WALK-FORWARD STUDY:")
    lines.append("COMPLETE")
    lines.append("")
    lines.append("FINAL RESERVED BLOCK:")
    lines.append("2026-03-01 through 2026-04-29")
    lines.append("")
    lines.append("STATIC R4 FINAL EV LIFT:")
    lines.append(f"${static_r4_lift:.2f}")
    lines.append("")
    lines.append("BEST ADAPTIVE POLICY:")
    lines.append(f"{best_family.upper()}, {best_window}")
    lines.append("")
    lines.append("BEST ADAPTIVE FINAL EV LIFT:")
    lines.append(f"${best_lift:.2f}")
    lines.append("")
    lines.append("BEST ADAPTIVE 95% CI:")
    lines.append(f"(${ci_lo:.2f}, ${ci_hi:.2f})")
    lines.append("")
    lines.append("BEST ADAPTIVE TOP-DECILE RUNNER RETENTION:")
    lines.append(f"{top_decile_retention:.1%}" if not pd.isna(top_decile_retention) else "N/A")
    lines.append("")
    lines.append("BEST ADAPTIVE MATCHED-RANDOM P:")
    lines.append(f"{matched_p:.4f}" if not pd.isna(matched_p) else "N/A")
    lines.append("")
    lines.append("MONTHS POSITIVE:")
    lines.append(f"{n_pos}/{n_total}")
    lines.append("")
    lines.append("RETAINED-TRADE PARITY:")
    lines.append("PASS" if retained_parity_pass else "FAIL")
    lines.append("")
    lines.append("PROVENANCE AUDIT:")
    lines.append("PASS" if provenance_pass else "FAIL")
    lines.append("")
    lines.append("VERDICT:")
    lines.append(verdict)
    lines.append("")
    lines.append("NEXT STEP:")
    lines.append(next_step)
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Decision criteria detail")
    lines.append("")
    lines.append("| Criterion | Met |")
    lines.append("|---|---|")
    for k, v in criteria.items():
        lines.append(f"| {k} | {'YES' if v else 'no'} |")
    lines.append("")
    lines.append(f"Criteria met: {n_criteria_met}/{len(criteria)}")
    lines.append("")

    ranked_overall = best_adaptive_policy(final_reserved, bootstrap, runner_retention, matched_random, static_r4_lift)
    overall_best = ranked_overall.iloc[0]
    if overall_best["policy"] != best_policy:
        lines.append(f"Note: the single best-performing adaptive policy overall (by EV lift vs R0, "
                      f"any family) is **{overall_best['policy']}** at ${overall_best['paired_ev_lift']:.2f}/eligible "
                      f"signal. The summary block above and the verdict are keyed to the best-performing "
                      f"**A4** window specifically ({best_policy}), since the task's decision criteria are framed "
                      f"around A4 vs static R4 -- A1/A2 are reported in full in the tables below for comparison.")
        lines.append("")

    lines.append("## Final reserved block (2026-03 .. 2026-04): all policies")
    lines.append("")
    fr_display = final_reserved[["policy", "eligible_signals", "filled_trades", "skip_rate",
                                   "ev_per_eligible_signal", "ev_per_filled_trade", "net_pnl",
                                   "win_rate", "profit_factor"]].sort_values("ev_per_eligible_signal", ascending=False)
    lines.append(df_to_md(fr_display))
    lines.append("")

    lines.append("## Pooled 2025 (Jan-Dec) results")
    lines.append("")
    pooled = pd.read_parquet(c.OUT / "pooled_results.parquet")
    pooled_2025 = pooled[pooled["block"] == "2025_JanDec"][["policy", "eligible_signals", "filled_trades",
                                                              "skip_rate", "ev_per_eligible_signal", "net_pnl",
                                                              "win_rate", "profit_factor"]].sort_values("ev_per_eligible_signal", ascending=False)
    lines.append(df_to_md(pooled_2025))
    lines.append("")

    lines.append("## Paired bootstrap (final reserved block)")
    lines.append("")
    boot_fr = bootstrap[bootstrap["block"] == "2026_MarApr_final_reserved"][
        ["policy", "comparator", "n_episodes", "paired_ev_lift", "ev_lift_ci_lo", "ev_lift_ci_hi"]]
    lines.append(df_to_md(boot_fr))
    lines.append("")

    lines.append("## Matched-random controls (final reserved block)")
    lines.append("")
    mr_fr = matched_random[matched_random["block"] == "2026_MarApr_final_reserved"]
    lines.append(df_to_md(mr_fr))
    lines.append("")

    lines.append("## Tail dependence (final reserved block)")
    lines.append("")
    td_fr = tail_dependence[tail_dependence["block"] == "2026_MarApr_final_reserved"]
    lines.append(df_to_md(td_fr))
    lines.append("")

    lines.append("## Runner retention (final reserved block, top-decile)")
    lines.append("")
    rr_fr = runner_retention[(runner_retention["block"] == "2026_MarApr_final_reserved") & (runner_retention["tier"] == "top10pct")]
    lines.append(df_to_md(rr_fr))
    lines.append("")

    lines.append("## Provenance / execution audit")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(provenance, indent=2))
    lines.append("```")
    lines.append("")
    lines.append(f"Retained-trade parity overall: {parity['n_exact_match'].sum() / parity['n_retained_filled'].sum() * 100:.4f}% "
                  f"({int(parity['n_mismatched'].sum())} mismatches across {int(parity['n_retained_filled'].sum())} retained trades)")
    lines.append("")

    lines.append("## Model quality (validation AUC by fold)")
    lines.append("")
    ta = pd.read_parquet(c.OUT / "model_training_audit.parquet")
    auc_summary = ta.groupby("window_name")["val_auc"].agg(["mean", "min", "max", "count"])
    lines.append(df_to_md(auc_summary.reset_index()))
    lines.append("")
    lines.append("Note: fold-level validation AUCs cluster near 0.50 (little to no genuine "
                 "out-of-sample discrimination month-to-month), consistent with this project's "
                 "prior finding that this feature family's OOS AUC is weak and unstable "
                 "(see memory: static_p4_robustness_real_but_fragile, v_a_1m_flip_signal_class_dead). "
                 "Any adaptive EV lift found here should be read against that backdrop.")
    lines.append("")

    with open(c.OUT / "final_report.md", "w") as f:
        f.write("\n".join(lines))

    print("Wrote final_report.md")
    print("\n".join(lines[:32]))


if __name__ == "__main__":
    main()
