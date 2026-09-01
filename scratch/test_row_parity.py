import pandas as pd
import numpy as np
from pathlib import Path
from utils.runner.data import CausalDataLoader
from research_workflow.target_runtime import OrderedBarrierTargetRuntime

work_dir = Path('studies/regime_transition_target_before_stop_v1/_work/train_merged_collection')
c_df = pd.read_parquet(work_dir / 'candidates.parquet').head(10)
o_df = pd.read_parquet(work_dir / 'observations.parquet').head(10)

loader = CausalDataLoader(Path('data/catalog/NQ_v0_2020_2026'))
bars = loader.load_bars('NQ.XCME-1-SECOND-LAST-EXTERNAL', pd.Timestamp('2021-01-04 00:00:00', tz='UTC'), pd.Timestamp('2021-01-04 23:59:59', tz='UTC'))
events = [{'ts': int(b.ts_init), 'open': float(b.open), 'high': float(b.high), 'low': float(b.low), 'gap': False} for b in bars]
events_ts = np.array([e['ts'] for e in events])

m1_bars = loader.load_bars('NQ.XCME-1-MINUTE-LAST-EXTERNAL', pd.Timestamp('2020-12-28 00:00:00', tz='UTC'), pd.Timestamp('2021-01-04 23:59:59', tz='UTC'))
from scripts.run_phase_c_full_evaluation import RegimeEngine
engine = RegimeEngine()
m1_ts = np.zeros(len(m1_bars), dtype=np.int64)
m1_atr = np.zeros(len(m1_bars), dtype=np.float64)
for i, b in enumerate(m1_bars):
    m1_ts[i] = int(b.ts_init)
    m1_atr[i] = engine.update(float(b.high), float(b.low), float(b.close))

runtime = OrderedBarrierTargetRuntime()
for i in range(10):
    T = int(o_df.iloc[i]['observation_ts'])
    reg_dir = int(o_df.iloc[i]['regime_direction'])
    atr_idx = np.searchsorted(m1_ts, T, side='right') - 1
    atr_val = m1_atr[atr_idx]
    cand = {
        'observation_ts': T,
        'direction': reg_dir,
        'atr': atr_val,
        'favorable_atr': 1.0,
        'adverse_atr': 1.0,
        'horizon_seconds': 300,
        'session_close_ts': int(o_df.iloc[i]['session_close_ts']),
        'max_gap_seconds': None,
        'entry_reference': 'next_bar_open',
    }
    pending = runtime.open_pending(cand)
    s_idx = np.searchsorted(events_ts, T, side='right')
    for b in events[s_idx:s_idx+350]:
        runtime.ingest_bar(pending, b)
    res = runtime.terminal(pending)
    print(f"Row {i}: actual={o_df.iloc[i]['disposition']}, actual_ts={o_df.iloc[i]['resolved_at_ts']}, runtime_disp={res.disposition}, runtime_ts={res.resolved_at_ts}")
