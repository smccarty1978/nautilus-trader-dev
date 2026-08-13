"""Phases 5-12 — policy economics, runner destruction, recovery, containment."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import polars as pl

from ..implementation.engine import LANDMARKS, PRICE_POLICIES, RUNNER_TIERS, _tag

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "studies/top10_post_confirmation_mfe_monetization/results"
ARMED = ROOT / "studies/armed_fade_score_path_progression/results/armed_regime_score_paths.parquet"
YEARS = (2021, 2022, 2023, 2024, 2025)

POLICIES = ["BASELINE", "P90A_EXIT", "P90B_EXIT", *PRICE_POLICIES,
            "P90ARM_GB050", "P90ARM_GB075", "P90ARM_PRICE", "P90ARM_PRICE_BUF",
            "P80ARM_075", "P80ARM_100", "P80ARM_P90EXIT", "STAIRSTEP"]
DOMAIN = {
    "BASELINE": "-", "P90A_EXIT": "A: NOT INTERPRETABLE - SURVIVORSHIP",
    "P90B_EXIT": "B: EXPLORATORY_OUT_OF_DOMAIN",
    "P90ARM_GB050": "B: EXPLORATORY_OUT_OF_DOMAIN",
    "P90ARM_GB075": "B: EXPLORATORY_OUT_OF_DOMAIN",
    "P90ARM_PRICE": "B: EXPLORATORY_OUT_OF_DOMAIN",
    "P90ARM_PRICE_BUF": "B: EXPLORATORY_OUT_OF_DOMAIN",
    "P80ARM_075": "B: EXPLORATORY_OUT_OF_DOMAIN",
    "P80ARM_100": "B: EXPLORATORY_OUT_OF_DOMAIN",
    "P80ARM_P90EXIT": "B: EXPLORATORY_OUT_OF_DOMAIN",
    **{k: "price only" for k in PRICE_POLICIES}, "STAIRSTEP": "price only",
}


def _m(s):
    s = s.drop_nulls()
    return round(float(s.median()), 4) if s.len() else None


def main() -> None:
    d = pl.read_parquet(OUT / "policy_panel.parquet")
    armed = pl.read_parquet(ARMED).filter(pl.col("valid"))
    n_entries = armed.height
    n_conf = d.height

    # Trades stopped BEFORE confirmation are untouched by every policy here, so
    # they cancel out of any delta -- but they must be carried in the LEVEL, or
    # the per-original-entry figure is inflated by conditioning on survivors,
    # which is exactly what the brief forbids.
    pre = armed.filter(pl.col("terminal_label_full") == "STOPPED_BEFORE_CONFIRM")
    pre_sum = float(pre["full_net_atr"].fill_null(0.0).sum())

    # Two giveback pools. The accepted excursion study measures it on flip-exit
    # trades only (~0.89 ATR/entry); including CONFIRMED_THEN_STOPPED adds their
    # peak-to-stop giveback and inflates the pool. Recovery is reported against
    # the ACCEPTED definition so it reconciles, with the wider pool alongside.
    flip = d.filter(pl.col("natural_kind") == "OPPOSING_FLIP")
    pool_accepted = float(flip["baseline_giveback_atr"].sum())
    pool_all_confirmed = float(d["baseline_giveback_atr"].sum())
    base_gb_pool = pool_accepted
    base_sum = float(d["BASELINE_net_atr"].sum())

    rows, dest, cont, stab = [], [], [], []
    for p in POLICIES:
        net = d[f"{p}_net_atr"]
        tot = float(net.sum())
        inc = tot - base_sum
        fired = d.filter(pl.col(f"{p}_exit_kind") == "POLICY")
        losers = d.filter(pl.col("BASELINE_net_atr") < 0)
        row = {
            "policy": p, "domain": DOMAIN[p],
            "coverage_pct": round(100 * fired.height / n_conf, 2),
            "mean_net_atr_per_confirmed": round(tot / n_conf, 4),
            "mean_net_atr_per_original_entry": round((tot + pre_sum) / n_entries, 4),
            "delta_per_original_entry": round(inc / n_entries, 4),
            "delta_per_confirmed": round(inc / n_conf, 4),
            "giveback_recovered_pct": round(100 * inc / base_gb_pool, 2)
                                      if base_gb_pool else None,
            "median_capture": _m(d[f"{p}_capture"]),
            "win_rate": round(float((net > 0).mean()), 4),
            "avg_winner": round(float(net.filter(net > 0).mean()), 4)
                          if (net > 0).any() else None,
            "avg_loser": round(float(net.filter(net < 0).mean()), 4)
                         if (net < 0).any() else None,
        }
        # Phase 12 loss containment, on trades the baseline lost.
        lb, lp = losers["BASELINE_net_atr"], losers[f"{p}_net_atr"]
        row["confirmed_losers_n"] = losers.height
        row["confirmed_losers_avg_baseline"] = round(float(lb.mean()), 4)
        row["confirmed_losers_avg_policy"] = round(float(lp.mean()), 4)
        row["confirmed_losers_atr_avoided"] = round(float((lp - lb).sum()), 2)
        row["confirmed_losers_improved_pct"] = round(100 * float((lp > lb).mean()), 2)
        row["confirmed_losers_turned_positive_pct"] = round(100 * float((lp > 0).mean()), 2)
        cont.append({"policy": p, **{k: row[k] for k in row if "loser" in k}})

        # Phase 10 runner destruction.
        for T in RUNNER_TIERS:
            col = f"{p}_cut_before_{_tag(T)}"
            pool = d.filter(pl.col("baseline_max_mfe_atr") >= T)
            cut = pool.filter(pl.col(col).fill_null(False)) if col in d.columns else pool.head(0)
            row[f"preserved_ge_{_tag(T)}_pct"] = (
                round(100 * (1 - cut.height / pool.height), 2) if pool.height else None)
            dest.append({
                "policy": p, "tier_atr": T, "n_runners": pool.height,
                "pct_cut_before_tier": round(100 * cut.height / pool.height, 2)
                                       if pool.height else None,
                "median_exit_return_of_cut": _m(cut[f"{p}_return_atr"]) if cut.height else None,
                "median_eventual_maxmfe_of_cut": _m(cut["baseline_max_mfe_atr"])
                                                 if cut.height else None,
                "atr_surrendered_by_cut": round(
                    float((cut["baseline_max_mfe_atr"] - cut[f"{p}_return_atr"]).sum()), 2)
                    if cut.height else 0.0,
            })
        for y in YEARS:
            s = d.filter(pl.col("entry_year") == y)
            row[f"y{y}"] = round(float(s[f"{p}_net_atr"].sum() - s["BASELINE_net_atr"].sum())
                                 / n_entries * 5, 4)
        rows.append(row)

        for key, sub in ([("pooled", d)]
                         + [(f"side:{s}", d.filter(pl.col("side") == s)) for s in ("LONG", "SHORT")]
                         + [(f"year:{y}", d.filter(pl.col("entry_year") == y)) for y in YEARS]):
            if sub.height == 0:
                continue
            stab.append({"policy": p, "slice": key, "n": sub.height,
                         "delta_atr_per_confirmed": round(float(
                             (sub[f"{p}_net_atr"] - sub["BASELINE_net_atr"]).mean()), 4),
                         "median_capture": _m(sub[f"{p}_capture"])})

    t = pl.DataFrame(rows, infer_schema_length=None)
    t.write_parquet(OUT / "policy_results.parquet"); t.write_csv(OUT / "policy_results.csv")
    pl.DataFrame(dest, infer_schema_length=None).write_parquet(OUT / "runner_destruction.parquet")
    pl.DataFrame(cont, infer_schema_length=None).write_parquet(OUT / "loss_containment.parquet")
    pl.DataFrame(stab, infer_schema_length=None).write_parquet(OUT / "year_direction_stability.parquet")
    (OUT / "giveback_recovery.json").write_text(json.dumps({
        "original_top10_entries": n_entries, "confirmed_trades": n_conf,
        "giveback_pool_accepted_flip_exit_only_atr": round(pool_accepted, 2),
        "giveback_pool_accepted_per_original_entry": round(pool_accepted / n_entries, 4),
        "giveback_pool_all_confirmed_atr": round(pool_all_confirmed, 2),
        "giveback_pool_all_confirmed_per_original_entry": round(pool_all_confirmed / n_entries, 4),
        "recovery_denominator": "accepted flip-exit-only pool",
        "baseline_net_atr_per_original_entry": round((base_sum + pre_sum) / n_entries, 4),
        "stopped_before_confirmation_n": pre.height,
        "stopped_before_confirmation_net_atr": round(pre_sum, 2),
        "policies": {r["policy"]: {k: r[k] for k in (
            "delta_per_original_entry", "giveback_recovered_pct", "domain")} for r in rows},
    }, indent=2, default=str))

    print(f"entries {n_entries:,} · confirmed {n_conf:,} · giveback pool "
          f"{base_gb_pool:,.0f} ATR = {base_gb_pool/n_entries:.3f}/entry · "
          f"baseline net {base_sum/n_entries:+.4f}/entry\n")
    print(f"{'policy':22s}{'cov%':>6s}{'d/entry':>9s}{'recov%':>8s}{'cap':>7s}"
          f"{'win':>6s}{'>=2':>6s}{'>=2.5':>7s}{'>=3':>6s}{'losFix%':>8s}{'domain':>34s}")
    for r in sorted(rows, key=lambda x: -x["delta_per_original_entry"]):
        print(f"{r['policy']:22s}{r['coverage_pct']:>6.1f}{r['delta_per_original_entry']:>+9.4f}"
              f"{(r['giveback_recovered_pct'] or 0):>8.1f}{(r['median_capture'] or 0):>7.3f}"
              f"{r['win_rate']:>6.3f}{(r['preserved_ge_2_00_pct'] or 0):>6.1f}"
              f"{(r['preserved_ge_2_50_pct'] or 0):>7.1f}{(r['preserved_ge_3_00_pct'] or 0):>6.1f}"
              f"{r['confirmed_losers_improved_pct']:>8.1f}  {r['domain']:<32s}")


if __name__ == "__main__":
    main()
