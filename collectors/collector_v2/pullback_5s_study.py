"""1m hC Regime Quality + 5s Pullback Entry Framework.

Universe: qualified 1m regimes (hC >= 0.50 at bar 8, Healthy or HH-HardStall)
Pullback trigger: depth-only at 0.25 / 0.50 / 0.75 ATR from regime running peak.
Entry: first up-close after depth reached (close > open for long), enter NEXT 5s bar open.
hC filter: rolling — re-checked at each pullback trigger vs the current 1m bar's hC.
SL: close below pullback low (long) → exit next 5s bar open.
PT variants: +0.5 ATR, +1.0 ATR (intra-bar high/low touch; PT takes priority over SL).
Bar-mode NQ: $20/pt, $4.06 RT commission, 1 lot.

Main question: does high 1m hC materially improve 5s pullback entry economics?
"""
from __future__ import annotations
import sys, time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "backtests" / "studies" / "regime_dna_knn"))
sys.path.insert(0, str(ROOT))

import early_health_filter as E   # noqa: E402

KNN_DIR = ROOT / "backtests/studies/regime_dna_knn/results"
OUT     = ROOT / "collectors/collector_v2/results/combined_arch"

DEPTHS      = [0.25, 0.50, 0.75]
OOS         = [2025, 2026]
MULT        = 20.0   # NQ $20/pt
COMM        = 4.06   # per RT, 1 lot
HC_FLOOR    = 0.50   # minimum hC at bar-8 for universe
NS_PER_MIN  = 60 * 10 ** 9
NS_PER_5S   = 5  * 10 ** 9

# IS stall hC thresholds (from trend_quality_emergence.py)
IS_STALL_P33 = 0.044
IS_STALL_P67 = 0.304

# ─────────────────────────────────────────────────────────────────────────────
# 1.  Load per-bar hC mapping
# ─────────────────────────────────────────────────────────────────────────────
print("Loading hC mapping …")
hc_df = pd.read_parquet(OUT / "hc_perbar_mapping.parquet")
# dict: (regime_start_ts: int, bars_in_regime: int) → (hC: float, state: str)
hc_lookup: dict[tuple, tuple] = {
    (int(r.regime_start_ts), int(r.bars_in_regime)): (r.hC, r.state)
    for r in hc_df.itertuples(index=False)
}
print(f"  {len(hc_lookup):,} (regime_ts, bir) entries")

# ─────────────────────────────────────────────────────────────────────────────
# 2.  Capsule → qualified regime universe
# ─────────────────────────────────────────────────────────────────────────────
print("Loading capsule …")
cap = pd.read_parquet(KNN_DIR / "early_health_capsule.parquet")
df  = E.compute_labels_features(cap).reset_index(drop=True)


def _state_cat(hc_val: float, state_raw: str) -> str:
    if state_raw == "Healthy":
        return "Healthy"
    if state_raw == "DETER":
        return "DETER"
    if state_raw in ("HardStall", "SoftStall"):
        if hc_val >= IS_STALL_P67:
            return "HH-HardStall"
        if hc_val >= IS_STALL_P33:
            return "MH-HardStall"
        return "LH-HardStall"
    return "Other"


qualified: list[dict] = []
for row in df.itertuples(index=False):
    if int(row.year) not in OOS:
        continue
    rs_ts = int(row.regime_start_ts)
    # bars_in_regime=9 → k=8 → hC AFTER bar 8 closes
    entry = hc_lookup.get((rs_ts, 9))
    if entry is None:
        continue
    hc_val, state_raw = entry
    if np.isnan(hc_val) or hc_val < HC_FLOOR:
        continue
    sc = _state_cat(hc_val, state_raw)
    if sc not in ("Healthy", "HH-HardStall"):
        continue
    qualified.append({
        "regime_start_ts": rs_ts,
        "year":      int(row.year),
        "direction": float(row.direction),
        "atr_base":  float(row.atr_base),
        "n_post":    int(row.n_post),
        "hC_bar8":   hc_val,
        "state_bar8": sc,
    })

n_25 = sum(1 for r in qualified if r["year"] == 2025)
n_26 = sum(1 for r in qualified if r["year"] == 2026)
print(f"  Qualified regimes: {len(qualified):,}  (2025={n_25}, 2026={n_26})")

# ─────────────────────────────────────────────────────────────────────────────
# 3.  1s bar loader via NT catalog API (16s for 12M bars + 53s convert)
# ─────────────────────────────────────────────────────────────────────────────
def load_1s_bars(year: int) -> pd.DataFrame:
    """Load full-year 1s bars via NT ParquetDataCatalog and convert to DataFrame."""
    from nautilus_trader.persistence.catalog import ParquetDataCatalog
    cat = ParquetDataCatalog(str(ROOT / "data/catalog/NQ_v0_2020_2026"))
    start_ns = int(pd.Timestamp(f"{year}-01-01", tz="UTC").timestamp() * 1e9)
    end_ns   = int(pd.Timestamp(f"{year+1}-01-01", tz="UTC").timestamp() * 1e9)

    bars = cat.bars(bar_types=["NQ.XCME-1-SECOND-LAST-EXTERNAL"],
                    start=start_ns, end=end_ns)
    if not bars:
        return pd.DataFrame(columns=["ts_event", "open", "high", "low", "close"])

    n      = len(bars)
    ts_arr = np.empty(n, dtype=np.int64)
    o_arr  = np.empty(n, dtype=np.float64)
    h_arr  = np.empty(n, dtype=np.float64)
    l_arr  = np.empty(n, dtype=np.float64)
    c_arr  = np.empty(n, dtype=np.float64)
    for i, b in enumerate(bars):
        ts_arr[i] = b.ts_event
        o_arr[i]  = float(b.open)
        h_arr[i]  = float(b.high)
        l_arr[i]  = float(b.low)
        c_arr[i]  = float(b.close)

    return pd.DataFrame({
        "ts_event": ts_arr,
        "open":  o_arr,
        "high":  h_arr,
        "low":   l_arr,
        "close": c_arr,
    })


def resample_5s(df1: pd.DataFrame) -> pd.DataFrame:
    # Close-time labels: ts_event = window close = T+5s for window [T, T+5s).
    # 1s bar ts_event = open time (Databento convention, no ts_init_delta for 1s).
    # floor(ts/5s) groups [T,T+5s) bars together; +1 shifts label to close time.
    ts5 = (df1.ts_event // NS_PER_5S + 1) * NS_PER_5S
    g   = df1.groupby(ts5)
    return pd.DataFrame({
        "ts_event": g["ts_event"].first().index.values,
        "open":  g["open"].first().values,
        "high":  g["high"].max().values,
        "low":   g["low"].min().values,
        "close": g["close"].last().values,
    }).reset_index(drop=True)


# ─────────────────────────────────────────────────────────────────────────────
# 4.  Per-regime pullback scanner
# ─────────────────────────────────────────────────────────────────────────────
class _PbState:
    __slots__ = ("active", "entered", "awaiting_confirm",
                 "high_px", "low_px", "low_ts",
                 "trigger_ts", "trigger_hC", "trigger_state",
                 "trigger_bir", "n_lower_highs", "confirm_ts")

    def __init__(self):
        self.reset()

    def reset(self):
        self.active           = False
        self.entered          = False
        self.awaiting_confirm = False
        self.high_px          = np.nan
        self.low_px           = np.nan
        self.low_ts           = 0
        self.trigger_ts       = 0
        self.trigger_hC       = np.nan
        self.trigger_state    = ""
        self.trigger_bir      = 0
        self.n_lower_highs    = 0
        self.confirm_ts       = 0


def scan_regime(regime: dict, df5: pd.DataFrame) -> list[dict]:
    """Detect pullback entry events in one qualified regime."""
    rs_ts  = regime["regime_start_ts"]
    n_post = regime["n_post"]
    dsign  = regime["direction"]   # +1 long, -1 short
    atr    = regime["atr_base"]

    win_start   = rs_ts
    win_end     = rs_ts + n_post * NS_PER_MIN
    detect_from = rs_ts + 8 * NS_PER_MIN   # only look for pullbacks from bar 8+

    ts5 = df5.ts_event.values
    # With close-time labels, bar [win_end-5s, win_end) has ts_event=win_end → include it.
    mask = (ts5 >= win_start) & (ts5 <= win_end)
    if mask.sum() < 3:
        return []

    idx    = np.where(mask)[0]
    ts_arr = ts5[idx]
    o_arr  = df5.open.values[idx]
    h_arr  = df5.high.values[idx]
    c_arr  = df5.close.values[idx]

    run_ext = -np.inf if dsign == 1 else np.inf
    pb      = {d: _PbState() for d in DEPTHS}
    events: list[dict] = []
    prev_h  = np.nan

    for i in range(len(ts_arr)):
        ts = int(ts_arr[i])
        o  = float(o_arr[i])
        h  = float(h_arr[i])
        c  = float(c_arr[i])
        in_detect = ts >= detect_from

        # ── Causal hC: bars_in_regime of last CLOSED 1m bar ────────────
        # With close-time labels: ts = close of current 5s window.
        # At ts = rs_ts + k*60s (close of last bar of minute k-1), bar k-1
        # has just closed → bir_closed = k = bars_in_regime k.
        # bar_k_elapsed = k at ts=rs_ts+k*60s, so bir_closed = bar_k_elapsed (no +1).
        bar_k_elapsed = (ts - rs_ts) // NS_PER_MIN
        bir_closed    = int(bar_k_elapsed)
        hc_entry      = hc_lookup.get((rs_ts, bir_closed), (np.nan, ""))
        cur_hC, cur_raw = hc_entry
        cur_sc          = _state_cat(cur_hC, cur_raw)

        # ── Enter at open of this bar (previous bar was up-close) ────────
        if in_detect:
            for d in DEPTHS:
                s = pb[d]
                if s.awaiting_confirm and not s.entered:
                    s.entered = True
                    events.append({
                        "regime_start_ts":  rs_ts,
                        "year":             regime["year"],
                        "direction":        dsign,
                        "atr":              atr,
                        "depth_bucket":     d,
                        "hC_at_trigger":    s.trigger_hC,
                        "state_at_trigger": s.trigger_state,
                        "bir_at_trigger":   s.trigger_bir,
                        "hC_at_entry":      cur_hC,
                        "state_at_entry":   cur_sc,
                        "trigger_ts":       s.trigger_ts,
                        "confirm_ts":       s.confirm_ts,
                        "entry_ts":         ts,
                        "entry_px":         o,
                        "pullback_low_px":  s.low_px,
                        "pullback_high_px": s.high_px,
                        "n_lower_highs":    s.n_lower_highs,
                        "regime_end_ts":    win_end,
                    })

        # ── Running extreme and new-peak detection ───────────────────────
        if dsign == 1:
            new_peak = c > run_ext
            if new_peak:
                run_ext = c
            pb_depth = (run_ext - c) / atr
        else:
            new_peak = c < run_ext
            if new_peak:
                run_ext = c
            pb_depth = (c - run_ext) / atr

        # ── New peak: reset ALL pb states (entered trades already in events) ─
        if new_peak and in_detect:
            for d in DEPTHS:
                pb[d].reset()

        # ── Lower-high counter ───────────────────────────────────────────
        lh_delta = 1 if (not np.isnan(prev_h) and h < prev_h) else 0
        prev_h   = h

        # ── Trigger new pullback / deepen existing ───────────────────────
        if in_detect and not new_peak:
            for d in DEPTHS:
                s = pb[d]
                if pb_depth >= d and not s.active and not s.entered:
                    if np.isnan(cur_hC):
                        continue
                    s.active         = True
                    s.high_px        = run_ext
                    s.low_px         = c
                    s.low_ts         = ts
                    s.trigger_ts     = ts
                    s.trigger_hC     = cur_hC
                    s.trigger_state  = cur_sc
                    s.trigger_bir    = bir_closed
                    s.n_lower_highs  = lh_delta
                elif s.active and not s.entered:
                    if (dsign == 1 and c < s.low_px) or (dsign == -1 and c > s.low_px):
                        s.low_px = c
                        s.low_ts = ts
                    s.n_lower_highs += lh_delta

        # ── First up-close confirmation ─────────────────────────────────
        if in_detect:
            for d in DEPTHS:
                s = pb[d]
                if s.active and not s.awaiting_confirm and not s.entered:
                    if (dsign == 1 and c > o) or (dsign == -1 and c < o):
                        s.awaiting_confirm = True
                        s.confirm_ts       = ts

    return events


# ─────────────────────────────────────────────────────────────────────────────
# 5.  Outcome tracker (pass 2, full-year 5s array)
# ─────────────────────────────────────────────────────────────────────────────
def fill_outcomes(events: list[dict], df5: pd.DataFrame) -> None:
    """Fill outcome fields in-place for all events."""
    if not events:
        return

    ts_g = df5.ts_event.values.astype(np.int64)
    o_g  = df5.open.values
    h_g  = df5.high.values
    l_g  = df5.low.values
    c_g  = df5.close.values

    for ev in events:
        entry_ts = int(ev["entry_ts"])
        win_end  = int(ev["regime_end_ts"])
        entry_px = float(ev["entry_px"])
        dsign    = float(ev["direction"])
        atr      = float(ev["atr"])
        sl_px    = float(ev["pullback_low_px"])

        pt05 = entry_px + 0.5 * atr * dsign
        pt10 = entry_px + 1.0 * atr * dsign

        start_j = int(np.searchsorted(ts_g, entry_ts, side="left"))

        exit_px  = float(c_g[-1]) if len(c_g) > 0 else entry_px
        exit_ts  = int(ts_g[-1])  if len(ts_g) > 0 else entry_ts
        exit_rsn = "regime_flip"
        new_high = False; r05 = False; r10 = False; sb = False
        run_high = float(ev["pullback_high_px"])

        for j in range(start_j, len(ts_g)):
            ts = int(ts_g[j])
            # With close-time labels, ts=win_end is the last regime bar's close.
            # Exit at the first POST-regime bar (ts > win_end).
            if ts > win_end:
                exit_px  = float(o_g[j]) if j < len(o_g) else exit_px
                exit_ts  = ts
                exit_rsn = "regime_flip"
                break

            h = float(h_g[j])
            c = float(c_g[j])

            # New regime high
            if dsign == 1 and c > run_high:
                new_high = True;  run_high = c
            elif dsign == -1 and c < run_high:
                new_high = True;  run_high = c

            # PT intra-bar touch (long uses bar HIGH, short uses bar LOW)
            if dsign == 1:
                if not r05 and h >= pt05: r05 = True
                if not r10 and h >= pt10: r10 = True
            else:
                if not r05 and l_g[j] <= pt05: r05 = True
                if not r10 and l_g[j] <= pt10: r10 = True

            # SL: close below pullback low (long) / above (short)
            if (dsign == 1 and c < sl_px) or (dsign == -1 and c > sl_px):
                if r05:
                    # PT was already touched intra-bar before the close crossed SL
                    exit_px  = pt05
                    exit_ts  = ts
                    exit_rsn = "pt05"
                else:
                    sb       = True
                    nj       = j + 1
                    exit_px  = float(o_g[nj]) if nj < len(o_g) else c
                    exit_ts  = int(ts_g[nj])  if nj < len(ts_g) else ts
                    exit_rsn = "structure_break"
                break

        ev["exit_ts"]         = exit_ts
        ev["exit_px"]         = exit_px
        ev["exit_reason"]     = exit_rsn
        ev["new_high_after"]  = new_high
        ev["reached_05atr"]   = r05
        ev["reached_10atr"]   = r10
        ev["structure_break"] = sb

        # PnL
        hold_pnl = (exit_px - entry_px) * dsign * MULT - COMM

        if exit_rsn == "pt05" or (r05 and not sb):
            p05 = (pt05 - entry_px) * dsign * MULT - COMM
        else:
            p05 = hold_pnl

        if r10 and not sb and exit_rsn != "structure_break":
            p10 = (pt10 - entry_px) * dsign * MULT - COMM
        elif exit_rsn == "pt05" or (r05 and not sb):
            p10 = p05   # PT10 not reached; same as pt05 exit
        else:
            p10 = hold_pnl

        ev["pnl_hold"] = hold_pnl
        ev["pnl_pt05"] = p05
        ev["pnl_pt10"] = p10


# ─────────────────────────────────────────────────────────────────────────────
# 6.  Main loop
# ─────────────────────────────────────────────────────────────────────────────
all_events: list[dict] = []

for year in OOS:
    t0 = time.time()
    print(f"\n{year}: loading 1s bars …")
    df_1s = load_1s_bars(year)
    print(f"  {len(df_1s):,} 1s bars in {time.time()-t0:.0f}s")

    print(f"  Resampling to 5s …")
    df_5s = resample_5s(df_1s)
    print(f"  {len(df_5s):,} 5s bars")
    del df_1s

    year_regimes = [r for r in qualified if r["year"] == year]
    print(f"  Scanning {len(year_regimes):,} regimes …")

    year_events: list[dict] = []
    t_scan = time.time()
    for i, reg in enumerate(year_regimes):
        evs = scan_regime(reg, df_5s)
        year_events.extend(evs)
        if (i + 1) % 500 == 0:
            print(f"    {i+1}/{len(year_regimes)} | events={len(year_events):,}")

    print(f"  Scan done in {time.time()-t_scan:.0f}s → {len(year_events):,} events")
    print(f"  Computing outcomes …")
    fill_outcomes(year_events, df_5s)
    all_events.extend(year_events)

# ─────────────────────────────────────────────────────────────────────────────
# 7.  Build DataFrame + save
# ─────────────────────────────────────────────────────────────────────────────
print("\nBuilding DataFrame …")
ev_df = pd.DataFrame(all_events)
if ev_df.empty:
    print("No events found — check universe or data range.")
    sys.exit(0)

ev_df.to_parquet(OUT / "pullback_5s_events.parquet", index=False)
print(f"Saved {len(ev_df):,} events → pullback_5s_events.parquet")

# ─────────────────────────────────────────────────────────────────────────────
# 8.  Report
# ─────────────────────────────────────────────────────────────────────────────
R: list[str] = [
    "# 1m hC Regime Quality + 5s Pullback Entry Framework",
    "",
    f"Universe: regimes hC≥{HC_FLOOR} at bar 8, state=Healthy or HH-HardStall, "
    f"OOS 2025+2026.",
    "Trigger: 0.25/0.50/0.75×ATR depth-only from running peak.",
    "Entry: first up-close bar after depth → enter next 5s bar open.",
    "hC: rolling (re-checked at each trigger). SL: close below pullback low.",
    "PT: +0.5/+1.0 ATR intra-bar touch (PT priority over SL close).",
    f"Bar-mode: {MULT:.0f}$/pt, ${COMM:.2f} RT, 1 lot.",
    "",
    f"Total events: {len(ev_df):,}  "
    f"(2025={int((ev_df.year==2025).sum()):,}  "
    f"2026={int((ev_df.year==2026).sum()):,})",
    f"By depth: 0.25={int((ev_df.depth_bucket==0.25).sum()):,}  "
    f"0.50={int((ev_df.depth_bucket==0.50).sum()):,}  "
    f"0.75={int((ev_df.depth_bucket==0.75).sum()):,}",
    "",
]

# ── A. Baseline ──────────────────────────────────────────────────────────────
R += [
    "## A. Baseline: All Pullbacks (no additional hC filter)",
    "",
    "| Depth | n | new_high% | +0.5ATR% | pnl_pt05 | +1.0ATR% | pnl_pt10 | pnl_hold |",
    "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
]
for d in DEPTHS:
    g = ev_df[ev_df.depth_bucket == d]
    if len(g) == 0:
        continue
    R.append(
        f"| {d:.2f} | {len(g):,} | "
        f"{g.new_high_after.mean()*100:.0f}% | "
        f"{g.reached_05atr.mean()*100:.0f}% | ${g.pnl_pt05.mean():+.0f} | "
        f"{g.reached_10atr.mean()*100:.0f}% | ${g.pnl_pt10.mean():+.0f} | "
        f"${g.pnl_hold.mean():+.0f} |"
    )
R.append("")

# ── B. hC level at trigger ───────────────────────────────────────────────────
R += [
    "## B. Pullback Outcomes by hC at Trigger Time",
    "",
    "| hC range | Depth | n | new_high% | +0.5ATR% | pnl_hold |",
    "| --- | --- | ---: | ---: | ---: | ---: |",
]
for lo, hi, lbl in [(0.50, 0.65, "0.50–0.65"), (0.65, 0.80, "0.65–0.80"),
                    (0.80, 1.01, "0.80–1.00")]:
    for d in DEPTHS:
        g = ev_df[(ev_df.depth_bucket == d) &
                  (ev_df.hC_at_trigger >= lo) & (ev_df.hC_at_trigger < hi)]
        if len(g) < 10:
            continue
        R.append(
            f"| {lbl} | {d:.2f} | {len(g):,} | "
            f"{g.new_high_after.mean()*100:.0f}% | "
            f"{g.reached_05atr.mean()*100:.0f}% | "
            f"${g.pnl_hold.mean():+.0f} |"
        )
R.append("")

# ── C. State at trigger ──────────────────────────────────────────────────────
R += [
    "## C. Pullback Outcomes by State at Trigger Time",
    "",
    "| State | Depth | n | new_high% | +0.5ATR% | pnl_hold |",
    "| --- | --- | ---: | ---: | ---: | ---: |",
]
for st in ["Healthy", "HH-HardStall", "MH-HardStall", "LH-HardStall", "DETER", "Other"]:
    for d in DEPTHS:
        g = ev_df[(ev_df.depth_bucket == d) & (ev_df.state_at_trigger == st)]
        if len(g) < 10:
            continue
        R.append(
            f"| {st} | {d:.2f} | {len(g):,} | "
            f"{g.new_high_after.mean()*100:.0f}% | "
            f"{g.reached_05atr.mean()*100:.0f}% | "
            f"${g.pnl_hold.mean():+.0f} |"
        )
R.append("")

# ── D. Economic test by year ─────────────────────────────────────────────────
R += [
    "## D. Economic Test: hC Macro Filter (year-by-year)",
    "",
    "| Filter | Depth | 2025 n | 2025 $/tr | 2026 n | 2026 $/tr | both>0 |",
    "| --- | --- | ---: | ---: | ---: | ---: | :---: |",
]


def _row(label: str, mask: "pd.Series[bool]", d: float) -> str:
    g   = ev_df[mask & (ev_df.depth_bucket == d)]
    n25 = int((g.year == 2025).sum())
    m25 = g[g.year == 2025].pnl_hold.mean()
    n26 = int((g.year == 2026).sum())
    m26 = g[g.year == 2026].pnl_hold.mean()
    both = m25 > 0 and m26 > 0
    return (f"| {label} | {d:.2f} | {n25:,} | ${m25:+.0f} | "
            f"{n26:,} | ${m26:+.0f} | {'YES' if both else 'no'} |")


for d in DEPTHS:
    R.append(_row("ALL",          pd.Series(True,  index=ev_df.index),         d))
    R.append(_row("hC≥0.65",      ev_df.hC_at_trigger >= 0.65,                 d))
    R.append(_row("hC≥0.80",      ev_df.hC_at_trigger >= 0.80,                 d))
    R.append(_row("Healthy",      ev_df.state_at_trigger == "Healthy",          d))
    R.append(_row("HH-HardStall", ev_df.state_at_trigger == "HH-HardStall",     d))
    R.append("| | | | | | | |")

R.append("")

# ── E. Year breakdown ────────────────────────────────────────────────────────
R += [
    "## E. Year-by-Year Breakdown (all depths combined)",
    "",
    "| Year | n | new_high% | +0.5ATR% | pnl_hold | pnl_pt05 | pnl_pt10 | SB% |",
    "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
]
for y in OOS:
    g = ev_df[ev_df.year == y]
    R.append(
        f"| {y} | {len(g):,} | {g.new_high_after.mean()*100:.0f}% | "
        f"{g.reached_05atr.mean()*100:.0f}% | ${g.pnl_hold.mean():+.0f} | "
        f"${g.pnl_pt05.mean():+.0f} | ${g.pnl_pt10.mean():+.0f} | "
        f"{g.structure_break.mean()*100:.0f}% |"
    )
R.append("")

# ── F. Exit distribution ─────────────────────────────────────────────────────
R += ["## F. Exit Reason Distribution", ""]
for reason, cnt in ev_df.exit_reason.value_counts().items():
    R.append(f"- {reason}: {cnt:,} ({100*cnt/len(ev_df):.0f}%)")
R.append("")

# ── G. Conclusion ────────────────────────────────────────────────────────────
R += ["## G. Conclusion: Does hC improve 5s pullback economics?", ""]

m_all_25 = ev_df[ev_df.year == 2025].pnl_hold.mean()
m_all_26 = ev_df[ev_df.year == 2026].pnl_hold.mean()
hh_mask  = ev_df.hC_at_trigger >= 0.80
m_hh_25  = ev_df[hh_mask & (ev_df.year == 2025)].pnl_hold.mean()
m_hh_26  = ev_df[hh_mask & (ev_df.year == 2026)].pnl_hold.mean()
hh_pct   = float(hh_mask.mean() * 100)

improves  = (float(m_hh_25) > float(m_all_25)) and (float(m_hh_26) > float(m_all_26))
both_pos  = (float(m_hh_25) > 0)               and (float(m_hh_26) > 0)

if both_pos:
    verdict = ("YES — hC≥0.80 produces positive expectancy in BOTH 2025 and 2026. "
               "hC is a valid macro filter for 5s pullback entries. "
               "Candidate for NT BacktestEngine streaming validation before deployment.")
elif improves and not both_pos:
    verdict = ("PARTIAL — hC filter improves $/tr in both years but expectancy stays "
               "negative. The macro signal reduces losses; 5s pullback structure alone "
               "is insufficient.")
else:
    verdict = ("NO — high hC does not improve 5s pullback economics. "
               "1m regime quality does not translate to better 5s entry outcomes. "
               "The macro-to-micro execution hypothesis fails on this setup.")

R += [
    f"Baseline (all): 2025 ${m_all_25:+.0f}/tr | 2026 ${m_all_26:+.0f}/tr",
    f"hC≥0.80 ({hh_pct:.0f}% of events): 2025 ${m_hh_25:+.0f}/tr | 2026 ${m_hh_26:+.0f}/tr",
    f"Improves both years: {'YES' if improves else 'NO'}",
    f"Both positive: {'YES' if both_pos else 'NO'}",
    "",
    f"**VERDICT: {verdict}**",
    "",
    "Note: bar-mode simulation overstates vs tick-mode by ~$9-18/tr on "
    "pullback/mean-reversion setups (per project memory). "
    "A positive bar-mode result still requires NT streaming validation before "
    "any deployment claim.",
]

out_path = OUT / "pullback_5s_study.md"
out_path.write_text("\n".join(R), encoding="utf-8")
print(f"\nWrote {out_path}")
print("Done.")
