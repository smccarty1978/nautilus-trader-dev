"""One raw-1s pass + regime chains for the conditional future-value atlas (2023 DEVELOPMENT sessions only).

Population = TRADE_EVENT_TIMELINE of nq_post_entry_path_mechanism_2023 (6,024 audited trades, 205 development
sessions). Sessions come only from that table: the final 20% of 2023 is never loaded; 2024+ never touched.

Outputs (_work/, not committed):
  PATH_EXT.parquet   per second from entry to terminal + 1800 s (>300 s bar gap censors):
                     t (s since T0), hi / lo / c (A from entry, favourable / adverse / close), v (volume), post (t >= D)
  TRADE_CTX.parquet  per trade: pre-T0 volume baseline (mean 1s volume over the 1800 s before T0)
  CHAINS.parquet     exact 5m/15m/1h regime chains (start_ns, dir) per trade through the terminal flip

Parity (hard failure otherwise):
  * the in-trade part of every path equals the prior study's PATH_1S cache row for row
  * first touches (+0.5..+3A, -0.5/-1A) equal the audited timeline
  * chain-derived T0 alignment / n transitions / first transition time equal the audited timeline

    python studies/nq_conditional_future_value_2023/extract.py
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

from research.analysis.diagnostic_ops import globex_trading_day  # noqa: E402

ROOT, BASE = REPO.parent, REPO.name.split("-")[0]
TL = ROOT / f"{BASE}-nq_post_entry_path_mechanism_2023" / "studies" / "nq_post_entry_path_mechanism_2023" / "artifacts" / "TRADE_EVENT_TIMELINE.parquet"
PRIOR_PATH = ROOT / f"{BASE}-nq_t0_segment_path_atlas_2023" / "studies" / "nq_t0_segment_path_atlas_2023" / "_work" / "PATH_1S.parquet"
MERGED = ROOT / f"{BASE}-nq_mtf_structural_predictive_ranking" / "studies" / "nq_mtf_structural_predictive_ranking" / "_work" / "controller" / "merged"
EXPECT_SHA = {"candidates.parquet": "475209b46caf48b674d66833f56005c8fc6c6436f34c8aa50626da7d07300842",
              "observations.parquet": "98e03dc4a2cf01b44d05c45d84b81af5768848142216945cfd133e13d66303b6"}
CATALOG = ROOT / BASE / "data" / "catalog" / "NQ_1S_V2_GLOBEX"
BAR_TYPE = "NQ.XCME-1-SECOND-LAST-EXTERNAL"
NS = 1_000_000_000
MAX_GAP_NS = 300 * NS
FWD_S = 1800
PRE_S = 1800
TFS = ["5m", "15m", "1h"]
KEY = ["observation_ts", "regime_start_ns", "checkpoint_index"]
WORK, OUT = HERE / "_work", HERE / "artifacts"


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


# --- regime chains: same construction as nq_post_entry_path_mechanism_2023 (audited there; parity re-checked here)
def build_links(f: pd.DataFrame, tf: str):
    dir_of, link = {}, {}
    for s, dcur, ps, pdir in f[[f"start_ns_{tf}", f"dir_{tf}", f"prior_start_ns_{tf}", f"prior_dir_{tf}"]].itertuples(index=False):
        for k, v in ((s, dcur), (ps, pdir)):
            if not pd.isna(k):
                dir_of[int(k)] = v
        if not pd.isna(ps):
            link[int(s)] = int(ps)
    return dir_of, link


def chain_for(obs_ts, obs_start, dir_of, link, s0, T):
    j = int(np.searchsorted(obs_ts, T, side="left"))
    if j >= len(obs_ts):
        return None
    cur, chain = int(obs_start[j]), []
    while cur > s0:
        chain.append(cur)
        if cur not in link:
            return None
        cur = link[cur]
    if cur != s0:
        return None
    chain.append(s0)
    return [(c, dir_of[c]) for c in sorted(c for c in chain if c <= T)]


def main() -> None:
    from utils.runner.data import CausalDataLoader
    t_start = time.time()
    tl = pd.read_parquet(TL)
    assert len(tl) == 6024 and tl.session.max() <= "2023-10-17"
    dev_sessions = set(tl.session)
    tl["D"] = (tl.terminal_ts - tl.t0_ns) // NS

    # ---------------- chains from the audited frame (development sessions only)
    if {n: sha(MERGED / n) for n in EXPECT_SHA} != EXPECT_SHA:
        raise SystemExit("INVALID: audited frame hash differs")
    c = pd.read_parquet(MERGED / "candidates.parquet")
    o = pd.read_parquet(MERGED / "observations.parquet")
    f = c.merge(o.drop(columns=[x for x in o.columns if x in c.columns and x not in KEY]), on=KEY, how="inner")
    f = f[pd.to_datetime(f["observation_ts"], unit="ns", utc=True).dt.year == 2023]
    f["session"] = globex_trading_day(f["observation_ts"])
    f = f[f["session"].isin(dev_sessions)].sort_values("observation_ts")      # final 20% never passes this line
    t0f = f[f.checkpoint_index == 0].set_index("regime_start_ns")
    links = {tf: build_links(f, tf) for tf in TFS}
    obs = {tf: {k: (g["observation_ts"].to_numpy(), g[f"start_ns_{tf}"].to_numpy()) for k, g in f.groupby("session")} for tf in TFS}
    chain_rows, cpar = [], {"compared": 0, "mismatch": 0, "no_chain": 0}
    for r in tl.itertuples():
        for tf in TFS:
            dir_of, link = links[tf]
            ch = chain_for(*obs[tf][r.session], dir_of, link, int(t0f.loc[r.regime_start_ns, f"start_ns_{tf}"]), int(r.terminal_ts))
            if ch is None:
                cpar["no_chain"] += 1
                continue
            starts = np.array([s for s, _ in ch])
            d0 = ch[int(np.searchsorted(starts, r.t0_ns, side="right")) - 1][1]
            inside = [(s, d) for s, d in ch if r.t0_ns < s < r.terminal_ts]
            mine = (int(d0 == r.dir), len(inside), (inside[0][0] - r.t0_ns) / NS if inside else np.nan)
            want = (getattr(r, f"aligned_T0_{tf}"), getattr(r, f"n_trans_{tf}"), getattr(r, f"t_first_trans_{tf}"))
            cpar["compared"] += 1
            ok = mine[0] == want[0] and mine[1] == want[1] and ((np.isnan(mine[2]) and np.isnan(want[2])) or mine[2] == want[2])
            cpar["mismatch"] += int(not ok)
            for s, d in ch:
                chain_rows.append({"regime_start_ns": r.regime_start_ns, "tf": tf, "start_ns": s, "dir": int(d)})
    t_chain = time.time() - t_start

    # ---------------- raw 1s pass
    t1 = time.time()
    loader = CausalDataLoader(CATALOG)
    prior = pd.read_parquet(PRIOR_PATH)
    prior_g = dict(tuple(prior.groupby("regime_start_ns")))
    paths, ctx = [], []
    ppar = {"trades": 0, "path_mismatch": 0, "touch_mismatch": 0, "entry_mismatch": 0}
    n_bar_rows = 0
    for sess, part in tl.groupby("session"):
        start = pd.Timestamp(int(part.t0_ns.min()), tz="UTC") - pd.Timedelta(seconds=PRE_S + 5)
        end = pd.Timestamp(int(part.terminal_ts.max()), tz="UTC") + pd.Timedelta(seconds=FWD_S + 5)
        bars = loader.load_bars(BAR_TYPE, start, end)
        n_bar_rows += len(bars)
        ti = np.fromiter((b.ts_init for b in bars), dtype=np.int64, count=len(bars))
        te = np.fromiter((b.ts_event for b in bars), dtype=np.int64, count=len(bars))
        op = np.fromiter((b.open.as_double() for b in bars), dtype=float, count=len(bars))
        hi = np.fromiter((b.high.as_double() for b in bars), dtype=float, count=len(bars))
        lo = np.fromiter((b.low.as_double() for b in bars), dtype=float, count=len(bars))
        cl = np.fromiter((b.close.as_double() for b in bars), dtype=float, count=len(bars))
        vo = np.fromiter((b.volume.as_double() for b in bars), dtype=float, count=len(bars))
        for r in part.itertuples():
            T0, T, d, atr, ep, D = int(r.t0_ns), int(r.terminal_ts), int(r.dir), float(r.atr), float(r.entry_price), int(r.D)
            i0 = int(np.searchsorted(ti, T0, side="right"))
            ppar["entry_mismatch"] += int(op[i0] != ep or int(te[i0]) != int(r.entry_ts))
            iE = int(np.searchsorted(ti, T + FWD_S * NS, side="right"))
            sti = ti[i0:iE]
            gaps = np.diff(np.concatenate([[int(r.entry_ts)], sti]))
            gi = np.flatnonzero(gaps > MAX_GAP_NS)
            n = int(gi[0]) if len(gi) else len(sti)
            sl = slice(i0, i0 + n)
            t = (sti[:n] - T0) // NS
            fx = ((hi[sl] - ep) if d > 0 else (ep - lo[sl])) / atr
            ax = ((ep - lo[sl]) if d > 0 else (hi[sl] - ep)) / atr
            cx = (cl[sl] - ep) * d / atr
            post = sti[:n] >= T
            # parity 1: in-trade rows equal the prior cache
            pg = prior_g.get(r.regime_start_ns)
            k = int((~post).sum())
            ppar["trades"] += 1
            if pg is None or len(pg) != k or not (np.array_equal(pg.t.to_numpy(), t[:k]) and np.allclose(pg.c.to_numpy(), cx[:k], atol=1e-5)
                                                   and np.allclose(pg.hi.to_numpy(), fx[:k], atol=1e-5)):
                ppar["path_mismatch"] += 1
            # parity 2: first touches (kernel price-level arithmetic) before terminal
            for side, xs in (("fav", (0.5, 1.0, 1.5, 2.0, 3.0)), ("adv", (0.5, 1.0))):
                for x in xs:
                    lvl = ep + d * x * atr if side == "fav" else ep - d * x * atr
                    hit = ((hi[sl] >= lvl) if d > 0 else (lo[sl] <= lvl)) if side == "fav" else ((lo[sl] <= lvl) if d > 0 else (hi[sl] >= lvl))
                    idx = np.flatnonzero(hit & ~post)
                    mine = float(t[idx[0]]) if len(idx) else np.nan
                    want = getattr(r, f"t_{side}_{f'{x:.1f}'.replace('.', 'p')}")
                    ppar["touch_mismatch"] += int(not ((np.isnan(mine) and np.isnan(want)) or mine == want))
            # pre-T0 volume baseline (bars closing in (T0 - PRE_S, T0])
            ip = int(np.searchsorted(ti, T0 - PRE_S * NS, side="right"))
            ctx.append({"regime_start_ns": r.regime_start_ns, "pre_vol_per_s": float(vo[ip:i0].sum() / PRE_S),
                        "pre_bars": int(i0 - ip)})
            paths.append(pd.DataFrame({"regime_start_ns": np.int64(r.regime_start_ns), "t": t.astype(np.int32), "hi": fx.astype(np.float32),
                                       "lo": ax.astype(np.float32), "c": cx.astype(np.float32), "v": vo[sl].astype(np.float32), "post": post}))
    p = pd.concat(paths, ignore_index=True)
    t_raw = time.time() - t1
    WORK.mkdir(exist_ok=True)
    OUT.mkdir(exist_ok=True)
    p.to_parquet(WORK / "PATH_EXT.parquet", index=False)
    pd.DataFrame(ctx).to_parquet(WORK / "TRADE_CTX.parquet", index=False)
    pd.DataFrame(chain_rows).to_parquet(WORK / "CHAINS.parquet", index=False)
    audit = {"population": "TRADE_EVENT_TIMELINE of nq_post_entry_path_mechanism_2023 (2023 development sessions only)",
             "final_20pct_loaded": False, "years_touched": [2023], "n_trades": int(tl.shape[0]),
             "raw_1s_bars_loaded": n_bar_rows, "path_rows_written": len(p), "in_trade_rows": int((~p.post).sum()),
             "path_parity_vs_prior_cache_and_timeline": ppar, "chain_parity_vs_timeline": cpar,
             "PASS": ppar["path_mismatch"] == 0 and ppar["touch_mismatch"] == 0 and ppar["entry_mismatch"] == 0 and cpar["mismatch"] == 0,
             "runtime_s": {"chains": round(t_chain, 1), "raw_1s_pass": round(t_raw, 1), "total": round(time.time() - t_start, 1)}}
    (OUT / "EXTRACT_AUDIT.json").write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(audit, indent=1))
    if not audit["PASS"]:
        raise SystemExit("INVALID: parity failed")


if __name__ == "__main__":
    main()
