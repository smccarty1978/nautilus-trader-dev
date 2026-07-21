# Regime Flip Truth Collector v1

## Objective

Stop optimizing exits/filters/HMM variants. Build a clean, high-quality
**event dataset** that answers:

- Which 1m regime flips become clean, persistent trends?
- Which become fakeouts?
- Can we identify the difference **early enough to matter**?

This is **truth collection**, not a strategy. No orders, no backtest PnL, no
optimization, no ML.

## Scope

- Instrument: NQ continuous futures (`NQ.v.0`), catalog `NQ_v0_2020_2026`
  (safe `closed='left'` 1m build).
- Ground truth: **1-second bars**. No tick / order-book data. No synthetic
  microstructure — all volume/velocity metrics derive only from 1s OHLCV.
- Period: **2021-01-01 → 2024-12-31** (per-year runs, 3-day lead-in for warmup,
  pre-year events dropped).
- Session: **24h Globex**, each event tagged `rth_flag` (08:30–15:00 CT).

## Regime definition (reused, unchanged)

Sticky EMA3/9-on-High/Low regime, computed per timeframe by the vetted
`collectors/collector_v2` causal stack (`aggregator → regime_engine →
registry`). Long if `close > EMA3_high AND close > EMA9_high`; short if
`close < EMA3_low AND close < EMA9_low`; else carry forward. ATR = Wilder(14).

The registry enforces the hard invariant `close_ts <= decision_ts` for every
timeframe on every snapshot (`audit_provenance`). This is the look-ahead
air-gap. The aggregator is extended additively to a **5s** bucket; the
`collector_v2` default (`30s/1m/3m/5m`) is provably untouched (it constructs
`CompletedBarRegistry()` with no args).

## Event populations

- **A — raw flips**: "entry" at the flip 1m bar's CLOSE.
- **B — bar1-confirmed**: after a flip, the next 1m bar (bar1) must make a HH
  (long) / LL (short) AND close in-direction (`close>open` / `close<open`);
  "entry" at bar1's CLOSE. (Exact prior-study definition.)

Each regime yields one A event and, if confirmed, one B event. `bar1_confirmed`
is back-linked onto the A event for cross-reference.

## Horizon (path study, not execution)

Track each event on 1s bars from entry to the **next opposite 1m regime flip**.
Terminal price = the opposite-flip bar's close. Regime is sticky and strictly
alternates, so "next opposite flip" = next flip.

## Outcomes & labels (1s precision)

- `mfe_atr`, `mae_atr`, `terminal_pnl_atr` (and `_pts`), `regime_duration_s/bars`.
- Milestones: `reached_{0.5,1,2,3}_atr`; `mae_before_{0.5,1,2}_atr` (MAE at the
  moment MFE first crossed the level).
- Clean Trend A: MFE≥2 ATR & MAE≤0.75 ATR. Clean Trend B: MFE≥3 & MAE≤1.
  Persistent: duration≥15 bars. Elite: persistent & MFE≥2 & MAE≤0.75.

## Entry features (all causal, ATR-normalized where signed)

MTF regime+alignment (5s/30s/1m/5m); EMA & SMA 9/13/21/50 distance+slope (1m
closes); Bollinger(20,2); Keltner(20,20,1.5); ATR + ATR percentile; realized
vol (5m/30m/recent); volume 1m/5m/30m + percentile + acceleration; returns
30s/60s/120s/300s + velocity/accel; VWAP distance/z; prior-regime
duration/MFE/MAE; flip density (30m/60m) + time-since-flip.

## Early-evolution checkpoints (`flip_checkpoint_dataset`)

One row per event per checkpoint: entry, +30/60/90/120/180s, Bar2/3/5. Each
records only info known then: `cur_mfe/mae/pnl_atr`, `stall_s`, `hh/ll_count`,
`dist_from_vwap_atr`, `dist_from_ema13_atr`, `path_efficiency`. Checkpoints past
the terminal flip are emitted with `reached=False`, frozen at terminal (balanced
panel for analysis).

## Deliverables

1. `flip_truth_dataset.parquet` — one row per event.
2. `flip_checkpoint_dataset.parquet` — one row per event per checkpoint.
3. `flip_truth_summary.md` — outcome distribution, path-quality distribution,
   and top feature separations (Cohen's d, rank, decile) for Elite vs non-Elite.
   No ML, no optimization, no parameter search.

## Causality / no-look-ahead controls

- `decision_ts = bar.ts_init` everywhere.
- All MTF state via registry only; `audit_provenance(decision_ts)` before every
  entry snapshot (fail-fast).
- Indicators are recursive/deque streaming over completed bars; feature engine
  is updated with the flip/bar1 bar before snapshotting.
- Entry at a 1m boundary; path MFE/MAE only over 1s bars with
  `ts_event >= entry_ts` (no first-minute blind spot).
- Audit gate: `lookahead-auditor` run on the full scope BEFORE collection;
  1-week causality smoke (zero `CausalityViolation`) before the full run.
