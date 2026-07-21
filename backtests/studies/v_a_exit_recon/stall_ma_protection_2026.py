"""V_A Stall-to-MA Protection — 2026 OOS test.

Runs the best H1-2025 variant `S5_SMA21` on 2026 RTH (Dec 2025 -
Apr 15 2026, 1,006 trades) to see whether it saves the brutal 2026
regime where baseline regime-exit was negative.

Also runs both baselines for direct comparison:
  - BASELINE_regime
  - BASELINE_cat_only

Outputs:
  studies/v_a_exit_recon/results/stall_ma_protection_2026/
    trades_<variant>.parquet
    grid_summary.parquet
    audit_summary.parquet
    REPORT_2026.md
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
    fmt_d, fmt_p, fmt_pf,
)
from utils.audit_replay_fills import audit_trades, AuditConfig

CT = pytz.timezone("America/Chicago")
PORT = Path("collectors/collector_v2/results/with_tape")
CATALOG_2026 = "./data/catalog/NQ_multi_year"
OUT = Path(
    "studies/v_a_exit_recon/results/stall_ma_protection_2026")
OUT.mkdir(parents=True, exist_ok=True)


def main():
    t_start = time.time()
    print("=" * 70)
    print("V_A Stall-to-MA Protection — 2026 OOS test (S5_SMA21)")
    print("=" * 70)

    # Load 2026 trades + tape (RTH only)
    print("\nLoading 2026 RTH trades + tape...")
    trades = pd.read_parquet(PORT / "NQ_2026/trades.parquet")
    tape = pd.read_parquet(PORT / "NQ_2026/trade_tape.parquet")
    rth = trades[trades["session"] == "RTH"].copy()
    rth["trade_id"] = rth["decision_event_id"]
    rth["baseline_net_pnl"] = rth["net_pnl"]
    ids = set(rth["decision_event_id"])
    tape_rth = tape[tape["decision_event_id"].isin(ids)].copy()
    tape_rth["trade_id"] = tape_rth["decision_event_id"]
    tape_rth = tape_rth.sort_values(
        ["trade_id", "ts_init"]).reset_index(drop=True)
    print(f"  trades: {len(rth):,}, tape rows: {len(tape_rth):,}")

    # Date range
    if len(rth):
        first = pd.Timestamp(int(rth["entry_ts"].min()),
                                  tz="UTC").tz_convert(CT)
        last = pd.Timestamp(int(rth["entry_ts"].max()),
                                 tz="UTC").tz_convert(CT)
        print(f"  date range: {first} to {last}")

    # Load 1m bars (Nov 2025 - Apr 2026)
    print("\nLoading 1m bars from catalog...")
    from nautilus_trader.persistence.catalog import (
        ParquetDataCatalog,
    )
    cat = ParquetDataCatalog(CATALOG_2026)
    start = pd.Timestamp("2025-11-01", tz="UTC")
    end = pd.Timestamp("2026-05-01", tz="UTC")
    bars = cat.bars(
        bar_types=["NQ.XCME-1-MINUTE-LAST-EXTERNAL"],
        start=start, end=end)
    rows = [(int(b.ts_init), float(b.open), float(b.high),
              float(b.low), float(b.close)) for b in bars]
    bars_1m = pd.DataFrame(rows, columns=[
        "ts_init", "open", "high", "low", "close"])
    bars_1m = bars_1m.sort_values("ts_init").reset_index(drop=True)
    print(f"  1m bars: {len(bars_1m):,}")

    print("\nComputing MAs...")
    ma_series = compute_mas(bars_1m)
    bars_1m_lookup = build_1m_lookup(bars_1m)
    bars_lookup_fn = build_bars_lookup_fn(
        bars_1m_lookup, tape_rth)

    summaries = []
    audits = []
    audit_failed = []

    # B1: regime-only
    print("\nRunning baselines + S5_SMA21...")
    b1_rows = []
    for _, t in rth.iterrows():
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
    print(f"  BASELINE_regime: total "
          f"{fmt_d(summaries[-1]['all_sum'])}, mean "
          f"{fmt_d(summaries[-1]['all_mean'])}, "
          f"WR {fmt_p(summaries[-1]['all_wr'])}")

    # B2: cat only
    cat_only_df = replay_variant(
        rth, tape_rth, bars_1m_lookup,
        ma_lookup={}, stall_bars=999, use_cat_stop=True)
    cat_only_df.to_parquet(
        OUT / "trades_BASELINE_cat_only.parquet", index=False)
    summaries.append(variant_summary(
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

    # S5_SMA21 (best H1 2025 variant)
    ma_lookup = ma_series[("SMA", 21)]
    s5_df = replay_variant(
        rth, tape_rth, bars_1m_lookup, ma_lookup,
        stall_bars=5,
        ohlc_convention="at_or_worse_close",
        invalid_stop_policy="market_exit_now",
        use_cat_stop=True)
    s5_df.to_parquet(
        OUT / "trades_S5_SMA21.parquet", index=False)
    summaries.append(variant_summary("S5_SMA21", s5_df))
    s = summaries[-1]
    print(f"  S5_SMA21: total {fmt_d(s['all_sum'])}, "
          f"mean {fmt_d(s['all_mean'])}, "
          f"cat={fmt_p(s['pct_cat'])} "
          f"ma={fmt_p(s['pct_ma_protect'])} "
          f"reg={fmt_p(s['pct_regime'])}, "
          f"vs base {fmt_d(s['all_vs_base_total'])}")

    ar = audit_trades(s5_df, bars_lookup_fn,
                            AuditConfig(
                                hard_fail_on_impossible=False))
    audits.append({"variant": "S5_SMA21",
                       "impossible": ar.impossible_fills_n,
                       "impossible_pnl": ar.impossible_fills_pnl})
    if ar.has_impossible_fills:
        audit_failed.append("S5_SMA21")

    # Save summaries
    summ_df = pd.DataFrame(summaries)
    summ_df.to_parquet(OUT / "grid_summary.parquet", index=False)
    audit_df = pd.DataFrame(audits)
    audit_df.to_parquet(OUT / "audit_summary.parquet",
                              index=False)

    # Markdown report
    print("\nWriting REPORT_2026.md...")
    base_regime = summaries[0]
    cat_only = summaries[1]
    s5 = summaries[2]
    base_total = base_regime["all_sum"]

    lines = []
    lines.append("# V_A Stall-to-MA Protection — 2026 OOS Test "
                  "(S5_SMA21)")
    lines.append("")
    lines.append(f"Run: {pd.Timestamp.now(tz='UTC').isoformat()}")
    lines.append("")
    lines.append("Tests the best H1-2025 variant (`S5_SMA21`) on "
                  "the 2026 regime where baseline regime-exit was "
                  "negative. Question: does the protective stop "
                  "save 2026?")
    lines.append("")
    lines.append("## Configuration")
    lines.append("")
    if len(rth):
        lines.append(f"- Span: NQ RTH {first.date()} to "
                      f"{last.date()}")
    lines.append(f"- Population: {base_regime['all_n']:,} V_A "
                  "trades")
    lines.append("- Cost: $10 RT")
    lines.append("- Framework: `utils/safe_replay`")
    lines.append("- Variant: `S5_SMA21` (stall_bars=5, MA=SMA(21), "
                  "1m granularity)")
    lines.append("- Mode: conservative_ohlc / at_or_worse_close / "
                  "market_exit_now")
    lines.append("")

    lines.append("## Audit verdict")
    lines.append("")
    if audit_failed:
        lines.append(f"- **FAIL** — {len(audit_failed)} variants "
                      "with impossible fills")
    else:
        lines.append("- **PASS** — 0 impossible fills")
    lines.append("")

    lines.append("## Headline")
    lines.append("")
    lines.append("| Variant | n | Total | vs Base | Mean | "
                 "Median | PF | WR | DD | %cat | %ma | %reg | "
                 "%inv@entry |")
    lines.append("|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|")
    for s in summaries:
        is_base = (s["variant"] == "BASELINE_regime")
        delta = ("(base)" if is_base
                  else f"{'+' if s['all_vs_base_total'] >= 0 else ''}"
                       f"{fmt_d(s['all_vs_base_total'])}")
        lines.append(
            f"| `{s['variant']}` | {s['all_n']:,} | "
            f"{fmt_d(s.get('all_sum'))} | {delta} | "
            f"{fmt_d(s.get('all_mean'))} | "
            f"{fmt_d(s.get('all_median'))} | "
            f"{fmt_pf(s.get('all_pf'))} | "
            f"{fmt_p(s.get('all_wr'))} | "
            f"{fmt_d(s.get('all_max_dd'))} | "
            f"{fmt_p(s.get('pct_cat', 0))} | "
            f"{fmt_p(s.get('pct_ma_protect', 0))} | "
            f"{fmt_p(s.get('pct_regime', 0))} | "
            f"{fmt_p(s.get('pct_cat_invalid_at_entry', 0))} |")
    lines.append("")

    lines.append("## Comparison vs H1 2025 result")
    lines.append("")
    lines.append("| Variant | H1 2025 total | 2026 total | "
                 "H1 2025 vs base | 2026 vs base |")
    lines.append("|---|--:|--:|--:|--:|")
    h1_2025 = {
        "BASELINE_regime": (53050, 0),
        "BASELINE_cat_only": (23385, -29665),
        "S5_SMA21": (16050, -37000),
    }
    for s in summaries:
        h1_total, h1_delta = h1_2025.get(s["variant"], (None, None))
        delta_str = (
            f"(base)" if s["variant"] == "BASELINE_regime"
            else (f"{'+' if s['all_vs_base_total'] >= 0 else ''}"
                   f"{fmt_d(s['all_vs_base_total'])}"))
        h1_delta_str = (
            f"(base)" if s["variant"] == "BASELINE_regime"
            else f"{'+' if h1_delta >= 0 else ''}{fmt_d(h1_delta)}"
                  if h1_delta is not None else "—")
        lines.append(
            f"| `{s['variant']}` | "
            f"{fmt_d(h1_total) if h1_total is not None else '—'} | "
            f"{fmt_d(s['all_sum'])} | "
            f"{h1_delta_str} | "
            f"{delta_str} |")
    lines.append("")

    lines.append("## Conclusion")
    lines.append("")
    s5_delta = s5["all_vs_base_total"]
    cat_delta = cat_only["all_vs_base_total"]
    if s5_delta > 0:
        lines.append(f"- **S5_SMA21 BEATS baseline regime exit on "
                      f"2026 by {fmt_d(s5_delta)}.** Despite "
                      "underperforming H1 2025, the rule "
                      f"specifically helps in the 2026 regime "
                      "where baseline is negative.")
        lines.append("- Recommend full IS/OOS expansion for "
                      "robustness validation.")
    else:
        lines.append(f"- **S5_SMA21 also UNDERPERFORMS baseline "
                      f"regime exit on 2026 by {fmt_d(s5_delta)}.** "
                      "The protective stop does not save the "
                      "negative-baseline regime — it makes 2026 "
                      "worse, not better.")
        lines.append(f"- Cat-only baseline: {fmt_d(cat_delta)} vs "
                      "regime baseline. The cat stop alone is "
                      f"{'profitable' if cat_only['all_sum'] > 0 else 'damaging'} on 2026.")
        lines.append("- The strategy class is dead across both H1 "
                      "2025 (positive baseline) and 2026 "
                      "(negative baseline) regimes. No further "
                      "expansion warranted.")
    lines.append("")

    (OUT / "REPORT_2026.md").write_text(
        "\n".join(lines), encoding="utf-8")
    print(f"  Report: {OUT / 'REPORT_2026.md'}")

    elapsed = (time.time() - t_start) / 60
    print(f"\nDone. {elapsed:.1f} min")
    return 0 if not audit_failed else 1


if __name__ == "__main__":
    sys.exit(main())
