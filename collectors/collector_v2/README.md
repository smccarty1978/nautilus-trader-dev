# Collector V2

NT-native MTF feature/state collector. The single source of MTF
truth in this repo.

## Status

- Foundation self-test: **10 / 10 passing**
  (`tests/test_provenance.py`)
- Micro smoke (Jan 5-9, 2024): **162 / 162 snapshot parity** between
  Mode 1 and Mode 2; 0 provenance violations
- Full Jan 8-15, 2024 smoke parity: **PASSED**
  (`reports/SMOKE_PARITY_2024_01_08_15.md`)
  - 366 / 366 snapshots matched, 0 only-Mode-1, 0 only-Mode-2, 48
    cols compared, 0 mismatched
  - 0 provenance violations across 30s / 1m / 3m / 5m, both modes
  - 75 V_A trades emitted in Mode 2 with full snapshot linkage

## Timing convention (HARD RULE)

- **Decisions** use `bar.ts_init` (NT delivery time). Never
  `bar.ts_event`.
- **Bucket assignment** uses `bar.ts_event` (calendar OPEN).
- **`close_ts`** is the calendar close (e.g. 5m bucket
  [09:00, 09:05) has `close_ts = 09:05:00`).
- **Audit invariant** on every snapshot:
  `close_ts <= decision_ts` for every TF in the registry. Naturally
  satisfied because the trigger 1s bar arrives at `ts_init = bucket
  close + 1s`.

## Public surface

- `CompletedBarRegistry` — single store of latest closed bar state per TF
- `CompletedBarState` — frozen per-TF state (close_ts, regime, ATR, EMAs, ...)
- `RegimeStateEngine` — per-TF EMA/ATR/regime, writes to registry on bar close
- `TimeframeAggregator` — 1s → 30s/1m/3m/5m, calendar-aligned, no partial closes
- `FeatureSnapshotBuilder` — builds frozen `FeatureSnapshot` rows; audits provenance first
- `CollectorV2Strategy` + `CollectorV2Config` — single strategy with `mode="research"` or `"trading"`

## Reference V_A strategy (built in)

- Detect 1m raw regime flip (from registry, not from raw 1m bar)
- Bar+1 HH/LL confirmation
- Bar+1 momentum confirmation (close-direction matches regime)
- Hold to opposing 1m regime flip CLOSE (causal)
- Optional 5m regime alignment gate via `require_5m_aligned=True`

Both modes emit identical snapshots at:
- regime flip
- bar+1 confirmation check (whether or not it passed)

Mode 2 additionally:
- submits market entry 1s before `decision_ts + 30s` so it fills at
  the target bar's open
- holds to opposing 1m regime flip; submits market exit at flip
- emits a `trades.parquet` linked via `event_id` to the snapshot
  that triggered each entry

## Outputs (per run)

```
<output_dir>/
├── snapshots.parquet   # one row per snapshot (regime_flip, bar1_check, ...)
├── trades.parquet      # Mode 2 only — full trade log
├── diag.json           # diagnostic counters
└── (FAILURE.txt)       # written if a CausalityViolation halts the run
```

## Rules

See `CAUSALITY.md` at repo root. The summary:

- No feature may use a source bar whose close time is after
  decision time.
- HTF features lag until bucket close.
- Regime flips are known only at close.
- No trade may be filtered by future regime end.
- Offline research is provisional until parity passes.

Banned patterns elsewhere in the repo (use `utils/causality` and
this collector instead):
- `searchsorted(htf_open_times, T) - 1` for feature lookup
- `pd.merge_asof` for state reconstruction
- `pd.resample` for feature engineering with HTF
