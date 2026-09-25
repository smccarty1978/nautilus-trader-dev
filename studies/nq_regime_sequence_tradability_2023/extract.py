"""Regime-level table for the regime-sequence tradability atlas (2023 DEVELOPMENT sessions only).

Unit = one completed 1m V_A regime of the audited RTH chain. Population = TRADE_EVENT_TIMELINE of
nq_post_entry_path_mechanism_2023 (6,024 regimes/trades, 205 development sessions). Sessions come only from
that table and TEMPORAL_SPLIT_2023.json: the final 20% of 2023 is never loaded; 2024+ never touched.

One raw-1s CausalDataLoader pass per session computes, per regime (flip price = close of the last 1s bar with
ts_init <= flip instant, i.e. the close of the 1m detection bar; the engine anchor start_price_1m is kept):
  start_px / end_px, regime high / low over 1s bars with ts_init in (start, end], trade MFE / MAE from entry,
  1m-grid closes (for clock-window path efficiency).
HTF context at T0 is read from the audited merged frame (checkpoint 0).

Parity (hard failure otherwise):
  * audited start_price_1m (engine anchor, generic_collector: start_price = flip bar open) == open of the first 1s bar
    in (S - 60 s, S]; the causal flip
    price used here is the detection-bar close (1s close at the flip instant)
  * entry open / entry ts == timeline entry
  * gross recomputed from audited terminal_exit_price == timeline terminal_gross_atr
  * session membership == TEMPORAL_SPLIT development blocks

    python studies/nq_regime_sequence_tradability_2023/extract.py
"""
from __future__ import annotations

import hashlib
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
TL = ROOT / f"{BASE}-nq_post_entry_path_mechanism_2023" / "studies" / "nq_post_entry_path_mechanism_2023" / "artifacts" / "TRADE_EVENT_TIMELINE.parquet"
SPLIT = ROOT / f"{BASE}-nq_target_a_constrained_stationary_2023" / "studies" / "nq_target_a_constrained_stationary_2023" / "artifacts" / "TEMPORAL_SPLIT_2023.json"
MERGED = ROOT / f"{BASE}-nq_mtf_structural_predictive_ranking" / "studies" / "nq_mtf_structural_predictive_ranking" / "_work" / "controller" / "merged"
EXPECT_SHA = {"candidates.parquet": "475209b46caf48b674d66833f56005c8fc6c6436f34c8aa50626da7d07300842",
              "observations.parquet": "98e03dc4a2cf01b44d05c45d84b81af5768848142216945cfd133e13d66303b6"}
CATALOG = ROOT / BASE / "data" / "catalog" / "NQ_1S_V2_GLOBEX"
BAR_TYPE = "NQ.XCME-1-SECOND-LAST-EXTERNAL"
NS = 1_000_000_000
KEY = ["observation_ts", "regime_start_ns", "checkpoint_index"]
HTF_COLS = [f"{p}_{tf}" for tf in ("5m", "15m", "1h") for p in
            ("dir", "start_ns", "start_price", "atr", "mfe_atr", "mae_atr", "pnl_atr",
             "prior_dir", "prior_start_price", "prior_end_price", "prior_mfe_price", "prior_mae_price",
             "prior_terminal_displacement_atr", "prior_frozen_atr")]
WORK, OUT = HERE / "_work", HERE / "artifacts"


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> None:
    from utils.runner.data import CausalDataLoader
    t_start = time.time()
    tl = pd.read_parquet(TL).sort_values("t0_ns").reset_index(drop=True)
    split = json.loads(SPLIT.read_text(encoding="utf-8"))
    blk_a = set(split["blocks"]["development_train"]["session_list"])
    blk_b = set(split["blocks"]["development_validation"]["session_list"])
    assert len(blk_a) == 154 and len(blk_b) == 51 and not blk_a & blk_b
    assert set(tl.session) == blk_a | blk_b and tl.session.max() <= "2023-10-17" and len(tl) == 6024
    tl["block"] = np.where(tl.session.isin(blk_a), "A", "B")

    if {n: sha(MERGED / n) for n in EXPECT_SHA} != EXPECT_SHA:
        raise SystemExit("INVALID: audited frame hash differs")
    c = pd.read_parquet(MERGED / "candidates.parquet", columns=KEY + ["start_price_1m", "dir_1m", "atr_entry_1m"] + HTF_COLS)
    o = pd.read_parquet(MERGED / "observations.parquet", columns=KEY + ["terminal_exit_price", "terminal_exit_ts", "terminal_entry_price",
                                                                     "terminal_gross_pnl_points", "terminal_flip_disposition"])
    f = c.merge(o, on=KEY)
    f = f[(f.checkpoint_index == 0) & f.regime_start_ns.isin(set(tl.regime_start_ns))].drop_duplicates("regime_start_ns")
    tl = tl.merge(f.drop(columns=["observation_ts", "checkpoint_index"]), on="regime_start_ns", how="left", validate="1:1")
    par = {"n": len(tl), "frame_missing": int(tl.start_price_1m.isna().sum()),
           "dir_mismatch": int((tl.dir != tl.dir_1m).sum()),
           "atr_mismatch": int((~np.isclose(tl.atr, tl.atr_entry_1m)).sum()),
           "entry_vs_frame_mismatch": int((~np.isclose(tl.entry_price, tl.terminal_entry_price)).sum())}
    g_re = tl.dir * (tl.terminal_exit_price - tl.entry_price) / tl.atr
    par["gross_recompute_mismatch"] = int((~np.isclose(g_re, tl.terminal_gross_atr, atol=1e-9)).sum())

    # ---------------- raw 1s pass
    t1 = time.time()
    loader = CausalDataLoader(CATALOG)
    rows, grid, n_bars = [], [], 0
    par.update({"engine_anchor_mismatch": 0, "entry_open_mismatch": 0})
    for sess, part in tl.groupby("session", sort=True):
        s0 = int(part.regime_start_ns.min()) - 70 * 60 * NS           # 1m grid 70 min before the first flip (RTH history)
        e0 = int(part.terminal_ts.max()) + 5 * NS
        bars = loader.load_bars(BAR_TYPE, pd.Timestamp(s0, tz="UTC"), pd.Timestamp(e0, tz="UTC"))
        n_bars += len(bars)
        ti = np.fromiter((b.ts_init for b in bars), dtype=np.int64, count=len(bars))
        te = np.fromiter((b.ts_event for b in bars), dtype=np.int64, count=len(bars))
        op = np.fromiter((b.open.as_double() for b in bars), dtype=float, count=len(bars))
        hi = np.fromiter((b.high.as_double() for b in bars), dtype=float, count=len(bars))
        lo = np.fromiter((b.low.as_double() for b in bars), dtype=float, count=len(bars))
        cl = np.fromiter((b.close.as_double() for b in bars), dtype=float, count=len(bars))

        def px_at(ts: int) -> float:
            k = int(np.searchsorted(ti, ts, side="right")) - 1
            return float(cl[k]) if k >= 0 else np.nan

        # 1m grid of closes (last 1s close at or before each minute boundary), for clock-window efficiency
        mins = np.arange((s0 // (60 * NS)) * 60 * NS, e0, 60 * NS)
        k = np.searchsorted(ti, mins, side="right") - 1
        grid.append(pd.DataFrame({"session": sess, "ts": mins[k >= 0], "close": cl[k[k >= 0]]}))
        for r in part.itertuples():
            S, T, d, ep = int(r.regime_start_ns), int(r.terminal_ts), int(r.dir), float(r.entry_price)
            sp, xp = px_at(S), px_at(T)
            par["engine_anchor_mismatch"] += int(op[int(np.searchsorted(ti, S - 60 * NS, side="right"))] != r.start_price_1m)  # engine anchor = detection-bar open
            i0 = int(np.searchsorted(ti, int(r.t0_ns), side="right"))
            par["entry_open_mismatch"] += int(op[i0] != ep or int(te[i0]) != int(r.entry_ts))
            a, b = int(np.searchsorted(ti, S, side="right")), int(np.searchsorted(ti, T, side="right"))
            rh, rl = (float(hi[a:b].max()), float(lo[a:b].min())) if b > a else (sp, sp)
            th, tlo = (float(hi[i0:b].max()), float(lo[i0:b].min())) if b > i0 else (ep, ep)
            rows.append({"regime_start_ns": S, "start_px": sp, "end_px": xp, "reg_hi": max(rh, sp), "reg_lo": min(rl, sp),
                         "trade_mfe_atr": ((th - ep) if d > 0 else (ep - tlo)) / r.atr,
                         "trade_mae_atr": ((ep - tlo) if d > 0 else (th - ep)) / r.atr})
    t_raw = time.time() - t1
    reg = tl.merge(pd.DataFrame(rows), on="regime_start_ns", validate="1:1")
    WORK.mkdir(exist_ok=True)
    OUT.mkdir(exist_ok=True)
    reg.to_parquet(WORK / "REGIMES.parquet", index=False)
    pd.concat(grid, ignore_index=True).to_parquet(WORK / "GRID_1M.parquet", index=False)
    audit = {"population": "TRADE_EVENT_TIMELINE of nq_post_entry_path_mechanism_2023 (2023 development sessions only)",
             "split": str(SPLIT.name), "blocks": {"A": len(blk_a), "B": len(blk_b)},
             "final_20pct_loaded": False, "years_touched": [2023], "raw_1s_bars_loaded": n_bars,
             "parity": par, "PASS": all(v == 0 for k, v in par.items() if k != "n"),
             "runtime_s": {"frame": round(t1 - t_start, 1), "raw_1s_pass": round(t_raw, 1), "total": round(time.time() - t_start, 1)}}
    (OUT / "EXTRACT_AUDIT.json").write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(audit, indent=1))
    if not audit["PASS"]:
        raise SystemExit("INVALID: parity failed")


if __name__ == "__main__":
    main()
