"""Machine evaluation of the frozen advancement gates and terminal labels."""
from __future__ import annotations

import numpy as np
import polars as pl

from ..implementation.common import COST_POINTS, RESULTS
from ..implementation.train import monotonicity


def _spearman(v: np.ndarray) -> tuple[float | None, int | None]:
    """Rank correlation of BUCKET TIGHTNESS against the metric, plus inversions.

    `v` arrives ordered LOOSEST -> TIGHTEST (top_50 ... top_1), so tightness is
    simply the position index. A model that concentrates the outcome scores +1
    with 0 inversions; a perfectly anti-monotone model scores -1.

    The first implementation reversed the tightness axis and counted a DECREASE
    from tight to loose as an inversion, which made both quantities read backwards
    -- a maximally bad model would have passed A-1/B-2. It changed no verdict here
    (both models fail either way) but it is a gate defect, so it is fixed and the
    orientation is pinned by `test_gate_orientation`.
    """
    v = np.asarray(v, dtype=float)
    if v.size < 3 or np.isnan(v).any():
        return None, None
    tight = np.arange(v.size, dtype=float)
    rx = np.argsort(np.argsort(tight)).astype(float)
    ry = np.argsort(np.argsort(v)).astype(float)
    return float(np.corrcoef(rx, ry)[0, 1]), int(np.sum(np.diff(v) < 0))


def model_a_gates() -> dict:
    a = pl.read_csv(RESULTS / "model_a_bucket_performance.csv", infer_schema_length=10000)
    abl = pl.read_csv(RESULTS / "_model_a_ablation.csv", infer_schema_length=10000)
    pred = pl.read_parquet(RESULTS / "model_a_oos_predictions.parquet")
    out = {}
    for prime in ("P80", "P90"):
        t = a.filter((pl.col("prime") == prime) & (pl.col("scope") == "POOLED"))
        tail = t.filter(pl.col("bucket") != "all")
        base = float(t.filter(pl.col("bucket") == "all")["win_pct"][0])
        sp, inv = _spearman(tail["win_pct"].to_numpy())
        top10 = float(tail.filter(pl.col("bucket") == "top_10")["win_pct"][0])
        top5 = float(tail.filter(pl.col("bucket") == "top_5")["win_pct"][0])
        n5 = int(tail.filter(pl.col("bucket") == "top_5")["n"][0])

        folds = {}
        for f in ("FOLD_1", "FOLD_2"):
            tf = a.filter((pl.col("prime") == prime) & (pl.col("scope") == f))
            if tf.height == 0:
                folds[f] = None
                continue
            bf = float(tf.filter(pl.col("bucket") == "all")["win_pct"][0])
            t10 = tf.filter(pl.col("bucket") == "top_10")
            folds[f] = (float(t10["win_pct"][0]) - bf) if t10.height else None
        sides = {}
        for s in ("LONG", "SHORT"):
            tsd = a.filter((pl.col("prime") == prime) & (pl.col("scope") == s))
            if tsd.height == 0:
                sides[s] = None
                continue
            bs = float(tsd.filter(pl.col("bucket") == "all")["win_pct"][0])
            t10 = tsd.filter(pl.col("bucket") == "top_10")
            sides[s] = (float(t10["win_pct"][0]) - bs) if t10.height else None

        # A-5 economics with a bootstrap CI on the top-10% net payoff.
        p = pred.filter((pl.col("prime_type") == prime) & pl.col("has_oos"))
        pr = p["oos_prob"].to_numpy()
        k = max(1, int(round(0.10 * pr.size)))
        sel = np.argsort(-pr, kind="stable")[:k]
        lab = p["label_300"].to_numpy()[sel]
        atr = p["frozen_atr"].to_numpy()[sel]
        val = np.where(lab == "WIN", 1.0, np.where(lab == "LOSS", -0.5, 0.0)) - COST_POINTS / atr
        rng = np.random.default_rng(20260811)
        draws = rng.choice(val, size=(1000, val.size), replace=True).mean(axis=1)
        ci = (float(np.quantile(draws, 0.025)), float(np.quantile(draws, 0.975)))
        base_net = float(t.filter(pl.col("bucket") == "all")["expected_net_atr"][0])
        top10_net = float(tail.filter(pl.col("bucket") == "top_10")["expected_net_atr"][0])

        ab = abl.filter(pl.col("prime") == prime)
        auc = {r["ablation"]: r["auc_pooled_oos"] for r in ab.iter_rows(named=True)}
        best_single = max(auc.get("ABL_MARKET", 0) or 0, auc.get("ABL_STATE", 0) or 0)

        g = {
            "A-1 MONOTONIC": {"spearman": sp, "inversions": inv,
                              "threshold": "spearman>=0.80 and inversions<=1",
                              "passed": bool(sp is not None and sp >= 0.80 and inv <= 1)},
            "A-2 TAIL": {"baseline_win_pct": base, "top10_win_pct": top10,
                         "top5_win_pct": top5, "top10_lift_pp": top10 - base,
                         "top5_lift_pp": top5 - base, "threshold": ">=+5.0pp both",
                         "passed": bool(top10 - base >= 5.0 and top5 - base >= 5.0)},
            "A-3 BOTH FOLDS": {"fold_top10_lift_pp": folds, "threshold": "both >0",
                               "passed": bool(all(v is not None and v > 0
                                                  for v in folds.values()))},
            "A-4 DIRECTION": {"side_top10_lift_pp": sides,
                              "threshold": "neither below its own baseline",
                              "passed": bool(all(v is not None and v >= 0
                                                 for v in sides.values()))},
            "A-5 ECONOMICS": {"baseline_net_atr": base_net, "top10_net_atr": top10_net,
                              "ci95": ci, "threshold": ">0, >baseline, CI_lo>0",
                              "passed": bool(top10_net > 0 and top10_net > base_net
                                             and ci[0] > 0)},
            "A-6 SAMPLE": {"top5_n": n5, "threshold": ">=30", "passed": bool(n5 >= 30)},
        }
        # A-7 has TWO satisfying clauses in SPEC 10 and both must be implemented:
        # the combined model materially beats either family, OR one family alone
        # already clears A-1..A-6 (i.e. the extra families are simply unnecessary).
        # Implementing only the first clause makes the gate unpassable for a model
        # whose single family is already sufficient -- a latent defect, flagged by
        # contract-checker W3. It did not change this run (nothing clears A-1..A-6).
        sufficient = all(g[k]["passed"] for k in
                         ("A-1 MONOTONIC", "A-2 TAIL", "A-3 BOTH FOLDS",
                          "A-4 DIRECTION", "A-5 ECONOMICS", "A-6 SAMPLE"))
        combined_lift = (auc.get("ABL_ALL") or 0) - best_single
        g["A-7 FAMILIES"] = {
            "auc": auc, "best_single": best_single,
            "combined_minus_best": combined_lift,
            "clause_combined_beats_best_by_0_02": bool(combined_lift >= 0.02),
            "clause_single_family_already_sufficient": bool(sufficient),
            "threshold": ">=0.02 OR one family already passes A1-A6",
            "passed": bool(combined_lift >= 0.02 or sufficient)}
        out[prime] = {"gates": g, "n_passed": sum(v["passed"] for v in g.values()),
                      "all_passed": all(v["passed"] for v in g.values())}
    return out


def model_b_gates() -> dict:
    b = pl.read_csv(RESULTS / "model_b_bucket_performance.csv", infer_schema_length=10000)
    abl = pl.read_csv(RESULTS / "_model_b_ablation.csv", infer_schema_length=10000)
    pred = pl.read_parquet(RESULTS / "model_b_oos_predictions.parquet")
    p = pred.filter(pl.col("has_oos"))
    pr = p["oos_prob"].to_numpy()
    lab = p["lab_f050_a075_300"].to_numpy()
    trades = p["regime_id"].to_numpy()
    order = np.argsort(-pr, kind="stable")
    k = max(1, int(round(0.10 * pr.size)))
    top, bot = order[:k], order[-k:]
    succ = (lab == "FAVOURABLE").astype(float)
    sep = 100 * (succ[top].mean() - succ[bot].mean())

    t = b.filter(pl.col("scope") == "POOLED")
    tail = t.filter(pl.col("bucket") != "all")
    sp, inv = _spearman(tail["continuation_success_pct"].to_numpy())

    fold_sep = {}
    for f in ("FOLD_1", "FOLD_2"):
        m = p["oos_fold"].to_numpy() == f
        if m.sum() < 40:
            fold_sep[f] = None
            continue
        prf, sf = pr[m], succ[m]
        o = np.argsort(-prf, kind="stable")
        kk = max(1, int(round(0.10 * prf.size)))
        fold_sep[f] = 100 * (sf[o[:kk]].mean() - sf[o[-kk:]].mean())

    # B-4: bottom-decile CONTINUE vs EXIT-NOW.
    nat = p["nat_terminal_return_atr"].to_numpy()
    mfe = p["current_mfe_atr"].to_numpy()
    diff = nat[bot] - mfe[bot]
    rng = np.random.default_rng(20260811)
    u, invm = np.unique(trades[bot], return_inverse=True)
    parts = [diff[invm == i] for i in range(u.size)]
    draws = np.array([np.concatenate([parts[i] for i in rng.integers(0, u.size, u.size)]).mean()
                      for _ in range(1000)])
    ci = (float(np.quantile(draws, 0.025)), float(np.quantile(draws, 0.975)))

    # B-5: does the separation survive stratification?
    strat = {}
    for scope in [s for s in b["scope"].unique().to_list()
                  if s.startswith(("RUNG_", "SINCECONF_"))]:
        tt = b.filter(pl.col("scope") == scope)
        a10 = tt.filter(pl.col("bucket") == "top_10")
        a0 = tt.filter(pl.col("bucket") == "all")
        if a10.height and a0.height:
            strat[scope] = float(a10["continuation_success_pct"][0]
                                 - a0["continuation_success_pct"][0])
    side_sep = {}
    for s in ("LONG", "SHORT"):
        tt = b.filter(pl.col("scope") == s)
        a10 = tt.filter(pl.col("bucket") == "top_10")
        a0 = tt.filter(pl.col("bucket") == "all")
        if a10.height and a0.height:
            side_sep[s] = float(a10["continuation_success_pct"][0]
                                - a0["continuation_success_pct"][0])
    min_trades = int(tail["n_unique_trades"].min())
    auc = {r["ablation"]: r["auc_pooled_oos"] for r in abl.iter_rows(named=True)}

    g = {
        "B-1 SEPARATION": {"top_minus_bottom_decile_pp": sep, "threshold": ">=15pp",
                           "passed": bool(sep >= 15.0)},
        "B-2 MONOTONIC": {"spearman": sp, "inversions": inv,
                          "threshold": "spearman>=0.80 and inversions<=1",
                          "passed": bool(sp is not None and sp >= 0.80 and inv <= 1)},
        "B-3 BOTH FOLDS": {"fold_separation_pp": fold_sep, "threshold": "both >=15pp",
                           "passed": bool(all(v is not None and v >= 15.0
                                              for v in fold_sep.values()))},
        "B-4 ECONOMICS": {"bottom_decile_continue_minus_exit_atr": float(diff.mean()),
                          "ci95_trade_clustered": ci, "threshold": "<0 with CI excluding 0",
                          "passed": bool(diff.mean() < 0 and ci[1] < 0)},
        "B-5 NOT-COMPOSITION": {"stratified_top10_lift_pp": strat,
                                "threshold": "positive in every stratum",
                                "passed": bool(strat and all(v > 0 for v in strat.values()))},
        "B-6 BOTH SIDES": {"side_top10_lift_pp": side_sep, "threshold": "same sign",
                           "passed": bool(side_sep and
                                          len({np.sign(v) for v in side_sep.values()}) == 1
                                          and all(v > 0 for v in side_sep.values()))},
        "B-7 SAMPLE": {"min_bucket_unique_trades": min_trades, "threshold": ">=20",
                       "passed": bool(min_trades >= 20)},
    }
    return {"gates": g, "auc": auc, "n_passed": sum(v["passed"] for v in g.values()),
            "all_passed": all(v["passed"] for v in g.values()),
            "baseline_success_pct": float(t.filter(pl.col("bucket") == "all")
                                          ["continuation_success_pct"][0])}


def terminal_labels(ga: dict, gb: dict, invalid: bool) -> dict:
    if invalid:
        return {"model_a": "A4 INVALID / CAUSAL OR DATA FAILURE",
                "model_b": "B4 INVALID / CAUSAL OR DATA FAILURE",
                "program": "WITHHELD -- a CRITICAL survives"}
    best = max(ga.values(), key=lambda x: x["n_passed"])
    a1 = any(v["all_passed"] for v in ga.values())
    a_any = any(v["gates"]["A-1 MONOTONIC"]["passed"] or v["gates"]["A-2 TAIL"]["passed"]
                for v in ga.values())
    a = ("A1 STRONG SIGNAL — EXPAND STUDY" if a1 else
         "A2 WEAK BUT PLAUSIBLE — FEATURE/DEFINITION WORK WARRANTED" if a_any else
         "A3 NO USEFUL SIGNAL")
    b1 = gb["all_passed"]
    b_any = gb["gates"]["B-1 SEPARATION"]["passed"] or gb["gates"]["B-2 MONOTONIC"]["passed"]
    bl = ("B1 STRONG SIGNAL — EXPAND STUDY" if b1 else
          "B2 WEAK BUT PLAUSIBLE — FEATURE/DEFINITION WORK WARRANTED" if b_any else
          "B3 NO USEFUL SIGNAL")
    prog = ("P3 BOTH WARRANT FULL DEVELOPMENT" if a1 and b1 else
            "P1 ENTRY OPPORTUNITY MODEL IS THE PRIORITY" if a1 else
            "P2 CONTINUATION MODEL IS THE PRIORITY" if b1 else
            "P4 NEITHER WARRANTS EXPANSION")
    return {"model_a": a, "model_b": bl, "program": prog,
            "model_a_best_prime": max(ga, key=lambda k: ga[k]["n_passed"]),
            "model_a_gates_passed": {k: v["n_passed"] for k, v in ga.items()},
            "model_b_gates_passed": gb["n_passed"]}
