"""Matched placebo entries (P4A/P4B) for the D10 pre-flip entry events.

For each real D10 entry event, sample one donor checkpoint matched on:
direction (exact), year (exact), session RTH/ETH (exact), regime-age bucket,
ATR bucket, current-MFE bucket, giveback bucket — all entry-time causal.
Donor constraints: valid weakness score with score < threshold (not a D10
moment), from a different regime than the real event, strictly before the
donor regime's end (causally pre-flip moment), inside the economics window,
at most one placebo per donor regime. Nothing about the donor regime's
future (duration, outcome, whether it later reaches D10) enters the match.

Placebo entries are executed by the same NT strategy code as real entries
(identical fill/stop/confirmation/exit mechanics).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from studies.fable5_pre_flip_d10_reversal_entry.common import (  # noqa: E402
    ECON_WINDOWS, NS_PER_S, RESULTS, WORK, load_frozen_threshold,
)

AGE_BINS = [0, 60, 180, 420, 900, 1800.01]
MFE_BINS = [-np.inf, 0.25, 0.5, 1.0, 2.0, np.inf]
GB_BINS = [-np.inf, 0.1, 0.25, 0.5, 1.0, np.inf]

# Relaxation ladder: drop the last covariate in the key if a cell is empty.
MATCH_KEYS = ["year", "direction", "rth", "atr_bucket", "age_bucket",
              "mfe_bucket", "gb_bucket"]


def bucketize(df: pd.DataFrame, atr_edges: np.ndarray) -> pd.DataFrame:
    df = df.copy()
    df["age_bucket"] = pd.cut(df["regime_age"], AGE_BINS, labels=False,
                              include_lowest=True)
    df["mfe_bucket"] = pd.cut(df["current_mfe"], MFE_BINS, labels=False)
    df["gb_bucket"] = pd.cut(df["giveback"], GB_BINS, labels=False)
    df["atr_bucket"] = np.clip(
        np.searchsorted(atr_edges, df["atr"].to_numpy(), side="right") - 1,
        0, len(atr_edges) - 2)
    return df


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    rng = np.random.default_rng(args.seed)

    thr = load_frozen_threshold()["threshold"]
    events = pd.read_parquet(RESULTS / "d10_entry_events.parquet")
    scores = pd.read_parquet(WORK / "causal_scores.parquet")
    cov = pd.read_parquet(RESULTS / "regime_d10_coverage.parquet")

    # Donor pool: valid, sub-threshold, in econ window, strictly pre-flip.
    ends = cov.set_index("regime_start_ns")["regime_end_ns"]
    pool = scores[scores["score_valid"] & scores["w4_score"].notna()
                  & (scores["w4_score"] < thr)
                  & scores["in_econ_window"]].copy()
    pool["regime_end_ns"] = pool["regime_start_ns"].map(ends)
    pool = pool[pool["regime_end_ns"].notna()
                & (pool["observation_time"] < pool["regime_end_ns"])]
    pool = pool.rename(columns={"atr": "atr"})
    print(f"Donor pool: {len(pool):,} checkpoints across "
          f"{pool['regime_start_ns'].nunique():,} regimes")

    # ATR quintile edges from the REAL events (entry-time values)
    atr_edges = np.quantile(events["atr_at_d10"].to_numpy(),
                            [0, .2, .4, .6, .8, 1.0])
    atr_edges[-1] = np.inf
    atr_edges[0] = -np.inf

    ev = events.rename(columns={
        "regime_age_at_d10": "regime_age", "atr_at_d10": "atr",
        "old_direction": "direction"})
    ev = bucketize(ev, atr_edges)
    pool = bucketize(pool, atr_edges)

    # Vectorized greedy matching: precompute per-level shuffled donor queues
    # keyed by the first `level` ladder keys; consume with pointers so each
    # event match is O(1) amortized and no donor regime is reused.
    used_regimes: set[int] = set()
    placebos, match_meta = [], []
    order = rng.permutation(len(ev))

    pool = pool.reset_index(drop=True)
    pool_regime = pool["regime_start_ns"].to_numpy()
    perm = rng.permutation(len(pool))
    levels = list(range(len(MATCH_KEYS), 3, -1))  # 7,6,5,4
    key_cols = {lv: pool[MATCH_KEYS[:lv]].to_numpy() for lv in levels}
    queues: dict[int, dict[tuple, list]] = {lv: {} for lv in levels}
    for idx in perm:
        for lv in levels:
            k = tuple(key_cols[lv][idx])
            queues[lv].setdefault(k, []).append(int(idx))
    heads: dict[tuple, int] = {}

    def take(lv: int, key: tuple, own_regime: int):
        q = queues[lv].get(key)
        if q is None:
            return None
        hk = (lv, key)
        i = heads.get(hk, 0)
        # skip donors whose regime is used up or is the event's own regime,
        # but do NOT advance past own-regime rows permanently (they may be
        # valid for other events) — swap them toward the head instead
        while i < len(q):
            ridx = q[i]
            reg = int(pool_regime[ridx])
            if reg in used_regimes:
                i += 1
                continue
            if reg == own_regime:
                # find next valid without consuming this row
                j = i + 1
                while j < len(q):
                    r2 = int(pool_regime[q[j]])
                    if r2 not in used_regimes and r2 != own_regime:
                        q[i], q[j] = q[j], q[i]
                        break
                    j += 1
                if j >= len(q):
                    heads[hk] = i
                    return None
                ridx = q[i]
            heads[hk] = i  # row at i is consumed via used_regimes marking
            return ridx
        heads[hk] = i
        return None

    ev_keys = {lv: ev[MATCH_KEYS[:lv]].to_numpy() for lv in levels}
    for oi in order:
        e = ev.iloc[oi]
        own = int(e["regime_start_ns"])
        chosen, level_used = None, None
        for lv in levels:
            ridx = take(lv, tuple(ev_keys[lv][oi]), own)
            if ridx is not None:
                chosen, level_used = pool.iloc[ridx], lv
                break
        match_meta.append({
            "regime_id": e["regime_id"],
            "matched": chosen is not None,
            "match_level": level_used if chosen is not None else -1,
        })
        if chosen is None:
            continue
        used_regimes.add(int(chosen["regime_start_ns"]))
        placebos.append({
            "placebo_of": e["regime_id"],
            "regime_id": f"{int(chosen['year'])}_{int(chosen['regime_start_ns'])}",
            "year": int(chosen["year"]),
            "old_direction": int(chosen["direction"]),
            "entry_dir": -int(chosen["direction"]),
            "regime_start_ns": int(chosen["regime_start_ns"]),
            "regime_end_ns": int(chosen["regime_end_ns"]),
            "d10_obs_time": int(chosen["observation_time"]),
            "score": float(chosen["w4_score"]),
            "threshold": thr,
            "regime_age_at_d10": float(chosen["regime_age"]),
            "atr_at_d10": float(chosen["atr"]),
            "current_mfe": float(chosen["current_mfe"]),
            "giveback": float(chosen["giveback"]),
            "rth": bool(chosen["rth"]),
            "seed": args.seed,
        })

    plc = pd.DataFrame(placebos)
    meta = pd.DataFrame(match_meta)
    plc.to_parquet(WORK / f"placebo_events_seed{args.seed}.parquet", index=False)

    # Covariate balance report
    bal_rows = []
    for col_e, col_p in [("regime_age", "regime_age_at_d10"),
                         ("atr", "atr_at_d10"),
                         ("current_mfe", "current_mfe"),
                         ("giveback", "giveback")]:
        bal_rows.append({
            "covariate": col_e,
            "real_mean": float(ev[col_e].mean()),
            "placebo_mean": float(plc[col_p].mean()) if len(plc) else np.nan,
            "real_median": float(ev[col_e].median()),
            "placebo_median": float(plc[col_p].median()) if len(plc) else np.nan,
        })
    bal = pd.DataFrame(bal_rows)
    bal.to_parquet(WORK / f"placebo_balance_seed{args.seed}.parquet", index=False)

    print(f"Matched {meta['matched'].sum()}/{len(meta)} events "
          f"(full-key matches: {(meta['match_level'] == len(MATCH_KEYS)).sum()})")
    print(bal.to_string(index=False))


if __name__ == "__main__":
    main()
