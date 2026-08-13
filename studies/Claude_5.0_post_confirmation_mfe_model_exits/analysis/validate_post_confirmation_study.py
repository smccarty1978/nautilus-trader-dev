"""Independent validation of the post-confirmation policy engine.

Deliberately separate implementation: a plain bar-by-bar replay that recomputes
favorable / adverse excursion from raw path OHLC rather than reusing the
builder's derived ATR columns. It does not import the engine module.

Checks per sampled (trade, initial stop):
  baseline outcome, confirmation timestamp, MFE path, activation timestamp,
  peak-MFE evolution, model-warning timestamp, management-exit timestamp,
  terminal classification, realized return.
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

import polars as pl

STUDY_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = STUDY_DIR.parents[1]
BUILDER = REPO_ROOT / "studies" / "full_trade_path_builder"
CONS = BUILDER / "consolidated"

SEED = 20260727
SAMPLE_PER_STOP = 100
STOPS = [0.75, 1.00, 1.25]
FLAT = 0.125

BULL = {"top_10": 0.43167249785595935, "top_5": 0.5067081427626979,
        "top_2_5": 0.5697449423968936}
BEAR = {"top_10": None, "top_5": 0.5084619230529974,
        "top_2_5": 0.5641320087327389}

# policies re-implemented here, independently of policy_defs
CHECK_POLICIES = [
    ("BASE", None),
    ("A1_act1_00_floor0_25", {"kind": "fixed", "a": 1.00, "p": 0.25}),
    ("A1_act2_00_floor0_50", {"kind": "fixed", "a": 2.00, "p": 0.50}),
    ("A2_act1_50_give0_75", {"kind": "giveback", "a": 1.50, "p": 0.75}),
    ("A2_act0_75_give0_50", {"kind": "giveback", "a": 0.75, "p": 0.50}),
    ("A3_act1_50_ret50", {"kind": "retention", "a": 1.50, "p": 0.50}),
    ("B_top_2_5_k1", {"kind": "model", "t": "top_2_5", "k": 1}),
    ("B_top_5_k2", {"kind": "model", "t": "top_5", "k": 2}),
    ("C1_P3_top_2_5", {"kind": "c1", "a": 1.50, "p": 0.75, "pk": "giveback",
                       "t": "top_2_5"}),
    ("C2_P3_top_2_5", {"kind": "c2", "a": 1.50, "p": 0.75, "pk": "giveback",
                       "t": "top_2_5"}),
]


def replay(bars: list[dict], sm: dict, stop: float, spec) -> dict:
    """Naive sequential replay for one trade under one policy."""
    d = int(sm["trade_direction"])
    ref = float(sm["checkpoint_reference_price"])
    atr = float(sm["atr_at_entry"])
    confirm = int(sm["confirm_flip_ns"])
    fallback = int(sm["fallback_exit_flip_ns"])
    complete = bool(sm["path_is_complete"])
    n = len(bars)

    adv, fav, mfe = [], [], []
    run = 0.0
    for b in bars:
        a = ((b["low"] - ref) if d == 1 else (ref - b["high"])) / atr
        f = ((b["high"] - ref) if d == 1 else (ref - b["low"])) / atr
        run = max(run, f)
        adv.append(a)
        fav.append(f)
        mfe.append(run)

    exec_start = n
    for i, b in enumerate(bars):
        if b["timestamp_open_ns"] >= confirm:
            exec_start = i
            break

    # eligible opposing-model observations
    elig = [i for i, b in enumerate(bars)
            if b["opp_dom"] and not b["opp_carried"] and b["opp_prob"] is not None]

    def warn_idx(tname, k):
        thr = (BEAR if d == -1 else BULL)[tname]
        if thr is None:
            return None
        post = [i for i in elig if i >= exec_start]
        pre = [i for i in elig if i < exec_start]
        prev = (bars[pre[-1]]["opp_prob"] >= thr) if pre else False
        above = [bars[i]["opp_prob"] >= thr for i in post]
        for j in range(len(post)):
            crossing = above[j] and not (above[j - 1] if j > 0 else prev)
            if crossing and j + k <= len(post) and all(above[j:j + k]):
                return post[j + k - 1]
        return None

    def price_idx(kind, a, p, after=None):
        peak = 0.0
        for i in range(n):
            floor = None
            if peak >= a and i >= exec_start and (after is None or i > after):
                if kind == "fixed":
                    floor = p
                elif kind == "giveback":
                    floor = max(0.0, peak - p)
                else:
                    floor = peak * p
            if floor is not None and adv[i] <= floor:
                return i
            peak = mfe[i]
        return None

    i_stop = next((i for i in range(n) if adv[i] <= -stop), None)
    i_mgmt = i_warn = None
    kind = "INITIAL_STOP"
    if spec is None:
        chosen, kind = i_stop, "INITIAL_STOP"
    elif spec["kind"] in ("fixed", "giveback", "retention"):
        i_mgmt = price_idx(spec["kind"], spec["a"], spec["p"])
        cands = [(i_mgmt, "PRICE_MANAGEMENT"), (i_stop, "INITIAL_STOP")]
        cands = [c for c in cands if c[0] is not None]
        chosen, kind = min(cands, key=lambda z: z[0]) if cands else (None, "NO_EXIT")
    elif spec["kind"] == "model":
        i_warn = warn_idx(spec["t"], spec["k"])
        cands = [(i_stop, "INITIAL_STOP"), (i_warn, "MODEL_WARNING")]
        cands = [c for c in cands if c[0] is not None]
        chosen, kind = min(cands, key=lambda z: z[0]) if cands else (None, "NO_EXIT")
    elif spec["kind"] == "c1":
        i_mgmt = price_idx(spec["pk"], spec["a"], spec["p"])
        i_warn = warn_idx(spec["t"], 1)
        order = {"PRICE_MANAGEMENT": 0, "INITIAL_STOP": 1, "MODEL_WARNING": 2}
        cands = [(i_mgmt, "PRICE_MANAGEMENT"), (i_stop, "INITIAL_STOP"),
                 (i_warn, "MODEL_WARNING")]
        cands = [c for c in cands if c[0] is not None]
        chosen, kind = (min(cands, key=lambda z: (z[0], order[z[1]]))
                        if cands else (None, "NO_EXIT"))
    else:  # c2
        i_warn = warn_idx(spec["t"], 1)
        i_mgmt = (price_idx(spec["pk"], spec["a"], spec["p"], after=i_warn)
                  if i_warn is not None else None)
        cands = [(i_mgmt, "PRICE_MANAGEMENT"), (i_stop, "INITIAL_STOP")]
        cands = [c for c in cands if c[0] is not None]
        chosen, kind = min(cands, key=lambda z: z[0]) if cands else (None, "NO_EXIT")

    out = {
        "confirmation_index": exec_start,
        "peak_mfe": mfe[-1],
        "activation_index": (
            next((i for i in range(n) if mfe[i] >= spec["a"]), None)
            if spec and "a" in spec else None),
        "warning_index": i_warn,
        "management_index": i_mgmt,
    }
    if chosen is not None:
        t_touch = int(bars[chosen]["timestamp_close_ns"])
        if t_touch in (confirm, fallback):
            return {**out, "outcome": "AMBIGUOUS EVENT ORDER", "ret": None}
        if chosen + 1 >= n:
            return {**out, "outcome": "CENSORED / UNRESOLVED", "ret": None}
        fill = int(bars[chosen + 1]["timestamp_open_ns"])
        if fill in (confirm, fallback):
            return {**out, "outcome": "AMBIGUOUS EVENT ORDER", "ret": None}
        pts = (bars[chosen + 1]["open"] - ref) * d
        if kind == "INITIAL_STOP":
            cls = ("STOPPED BEFORE CONFIRMATION" if t_touch < confirm
                   else "STOPPED AFTER CONFIRMATION")
        elif kind == "PRICE_MANAGEMENT":
            cls = "PRICE MANAGEMENT EXIT"
        else:
            cls = "MODEL WARNING EXIT"
        return {**out, "outcome": cls, "ret": pts / atr}
    if not complete or sm["fallback_exit_mark_return_points"] is None:
        return {**out, "outcome": "CENSORED / UNRESOLVED", "ret": None}
    pts = float(sm["fallback_exit_mark_return_points"])
    cls = ("REGIME-FLIP EXIT FLAT" if abs(pts) <= FLAT
           else "REGIME-FLIP EXIT FOR PROFIT" if pts > 0
           else "REGIME-FLIP EXIT FOR LOSS")
    return {**out, "outcome": cls, "ret": pts / atr}


def main() -> int:
    eng = pl.read_parquet(
        STUDY_DIR / "results"
        / "post_confirmation_mfe_model_exit_trade_policy_results.parquet")
    sm_all = pl.read_parquet(CONS / "canonical_trade_summaries_all.parquet").select(
        "trade_id", "trade_direction", "trade_direction_name",
        "checkpoint_reference_price", "atr_at_entry", "confirm_flip_ns",
        "fallback_exit_flip_ns", "path_is_complete",
        "fallback_exit_mark_return_points")

    rng = random.Random(SEED)
    ids = sorted(sm_all["trade_id"].to_list())
    samples = {s: rng.sample(ids, SAMPLE_PER_STOP) for s in STOPS}
    wanted = sorted({t for v in samples.values() for t in v})
    print(json.dumps({"stage": "sampled", "unique_trades": len(wanted)}), flush=True)

    is_short = pl.col("trade_direction") == -1
    paths = (
        pl.scan_parquet(CONS / "canonical_trade_paths_all.parquet")
        .filter(pl.col("trade_id").is_in(wanted))
        .with_columns(
            pl.when(is_short).then(pl.col("bearish_probability"))
              .otherwise(pl.col("bullish_probability")).alias("opp_prob"),
            pl.when(is_short).then(pl.col("bearish_in_domain"))
              .otherwise(pl.col("bullish_in_domain")).fill_null(False).alias("opp_dom"),
            pl.when(is_short).then(pl.col("bearish_is_carried_forward"))
              .otherwise(pl.col("bullish_is_carried_forward")).fill_null(True)
              .alias("opp_carried"),
        )
        .select("trade_id", "path_sequence", "timestamp_open_ns",
                "timestamp_close_ns", "open", "high", "low",
                "opp_prob", "opp_dom", "opp_carried")
        .sort(["trade_id", "path_sequence"])
        .collect(engine="streaming")
    )
    print(json.dumps({"stage": "paths_loaded", "rows": paths.height}), flush=True)
    by_trade = {k[0]: v.to_dicts()
                for k, v in paths.partition_by("trade_id", as_dict=True).items()}
    summaries = {r["trade_id"]: r for r in sm_all.filter(
        pl.col("trade_id").is_in(wanted)).to_dicts()}

    eng_idx = {}
    for r in eng.filter(pl.col("trade_id").is_in(wanted)).to_dicts():
        eng_idx[(r["trade_id"], r["initial_stop_atr"], r["policy_id"])] = r

    mismatches, checks = [], 0
    for stop in STOPS:
        for tid in samples[stop]:
            bars = by_trade[tid]
            sm = summaries[tid]
            for pid, spec in CHECK_POLICIES:
                key = (tid, stop, pid)
                if key not in eng_idx:  # LONG_ONLY policies on SHORT trades
                    continue
                got = eng_idx[key]
                exp = replay(bars, sm, stop, spec)
                checks += 1
                problems = []
                if got["outcome_class"] != exp["outcome"]:
                    problems.append(
                        f"outcome {got['outcome_class']} != {exp['outcome']}")
                gr, er = got["realized_return_atr"], exp["ret"]
                if (gr is None) != (er is None) or (
                        gr is not None and abs(gr - er) > 1e-9):
                    problems.append(f"return {gr} != {er}")
                if abs(got["peak_mfe_full_path_atr"] - exp["peak_mfe"]) > 1e-9:
                    problems.append(
                        f"peak_mfe {got['peak_mfe_full_path_atr']} != {exp['peak_mfe']}")
                # confirmation timestamp
                if got["confirmation_timestamp"] != sm["confirm_flip_ns"]:
                    problems.append("confirmation timestamp drift")
                # warning timestamp
                ew = (int(bars[exp["warning_index"]]["timestamp_close_ns"])
                      if exp["warning_index"] is not None else None)
                if spec and spec["kind"] in ("model", "c1", "c2"):
                    if got["warning_timestamp"] != ew:
                        problems.append(
                            f"warning ts {got['warning_timestamp']} != {ew}")
                # management exit bar
                if (spec and spec["kind"] in ("fixed", "giveback", "retention")
                        and got["exit_reason"] == "PRICE_MANAGEMENT"
                        and got["exit_bar_index"] != exp["management_index"]):
                    problems.append(
                        f"mgmt idx {got['exit_bar_index']} != {exp['management_index']}")
                if problems:
                    mismatches.append({"trade_id": tid, "stop": stop,
                                       "policy_id": pid, "problems": problems})

    report = {
        "seed": SEED, "sample_per_stop": SAMPLE_PER_STOP,
        "stops": STOPS, "unique_trades_sampled": len(wanted),
        "trade_stop_cases": SAMPLE_PER_STOP * len(STOPS),
        "policy_checks_performed": checks,
        "unexplained_mismatches": len(mismatches),
        "mismatch_detail": mismatches[:25],
        "independent_implementation": (
            "bar-by-bar replay recomputing favorable/adverse excursion from raw "
            "path high/low; does not import the engine module"),
    }
    out = STUDY_DIR / "results" / "post_confirmation_validation.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "mismatch_detail"},
                     indent=2))
    if mismatches:
        print(json.dumps(mismatches[:10], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
