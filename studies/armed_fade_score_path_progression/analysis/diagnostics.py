"""All SPEC 8 diagnostics, as queries over the armed-regime event table.

Every analysis here is descriptive. Nothing selects a parameter by outcome, and
no quantile cutoff is tuned -- the progression-speed quartiles are computed on
this population precisely because they are meant to describe it, not to
discriminate on it.

Breakdowns are pooled / by direction / by year throughout. Per SPEC 2.2 the
model partition is identical to the direction partition (the two domains never
overlap), so it is stated once and not duplicated as a third breakdown.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import polars as pl

from ..implementation.arming import LEVELS, LEVEL_SUFFIX, RETREAT_DEFINITIONS
from ..implementation.walks import FULL_LABELS, PRIMARY_LABELS

ROOT = Path(__file__).resolve().parents[3]
RESULTS = ROOT / "studies/armed_fade_score_path_progression/results"

SURVIVAL_BANDS = (0.25, 0.50, 0.75, 1.00)
YEARS = (2021, 2022, 2023, 2024, 2025)
SUFFIXES = [LEVEL_SUFFIX[l] for l in LEVELS]


# ------------------------------------------------------------------ helpers


def _stats(values) -> dict:
    a = np.asarray([v for v in values if v is not None and np.isfinite(v)], dtype=float)
    if a.size == 0:
        return {"n": 0}
    return {
        "n": int(a.size),
        "mean": float(a.mean()),
        "median": float(np.median(a)),
        "p25": float(np.percentile(a, 25)),
        "p50": float(np.percentile(a, 50)),
        "p75": float(np.percentile(a, 75)),
        "p90": float(np.percentile(a, 90)),
        "p95": float(np.percentile(a, 95)),
        "max": float(a.max()),
    }


def _rate(df: pl.DataFrame, col: str) -> float | None:
    if df.height == 0:
        return None
    return round(float(df[col].fill_null(False).cast(pl.Int32).mean()), 4)


def _med(df: pl.DataFrame, col: str) -> float | None:
    if df.height == 0:
        return None
    v = df[col].drop_nulls()
    return round(float(v.median()), 4) if v.len() else None


def breakdowns(df: pl.DataFrame):
    """Yield (label, slice) for pooled, each direction, and each year."""
    yield "pooled", df
    for side in ("SHORT", "LONG"):
        yield f"direction:{side}", df.filter(pl.col("side") == side)
    for year in YEARS:
        yield f"year:{year}", df.filter(pl.col("entry_year") == year)


# ----------------------------------------------------------- 8.1 the funnel


def _funnel_stage(stage_df: pl.DataFrame, armed_n: int, label: str) -> dict:
    confirmed = stage_df.filter(pl.col("walk_a_confirm_reached_censored"))
    return {
        "stage": label,
        "n": stage_df.height,
        "pct_of_armed": round(100 * stage_df.height / armed_n, 2) if armed_n else None,
        "p_confirm": _rate(stage_df, "walk_a_confirm_reached_censored"),
        "p_confirm_uncensored": _rate(stage_df, "walk_a_confirm_reached_uncensored"),
        "p_stop_before_confirm": _rate(stage_df, "walk_a_stop_before_confirm"),
        "p_session_close_unresolved": _rate(stage_df, "walk_a_session_close_unresolved"),
        "median_seconds_to_confirm": _med(confirmed, "walk_a_seconds_to_confirm"),
        "median_return_at_confirm_atr": _med(confirmed, "walk_a_return_at_confirm_atr"),
        "median_net_return_at_confirm_atr": _med(
            confirmed, "walk_a_net_return_at_confirm_atr"
        ),
        "median_mae_to_confirm_atr": _med(confirmed, "walk_a_mae_to_confirm_atr"),
        "median_mfe_to_confirm_atr": _med(confirmed, "walk_a_mfe_to_confirm_atr"),
        "ambiguous": int(stage_df["walk_a_ambiguous"].fill_null(False).sum()),
    }


def threshold_progression_funnel(df: pl.DataFrame) -> dict:
    """Walk A funnel: armed -> Top-5 -> Top-2.5 -> Top-1 -> confirmed.

    Nested and path-dependent by construction: a level counts only if it was
    reached while the arm-anchored lifecycle was still live. Metrics are always
    measured from the arm, because in Walk A deeper levels subset the population
    rather than relocate the measurement origin.
    """
    out = {
        "walk": "A (arm-anchored)",
        "note": "all metrics measured from the Top-10 arm; deeper levels subset "
                "the population. Confirmation is the conservative (censored) "
                "bound, in which a same-bar stop/confirm tie resolves adversely.",
        "breakdowns": {},
    }
    for label, sub in breakdowns(df):
        armed_n = sub.height
        stages = [_funnel_stage(sub, armed_n, "armed_top10")]
        for level in ("top_5", "top_2_5", "top_1"):
            sfx = LEVEL_SUFFIX[level]
            stages.append(
                _funnel_stage(
                    sub.filter(pl.col(f"{sfx}_reached_walk_a")), armed_n, f"reached_{sfx}"
                )
            )
        by_stage = {s["stage"]: s for s in stages}
        order = ["armed_top10", "reached_top5", "reached_top2_5", "reached_top1"]
        lift = {}
        for prev, nxt in zip(order, order[1:]):
            a, b = by_stage[prev]["p_confirm"], by_stage[nxt]["p_confirm"]
            lift[f"{nxt}_minus_{prev}"] = (
                round(b - a, 4) if a is not None and b is not None else None
            )
        out["breakdowns"][label] = {
            "armed_n": armed_n,
            "stages": stages,
            "incremental_lift": lift,
            "terminal_labels": _label_counts(sub, "walk_a_terminal_label", PRIMARY_LABELS),
            "terminal_labels_full": _label_counts(sub, "terminal_label_full", FULL_LABELS),
        }
    return out


def _label_counts(df: pl.DataFrame, col: str, universe) -> dict:
    counts = dict.fromkeys(universe, 0)
    if df.height:
        for row in df[col].value_counts().iter_rows(named=True):
            if row[col] is not None:
                counts[row[col]] = row["count"]
    return counts


# ------------------------------------------------------- 8.2 MAE to confirm


def mae_to_confirm_by_level(df: pl.DataFrame) -> dict:
    """MAE required by successful flips, from each of the four entry levels.

    Reported in two populations, side by side:

    * `uncensored` -- everything that reached the confirming flip before the
      session close, no stop applied. This is the answer to "how much stop room
      does the successful flip population require".
    * `censored_1atr` -- only entries confirming before a 1.0 ATR adverse
      excursion. Bounded above by 1.0 ATR *by construction*, so its 1.00-ATR
      survival row is necessarily 1.0 and its p90/p95 are truncation artifacts,
      not measurements. Included because it is the Walk A survivor population.
    """
    out = {
        "walk": "B (per-level independent entries)",
        "note": "each level measured from its own first-reach dispatch, own "
                "reference price, own frozen ATR. The censored block is bounded "
                "above by 1.0 ATR by construction -- read Q2 from the uncensored "
                "block.",
        "breakdowns": {},
    }
    for label, sub in breakdowns(df):
        block = {}
        for sfx in SUFFIXES:
            reached = sub.filter(pl.col(f"{sfx}_reached"))
            unc = reached.filter(pl.col(f"walk_b_confirm_reached_uncensored_{sfx}"))
            cen = reached.filter(pl.col(f"walk_b_confirm_reached_censored_{sfx}"))
            block[sfx] = {
                "reached_n": reached.height,
                "uncensored": _population_block(unc, sfx),
                "censored_1atr": _population_block(cen, sfx),
            }
        out["breakdowns"][label] = block
    return out


def _population_block(df: pl.DataFrame, sfx: str) -> dict:
    mae = df[f"walk_b_mae_to_confirm_atr_{sfx}"].to_list() if df.height else []
    a = np.asarray([v for v in mae if v is not None], dtype=float)
    survival = {
        f"pct_within_{band:.2f}_atr": (
            round(100 * float(np.mean(a <= band)), 2) if a.size else None
        )
        for band in SURVIVAL_BANDS
    }
    return {
        "n": df.height,
        "mae_to_confirm_atr": _stats(mae),
        "survival": survival,
        "mfe_to_confirm_atr": _stats(
            df[f"walk_b_mfe_to_confirm_atr_{sfx}"].to_list() if df.height else []
        ),
        "return_at_confirm_atr": _stats(
            df[f"walk_b_return_at_confirm_atr_{sfx}"].to_list() if df.height else []
        ),
        "net_return_at_confirm_atr": _stats(
            df[f"walk_b_net_return_at_confirm_atr_{sfx}"].to_list() if df.height else []
        ),
        "seconds_to_confirm": _stats(
            df[f"walk_b_seconds_to_confirm_{sfx}"].to_list() if df.height else []
        ),
    }


def remaining_opportunity(df: pl.DataFrame) -> dict:
    """8.3 -- what is left of the move at each level, for confirmed entries."""
    out = {"walk": "B (per-level independent entries)", "breakdowns": {}}
    for label, sub in breakdowns(df):
        block = {}
        for sfx in SUFFIXES:
            unc = sub.filter(
                pl.col(f"{sfx}_reached")
                & pl.col(f"walk_b_confirm_reached_uncensored_{sfx}")
            )
            block[sfx] = {
                "n": unc.height,
                "p_confirm_of_reached": _rate(
                    sub.filter(pl.col(f"{sfx}_reached")),
                    f"walk_b_confirm_reached_censored_{sfx}",
                ),
                "mfe_to_confirm_atr": _stats(
                    unc[f"walk_b_mfe_to_confirm_atr_{sfx}"].to_list() if unc.height else []
                ),
                "return_at_confirm_atr": _stats(
                    unc[f"walk_b_return_at_confirm_atr_{sfx}"].to_list() if unc.height else []
                ),
                "net_return_at_confirm_atr": _stats(
                    unc[f"walk_b_net_return_at_confirm_atr_{sfx}"].to_list()
                    if unc.height else []
                ),
                "median_progress_atr_at_entry": _med(unc, f"progress_atr_at_{sfx}"),
            }
        out["breakdowns"][label] = block
    return out


# ---------------------------------------------------- 8.4 progression speed


def progression_speed(df: pl.DataFrame) -> dict:
    """Within-level elapsed-time quartiles, descriptive not tuned.

    `median_progress_atr_at_entry` is carried into every cell so the report can
    separate "fast escalation is more reliable" from "fast escalation simply
    arrives later in the price move" -- the two are confounded unless realized
    regime progress is shown alongside.
    """
    out = {"walk": "A for outcomes, level dispatch for timing", "breakdowns": {}}
    for label, sub in breakdowns(df):
        block = {}
        for sfx in ("top5", "top2_5", "top1"):
            reached = sub.filter(
                pl.col(f"{sfx}_reached_walk_a")
                & pl.col(f"seconds_top10_to_{sfx}").is_not_null()
            )
            if reached.height < 8:
                block[f"top10_to_{sfx}"] = {"n": reached.height, "quartiles": []}
                continue
            secs = reached[f"seconds_top10_to_{sfx}"].to_numpy()
            edges = np.percentile(secs, [25, 50, 75])
            cells = []
            for q in range(4):
                lo = -np.inf if q == 0 else edges[q - 1]
                hi = np.inf if q == 3 else edges[q]
                mask = (secs > lo) & (secs <= hi) if q else (secs <= hi)
                cell = reached.filter(pl.Series(mask))
                confirmed = cell.filter(pl.col("walk_a_confirm_reached_censored"))
                cells.append({
                    "quartile": f"Q{q + 1}",
                    "seconds_range": [
                        None if not np.isfinite(lo) else round(float(lo), 1),
                        None if not np.isfinite(hi) else round(float(hi), 1),
                    ],
                    "n": cell.height,
                    "p_confirm": _rate(cell, "walk_a_confirm_reached_censored"),
                    "p_stop_before_confirm": _rate(cell, "walk_a_stop_before_confirm"),
                    "median_mae_to_confirm_atr": _med(confirmed, "walk_a_mae_to_confirm_atr"),
                    "median_return_at_confirm_atr": _med(
                        confirmed, "walk_a_return_at_confirm_atr"
                    ),
                    "median_mfe_to_confirm_atr": _med(confirmed, "walk_a_mfe_to_confirm_atr"),
                    "median_progress_atr_at_entry": _med(cell, f"progress_atr_at_{sfx}"),
                })
            block[f"top10_to_{sfx}"] = {
                "n": reached.height,
                "quartile_edges_s": [round(float(e), 1) for e in edges],
                "quartiles": cells,
            }
        out["breakdowns"][label] = block
    return out


# --------------------------------------------------------- 8.5 persistence


def persistence_diagnostics(df: pl.DataFrame) -> dict:
    """Five cells only. No grid.

    "Consecutive" counts consecutive *true dispatches* with no wall-clock cap.
    The gap distribution is emitted alongside so that a 3-observation run is not
    silently read as 15 seconds when the cadence had a hole in it.
    """
    gaps = df["median_dispatch_gap_s"].drop_nulls().to_numpy()
    out = {
        "dispatch_gap_seconds": _stats(gaps.tolist()),
        "max_dispatch_gap_seconds": _stats(
            df["max_dispatch_gap_s"].drop_nulls().to_list()
        ),
        "breakdowns": {},
    }
    for label, sub in breakdowns(df):
        cells = {}
        for n in (1, 2, 3):
            cells[f"top10_x{n}"] = _persistence_cell(
                sub.filter(pl.col("consecutive_top10_at_arm") >= n)
            )
        for n in (2, 3):
            cells[f"top5_x{n}"] = _persistence_cell(
                sub.filter(
                    pl.col("top5_reached_walk_a")
                    & (pl.col("consecutive_top5_at_reach") >= n)
                )
            )
        out["breakdowns"][label] = cells
    return out


def _persistence_cell(df: pl.DataFrame) -> dict:
    confirmed = df.filter(pl.col("walk_a_confirm_reached_censored"))
    return {
        "n": df.height,
        "p_confirm": _rate(df, "walk_a_confirm_reached_censored"),
        "p_stop_before_confirm": _rate(df, "walk_a_stop_before_confirm"),
        "median_mae_to_confirm_atr": _med(confirmed, "walk_a_mae_to_confirm_atr"),
        "median_return_at_confirm_atr": _med(confirmed, "walk_a_return_at_confirm_atr"),
        "median_seconds_to_confirm": _med(confirmed, "walk_a_seconds_to_confirm"),
    }


# --------------------------------------------- 8.6 shape and re-expansion


def shape_diagnostics(df: pl.DataFrame) -> dict:
    out = {"breakdowns": {}}
    for label, sub in breakdowns(df):
        block = {}
        for retreat in RETREAT_DEFINITIONS:
            tag = f"{retreat:.2f}".replace(".", "_")
            classes = {}
            for cls in sub[f"shape_class_{tag}"].drop_nulls().unique().sort().to_list():
                cell = sub.filter(pl.col(f"shape_class_{tag}") == cls)
                confirmed = cell.filter(pl.col("walk_a_confirm_reached_censored"))
                classes[cls] = {
                    "n": cell.height,
                    "pct_of_armed": round(100 * cell.height / sub.height, 2)
                    if sub.height else None,
                    "p_confirm": _rate(cell, "walk_a_confirm_reached_censored"),
                    "p_stop_before_confirm": _rate(cell, "walk_a_stop_before_confirm"),
                    "median_mae_to_confirm_atr": _med(confirmed, "walk_a_mae_to_confirm_atr"),
                    "median_return_at_confirm_atr": _med(
                        confirmed, "walk_a_return_at_confirm_atr"
                    ),
                    "median_seconds_to_confirm": _med(confirmed, "walk_a_seconds_to_confirm"),
                }
            # Depth and shape are orthogonal; precedence would otherwise hide it.
            cross = {}
            for reached in (True, False):
                cell = sub.filter(pl.col("top5_reached_walk_a") == reached)
                cross[f"reached_top5={reached}"] = {
                    "n": cell.height,
                    "p_confirm": _rate(cell, "walk_a_confirm_reached_censored"),
                }
            block[f"retreat_{tag}"] = {"classes": classes, "depth_cross_tab": cross}
        out["breakdowns"][label] = block
    return out


def reexpansion_diagnostics(df: pl.DataFrame) -> dict:
    """Post-arm re-expansion against its two honest comparators.

    Diagnostic only. The predecessor study found `reexpansion` gross-positive
    across neighbouring settings and still below breakeven, so a favourable
    number here is a structural observation, not a rule.
    """
    out = {"breakdowns": {}}
    for label, sub in breakdowns(df):
        block = {}
        for retreat in RETREAT_DEFINITIONS:
            tag = f"{retreat:.2f}".replace(".", "_")
            groups = {
                "reexpansion": sub.filter(pl.col(f"had_reexpansion_{tag}")),
                "retreat_without_recovery": sub.filter(
                    pl.col(f"had_retreat_{tag}") & ~pl.col(f"had_reexpansion_{tag}")
                ),
                "no_retreat": sub.filter(~pl.col(f"had_retreat_{tag}")),
            }
            cells = {}
            for name, cell in groups.items():
                confirmed = cell.filter(pl.col("walk_a_confirm_reached_censored"))
                entry = {
                    "n": cell.height,
                    "p_confirm": _rate(cell, "walk_a_confirm_reached_censored"),
                    "p_stop_before_confirm": _rate(cell, "walk_a_stop_before_confirm"),
                    "median_mae_to_confirm_atr": _med(confirmed, "walk_a_mae_to_confirm_atr"),
                    "median_return_at_confirm_atr": _med(
                        confirmed, "walk_a_return_at_confirm_atr"
                    ),
                }
                if name == "reexpansion":
                    entry["median_seconds_reexpansion_to_confirm"] = _med(
                        confirmed, f"seconds_reexpansion_to_confirm_{tag}"
                    )
                cells[name] = entry
            block[f"retreat_{tag}"] = cells
        out["breakdowns"][label] = block
    return out


# ------------------------------------------------- 11 candidate hypotheses


def entry_confirmation_candidates(df: pl.DataFrame) -> dict:
    """At most five causal entry concepts. Hypotheses, never policies.

    Each is a filter over the armed population plus a choice of measurement
    origin. None is optimized; the parameters are the ones already frozen in the
    SPEC (levels, retreat definitions, persistence counts).
    """
    specs = [
        ("arm_top10_enter_first_top5",
         "Arm at Top-10, enter at the first post-arm Top-5",
         pl.col("top5_reached"), "top5"),
        ("arm_top10_enter_top5_persistent_2",
         "Arm at Top-10, enter after 2 consecutive true Top-5 observations",
         pl.col("top5_reached") & (pl.col("consecutive_top5_at_reach") >= 2), "top5"),
        ("arm_top10_enter_top5_reexpansion",
         "Arm at Top-10, enter at Top-5 only on a re-expansion path (retreat 0.05)",
         pl.col("top5_reached") & pl.col("had_reexpansion_0_05"), "top5"),
        ("arm_top10_enter_top5_fast",
         "Arm at Top-10, enter at Top-5 only when it arrives in the fastest quartile",
         None, "top5"),
        ("arm_top10_enter_first_top2_5",
         "Arm at Top-10, enter at the first post-arm Top-2.5",
         pl.col("top2_5_reached"), "top2_5"),
    ]

    fast_edge = None
    reached5 = df.filter(pl.col("top5_reached") & pl.col("seconds_top10_to_top5").is_not_null())
    if reached5.height >= 8:
        fast_edge = float(np.percentile(reached5["seconds_top10_to_top5"].to_numpy(), 25))

    out = {
        "note": "hypotheses only; no production winner is designated and none is "
                "optimized. Metrics are Walk B (measured from the entry level "
                "itself). Confirmation is the conservative censored bound.",
        "fast_quartile_edge_seconds": fast_edge,
        "candidates": [],
    }
    for key, description, predicate, sfx in specs:
        if predicate is None:
            if fast_edge is None:
                continue
            predicate = pl.col("top5_reached") & (pl.col("seconds_top10_to_top5") <= fast_edge)
        cell = df.filter(predicate)
        entry = {"key": key, "description": description, "entry_level": sfx}
        entry.update(_candidate_metrics(cell, sfx))
        entry["by_direction"] = {
            side: _candidate_metrics(cell.filter(pl.col("side") == side), sfx)
            for side in ("SHORT", "LONG")
        }
        entry["by_year"] = {
            str(y): _candidate_metrics(cell.filter(pl.col("entry_year") == y), sfx)
            for y in YEARS
        }
        out["candidates"].append(entry)
    return out


def _candidate_metrics(df: pl.DataFrame, sfx: str) -> dict:
    if df.height == 0:
        return {"n": 0}
    confirmed = df.filter(pl.col(f"walk_b_confirm_reached_censored_{sfx}"))
    unc = df.filter(pl.col(f"walk_b_confirm_reached_uncensored_{sfx}"))
    return {
        "n": df.height,
        "p_confirm": _rate(df, f"walk_b_confirm_reached_censored_{sfx}"),
        "p_stop_before_confirm": _rate(df, f"walk_b_stop_before_confirm_{sfx}"),
        "median_mae_to_confirm_atr_censored": _med(
            confirmed, f"walk_b_mae_to_confirm_atr_{sfx}"
        ),
        "median_mae_to_confirm_atr_uncensored": _med(
            unc, f"walk_b_mae_to_confirm_atr_{sfx}"
        ),
        "p90_mae_to_confirm_atr_uncensored": (
            round(float(np.percentile(
                unc[f"walk_b_mae_to_confirm_atr_{sfx}"].drop_nulls().to_numpy(), 90)), 4)
            if unc.height else None
        ),
        "median_return_at_confirm_atr": _med(
            confirmed, f"walk_b_return_at_confirm_atr_{sfx}"
        ),
        "median_net_return_at_confirm_atr": _med(
            confirmed, f"walk_b_net_return_at_confirm_atr_{sfx}"
        ),
        "median_seconds_to_confirm": _med(confirmed, f"walk_b_seconds_to_confirm_{sfx}"),
    }


# ------------------------------------------------------------------- main


def main() -> None:
    path = RESULTS / "armed_regime_score_paths.parquet"
    df = pl.read_parquet(path).filter(pl.col("valid"))
    print(f"loaded {df.height:,} valid armed regimes from {path.name}", flush=True)

    artifacts = {
        "threshold_progression_funnel.json": threshold_progression_funnel(df),
        "mae_to_confirm_by_level.json": mae_to_confirm_by_level(df),
        "remaining_opportunity.json": remaining_opportunity(df),
        "progression_speed.json": progression_speed(df),
        "persistence_diagnostics.json": persistence_diagnostics(df),
        "shape_diagnostics.json": shape_diagnostics(df),
        "reexpansion_diagnostics.json": reexpansion_diagnostics(df),
        "entry_confirmation_candidates.json": entry_confirmation_candidates(df),
    }
    for name, payload in artifacts.items():
        (RESULTS / name).write_text(json.dumps(payload, indent=2, default=str))
        print(f"  wrote results/{name}", flush=True)


if __name__ == "__main__":
    main()
