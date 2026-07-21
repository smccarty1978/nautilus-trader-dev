"""Reconciliation diagnostic — NT manual-rule backtest vs collector
forward-path simulation, 2025 only.

Six sections, five log files + one final summary.

Goal: identify the source of the 3,153 (NT) vs ~2,253 (collector) trade
gap and the WR/Avg$ mismatch on the same intended rule.

NO new strategies, NO new ML — diagnostic only.
"""

import sys
import os
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd
import numpy as np

NT_PATH = ("backtests/results/flip_5m_nonaligned_bracket/"
           "trades_2025.parquet")
TRADES_PATH = ("studies/1m_delayed_checkpoint_context/results/"
               "trades_all.parquet")
OUT_DIR = Path("backtests/results/flip_5m_nonaligned_bracket/"
                "reconciliation")
OUT_DIR.mkdir(parents=True, exist_ok=True)

NQ_MULT = 20.0
COMMISSION = 5.0


def load_data():
    nt = pd.read_parquet(NT_PATH)
    # Filter NT to signals AT OR AFTER 2025-01-01 UTC
    cutoff = pd.Timestamp("2025-01-01", tz="UTC").value
    nt_2025 = nt[nt["signal_time"] >= cutoff].copy()

    trades = pd.read_parquet(TRADES_PATH)
    trades = trades.drop_duplicates(subset=["signal_ts"], keep="first")
    trades_2025 = trades[trades["year"] == 2025].copy()
    return nt_2025, trades_2025, trades


def fmt_pf(pf):
    if pd.isna(pf):
        return "n/a"
    if pf == float("inf"):
        return "inf"
    return f"{pf:.2f}"


def stats(df, pnl_col="pnl_dollars"):
    n = len(df)
    if n == 0:
        return {"n": 0}
    pnl = df[pnl_col]
    wr = (pnl > 0).mean() * 100
    avg = pnl.mean()
    total = pnl.sum()
    gp = pnl[pnl > 0].sum()
    gl = abs(pnl[pnl <= 0].sum())
    pf = gp / gl if gl > 0 else float("inf")
    return {"n": n, "wr%": wr, "avg$": avg, "total$": total, "pf": pf}


def sim_collector_bracket(df, pt_r=1.0, sl_r=1.0,
                            col="forward_pt100_before_sl100_T_000"):
    """Simulate the collector's bracket race outcome → $ PnL using
    per-trade ATR. Mirrors what tradeability_sanity.py did."""
    n = len(df)
    if n == 0:
        return pd.Series([], dtype=float)
    atr = df["atr_at_signal"].values
    bracket = df[col].values
    reg_pnl = df["forward_regime_pnl_dollars_T_000"].values
    pnl = np.full(n, np.nan)
    pt_first = bracket == 1
    sl_first = bracket == 0
    neither = pd.isna(bracket)
    pnl[pt_first] = (pt_r * atr[pt_first] * NQ_MULT) - COMMISSION
    pnl[sl_first] = (-sl_r * atr[sl_first] * NQ_MULT) - COMMISSION
    pnl[neither] = reg_pnl[neither]
    return pd.Series(pnl, index=df.index)


# ====================================================================
# SECTION 1 — Trade-count reconciliation
# ====================================================================

def section1_trade_count(nt, trades_2025, lines):
    lines.append("=" * 100)
    lines.append("SECTION 1 — TRADE-COUNT RECONCILIATION (2025)")
    lines.append("=" * 100)

    # Build the four collector-side populations
    base_2025 = trades_2025  # all confirmed signals 2025
    rth = trades_2025[trades_2025["is_rth"] == 1]
    rth_nonalign = rth[rth["regime_5m_aligned_T_000"] == 0]
    rth_nonalign_fill = rth_nonalign[
        rth_nonalign["fillable_at_T_000"] == 1]

    lines.append("\n--- Collector-side filter waterfall (2025) ---")
    lines.append(f"  Total confirmed signals:                "
                  f"{len(base_2025):>6,}")
    lines.append(f"  RTH:                                    "
                  f"{len(rth):>6,}")
    lines.append(f"  RTH + 5m_not_aligned_T_000:             "
                  f"{len(rth_nonalign):>6,}")
    lines.append(f"  RTH + 5m_not_aligned + fillable_T_000:  "
                  f"{len(rth_nonalign_fill):>6,}  <-- 'expected' for NT")

    lines.append(f"\n--- NT side (2025 only, post-warmup) ---")
    lines.append(f"  NT trades 2025:                         "
                  f"{len(nt):>6,}")

    # Match by signal_time (= signal_ts)
    nt_sig = set(nt["signal_time"].values)
    expected_sig = set(rth_nonalign_fill["signal_ts"].values)
    matched_sig = nt_sig & expected_sig
    nt_only = nt_sig - expected_sig
    col_only = expected_sig - nt_sig

    lines.append(f"\n--- Match summary ---")
    lines.append(f"  Matched (in both):       {len(matched_sig):>6,}")
    lines.append(f"  NT-only (overshoot):     {len(nt_only):>6,}")
    lines.append(f"  Collector-only (NT miss):{len(col_only):>6,}")

    # Where do NT-only trades come from? Check against various collector
    # filters
    nt_only_in_trades = trades_2025[
        trades_2025["signal_ts"].isin(nt_only)]
    nt_only_not_in_trades = nt_only - set(
        trades_2025["signal_ts"].values)

    lines.append(f"\n--- NT-only trades — root cause categorization ---")
    lines.append(
        f"  NT-only signals NOT in collector trades_all:  "
        f"{len(nt_only_not_in_trades):>5,}")
    lines.append(
        f"    (signals NT generated but collector didn't)")

    if len(nt_only_in_trades) > 0:
        # Categorize: what filter excludes them on collector side?
        n_eth = (nt_only_in_trades["is_rth"] == 0).sum()
        n_aligned = (nt_only_in_trades["regime_5m_aligned_T_000"] == 1).sum()
        n_not_fill = (nt_only_in_trades["fillable_at_T_000"] == 0).sum()
        lines.append(
            f"  NT-only signals IN collector but excluded by:")
        lines.append(
            f"    is_rth == 0 (ETH per collector):          "
            f"{n_eth:>5,}")
        lines.append(
            f"    regime_5m_aligned_T_000 == 1:             "
            f"{n_aligned:>5,}")
        lines.append(
            f"    fillable_at_T_000 == 0 (regime died):     "
            f"{n_not_fill:>5,}")

    # Sample NT-only trades — show why
    lines.append(f"\n--- 10 NT-only trade samples ---")
    sample_nt_only = nt[nt["signal_time"].isin(list(nt_only)[:10])]
    for _, row in sample_nt_only.head(10).iterrows():
        ts = row["signal_time"]
        in_col = ts in trades_2025["signal_ts"].values
        if in_col:
            crow = trades_2025[trades_2025["signal_ts"] == ts].iloc[0]
            cause = []
            if crow["is_rth"] == 0:
                cause.append("collector says ETH")
            if crow["regime_5m_aligned_T_000"] == 1:
                cause.append("collector says 5m aligned at T0")
            if crow["fillable_at_T_000"] == 0:
                cause.append("collector says not fillable at T0")
            cause_s = "; ".join(cause) if cause else "in collector pop?!"
        else:
            cause_s = "NOT IN collector trades_all"
        sig_dt = pd.Timestamp(ts, unit="ns", tz="UTC")
        lines.append(
            f"  {sig_dt}  dir={row['direction']:>+2}  "
            f"NT_pnl=${row['pnl_dollars']:>+7.1f}  cause: {cause_s}")

    # Sample col-only (NT missed)
    lines.append(f"\n--- 10 collector-only (NT miss) trade samples ---")
    col_only_rows = rth_nonalign_fill[
        rth_nonalign_fill["signal_ts"].isin(list(col_only)[:10])]
    for _, row in col_only_rows.head(10).iterrows():
        ts = row["signal_ts"]
        sig_dt = pd.Timestamp(ts, unit="ns", tz="UTC")
        lines.append(
            f"  {sig_dt}  dir={row['signal_direction']:>+2}  "
            f"collector_pt100_T0={row['forward_pt100_before_sl100_T_000']}  "
            f"trade_id={row['trade_id']}")

    return matched_sig, nt_only, col_only


# ====================================================================
# SECTION 2 — fillable_at_T_000 audit
# ====================================================================

def section2_fillable_audit(nt, trades_2025, lines):
    lines.append("=" * 100)
    lines.append("SECTION 2 — FILLABLE_AT_T_000 AUDIT")
    lines.append("=" * 100)

    rth_nonalign = trades_2025[
        (trades_2025["is_rth"] == 1)
        & (trades_2025["regime_5m_aligned_T_000"] == 0)
    ]

    with_fill = rth_nonalign[rth_nonalign["fillable_at_T_000"] == 1]
    without_fill = rth_nonalign[rth_nonalign["fillable_at_T_000"] == 0]

    lines.append("\n--- A. COUNT IMPACT ---")
    lines.append(f"  RTH + 5m_not_aligned_T_000 (no fillable filter): "
                  f"{len(rth_nonalign):>5,}")
    lines.append(f"    With fillable_at_T_000 == 1:                  "
                  f"{len(with_fill):>5,}  "
                  f"({len(with_fill)/len(rth_nonalign)*100:.1f}%)")
    lines.append(f"    With fillable_at_T_000 == 0:                  "
                  f"{len(without_fill):>5,}  "
                  f"({len(without_fill)/len(rth_nonalign)*100:.1f}%)")

    # Outcomes by fillable
    lines.append("\n--- B. WHY 'NOT FILLABLE' HAPPENS ---")
    lines.append(
        "  fillable_at_T_000 = 1 iff regime_exit_time > "
        "(signal_time + 30s)")
    lines.append(
        "  regime_exit_time gets set when, after the trade is registered,")
    lines.append(
        "  a subsequent 1m close has the regime indicator flip against")
    lines.append(
        "  the trade direction. The exit time is recorded as that bar's")
    lines.append(
        "  close time (rec.ts_event + 60s).")
    lines.append("")
    lines.append(
        "  For T_d=0 specifically (fill at signal+30s), 'not fillable'")
    lines.append(
        "  means the regime flipped against between signal_time and")
    lines.append(
        "  signal_time + 30s. The only way that can happen on the 30s")
    lines.append(
        "  grid is if regime_exit_time <= signal_time + 30s, i.e., the")
    lines.append(
        "  regime exit fires AT or BEFORE the next 30s boundary after")
    lines.append(
        "  signal close. Given regime_exit_time = bar.ts_event + 60s")
    lines.append(
        "  (a 1m boundary), and signal_time + 30s is mid-minute, the")
    lines.append(
        "  only valid case is regime_exit_time == signal_time exactly,")
    lines.append(
        "  meaning the regime exit was REGISTERED ON THE BAR+1 BAR")
    lines.append(
        "  ITSELF (bar+1.ts_event + 60s == signal_time → bar+1 was the")
    lines.append(
        "  bar that flipped the regime against the trade direction).")

    lines.append(
        "\n  Sample non-fillable trades (15):")
    sample = without_fill.head(15)
    for _, r in sample.iterrows():
        sig_dt = pd.Timestamp(r["signal_ts"], unit="ns", tz="UTC")
        ret_dt = (
            pd.Timestamp(r["regime_exit_time"], unit="ns", tz="UTC")
            if pd.notna(r["regime_exit_time"]) else None)
        delta_s = ((r["regime_exit_time"] - r["signal_ts"]) / 1e9
                   if pd.notna(r["regime_exit_time"]) else None)
        lines.append(
            f"    signal={sig_dt}  dir={r['signal_direction']:>+2}  "
            f"flip→sig dur={int(r['prior_regime_duration_bars'])} bars  "
            f"regime_exit={ret_dt}  exit_minus_sig={delta_s}s")

    # C. Compare outcomes
    lines.append("\n--- C. COMPARE OUTCOMES (collector bracket sim) ---")
    lines.append(
        "  PT=1.0/SL=1.0 dollar simulation using collector bracket race:")
    lines.append("")
    for label, sub in [
        ("WITH fillable_at_T_000 == 1", with_fill),
        ("WITHOUT (== 0 only)", without_fill),
        ("BOTH (no fillable filter)", rth_nonalign),
    ]:
        if len(sub) == 0:
            lines.append(f"    {label:<32} (empty)")
            continue
        pnl = sim_collector_bracket(sub)
        s = stats(sub.assign(pnl_dollars=pnl))
        # PT/SL/regime breakdown
        bracket = sub["forward_pt100_before_sl100_T_000"].values
        pt_n = (bracket == 1).sum()
        sl_n = (bracket == 0).sum()
        nth_n = pd.isna(bracket).sum()
        lines.append(
            f"    {label:<32} N={s['n']:>5,}  "
            f"WR={s['wr%']:>5.1f}%  Avg=${s['avg$']:>+7.1f}  "
            f"PF={fmt_pf(s['pf']):>5}  "
            f"PT={pt_n/s['n']*100:>5.1f}%  "
            f"SL={sl_n/s['n']*100:>5.1f}%  "
            f"reg={nth_n/s['n']*100:>5.1f}%")

    lines.append("")
    lines.append(
        "  KEY QUESTION: is fillable_at_T_000 a real trading constraint")
    lines.append("                or a collector survivor-filter?")
    lines.append("")
    lines.append(
        "  In live trading: the order is submitted at signal time. The")
    lines.append(
        "  fill happens 30s later (per design). If the 1m regime flip")
    lines.append(
        "  bar+2 (closing at signal+60s) had the regime flip, the trade")
    lines.append(
        "  would still HAVE FILLED at signal+30s (before the bar+2 close)")
    lines.append(
        "  and then BE STOPPED OUT on the regime flip exit at signal+60s.")
    lines.append(
        "  So in practice, 'not fillable' trades in the collector still")
    lines.append(
        "  enter and exit normally in NT — they don't disappear, they")
    lines.append(
        "  just become regime-flip exits. fillable_at_T_000 is therefore")
    lines.append(
        "  a SURVIVOR FILTER on the collector side (excludes trades that")
    lines.append(
        "  the collector decided would have died — but they don't really).")


# ====================================================================
# SECTION 3 — Bracket resolution mismatch
# ====================================================================

def section3_bracket_mismatch(nt, trades_2025, matched_sig, lines):
    lines.append("=" * 100)
    lines.append("SECTION 3 — BRACKET RESOLUTION MISMATCH (matched only)")
    lines.append("=" * 100)

    # Build matched DataFrame
    nt_m = nt[nt["signal_time"].isin(matched_sig)].copy()
    col_m = trades_2025[
        trades_2025["signal_ts"].isin(matched_sig)
    ][[
        "signal_ts", "forward_pt100_before_sl100_T_000",
        "forward_regime_pnl_dollars_T_000",
        "forward_peak_mfe_atr_T_000",
        "forward_peak_mae_atr_T_000",
        "atr_at_signal", "signal_direction",
    ]].copy()

    # Merge
    merged = nt_m.merge(col_m, left_on="signal_time",
                          right_on="signal_ts", suffixes=("_nt", "_col"))
    lines.append(f"\n  Matched pairs: {len(merged):,}")

    # Map outcomes
    def col_outcome(b):
        if pd.isna(b):
            return "neither"
        return "PT" if b == 1 else "SL"

    def nt_outcome(r):
        if r == "pt":
            return "PT"
        elif r.startswith("sl"):
            return "SL"
        elif r == "regime_flip":
            return "regime"
        return "other"

    merged["col_out"] = merged[
        "forward_pt100_before_sl100_T_000"].apply(col_outcome)
    merged["nt_out"] = merged["exit_reason"].apply(nt_outcome)

    # Confusion matrix
    cm = pd.crosstab(merged["col_out"], merged["nt_out"], margins=True)
    lines.append("\n--- Confusion matrix (collector × NT outcomes) ---")
    lines.append(f"  rows: collector | cols: NT")
    lines.append("")
    lines.append(cm.to_string())

    # Pct
    lines.append("\n  Same outcome (PT==PT, SL==SL):")
    same_pt = ((merged["col_out"] == "PT") & (merged["nt_out"] == "PT")).sum()
    same_sl = ((merged["col_out"] == "SL") & (merged["nt_out"] == "SL")).sum()
    lines.append(f"    PT==PT:  {same_pt:>5,}")
    lines.append(f"    SL==SL:  {same_sl:>5,}")
    lines.append(f"    agreement rate (PT/SL only): "
                  f"{(same_pt+same_sl)/len(merged)*100:.1f}%")

    # Disagreement focus: collector PT but NT not PT
    col_pt = merged[merged["col_out"] == "PT"]
    n_col_pt = len(col_pt)
    if n_col_pt > 0:
        nt_dist = col_pt["nt_out"].value_counts()
        lines.append(f"\n  Of {n_col_pt:,} collector PT trades, NT says:")
        for o, c in nt_dist.items():
            lines.append(
                f"    {o:<10} {c:>5,}  ({c/n_col_pt*100:>5.1f}%)")

    col_sl = merged[merged["col_out"] == "SL"]
    n_col_sl = len(col_sl)
    if n_col_sl > 0:
        nt_dist = col_sl["nt_out"].value_counts()
        lines.append(f"\n  Of {n_col_sl:,} collector SL trades, NT says:")
        for o, c in nt_dist.items():
            lines.append(
                f"    {o:<10} {c:>5,}  ({c/n_col_sl*100:>5.1f}%)")

    col_neither = merged[merged["col_out"] == "neither"]
    n_col_n = len(col_neither)
    if n_col_n > 0:
        nt_dist = col_neither["nt_out"].value_counts()
        lines.append(f"\n  Of {n_col_n:,} collector NEITHER trades, NT says:")
        for o, c in nt_dist.items():
            lines.append(
                f"    {o:<10} {c:>5,}  ({c/n_col_n*100:>5.1f}%)")

    # Sample disagreements: collector PT but NT SL/regime
    disagree_pt_to_other = merged[
        (merged["col_out"] == "PT") & (merged["nt_out"] != "PT")]
    lines.append(
        f"\n--- 10 sample disagreements: collector says PT, NT doesn't ---")
    for _, r in disagree_pt_to_other.head(10).iterrows():
        sig_dt = pd.Timestamp(r["signal_time"], unit="ns", tz="UTC")
        lines.append(
            f"  {sig_dt}  dir={r['direction']:>+2}  "
            f"col_mfe={r['forward_peak_mfe_atr_T_000']:.2f}  "
            f"col_mae={r['forward_peak_mae_atr_T_000']:.2f}  "
            f"NT_exit={r['exit_reason']}  "
            f"NT_pnl=${r['pnl_dollars']:>+7.1f}  "
            f"NT_pnl_pts={r['pnl_pts']:.2f}  "
            f"atr={r['atr_at_signal_nt']:.2f}")

    # Sample agreements
    agree_pt = merged[
        (merged["col_out"] == "PT") & (merged["nt_out"] == "PT")]
    lines.append(
        f"\n--- 5 sample agreements: collector PT, NT PT ---")
    for _, r in agree_pt.head(5).iterrows():
        sig_dt = pd.Timestamp(r["signal_time"], unit="ns", tz="UTC")
        lines.append(
            f"  {sig_dt}  dir={r['direction']:>+2}  "
            f"col_mfe={r['forward_peak_mfe_atr_T_000']:.2f}  "
            f"NT_pnl=${r['pnl_dollars']:>+7.1f}  "
            f"NT_pnl_pts={r['pnl_pts']:.2f}  "
            f"atr={r['atr_at_signal_nt']:.2f}")

    return merged


# ====================================================================
# SECTION 4 — Population definition audit
# ====================================================================

def section4_definition_audit(lines):
    lines.append("=" * 100)
    lines.append("SECTION 4 — RULE DEFINITION AUDIT")
    lines.append("=" * 100)

    rows = [
        ("RTH session at signal_time",
         "is_rth flag: 1 if 510 <= ct_min < 900, set at signal_time",
         "Same: RTH check uses 510 <= ct_min < 900 in CT timezone, "
         "evaluated at signal_time",
         "SAME"),
        ("1m regime flip detection",
         "RegimeState.update on each 1m bar; sticky regime; "
         "flip = prev_regime_1m != new AND both nonzero AND prev != new",
         "Same RegimeState class copied verbatim from collector",
         "SAME"),
        ("Bar+1 HH/LL confirmation",
         "Long: bar1.h > flip_bar.h. Short: bar1.l < flip_bar.l. "
         "Strict inequality.",
         "Same: bar1.h > flip_bar.h (long) / bar1.l < flip_bar.l (short)",
         "SAME"),
        ("5m regime aggregation",
         "Aggregate 5 1m bars when minute_of_hour % 5 == 4. "
         "Update RegimeState on aggregated H/L/C.",
         "Same logic copied from collector",
         "SAME"),
        ("5m alignment check at signal time",
         "T_000 snap fires at current_ts=signal_time from 1s/30s "
         "boundary, BEFORE bar+1's _on_1m updates regime_5m. So "
         "regime_5m_aligned_T_000 reflects PRE-bar+1 state.",
         "prev_regime_5m captured at TOP of bar+1's _on_1m, BEFORE "
         "_update_5m for bar+1 fires. Same semantic.",
         "SAME (intended)"),
        ("Entry timestamp / fill price",
         "fill_price = open of 1s bar with ts_event = signal_time + 30s",
         "Order submitted during processing of 1s bar at "
         "ts_event=signal+29s (ts_init=signal+30s); fills at NEXT 1s "
         "bar's open, which is ts_event=signal+30s. Same price target.",
         "SAME"),
        ("Bracket activation timing",
         "ForwardPathTracker starts tracking at fill_ts = signal+30s. "
         "Updates on each 1s bar ts >= fill_ts.",
         "_check_brackets fires on each 1s bar while IN_TRADE, "
         "starting from the fill bar (ts = signal+30s).",
         "SAME"),
        ("Bracket hit detection (PT/SL)",
         "Uses cumulative peak: pt_hit = peak_mfe >= pt_atr. Resolves "
         "first-hit on the 1s bar where cumulative peak crosses.",
         "Uses CURRENT bar high/low: hit_pt = high >= pt_px. Different "
         "mechanism: peak-based vs current-bar-cross.",
         "DIFFERENT (mechanism)"),
        ("Same-bar both-hit resolution",
         "If pt_hit AND sl_hit on same bar update: ratio decision "
         "(cur_mfe/pt_atr vs cur_mae/sl_atr) — slight PT bias when "
         "MFE growth dominates.",
         "Pessimistic SL-first when both flags trigger same 1s bar.",
         "DIFFERENT (resolution rule)"),
        ("Regime-flip exit timing",
         "regime_exit_time set in _update_active_trades_on_1m AT 1m "
         "close that has regime against. forward_path stops updating "
         "after finalize. forward_regime_pnl_dollars uses regime_exit_price "
         "= bar.close.",
         "On _on_1m flip-against-direction: submit market close. NT "
         "fills close at NEXT 1s bar OPEN (= price right after the 1m "
         "close). Slightly different fill price than collector's bar.close.",
         "DIFFERENT (fill price for regime exit)"),
        ("'fillable_at_T_000' semantic",
         "fillable=1 iff regime_exit_time > signal_time+30s. Excludes "
         "trades whose regime flipped AT signal_time itself.",
         "Trades enter as long as regime is alive at order submission. "
         "If regime flips later (post-fill), trade is closed by regime "
         "exit instead of being excluded.",
         "DIFFERENT (filter vs exit)"),
        ("One-entry-per-event",
         "Each confirmed signal becomes one trade record.",
         "State machine enforces FLAT→AWAITING→PENDING_FILL→IN_TRADE→"
         "FLAT cycle. New flips during AWAITING overwrite pending. "
         "New flips during PENDING_FILL or IN_TRADE may abort pending "
         "or close trade (per direction).",
         "MOSTLY SAME, edge cases differ"),
    ]
    lines.append("")
    lines.append(
        f"  {'Rule component':<38} | {'Same/Diff':<22} | Notes")
    lines.append("  " + "-" * 100)
    for name, col_def, nt_def, status in rows:
        lines.append(f"  {name:<38} | {status:<22} |")
        lines.append(f"      collector: {col_def}")
        lines.append(f"      NT       : {nt_def}")
        lines.append("")


# ====================================================================
# SECTION 5 — Apples-to-apples (matched population only)
# ====================================================================

def section5_apples_to_apples(nt, trades_2025, matched_sig, lines):
    lines.append("=" * 100)
    lines.append("SECTION 5 — APPLES-TO-APPLES (matched population only)")
    lines.append("=" * 100)

    nt_m = nt[nt["signal_time"].isin(matched_sig)].copy()
    col_m = trades_2025[trades_2025["signal_ts"].isin(matched_sig)].copy()

    # Compute collector bracket sim PnL
    col_m["pnl_dollars"] = sim_collector_bracket(col_m)

    # Map exit reasons for collector (from bracket field)
    col_m["exit_reason"] = col_m[
        "forward_pt100_before_sl100_T_000"].apply(
        lambda b: "pt" if b == 1 else ("sl" if b == 0 else "regime")
    )

    lines.append(f"\n  Matched population N: {len(nt_m):,}")
    lines.append(f"  (NT: {len(nt_m)}; collector: {len(col_m)})")

    s_col = stats(col_m)
    s_nt = stats(nt_m)

    lines.append("\n--- Headline ---")
    lines.append(
        f"  {'Metric':<14} {'Collector sim':>15} {'NT backtest':>15} "
        f"{'Δ':>10}")
    lines.append(
        f"  {'-'*14} {'-'*15} {'-'*15} {'-'*10}")
    lines.append(
        f"  {'N':<14} {s_col['n']:>15,} {s_nt['n']:>15,} "
        f"{s_nt['n']-s_col['n']:>+10}")
    lines.append(
        f"  {'WR%':<14} {s_col['wr%']:>14.1f}% {s_nt['wr%']:>14.1f}% "
        f"{s_nt['wr%']-s_col['wr%']:>+9.1f}pp")
    lines.append(
        f"  {'Avg$':<14} ${s_col['avg$']:>+13.1f} "
        f"${s_nt['avg$']:>+13.1f} ${s_nt['avg$']-s_col['avg$']:>+8.1f}")
    lines.append(
        f"  {'PF':<14} {fmt_pf(s_col['pf']):>15} "
        f"{fmt_pf(s_nt['pf']):>15} "
        f"{s_nt['pf']-s_col['pf']:>+10.2f}")
    lines.append(
        f"  {'Total$':<14} ${s_col['total$']:>+13,.0f} "
        f"${s_nt['total$']:>+13,.0f} "
        f"${s_nt['total$']-s_col['total$']:>+8,.0f}")

    # Exit breakdown
    lines.append("\n--- Exit breakdown ---")
    lines.append(
        f"  {'reason':<10} {'col N':>6} {'col %':>6} "
        f"{'NT N':>6} {'NT %':>6}")
    nt_reason_map = nt_m["exit_reason"].apply(
        lambda r: "pt" if r == "pt"
        else ("sl" if r.startswith("sl") else "regime"))
    n = len(nt_m)
    for label in ["pt", "sl", "regime"]:
        cn = (col_m["exit_reason"] == label).sum()
        nn = (nt_reason_map == label).sum()
        lines.append(
            f"  {label:<10} {cn:>6,} {cn/n*100:>5.1f}% "
            f"{nn:>6,} {nn/n*100:>5.1f}%")


# ====================================================================
# SECTION 6 — Final conclusions
# ====================================================================

def section6_conclusions(nt, trades_2025, matched_sig, lines):
    lines.append("=" * 100)
    lines.append("SECTION 6 — FINAL CONCLUSIONS")
    lines.append("=" * 100)

    rth_nonalign = trades_2025[
        (trades_2025["is_rth"] == 1)
        & (trades_2025["regime_5m_aligned_T_000"] == 0)
    ]
    rth_nonalign_fill = rth_nonalign[
        rth_nonalign["fillable_at_T_000"] == 1]

    nt_only = set(nt["signal_time"].values) - set(
        rth_nonalign_fill["signal_ts"].values)
    nt_only_in_collector = trades_2025[
        trades_2025["signal_ts"].isin(nt_only)]

    n_nt = len(nt)
    n_col = len(rth_nonalign_fill)
    n_overshoot = n_nt - n_col

    n_unfillable_explained = (
        nt_only_in_collector["fillable_at_T_000"] == 0).sum()
    n_aligned_explained = (
        nt_only_in_collector["regime_5m_aligned_T_000"] == 1).sum()
    n_eth_explained = (nt_only_in_collector["is_rth"] == 0).sum()
    n_not_in_collector = len(nt_only) - len(nt_only_in_collector)

    lines.append("\n--- Q1: What caused the +900 trade NT overshoot? ---")
    lines.append(
        f"  NT 2025 trades:                 {n_nt:>5,}")
    lines.append(
        f"  Collector matched-rule trades:  {n_col:>5,}")
    lines.append(
        f"  Overshoot:                      {n_overshoot:>5,}  "
        f"({n_overshoot/n_col*100:.1f}% over)")
    lines.append("")
    lines.append(
        f"  Of the {len(nt_only):,} NT-only signals (overshoot),")
    lines.append(
        f"    Excluded by fillable=0:        {n_unfillable_explained:>5,}  "
        f"({n_unfillable_explained/len(nt_only)*100:>4.1f}%)")
    lines.append(
        f"    Excluded by 5m_aligned=1:      {n_aligned_explained:>5,}  "
        f"({n_aligned_explained/len(nt_only)*100:>4.1f}%)")
    lines.append(
        f"    Excluded by ETH:               {n_eth_explained:>5,}  "
        f"({n_eth_explained/len(nt_only)*100:>4.1f}%)")
    lines.append(
        f"    Not in collector trades_all:   {n_not_in_collector:>5,}  "
        f"({n_not_in_collector/len(nt_only)*100:>4.1f}%)")
    pct_explained_by_fillable = (
        n_unfillable_explained / len(nt_only) * 100
        if len(nt_only) > 0 else 0)
    lines.append("")
    lines.append(
        f"  ANSWER: ~{pct_explained_by_fillable:.0f}% of overshoot is "
        f"due to the 'fillable_at_T_000=0' filter.")
    lines.append(
        f"  These are real trades NT enters (regime is alive at fill")
    lines.append(
        f"  time) but the collector marks unfillable because regime")
    lines.append(
        f"  exit fires shortly after. They become regime-flip exits")
    lines.append(
        f"  in NT, not no-entry events.")

    lines.append(
        "\n--- Q2: Is fillable_at_T_000 a real constraint or "
        "a survivor filter? ---")
    lines.append(
        "  ANSWER: Survivor filter on the collector side.")
    lines.append(
        "  In live trading, an order submitted at signal time WILL fill")
    lines.append(
        "  ~30s later regardless of what the regime indicator does on")
    lines.append(
        "  the bar+2 close. The 'unfillable' trades just become")
    lines.append(
        "  immediate regime-flip losers in NT.")
    lines.append(
        "  The collector's fillable=1 filter implicitly excludes the")
    lines.append(
        "  worst trades (those that die fastest), inflating apparent edge.")

    lines.append(
        "\n--- Q3: Does the collector bracket race overstate PT wins? ---")
    lines.append(
        "  See Section 3 confusion matrix and Section 5 apples-to-apples.")
    lines.append(
        "  After matching populations, compare PT% in collector vs NT")
    lines.append(
        "  on the same set of trades.")

    lines.append("\n--- Q4: Any credible edge left in the simple manual rule? ---")
    lines.append(
        "  See Section 5 apples-to-apples summary.")
    lines.append(
        "  If matched-population WR/Avg$/PF in NT is still positive and")
    lines.append(
        "  meaningfully above zero, there's a real but smaller edge.")
    lines.append(
        "  If it collapses to ~zero, the edge was an artifact of the")
    lines.append(
        "  collector's idealizations.")


# ====================================================================
# Main runner
# ====================================================================

def main():
    print("Loading NT trades + collector trades_all...")
    nt, trades_2025, _trades_all = load_data()
    print(f"  NT 2025-only:        {len(nt):,}")
    print(f"  trades_all 2025:     {len(trades_2025):,}")

    # Section 1
    print("\nSection 1...")
    s1 = []
    matched_sig, nt_only, col_only = section1_trade_count(
        nt, trades_2025, s1)
    out1 = OUT_DIR / "1_trade_count_reconciliation.log"
    out1.write_text("\n".join(s1), encoding="utf-8")
    print(f"  Saved: {out1}")

    # Section 2
    print("Section 2...")
    s2 = []
    section2_fillable_audit(nt, trades_2025, s2)
    out2 = OUT_DIR / "2_fillable_audit.log"
    out2.write_text("\n".join(s2), encoding="utf-8")
    print(f"  Saved: {out2}")

    # Section 3
    print("Section 3...")
    s3 = []
    section3_bracket_mismatch(nt, trades_2025, matched_sig, s3)
    out3 = OUT_DIR / "3_bracket_mismatch.log"
    out3.write_text("\n".join(s3), encoding="utf-8")
    print(f"  Saved: {out3}")

    # Section 4
    print("Section 4...")
    s4 = []
    section4_definition_audit(s4)
    out4 = OUT_DIR / "4_definition_audit.log"
    out4.write_text("\n".join(s4), encoding="utf-8")
    print(f"  Saved: {out4}")

    # Section 5
    print("Section 5...")
    s5 = []
    section5_apples_to_apples(nt, trades_2025, matched_sig, s5)
    out5 = OUT_DIR / "5_apples_to_apples.log"
    out5.write_text("\n".join(s5), encoding="utf-8")
    print(f"  Saved: {out5}")

    # Section 6
    print("Section 6...")
    s6 = []
    section6_conclusions(nt, trades_2025, matched_sig, s6)
    out6 = OUT_DIR / "6_final_conclusions.log"
    out6.write_text("\n".join(s6), encoding="utf-8")
    print(f"  Saved: {out6}")

    # Print combined summary
    print("\n" + "=" * 100)
    print("RECONCILIATION COMPLETE")
    print("=" * 100)
    for f in [out1, out2, out3, out4, out5, out6]:
        print(f"  {f}")


if __name__ == "__main__":
    main()
