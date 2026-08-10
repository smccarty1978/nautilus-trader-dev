"""Arm detection and post-arm score-path structure.

The arm is the *first true crossing of Top-10 from below* in a regime that is
already older than 600 seconds (SPEC 3). Two properties make this different from
the accepted `first_qualifying` rule and both matter:

* **From below.** A score already at or above Top-10 when the regime crosses the
  600s age boundary is not an arm. The predecessor study's `first_qualifying`
  rule accepted those, which is the entire 8,988 vs 8,953 delta at Top-10.
* **One arm per regime.** Later re-crossings inside the same regime feed the
  shape diagnostics but never create a second armed row.

Everything here reads score rows only. `canonical_regime_scores_all.parquet`
holds one row per *true model dispatch* -- carried-forward copies live on path
rows -- so no observation count, persistence run, or progression interval in
this module can be contaminated by a forward-filled second. That is a structural
property of the substrate, and it is verified rather than assumed in
`validate.py` gate 2.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import polars as pl

from studies.model_driven_entry_exit_discovery.implementation.candidates import (
    THRESHOLDS,
    load_scored,
)

NS = 1_000_000_000

MIN_REGIME_AGE_S = 600.0
ARM_LEVEL = "top_10"
# Ordered shallow -> deep. The band index of an observation is how many of these
# it meets, so the ordering is load-bearing.
LEVELS = ("top_10", "top_5", "top_2_5", "top_1")
LEVEL_SUFFIX = {"top_10": "top10", "top_5": "top5", "top_2_5": "top2_5", "top_1": "top1"}

RETREAT_DEFINITIONS = (0.03, 0.05)

TOP10_ONLY = "TOP10_ONLY"
OSCILLATING = "OSCILLATING"
RETREAT_REEXPANSION = "RETREAT_REEXPANSION"
RETREAT_NO_RECOVERY = "RETREAT_NO_RECOVERY"
MONOTONIC_PROGRESS = "MONOTONIC_PROGRESS"

SHAPE_CLASSES = (
    TOP10_ONLY,
    OSCILLATING,
    RETREAT_REEXPANSION,
    RETREAT_NO_RECOVERY,
    MONOTONIC_PROGRESS,
)


def load_observations() -> pl.DataFrame:
    """In-domain dispatches that actually produced a score.

    `load_scored` keeps every in-domain dispatch, including those where the
    model declined to score -- roughly 8% of the in-domain population carries a
    null `probability` because a frozen feature was incomplete at that second.
    Those rows are dispatches, but they are not *observations*, and treating
    them as such is wrong in two distinct ways:

    * **Causally.** A null is not evidence of "below threshold". If the model
      declined to score at T-5s, the last thing a live trader saw was the score
      at T-10s, so that is the correct predecessor for a crossing test. Letting
      a null stand in as the predecessor rejects genuine crossings (13 regimes
      at Top-10) and would equally have manufactured false ones under the
      opposite null convention.
    * **Numerically.** `probability.to_numpy()` renders nulls as NaN, and NaN
      propagates through `np.maximum.accumulate`, so a single unscored dispatch
      inside a post-arm window would silently corrupt that regime's peak,
      drawdown, and shape classification rather than failing loudly.

    Filtering here does not disturb the SPEC 9 gate 1 parity target: the
    first-qualifying rule compares `probability >= threshold`, which already
    drops nulls, so the accepted 8,988 / 7,396 / 5,823 / 3,415 counts are
    unchanged.
    """
    scored = load_scored()
    return scored.filter(pl.col("probability").is_not_null())


def threshold_expr(label: str) -> pl.Expr:
    """Direction-specific frozen threshold for `label`.

    The bullish and bearish models carry different calibrated values; using one
    for both would silently re-thresholds half the population.
    """
    bull, bear = THRESHOLDS[label]
    return (
        pl.when(pl.col("bullish_in_domain")).then(pl.lit(bull)).otherwise(pl.lit(bear))
    )


def with_level_flags(scored: pl.DataFrame) -> pl.DataFrame:
    """Attach a per-level qualification flag and a band index to every dispatch."""
    flags = [(pl.col("probability") >= threshold_expr(l)).alias(f"q_{l}") for l in LEVELS]
    df = scored.with_columns(flags)
    band = pl.sum_horizontal([pl.col(f"q_{l}").cast(pl.Int8) for l in LEVELS])
    return df.with_columns(band=band)


def _assert_arming_population_is_complete(scored: pl.DataFrame) -> None:
    """Refuse to arm on a partial-year slice.

    The from-below test is a `shift(1).over("regime_id")`, so it can only see
    predecessors that are present in the frame. Filtering years *before* arming
    would drop a regime's true predecessor dispatch at each year boundary and
    manufacture phantom crossings -- the same class of defect as
    `partition_local_checks_miss_cross_partition_defects`. Arming must therefore
    always run on the full population; year filtering happens afterwards.
    """
    observed = set(scored["entry_year"].unique().to_list())
    expected = set(range(2021, 2026))
    if not expected.issubset(observed):
        raise ValueError(
            "arm_population requires the full 2021-2025 score population; "
            f"got years {sorted(observed)}. Filter years after arming, never "
            "before -- a partial slice drops the predecessor dispatch that the "
            "from-below test depends on and invents crossings at each boundary."
        )


def arm_population(scored: pl.DataFrame, *, require_full_population: bool = True) -> pl.DataFrame:
    """One row per armed regime: the first post-600s Top-10 crossing from below.

    `prev_q` is the previous *in-domain dispatch in the same regime*, which is
    what "from below" means causally -- there is no other observation the model
    could have seen. It is allowed to lie before the 600s boundary; the age
    filter constrains the crossing dispatch alone (SPEC 3).

    A regime whose **first** in-domain dispatch is already at or above Top-10 is
    **not** armed. There is no predecessor, so no crossing was ever observed;
    accepting it would assert a rise from below on zero evidence. The previous
    implementation used `shift(1, fill_value=False)`, which silently supplied
    that missing evidence by treating "no prior observation" as "prior
    observation did not qualify". Found by lookahead-auditor pass 1 (WARNING).

    `require_full_population` exists only so unit tests can arm on a synthetic
    frame; production callers must leave it True.
    """
    if require_full_population:
        _assert_arming_population_is_complete(scored)
    df = scored.with_columns(q=(pl.col("probability") >= threshold_expr(ARM_LEVEL)))
    df = df.with_columns(prev_q=pl.col("q").shift(1).over("regime_id"))
    return (
        df.filter(
            pl.col("q")
            & pl.col("prev_q").is_not_null()
            & ~pl.col("prev_q")
            & (pl.col("seconds_from_regime_start") > MIN_REGIME_AGE_S)
        )
        .sort("checkpoint_decision_ns")
        .group_by("regime_id")
        .first()
        .sort("checkpoint_decision_ns")
    )


def first_qualifying_population(scored: pl.DataFrame, label: str) -> pl.DataFrame:
    """The predecessor study's rule, kept only as the parity reference (gate 1)."""
    return (
        scored.filter(
            (pl.col("probability") >= threshold_expr(label))
            & (pl.col("seconds_from_regime_start") > MIN_REGIME_AGE_S)
        )
        .sort("checkpoint_decision_ns")
        .group_by("regime_id")
        .first()
    )


@dataclass
class PostArmScores:
    """Per-regime score observations from the arm dispatch forward.

    Index 0 is the arm itself. Arrays are parallel and sorted by decision time.
    """

    ns: np.ndarray
    probability: np.ndarray
    price: np.ndarray
    atr: np.ndarray
    progress_atr: np.ndarray
    band: np.ndarray
    qualifies: dict[str, np.ndarray]


def post_arm_scores(scored: pl.DataFrame, arms: pl.DataFrame) -> dict[str, PostArmScores]:
    """Slice the score table to each armed regime's post-arm dispatches.

    Restricting to `checkpoint_decision_ns >= arm_ns` is what makes level reach
    post-arm-only (SPEC 4): a level touched earlier in the regime and abandoned
    does not count, the regime has to reach it again.
    """
    flagged = with_level_flags(scored)
    arm_ns = arms.select("regime_id", arm_ns=pl.col("checkpoint_decision_ns"))
    joined = (
        flagged.join(arm_ns, on="regime_id", how="inner")
        .filter(pl.col("checkpoint_decision_ns") >= pl.col("arm_ns"))
        .sort(["regime_id", "checkpoint_decision_ns"])
    )

    out: dict[str, PostArmScores] = {}
    for rid, block in joined.partition_by("regime_id", as_dict=True).items():
        key = rid[0] if isinstance(rid, tuple) else rid
        out[key] = PostArmScores(
            ns=block["checkpoint_decision_ns"].to_numpy(),
            probability=block["probability"].to_numpy(),
            price=block["checkpoint_reference_price"].to_numpy(),
            atr=block["atr_at_checkpoint"].to_numpy(),
            progress_atr=block["current_progress_atr"].to_numpy(),
            band=block["band"].to_numpy(),
            qualifies={l: block[f"q_{l}"].to_numpy() for l in LEVELS},
        )
    return out


def level_reaches(obs: PostArmScores) -> dict[str, int]:
    """Index of the first post-arm dispatch meeting each level, or -1.

    A dispatch that jumps several levels at once satisfies all of them at the
    same index, which is how SPEC 4's "multi-level crossing shares one
    timestamp" rule is realised: the elapsed interval between those levels is
    then exactly 0, not a negative or interpolated value.
    """
    reaches = {}
    for level in LEVELS:
        hits = np.flatnonzero(obs.qualifies[level])
        reaches[level] = int(hits[0]) if hits.size else -1
    return reaches


def _elapsed_s(obs: PostArmScores, i: int, j: int) -> float | None:
    if i < 0 or j < 0:
        return None
    return float((int(obs.ns[j]) - int(obs.ns[i])) / NS)


def classify_shape(
    obs: PostArmScores, upto: int, retreat: float
) -> dict[str, object]:
    """Descriptive score-path shape over observations [0, upto].

    `upto` is the last dispatch at or before the Walk A terminal event, so the
    shape describes only what was knowable while the trade was live. Classes are
    mutually exclusive by the SPEC 7 precedence, and the raw components are
    returned alongside because precedence discards information the report needs.

    `OSCILLATING` is defined on retreat->new-high *cycles* alone. Band changes
    are counted and emitted but deliberately excluded from the class test: a
    single retreat-and-recovery through one threshold band already produces
    three band changes, so a `band_changes >= 3` disjunct swallows
    `RETREAT_REEXPANSION` almost entirely. Band traversal measures depth, not
    oscillation, and conflating them makes the class unreadable.
    """
    prob = obs.probability[: upto + 1]
    band = obs.band[: upto + 1]
    reached_top5 = bool(np.any(obs.qualifies["top_5"][: upto + 1]))

    peak = np.maximum.accumulate(prob)
    drawdown = peak - prob

    # Walk the path counting retreat -> new-high cycles. A cycle opens the first
    # time the score falls `retreat` below the running peak and closes when the
    # score exceeds the peak that was standing when it opened.
    cycles = 0
    had_retreat = False
    open_peak: float | None = None
    for i in range(prob.size):
        if open_peak is None:
            if drawdown[i] >= retreat:
                had_retreat = True
                open_peak = float(peak[i])
        elif prob[i] > open_peak:
            cycles += 1
            open_peak = None

    band_changes = int(np.count_nonzero(np.diff(band) != 0)) if band.size > 1 else 0
    had_reexpansion = cycles >= 1

    if not reached_top5:
        cls = TOP10_ONLY
    elif cycles >= 2:
        cls = OSCILLATING
    elif cycles == 1:
        cls = RETREAT_REEXPANSION
    elif had_retreat:
        cls = RETREAT_NO_RECOVERY
    else:
        cls = MONOTONIC_PROGRESS

    return {
        "shape_class": cls,
        "had_retreat": had_retreat,
        "had_reexpansion": had_reexpansion,
        "n_retreat_cycles": cycles,
        "band_changes": band_changes,
        "reached_top5": reached_top5,
    }


def reexpansion_index(obs: PostArmScores, upto: int, retreat: float) -> int:
    """Index of the first post-arm re-expansion: peak -> retreat >= r -> new high.

    Returned so SPEC 8.6 can measure time from the re-expansion itself to
    confirmation, rather than from the arm.
    """
    prob = obs.probability[: upto + 1]
    peak = np.maximum.accumulate(prob)
    drawdown = peak - prob
    open_peak: float | None = None
    for i in range(prob.size):
        if open_peak is None:
            if drawdown[i] >= retreat:
                open_peak = float(peak[i])
        elif prob[i] > open_peak:
            return i
    return -1


def consecutive_run_at_arm(obs: PostArmScores, level: str, upto: int) -> int:
    """Length of the unbroken run of dispatches at or above `level`, from index 0.

    Counts *true dispatches*, with no cap on the wall-clock gap between them --
    the cadence is nominally 5s but has real gaps, and the observed gap
    distribution is reported alongside the persistence result so the number can
    be read honestly (SPEC 8.5).
    """
    q = obs.qualifies[level][: upto + 1]
    run = 0
    for value in q:
        if not value:
            break
        run += 1
    return run


def load_population():
    """Convenience loader: score observations, the armed population, and slices.

    Deliberately takes no `years` argument -- see
    `_assert_arming_population_is_complete`.
    """
    scored = load_observations()
    arms = arm_population(scored)
    return scored, arms, post_arm_scores(scored, arms)
