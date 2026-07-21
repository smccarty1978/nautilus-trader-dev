# Collector v2 — skeleton

Framework for the v2 leak-safe, checkpoint-native collector.

**Spec:** `collector_v2_spec.md`
**Contract:** `models/ml_5m_flip/feature_contract_v2.json`

## Directory

```
studies/1m_regime_collector_v2/
├── README.md                                   ← this file
├── collector.py                                ← skeleton (framework complete, features TODO)
├── run_collection.py                           ← runner (--smoke / --year / full 6yr)
├── contract/
│   ├── generate_feature_contract_v2.py         ← emits feature_contract_v2.json
│   ├── audit_v2_contract.py                    ← contract audit
│   └── audit_v2_contract.log                   ← audit report (0 duplicates, 0 issues)
├── parity/                                     ← parity harness (Phase 3 work order)
├── analysis/                                   ← research scripts (after collection)
└── results/                                    ← parquet outputs
```

## What the skeleton does (complete)

- Subscribes to 1s + 1m bars, enforces §3.5 ts_init_delta invariant.
- Aggregates 30s (from 1s) and 5m (from 1m) internally per §5.5.
- Maintains RegimeState at 1m/30s/5m, ATR(14), SMA(20/50),
  EMA(3/9), session high/low, rolling buffers.
- §3.6 warmup gating — no events emitted until minimum history satisfied.
- §3 event lifecycle: flip → bar+1 HH/LL → event registered with
  root-feature snap.
- Checkpoint snap scheduling — every 30s boundary from `signal_time`
  through termination fires `_snap_checkpoint(T)`.
- Termination rule per §5 — opposing 1m flip OR `max_checkpoint_s`.
  Emits `regime_exit_reason` enum.
- Forward-path tracker scaffold — 1s-bar resolution per §5.5, bracket
  race outcome slots, window censoring flags.
- Two-table output: `v2_feature_snapshots_*.parquet` and
  `v2_outcome_labels_*.parquet` (plus event summary + QA log).

## What's intentionally stubbed (TODO markers in code)

Feature math for the 189 contracted features is split into focused
work orders. All TODOs are tagged with a category prefix so they can
be picked up in any order:

| TODO tag | What's needed | ~Count |
|---|---|---|
| `TODO[feat/root/flip_anatomy]` | §6.1 flip bar anatomy | 13 |
| `TODO[feat/root/bar1_anatomy]` | §6.1 bar+1 anatomy | 15 |
| `TODO[feat/root/two_bar]` | §6.1 two-bar | 6 |
| `TODO[feat/root/pre_signal_lookback]` | §6.2A + §15.2 | 39 |
| `TODO[feat/root/compression]` | §6.2B + §15.3 | 5 |
| `TODO[feat/root/local_structure]` | §6.2C + §15.4 | 8 |
| `TODO[feat/root/trend_quality]` | §6.2D + §15.5 | 6 |
| `TODO[feat/root/regime_ctx]` | §6.3 + §15.6 | 6 |
| `TODO[feat/root/ma_state]` | §6.3 | 9 |
| `TODO[feat/root/vol_state]` | §6.3 | 6 |
| `TODO[feat/root/session_sig]` | §6.6 signal | 9 |
| `TODO[feat/ckp/*]` | §6.4 + §6.5 + §6.6 ckp + §15.7 | 62 |
| `TODO[label/forward_mfe_mae]` | §7.1 MFE/MAE grid | 12 |
| `TODO[label/bracket]` | §7.2 bracket races | 4 × 3 cols |
| `TODO[label/regime_exit]` | §7.3 | 5 |
| `TODO[label/clean_path]` | §7.4 | 7 |
| `TODO[label/censoring]` | §7.0 censoring flags | 6 |

## How to pick up a TODO

1. Find the feature name in `models/ml_5m_flip/feature_contract_v2.json`.
2. Read its `definition` and `snap_call_order_anchor` fields.
3. Implement the computation at the matching TODO marker in
   `collector.py`.
4. Verify parity on at least one sampled event via the parity harness
   (to be built in the next step).

## Runner usage

```bash
# 1-week smoke test (recommended first)
python studies/1m_regime_collector_v2/run_collection.py --smoke

# Single year
python studies/1m_regime_collector_v2/run_collection.py --year 2025

# Full 2020-2025
python studies/1m_regime_collector_v2/run_collection.py
```

Output artifacts per run:

- `results/v2_feature_snapshots_<LABEL>.parquet`
- `results/v2_outcome_labels_<LABEL>.parquet`
- `results/v2_event_summary_<LABEL>.parquet`
- `results/v2_collection_qa_<LABEL>.log`

## Next work orders (in order)

1. **Implement `_snap_root_features`** — all 123 signal-time features.
   Smoke-test produces non-NaN feature rows.
2. **Implement `_snap_checkpoint`** — all 65 checkpoint-time features.
3. **Instantiate `ForwardPathTracker` at fill_time** — 1s bar arrives
   at `fill_time`, open becomes `execution_price`, tracker created.
4. **Implement label emission in `_emit_event_records`** — MFE/MAE
   grid, bracket races, regime-exit PnL, clean-path booleans,
   censoring flags.
5. **Build parity harness** (`parity/`) and run smoke-test parity on
   ≥ 50 sampled events. Pass/fail report required before full 6yr run.
6. **Full 6-year collection.**
7. Archive v1 pipeline.

## Verification

The skeleton imports cleanly:

```
python -c "
import sys
sys.path.insert(0, 'studies/1m_regime_collector_v2')
from collector import CollectorV2, CollectorV2Config
print('skeleton imports OK')
"
```
