"""Frozen bucket definitions and the shared forward-opportunity metric block.

Every boundary here is written down once, in SPEC §7, and is never tuned. The
point of freezing them in a module of their own is that a reader can check the
entire discretisation of the study in forty lines, and no phase can quietly use
a different edge from another phase.
"""
from __future__ import annotations

import numpy as np
import polars as pl

# ---- frozen edges (SPEC §7) ----------------------------------------------
STALL_BUCKETS = (("0-15", None, 15), ("16-30", 15, 30), ("31-45", 30, 45),
                 ("46-60", 45, 60), ("61-90", 60, 90), ("91-120", 90, 120),
                 (">120", 120, None))
STALL4_BUCKETS = (("<=30", None, 30), ("31-60", 30, 60), ("61-90", 60, 90),
                  (">90", 90, None))
PROGRESS5_BUCKETS = (("STRONG_NEG", None, -0.25), ("NEG", -0.25, -0.05),
                     ("FLAT", -0.05, 0.05), ("POS", 0.05, 0.25),
                     ("STRONG_POS", 0.25, None))
PROGRESS3_BUCKETS = (("NEGATIVE", None, -0.05), ("FLAT_WEAK", -0.05, 0.05),
                     ("POSITIVE", 0.05, None))
MFE_BUCKETS = (("<1", None, 1.0), ("1-2", 1.0, 2.0), ("2-3", 2.0, 3.0),
               (">=3", 3.0, None))
DD_BUCKETS = (("<0.25", None, 0.25), ("0.25-0.50", 0.25, 0.50),
              ("0.50-0.75", 0.50, 0.75), (">=0.75", 0.75, None))

# the four races carried on every bucket table
KEY_RACES = (("p_up025_b_dn025", "race_0_25_before_0_25"),
             ("p_up050_b_dn025", "race_0_5_before_0_25"),
             ("p_up050_b_dn050", "race_0_5_before_0_5"),
             ("p_up100_b_dn050", "race_1_0_before_0_5"))


def bucketize(col: str, spec, out: str) -> pl.Expr:
    """Left-open / right-closed bins, so the edges partition exactly.

    A value exactly on an edge belongs to the LOWER bucket. Stated because an
    ambiguous edge silently moved 52 trades between cohorts in the predecessor.
    """
    e = pl.lit(None, dtype=pl.String)
    for name, lo, hi in reversed(spec):
        cond = pl.lit(True)
        if lo is not None:
            cond = cond & (pl.col(col) > lo)
        if hi is not None:
            cond = cond & (pl.col(col) <= hi)
        e = pl.when(pl.col(col).is_not_null() & cond).then(pl.lit(name)).otherwise(e)
    return e.alias(out)


def with_buckets(df: pl.DataFrame) -> pl.DataFrame:
    return df.with_columns(
        bucketize("seconds_since_last_favorable_extreme", STALL_BUCKETS, "stall_bucket"),
        bucketize("seconds_since_last_favorable_extreme", STALL4_BUCKETS, "stall4_bucket"),
        bucketize("mark_progress_last_60s", PROGRESS5_BUCKETS, "progress60_bucket"),
        bucketize("mark_progress_last_30s", PROGRESS5_BUCKETS, "progress30_bucket"),
        bucketize("mark_progress_last_60s", PROGRESS3_BUCKETS, "progress3_bucket"),
        bucketize("running_mfe_from_entry_atr", MFE_BUCKETS, "mfe_bucket"),
        bucketize("drawdown_from_running_max_atr", DD_BUCKETS, "dd_bucket"),
    )


def race_exprs() -> list[pl.Expr]:
    """Race probabilities.

    The denominator is EVERY observation in the group, including those where
    neither barrier was touched before the natural terminal. That is the
    conservative reading: an unresolved race is not a favorable one. The
    resolved-only rate and the unresolved share are both carried so the reader
    can move between the two, and the optimistic bound folds the same-bar
    ambiguities back into the favorable side.
    """
    out = []
    for name, col in KEY_RACES:
        fav = (pl.col(col) == "FAVORABLE")
        unres = (pl.col(col) == "UNRESOLVED")
        amb = pl.col(col + "_ambiguous")
        out += [
            fav.mean().alias(name),
            (fav | amb).mean().alias(name + "_optimistic"),
            unres.mean().alias(name + "_unresolved"),
            (fav.sum() / (~unres).sum()).alias(name + "_of_resolved"),
        ]
    return out


def metric_block() -> list[pl.Expr]:
    """The forward-opportunity metric set shared by Phases 5-9."""
    return [
        pl.len().alias("n_obs"),
        pl.col("regime_id").n_unique().alias("n_unique_trades"),
        pl.col("forward_mfe_atr").median().alias("fwd_mfe_median"),
        pl.col("forward_mfe_atr").mean().alias("fwd_mfe_mean"),
        pl.col("forward_mfe_atr").quantile(0.75).alias("fwd_mfe_p75"),
        pl.col("forward_mae_atr").median().alias("fwd_mae_median"),
        pl.col("forward_mae_atr").mean().alias("fwd_mae_mean"),
        pl.col("forward_mae_atr").quantile(0.90).alias("fwd_mae_p90"),
        *race_exprs(),
        pl.col("forward_net_to_nat_exit_atr").mean().alias("nat_exit_ret_from_now_mean"),
        pl.col("forward_net_to_nat_exit_atr").median().alias("nat_exit_ret_from_now_median"),
        pl.col("forward_net_to_unc_exit_atr").mean().alias("unc_exit_ret_from_now_mean"),
        pl.col("another_favorable_extreme").mean().alias("p_another_extreme"),
        pl.col("cv_stop_live_atr").mean().alias("mean_cv_stop_live"),
        pl.col("cv_stop_live_atr").median().alias("median_cv_stop_live"),
        pl.col("cv_unconstrained_atr").mean().alias("mean_cv_unconstrained"),
        (pl.col("cv_stop_live_atr") < 0).mean().alias("pct_cv_negative"),
        pl.col("alive_stop_live").mean().alias("pct_alive_stop_live"),
        pl.col("running_mfe_from_entry_atr").median().alias("state_mfe_median"),
        pl.col("return_from_entry_atr").median().alias("state_ret_median"),
        pl.col("eventual_max_mfe_atr").median().alias("label_eventual_maxmfe_median"),
        pl.col("reached_3_0").mean().alias("label_p_ge3"),
    ]


def slices(df: pl.DataFrame):
    """POOLED, then LONG/SHORT, then each year. Same shape every time."""
    yield "POOLED", "ALL", df
    for s in ("LONG", "SHORT"):
        yield "SIDE", s, df.filter(pl.col("side") == s)
    for y in range(2021, 2026):
        yield "YEAR", str(y), df.filter(pl.col("entry_year") == y)


def grouped(df: pl.DataFrame, keys: list[str], spec_names: list[tuple]) -> pl.DataFrame:
    """Aggregate over `keys` across every slice, retaining EMPTY cells.

    An empty cell is emitted with `n_obs = 0` and `empty_cell = true` rather than
    vanishing (SPEC §7). A silently missing cell reads as "not applicable"; a
    zero-count cell reads as "we looked and there was nothing there", and only
    the second is true.
    """
    frames = []
    for kind, name, sub in slices(df):
        if sub.height == 0:
            continue
        g = sub.group_by(keys).agg(metric_block())
        full = _full_grid(spec_names, keys)
        g = full.join(g, on=keys, how="left").with_columns(
            pl.col("n_obs").fill_null(0), pl.col("n_unique_trades").fill_null(0))
        g = g.with_columns(empty_cell=pl.col("n_obs") == 0,
                           slice_kind=pl.lit(kind), slice=pl.lit(name))
        frames.append(g)
    out = pl.concat(frames, how="vertical_relaxed")
    return out.select(["slice_kind", "slice", *keys,
                       *[c for c in out.columns if c not in
                         ("slice_kind", "slice", *keys)]])


def _full_grid(spec_names: list[tuple], keys: list[str]) -> pl.DataFrame:
    grid = pl.DataFrame({keys[0]: [n for n, *_ in spec_names[0]]})
    for k, spec in zip(keys[1:], spec_names[1:]):
        grid = grid.join(pl.DataFrame({k: [n for n, *_ in spec]}), how="cross")
    return grid


def bootstrap_ci(values: np.ndarray, n_boot: int = 1000, seed: int = 20260811):
    """Percentile CI on the mean. Rows handed in are ONE PER TRADE (SPEC D8).

    Because each trade contributes at most one row to the array, resampling rows
    IS resampling trades -- the cluster structure is handled by the construction
    of the input, not by a correction afterwards.
    """
    v = values[np.isfinite(values)]
    if v.size < 10:
        return None, None
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, v.size, size=(n_boot, v.size))
    means = v[idx].mean(axis=1)
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))
