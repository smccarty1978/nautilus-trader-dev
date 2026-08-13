"""Build the armed-regime score-path event table (SPEC 6).

One row per armed regime, carrying the arm, the post-arm threshold progression,
the score-path shape, and both walks' excursion measurements. Every downstream
artifact is a query over this table, so the expensive path work happens exactly
once.

Session gating on level reach is deliberate and worth stating plainly: a regime
can span the overnight boundary, so a post-arm Top-5 dispatch may land in the
*next* RTH session. Counting that as "waited for Top-5" would be dishonest --
under the frozen 15:00 CT flat you would have been out of the market for hours
in between. A level therefore only counts as reached if its dispatch falls
within the arm's own session.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import polars as pl

from studies.model_driven_entry_exit_discovery.implementation.engine import (
    COST_POINTS,
    load_market,
    load_regimes,
)
from studies.model_driven_entry_exit_discovery.implementation.candidates import THRESHOLDS

from .arming import (
    load_observations,
    ARM_LEVEL,
    LEVEL_SUFFIX,
    LEVELS,
    MIN_REGIME_AGE_S,
    RETREAT_DEFINITIONS,
    arm_population,
    classify_shape,
    consecutive_run_at_arm,
    level_reaches,
    post_arm_scores,
    reexpansion_index,
)
from .walks import STOP_ATR, continuation_label, measure_to_confirm

NS = 1_000_000_000
ROOT = Path(__file__).resolve().parents[3]
RESULTS = ROOT / "studies/armed_fade_score_path_progression/results"

WALK_B_FIELDS = (
    "confirm_reached_uncensored",
    "confirm_reached_censored",
    "stop_before_confirm",
    "session_close_unresolved",
    "ambiguous",
    "terminal_label",
    "gross_atr",
    "net_atr",
    "seconds_to_confirm",
    "mae_to_confirm_atr",
    "mfe_to_confirm_atr",
    "return_at_confirm_atr",
    "net_return_at_confirm_atr",
)


def _session_close_ns(market, entry_ns: int) -> int | None:
    start = market.index_strictly_after(entry_ns)
    if start >= market.n:
        return None
    return int(market.day_close_ns[start])


def build() -> pl.DataFrame:
    """Build the event table over the full 2021-2025 population.

    Takes no `years` argument on purpose. Arming depends on each regime's
    predecessor dispatch, so a year filter applied *before* arming would drop
    that predecessor at every boundary and manufacture phantom crossings. Year
    breakdowns are produced downstream, by slicing the finished table.
    """
    print("loading substrate ...", flush=True)
    market = load_market()
    regimes = load_regimes()
    scored = load_observations()
    print(f"  {market.n:,} RTH 1s bars, {scored.height:,} scored in-domain "
          f"observations", flush=True)

    arms = arm_population(scored)
    print(f"  {arms.height:,} armed regimes (first post-{MIN_REGIME_AGE_S:.0f}s "
          f"{ARM_LEVEL} crossing from below)", flush=True)

    obs_by_regime = post_arm_scores(scored, arms)

    rows: list[dict] = []
    for arm in arms.iter_rows(named=True):
        rid = arm["regime_id"]
        obs = obs_by_regime.get(rid)
        if obs is None:
            continue

        arm_ns = int(arm["checkpoint_decision_ns"])
        direction = int(arm["direction"])
        arm_price = arm["checkpoint_reference_price"]
        arm_atr = arm["atr_at_checkpoint"]

        session_close = _session_close_ns(market, arm_ns)

        walk_a = measure_to_confirm(
            market, regimes, arm_ns, direction, arm_price, arm_atr
        )
        full = continuation_label(
            market, regimes, arm_ns, direction, arm_price, arm_atr
        )

        row: dict = {
            "regime_id": rid,
            "direction": direction,
            "side": "LONG" if direction > 0 else "SHORT",
            "model_id": arm["model_id"],
            "entry_year": int(arm["entry_year"]),
            "regime_start_ns": int(arm["regime_start_ns"]),
            "arm_top10_ns": arm_ns,
            "regime_age_at_arm_s": float(arm["seconds_from_regime_start"]),
            "arm_score": float(arm["probability"]),
            "arm_price": float(arm_price) if arm_price is not None else None,
            "arm_atr": float(arm_atr) if arm_atr is not None else None,
            "arm_progress_atr": arm["current_progress_atr"],
            "session_close_ns": session_close,
            "valid": bool(walk_a.get("valid", False)),
        }

        for key in (
            "confirm_reached_uncensored", "confirm_reached_censored",
            "confirm_reached_censored_optimistic", "stop_before_confirm",
            "session_close_unresolved", "ambiguous", "terminal_label",
            "terminal_ns", "confirm_ns", "stop_ns", "gross_atr", "net_atr",
            "mae_at_terminal_atr", "mfe_at_terminal_atr",
            "seconds_to_confirm", "mae_to_confirm_atr", "mfe_to_confirm_atr",
            "return_at_confirm_atr", "net_return_at_confirm_atr",
        ):
            row[f"walk_a_{key}"] = walk_a.get(key)
        row["walk_a_seconds_top10_to_confirm"] = walk_a.get("seconds_to_confirm")
        for key in (
            "terminal_label_full", "full_exit_ns", "full_gross_atr",
            "full_net_atr", "full_mfe_atr", "full_mae_atr",
        ):
            row[key] = full.get(key)

        if not walk_a.get("valid"):
            rows.append(row)
            continue

        # --- post-arm dispatch structure, bounded by the Walk A terminal event
        terminal_ns = int(walk_a["terminal_ns"])
        live = np.flatnonzero(obs.ns <= terminal_ns)
        upto = int(live[-1]) if live.size else 0

        gaps = np.diff(obs.ns[: upto + 1]) / NS if upto >= 1 else np.array([])
        row["n_true_observations_post_arm"] = upto + 1
        row["median_dispatch_gap_s"] = float(np.median(gaps)) if gaps.size else None
        row["max_dispatch_gap_s"] = float(gaps.max()) if gaps.size else None

        prob = obs.probability[: upto + 1]
        row["max_score_before_terminal"] = float(prob.max())
        row["min_score_after_arm"] = float(prob.min())
        row["score_drawdown_from_arm"] = float(row["arm_score"] - prob.min())
        row["score_drawdown_from_peak"] = float(
            np.max(np.maximum.accumulate(prob) - prob)
        )

        # --- threshold progression, post-arm and inside the arm's own session
        reaches = level_reaches(obs)
        reach_idx: dict[str, int] = {}
        for level in LEVELS:
            i = reaches[level]
            if i >= 0 and session_close is not None and int(obs.ns[i]) > session_close:
                i = -1                      # reached, but only in a later session
            reach_idx[level] = i

        for level in LEVELS:
            sfx = LEVEL_SUFFIX[level]
            i = reach_idx[level]
            row[f"{sfx}_reached"] = i >= 0
            row[f"{sfx}_ns"] = int(obs.ns[i]) if i >= 0 else None
            row[f"score_at_{sfx}"] = float(obs.probability[i]) if i >= 0 else None
            row[f"price_at_{sfx}"] = float(obs.price[i]) if i >= 0 else None
            row[f"atr_at_{sfx}"] = float(obs.atr[i]) if i >= 0 else None
            row[f"progress_atr_at_{sfx}"] = (
                float(obs.progress_atr[i])
                if i >= 0 and obs.progress_atr[i] is not None
                and np.isfinite(obs.progress_atr[i])
                else None
            )
            row[f"true_score_observations_to_{sfx}"] = i + 1 if i >= 0 else None
            row[f"seconds_top10_to_{sfx}"] = (
                float((int(obs.ns[i]) - arm_ns) / NS) if i >= 0 else None
            )
            # Reached while the Walk A lifecycle was still live -- the Walk A
            # funnel's conditioning event.
            row[f"{sfx}_reached_walk_a"] = i >= 0 and int(obs.ns[i]) <= terminal_ns

        for a, b in (("top_5", "top_2_5"), ("top_2_5", "top_1")):
            ia, ib = reach_idx[a], reach_idx[b]
            key = f"seconds_{LEVEL_SUFFIX[a]}_to_{LEVEL_SUFFIX[b]}"
            row[key] = (
                float((int(obs.ns[ib]) - int(obs.ns[ia])) / NS)
                if ia >= 0 and ib >= 0
                else None
            )

        row["true_score_observations_to_confirm"] = (
            upto + 1 if walk_a.get("confirm_reached_uncensored") else None
        )

        # --- score-path shape, at both frozen retreat definitions
        for retreat in RETREAT_DEFINITIONS:
            tag = f"{retreat:.2f}".replace(".", "_")
            shape = classify_shape(obs, upto, retreat)
            row[f"shape_class_{tag}"] = shape["shape_class"]
            row[f"had_retreat_{tag}"] = shape["had_retreat"]
            row[f"had_reexpansion_{tag}"] = shape["had_reexpansion"]
            row[f"n_retreat_cycles_{tag}"] = shape["n_retreat_cycles"]
            row[f"band_changes_{tag}"] = shape["band_changes"]
            rx = reexpansion_index(obs, upto, retreat)
            row[f"reexpansion_ns_{tag}"] = int(obs.ns[rx]) if rx >= 0 else None
            row[f"seconds_reexpansion_to_confirm_{tag}"] = (
                float((int(walk_a["confirm_ns"]) - int(obs.ns[rx])) / NS)
                if rx >= 0
                and walk_a.get("confirm_reached_uncensored")
                and walk_a.get("confirm_ns") is not None
                else None
            )

        # --- persistence, counted in true dispatches
        row["consecutive_top10_at_arm"] = consecutive_run_at_arm(obs, "top_10", upto)
        i5 = reach_idx["top_5"]
        row["consecutive_top5_at_reach"] = (
            _run_from(obs.qualifies["top_5"][: upto + 1], i5) if i5 >= 0 else 0
        )

        # --- Walk B: an independent hypothetical entry at every level reached
        for level in LEVELS:
            sfx = LEVEL_SUFFIX[level]
            i = reach_idx[level]
            if i < 0:
                for key in WALK_B_FIELDS:
                    row[f"walk_b_{key}_{sfx}"] = None
                continue
            m = measure_to_confirm(
                market, regimes, int(obs.ns[i]), direction,
                float(obs.price[i]), float(obs.atr[i]),
            )
            for key in WALK_B_FIELDS:
                row[f"walk_b_{key}_{sfx}"] = m.get(key)

        rows.append(row)

    df = pl.DataFrame(rows, infer_schema_length=None)
    RESULTS.mkdir(parents=True, exist_ok=True)
    out = RESULTS / "armed_regime_score_paths.parquet"
    df.write_parquet(out)
    print(f"\nwrote {out.relative_to(ROOT)}  ({df.height:,} armed regimes)")

    _write_manifest(df, market, scored)
    return df


def _run_from(mask: np.ndarray, start: int) -> int:
    run = 0
    for value in mask[start:]:
        if not value:
            break
        run += 1
    return run


def _write_manifest(df: pl.DataFrame, market, scored) -> None:
    import hashlib

    impl = Path(__file__).parent
    hashes = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()[:16]
        for p in sorted(impl.glob("*.py"))
    }
    manifest = {
        "study": "armed_fade_score_path_progression",
        "substrate": "data/canonical/regime_complete_v1",
        "cost_points_round_turn": COST_POINTS,
        "stop_atr": STOP_ATR,
        "min_regime_age_s": MIN_REGIME_AGE_S,
        "arm_level": ARM_LEVEL,
        "levels": list(LEVELS),
        "retreat_definitions": list(RETREAT_DEFINITIONS),
        "thresholds": {k: list(v) for k, v in THRESHOLDS.items() if k in LEVELS},
        "walks": {
            "walk_a": "arm-anchored: one lifecycle per armed regime, reference "
                      "price and ATR frozen at the Top-10 arm; deeper levels "
                      "subset the population and never move the origin",
            "walk_b": "per-level independent: one hypothetical entry per level "
                      "reached, own reference price, own frozen ATR, own 1.0 ATR stop",
        },
        "session_rule": "RTH only, forced flat 15:00 CT, level reach must fall "
                        "inside the arm's own session",
        "years": sorted(df["entry_year"].unique().to_list()),
        "armed_regimes": df.height,
        "rth_bars": int(market.n),
        "in_domain_dispatches": int(scored.height),
        "code_hashes": hashes,
        "threshold_overlap_disclosure": "both calibration populations are "
                                        "calendar-2025 and overlap the evaluation "
                                        "window; 2025 is not threshold-OOS",
    }
    (RESULTS / "partition_manifest.json").write_text(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    build()
