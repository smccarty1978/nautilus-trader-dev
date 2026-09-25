"""One pass over raw 1s bars: per-trade, per-second path from the original T0 entry to the terminal bound.

Population = the audited 2023 DEVELOPMENT trades of nq_post_entry_path_mechanism_2023 (TRADE_EVENT_TIMELINE,
6,024 trades, 205 sessions, first 80% of 2023). The final 20% of 2023 is never loaded: sessions come only from
that table. Entry, ATR (atr_entry_1m) and terminal bound are taken from it unchanged.

Per second (bars with T0 < ts_init < terminal, same >300 s gap censor as the audited timeline):
  t    seconds since T0 (bar close)
  hi   favourable excursion of the bar extreme, in A (from entry)
  lo   adverse excursion of the bar extreme, in A (positive = against the trade)
  c    close P&L in A

Parity: first-touch seconds of +0.5/+1/+1.5/+2/+3A and -0.5/-1A must equal the audited timeline exactly.

    python studies/nq_t0_segment_path_atlas_2023/extract_paths.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO))

ROOT, BASE = REPO.parent, REPO.name.split("-")[0]
SRC = ROOT / f"{BASE}-nq_post_entry_path_mechanism_2023" / "studies" / "nq_post_entry_path_mechanism_2023" / "artifacts"
CATALOG = ROOT / BASE / "data" / "catalog" / "NQ_1S_V2_GLOBEX"
BAR_TYPE = "NQ.XCME-1-SECOND-LAST-EXTERNAL"
NS = 1_000_000_000
MAX_GAP_NS = 300 * NS
ALL_FAV = (0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0)
ALL_ADV = (0.25, 0.5, 1.0)
WORK = HERE / "_work"
OUT = HERE / "artifacts"


def main() -> None:
    from utils.runner.data import CausalDataLoader
    t_start = time.time()
    tl = pd.read_parquet(SRC / "TRADE_EVENT_TIMELINE.parquet")
    assert tl["session"].max() <= "2023-10-17" and len(tl) == 6024
    loader = CausalDataLoader(CATALOG)
    paths, touches, parity = [], [], {"compared": 0, "mismatch": 0, "entry_mismatch": 0}
    for tid_sess, part in tl.groupby("session"):
        start = pd.Timestamp(int(part["t0_ns"].min()), tz="UTC") - pd.Timedelta(seconds=5)
        end = pd.Timestamp(int(part["terminal_ts"].max()), tz="UTC") + pd.Timedelta(seconds=5)
        bars = loader.load_bars(BAR_TYPE, start, end)
        ti = np.fromiter((b.ts_init for b in bars), dtype=np.int64, count=len(bars))
        te = np.fromiter((b.ts_event for b in bars), dtype=np.int64, count=len(bars))
        op = np.fromiter((b.open.as_double() for b in bars), dtype=float, count=len(bars))
        hi = np.fromiter((b.high.as_double() for b in bars), dtype=float, count=len(bars))
        lo = np.fromiter((b.low.as_double() for b in bars), dtype=float, count=len(bars))
        cl = np.fromiter((b.close.as_double() for b in bars), dtype=float, count=len(bars))
        for r in part.itertuples():
            T0, T, d, atr, ep = int(r.t0_ns), int(r.terminal_ts), int(r.dir), float(r.atr), float(r.entry_price)
            i0 = int(np.searchsorted(ti, T0, side="right"))
            parity["entry_mismatch"] += int(op[i0] != ep or int(te[i0]) != int(r.entry_ts))
            iT = int(np.searchsorted(ti, T, side="left"))              # bars closing strictly before the terminal bound
            sti = ti[i0:iT]
            gaps = np.diff(np.concatenate([[int(r.entry_ts)], sti]))
            gi = np.flatnonzero(gaps > MAX_GAP_NS)
            n = int(gi[0]) if len(gi) else len(sti)
            sti = sti[:n]
            fx = ((hi[i0:i0 + n] - ep) if d > 0 else (ep - lo[i0:i0 + n])) / atr
            ax = ((ep - lo[i0:i0 + n]) if d > 0 else (hi[i0:i0 + n] - ep)) / atr
            cx = (cl[i0:i0 + n] - ep) * d / atr
            t = (sti - T0) // NS
            for side, xs, arr in (("fav", (0.5, 1.0, 1.5, 2.0, 3.0), fx), ("adv", (0.5, 1.0), ax)):
                for x in xs:
                    lvl = ep + d * x * atr if side == "fav" else ep - d * x * atr
                    # kernel level arithmetic, same comparison as the audited timeline
                    if side == "fav":
                        hit = (hi[i0:i0 + n] >= lvl) if d > 0 else (lo[i0:i0 + n] <= lvl)
                    else:
                        hit = (lo[i0:i0 + n] <= lvl) if d > 0 else (hi[i0:i0 + n] >= lvl)
                    idx = np.flatnonzero(hit)
                    mine = float(t[idx[0]]) if len(idx) else np.nan
                    want = getattr(r, f"t_{side}_{f'{x:.1f}'.replace('.', 'p')}")
                    parity["compared"] += 1
                    parity["mismatch"] += int(not ((np.isnan(mine) and np.isnan(want)) or mine == want))
            trow = {"regime_start_ns": np.int64(r.regime_start_ns)}
            for side, xs in (("fav", ALL_FAV), ("adv", ALL_ADV)):
                for x in xs:
                    lvl = ep + d * x * atr if side == "fav" else ep - d * x * atr
                    if side == "fav":
                        hit = (hi[i0:i0 + n] >= lvl) if d > 0 else (lo[i0:i0 + n] <= lvl)
                    else:
                        hit = (lo[i0:i0 + n] <= lvl) if d > 0 else (hi[i0:i0 + n] >= lvl)
                    idx = np.flatnonzero(hit)
                    trow[f"t_{side}_{x:g}".replace(".", "p")] = float(t[idx[0]]) if len(idx) else np.nan
            touches.append(trow)
            paths.append(pd.DataFrame({"regime_start_ns": np.int64(r.regime_start_ns), "t": t.astype(np.int32),
                                       "hi": fx.astype(np.float32), "lo": ax.astype(np.float32), "c": cx.astype(np.float32)}))
    p = pd.concat(paths, ignore_index=True)
    WORK.mkdir(exist_ok=True)
    OUT.mkdir(exist_ok=True)
    p.to_parquet(WORK / "PATH_1S.parquet", index=False)
    pd.DataFrame(touches).to_parquet(WORK / "FIRST_TOUCH.parquet", index=False)
    audit = {"population": "TRADE_EVENT_TIMELINE of nq_post_entry_path_mechanism_2023 (2023 development sessions only)",
             "n_trades": int(p["regime_start_ns"].nunique()), "n_rows": len(p), "final_20pct_loaded": False,
             "first_touch_parity_vs_audited_timeline": parity, "PASS": parity["mismatch"] == 0 and parity["entry_mismatch"] == 0,
             "runtime_s": round(time.time() - t_start, 1)}
    (OUT / "PATH_EXTRACT_AUDIT.json").write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(audit, indent=1))


if __name__ == "__main__":
    main()
