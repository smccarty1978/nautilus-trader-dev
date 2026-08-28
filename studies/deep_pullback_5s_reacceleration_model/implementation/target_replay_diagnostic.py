"""Independent exhaustive replay of the FROZEN ordered-barrier target over the full
resolved TRAIN population, compared against the as-collected `target_flip_within_horizon`
/ `disposition`.

Frozen research target (SPEC / target_contract / research_decision `asymmetric_ordered_forward_barrier`):
    favorable  = +1.00 * ATR_T  (continuation in the prevailing direction)
    adverse    = -0.75 * ATR_T
    horizon    = 300 s
    entry      = first executable 1s open at/after candidate T   (entry_reference: next_bar_open)
    ATR_T      = frozen candidate-time 1m Wilder ATR (the `atr_t` column)
    bar rule   = FULLY_FORWARD, deadline ts_close <= entry_ts + 300s
    both sides in one bar  -> AMBIGUOUS_FIRST_TOUCH (excluded)
    deadline, no touch, fully observed -> TIMEOUT (binary 0)
    deadline, not fully observed / session-end -> CENSORED (excluded)

This module reads 1s bars straight from the sealed catalog (CausalDataLoader) -- it is a
read-only diagnostic, writes no governed artifact, changes no science.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

import numpy as np
import pandas as pd

NS = 1_000_000_000
FAV_ATR = 1.00
ADV_ATR = 0.75
HORIZON_S = 300
BAR_TYPE = "NQ.XCME-1-SECOND-LAST-EXTERNAL"
CATALOG = Path("data/catalog/NQ_v0_2020_2026")

RUN_DIRS = {
    2021: "studies/deep_pullback_5s_reacceleration_model/runs/20260828_144743_deep_pullback_5s_reacceleration_model_full",
    2022: "studies/deep_pullback_5s_reacceleration_model/runs/20260828_150235_deep_pullback_5s_reacceleration_model_full",
    2023: "studies/deep_pullback_5s_reacceleration_model/runs/20260828_152004_deep_pullback_5s_reacceleration_model_full",
}


def _load_1s_series() -> Dict[str, np.ndarray]:
    from utils.runner.data import CausalDataLoader

    loader = CausalDataLoader(CATALOG)
    ev, op, hi, lo = [], [], [], []
    start = pd.Timestamp("2020-12-20", tz="UTC")
    for wk in range(170):
        a = start + pd.Timedelta(weeks=wk)
        b = a + pd.Timedelta(weeks=1)
        if a.year > 2024:
            break
        bars = loader.load_bars(BAR_TYPE, a, b)
        for bar in bars:
            ev.append(int(bar.ts_event)); op.append(float(bar.open))
            hi.append(float(bar.high)); lo.append(float(bar.low))
        loader.clear_cache()
    order = np.argsort(np.asarray(ev, dtype=np.int64), kind="mergesort")
    return {
        "ts_event": np.asarray(ev, dtype=np.int64)[order],
        "open": np.asarray(op, dtype=np.float64)[order],
        "high": np.asarray(hi, dtype=np.float64)[order],
        "low": np.asarray(lo, dtype=np.float64)[order],
    }


def _replay_one(series, T: int, atr: float, sign: int, session_close_ts: int) -> Dict[str, Any]:
    ev = series["ts_event"]
    i0 = int(np.searchsorted(ev, T, side="left"))          # first bar opening at/after T
    if i0 >= len(ev):
        return {"label": None, "disposition": "CENSORED", "reason": "NO_ENTRY_BAR",
                "entry_ts": None, "entry_price": None, "fav_ts": None, "adv_ts": None}
    entry_ts = int(ev[i0])
    entry_price = float(series["open"][i0])
    deadline = entry_ts + HORIZON_S * NS
    i1 = int(np.searchsorted(ev, deadline, side="right"))   # ts_close <= deadline  <=>  ts_event <= deadline - 1s ; use ts_event < deadline
    # a bar with ts_event = e closes at e + 1s; require e + 1s <= deadline  ->  e <= deadline - NS
    i1 = int(np.searchsorted(ev, deadline - NS, side="right"))
    hi = series["high"][i0:i1]
    lo = series["low"][i0:i1]
    evw = ev[i0:i1]
    if sign > 0:
        favorable = hi - entry_price
        adverse = entry_price - lo
    else:
        favorable = entry_price - lo
        adverse = hi - entry_price
    hit_fav = favorable >= FAV_ATR * atr
    hit_adv = adverse >= ADV_ATR * atr
    any_hit = hit_fav | hit_adv
    session_censored = (entry_ts + HORIZON_S * NS) > session_close_ts if session_close_ts else False

    if any_hit.any():
        k = int(np.argmax(any_hit))
        f, a = bool(hit_fav[k]), bool(hit_adv[k])
        touch_ts = int(evw[k]) + NS
        if f and a:
            return {"label": None, "disposition": "AMBIGUOUS_FIRST_TOUCH", "reason": "SAME_BAR",
                    "entry_ts": entry_ts, "entry_price": entry_price,
                    "fav_ts": touch_ts, "adv_ts": touch_ts}
        if f:
            return {"label": 1, "disposition": "SUCCESS", "reason": "FAVORABLE_FIRST",
                    "entry_ts": entry_ts, "entry_price": entry_price,
                    "fav_ts": touch_ts, "adv_ts": None}
        return {"label": 0, "disposition": "FAILURE", "reason": "ADVERSE_FIRST",
                "entry_ts": entry_ts, "entry_price": entry_price,
                "fav_ts": None, "adv_ts": touch_ts}

    # no touch within the window
    fully_observed = len(evw) > 0 and int(evw[-1]) + NS >= deadline
    if session_censored or not fully_observed:
        return {"label": None, "disposition": "CENSORED",
                "reason": "SESSION_END" if session_censored else "DATA_GAP_OR_END",
                "entry_ts": entry_ts, "entry_price": entry_price, "fav_ts": None, "adv_ts": None}
    return {"label": 0, "disposition": "TIMEOUT", "reason": "HORIZON_ELAPSED_NO_TOUCH",
            "entry_ts": entry_ts, "entry_price": entry_price, "fav_ts": None, "adv_ts": None}


def run() -> Dict[str, Any]:
    from studies.deep_pullback_5s_reacceleration_model.implementation.train_merge_fit_freeze import (
        KEY, _year_of, merge_train_partitions,
    )

    sd = Path("studies/deep_pullback_5s_reacceleration_model")
    fc = json.loads((sd / "config" / "feature_contract.json").read_text(encoding="utf-8"))
    of = list(fc["feature_list"])
    rd = {y: Path(p) for y, p in RUN_DIRS.items()}
    mi = merge_train_partitions(sd, rd, of)
    cand = mi["merged_candidates"]
    obs = mi["merged_observations"]

    j = cand.merge(
        obs[KEY + ["disposition", "target_flip_within_horizon", "censored", "session_close_ts"]],
        on=KEY, how="inner", validate="one_to_one",
    )
    print(f"[replay] loading 1s series ...", flush=True)
    series = _load_1s_series()
    print(f"[replay] {len(series['ts_event']):,} 1s bars loaded; replaying {len(j):,} rows", flush=True)

    rows = []
    for r in j.itertuples(index=False):
        d = _replay_one(
            series, int(r.candidate_ts), float(r.atr_t),
            1 if int(r.prevailing_direction) == 1 else -1,
            int(r.session_close_ts) if not pd.isna(r.session_close_ts) else 0,
        )
        rows.append({
            "candidate_ts": int(r.candidate_ts),
            "direction": "LONG" if int(r.prevailing_direction) == 1 else "SHORT",
            "atr_t": float(r.atr_t),
            "collected_disposition": r.disposition,
            "collected_label": (None if pd.isna(r.target_flip_within_horizon)
                                else int(r.target_flip_within_horizon)),
            **d,
        })
    rep = pd.DataFrame(rows)

    # binary comparison population: rows the COLLECTOR resolved to 0/1
    collected_resolved = rep[rep["collected_label"].notna()].copy()
    replay_resolved = rep[rep["label"].notna()].copy()

    both = rep[rep["collected_label"].notna() & rep["label"].notna()]
    label_mismatch = both[both["collected_label"] != both["label"]]

    def _dir(df, d):
        return df[df["direction"] == d]

    summary = {
        "rows_replayed": int(len(rep)),
        "LONG_rows": int((rep["direction"] == "LONG").sum()),
        "SHORT_rows": int((rep["direction"] == "SHORT").sum()),
        "collected_resolved_binary_rows": int(len(collected_resolved)),
        "replay_resolved_binary_rows": int(len(replay_resolved)),
        "rows_binary_in_both": int(len(both)),
        "LONG_label_mismatches": int(len(_dir(label_mismatch, "LONG"))),
        "SHORT_label_mismatches": int(len(_dir(label_mismatch, "SHORT"))),
        "total_label_mismatches": int(len(label_mismatch)),
        "disposition_mismatches": int((rep["collected_disposition"] != _canon(rep["disposition"])).sum()),
        "collected_disposition_counts": rep["collected_disposition"].value_counts().to_dict(),
        "replay_disposition_counts": rep["disposition"].value_counts().to_dict(),
        "collected_positive_rate": float(collected_resolved["collected_label"].mean()),
        "replay_positive_rate": float(replay_resolved["label"].mean()),
        "collected_pos_rate_LONG": float(_dir(collected_resolved, "LONG")["collected_label"].mean()),
        "collected_pos_rate_SHORT": float(_dir(collected_resolved, "SHORT")["collected_label"].mean()),
        "replay_pos_rate_LONG": float(_dir(replay_resolved, "LONG")["label"].mean()),
        "replay_pos_rate_SHORT": float(_dir(replay_resolved, "SHORT")["label"].mean()),
        "censoring_only_collected": int((rep["collected_label"].isna() & rep["label"].notna()).sum()),
        "censoring_only_replay": int((rep["label"].isna() & rep["collected_label"].notna()).sum()),
    }

    out_dir = sd / "artifacts"
    rep.to_parquet(out_dir / "target_replay_full.parquet")
    # deterministic audit sample: first 50 LONG + 50 SHORT by candidate_ts
    audit = pd.concat([
        _dir(rep, "LONG").sort_values("candidate_ts").head(50),
        _dir(rep, "SHORT").sort_values("candidate_ts").head(50),
    ])
    audit.to_csv(out_dir / "target_replay_audit_sample.csv", index=False)

    verdict = "BLOCK_OOS" if (summary["total_label_mismatches"] > 0
                              or summary["disposition_mismatches"] > 0) else "CLEAR"
    result = {"summary": summary, "verdict": verdict,
              "artifacts": ["artifacts/target_replay_full.parquet",
                            "artifacts/target_replay_audit_sample.csv"]}
    (out_dir / "target_replay_diagnostic.json").write_text(
        json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8")
    return result


def _canon(disp: pd.Series) -> pd.Series:
    m = {"SUCCESS": "LABELED_POSITIVE", "FAILURE": "LABELED_NEGATIVE",
         "TIMEOUT": "LABELED_NEGATIVE", "CENSORED": "CENSORED",
         "AMBIGUOUS_FIRST_TOUCH": "AMBIGUOUS"}
    return disp.map(m)


if __name__ == "__main__":
    import sys

    r = run()
    json.dump(r, sys.stdout, indent=2, default=str)
    print()
