"""Phase 5: the concrete E0/E1/S1-S7 policy grid, population-agnostic
(same configs apply to both studies; each study supplies its own
frozen model/table via StopPolicyEngine).

Documented choices not pinned exactly by the study spec:
  - E1 "high weakness" operationalized as decile >= 9 (top 20%).
  - S7's protected-profit floor operationalized as breakeven
    (protect_floor_atr=0.0), the standard conservative choice absent a
    spec-specified value.
  - S2's persistence requirement: unspecified in the spec, so left at
    the default (first_touch is enough), matching S1/S4/S6/S7. Only
    S3 and S5 explicitly require 10s persistence per the spec text.

E0 is NOT in this grid -- it needs no policy engine at all (the
existing baseline strategies already implement it exactly).
"""
from __future__ import annotations
from studies._shared_exit_mgmt.stop_policy import StopPolicyConfig

E1 = StopPolicyConfig(name="E1", direct_exit_decile=9)

_S_BASE = [
    ("S1", dict(arm_decile=6, percentile=95)),
    ("S2", dict(arm_decile=6, tighten_decile=8, percentile=90)),
    ("S3", dict(arm_decile=7, percentile=95, require_persistence_s=10.0)),
    ("S4", dict(arm_decile=6, tighten_decile=8, terminal_tighten_decile=9,
                    percentile=90)),
    ("S5", dict(arm_decile=6, tighten_decile=8, terminal_tighten_decile=9,
                    percentile=90, require_persistence_s=10.0)),
    ("S6", dict(arm_decile=6, tighten_decile=8, terminal_tighten_decile=9,
                    percentile=90, ratchet_only=True)),
    ("S7", dict(arm_decile=6, tighten_decile=8, terminal_tighten_decile=9,
                    percentile=90, reversible_with_floor=True,
                    protect_floor_atr=0.0)),
]

POLICY_GRID: dict[str, StopPolicyConfig] = {"E1": E1}
for base_name, kwargs in _S_BASE:
    for anchor in ("checkpoint", "mfe"):
        name = f"{base_name}_{anchor}"
        POLICY_GRID[name] = StopPolicyConfig(
            name=name, anchor_mode=anchor, **kwargs)
