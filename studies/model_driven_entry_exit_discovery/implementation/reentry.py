"""Stateful reentry.

SPEC 5 requires reentry to be testable and SPEC 8 requires the reentry
state-reset gate to be executed. Both are implemented here even though the
discovery result advances no reentry policy: an unexecuted gate is not a passed
gate, and the headline conclusion should not rest on a mechanism that was never
built.

Each leg is an independent trade charged its own round turn. Legs are strictly
chronological and non-overlapping, and the sequence terminates at the source
regime's terminal boundary or the session close, whichever is first.
"""
from __future__ import annotations

import polars as pl

from .engine import NS, ExitPolicy, Trade, simulate

# Reentry rules the SPEC names. `none` is the control.
RULES = ("none", "after_stop", "score_reset_recross", "cooldown")


def simulate_with_reentry(
    market,
    regimes,
    entry_ns: int,
    direction: int,
    entry_price: float,
    atr: float,
    policy: ExitPolicy,
    scored: pl.DataFrame,
    max_reentries: int = 1,
    rule: str = "after_stop",
    cooldown_observations: int = 3,
    reset_label: str | None = None,
) -> list[Trade]:
    """Return the ordered legs of one reentry sequence.

    The first leg is always the original candidate. A further leg is opened only
    if the previous leg stopped out, the rule's own condition is met, and a true
    score checkpoint exists strictly after the previous exit inside the same
    source regime.
    """
    first = simulate(market, regimes, entry_ns, direction, entry_price, atr, policy)
    first.reentry_index = 0
    legs = [first]
    if rule == "none" or max_reentries <= 0:
        return legs

    # The source regime bounds the sequence: reentry is within the same regime,
    # never a new one. Resolved from the regime index, not a hard-coded offset.
    regime_end = regimes.next_start_after(entry_ns, -direction)

    previous = first
    while len(legs) <= max_reentries:
        if previous.outcome != "STOP" or previous.exit_ns is None:
            break
        after = _next_checkpoint(
            scored, previous.exit_ns, direction, regime_end, rule,
            cooldown_observations, reset_label,
        )
        if after is None:
            break
        leg = simulate(
            market, regimes, after["checkpoint_decision_ns"], direction,
            after["checkpoint_reference_price"], after["atr_at_checkpoint"], policy,
        )
        if leg.exit_ns is None and leg.outcome == "CENSORED":
            break
        leg.reentry_index = len(legs)
        legs.append(leg)
        previous = leg
    return legs


def _next_checkpoint(
    scored: pl.DataFrame,
    after_ns: int,
    direction: int,
    regime_end: int | None,
    rule: str,
    cooldown_observations: int,
    reset_label: str | None,
) -> dict | None:
    """First eligible true score checkpoint strictly after `after_ns`.

    Eligibility is evaluated only on observations at or before their own
    decision timestamp, so no rule can consult the outcome of the leg it opens.
    """
    window = scored.filter(
        (pl.col("checkpoint_decision_ns") > after_ns)
        & (pl.col("direction") == direction)
    )
    if regime_end is not None:
        window = window.filter(pl.col("checkpoint_decision_ns") < regime_end)
    if window.height == 0:
        return None

    window = window.sort("checkpoint_decision_ns")
    if rule == "cooldown":
        if window.height <= cooldown_observations:
            return None
        window = window.slice(cooldown_observations)
    elif rule == "score_reset_recross" and reset_label is not None:
        from .candidates import THRESHOLDS

        bull, bear = THRESHOLDS[reset_label]
        reset = (
            pl.when(pl.col("bullish_in_domain")).then(pl.lit(bull)).otherwise(pl.lit(bear))
        )
        # Require the score to have fallen below the reset level and come back.
        below = window.filter(pl.col("probability") < reset)
        if below.height == 0:
            return None
        first_below = below["checkpoint_decision_ns"][0]
        window = window.filter(
            (pl.col("checkpoint_decision_ns") > first_below)
            & (pl.col("probability") >= reset)
        )
        if window.height == 0:
            return None

    return window.row(0, named=True)
