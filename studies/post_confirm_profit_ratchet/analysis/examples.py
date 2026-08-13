"""Phase 8 path examples, selected by frozen rules -- never hand-picked.

The selection cell is fixed in SPEC 8 before any result was seen: rung 2.0, step
0.50, architecture HWM, D = 0.50, basis POST_CONFIRM. Within each category the
three exhibits are the 25th/50th/75th percentile of that category's own ranking
variable, so the set is deterministic and reproducible, and no exhibit was chosen
because it made a point.

Each exhibit carries its causal path from the rung bar to the terminal, sampled
every 15 s, with the stop level that WOULD have been live on each bar -- computed
from the previous bar's high-water mark, the same reference the policy uses.
"""
from __future__ import annotations

import numpy as np
import polars as pl

from studies.model_driven_entry_exit_discovery.implementation.engine import (
    load_market, load_regimes,
)
from studies.top10_fast_confirm_runner_path.implementation.build import (
    confirmed_population,
)
from studies.post_confirm_profit_ratchet.implementation.rungs import (
    BASIS_POST, build_trade,
)
from .phases import OUT, _write

CELL = {"rung": 2.0, "step": 0.50, "arch": "HWM", "D": 0.50}
SAMPLE_S = 15


def categories(j: pl.DataFrame) -> dict[str, pl.DataFrame]:
    suc = j.filter(pl.col("outcome") == "SUCCESS")
    fail = j.filter(pl.col("outcome") == "FAIL")
    stopped_fail = fail.filter(pl.col("policy_exit_kind") == "RATCHET")
    lo_q = suc["mae_from_hwm_atr"].quantile(0.10)
    hi_q = suc["mae_from_hwm_atr"].quantile(0.90)
    gb_hi = stopped_fail["delta_atr"].quantile(0.75)
    gb_lo = stopped_fail["delta_atr"].quantile(0.25)
    r3 = j.filter(pl.col("eventual_max_mfe_atr") >= 3.0)
    return {
        "SUCCESS_TINY_RETRACEMENT": (suc.filter(pl.col("mae_from_hwm_atr") <= lo_q),
                                     "mae_from_hwm_atr"),
        "SUCCESS_LARGE_RETRACEMENT": (suc.filter(pl.col("mae_from_hwm_atr") >= hi_q),
                                      "mae_from_hwm_atr"),
        "FAIL_CAUGHT_WELL": (stopped_fail.filter(pl.col("delta_atr") >= gb_hi),
                             "delta_atr"),
        "FAIL_NOT_HELPED": (stopped_fail.filter(pl.col("delta_atr") <= gb_lo),
                            "delta_atr"),
        "RUNNER_3ATR_DESTROYED": (r3.filter(~pl.col("runner_survived_3_0")),
                                  "eventual_max_mfe_atr"),
        "RUNNER_3ATR_PRESERVED": (r3.filter(pl.col("runner_survived_3_0")),
                                  "eventual_max_mfe_atr"),
    }


def path_rows(rt, X: float, D: float, label: str, rank: str) -> list[dict]:
    w = rt.w
    r = rt.rung_index(X, BASIS_POST)
    if r < 0:
        return []
    e = rt.exit_index(r, D, "HWM", X)
    ts0 = int(w.ts[r])
    out = []
    k = r
    while k <= w.unc_i:
        out.append({
            "category": label, "rank": rank,
            "regime_id": rt.meta["regime_id"], "entry_year": rt.meta["entry_year"],
            "side": rt.meta["side"], "rung_atr": X, "stop_d": D,
            "secs_from_rung": float((int(w.ts[k]) - ts0) / 1e9),
            "bar_idx": int(k),
            "mark_atr": float(w.mark[k]),
            "bar_high_atr": float(w.bar_hi[k]),
            "bar_low_atr": float(w.bar_lo[k]),
            "hwm_prev_atr": (float(rt.hwm_prev[k])
                             if np.isfinite(rt.hwm_prev[k]) else None),
            "live_stop_level_atr": (float(rt.hwm_prev[k] - D)
                                    if np.isfinite(rt.hwm_prev[k]) else None),
            "is_rung_bar": bool(k == r),
            "is_ratchet_exit_bar": bool(e >= 0 and k == e),
            "is_terminal_bar": bool(k == w.unc_i),
            "eventual_max_mfe_atr": rt.meta["eventual_max_mfe_atr"],
            "baseline_return_atr": rt.meta["baseline_return_atr"],
        })
        if k == w.unc_i:
            break
        nxt = int(np.searchsorted(w.ts, int(w.ts[k]) + SAMPLE_S * 1_000_000_000))
        # always include the exit and terminal bars even if off the sample grid
        for special in (e, w.unc_i):
            if special is not None and k < special < nxt:
                nxt = special
        k = min(max(nxt, k + 1), w.unc_i)
    return out


def main() -> None:
    X, D = CELL["rung"], CELL["D"]
    xd = pl.read_parquet(OUT / "rung_transitions.parquet").filter(
        (pl.col("basis") == BASIS_POST) & (pl.col("step_atr") == CELL["step"])
        & (pl.col("rung_atr") == X))
    cd = pl.read_parquet(OUT / "ratchet_economics.parquet").filter(
        (pl.col("rung_atr") == X) & (pl.col("stop_d") == D)
        & (pl.col("architecture") == CELL["arch"]) & pl.col("achieved"))
    j = xd.join(cd, on=["regime_id", "rung_atr"], how="inner")

    picks = []
    for label, (sub, rank_col) in categories(j).items():
        if sub.height == 0:
            picks.append({"category": label, "rank": "NONE", "regime_id": None})
            continue
        s = sub.sort(rank_col)
        for q, nm in ((0.25, "p25"), (0.50, "p50"), (0.75, "p75")):
            i = min(int(q * (s.height - 1)), s.height - 1)
            picks.append({"category": label, "rank": nm,
                          "regime_id": s["regime_id"][i]})
    pk = pl.DataFrame(picks)
    _write(pk, "path_examples_index")

    ids = set(pk["regime_id"].drop_nulls().to_list())
    market, regimes = load_market(), load_regimes()
    conf = confirmed_population().filter(pl.col("regime_id").is_in(list(ids)))
    lut = {r["regime_id"]: [] for r in picks if r["regime_id"] is not None}
    for r in picks:
        if r["regime_id"] is not None:
            lut[r["regime_id"]].append((r["category"], r["rank"]))

    rows = []
    for tr in conf.iter_rows(named=True):
        rt = build_trade(market, regimes, tr)
        if rt is None:
            continue
        rt.build_exit_tables()
        for label, rank in lut.get(tr["regime_id"], []):
            rows.append(path_rows(rt, X, D, label, rank))
    flat = [r for grp in rows for r in grp]
    _write(pl.DataFrame(flat), "path_examples")


if __name__ == "__main__":
    main()
