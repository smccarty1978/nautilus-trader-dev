"""F2_CONFIRMED strategy variant with the Phase 5 stop-policy grid
wired in. Entry mechanics are UNCHANGED from F2ConfirmedStrategy --
only the exit side gains the policy hook.
"""
from __future__ import annotations

from studies._shared_exit_mgmt.policy_strategy import StopPolicyMixin
from studies.f2_confirmed_exit_management.strategy import (
    F2ConfirmedStrategy, F2ConfirmedConfig,
)


class F2ConfirmedPolicyStrategy(StopPolicyMixin, F2ConfirmedStrategy):
    pass


class F2ConfirmedPolicyConfig(F2ConfirmedConfig, frozen=True):
    pass
