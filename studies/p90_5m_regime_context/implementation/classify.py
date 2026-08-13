"""WITH/AGAINST classification, transition matrix, Phase 6 (label-only,
walled off), and Phase 11 stratification keys (SPEC sections 3, 4, 5).

Causal guarantee for every non-Phase-6 function: every regime lookup goes
through `Regime5m.state_at`/`age_seconds_at`/`age_bars_at`, which only ever
resolve flips with `close_ts <= decision_ts` (SPEC section 3). The ONE
exception is `phase6_future_flip_labels`, the only function in this module
permitted to call `Regime5m.lookahead_next_change_into_direction_after` -- its output is
a separate frame with every produced timing/relationship column prefixed
`label_only_`, never merged into `classify_core`'s output.
"""
from __future__ import annotations

import numpy as np
import polars as pl

from studies.p90_5m_regime_context.implementation.regime_5m import NS, Regime5m

CT = "America/Chicago"

#: Phase 1 frozen age buckets (minutes), shared by Phase 1, 7, and 11's
#: 1m-regime-age stratum. Not optimized (SPEC section 4, Phase 1).
AGE_BUCKET_EDGES_MIN = (5, 15, 30, 60)
AGE_BUCKET_LABELS = ("0-5min", "5-15min", "15-30min", "30-60min", ">60min")

#: Phase 11 frozen time-of-day windows, RTH quartered (SPEC section 4, Phase 11).
#: minutes-since-midnight-CT: 08:30, 10:00, 11:30, 13:00, 15:00
TOD_EDGES_MIN = (510, 600, 690, 780, 900)
TOD_LABELS = ("08:30-10:00", "10:00-11:30", "11:30-13:00", "13:00-15:00")

#: Phase 6 timing buckets on label_only_p90_to_5m_flip_s (SPEC section 4, Phase 6)
TIMING_EDGES_S = (60, 120, 300, 600)
TIMING_LABELS = ("<=60s", "61-120s", "121-300s", "301-600s", ">600s")


def _bucket(values: np.ndarray, edges: tuple, labels: tuple) -> np.ndarray:
    """Left-closed, right-open buckets except the final unbounded one
    (SPEC section 8.1 boundary convention)."""
    idx = np.searchsorted(edges, values, side="right")
    out = np.array(labels, dtype=object)[np.clip(idx, 0, len(labels) - 1)]
    return out


def age_bucket(seconds: np.ndarray) -> np.ndarray:
    minutes = seconds / 60.0
    out = _bucket(minutes, AGE_BUCKET_EDGES_MIN, AGE_BUCKET_LABELS)
    out = np.where(np.isnan(seconds), None, out)
    return out


def time_of_day_bucket(ts_ns: np.ndarray) -> np.ndarray:
    local = (
        pl.Series("t", ts_ns).to_frame()
        .select(pl.from_epoch("t", time_unit="ns").dt.convert_time_zone(CT).alias("local"))
    )["local"]
    # dt.hour()/dt.minute() return a narrow integer dtype (Int8) -- cast
    # before arithmetic or `hour * 60` silently overflows/wraps.
    minutes = (local.dt.hour().cast(pl.Int32) * 60
               + local.dt.minute().cast(pl.Int32)).to_numpy()
    return _bucket(minutes, TOD_EDGES_MIN[1:], TOD_LABELS)


def classify_core(arms: pl.DataFrame, r5m: Regime5m) -> pl.DataFrame:
    """Core classification, all 8,950 arms (SPEC section 3)."""
    t = arms["arm_top10_ns"].to_numpy()
    d = arms["direction"].to_numpy()
    state = r5m.state_at(t)
    with_5m = (state == d) & (state != 0)
    against_5m = (state != d) & (state != 0)
    uninit = state == 0
    age_s = r5m.age_seconds_at(t)
    age_bars = r5m.age_bars_at(t)

    conf_t = arms["walk_a_confirm_ns"].to_numpy()
    conf_mask = arms["walk_a_confirm_reached_censored"].to_numpy()
    state_conf = r5m.state_at(conf_t)
    d_conf = d
    with_5m_confirm_raw = (state_conf == d_conf) & (state_conf != 0)

    out = arms.select("regime_id", "direction", "side", "entry_year", "arm_top10_ns").with_columns(
        with_5m_at_p90=pl.Series(with_5m),
        against_5m_at_p90=pl.Series(against_5m),
        uninit_at_p90=pl.Series(uninit),
        regime_age_s_at_p90=pl.Series(age_s),
        regime_age_bars_at_p90=pl.Series(age_bars),
        age_bucket=pl.Series(age_bucket(age_s)),
        with_5m_at_confirm=pl.when(pl.Series(conf_mask))
        .then(pl.Series(with_5m_confirm_raw))
        .otherwise(None),
    )
    return out


def phase6_future_flip_labels(arms: pl.DataFrame, r5m: Regime5m) -> pl.DataFrame:
    """The one legitimate forward-looking lookup in this study (SPEC section 5).

    For every P90 arm, determine whether P90 occurs AFTER an existing 5m flip
    into trade direction, or while still against/uninitialised 5m with a
    future 5m flip into direction eventually occurring. The flip timestamp is
    an OUTCOME LABEL ONLY -- every produced column is `label_only_`-prefixed
    and this frame is never merged into `classify_core`'s output.
    """
    t = arms["arm_top10_ns"].to_numpy()
    d = arms["direction"].to_numpy()
    terminal_ns = arms["full_exit_ns"].to_numpy()
    state = r5m.state_at(t)
    already_with = (state == d) & (state != 0)

    future_flip = np.array(
        [r5m.lookahead_next_change_into_direction_after(int(tt), int(dd)) if not aw else -1
         for tt, dd, aw in zip(t, d, already_with)]
    )
    has_future_flip = future_flip >= 0
    flip_before_terminal = has_future_flip & (future_flip <= terminal_ns)

    relationship = np.where(
        already_with, "AFTER_EXISTING_FLIP",
        np.where(flip_before_terminal, "BEFORE_FUTURE_FLIP", "NO_FLIP_BEFORE_TERMINAL"),
    )
    seconds_to_flip = np.where(flip_before_terminal, (future_flip - t) / NS, np.nan)
    timing_bucket = np.where(
        flip_before_terminal,
        _bucket(seconds_to_flip, TIMING_EDGES_S, TIMING_LABELS),
        np.where(already_with, "N/A_ALREADY_WITH", "NO_FLIP_BEFORE_TERMINAL"),
    )

    return arms.select("regime_id", "direction", "side", "entry_year").with_columns(
        label_only_p90_relative_to_5m_flip=pl.Series(relationship),
        label_only_p90_to_5m_flip_s=pl.Series(seconds_to_flip),
        timing_bucket=pl.Series(timing_bucket),
    )


def arm_score_quartiles(arms: pl.DataFrame) -> list[float]:
    """Frozen once on the full 8,950 population (SPEC section 4, Phase 11)."""
    return [float(arms["arm_score"].quantile(q)) for q in (0.25, 0.50, 0.75)]


def arm_score_bucket(scores: np.ndarray, edges: list[float]) -> np.ndarray:
    labels = ("Q1", "Q2", "Q3", "Q4")
    return _bucket(scores, tuple(edges), labels)


def phase11_strata(arms: pl.DataFrame) -> pl.DataFrame:
    """Stratification keys only -- no outcome field (SPEC section 4, Phase 11).

    Matching uses only quantities available at `arm_top10_ns`: year, side,
    time-of-day, `arm_score` quartile, and the EXISTING 1m regime age
    (`regime_age_at_arm_s`), explicitly distinct from the new 5m age field.
    """
    edges = arm_score_quartiles(arms)
    tod = time_of_day_bucket(arms["arm_top10_ns"].to_numpy())
    score_q = arm_score_bucket(arms["arm_score"].to_numpy(), edges)
    age_1m_bucket = age_bucket(arms["regime_age_at_arm_s"].to_numpy())
    return arms.select("regime_id", "entry_year", "side").with_columns(
        time_of_day=pl.Series(tod),
        arm_score_quartile=pl.Series(score_q),
        regime_age_1m_bucket=pl.Series(age_1m_bucket),
    )
