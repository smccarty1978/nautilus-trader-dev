"""Build the three panels every table in this study aggregates from.

Nothing downstream recomputes a path. `analysis/` only ever groups these panels,
so a descriptive table cannot disagree with the causal walk that produced it.

The confirmed population is IMPORTED from the accepted study, never re-derived.
Re-deriving it would be a fresh chance to get the `arm_top10_ns` clock or the
integer-nanosecond cohort edges wrong, and both have already cost this program a
population error.

Panels
------
rung_events        trade x rung x basis          (Phase 1)
rung_transitions   rung event x step {0.50,1.00} (Phases 2-4)
ratchet_economics  trade x rung x D x arch       (Phases 5-7), POST_CONFIRM only,
                   each row carrying its three matched placebos
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import polars as pl

from studies.model_driven_entry_exit_discovery.implementation.engine import (
    COST_POINTS, load_market, load_regimes,
)
from studies.top10_fast_confirm_runner_path.implementation.build import (
    confirmed_population,
)
from studies.top10_fast_confirm_runner_path.implementation.engine import STOP_ATR
from .rungs import (
    ARCHITECTURES, BASIS_ENTRY, BASIS_POST, DENSE_OFFSETS_S, N_PLACEBO, RUNGS,
    RUNNER_TIERS, SEED, STEPS, STOP_DISTANCES, build_trade, tag,
)

ROOT = Path(__file__).resolve().parents[3]
STORE = ROOT / "data/canonical/regime_complete_v1"
ARMED = ROOT / "studies/armed_fade_score_path_progression/results/armed_regime_score_paths.parquet"
OUT = ROOT / "studies/post_confirm_profit_ratchet/results"

N_ENTRIES = 8950
ACCEPTED = {"entries": 8950, "confirmed": 4705, "stopped_before": 4245,
            "measurable": 4656, "non_measurable": 49,
            "pool_per_entry": 0.89808, "baseline_per_entry": -0.07653}
# The accepted P(next +0.50) ladder, FROM_ENTRY basis. Gate 3 reproduces it.
ACCEPTED_LADDER = {1.0: 0.8069712, 1.5: 0.8007743, 2.0: 0.7919762,
                   2.5: 0.8149016, 3.0: 0.8008037, 4.0: 0.8042328}


def placebo_armings(rt, rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    """The two placebo arming vectors for one trade (SPEC D8).

    Drawn ONCE per trade and reused across all 126 cells, which makes every
    policy-vs-placebo comparison paired rather than independently noisy.

    P_BLIND draws a GRID OFFSET, not an index: it cannot know how long the trade
    will live. If the offset lands past the trade's own stop-live terminal the
    rule never arms, exactly as a live rule would experience it. A placebo drawn
    over the REALISED lifetime is itself look-ahead -- that defect inverted an
    accepted study's headline in this repository once already, which is why
    P_UNIFORM below is labelled FUTURE_INFORMATION everywhere it appears.
    """
    w = rt.w
    blind = np.full(N_PLACEBO, -1, dtype=np.int64)
    for i, L in enumerate(rng.choice(np.array(DENSE_OFFSETS_S), size=N_PLACEBO)):
        j = w.index_at_offset(int(L))
        if 0 <= j <= w.nat_i:
            blind[i] = j
    if w.nat_i > w.ci:
        unif = rng.integers(w.ci, w.nat_i, size=N_PLACEBO).astype(np.int64)
    else:
        unif = np.full(N_PLACEBO, w.ci, dtype=np.int64)
    return blind, unif


def economics_rows(rt, rung_idx: dict, blind: np.ndarray,
                   unif: np.ndarray) -> list[dict]:
    """All 126 (rung x D x architecture) cells for one trade, with placebos."""
    w = rt.w
    uncond = np.array([w.ci if w.ci <= w.nat_i else -1], dtype=np.int64)
    base = float(rt.nat_ret)
    key = {k: rt.meta[k] for k in ("regime_id", "entry_year", "side",
                                   "runner_bucket", "eventual_max_mfe_atr",
                                   "nat_kind", "entry_atr", "cost_atr")}
    rows = []
    for X in RUNGS:
        r = rung_idx.get(X, -1)
        for D in STOP_DISTANCES:
            for arch in ARCHITECTURES:
                if r < 0:
                    # Trade never earned this rung: it is a non-participant and
                    # contributes a zero delta, NOT an omission. Dropping it
                    # would silently change the 8,950 denominator.
                    rows.append({**key, "rung_atr": X, "stop_d": D,
                                 "architecture": arch, "achieved": False,
                                 "participated": False, "stop_live_reachable": False,
                                 "baseline_return_atr": base,
                                 "policy_return_atr": base, "delta_atr": 0.0,
                                 "policy_exit_kind": "NOT_ACHIEVED",
                                 "policy_exit_idx": -1, "secs_exit_before_baseline": None,
                                 "blind_return_atr": base, "uncond_return_atr": base,
                                 "uniform_return_atr": base,
                                 "d_blind": 0.0, "d_uncond": 0.0, "d_uniform": 0.0,
                                 **{f"runner_survived_{tag(T)}": None
                                    for T in RUNNER_TIERS}})
                    continue

                p = rt.policy(r, D, arch, X)
                e = p["policy_exit_idx"] if p["policy_exit_kind"] == "RATCHET" else -1
                # UNCONSTRAINED trigger (SPEC D1): the bar at which this stop
                # WOULD fire on the stop-released path. Phases 1-5 are
                # descriptive and must not be truncated by the accepted 1 ATR
                # stop -- "would a stop of distance D have survived this path" is
                # undefined if a different stop already ended the path. This is
                # the ONLY exit the Phase 5 frontier may read; Phases 6-7
                # economics read `policy_exit_idx`, which is stop-live gated.
                unc_e = rt.exit_index(r, D, arch, X)
                pol = float(p["policy_return_atr"])
                b = float(rt.returns_for_armings(blind, D, arch, X).mean())
                u = float(rt.returns_for_armings(uncond, D, arch, X).mean())
                q = float(rt.returns_for_armings(unif, D, arch, X).mean())
                rows.append({
                    **key, "rung_atr": X, "stop_d": D, "architecture": arch,
                    "achieved": True,
                    "participated": bool(p["participated"]),
                    "stop_live_reachable": bool(r <= w.nat_i),
                    "baseline_return_atr": base,
                    "policy_return_atr": pol,
                    "delta_atr": pol - base,
                    "policy_exit_kind": p["policy_exit_kind"],
                    "policy_exit_idx": int(p["policy_exit_idx"]),
                    "unc_exit_idx": int(unc_e),
                    "unc_stopped": bool(unc_e >= 0),
                    "secs_exit_before_baseline": float(
                        (int(w.ts[w.nat_i]) - int(w.ts[p["policy_exit_idx"]])) / 1e9),
                    "blind_return_atr": b, "uncond_return_atr": u,
                    "uniform_return_atr": q,
                    "d_blind": b - base, "d_uncond": u - base, "d_uniform": q - base,
                    **{f"runner_survived_{tag(T)}": rt.runner_survived(e, T)
                       for T in RUNNER_TIERS},
                })
    return rows


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    print("loading market/regimes ...", flush=True)
    market, regimes = load_market(), load_regimes()
    conf = confirmed_population()
    print(f"  confirmed rows: {conf.height:,}", flush=True)
    assert conf.height == ACCEPTED["confirmed"], conf.height

    # 2026 is sealed at the SOURCE, before a single walk runs -- not asserted
    # after the fact, when the read would already have happened.
    years = sorted(conf["entry_year"].unique().to_list())
    assert 2026 not in years, f"2026 leaked into the population: {years}"

    rng = np.random.default_rng(SEED)
    trades, events, trans, econ, dropped = [], [], [], [], []
    for n, tr in enumerate(conf.iter_rows(named=True), 1):
        rt = build_trade(market, regimes, tr)
        if rt is None:
            dropped.append({"regime_id": tr["regime_id"],
                            "terminal_label": tr["terminal_label"],
                            "entry_year": tr["entry_year"]})
            continue
        rt.build_exit_tables()
        trades.append(rt.meta)

        post_idx = {}
        for basis in (BASIS_POST, BASIS_ENTRY):
            for X in RUNGS:
                ev = rt.rung_event(X, basis)
                if ev is None:
                    continue
                events.append(ev)
                if basis == BASIS_POST:
                    post_idx[X] = ev["rung_idx"]
                slim = {k: ev[k] for k in ("regime_id", "entry_year", "side",
                                           "rung_atr", "basis", "stratum",
                                           "rung_idx", "rung_ts",
                                           "stop_live_reachable",
                                           "hwm_at_arm_atr", "rung_overshoot_atr",
                                           "eventual_max_mfe_atr", "runner_bucket",
                                           "nat_kind", "unc_kind",
                                           "nat_terminal_return_atr",
                                           "unc_terminal_return_atr")}
                for step in STEPS:
                    trans.append({**slim, **rt.transition(ev, step)})

        blind, unif = placebo_armings(rt, rng)
        econ.extend(economics_rows(rt, post_idx, blind, unif))
        if n % 500 == 0:
            print(f"  {n:,}/{conf.height:,}  ({time.time() - t0:.0f}s)", flush=True)

    td = pl.DataFrame(trades, infer_schema_length=None)
    ed = pl.DataFrame(events, infer_schema_length=None)
    xd = pl.DataFrame(trans, infer_schema_length=None)
    cd = pl.DataFrame(econ, infer_schema_length=None)

    td.write_parquet(OUT / "trade_panel.parquet")
    ed.write_parquet(OUT / "rung_events.parquet")
    xd.write_parquet(OUT / "rung_transitions.parquet")
    cd.write_parquet(OUT / "ratchet_economics.parquet")

    print(f"  trades {td.height:,} · rung events {ed.height:,} ·"
          f" transitions {xd.height:,} · economics {cd.height:,}"
          f"  ({time.time() - t0:.0f}s)", flush=True)

    armed = pl.read_parquet(ARMED).filter(pl.col("valid"))
    (OUT / "partition_manifest.json").write_text(json.dumps({
        "study": "post_confirm_profit_ratchet",
        "predecessor": "post_confirm_forward_opportunity (verdict E)",
        "inputs": {"armed_paths": str(ARMED.relative_to(ROOT)),
                   "store": str(STORE.relative_to(ROOT))},
        "original_top10_entries": int(armed.height),
        "confirmed_rows": int(conf.height),
        "measurable_confirmed": int(td.height),
        "non_measurable_confirmed": len(dropped),
        "non_measurable_by_label": (pl.DataFrame(dropped)["terminal_label"]
                                    .value_counts().to_dicts() if dropped else []),
        "rung_events": int(ed.height),
        "transitions": int(xd.height),
        "economics_rows": int(cd.height),
        "rungs_atr": list(RUNGS),
        "steps_atr": list(STEPS),
        "stop_distances_atr": list(STOP_DISTANCES),
        "architectures": list(ARCHITECTURES),
        "runner_tiers_atr": list(RUNNER_TIERS),
        "bases": [BASIS_POST, BASIS_ENTRY],
        "primary_basis": BASIS_POST,
        "stop_atr": STOP_ATR,
        "cost_points_round_turn": COST_POINTS,
        "cost_convention": "one round turn per exit; identical for baseline and "
                           "policy, so the delta is a gross difference",
        "placebo_seed": SEED,
        "placebo_draws": N_PLACEBO,
        "placebo_blind_support_s": list(DENSE_OFFSETS_S),
        "placebos": {
            "P_BLIND": "length-blind grid-offset arming; CAUSALLY IMPLEMENTABLE",
            "P_UNCOND": "armed at confirmation, no rung condition; IMPLEMENTABLE",
            "P_UNIFORM": "uniform over the REALISED lifetime; FUTURE_INFORMATION",
        },
        "hwm_reference": "run_mfe[k-1] -- previous completed bar; causal and "
                         "adverse on same-bar collisions",
        "target_window": "(r, t] INCLUDES the target bar; optimistic bound over "
                         "(r, t) reported alongside",
        "descriptive_track": "UNCONSTRAINED (unc_i) -- no stop censoring",
        "economics_track": "STOP-LIVE (nat_i) -- the accepted contract",
        "threshold_overlap_disclosure": "2025 is NOT threshold-OOS; waiver "
            "studies/full_trade_path_builder/THRESHOLD_OVERLAP_WAIVER.json",
        "accepted_ladder_from_entry": ACCEPTED_LADDER,
        "years": years,
        "note_2026": "sealed; never read",
        "build_seconds": round(time.time() - t0, 1),
    }, indent=2, default=str))
    print("  wrote partition_manifest.json", flush=True)


if __name__ == "__main__":
    main()
