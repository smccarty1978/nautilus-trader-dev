"""Phase 5: parameterized stop-management policy, expressed as a single
mechanism configured differently for E1/S1-S7 rather than 7 separate
classes -- reduces audit surface (one causal mechanism, many frozen
configs) per the project's existing config-flag convention (e.g.
CollectorV2Config).

CAUSALITY: the model, decile edges, and conditional recovery-MAE
tables are all FROZEN artifacts fit on train+validation only (Phase
3/4). At runtime this class only performs a lookup against those
frozen tables using the CURRENT checkpoint's own state (decile,
persistence bucket, score path) -- no retraining, no future
information, exactly like the existing frozen-skip-gate pattern in
collectors/collector_v2/strategy.py's `_is_policy_skip`.

State machine (per open trade):
  NONE -> ARMED (at arm_decile) -> TIGHTENED (at tighten_decile)
       -> TERMINAL (at terminal_tighten_decile)

  User-confirmed 2026-07-11: state is MONOTONIC (forward-only, never
  loosens) for every policy EXCEPT S7. A stop, once armed/tightened,
  must never give back protection purely because the model's
  weakness estimate ticked down a decile. This means `ratchet_only`
  (S6) is now mechanically equivalent to the default (S1-S5) --
  kept as an explicit config flag for self-documentation; expect S6
  and S4 to be statistically indistinguishable in Phase 6/7 results,
  and report that as a finding rather than a bug.
  reversible_with_floor=True (S7) is the ONLY exception: state MAY
  loosen by exactly one level after the weakness score improves or a
  new MFE is set, but the resulting stop price can never move below
  `protect_floor_atr` ATR of profit (entry price, i.e. breakeven, by
  default -- documented choice, not specified exactly by the study
  spec).

Each state has an associated stop DISTANCE (in ATR units) read from
the frozen conditional_recovery_mae_tables at (decile,
persistence_bucket, score_path), using the configured percentile.
anchor_mode="checkpoint": stop_price is placed relative to the price
    AT THE MOMENT OF ARMING/TIGHTENING (fixed at that instant).
anchor_mode="mfe": stop_price is placed relative to the trade's
    MFE peak PRICE level (updates if MFE keeps growing before the
    stop triggers).
"""
from __future__ import annotations
from dataclasses import dataclass, field
import pandas as pd
import numpy as np

STATE_NONE, STATE_ARMED, STATE_TIGHTENED, STATE_TERMINAL = 0, 1, 2, 3


@dataclass(frozen=True)
class StopPolicyConfig:
    name: str
    arm_decile: int = 0            # 0 = policy disabled (E0)
    tighten_decile: int = 0        # 0 = no tighten level
    terminal_tighten_decile: int = 0  # 0 = no terminal level
    percentile: int = 90           # which recovery-MAE percentile to use (90 or 95)
    require_persistence_s: float = 0.0  # 0 = first_touch is enough; 10.0 = require 10s bucket+
    ratchet_only: bool = False     # S6
    reversible_with_floor: bool = False  # S7
    protect_floor_atr: float = 0.0  # ATR of guaranteed profit floor for S7 (0 = breakeven)
    anchor_mode: str = "checkpoint"  # "checkpoint" | "mfe"
    direct_exit_decile: int = 0    # E1: exit immediately at this decile (0 = disabled)


class StopPolicyEngine:
    """Holds the frozen model + decile edges + conditional table for
    ONE population, and exposes a causal per-checkpoint decision
    function usable both inside the NT strategy (Phase 6) and inside
    any offline replay/audit tooling."""

    def __init__(self, model, feature_cols: list[str], decile_edges: np.ndarray,
                    cond_table: pd.DataFrame):
        self.model = model
        self.feature_cols = feature_cols
        self.decile_edges = decile_edges
        # Raw LightGBM booster, bypassing the sklearn wrapper's
        # DataFrame-construction + validation overhead entirely --
        # measured ~16x faster per call (3.5ms -> 0.22ms), which
        # matters at tens of millions of per-1s-bar calls across the
        # Phase 6 grid. Numerically verified identical to
        # model.predict_proba(X)[:, 1] (max abs diff 0.0 over 2000
        # random feature vectors) before switching -- LightGBM's
        # Booster.predict() for a binary objective already returns
        # sigmoid-transformed probabilities, not raw margins.
        self._booster = model.booster_
        # Index the conditional table for O(1) lookup by
        # (decile, persistence_bucket, score_path).
        self._table = cond_table.set_index(
            ["decile", "persistence_bucket", "score_path"])

    def score(self, feature_row: dict) -> float:
        X = np.array([[feature_row[c] for c in self.feature_cols]],
                        dtype=np.float64)
        return float(self._booster.predict(X)[0])

    def decile_of(self, prob: float) -> int:
        # MUST match pd.cut(..., right=True)'s tie convention exactly
        # (train_model.py's offline decile assignment) -- pd.cut bins
        # are left-open/right-closed, (edges[i], edges[i+1]], so an
        # exact tie at an interior edge belongs to the LOWER bin.
        # side="left" reproduces this (side="right" pushes exact ties
        # into the next decile up -- a real, recurring bug fixed here
        # per the 2026-07-11 pre-execution audit, since tree-ensemble
        # predict_proba output ties at low-variance early checkpoints
        # constantly, not a measure-zero corner case).
        idx = int(np.searchsorted(self.decile_edges, prob, side="left"))
        return max(1, min(10, idx))

    def lookup_recovery_mae(self, decile: int, persistence_bucket: str,
                                 score_path: str, percentile: int,
                                 anchor_mode: str) -> float | None:
        key_col = (f"recovery_MAE_from_checkpoint_p{percentile}"
                       if anchor_mode == "checkpoint"
                       else f"recovery_MAE_from_MFE_p{percentile}")
        try:
            row = self._table.loc[(decile, persistence_bucket, score_path)]
        except KeyError:
            return None
        val = row[key_col]
        if val != val:  # NaN
            return None
        return float(val)


def _state_for_decile(cfg: StopPolicyConfig, decile: int) -> int:
    if cfg.terminal_tighten_decile and decile >= cfg.terminal_tighten_decile:
        return STATE_TERMINAL
    if cfg.tighten_decile and decile >= cfg.tighten_decile:
        return STATE_TIGHTENED
    if cfg.arm_decile and decile >= cfg.arm_decile:
        return STATE_ARMED
    return STATE_NONE


def decile_for_state(cfg: StopPolicyConfig, state: int) -> int:
    return {STATE_TERMINAL: cfg.terminal_tighten_decile,
               STATE_TIGHTENED: cfg.tighten_decile,
               STATE_ARMED: cfg.arm_decile}.get(state, 0)


def next_policy_state(
    cfg: StopPolicyConfig, current_state: int, decile: int,
    persistence_bucket: str, score_improved: bool, new_mfe_this_bar: bool,
) -> int:
    """Pure function: given the policy config and current checkpoint's
    causal state, returns the new state. No side effects, no lookahead
    -- only reads the CURRENT checkpoint's own (already-causal) fields.

    User-confirmed 2026-07-11 (pre-execution audit follow-up): a stop,
    once armed/tightened, must NEVER loosen back out purely because the
    model's momentary weakness estimate ticked down a decile -- this
    overrides the study spec's original framing of S1-S5 as
    "naturally re-deriving" state each checkpoint (which would have
    allowed already-earned protection to be given back). The only
    loosening path in this whole grid is S7's explicit,
    floor-respecting, one-level, improvement-gated exception.

    Consequence: S6 ("ratchet-only version of S4") is now MECHANICALLY
    IDENTICAL to S4 in state-transition behavior, since S1-S5 already
    never loosen under this rule. `cfg.ratchet_only` is kept as an
    explicit, self-documenting flag rather than removed; Phase 6/7
    results are expected to show S6 statistically indistinguishable
    from S4, and that equivalence should be reported as a finding
    (confirms the loosening question was the only thing separating
    them), not hidden.
    """
    if cfg.require_persistence_s > 0 and persistence_bucket == "first_touch":
        return current_state  # not persisted long enough to progress forward

    target_state = _state_for_decile(cfg, decile)

    if cfg.reversible_with_floor:
        if target_state >= current_state:
            return target_state
        # Only allowed to loosen by exactly one level, and only on
        # improvement/new MFE (caller passes score_improved/new_mfe).
        if score_improved or new_mfe_this_bar:
            return max(target_state, current_state - 1)
        return current_state

    # Default (S1-S6): monotonic ratchet, forward-only.
    return max(current_state, target_state)
