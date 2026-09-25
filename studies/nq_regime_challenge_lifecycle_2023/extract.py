"""Regime lifecycle extraction (2023 DEVELOPMENT only; reusable by later studies).

Replays the authoritative dual-EMA engine (features/trackers/regime_dual_ema.py) on catalog 1m bars
(NQ.XCME-1-MINUTE-LAST-EXTERNAL) from 2022-12-20 (warm-up) to the close of the last development session
(2023-10-17 21:00 UTC). The final 20% of 2023 and 2024+ are never loaded. 5m / 15m / 1h regimes come from the
same tracker fed clock-bucketed bars built from those 1m bars; an HTF bar becomes known at its bucket end.

Outputs (artifacts/, reusable):
  LIFECYCLE_1M.parquet    every 1m bar: OHLCV, 1m regime, flip flag, ATR, EMA3/EMA9 of high and low, and the
                          5m/15m/1h regime, regime start, ATR and EMAs as of that bar's close (causal)
  REGIME_LEDGER.parquet   every replayed 1m regime (overnight and the 84 in-session holes included): start, end,
                          dir, ATR at start, anchor open, start/end close, 1m high/low, duration, audited flag
  LIFECYCLE_1S.parquet    per second from S to T for every audited regime (6,024): t (s since S), o/h/l/c/v
Parity (hard failure otherwise): flips / dir / ATR vs the audited timeline, terminal flips, HTF dir + start vs
the audited merged frame at T0, 1s close at S == 1m close, 1s entry open == audited entry.

    python studies/nq_regime_challenge_lifecycle_2023/extract.py
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

from features.trackers.regime_dual_ema import DualEmaRegimeTracker, SEMANTICS_VERSION  # noqa: E402

ROOT, BASE = REPO.parent, REPO.name.split("-")[0]
TL = ROOT / f"{BASE}-nq_post_entry_path_mechanism_2023" / "studies" / "nq_post_entry_path_mechanism_2023" / "artifacts" / "TRADE_EVENT_TIMELINE.parquet"
SPLIT = ROOT / f"{BASE}-nq_target_a_constrained_stationary_2023" / "studies" / "nq_target_a_constrained_stationary_2023" / "artifacts" / "TEMPORAL_SPLIT_2023.json"
MERGED = ROOT / f"{BASE}-nq_mtf_structural_predictive_ranking" / "studies" / "nq_mtf_structural_predictive_ranking" / "_work" / "controller" / "merged"
EXPECT_SHA = {"candidates.parquet": "475209b46caf48b674d66833f56005c8fc6c6436f34c8aa50626da7d07300842",
              "observations.parquet": "98e03dc4a2cf01b44d05c45d84b81af5768848142216945cfd133e13d66303b6"}
CATALOG = ROOT / BASE / "data" / "catalog" / "NQ_1S_V2_GLOBEX"
BAR_1M, BAR_1S = "NQ.XCME-1-MINUTE-LAST-EXTERNAL", "NQ.XCME-1-SECOND-LAST-EXTERNAL"
WARMUP_START = pd.Timestamp("2022-12-20", tz="UTC")
DEV_END = pd.Timestamp("2023-10-17 21:00", tz="UTC")        # close of the last development session
NS = 1_000_000_000
HTF = {"5m": 5, "15m": 15, "1h": 60}
KEY = ["observation_ts", "regime_start_ns", "checkpoint_index"]
OUT = HERE / "artifacts"


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def replay(h, l, c):
    tr = DualEmaRegimeTracker()
    n = len(h)
    out = {k: np.full(n, np.nan) for k in ("regime", "atr", "e3h", "e9h", "e3l", "e9l")}
    flip = np.zeros(n, bool)
    for i in range(n):
        u = tr.observe(h[i], l[i], c[i])
        out["regime"][i], out["atr"][i] = u.regime, (np.nan if u.atr is None else u.atr)
        out["e3h"][i], out["e9h"][i], out["e3l"][i], out["e9l"][i] = u.ema_short_high, u.ema_long_high, u.ema_short_low, u.ema_long_low
        flip[i] = u.flipped
    return out, flip


def main() -> None:
    from utils.runner.data import CausalDataLoader
    T = {}
    t0 = time.time()
    tl = pd.read_parquet(TL).sort_values("t0_ns").reset_index(drop=True)
    split = json.loads(SPLIT.read_text(encoding="utf-8"))
    blk_a = set(split["blocks"]["development_train"]["session_list"])
    blk_b = set(split["blocks"]["development_validation"]["session_list"])
    assert set(tl.session) == blk_a | blk_b and len(tl) == 6024 and tl.session.max() <= "2023-10-17"
    loader = CausalDataLoader(CATALOG)

    # ---------------- 1m engine replay
    bars = loader.load_bars(BAR_1M, WARMUP_START, DEV_END)
    m = pd.DataFrame({"ts": np.fromiter((b.ts_init for b in bars), np.int64, len(bars)),
                      "o": [b.open.as_double() for b in bars], "h": [b.high.as_double() for b in bars],
                      "l": [b.low.as_double() for b in bars], "c": [b.close.as_double() for b in bars],
                      "v": [b.volume.as_double() for b in bars]})
    loader.clear_cache()
    assert m.ts.max() <= DEV_END.value
    st, flip = replay(m.h.to_numpy(), m.l.to_numpy(), m.c.to_numpy())
    for k, v in st.items():
        m[k] = v
    m["flip"] = flip
    # ---------------- HTF replay: clock buckets of 1m bars, known at bucket end
    for tf, mins in HTF.items():
        B = mins * 60 * NS
        g = m.groupby((m.ts + B - 1) // B)
        agg = pd.DataFrame({"end": g.ts.max().index.to_numpy() * B, "h": g.h.max().to_numpy(), "l": g.l.min().to_numpy(), "c": g.c.last().to_numpy()})
        s, f = replay(agg.h.to_numpy(), agg.l.to_numpy(), agg.c.to_numpy())
        reg = s["regime"]
        start = np.where(f | ((reg != 0) & (np.concatenate([[0], reg[:-1]]) == 0)), agg.end.to_numpy(), np.nan)
        start = pd.Series(start).ffill().to_numpy()
        j = np.searchsorted(agg.end.to_numpy(), m.ts.to_numpy(), side="right") - 1          # last HTF bar closed at or before
        ok = j >= 0
        for k, arr in (("dir", reg), ("start", start), ("atr", s["atr"]), ("e3h", s["e3h"]), ("e9h", s["e9h"]), ("e3l", s["e3l"]), ("e9l", s["e9l"]), ("close", agg.c.to_numpy())):
            col = np.full(len(m), np.nan)
            col[ok] = arr[j[ok]]
            m[f"{k}_{tf}"] = col
    T["engine_replay_s"] = round(time.time() - t0, 1)

    # ---------------- parity vs audited timeline and merged frame
    par = {}
    fl = m[m.flip]
    mm = tl.merge(fl[["ts", "regime", "atr"]], left_on="regime_start_ns", right_on="ts", how="left")
    par["flip_missing"] = int(mm.ts.isna().sum())
    par["dir_mismatch"] = int((mm.regime != mm.dir).sum())
    par["atr_mismatch"] = int((~np.isclose(mm.atr_x, mm.atr_y, rtol=0, atol=1e-9)).sum())
    par["terminal_flip_missing"] = int((~tl.terminal_ts.isin(fl.ts)).sum())
    if {n: sha(MERGED / n) for n in EXPECT_SHA} != EXPECT_SHA:
        raise SystemExit("INVALID: audited frame hash differs")
    c = pd.read_parquet(MERGED / "candidates.parquet", columns=KEY + [f"{p}_{tf}" for tf in HTF for p in ("dir", "start_ns")])
    c = c[(c.checkpoint_index == 0) & c.regime_start_ns.isin(set(tl.regime_start_ns))].drop_duplicates("regime_start_ns")
    j = np.searchsorted(m.ts.to_numpy(), c.observation_ts.to_numpy(), side="right") - 1
    for tf in HTF:
        par[f"htf_{tf}_dir_mismatch"] = int((m[f"dir_{tf}"].to_numpy()[j] != c[f"dir_{tf}"].to_numpy()).sum())
        par[f"htf_{tf}_start_mismatch"] = int((m[f"start_{tf}"].to_numpy()[j] != c[f"start_ns_{tf}"].to_numpy()).sum())

    # ---------------- regime ledger (all replayed 1m regimes inside the development window)
    fi = np.flatnonzero(m.flip.to_numpy())
    ts, hi, lo, cl, op = m.ts.to_numpy(), m.h.to_numpy(), m.l.to_numpy(), m.c.to_numpy(), m.o.to_numpy()
    led = []
    for a, b in zip(fi[:-1], fi[1:]):
        d = int(m.regime.iat[a])
        led.append({"start_ns": ts[a], "end_ns": ts[b], "dir": d, "atr_start": m.atr.iat[a], "anchor_open": op[a], "start_close": cl[a],
                    "end_close": cl[b], "hi": max(hi[a + 1:b + 1].max(), cl[a]), "lo": min(lo[a + 1:b + 1].min(), cl[a]),
                    "bars": b - a, "duration_s": (ts[b] - ts[a]) // NS})
    led = pd.DataFrame(led)
    led["fav_ext"] = np.where(led.dir > 0, led.hi, led.lo)
    led["audited"] = led.start_ns.isin(set(tl.regime_start_ns))
    audited_rows = led[led.audited].merge(tl[["regime_start_ns", "terminal_ts"]], left_on="start_ns", right_on="regime_start_ns")
    par["ledger_end_vs_terminal_mismatch"] = int((audited_rows.end_ns != audited_rows.terminal_ts).sum())
    par["ledger_audited_count"] = int(led.audited.sum())

    # ---------------- 1s lifecycle pass (audited regimes)
    t1 = time.time()
    rows, n1 = [], 0
    par.update({"close_at_S_mismatch": 0, "entry_open_mismatch": 0})
    mclose = pd.Series(cl, index=ts)
    for sess, part in tl.groupby("session", sort=True):
        s0, e0 = int(part.regime_start_ns.min()) - 5 * NS, int(part.terminal_ts.max()) + 30 * NS
        b1 = loader.load_bars(BAR_1S, pd.Timestamp(s0, tz="UTC"), pd.Timestamp(e0, tz="UTC"))
        loader.clear_cache()
        n1 += len(b1)
        ti = np.fromiter((b.ts_init for b in b1), np.int64, len(b1))
        te = np.fromiter((b.ts_event for b in b1), np.int64, len(b1))
        o1 = np.fromiter((b.open.as_double() for b in b1), float, len(b1))
        h1 = np.fromiter((b.high.as_double() for b in b1), float, len(b1))
        l1 = np.fromiter((b.low.as_double() for b in b1), float, len(b1))
        c1 = np.fromiter((b.close.as_double() for b in b1), float, len(b1))
        v1 = np.fromiter((b.volume.as_double() for b in b1), float, len(b1))
        for r in part.itertuples():
            S, E = int(r.regime_start_ns), int(r.terminal_ts)
            k = int(np.searchsorted(ti, S, side="right")) - 1
            par["close_at_S_mismatch"] += int(c1[k] != mclose[S])
            i0 = int(np.searchsorted(ti, int(r.t0_ns), side="right"))
            par["entry_open_mismatch"] += int(o1[i0] != r.entry_price or te[i0] != r.entry_ts)
            a, b = int(np.searchsorted(ti, S, side="right")), int(np.searchsorted(ti, E, side="right"))
            rows.append(pd.DataFrame({"regime_start_ns": np.int64(S), "t": ((ti[a:b] - S) // NS).astype(np.int32),
                                      "o": o1[a:b].astype(np.float32), "h": h1[a:b].astype(np.float32), "l": l1[a:b].astype(np.float32),
                                      "c": c1[a:b].astype(np.float32), "v": v1[a:b].astype(np.float32)}))
    life = pd.concat(rows, ignore_index=True)
    T["raw_1s_pass_s"] = round(time.time() - t1, 1)

    OUT.mkdir(exist_ok=True)
    m.to_parquet(OUT / "LIFECYCLE_1M.parquet", index=False)
    led.to_parquet(OUT / "REGIME_LEDGER.parquet", index=False)
    life.to_parquet(OUT / "LIFECYCLE_1S.parquet", index=False)
    T["total_s"] = round(time.time() - t0, 1)
    audit = {"engine": SEMANTICS_VERSION, "bars_1m": len(m), "bars_1s": n1, "lifecycle_1s_rows": len(life), "ledger_regimes": len(led),
             "final_20pct_loaded": False, "years_touched": [2022, 2023], "note_2022": "2022-12-20..12-31 1m bars = engine warm-up only",
             "htf_atr_note": "HTF ATR here is the tracker's Wilder ATR on clock buckets; the audited frame's atr_5m/15m/1h differ and are not used",
             "parity": par, "PASS": all(v == 0 for k, v in par.items() if k != "ledger_audited_count") and par["ledger_audited_count"] == 6024,
             "runtime_s": T}
    (OUT / "EXTRACT_AUDIT.json").write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(audit, indent=1))
    if not audit["PASS"]:
        raise SystemExit("INVALID: parity failed")


if __name__ == "__main__":
    main()
