"""tracker.price_level.failed_breakout -- failed-breakout episodes at finalized reference levels.

Completed 1-minute bars, RTH only. The full contract (eligibility, arming, episode start/update, failure,
expiry, invalidation, tie-break, resets) is the proposal
``research_workflow/capabilities/proposals/tracker.price_level.failed_breakout.yaml``; in short, per level L
(resistance side +1, support side -1):

* eligible  -- L was published by the canonical level provider after the PREVIOUS completed bar;
* armed     -- the previous completed bar closed at or on the near side of L;
* breach    -- an armed level and a bar trading min_breach_points beyond L opens an episode (extreme = that
               bar's high / low; a close beyond L is not required);
* failure   -- a bar of the episode (the breach bar included) closes strictly back on the near side of L no later
               than episode_start_ts + max_episode_minutes: the event, stamped at that bar's close, with the
               episode extreme (failure bar included) frozen as ``stop_reference_price``;
* otherwise -- ACCEPTED (no event) until a bar closes back at or on the near side of L.

Levels come from ``GenericPriceLevelProvider`` (the provider behind the ``price_level_*`` features) fed the same
bars with the same RTH rule, so a level here is the same number a study's ``price_level_value`` feature reads.
"""
from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

from features.trackers.base import BarView, BaseBinding
from features.trackers.generic_price_levels import GenericPriceLevelProvider
from features.trackers.price_levels import trading_day_key

NS = 1_000_000_000
EPS = 1e-9  # price comparisons on a tick grid; absorbs float noise only

# short id -> (canonical PriceLevelTracker level name, side): +1 resistance (breach above), -1 support (breach below)
LEVELS: Dict[str, tuple] = {
    "pdh": ("prior_day_high", 1),
    "pdl": ("prior_day_low", -1),
    "onh": ("overnight_high_final", 1),
    "onl": ("overnight_low_final", -1),
    "orh": ("opening_range_30m_high_final", 1),
    "orl": ("opening_range_30m_low_final", -1),
}
DEFAULT_LEVELS = ("pdh", "pdl", "onh", "onl", "orh", "orl")

UNAVAILABLE, UNARMED, ARMED, BREACHED, ACCEPTED, NOT_TRACKED = (
    "UNAVAILABLE", "UNARMED", "ARMED", "BREACHED", "ACCEPTED", "NOT_TRACKED")

PRIMARY_FIELDS = (
    "event", "event_dir", "event_level", "event_level_price", "event_level_available", "breach_dir",
    "episode_start_ts", "episode_bars", "episode_extreme", "stop_reference_price", "event_ts",
    "event_seq_level", "n_levels_fired", "conflict", "last_bar_close_ts",
)
LEVEL_SUFFIXES = ("_price", "_available", "_state", "_episode_extreme", "_event")
FIELDS = PRIMARY_FIELDS + tuple(f"{lvl}{sfx}" for lvl in DEFAULT_LEVELS for sfx in LEVEL_SUFFIXES)


class _Episode:
    __slots__ = ("state", "level", "start_ts", "extreme", "bars", "seq")

    def __init__(self) -> None:
        self.state = UNAVAILABLE
        self.level: Optional[float] = None      # the level price the episode was opened against
        self.start_ts: Optional[int] = None     # breach bar's interval open
        self.extreme: Optional[float] = None
        self.bars = 0
        self.seq = 0                            # failed-breakout events at this level this RTH session

    def clear(self, state: str) -> None:
        self.state, self.level, self.start_ts, self.extreme, self.bars = state, None, None, None, 0


class PriceLevelFailedBreakoutBinding(BaseBinding):
    CAPABILITY = "tracker.price_level.failed_breakout"
    PARAMS = {"min_breach_points": 0.5, "max_episode_minutes": 5, "levels": list(DEFAULT_LEVELS)}
    INPUTS = {"bars": "stream"}
    FIELDS = FIELDS
    EVENTS = ("failed_breakout",)
    WARMUP_BARS = 0
    CADENCE = "per_source_bar"

    def __init__(self, params: Mapping[str, Any], inputs: Mapping[str, Any]) -> None:
        super().__init__(params, inputs)
        levels = [str(x) for x in (self.params["levels"] or ())]
        if not levels or len(set(levels)) != len(levels) or any(x not in LEVELS for x in levels):
            raise ValueError(f"{self.CAPABILITY}: levels must be a non-empty, duplicate-free subset of {list(LEVELS)}")
        self.min_breach = float(self.params["min_breach_points"])
        if not self.min_breach > 0:
            raise ValueError(f"{self.CAPABILITY}: min_breach_points must be > 0")
        minutes = int(self.params["max_episode_minutes"])
        if minutes < 1 or minutes != float(self.params["max_episode_minutes"]):
            raise ValueError(f"{self.CAPABILITY}: max_episode_minutes must be a positive integer")
        self.levels = tuple(levels)
        self.max_episode_ns = minutes * 60 * NS
        self._provider = GenericPriceLevelProvider()
        self._episodes = {lvl: _Episode() for lvl in LEVELS}
        for lvl in LEVELS:
            if lvl not in self.levels:
                self._episodes[lvl].state = NOT_TRACKED
        self._known: Dict[str, Optional[float]] = {lvl: None for lvl in LEVELS}   # published after the previous bar
        self._prev_close: Optional[float] = None
        self._rth_day: Optional[str] = None
        for f in FIELDS:
            setattr(self, f, None)
        self._clear_bar_fields()
        self._publish_levels()

    # -- host entry point ---------------------------------------------------------------------------------
    def on_bar(self, input_key: str, bar: BarView) -> None:
        if input_key != "bars":
            return
        from utils.session_boundaries import is_rth_completed_bar_1m

        is_rth = bool(is_rth_completed_bar_1m(int(bar.ts_init)))
        if not is_rth:
            self._reset_session()
        else:
            day = trading_day_key(int(bar.ts_init))
            if day != self._rth_day:
                self._reset_session()
                self._rth_day = day
        self.step(bar, self._known, self._prev_close, is_rth=is_rth)
        # the level provider sees the bar only AFTER the episode logic: a level published at this bar's close
        # is usable from the next bar on
        self._provider.update_completed_bar(ts_avail=int(bar.ts_init), open_px=float(bar.open), high=float(bar.high),
                                            low=float(bar.low), close=float(bar.close), is_rth=is_rth)
        # the provider's raw level prices -- exactly what its snapshot publishes as <name>_price (pinned by
        # test_levels_equal_the_provider_snapshot), without the per-bar cluster/density computation
        raw = self._provider._tracker._raw_levels()
        self._known = {lvl: _finite(raw[name][0]) for lvl, (name, _side) in LEVELS.items()}
        self._prev_close = float(bar.close)
        self._publish_levels()

    # -- episode logic (pure in its inputs; unit tests drive it directly) ----------------------------------
    def step(self, bar: BarView, known: Mapping[str, Optional[float]], prev_close: Optional[float], *,
             is_rth: bool) -> None:
        """Advance every tracked level by one completed bar. ``known`` = level prices published at or before the
        bar's open; ``prev_close`` = the previous completed bar's close."""
        self._clear_bar_fields()
        self.last_bar_close_ts = int(bar.ts_init)
        if not is_rth:
            return
        fired = []
        for lvl in self.levels:
            ep = self._episodes[lvl]
            side = LEVELS[lvl][1]
            level = _finite(known.get(lvl))
            # 0. availability / invalidation
            if level is None:
                ep.clear(UNAVAILABLE)
                continue
            if ep.state == BREACHED and abs(level - ep.level) > EPS:
                ep.clear(UNARMED)                                       # the level moved under the episode
            elif ep.state == UNAVAILABLE:
                ep.clear(UNARMED)
            # 1. lazy expiry (a missing minute cannot extend an episode)
            if ep.state == BREACHED and int(bar.ts_init) > ep.start_ts + self.max_episode_ns:
                ep.clear(ACCEPTED)
            # 2. arming by the previous completed bar's close
            if ep.state in (UNARMED, ACCEPTED) and prev_close is not None and side * (prev_close - level) <= EPS:
                ep.clear(ARMED)
            # 3. breach opens an episode on this bar
            probe = float(bar.high) if side > 0 else float(bar.low)
            if ep.state == ARMED and side * (probe - level) >= self.min_breach - EPS:
                ep.state, ep.level, ep.start_ts, ep.extreme, ep.bars = BREACHED, level, int(bar.ts_event), probe, 0
            if ep.state != BREACHED:
                continue
            # 4. update the extreme (this bar included), then the failure / expiry test
            ep.extreme = max(ep.extreme, probe) if side > 0 else min(ep.extreme, probe)
            ep.bars += 1
            if side * (float(bar.close) - level) < -EPS:
                ep.seq += 1
                fired.append((lvl, side, ep.level, ep.start_ts, ep.bars, ep.extreme, ep.seq))
                setattr(self, f"{lvl}_event", 1)
                setattr(self, f"{lvl}_episode_extreme", ep.extreme)
                ep.clear(ARMED)                                         # the failure close re-arms the level
            elif int(bar.ts_init) >= ep.start_ts + self.max_episode_ns:
                ep.clear(ACCEPTED)
        self.n_levels_fired = len(fired)
        if not fired:
            return
        if len({side for _l, side, *_r in fired}) > 1:
            self.conflict = 1                                           # opposite-direction failures on one bar
            return
        lvl, side, level, start_ts, n_bars, extreme, seq = fired[0]     # declared `levels` order = priority
        self.event, self.event_dir, self.breach_dir = 1, -side, side
        self.event_level, self.event_level_price, self.event_level_available = lvl, level, 1
        self.episode_start_ts, self.episode_bars, self.episode_extreme = start_ts, n_bars, extreme
        self.stop_reference_price, self.event_ts, self.event_seq_level = extreme, int(bar.ts_init), seq
        self.emit("failed_breakout", {"ts": int(bar.ts_init), "direction": -side, "level": lvl, "level_price": level,
                                      "stop_reference_price": extreme, "episode_start_ts": start_ts})

    # -- helpers --------------------------------------------------------------------------------------------
    def _reset_session(self) -> None:
        for lvl in self.levels:
            self._episodes[lvl].clear(UNAVAILABLE)
            self._episodes[lvl].seq = 0
        self._rth_day = None

    def _clear_bar_fields(self) -> None:
        for f in PRIMARY_FIELDS:
            setattr(self, f, None)
        self.event, self.event_dir, self.n_levels_fired, self.conflict = 0, 0, 0, 0
        for lvl in LEVELS:
            setattr(self, f"{lvl}_event", 0)
            setattr(self, f"{lvl}_episode_extreme", None)

    def _publish_levels(self) -> None:
        for lvl in LEVELS:
            ep = self._episodes[lvl]
            px = self._known.get(lvl)
            setattr(self, f"{lvl}_price", px)
            setattr(self, f"{lvl}_available", 1 if px is not None else 0)
            setattr(self, f"{lvl}_state", ep.state)
            if ep.state == BREACHED:
                setattr(self, f"{lvl}_episode_extreme", ep.extreme)


def _finite(x: Any) -> Optional[float]:
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v and v not in (float("inf"), float("-inf")) else None
