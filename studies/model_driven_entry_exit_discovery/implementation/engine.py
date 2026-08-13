"""Causal path-simulation engine over the regime-complete canonical store.

Design notes that matter for correctness:

* The trade lifecycle is **derived**, never labelled. `next_regime_start_after`
  resolves the direction flip and the opposing exit by searching the regime
  sequence, so no rule references a literal R+1 / R+2.
* Every decision uses only bars at or before the decision second. A stop touch is
  detected on a completed 1s bar and fills at the **following** bar's open; the
  trigger price is never credited.
* Trades are intraday: entries are RTH-only (both models are unscored in ETH) and
  any open position is forced flat at the 15:00 CT session close.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[3]
STORE = ROOT / "data/canonical/regime_complete_v1"
NS = 1_000_000_000
CT = "America/Chicago"

TICK = 0.25
POINT_VALUE = 20.0
# Frozen: 2 ticks round-turn, charged per completed trade and per reentry.
COST_POINTS = 2 * TICK
FLAT_POINTS = 0.125          # |return| below this is flat, per the accepted contract
RTH_CLOSE_MINUTE = 15 * 60

# Outcome codes
OPEN, TARGET, STOP, TRAIL, GIVEBACK, SCORE_EXIT, OPPOSING_FLIP, SESSION_CLOSE, CENSORED = (
    "OPEN", "TARGET", "STOP", "TRAIL", "GIVEBACK", "SCORE_EXIT",
    "OPPOSING_FLIP", "SESSION_CLOSE", "CENSORED",
)


# --------------------------------------------------------------------- data


@dataclass
class MarketData:
    """RTH one-second path as contiguous arrays, plus a day index.

    Only RTH is loaded: entries are RTH-only and every trade is forced flat at
    the session close, so no ETH bar can ever be part of a trade.
    """

    ts: np.ndarray            # path_init_ns, sorted, unique
    open_: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    day_close_ns: np.ndarray  # per bar: the 15:00 CT boundary of its session

    @property
    def n(self) -> int:
        return self.ts.size

    def index_at_or_after(self, ts_ns: int) -> int:
        return int(np.searchsorted(self.ts, ts_ns, side="left"))

    def index_strictly_after(self, ts_ns: int) -> int:
        return int(np.searchsorted(self.ts, ts_ns, side="right"))


@dataclass
class RegimeIndex:
    """Regime starts and directions, for programmatic lifecycle derivation."""

    start_ns: np.ndarray      # sorted
    direction: np.ndarray

    def next_start_after(
        self, ts_ns: int, direction: int | None = None, inclusive: bool = True
    ) -> int | None:
        """First regime start at or after `ts_ns`, optionally of a direction.

        This is how the direction flip and the opposing exit are resolved. No
        caller may substitute a hard-coded sequence offset.

        `inclusive=True` is the causally correct default. A 1s checkpoint with
        `ts_init == T` is dispatched *before* the 1m bar with `ts_init == T`
        (the project's 1s-before-1m convention), so a regime flip stamped T is
        knowable only after a decision made at T -- it is genuinely in the
        trade's future.

        Searching strictly after skipped exactly those boundary flips, and then
        matched a much later regime of the same direction instead: for an entry
        at 09:53:00 whose confirming flip was also stamped 09:53:00, the confirm
        resolved 28 minutes late and the *opposing* regime in between was
        mislabelled as the exit. 69 of 3,415 top_1 trades were affected.
        """
        side = "left" if inclusive else "right"
        i = int(np.searchsorted(self.start_ns, ts_ns, side=side))
        if direction is None:
            return int(self.start_ns[i]) if i < self.start_ns.size else None
        while i < self.start_ns.size:
            if self.direction[i] == direction:
                return int(self.start_ns[i])
            i += 1
        return None


def _chicago_minute(col: str) -> pl.Expr:
    local = pl.from_epoch(pl.col(col), time_unit="ns").dt.convert_time_zone(CT)
    return local.dt.hour().cast(pl.Int32) * 60 + local.dt.minute().cast(pl.Int32)


def load_market(years: tuple[int, ...] | None = None) -> MarketData:
    lf = (
        pl.scan_parquet(STORE / "canonical_regime_paths_all.parquet")
        .filter(pl.col("session") == "RTH")
        .select("path_init_ns", "open", "high", "low", "close", "entry_year")
    )
    if years:
        lf = lf.filter(pl.col("entry_year").is_in(list(years)))
    df = lf.sort("path_init_ns").unique(subset=["path_init_ns"], keep="first").collect()
    if df.height == 0:
        raise RuntimeError("no RTH path rows; check the session column")

    ts = df["path_init_ns"].to_numpy()
    local = pl.from_epoch(pl.col("path_init_ns"), time_unit="ns").dt.convert_time_zone(CT)
    day_close = df.select(
        (
            local.dt.truncate("1d").dt.offset_by(f"{RTH_CLOSE_MINUTE}m")
            .dt.convert_time_zone("UTC")
            .dt.epoch(time_unit="ns")
        ).alias("d")
    )["d"].to_numpy()
    return MarketData(
        ts=ts,
        open_=df["open"].to_numpy(),
        high=df["high"].to_numpy(),
        low=df["low"].to_numpy(),
        close=df["close"].to_numpy(),
        day_close_ns=day_close,
    )


def load_regimes() -> RegimeIndex:
    df = (
        pl.scan_parquet(STORE / "canonical_regimes_all.parquet")
        .select("regime_start_decision_ns", "regime_direction")
        .sort("regime_start_decision_ns")
        .collect()
    )
    return RegimeIndex(
        start_ns=df["regime_start_decision_ns"].to_numpy(),
        direction=df["regime_direction"].to_numpy(),
    )


# ------------------------------------------------------------------ policy


@dataclass(frozen=True)
class ExitPolicy:
    """Causal exit rules. `None` disables a component."""

    stop_atr: float | None = 1.00
    target_atr: float | None = None
    trail_atr: float | None = None          # trail this far below running MFE
    giveback_frac: float | None = None      # exit after surrendering this share of MFE
    mfe_floor_atr: float | None = None      # arm giveback/trail only past this MFE
    breakeven_at_atr: float | None = None   # move stop to entry once MFE >= this
    time_stop_s: int | None = None
    hold_to_opposing_flip: bool = True      # else exit at direction flip
    name: str = "unnamed"


@dataclass
class Trade:
    entry_ns: int
    exit_ns: int | None
    direction: int
    entry_price: float
    exit_price: float | None
    atr: float
    outcome: str
    mfe_atr: float
    mae_atr: float
    bars: int
    ambiguous: bool = False
    regime_id: str = ""
    year: int = 0
    threshold_label: str = ""
    entry_probability: float = float("nan")
    reentry_index: int = 0
    extra: dict = field(default_factory=dict)

    @property
    def gross_atr(self) -> float:
        if self.exit_price is None:
            return float("nan")
        pts = (self.exit_price - self.entry_price) * self.direction
        return 0.0 if abs(pts) < FLAT_POINTS else pts / self.atr

    @property
    def net_atr(self) -> float:
        g = self.gross_atr
        return g if np.isnan(g) else g - COST_POINTS / self.atr


# -------------------------------------------------------------- simulation


def simulate(
    market: MarketData,
    regimes: RegimeIndex,
    entry_ns: int,
    direction: int,
    entry_price: float,
    atr: float,
    policy: ExitPolicy,
) -> Trade:
    """Simulate one trade forward from `entry_ns` under `policy`.

    Ordering within a second is not resolvable from OHLC, so a bar that could
    satisfy both an adverse and a favorable trigger is flagged `ambiguous` and
    resolved adversely (the conservative bound). Callers report both bounds.
    """
    start = market.index_strictly_after(entry_ns)
    if start >= market.n or atr <= 0 or not np.isfinite(atr):
        return Trade(entry_ns, None, direction, entry_price, None, atr, CENSORED,
                     0.0, 0.0, 0)

    # Lifecycle, derived rather than labelled.
    flip_ns = regimes.next_start_after(entry_ns, direction)          # thesis confirms
    opposing_ns = regimes.next_start_after(entry_ns, -direction)     # fallback exit
    session_close_ns = int(market.day_close_ns[start])

    regime_exit_ns = opposing_ns if policy.hold_to_opposing_flip else flip_ns
    horizon_ns = session_close_ns
    if regime_exit_ns is not None:
        horizon_ns = min(horizon_ns, regime_exit_ns)
    if policy.time_stop_s is not None:
        horizon_ns = min(horizon_ns, entry_ns + policy.time_stop_s * NS)

    # Only RTH bars are loaded, so consecutive indices jump the overnight gap:
    # 14:59:59 is immediately followed by the next session's 08:30:00. A horizon
    # lookup alone therefore runs straight through the gap and collects the
    # overnight move, which the forced 15:00 flat exists to exclude. Clamp the
    # window to bars belonging to the entry's own session.
    session_end = int(
        np.searchsorted(market.day_close_ns, market.day_close_ns[start], side="right")
    )
    end = min(market.index_at_or_after(horizon_ns) + 1, session_end, market.n)
    if end <= start:
        return Trade(entry_ns, None, direction, entry_price, None, atr, CENSORED,
                     0.0, 0.0, 0)

    hi = market.high[start:end]
    lo = market.low[start:end]
    ts = market.ts[start:end]

    favorable = (hi - entry_price) * direction if direction > 0 else (entry_price - lo)
    adverse = (entry_price - lo) if direction > 0 else (hi - entry_price)
    run_mfe = np.maximum.accumulate(np.maximum(favorable, 0.0)) / atr
    run_mae = np.maximum.accumulate(np.maximum(adverse, 0.0)) / atr

    stop_hit = _first_true(run_mae >= policy.stop_atr) if policy.stop_atr else -1
    target_hit = (
        _first_true(run_mfe >= policy.target_atr) if policy.target_atr else -1
    )

    current = favorable / atr

    be_hit = (
        _first_true(run_mfe >= policy.breakeven_at_atr)
        if policy.breakeven_at_atr
        else -1
    )
    if be_hit >= 0:
        # Once armed, the stop sits at the entry price: the trade closes when
        # favorable excursion returns to zero or below.
        #
        # This previously tested `run_mae >= 0.0`, which is a tautology --
        # `run_mae` is a running maximum floored at zero, so it is non-negative
        # at every index. Every armed trade was force-closed one bar after
        # arming regardless of price, which made the breakeven family untestable
        # and understated it. Found by lookahead-auditor pass 1.
        after = np.arange(current.size) > be_hit
        be_stop = _first_true(after & (current <= 0.0))
        if be_stop >= 0 and (stop_hit < 0 or be_stop < stop_hit):
            stop_hit = be_stop

    give_hit = -1
    if policy.giveback_frac or policy.trail_atr:
        armed = (
            run_mfe >= policy.mfe_floor_atr
            if policy.mfe_floor_atr
            else run_mfe > 0
        )
        if policy.giveback_frac:
            give = armed & (current <= run_mfe * (1.0 - policy.giveback_frac))
            give_hit = _first_true(give)
        if policy.trail_atr:
            trail = armed & (current <= run_mfe - policy.trail_atr)
            t_hit = _first_true(trail)
            if t_hit >= 0 and (give_hit < 0 or t_hit < give_hit):
                give_hit = t_hit

    candidates = [
        (stop_hit, STOP), (target_hit, TARGET), (give_hit, GIVEBACK),
    ]
    live = [(i, tag) for i, tag in candidates if i >= 0]
    ambiguous = len({i for i, _ in live}) < len(live)

    if live:
        idx, outcome = min(live, key=lambda p: (p[0], p[1] != STOP))
        fill = idx + 1
        # The fill bar must belong to the same session. A trigger on the final
        # bar of the day has no next open to fill against; crediting the next
        # session's open would import the overnight gap.
        if start + fill >= session_end or start + fill >= market.n:
            exit_price = float(market.close[end - 1])
            exit_ns = int(market.ts[end - 1])
            outcome = SESSION_CLOSE
        else:
            exit_price = float(market.open_[start + fill])
            exit_ns = int(market.ts[start + fill])
    else:
        idx = ts.size - 1
        exit_price = float(market.close[start + idx])
        exit_ns = int(ts[idx])
        if regime_exit_ns is not None and exit_ns >= regime_exit_ns - NS:
            outcome = OPPOSING_FLIP if policy.hold_to_opposing_flip else SCORE_EXIT
        elif policy.time_stop_s is not None and exit_ns >= entry_ns + policy.time_stop_s * NS:
            outcome = SCORE_EXIT
        else:
            outcome = SESSION_CLOSE

    return Trade(
        entry_ns=entry_ns, exit_ns=exit_ns, direction=direction,
        entry_price=entry_price, exit_price=exit_price, atr=atr, outcome=outcome,
        mfe_atr=float(run_mfe[idx]), mae_atr=float(run_mae[idx]), bars=idx + 1,
        ambiguous=ambiguous,
    )


def _first_true(mask: np.ndarray) -> int:
    hits = np.flatnonzero(mask)
    return int(hits[0]) if hits.size else -1
