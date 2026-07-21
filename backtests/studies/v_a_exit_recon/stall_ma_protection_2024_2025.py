"""V_A Stall-to-MA Protection — full grid across 2024 + 2025 RTH.

Re-runs the 24-variant grid using the CORRECTED flip-bar logic
(flip_bar_ts_init = floor(decision_ts to 60s) - 60s) on the full
2024 + 2025 RTH span (~6,653 trades).

Outputs:
  studies/v_a_exit_recon/results/stall_ma_protection_2024_2025/
    trades_<variant>.parquet
    grid_summary.parquet
    audit_summary.parquet
    sensitivity_summary.parquet
    REPORT_2024_2025.md
"""

from __future__ import annotations
import os, sys, time, json
from pathlib import Path
import numpy as np
import pandas as pd
import pytz

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

from studies.v_a_exit_recon.stall_ma_protection import (
    compute_mas, build_1m_lookup, build_bars_lookup_fn,
    replay_variant, variant_summary, _finalize_safe,
    fmt_d, fmt_p, fmt_pf, stats,
)
from utils.audit_replay_fills import audit_trades, AuditConfig

CT = pytz.timezone("America/Chicago")
PORT = Path("collectors/collector_v2/results/with_tape")
OUT = Path(
    "studies/v_a_exit_recon/results/stall_ma_protection_2024_2025")
OUT.mkdir(parents=True, exist_ok=True)


def load_2024_2025_rth():
    print("Loading 2024 + 2025 RTH trades + tape...")
    all_trades = []; all_tape = []
    for yr in (2024, 2025):
        d = PORT / f"NQ_{yr}"
        t = pd.read_parquet(d / "trades.parquet")
        tape = pd.read_parquet(d / "trade_tape.parquet")
        rth = t[t["session"] == "RTH"].copy()
        ids = set(rth["decision_event_id"])
        tape_rth = tape[tape["decision_event_id"].isin(ids)].copy()
        # Year-prefix trade_id to avoid id collisions across years
        OFFSET = yr * 1_000_000
        rth["trade_id"] = rth["decision_event_id"] + OFFSET
        rth["baseline_net_pnl"] = rth["net_pnl"]
        rth["year"] = yr
        tape_rth["trade_id"] = (
            tape_rth["decision_event_id"] + OFFSET)
        tape_rth = tape_rth.sort_values(
            ["trade_id", "ts_init"]).reset_index(drop=True)
        print(f"  NQ {yr} RTH: {len(rth):,} trades, "
              f"{len(tape_rth):,} tape rows")
        all_trades.append(rth)
        all_tape.append(tape_rth)
    trades = pd.concat(all_trades, ignore_index=True)
    tape = pd.concat(all_tape, ignore_index=True)
    return trades, tape


def load_1m_bars_2024_2025():
    print("Loading 1m bars from catalog (Dec 2023 - Jan 2026)...")
    from nautilus_trader.persistence.catalog import (
        ParquetDataCatalog,
    )
    cat = ParquetDataCatalog("./data/catalog/NQ_2020_2025")
    start = pd.Timestamp("2023-12-01", tz="UTC")
    end = pd.Timestamp("2026-01-01", tz="UTC")
    bars = cat.bars(
        bar_types=["NQ.XCME-1-MINUTE-LAST-EXTERNAL"],
        start=start, end=end)
    rows = [(int(b.ts_init), float(b.open), float(b.high),
              float(b.low), float(b.close)) for b in bars]
    df = pd.DataFrame(rows, columns=[
        "ts_init", "open", "high", "low", "close"])
    df = df.sort_values("ts_init").reset_index(drop=True)
    print(f"  1m bars: {len(df):,}")
    return df


def per_year_stats(name, df):
    """Per-year breakdown."""
    out = {"variant": name}
    df = df.copy()
    df["year"] = df["entry_ts"].apply(
        lambda ts: pd.Timestamp(int(ts), tz="UTC")
        .tz_convert(CT).year)
    for yr in (2024, 2025):
        sub = df[df["year"] == yr]
        s = stats(sub["net_pnl"])
        out[f"y{yr}_n"] = s.get("n", 0)
        out[f"y{yr}_total"] = s.get("sum")
        out[f"y{yr}_mean"] = s.get("mean")
        out[f"y{yr}_pf"] = s.get("pf")
        out[f"y{yr}_wr"] = s.get("wr")
        out[f"y{yr}_dd"] = s.get("max_dd")
        # vs baseline
        if len(sub):
            out[f"y{yr}_vs_base"] = float(
                sub["net_pnl"].sum()
                - sub["baseline_net_pnl"].sum())
        else:
            out[f"y{yr}_vs_base"] = 0.0
    return out


def main():
    t_start = time.time()
    print("=" * 70)
    print("V_A Stall-to-MA Protection — 2024 + 2025 RTH "
          "(corrected flip bar)")
    print("=" * 70)

    trades, tape = load_2024_2025_rth()
    bars_1m = load_1m_bars_2024_2025()
    ma_series = compute_mas(bars_1m)
    bars_1m_lookup = build_1m_lookup(bars_1m)
    bars_lookup_fn = build_bars_lookup_fn(bars_1m_lookup, tape)

    print(f"\nTotal trades: {len(trades):,}")

    summaries = []
    per_yr_summaries = []
    audits = []
    audit_failed = []

    # B1: regime-only
    print("\nRunning baselines + 24 variants...")
    b1_rows = []
    for _, t in trades.iterrows():
        b1_rows.append(_finalize_safe(
            t, float(t["exit_price"]), int(t["exit_ts"]),
            "regime", fired_rule=False,
            extra={"cat_stop": None,
                      "cat_invalid_at_entry": False,
                      "ma_armed": False, "protect_px": None,
                      "n_arms": 0, "n_updates": 0,
                      "n_invalid_at_update": 0}))
    base_df = pd.DataFrame(b1_rows)
    base_df.to_parquet(
        OUT / "trades_BASELINE_regime.parquet", index=False)
    summaries.append(variant_summary("BASELINE_regime", base_df))
    per_yr_summaries.append(per_year_stats(
        "BASELINE_regime", base_df))
    s = summaries[-1]
    print(f"  BASELINE_regime: total {fmt_d(s['all_sum'])}, "
          f"mean {fmt_d(s['all_mean'])}, "
          f"WR {fmt_p(s['all_wr'])}, PF {fmt_pf(s['all_pf'])}")

    # B2: cat only
    cat_only_df = replay_variant(
        trades, tape, bars_1m_lookup,
        ma_lookup={}, stall_bars=999, use_cat_stop=True)
    cat_only_df.to_parquet(
        OUT / "trades_BASELINE_cat_only.parquet", index=False)
    summaries.append(variant_summary(
        "BASELINE_cat_only", cat_only_df))
    per_yr_summaries.append(per_year_stats(
        "BASELINE_cat_only", cat_only_df))
    s = summaries[-1]
    print(f"  BASELINE_cat_only: total {fmt_d(s['all_sum'])}, "
          f"mean {fmt_d(s['all_mean'])}, "
          f"cat-exits {fmt_p(s['pct_cat'])}, "
          f"cat-invalid-at-entry "
          f"{fmt_p(s['pct_cat_invalid_at_entry'])}, "
          f"vs base {fmt_d(s['all_vs_base_total'])}")
    ar = audit_trades(cat_only_df, bars_lookup_fn,
                            AuditConfig(
                                hard_fail_on_impossible=False))
    audits.append({"variant": "BASELINE_cat_only",
                       "impossible": ar.impossible_fills_n,
                       "impossible_pnl": ar.impossible_fills_pnl})
    if ar.has_impossible_fills:
        audit_failed.append("BASELINE_cat_only")

    # 24-variant grid
    STALL_BARS = [2, 3, 4, 5]
    MA_TYPES = ["SMA", "EMA"]
    MA_LENS = [9, 13, 21]

    grid = []
    for sb in STALL_BARS:
        for mt in MA_TYPES:
            for ml in MA_LENS:
                grid.append((sb, mt, ml))

    for i, (sb, mt, ml) in enumerate(grid, 1):
        t0 = time.time()
        name = f"S{sb}_{mt}{ml}"
        ma_lookup = ma_series[(mt, ml)]
        df = replay_variant(
            trades, tape, bars_1m_lookup, ma_lookup,
            stall_bars=sb,
            ohlc_convention="at_or_worse_close",
            invalid_stop_policy="market_exit_now",
            use_cat_stop=True)
        df.to_parquet(
            OUT / f"trades_{name}.parquet", index=False)
        ar = audit_trades(df, bars_lookup_fn,
                                AuditConfig(
                                    hard_fail_on_impossible=False))
        audits.append({"variant": name,
                            "impossible": ar.impossible_fills_n,
                            "impossible_pnl": (
                                ar.impossible_fills_pnl)})
        if ar.has_impossible_fills:
            audit_failed.append(name)
        s = variant_summary(name, df)
        summaries.append(s)
        per_yr_summaries.append(per_year_stats(name, df))
        elapsed = time.time() - t0
        print(f"  [{i:2d}/24] {name:<14} "
              f"total {fmt_d(s['all_sum'])} "
              f"vs_base {fmt_d(s['all_vs_base_total']):>10} "
              f"cat={fmt_p(s['pct_cat'])} "
              f"ma={fmt_p(s['pct_ma_protect'])} "
              f"reg={fmt_p(s['pct_regime'])} "
              f"imposs={ar.impossible_fills_n} ({elapsed:.1f}s)")

    # Diagnostic sensitivity (3 reps)
    print("\nDiagnostic sensitivity (skip + worst_in_bar) on 3 reps...")
    sens_variants = [
        ("S3_SMA21", 3, "SMA", 21),
        ("S4_EMA13", 4, "EMA", 13),
        ("S5_SMA21", 5, "SMA", 21),  # best from H1 2025 corrected
    ]
    sens_rows = []
    for name, sb, mt, ml in sens_variants:
        ma_lookup = ma_series[(mt, ml)]
        for label, kw in [
            ("worst_in_bar", {
                "ohlc_convention": "worst_in_bar",
                "invalid_stop_policy": "market_exit_now"}),
            ("skip_update_and_hold", {
                "ohlc_convention": "at_or_worse_close",
                "invalid_stop_policy": "skip_update_and_hold"}),
        ]:
            df = replay_variant(
                trades, tape, bars_1m_lookup, ma_lookup,
                stall_bars=sb, use_cat_stop=True, **kw)
            df.to_parquet(
                OUT / f"sens_{name}_{label}.parquet", index=False)
            s = variant_summary(f"{name}__{label}", df)
            sens_rows.append(s)
            print(f"  {name} [{label:<22}] total "
                  f"{fmt_d(s['all_sum'])}, mean "
                  f"{fmt_d(s['all_mean'])}/trade")
    sens_df = pd.DataFrame(sens_rows)
    sens_df.to_parquet(OUT / "sensitivity_summary.parquet",
                              index=False)

    # Save summaries
    summ_df = pd.DataFrame(summaries)
    summ_df.to_parquet(OUT / "grid_summary.parquet", index=False)
    yr_df = pd.DataFrame(per_yr_summaries)
    yr_df.to_parquet(OUT / "per_year_summary.parquet", index=False)
    audit_df = pd.DataFrame(audits)
    audit_df.to_parquet(OUT / "audit_summary.parquet", index=False)

    # Markdown report
    print("\nWriting REPORT_2024_2025.md...")
    write_report(summaries, per_yr_summaries, audits, sens_df,
                       audit_failed)

    elapsed = (time.time() - t_start) / 60
    print(f"\nDone. {elapsed:.1f} min")
    return 0 if not audit_failed else 1


def write_report(summaries, per_yr, audits, sens_df,
                       audit_failed):
    base_regime = next(s for s in summaries
                          if s["variant"] == "BASELINE_regime")
    base_total = base_regime["all_sum"]
    base_per_yr = next(s for s in per_yr
                          if s["variant"] == "BASELINE_regime")
    cat_only = next(s for s in summaries
                       if s["variant"] == "BASELINE_cat_only")

    lines = []
    lines.append("# V_A Stall-to-MA Protection — 2024 + 2025 RTH "
                  "(corrected flip bar)")
    lines.append("")
    lines.append(f"Run: {pd.Timestamp.now(tz='UTC').isoformat()}")
    lines.append("")
    lines.append("Re-runs the 24-variant grid using the corrected "
                  "`flip_bar_ts_init` (now subtracts an extra 60s "
                  "to land on the actual flip bar, not the "
                  "confirmation bar). Question: does any variant "
                  "beat baseline regime exit on the full 2-year "
                  "span?")
    lines.append("")
    lines.append("## Configuration")
    lines.append("")
    lines.append(f"- Span: NQ RTH 2024 + 2025")
    lines.append(f"- Population: {base_regime['all_n']:,} V_A "
                  "trades")
    lines.append("- Cost: $10 RT")
    lines.append("- Framework: `utils/safe_replay`")
    lines.append("- Primary mode: conservative_ohlc / "
                  "at_or_worse_close / market_exit_now")
    lines.append("- 24 variants: stall {2,3,4,5} × {SMA,EMA} × "
                  "{9,13,21}")
    lines.append("")

    lines.append("## Audit verdict")
    lines.append("")
    if audit_failed:
        lines.append(f"- **FAIL** — {len(audit_failed)} variants "
                      f"with impossible fills:")
        for n in audit_failed:
            lines.append(f"  - `{n}`")
    else:
        lines.append(f"- **PASS** — 0 impossible fills across "
                      f"{len(audits)} variants")
    lines.append("")

    lines.append("## Baselines")
    lines.append("")
    lines.append(f"- **BASELINE_regime**: n={base_regime['all_n']:,}"
                  f", total **{fmt_d(base_total)}**, mean "
                  f"{fmt_d(base_regime['all_mean'])}, PF "
                  f"{fmt_pf(base_regime['all_pf'])}, WR "
                  f"{fmt_p(base_regime['all_wr'])}")
    for yr in (2024, 2025):
        lines.append(f"  - {yr}: n={base_per_yr[f'y{yr}_n']:,}, "
                      f"total {fmt_d(base_per_yr[f'y{yr}_total'])}, "
                      f"mean {fmt_d(base_per_yr[f'y{yr}_mean'])}, "
                      f"PF {fmt_pf(base_per_yr[f'y{yr}_pf'])}, "
                      f"WR {fmt_p(base_per_yr[f'y{yr}_wr'])}")
    lines.append(f"- **BASELINE_cat_only**: total "
                  f"{fmt_d(cat_only['all_sum'])}, mean "
                  f"{fmt_d(cat_only['all_mean'])}, "
                  f"cat-exits {fmt_p(cat_only['pct_cat'])}, "
                  f"cat-invalid-at-entry "
                  f"{fmt_p(cat_only['pct_cat_invalid_at_entry'])}, "
                  f"vs base "
                  f"{fmt_d(cat_only['all_vs_base_total'])}")
    lines.append("")

    surviving = [s for s in summaries
                    if s["variant"].startswith("S")
                    and s["all_sum"] is not None
                    and s["all_sum"] > base_total]
    lines.append("## Survivors (beat BASELINE_regime all-years)")
    lines.append("")
    if not surviving:
        lines.append("**No variant beats BASELINE_regime "
                      f"({fmt_d(base_total)}).**")
    else:
        lines.append(f"{len(surviving)} variants beat baseline:")
        lines.append("")
        lines.append("| Variant | Total | vs Base | Mean | PF | "
                     "WR | %cat | %ma | %reg |")
        lines.append("|---|--:|--:|--:|--:|--:|--:|--:|--:|")
        for s in sorted(surviving, key=lambda x: -x["all_sum"]):
            lines.append(
                f"| `{s['variant']}` | "
                f"{fmt_d(s['all_sum'])} | "
                f"+{fmt_d(s['all_vs_base_total'])} | "
                f"{fmt_d(s['all_mean'])} | "
                f"{fmt_pf(s['all_pf'])} | "
                f"{fmt_p(s['all_wr'])} | "
                f"{fmt_p(s['pct_cat'])} | "
                f"{fmt_p(s['pct_ma_protect'])} | "
                f"{fmt_p(s['pct_regime'])} |")
    lines.append("")

    lines.append("## Full scoreboard (all-years)")
    lines.append("")
    lines.append("| Variant | n | Total | vs Base | Mean | PF | "
                 "WR | DD | MedHold | %cat | %ma | %reg | "
                 "%inv@entry | top-1% |")
    lines.append("|" + "|".join(["---"] * 14) + "|")
    for s in summaries:
        is_base = s["variant"].startswith("BASELINE")
        delta = ("(base)" if s["variant"] == "BASELINE_regime"
                  else f"{'+' if s['all_vs_base_total'] >= 0 else ''}"
                       f"{fmt_d(s['all_vs_base_total'])}")
        prefix = "**" if is_base else ""
        suffix = "**" if is_base else ""
        lines.append(
            f"| {prefix}`{s['variant']}`{suffix} | "
            f"{s['all_n']:,} | {fmt_d(s.get('all_sum'))} | "
            f"{delta} | {fmt_d(s.get('all_mean'))} | "
            f"{fmt_pf(s.get('all_pf'))} | "
            f"{fmt_p(s.get('all_wr'))} | "
            f"{fmt_d(s.get('all_max_dd'))} | "
            f"{s.get('med_hold_s', 0):.0f}s | "
            f"{fmt_p(s.get('pct_cat', 0))} | "
            f"{fmt_p(s.get('pct_ma_protect', 0))} | "
            f"{fmt_p(s.get('pct_regime', 0))} | "
            f"{fmt_p(s.get('pct_cat_invalid_at_entry', 0))} | "
            f"{fmt_p(s.get('top1_share', 0))} |")
    lines.append("")

    lines.append("## Per-year breakdown")
    lines.append("")
    lines.append("| Variant | 2024 total | 2024 vs base | 2024 PF | "
                 "2024 WR | 2025 total | 2025 vs base | 2025 PF | "
                 "2025 WR |")
    lines.append("|---|--:|--:|--:|--:|--:|--:|--:|--:|")
    for s in per_yr:
        is_base = s["variant"] == "BASELINE_regime"
        y24_delta = ("(base)" if is_base
                       else f"{'+' if s['y2024_vs_base'] >= 0 else ''}"
                            f"{fmt_d(s['y2024_vs_base'])}")
        y25_delta = ("(base)" if is_base
                       else f"{'+' if s['y2025_vs_base'] >= 0 else ''}"
                            f"{fmt_d(s['y2025_vs_base'])}")
        prefix = "**" if is_base else ""
        suffix = "**" if is_base else ""
        lines.append(
            f"| {prefix}`{s['variant']}`{suffix} | "
            f"{fmt_d(s.get('y2024_total'))} | {y24_delta} | "
            f"{fmt_pf(s.get('y2024_pf'))} | "
            f"{fmt_p(s.get('y2024_wr'))} | "
            f"{fmt_d(s.get('y2025_total'))} | {y25_delta} | "
            f"{fmt_pf(s.get('y2025_pf'))} | "
            f"{fmt_p(s.get('y2025_wr'))} |")
    lines.append("")

    lines.append("## Diagnostic sensitivity")
    lines.append("")
    lines.append("| Variant | Mode | Total | Mean | PF | WR | "
                 "%cat | %ma | %reg |")
    lines.append("|---|---|--:|--:|--:|--:|--:|--:|--:|")
    for _, r in sens_df.iterrows():
        var, mode = r["variant"].split("__", 1)
        lines.append(
            f"| `{var}` | {mode} | "
            f"{fmt_d(r['all_sum'])} | "
            f"{fmt_d(r['all_mean'])} | "
            f"{fmt_pf(r['all_pf'])} | "
            f"{fmt_p(r['all_wr'])} | "
            f"{fmt_p(r['pct_cat'])} | "
            f"{fmt_p(r['pct_ma_protect'])} | "
            f"{fmt_p(r['pct_regime'])} |")
    lines.append("")

    lines.append("## Conclusion")
    lines.append("")
    if not surviving:
        lines.append("- **No variant beats BASELINE_regime on the "
                      "2-year span.** Confirms the H1 2025 result "
                      "extends to a larger sample. The cat stop "
                      "at flip-bar open + MA protection layer is "
                      "structurally non-viable on V_A regardless "
                      "of stall/MA tuning.")
    else:
        lines.append(f"- {len(surviving)} variant(s) beat baseline. "
                      "Recommend OOS expansion (2020-2023, 2026) "
                      "for robustness.")
    lines.append("")

    (OUT / "REPORT_2024_2025.md").write_text(
        "\n".join(lines), encoding="utf-8")
    print(f"  Report: {OUT / 'REPORT_2024_2025.md'}")


if __name__ == "__main__":
    sys.exit(main())
