"""Enumerate capability rows (360/1380, poc non-null) absent from the legacy ledgers; relate them to rolls and to
the legacy ATR(14) 5-minute seeding (vp_v1.atr_series: rows with atr NaN are skipped by vp_v1.run_block)."""
import json, sys
from pathlib import Path
import numpy as np, pandas as pd
W = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(W)); sys.path.insert(0, str(W / "scripts"))
import parity_volume_profile_rolling as P
from features.trackers.volume_profile_rolling import MIN_NS, VolumeProfileKernel, open_minute_ends

ref = P.dataset_v2.load_reference_tables(P.CATALOG, ["sessions", "rolls"])
s = ref["sessions"].copy(); s["session_date"] = s.session_date.astype(str)
s = s[s.close_ns <= P.DEV_END].sort_values("open_ns").reset_index(drop=True)
om = open_minute_ends(s.open_ns.to_numpy(), s.close_ns.to_numpy())
rolls = np.sort(ref["rolls"].ts_ns.to_numpy().astype(np.int64))
out = {}
for blk, (s0, s1) in P.BLOCKS.items():
    b = s[(s.session_date >= s0) & (s.session_date <= s1)]
    ef, et = int(b.open_ns.min()), int(b.close_ns.max())
    O = {h: P.oracle(h, blk, ef, et) for h in (360, 1380)}
    res = []
    for r in rolls[(rolls > ef) & (rolls <= et)]:
        t0 = int(s[s.close_ns <= r].tail(2).open_ns.min())          # two sessions before the roll
        t1 = int(om[np.searchsorted(om, r) + 200])
        K = {h: VolumeProfileKernel(om, rolls, h, "range_uniform", origin_ns=t0) for h in O}
        rows = {h: [] for h in O}
        for h, k in K.items():
            k.on_close = (lambda kk, rr: (lambda p: rr.append(kk.snapshot()) if r < kk.om[p] <= t1 else None))(k, rows[h])
        d = P.tape(int(om[np.searchsorted(om, t0, side="right")]) - MIN_NS, t1)
        for row in d[["ts", "h", "l", "c", "v"]].itertuples(index=False):
            for k in K.values():
                k.push(int(row.ts), float(row.h), float(row.l), float(row.c), float(row.v))
        for k in K.values():
            k.close_through(t1)
        # legacy ATR seeding: 5-min bar ends (minute ts % 5min == 0) after the roll; ATR defined from the 14th end
        post = om[(om > r) & (om <= t1)]
        ends = post[(post // MIN_NS) % 5 == 0]
        atr_from = int(ends[13])
        for h in O:
            C = pd.DataFrame(rows[h]).set_index("snapshot_ts")
            nn = C[C.poc.notna()]
            extra = nn[~nn.index.isin(O[h].index)]
            first_o = int(O[h].index[O[h].index > r].min())
            res.append(dict(roll=pd.Timestamp(int(r), tz="UTC").isoformat(), horizon=h, extra=len(extra),
                             extra_first=pd.Timestamp(int(extra.index.min()), tz="UTC").isoformat() if len(extra) else None,
                             extra_last=pd.Timestamp(int(extra.index.max()), tz="UTC").isoformat() if len(extra) else None,
                             extra_window_minutes=[int(extra.window_minutes.min()), int(extra.window_minutes.max())] if len(extra) else None,
                             extra_all_roll_truncated=bool(extra.roll_truncated.all()), extra_any_window_complete=bool(extra.window_complete.any()),
                             first_oracle_row=pd.Timestamp(first_o, tz="UTC").isoformat(),
                             legacy_atr_defined_from=pd.Timestamp(atr_from, tz="UTC").isoformat(),
                             first_oracle_equals_atr_seed=first_o == atr_from,
                             extra_are_exactly_minutes_before_atr_seed=bool((extra.index < atr_from).all() and
                                 len(extra) == int(((nn.index > r) & (nn.index < atr_from)).sum())),
                             oracle_rows_missing_after_seed=int(((C.index >= atr_from) & C.poc.notna() & ~C.index.isin(O[h].index)).sum())))
            print(json.dumps(res[-1]), flush=True)
    out[blk] = res
json.dump(out, open(W / "artifacts" / "parity" / "volume_profile_rolling_roll_warmup.json", "w"), indent=1)

