from typing import Dict


class CompletedBarRegistry:
    """Ensures strict causal ordering by tracking completed bars and their close times."""

    def __init__(self):
        # Maps bar_type string to the last processed bar close timestamp (ts_init)
        self.last_completed_ts: Dict[str, int] = {}

    def register_completed_bar(self, bar_type: str, ts_init: int) -> bool:
        """Registers a completed bar close. Returns True if it is strictly newer than the last."""
        last_ts = self.last_completed_ts.get(bar_type, -1)
        if ts_init > last_ts:
            self.last_completed_ts[bar_type] = ts_init
            return True
        return False

    def is_bar_closed(self, bar_type: str, ts_init: int) -> bool:
        """Checks if a bar close timestamp is already registered (fully closed)."""
        return ts_init <= self.last_completed_ts.get(bar_type, -1)
