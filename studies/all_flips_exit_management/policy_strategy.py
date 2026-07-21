"""ALL_FLIPS strategy variant with the Phase 5 stop-policy grid wired
in. Entry mechanics are UNCHANGED from AllFlipsStrategy -- only the
exit side gains the policy hook.
"""
from __future__ import annotations

from studies._shared_exit_mgmt.policy_strategy import StopPolicyMixin
from studies.all_flips_exit_management.strategy import (
    AllFlipsStrategy, AllFlipsConfig,
)


class AllFlipsPolicyStrategy(StopPolicyMixin, AllFlipsStrategy):
    pass


class AllFlipsPolicyConfig(AllFlipsConfig, frozen=True):
    pass
