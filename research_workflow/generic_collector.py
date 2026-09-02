"""Canonical Flip Prediction Collector Strategy for NautilusTrader.
===================================================================
Executes live regime tracking, candidate generation, feature computation,
and forward outcome observation inside the NT event loop on streaming bars.
"""

from __future__ import annotations

import os
import hashlib
from collections import deque
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.trading.strategy import Strategy

from features.trackers.velocity import ArrivalVelocityTracker
from features.trackers.volume import ArrivalVolumeTracker
from features.trackers.pullback import PullbackTracker
from features.trackers.ohlcv_delta import OHLCVDeltaTracker
from features.trackers.price_levels import PriceLevelTracker
from features.trackers.rolling_5m_productivity import Rolling5mProductivityTracker
from features.trackers.structural_regime_geometry import StructuralRegimeGeometryTracker
from features.trackers.wick import WickTracker
from features.trackers.range_position import RangePositionTracker
from features.registry import resolve_runtime_feature_aliases
from backtests.nt_runtime.phase0 import authorize_execution
from utils.session_boundaries import is_in_session, session_close_ns
from features.trackers.regime_dual_ema import DualEmaRegimeTracker
from research_workflow.execution_plan import CompiledExecutionPlan

from datetime import datetime, timezone
import pytz

NS = 1_000_000_000
CT = pytz.timezone("America/Chicago")

# Terminal dispositions. Every emitted candidate reaches exactly one of these.
DISPOSITION_POSITIVE = "LABELED_POSITIVE"
DISPOSITION_NEGATIVE = "LABELED_NEGATIVE"
DISPOSITION_CENSORED = "CENSORED"

# Why a candidate was censored rather than labeled.
CENSOR_SESSION_END = "SESSION_END"
CENSOR_DATA_END = "DATA_END"
# The fused ring-buffer snapshot assembles two things in one pass: a base block of
# OHLCV/delta/price-level/RTH keys built inline by ``all_computed_60``, and the
# structural-geometry + rolling-productivity provider snapshots spread into it.
#
# A study needs that fused assembly only when its declared surface spans the provider
# block. A surface drawn purely from the base block has always been served by the
# per-tracker path and must keep being served by it -- those are different computations
# of the same column names, and silently swapping them would change values nobody asked
# to change.
#
# The old gate was ``len(feature_list) == 60``: the cardinality of base+provider. It
# therefore accepted any unrelated 60-name surface and rejected every valid subset.
# Drift-checked by scripts/tests/test_generic_collector_surface.py.
_FUSED_BASE_BLOCK: frozenset[str] = frozenset({
    "est_bear_vol_sum_300s", "est_delta_sum_1800s", "full_level_envelope_width_atr",
    "n_levels_below", "opening_range_30m_low_developing_signed_distance_points",
    "opening_range_30m_low_final_signed_distance_points", "pct_levels_behind_trade",
    "price_change_atr_30s", "price_change_atr_60s", "price_change_points_60s",
    "price_position_in_full_envelope", "prior_day_close_signed_distance_atr",
    "prior_day_low_signed_distance_points", "range_points_1800s",
    "rolling_15m_high_signed_distance_atr", "rolling_15m_low_signed_distance_atr",
    "rolling_30m_high_signed_distance_atr", "rolling_30m_low_signed_distance_atr",
    "rolling_5m_low_signed_distance_atr", "rolling_60m_high_signed_distance_atr",
    "rth_abs_delta_cum", "rth_elapsed_seconds", "rth_vol_cum", "up_down_vol_ratio_1800s",
    "vol_max_1s_1800s",
})

_FUSED_PROVIDER_BLOCK: frozenset[str] = frozenset({
    "current_1m_move_outside_completed_5m_range", "current_5m_directional_displacement_atr",
    "current_5m_regime_age_min", "current_5m_regime_range_atr",
    "current_5m_regime_range_atr_per_min", "distance_to_completed_5m_high_atr",
    "distance_to_completed_5m_low_atr", "prior_1m_regime_duration_min",
    "prior_1m_regime_efficiency", "prior_1m_regime_mfe_atr",
    "prior_1m_regime_net_directional_move_atr", "prior_1m_regime_net_move_atr_per_min",
    "prior_1m_regime_range_atr", "prior_1m_regime_range_atr_per_min",
    "prior_5m_regime_duration_min", "prior_5m_regime_efficiency", "prior_5m_regime_mfe_atr",
    "prior_5m_regime_net_directional_move_atr", "prior_5m_regime_net_move_atr_per_min",
    "prior_5m_regime_range_atr", "prior_5m_regime_range_atr_per_min",
    "regime_expansion_atr_per_min", "rolling_5m_current_progress_atr",
    "rolling_5m_current_speed_atr_per_min", "rolling_5m_current_speed_vs_lifetime",
    "rolling_5m_giveback_atr", "rolling_5m_max_progress_atr",
    "rolling_5m_max_speed_atr_per_min", "rolling_5m_max_speed_vs_lifetime",
    "rolling_5m_retention_ratio", "structural_current_expansion_atr",
    "structural_expansion_atr_per_min", "structural_giveback_atr",
    "structural_max_expansion_atr", "structural_retention_ratio",
})

_FUSED_RING_SURFACE: frozenset[str] = _FUSED_BASE_BLOCK | _FUSED_PROVIDER_BLOCK

PROGRESS_GAP_NS = 120 * NS
CANDIDATE_STEP_NS = 5 * NS
CANDIDATE_TIMEOUT_NS = 1800 * NS


class FastOHLCVRingBuffer:
    """Zero-allocation circular buffer for 1-second OHLCV rolling window statistics."""
    def __init__(self, capacity: int = 3600):
        self.capacity = capacity
        self.ts = np.zeros(capacity, dtype=np.int64)
        self.opens = np.zeros(capacity, dtype=np.float64)
        self.highs = np.zeros(capacity, dtype=np.float64)
        self.lows = np.zeros(capacity, dtype=np.float64)
        self.closes = np.zeros(capacity, dtype=np.float64)
        self.volumes = np.zeros(capacity, dtype=np.float64)
        self.deltas = np.zeros(capacity, dtype=np.float64)
        self.bear_vols = np.zeros(capacity, dtype=np.float64)
        self.head = 0
        self.count = 0

        self._rth_active = False
        self._rth_start_ts = None
        self._rth_vol_cum = 0.0
        self._rth_abs_delta_cum = 0.0

    def on_rth_open(self, ts: int):
        self._rth_active = True
        self._rth_start_ts = ts
        self._rth_vol_cum = 0.0
        self._rth_abs_delta_cum = 0.0

    def on_rth_close(self):
        self._rth_active = False

    def append(self, ts: int, o: float, h: float, l: float, c: float, v: float, d: float):
        idx = self.head
        self.ts[idx] = ts
        self.opens[idx] = o
        self.highs[idx] = h
        self.lows[idx] = l
        self.closes[idx] = c
        self.volumes[idx] = v
        self.deltas[idx] = d

        rng = h - l
        bull_ratio = min(max((c - l) / rng, 0.0), 1.0) if rng > 0 else 0.5
        self.bear_vols[idx] = v * (1.0 - bull_ratio)

        self.head = (self.head + 1) % self.capacity
        if self.count < self.capacity:
            self.count += 1

        if self._rth_active:
            self._rth_vol_cum += v
            self._rth_abs_delta_cum += abs(d)


class RegimeEngine(DualEmaRegimeTracker):
    """Legacy name for the single authoritative dual-EMA regime tracker.

    The formula lives in ``features/trackers/regime_dual_ema.py`` (``tracker.regime.dual_ema``);
    this subclass only preserves the constructor signature and attribute names
    (``regime``, ``atr``, ``ema3_h`` ...) the collector has always used.
    """
    ALPHA3 = 0.5
    ALPHA9 = 0.2
    ATR_P = 14

    def __init__(self) -> None:
        super().__init__(timeframe="1m", short_period=3, long_period=9, atr_period=14)


def verify_checkpoint_identities_authority(path: str | Path, declared_sha256: str) -> Dict[str, str]:
    """Verify allowlist bytes before any parquet decoder/candidate generation runs."""
    resolved = Path(path).resolve()
    actual = hashlib.sha256(resolved.read_bytes()).hexdigest()
    if not declared_sha256 or actual != str(declared_sha256).lower():
        raise RuntimeError(
            "REQUIRED_CHECKPOINT_IDENTITIES_SHA256_MISMATCH: identity allowlist "
            "content does not match the compiled population authority"
        )
    return {"path": str(resolved), "sha256": actual}


class FlipPredictionCollectorConfig(StrategyConfig, frozen=True):
    instrument_id: str = "NQ.XCME"
    bar_type_1s: str = "NQ.XCME-1-SECOND-LAST-EXTERNAL"
    bar_type_1m: str = "NQ.XCME-1-MINUTE-LAST-EXTERNAL"
    prevailing_regime: str = "bearish"       # 'bearish' (-1), 'bullish' (+1), or 'both'
    target_direction: str = "bullish"        # 'bullish' (+1), 'bearish' (-1), or 'both'
    horizon_seconds: int = 300               # forward horizon
    age_gate_seconds: int = 120              # minimum regime age before candidate declaration
    established_required: bool = True
    checkpoint_interval_seconds: int = 5
    # Generic allowlist-membership qualification, orthogonal to the established-filter
    # path above: when set, this is the ONLY population-qualification test applied, and
    # the established filter is not evaluated at all. Population membership then comes
    # from an externally frozen (regime_start_ns, checkpoint_index) identity table
    # instead of a live threshold/persistence rule -- for a population whose selection
    # was itself computed once, offline, against an already-collected checkpoint stream
    # (e.g. a derived-score upcross rule scored against a frozen upstream model), so the
    # collector's job is to reproduce that exact checkpoint's feature surface, not to
    # rediscover membership. Path is resolved relative to the study directory by the
    # generic config-kwargs builder; empty string disables this path entirely.
    required_checkpoint_identities_path: str = ""
    required_checkpoint_identities_sha256: str = ""
    running_mfe_atr_gte: float = 1.0
    new_progress_windows_gte: int = 2
    retained_mfe_ratio_gte: float = 0.5
    feature_list: Optional[List[str]] = None
    feature_requirements: dict = {}
    metadata_columns: tuple[str, ...] = ()
    phase0_manifest_path: str = ""
    feature_authority: str = "active"
    session: str = "RTH"                     # resolved via utils.session_boundaries
    session_end_censoring: bool = True       # from target_contract.censoring_policy
    target_contract: dict = {}
    # Compiled population_contract.episode_lifecycle (empty for non-episode studies).
    # When populated, the collector runs the generic population runtime
    # (research_workflow.population_runtime) instead of emitting on the checkpoint grid.
    episode_lifecycle: dict = {}
    # Compiled feature_contract (for the Stage-3 ProviderHost) and derived_causal_inputs
    # (for the frozen Model-C scorer). Empty for non-episode / non-provider_host studies.
    feature_contract: dict = {}
    derived_inputs: tuple = ()
    # Partitioned collection may replay causal lookahead bars while retaining only
    # primary-interval candidates.  None preserves the ordinary study-wide surface.
    primary_start_ts: Optional[int] = None
    primary_end_ts: Optional[int] = None


class FlipPredictionCollector(Strategy):
    """Canonical event-driven collector strategy for flip prediction research."""

    # --- Honest runtime capability declaration (research_workflow.runtime_bindings) ---
    # For a population_contract.episode_lifecycle study this collector runs the generic
    # population runtime (research_workflow.population_runtime.resolve_population_runtime
    # -> EpisodePopulationRuntime -> EpisodePopulationEngine) and does NOT emit any
    # candidate from the checkpoint grid. runtime_bindings verifies the real dispatch
    # path, not just this flag.
    SUPPORTS_EPISODE_LIFECYCLE = True
    EPISODE_POPULATION_RUNTIME = "research_workflow.population_runtime.resolve_population_runtime"

    def __init__(self, config: FlipPredictionCollectorConfig) -> None:
        super().__init__(config)
        self.cfg = config
        # Benchmark-only ablation switch.  It is unset for all governed/runtime
        # executions and exists solely to measure marginal replay costs without
        # creating alternate production collectors.
        self._benchmark_mode = os.environ.get("NT_COLLECTOR_ABLATION", "")
        self._benchmark_bars_1s = 0
        self._benchmark_bars_1m = 0
        self.bars_1s_count = 0
        self.bars_1m_count = 0
        # Bind the two subscribed bar types once.  Converting ``bar_type.spec``
        # to a string for every 1s callback was a hot-loop tax introduced by
        # the generic dispatch path; equality against the immutable BarType is
        # both clearer and substantially cheaper.
        self._bar_type_1s = BarType.from_str(config.bar_type_1s)
        self._bar_type_1m = BarType.from_str(config.bar_type_1m)
        if not config.phase0_manifest_path:
            raise RuntimeError("phase-zero authorization missing; collection and fit are refused")
        phase0 = authorize_execution(Path(config.phase0_manifest_path), feature_authority=config.feature_authority)
        self._feature_authority = phase0.get("feature_authority", "active")
        requirements = config.feature_requirements if isinstance(config.feature_requirements, dict) else {}
        resolved_instances = requirements.get("resolved_instances", ())
        self._study_feature_aliases = tuple(dict.fromkeys(
            str(item.get("physical_alias")) for item in resolved_instances
            if item.get("physical_alias")
        )) or tuple(dict.fromkeys(requirements.get("aliases", ())))
        self._resolved_instance_parameters: Dict[str, Dict[str, Any]] = {
            str(item.get("physical_alias")): dict(item.get("parameters") or {})
            for item in resolved_instances if item.get("physical_alias")
        }
        self._metadata_columns = tuple(config.metadata_columns)
        # Generic V2 provider: GenericArrivalVolumeProvider (features/trackers/generic_arrival.py)
        # is the canonical registry-declared implementation of `relative_volume`. The
        # legacy ArrivalVolumeTracker already on this collector computes a related
        # `rvol_*` family but with different cold-start fallback behavior (returns
        # 1.0 instead of None below the full window) -- not the same contract, so it
        # is not reused for this alias. Constructed only when the study declares the
        # alias (capability, not cardinality), with lookbacks read from the study's
        # own declared parameters rather than hardcoded.
        self._relative_volume_provider: Optional["GenericArrivalVolumeProvider"] = None
        if "relative_volume" in self._study_feature_aliases:
            rv_params = self._resolved_instance_parameters.get("relative_volume", {})
            agg_lb = int(rv_params.get("aggregation_lookback", 5))
            base_lb = int(rv_params.get("baseline_lookback", 5))
            self._relative_volume_agg_lookback = agg_lb
            self._relative_volume_baseline_lookback = base_lb
            from features.trackers.generic_arrival import GenericArrivalVolumeProvider
            self._relative_volume_provider = GenericArrivalVolumeProvider(
                max_lookback_bars=max(agg_lb + base_lb, 60)
            )
        # Generic identity-allowlist qualification (see config field docstring above).
        # Loaded once at construction; membership tested per-checkpoint in
        # _evaluate_checkpoint. A missing/malformed file fails closed -- an allowlist
        # path that silently resolved to "no restriction" would collect an unbounded
        # population under a name that promises a specific, frozen one.
        self._required_identities: Optional[frozenset] = None
        self._required_checkpoint_identities_lineage: Optional[Dict[str, str]] = None
        if config.required_checkpoint_identities_path:
            self._required_checkpoint_identities_lineage = verify_checkpoint_identities_authority(
                config.required_checkpoint_identities_path, config.required_checkpoint_identities_sha256,
            )
            allowlist_path = Path(self._required_checkpoint_identities_lineage["path"])
            ident_df = pd.read_parquet(allowlist_path)
            missing_cols = {"regime_start_ns", "checkpoint_index"} - set(ident_df.columns)
            if missing_cols:
                raise RuntimeError(
                    f"REQUIRED_CHECKPOINT_IDENTITIES_MALFORMED: missing columns {sorted(missing_cols)} "
                    f"in {config.required_checkpoint_identities_path}"
                )
            self._required_identities = frozenset(
                zip(ident_df["regime_start_ns"].astype("int64"), ident_df["checkpoint_index"].astype("int64"))
            )
            if len(self._required_identities) != len(ident_df):
                raise RuntimeError(
                    f"REQUIRED_CHECKPOINT_IDENTITIES_DUPLICATE: {len(ident_df)} rows collapsed to "
                    f"{len(self._required_identities)} unique (regime_start_ns, checkpoint_index) identities"
                )
        # V2-native studies declare a small explicit surface.  Keep this fast
        # path deliberately narrow: it is only enabled when every requested
        # alias is produced by the structural/rolling/arrival/context providers
        # below.  All other studies retain the historical full-surface path.
        self._compact_supported = {
            "prior_1m_regime_efficiency", "prior_1m_regime_mfe_atr",
            "prior_1m_regime_range_atr", "prior_5m_regime_efficiency",
            "prior_5m_regime_mfe_atr", "prior_5m_regime_range_atr",
            "rolling_300s_retention_ratio", "rolling_300s_current_progress_atr",
            "rolling_300s_max_progress_atr", "rolling_300s_giveback_atr",
            "arrival_velocity", "arrival_acceleration", "ema_slope",
        }
        self._compact_surface = bool(self._study_feature_aliases) and set(
            self._study_feature_aliases
        ).issubset(self._compact_supported)
        self.is_both_directions = config.prevailing_regime == "both"
        self.prevailing_dir = 0 if self.is_both_directions else (1 if config.prevailing_regime == "bullish" else -1)
        self.target_dir = 0 if self.is_both_directions else (1 if config.target_direction == "bullish" else -1)
        self.trade_dir = -self.prevailing_dir

        # Capability, not cardinality. The fused ring snapshot is required when the
        # declared surface is servable by it AND actually spans the provider block --
        # a base-block-only surface stays on the per-tracker path it has always used.
        _declared = set(config.feature_list or ())
        self._requires_fused_ring_snapshot = bool(_declared) and _declared.issubset(
            _FUSED_RING_SURFACE
        ) and bool(_declared & _FUSED_PROVIDER_BLOCK)

        self.regime_engine = RegimeEngine()
        self.ohlcv_tracker = OHLCVDeltaTracker()
        self.price_level_tracker = PriceLevelTracker()
        self.structural_geometry_tracker = StructuralRegimeGeometryTracker()
        self.rolling_productivity_tracker = Rolling5mProductivityTracker(window_seconds=300)
        self.wick_tracker = WickTracker()
        self.range_position_tracker = RangePositionTracker()

        if self._requires_fused_ring_snapshot:
            self.ring = FastOHLCVRingBuffer(capacity=3600)
            self.velocity_tracker = None
            self.volume_tracker = None
        else:
            self.ring = None
            self.velocity_tracker = ArrivalVelocityTracker(maxlen=60)
            self.volume_tracker = ArrivalVolumeTracker(maxlen=60)

        self.highs_1s: deque[float] = deque(maxlen=60)
        self.lows_1s: deque[float] = deque(maxlen=60)
        self.closes_1s: deque[float] = deque(maxlen=60)
        self.short_ema_history: deque[float] = deque(maxlen=20)
        self.long_ema_history: deque[float] = deque(maxlen=20)
        self.bars_since_breach_1m: List[Any] = []
        self.breach_price: Optional[float] = None
        self.bars_in_regime: int = 0

        # 5m bar accumulator
        self._current_5m_open: Optional[float] = None
        self._current_5m_high: float = -float("inf")
        self._current_5m_low: float = float("inf")

        # Regime state tracking
        self.active_regime_dir: int = 0
        self.regime_start_ns: int = 0
        self.regime_start_close: float = 0.0
        self.regime_frozen_atr: float = 0.0
        self.highest_high_since_flip: float = -float("inf")
        self.lowest_low_since_flip: float = float("inf")
        self.mfe_progress_count: int = 0
        self.mfe_progress_last_extreme_ts: Optional[int] = None
        self.mfe_progress_previous_extreme: float = 0.0
        self.next_checkpoint_index: int = 0

        # Buffers for retro-accumulation across minute boundaries
        self.minute_1s_buffer: List[Tuple[int, float, float, float, float]] = []
        self.was_rth: bool = False
        self.last_close: Optional[float] = None
        # Latest observed event time, used to stamp when a run-end censoring occurred.
        self.last_ts_seen: Optional[int] = None
        # Target contract is authoritative for all terminal labels.  A contract with no
        # explicit ``primitive`` key is a legacy compiled study (compiled before the
        # target-runtime binding existed): it keeps the historical flip labeling until it
        # is recompiled.  Every newly compiled contract carries ``primitive`` and is
        # dispatched strictly (an unknown primitive fails closed).
        from research_workflow.target_runtime import resolve_target_runtime
        _tc = config.target_contract or {}
        self._target_runtime = resolve_target_runtime(_tc, legacy_mode="primitive" not in _tc)
        self._target_primitive = self._target_runtime.primitive
        _ordered = ((config.target_contract or {}).get("required_forward_outcomes") or [])
        from research_workflow.target_expression import compile_target_expression
        _expression = compile_target_expression(_tc)
        _ordered_leaves = [leaf for leaf in _expression.leaves() if leaf.primitive == "ordered_barrier"]
        _ordered_params = dict(_ordered_leaves[0].params) if len(_ordered_leaves) == 1 and self._target_primitive == "ordered_barrier" else {}
        self._ordered_barrier = _ordered_params
        # Entry-reference + gap policy are TARGET-contract concerns: the collector reads
        # them off the compiled forward-outcome spec and hands them to the target runtime,
        # which owns entry-reference resolution.  The population candidate builder never
        # synthesizes a target-specific entry price.
        self._ordered_barrier_entry_reference = (
            _ordered_params.get("entry_reference", "next_bar_open")
        )
        self._ordered_barrier_max_gap_seconds = (
            _ordered_params.get("max_gap_seconds")
        )
        # A composite target (>= 2 conditions) is executed by CompositeTargetRuntime,
        # which owns one child runtime per condition and conjoins/disjoins them per
        # condition_logic (monotone worst_status censoring, no short-circuit). The
        # collector streams BOTH the 1s tape and prevailing-regime flips to it.
        self._composite_target = self._target_primitive == "composite"
        self._composite_parity_rows: List[Dict[str, Any]] = []
        self._ordered_barrier_parity_rows: List[Dict[str, Any]] = []
        self._composite_gap_seconds = None  # retained only for historical test fixtures; never used for execution

        # Telemetry & Output logs
        self.candidates_log: List[Dict[str, Any]] = []
        self.observations_log: List[Dict[str, Any]] = []
        self.pending_candidates: List[Dict[str, Any]] = []
        self._next_pending_horizon_ns: Optional[int] = None
        # Compile the declared surface after all providers exist.  The resulting
        # immutable plan is the only object consulted by the compact hot path.
        self._execution_plan = CompiledExecutionPlan.for_collector(
            self, self._study_feature_aliases
        )

        # --- Generic population runtime dispatch (Stage 2) ------------------------
        # The compiled population_contract decides WHEN a candidate exists. For an
        # episode_lifecycle study that is EpisodePopulationEngine (via the generic
        # dispatcher), and the checkpoint grid must NOT emit candidates. Non-episode
        # studies keep the existing checkpoint-grid path unchanged.
        from research_workflow.population_runtime import resolve_population_runtime
        _episode_lc = dict(getattr(config, "episode_lifecycle", {}) or {})
        _pop_contract = (
            {"episode_lifecycle": _episode_lc} if _episode_lc
            else {"population_type": "regime_state"}
        )
        self._population_runtime = resolve_population_runtime(_pop_contract)
        self._episode_mode = not self._population_runtime.emits_from_checkpoint_grid()
        self._episode_candidate_events: List[Any] = []
        self._episode_candidates_this_regime = 0

        # --- Stage 3: ProviderHost feature realization ----------------------------
        self._provider_host = None
        self._regime_feed = None
        if self._episode_mode:
            from research_workflow.provider_host import ProviderHost
            from research_workflow.completed_regime_state import CompletedRegimeStateFeed
            fc = dict(getattr(config, "feature_contract", {}) or {})
            if fc:
                self._provider_host = ProviderHost.from_feature_contract(
                    {"contracts": {"feature_contract": fc}},
                    feature_authority=self._feature_authority,
                )
            self._regime_feed = CompletedRegimeStateFeed(["5s", "5m"])

        # --- Frozen derived-input scorers (RT-04) --------------------------------
        # An ORDERED list, one scorer per declared features.derived_inputs entry --
        # never just di_list[0], and independent of population type. Every declared
        # input produces exactly one output column of the same name; a declared input
        # whose scorer cannot bind fails here (fail closed, before any row is emitted).
        self._derived_scorers: List[Dict[str, Any]] = []
        di_list = list(getattr(config, "derived_inputs", ()) or [])
        if di_list:
            from research.schemas.study_spec import DerivedCausalInputSpec
            from research_workflow.external_model_scoring import FrozenExternalModelScorer

            # phase0 manifest lives at <studies_root>/<study>/artifacts/phase0_source_manifest.json,
            # so parents[2] is the studies root -- and bind() needs a parent_dir under it.
            _studies_root = None
            if getattr(config, "phase0_manifest_path", ""):
                _studies_root = Path(config.phase0_manifest_path).resolve().parents[2]
            seen_names: set[str] = set()
            for raw in di_list:
                di = raw if isinstance(raw, DerivedCausalInputSpec) else DerivedCausalInputSpec.model_validate(raw)
                if di.name in seen_names:
                    raise RuntimeError(f"DERIVED_INPUT_DUPLICATE_NAME: {di.name!r}")
                seen_names.add(di.name)
                _root = _studies_root or Path.cwd()
                parent_dir = _root / (di.parent_study_id or "_model_id_binding")
                scorer = FrozenExternalModelScorer.bind(di, parent_dir=parent_dir)
                self._derived_scorers.append({
                    "name": di.name,
                    "scorer": scorer,
                    "surface": {
                        "LONG": scorer.ordered_inputs("LONG"),
                        "SHORT": scorer.ordered_inputs("SHORT"),
                    },
                })
        # Back-compat alias for the single-scorer episode row builder / tests.
        self._model_c_derived_name = (
            self._derived_scorers[0]["name"] if self._derived_scorers else "model_c_score_at_candidate"
        )

    def get_episode_candidate_events(self) -> List[Any]:
        """Population-runtime candidate events (Stage 2/3 internal record)."""
        return list(self._episode_candidate_events)

    def _apply_derived_scores(self, record: Dict[str, Any]) -> None:
        """RT-04: fill EVERY declared frozen derived-input score column on ``record``,
        in declaration order, for both checkpoint-grid and episode populations.

        One column per declared input; a column always exists (``None`` when the
        direction-appropriate surface has a null input or is not declared). No
        undeclared score column is ever written.
        """
        if not self._derived_scorers:
            return
        _dir = record.get("prevailing_direction", record.get("regime_direction"))
        direction = "LONG" if int(_dir or 0) == 1 else "SHORT"
        ts = int(record.get("candidate_ts", record.get("observation_ts", 0)))
        for s in self._derived_scorers:
            name = s["name"]
            record.setdefault(name, None)
            surf = s["surface"].get(direction) or []
            if not surf:
                continue
            inputs = {n: record.get(n) for n in surf}
            if any(v is None for v in inputs.values()):
                continue
            obs = s["scorer"].score(
                inputs, checkpoint_ts=ts, direction=direction,
                availability_ts={n: ts for n in surf},
            )
            record[name] = float(obs.score)

    def _append_candidate(self, record: Dict[str, Any]) -> None:
        """Emit only the study-declared surface plus canonical key/metadata fields."""
        if getattr(self, "_benchmark_mode", "") in {"checkpoint_only", "baseline", "structural", "rolling", "full_no_target"}:
            return
        self._apply_derived_scores(record)
        aliases = set(self._study_feature_aliases or self.cfg.feature_list or ())
        # Causality evidence is a runtime metadata field, not a feature.  It is
        # required by the smoke validator to prove source availability for every
        # persisted candidate row.
        keep = {"observation_ts", "regime_start_ns", "checkpoint_index", "triggering_1s_ts_init"}
        keep.update(self._metadata_columns)
        keep.update(aliases)
        # RT-04: exactly the declared derived-input score columns, no more.
        for s in self._derived_scorers:
            keep.add(s["name"])
        self.candidates_log.append({key: value for key, value in record.items() if key in keep})

    def on_start(self) -> None:
        self.subscribe_bars(self._bar_type_1s)
        self.subscribe_bars(self._bar_type_1m)

    def on_bar(self, bar: Bar) -> None:
        if bar.bar_type == self._bar_type_1s:
            self._benchmark_bars_1s += 1
            self.bars_1s_count = self._benchmark_bars_1s
        elif bar.bar_type == self._bar_type_1m:
            self._benchmark_bars_1m += 1
            self.bars_1m_count = self._benchmark_bars_1m
        if getattr(self, "_benchmark_mode", "") == "empty_generic":
            return
        if getattr(self, "_benchmark_mode", "") == "regime_state" and bar.bar_type == self._bar_type_1s:
            return
        if bar.bar_type == self._bar_type_1s:
            self._handle_1s_bar(bar)
        elif bar.bar_type == self._bar_type_1m:
            self._handle_1m_bar(bar)

    def _handle_1m_bar(self, bar: Bar) -> None:
        ts_event = int(bar.ts_event)
        ts_avail = int(bar.ts_init)
        o = float(bar.open)
        h = float(bar.high)
        l = float(bar.low)
        c = float(bar.close)
        v = float(bar.volume)

        # 1. Update Wilder ATR & Dual-EMA Regime Tracker
        old_regime = self.regime_engine.regime
        new_regime = self.regime_engine.update(h, l, c)
        atr_val = self.regime_engine.atr or 0.0

        if self.regime_engine.ema3_h is not None:
            self.short_ema_history.append((self.regime_engine.ema3_h + (self.regime_engine.ema3_l or self.regime_engine.ema3_h)) / 2.0)
            self.long_ema_history.append((self.regime_engine.ema9_h + (self.regime_engine.ema9_l or self.regime_engine.ema9_h)) / 2.0)

        # 2. Check 5m boundary and dispatch completed 5m bar to Structural Tracker
        ts_pd = pd.Timestamp(ts_avail, tz="UTC").tz_convert("America/Chicago")
        minute_of_day = ts_pd.hour * 60 + ts_pd.minute

        if self._current_5m_open is None:
            self._current_5m_open = o
        self._current_5m_high = max(self._current_5m_high, h)
        self._current_5m_low = min(self._current_5m_low, l)

        if minute_of_day % 5 == 0:
            self.structural_geometry_tracker.on_5m_bar(
                close_ts=ts_avail,
                direction=self.active_regime_dir if self.active_regime_dir != 0 else new_regime,
                open_=self._current_5m_open,
                high=self._current_5m_high,
                low=self._current_5m_low,
                close=c,
                atr=atr_val,
            )
            self._current_5m_open = None
            self._current_5m_high = -float("inf")
            self._current_5m_low = float("inf")

        # 3. Handle session and RTH transitions for OHLCV Tracker
        is_rth_now = is_in_session(ts_avail, self.cfg.session)
        if not self._compact_surface:
            if is_rth_now and not self.was_rth:
                self.ohlcv_tracker.reset_rth(ts_avail)
                if self.ring:
                    self.ring.on_rth_open(ts_avail)
            elif not is_rth_now and self.was_rth:
                self.ohlcv_tracker.end_rth()
                if self.ring:
                    self.ring.on_rth_close()
            self.was_rth = is_rth_now

            for buf_ts, buf_h, buf_l, buf_v, buf_d in self.minute_1s_buffer:
                if old_regime != 0:
                    self.ohlcv_tracker.accumulate_regime(buf_ts, buf_h, buf_l, buf_v, buf_d)
                self.ohlcv_tracker.accumulate_rth(buf_v, buf_d)

        # Stage 3: completed 1m bar -> ProviderHost (ema-slope series, structural geometry).
        if getattr(self, "_episode_mode", False):
            self._episode_dispatch_1m(ts_avail, o, h, l, c, new_regime, atr_val)

        # 4. Handle regime transition (flips)
        if new_regime != old_regime and new_regime != 0:
            self._on_regime_flip(
                new_regime=new_regime,
                flip_ts=ts_avail,
                open_price=o,
                close_price=c,
                atr_val=atr_val,
            )
            if not self._compact_surface:
                self.ohlcv_tracker.reset_regime(ts_avail, o)
            self.structural_geometry_tracker.on_1m_flip(
                direction=new_regime,
                start_ns=ts_avail,
                start_price=o,
                atr_start=atr_val,
                prior_end_close=self.last_close or c,
            )
            if getattr(self, "_episode_mode", False):
                self._episode_regime_transition(
                    new_regime, ts_avail, o, atr_val, self.last_close or c,
                )
                self._episode_candidates_this_regime = 0
            self.bars_in_regime = 0
            self.bars_since_breach_1m = []
            self.breach_price = None
        else:
            self.bars_in_regime += 1

        if not self._compact_surface:
            for buf_ts, buf_h, buf_l, buf_v, buf_d in self.minute_1s_buffer:
                self.ohlcv_tracker.accumulate_regime_rth(buf_ts, buf_h, buf_l, buf_v, buf_d)
            self.minute_1s_buffer = []

            self.price_level_tracker.update_1m(ts_avail, o, h, l, c, is_rth_now)
            self.wick_tracker.update(o, h, l, c)
            self.range_position_tracker.update(h, l, c)
            self.bars_since_breach_1m.append(bar)

    def _track_pending(self, cand_record: Dict[str, Any], T: int) -> None:
        """Registers a freshly emitted candidate for terminal disposition.

        Deliberately a separate, narrow dict rather than the candidate record itself:
        ``horizon_end_ts``/``session_close_ts`` are resolution bookkeeping, and the output
        contract in ``OutputManager.persist_collection`` rejects columns the study never
        declared. They belong to the observation surface, not the feature surface.
        """
        if getattr(self, "_benchmark_mode", "") in {"checkpoint_only", "baseline", "structural", "rolling", "full_no_target"}:
            return

        if getattr(self, "_target_primitive", "flip_within_horizon") == "composite":
            direction = int(cand_record.get("regime_direction", self.active_regime_dir))
            candidate = {
                "observation_ts": int(cand_record["observation_ts"]),
                "regime_start_ns": cand_record["regime_start_ns"],
                "regime_direction": direction,
                "direction": direction,
                "checkpoint_index": cand_record["checkpoint_index"],
                "atr": self._frozen_target_atr_at_T(cand_record),
                "atr_source": "latest_causally_completed_1m_wilder_atr_14_available_at_T",
                "session_close_ts": (
                    session_close_ns(T, self.cfg.session)
                    if self.cfg.session_end_censoring else None
                ),
            }
            self.pending_candidates.append(self._target_runtime.open_pending(candidate))
            return

        if getattr(self, "_target_primitive", "flip_within_horizon") == "ordered_barrier":
            if not self._ordered_barrier:
                raise RuntimeError("TARGET_RUNTIME_MISMATCH: ordered_barrier has no compiled barrier")
            # The population supplies candidate identity, T, and the causal candidate-time
            # ATR.  The TARGET runtime owns entry-reference resolution -- the candidate
            # builder must never synthesize a target-specific entry_price.
            frozen_atr = self._frozen_target_atr_at_T(cand_record)
            direction = int(cand_record.get("regime_direction", self.active_regime_dir))
            candidate = {
                "observation_ts": int(cand_record["observation_ts"]),
                "regime_start_ns": cand_record["regime_start_ns"],
                "regime_direction": direction,
                "checkpoint_index": cand_record["checkpoint_index"],
                "direction": direction,
                "atr": frozen_atr,
                "atr_source": "latest_causally_completed_1m_wilder_atr_14_available_at_T",
                "declared_atr_source": self._ordered_barrier.get("atr_source"),
                "forward_outcome_id": self._ordered_barrier.get("forward_outcome_id"),
                "barrier_id": self._ordered_barrier.get("barrier_id"),
                "favorable_atr": float(self._ordered_barrier["favorable_atr"]),
                "adverse_atr": float(self._ordered_barrier["adverse_atr"]),
                # The ordered-barrier horizon is the compiled barrier's own
                # horizon_seconds (target_contract.required_forward_outcomes[].
                # ordered_barriers[].horizon_seconds), NOT cfg.horizon_seconds -- the
                # latter falls back to 300 when the target declares no top-level
                # horizon (build_collector_config_kwargs), which is wrong for a
                # forward-outcome-scoped barrier.
                "horizon_seconds": int(self._ordered_barrier["horizon_seconds"] if self._ordered_barrier.get("horizon_seconds") is not None
                                       else self.cfg.horizon_seconds),
                "session_close_ts": (
                    session_close_ns(T, self.cfg.session)
                    if self.cfg.session_end_censoring else None
                ),
                "max_gap_seconds": getattr(self, "_ordered_barrier_max_gap_seconds", None),
                "entry_reference": getattr(self, "_ordered_barrier_entry_reference", "next_bar_open"),
            }
            self.pending_candidates.append(self._target_runtime.open_pending(candidate))
            return

        pending = {
            "observation_ts": cand_record["observation_ts"],
            "regime_start_ns": cand_record["regime_start_ns"],
            "regime_direction": cand_record["regime_direction"],
            "checkpoint_index": cand_record["checkpoint_index"],
            "horizon_end_ts": T + int(self.cfg.horizon_seconds) * NS,
            "session_close_ts": (
                session_close_ns(T, self.cfg.session)
                if self.cfg.session_end_censoring else None
            ),
        }
        self.pending_candidates.append(pending)
        horizon_end = T + int(self.cfg.horizon_seconds) * NS
        next_horizon = getattr(self, "_next_pending_horizon_ns", None)
        if next_horizon is None or horizon_end < next_horizon:
            self._next_pending_horizon_ns = horizon_end

    @staticmethod
    def _frozen_target_atr_at_T(cand_record: Dict[str, Any]) -> float:
        """The causal candidate-time ATR the ordered barrier is frozen against.

        Normalized so both population paths expose the same target-time state: the
        checkpoint grid writes ``atr``; the episode row writes ``atr_t`` /
        ``target_frozen_atr``.  Every source is ATR from completed bars at or before T.
        """
        for key in ("target_frozen_atr", "atr_t", "atr"):
            value = cand_record.get(key)
            if value is not None and float(value) > 0:
                return float(value)
        raise RuntimeError(
            "TARGET_FROZEN_ATR_MISSING: no positive candidate-time ATR "
            "(target_frozen_atr / atr_t / atr) on the candidate record"
        )

    def _emit_observation(
        self,
        cand: Dict[str, Any],
        disposition: str,
        flip_ts: Optional[int],
        censor_reason: Optional[str] = None,
        censored_at_ts: Optional[int] = None,
    ) -> None:
        """Records the single terminal disposition of one candidate.

        Every emitted candidate passes through here exactly once. A candidate that simply
        stopped being tracked -- which is what used to happen to anything still pending
        when the run ended -- has no row at all, and a population that silently loses its
        unresolved members is conditioned on the future.
        """
        cand_ts = cand["observation_ts"]
        time_to_flip_s = ((flip_ts - cand_ts) / NS) if flip_ts is not None else None

        # Small historical collector fixtures construct via ``__new__`` and do not
        # run __init__; retain their explicit legacy flip semantics.
        runtime = getattr(self, "_target_runtime", None)
        if runtime is None:
            from research_workflow.target_runtime import resolve_target_runtime
            runtime = resolve_target_runtime({}, legacy_mode=True)
        target_result = runtime.from_disposition(
            disposition, resolved_at_ts=(censored_at_ts if flip_ts is None else flip_ts),
            censor_reason=censor_reason,
        )
        self.observations_log.append({
            "observation_ts": cand_ts,
            "regime_start_ns": cand["regime_start_ns"],
            "regime_direction": cand["regime_direction"],
            "checkpoint_index": cand["checkpoint_index"],
            "flip_ts": flip_ts,
            "time_to_flip_seconds": time_to_flip_s,
            "target_flip_within_horizon": target_result.label,
            "disposition": target_result.disposition,
            "censored": int(target_result.disposition == DISPOSITION_CENSORED),
            "censor_reason": target_result.censor_reason,
            "horizon_end_ts": cand.get("horizon_end_ts"),
            "session_close_ts": cand.get("session_close_ts"),
            "resolved_at_ts": target_result.resolved_at_ts,
        })

    def _resolve_ordered_barriers(self, event: Optional[Dict[str, Any]], *, now_ts: int, final: bool = False) -> None:
        """Stream completed 1s execution bars to OrderedBarrierTargetRuntime.

        The runtime resolves the compiled ``entry_reference`` (``next_bar_open``) on the
        first bar strictly after T and owns every barrier first-touch decision; the
        collector only decides retention vs. run-end censoring.
        """
        _map = {"POSITIVE": DISPOSITION_POSITIVE, "NEGATIVE": DISPOSITION_NEGATIVE,
                "CENSORED": DISPOSITION_CENSORED}
        remaining: List[Dict[str, Any]] = []
        for cand in self.pending_candidates:
            if event is not None:
                self._target_runtime.ingest_bar(cand, event)

            # The entry reference has not been observed yet: keep waiting, unless the
            # run is ending -- then the entry itself is unobservable -> DATA_END censor.
            if not cand.get("entry_resolved"):
                if final:
                    self._emit_observation(cand, DISPOSITION_CENSORED, None,
                                           censor_reason=CENSOR_DATA_END, censored_at_ts=now_ts)
                    self._record_ordered_barrier_parity(cand)
                else:
                    remaining.append(cand)
                continue

            if final and now_ts < cand["horizon_end_ts"]:
                self._emit_observation(cand, DISPOSITION_CENSORED, None,
                                       censor_reason=CENSOR_DATA_END, censored_at_ts=now_ts)
                self._record_ordered_barrier_parity(cand)
                continue

            live = self._target_runtime.terminal(cand, final=False)
            if live.disposition != "PENDING":
                disp = _map[live.disposition]
                self._emit_observation(cand, disp,
                                       live.resolved_at_ts if disp == DISPOSITION_POSITIVE else None,
                                       censor_reason=live.censor_reason, censored_at_ts=live.resolved_at_ts)
                self._record_ordered_barrier_parity(cand)
                continue
            # Inclusive horizon: retain through its exact completed timestamp.
            if not final and now_ts <= cand["horizon_end_ts"]:
                remaining.append(cand)
                continue
            result = self._target_runtime.terminal(cand, final=True)
            disp = _map[result.disposition]
            self._emit_observation(
                cand, disp,
                result.resolved_at_ts if disp == DISPOSITION_POSITIVE else None,
                censor_reason=result.censor_reason, censored_at_ts=result.resolved_at_ts,
            )
            self._record_ordered_barrier_parity(cand)
        self.pending_candidates = remaining
        self._next_pending_horizon_ns = min(
            (c["horizon_end_ts"] for c in remaining if c.get("entry_resolved")), default=None
        )

    def _record_ordered_barrier_parity(self, cand: Mapping[str, Any]) -> None:
        """Record every primitive ordered-barrier result for independent replay."""
        if not self.observations_log:
            return
        obs = self.observations_log[-1]
        rows = getattr(self, "_ordered_barrier_parity_rows", None)
        if rows is None:  # narrow __new__ fixtures bypass normal collector initialization
            rows = self._ordered_barrier_parity_rows = []
        rows.append({
            "candidate": {
                "observation_ts": int(cand["observation_ts"]),
                "session_close_ts": cand.get("session_close_ts"),
                "atr": cand.get("atr"),
                "atr_source": cand.get("atr_source"),
                "direction": cand.get("direction", cand.get("regime_direction")),
            },
            "events": [dict(e) for e in cand.get("events", ())],
            "actual": {"disposition": obs["disposition"], "label": obs["target_flip_within_horizon"],
                       "censor_reason": obs["censor_reason"]},
        })

    def _resolve_composite(self, event: Optional[Dict[str, Any]], *, now_ts: int, final: bool = False) -> None:
        """Stream one completed 1s bar to every pending composite candidate.

        The CompositeTargetRuntime routes the bar to each ordered-barrier child and
        the prevailing-regime flips (fed separately via :meth:`_on_regime_flip`) to
        each flip child, then composes their terminal results through the compiled
        Boolean expression -- monotone ``worst_status`` censoring, no short-circuit.
        The collector only decides retention vs. run-end resolution.
        """
        _map = {"POSITIVE": DISPOSITION_POSITIVE, "NEGATIVE": DISPOSITION_NEGATIVE,
                "CENSORED": DISPOSITION_CENSORED}
        remaining: List[Dict[str, Any]] = []
        for cand in self.pending_candidates:
            if event is not None:
                self._target_runtime.ingest_bar(cand, event)

            live = self._target_runtime.terminal(cand, final=False, now_ts=now_ts)
            if live.disposition != "PENDING":
                self._emit_composite(cand, live)
                continue
            # Inclusive horizon: retain through its exact completed timestamp so a flip
            # coincident with horizon_end still lands (same rule as the flip sweep).
            if not final and now_ts <= cand["horizon_end_ts"]:
                remaining.append(cand)
                continue
            self._emit_composite(cand, self._target_runtime.terminal(cand, final=True, now_ts=now_ts))
        self.pending_candidates = remaining
        self._next_pending_horizon_ns = min(
            (c["horizon_end_ts"] for c in remaining), default=None
        )

    def _emit_composite(self, cand: Dict[str, Any], result) -> None:
        """Emit one composite observation and stash an independent-replay parity row.

        The parity row carries only raw causal inputs (the retained 1s tape, the observed
        flips, the frozen ATR); ``research_workflow.target_runtime.validate_target_parity``
        re-derives the label from the contract via the independent oracle and a divergence
        is a defect (written to ``composite_target_replay_parity.json`` by collect mode).
        """
        _map = {"POSITIVE": DISPOSITION_POSITIVE, "NEGATIVE": DISPOSITION_NEGATIVE,
                "CENSORED": DISPOSITION_CENSORED}
        disp = _map[result.disposition]
        self._emit_observation(
            cand, disp,
            result.resolved_at_ts if disp == DISPOSITION_POSITIVE else None,
            censor_reason=result.censor_reason, censored_at_ts=result.resolved_at_ts,
        )
        obs = self.observations_log[-1]
        self._composite_parity_rows.append(self._target_runtime.parity_row(cand, {
            "disposition": obs["disposition"],
            "label": obs["target_flip_within_horizon"],
            "censor_reason": obs["censor_reason"],
        }))

    def get_composite_target_parity(self) -> Optional[Dict[str, Any]]:
        """Independent-oracle parity over every emitted composite observation.

        Returns ``None`` for a non-composite study.  Consumed by collect mode, which
        writes ``composite_target_replay_parity.json`` into the run directory.
        """
        primitive = getattr(self, "_target_primitive", None)
        if primitive not in {"composite", "ordered_barrier"}:
            return None
        from research_workflow.target_runtime import validate_target_parity

        rows = (self._composite_parity_rows if primitive == "composite"
                else self._ordered_barrier_parity_rows)
        report = validate_target_parity(self.cfg.target_contract, rows)
        contract = self.cfg.target_contract or {}
        report["target_expression"] = contract.get("target_expression")
        report["censoring_composition"] = contract.get("censoring_composition")
        if not report.get("passed") and os.environ.get("NT_COMPOSITE_PARITY_DUMP"):
            import pickle
            with open(os.environ["NT_COMPOSITE_PARITY_DUMP"], "wb") as fh:
                pickle.dump(self._composite_parity_rows, fh)
        return report

    def _sweep_elapsed_horizons(self, now_ts: int, final: bool = False) -> None:
        """Resolves pending candidates whose horizon has fully elapsed with no flip.

        Called on every completed 1s bar. Resolving at horizon expiry rather than at the
        next flip matters for two reasons: the label stops depending on an event outside
        the horizon, and the recorded ``flip_ts`` stops carrying a timestamp the candidate
        was never entitled to see.

        Boundary handling (causal audit pass 01). The horizon is **inclusive** of its
        endpoint, so a flip at exactly ``horizon_end`` is a positive. Candidates sit on a
        5s grid from a minute-aligned regime start and the horizon is 300s, so every 12th
        candidate's ``horizon_end`` falls exactly on a minute boundary -- which is when
        flips happen. Because a 1s bar closing at T is dispatched before the 1m bar
        closing at the same T, sweeping with ``>=`` here would resolve such a candidate
        NEGATIVE moments before the coincident flip was visible, systematically
        mislabelling roughly one candidate in twelve.

        So a candidate whose horizon ends exactly at ``now_ts`` is held for one more tick,
        giving the same-timestamp 1m flip its chance. ``final=True`` (run end) resolves
        those, because by then no further bar can arrive to change the answer.
        """
        if getattr(self, "_benchmark_mode", "") in {"checkpoint_only", "baseline", "structural", "rolling", "full_no_target"}:
            return
        if not self.pending_candidates:
            self._next_pending_horizon_ns = None
            return
        if getattr(self, "_target_primitive", "flip_within_horizon") == "ordered_barrier":
            self._resolve_ordered_barriers(None, now_ts=now_ts, final=final)
            return
        if getattr(self, "_target_primitive", "flip_within_horizon") == "composite":
            self._resolve_composite(None, now_ts=now_ts, final=final)
            return
        next_horizon = getattr(self, "_next_pending_horizon_ns", None)
        if not final and next_horizon is not None and now_ts < next_horizon:
            return
        still_pending: List[Dict[str, Any]] = []
        for cand in self.pending_candidates:
            horizon_end = cand["horizon_end_ts"]
            if horizon_end > now_ts or (horizon_end == now_ts and not final):
                still_pending.append(cand)
                continue
            # Horizon fully elapsed without an opposing flip.
            if self._is_censored_by_session(cand):
                self._emit_observation(
                    cand, DISPOSITION_CENSORED, None,
                    censor_reason=CENSOR_SESSION_END, censored_at_ts=now_ts,
                )
            else:
                self._emit_observation(cand, DISPOSITION_NEGATIVE, None, censored_at_ts=horizon_end)
        self.pending_candidates = still_pending
        self._next_pending_horizon_ns = (
            min((c["horizon_end_ts"] for c in still_pending), default=None)
        )

    def _is_censored_by_session(self, cand: Dict[str, Any]) -> bool:
        """True when the candidate's horizon extends past its own session close.

        ``target_contract.censoring_policy.session_end_censoring`` declares this. Such a
        candidate cannot be labeled from in-session data: a 'no flip' verdict would rest
        on a window the session never covered, and a 'flip' verdict would rest on price
        action from the next session.
        """
        if not self.cfg.session_end_censoring:
            return False
        session_close = cand.get("session_close_ts")
        if session_close is None:
            return False
        return cand["horizon_end_ts"] > session_close

    def on_stop(self) -> None:
        """Disposes every still-pending candidate before the run ends.

        Without this the collector simply dropped them. The candidates were already in
        ``candidates.parquet``; their absence from ``observations.parquet`` is exactly the
        future-conditioned selection the censoring policy exists to prevent.
        """
        # Any candidate whose horizon completed within the observed data has a known
        # outcome and must be labeled, not censored -- including the boundary case the
        # sweep deferred by one tick.
        if self.last_ts_seen is not None:
            self._sweep_elapsed_horizons(self.last_ts_seen, final=True)

        for cand in self.pending_candidates:
            reason = (
                CENSOR_SESSION_END if self._is_censored_by_session(cand) else CENSOR_DATA_END
            )
            self._emit_observation(
                cand, DISPOSITION_CENSORED, None,
                censor_reason=reason, censored_at_ts=self.last_ts_seen,
            )
        self.pending_candidates = []

    def _on_regime_flip(self, new_regime: int, flip_ts: int, open_price: float, close_price: float, atr_val: float) -> None:
        # Ordered barriers are resolved exclusively from completed 1s OHLC events; a
        # composite target's flip child consumes flips through its own runtime. The
        # legacy flip-clearing path below runs ONLY for a bare flip_within_horizon
        # target -- it must never override any other compiled primitive.
        _prim = getattr(self, "_target_primitive", "flip_within_horizon")
        if _prim == "composite":
            for cand in self.pending_candidates:
                self._target_runtime.ingest_flip(cand, {"ts": int(flip_ts), "direction": int(new_regime)})
        target_dir = -self.active_regime_dir if self.is_both_directions else self.target_dir
        if _prim == "flip_within_horizon" and (self.active_regime_dir in (-1, 1)) and new_regime == target_dir:
            for cand in self.pending_candidates:
                cand_ts = cand["observation_ts"]
                within_horizon = cand_ts <= flip_ts <= cand["horizon_end_ts"]

                if self._is_censored_by_session(cand):
                    # The horizon reached past the session close, so this candidate is
                    # censored whether or not a flip happened to land inside it.
                    self._emit_observation(
                        cand, DISPOSITION_CENSORED, None,
                        censor_reason=CENSOR_SESSION_END, censored_at_ts=flip_ts,
                    )
                elif within_horizon:
                    self._emit_observation(cand, DISPOSITION_POSITIVE, flip_ts)
                else:
                    # Horizon already elapsed; the sweep should normally have caught it.
                    self._emit_observation(cand, DISPOSITION_NEGATIVE, None,
                                           censored_at_ts=cand["horizon_end_ts"])
            self.pending_candidates.clear()

        # Reset regime state
        self.active_regime_dir = new_regime
        self.regime_start_ns = flip_ts
        self.regime_start_close = open_price
        self.regime_frozen_atr = atr_val if atr_val > 0 else 0.0
        self.highest_high_since_flip = open_price
        self.lowest_low_since_flip = open_price
        self.mfe_progress_previous_extreme = 0.0
        self.mfe_progress_last_extreme_ts = None
        self.mfe_progress_count = 0
        self.next_checkpoint_index = 0

        # Stage 2: a true prevailing-1m regime boundary is the ONLY thing that starts a
        # new episode (the engine TERMINATEs the old one on the next snapshot).
        if getattr(self, "_episode_mode", False):
            self._population_runtime.on_prevailing_regime(
                direction=new_regime, start_ns=flip_ts, start_price=open_price,
            )

    def _handle_1s_bar(self, bar: Bar) -> None:
        ts_event = int(bar.ts_event)
        ts_avail = int(bar.ts_init)
        o = float(bar.open)
        h = float(bar.high)
        l = float(bar.low)
        c = float(bar.close)
        v = float(bar.volume)

        if not self._requires_fused_ring_snapshot:
            if self.velocity_tracker and getattr(self, "_benchmark_mode", "") not in {"checkpoint_only", "baseline"}:
                self.velocity_tracker.update(c)
            if self.volume_tracker and not self._compact_surface:
                self.volume_tracker.update(v, o, c)
            if self._relative_volume_provider is not None:
                self._relative_volume_provider.update_completed_bar(volume=v, open_px=o, close_px=c)
            if not self._compact_surface:
                self.highs_1s.append(h)
                self.lows_1s.append(l)
                self.closes_1s.append(c)

        if self._compact_surface and getattr(self, "_benchmark_mode", "") not in {"checkpoint_only", "baseline"}:
            # The selected V2 surface does not consume OHLCV-delta, price-level,
            # wick, range-position, pullback, or volume snapshots.  Structural,
            # rolling, and arrival providers maintain their own causal state.
            # Do not materialize an unused OHLCV dictionary or buffer entry on
            # every 1s bar; this preserves the selected feature values while
            # removing legacy exploratory work from the hot loop.
            b_est = None
        else:
            b_est = self.ohlcv_tracker.update(ts_avail, o, h, l, c, v)
        if self._requires_fused_ring_snapshot and self.ring:
            self.ring.append(ts_avail, o, h, l, c, v, b_est["bar_est_delta"])

        if not self._compact_surface:
            self.minute_1s_buffer.append((ts_avail, h, l, v, b_est["bar_est_delta"]))

        if self._compact_surface:
            for update in self._execution_plan.update_1s_callbacks:
                update(ts_avail, h, l, c)
        else:
            self.structural_geometry_tracker.on_1s(ts_avail, h, l, c)
            self.rolling_productivity_tracker.on_completed_1s(ts_avail, h, l, c)

        # Stage 2/3: episode_lifecycle studies determine candidate existence through the
        # generic population runtime, driven by completed 1s + completed 5s regime state,
        # and (Stage 3) realize the full governed candidate row via ProviderHost + scorer.
        if getattr(self, "_episode_mode", False):
            self._episode_dispatch_1s(ts_event, ts_avail, o, h, l, c, v)

        if self.active_regime_dir != 0:
            self.highest_high_since_flip = max(self.highest_high_since_flip, h)
            self.lowest_low_since_flip = min(self.lowest_low_since_flip, l)

            current_mfe = self._compute_running_mfe(self.active_regime_dir)
            if current_mfe > (self.mfe_progress_previous_extreme + 1e-12):
                if self.mfe_progress_last_extreme_ts is None or (ts_event - self.mfe_progress_last_extreme_ts) >= PROGRESS_GAP_NS:
                    self.mfe_progress_count += 1
                self.mfe_progress_last_extreme_ts = ts_event
                self.mfe_progress_previous_extreme = current_mfe

            # Episode-lifecycle studies must NOT emit population rows from the checkpoint
            # grid -- the population runtime above owns candidate existence.
            while self.regime_start_ns > 0 and not getattr(self, "_episode_mode", False):
                T = self.regime_start_ns + (
                    self.next_checkpoint_index + 1
                ) * int(self.cfg.checkpoint_interval_seconds) * NS
                if T > ts_avail:
                    break
                if (T - self.regime_start_ns) > CANDIDATE_TIMEOUT_NS:
                    break

                if T < ts_avail:
                    # Missing 1s bar at checkpoint grid T (e.g. no trades during that second).
                    # Under strict 5s cadence, skip missing checkpoint. Do not back-stamp future bar.
                    self.next_checkpoint_index += 1
                    continue

                # Here T == ts_avail exactly (exact completed 1s bar boundary at checkpoint T)
                self._evaluate_checkpoint(T, price_at_T=c, direction=self.active_regime_dir, triggering_1s_ts_init=ts_avail)
                self.next_checkpoint_index += 1

        if self._target_primitive == "ordered_barrier":
            previous = self.last_ts_seen
            self._resolve_ordered_barriers(
                {"ts": int(ts_avail), "open": o, "high": h, "low": l, "gap": False},
                now_ts=int(ts_avail),
            )
        elif self._target_primitive == "composite":
            previous = self.last_ts_seen
            self._resolve_composite(
                {"ts": int(ts_avail), "open": o, "high": h, "low": l, "gap": False},
                now_ts=int(ts_avail),
            )
        # Resolve any candidate whose forward horizon has now fully elapsed. Ordered
        # after checkpoint evaluation so a candidate declared at T is never swept by the
        # same bar that created it.
        self._sweep_elapsed_horizons(ts_avail)

        self.last_close = c
        self.last_ts_seen = ts_avail

    # --- Stage 3: episode-lifecycle runtime integration --------------------------
    def _episode_dispatch_1s(self, ts_event, ts_init, o, h, l, c, v) -> None:
        """One completed 1s bar: drive the shared 5s/5m feed, the ProviderHost, and the
        population runtime; realize any emitted candidate into a full governed row."""
        from research_workflow.provider_host import (
            STREAM_COMPLETED_1S, STREAM_COMPLETED_5S, STREAM_COMPLETED_5M,
        )
        transitions_5s: list = []
        transitions_5m: list = []
        if self._regime_feed is not None:
            for tr in self._regime_feed.on_completed_1s_bar(
                ts_event=int(ts_event), ts_init=int(ts_init),
                open=float(o), high=float(h), low=float(l), close=float(c), volume=float(v),
            ):
                (transitions_5s if tr.timeframe == "5s" else transitions_5m).append(tr)

        if self._provider_host is not None:
            self._provider_host.dispatch(STREAM_COMPLETED_1S, {
                "ts_init": int(ts_init), "open": float(o), "high": float(h),
                "low": float(l), "close": float(c), "volume": float(v),
            })
            for tr in transitions_5s:
                if self._bucket_ready(tr):
                    self._provider_host.dispatch(STREAM_COMPLETED_5S, self._bucket_event(tr, ts_init))
            for tr in transitions_5m:
                if self._bucket_ready(tr):
                    self._provider_host.dispatch(STREAM_COMPLETED_5M, self._bucket_event(tr, ts_init))

        cur5s = self._regime_feed.state("5s", decision_ts=int(ts_init)) if self._regime_feed is not None else None
        new_events = self._population_runtime.on_completed_1s(
            ts_event=int(ts_event), ts_init=int(ts_init), open=float(o), high=float(h),
            low=float(l), close=float(c), volume=float(v),
            completed_1m_atr=self.regime_engine.atr,
            completed_5s_state=(int(cur5s.regime) if cur5s is not None else None),
            completed_5s_transitions=tuple(transitions_5s),
        )
        for ev in new_events:
            self._episode_candidate_events.append(ev)
            row = self._build_episode_candidate_row(ev, price_at_T=float(c), ts_avail=int(ts_init))
            self._append_candidate(row)
            self._track_pending(row, int(ev.candidate_ts))
            self._episode_candidates_this_regime += 1

    @staticmethod
    def _bucket_ready(tr) -> bool:
        """A completed regime bucket is usable only once its own timeframe ATR has warmed
        (nan/None/<=0 during warmup) and a directional regime is established."""
        s = tr.current
        if s is None or int(s.regime) not in (-1, 1):
            return False
        a = s.atr
        return a is not None and np.isfinite(a) and float(a) > 0.0

    @staticmethod
    def _bucket_event(tr, available_ts: int) -> Dict[str, Any]:
        s = tr.current
        return {
            "close_ts": int(s.close_ts), "available_ts": int(available_ts),
            "direction": int(s.regime), "open": float(s.open), "high": float(s.high),
            "low": float(s.low), "close": float(s.close), "atr": float(s.atr),
        }

    def _episode_dispatch_1m(self, ts_init, o, h, l, c, new_regime, atr_val) -> None:
        """Completed 1m bar -> ProviderHost. ContextAdapter needs EVERY completed 1m
        (EMA-slope series); the regime-geometry adapter self-skips warmup/neutral bars."""
        if self._provider_host is None:
            return
        from research_workflow.provider_host import STREAM_COMPLETED_1M
        self._provider_host.dispatch(STREAM_COMPLETED_1M, {
            "ts_init": int(ts_init), "close_ts": int(ts_init), "direction": int(new_regime or 0),
            "open": float(o), "high": float(h), "low": float(l), "close": float(c),
            "volume": 0.0, "atr": float(atr_val),
        })

    def _episode_regime_transition(self, direction, start_ns, start_price, atr_start, prior_end_close) -> None:
        # Structural geometry has no causal meaning before the 1m Wilder ATR warms up.
        if self._provider_host is None or not (float(atr_start) > 0.0):
            return
        from research_workflow.provider_host import EVENT_REGIME_TRANSITION_1M
        self._provider_host.dispatch(EVENT_REGIME_TRANSITION_1M, {
            "direction": int(direction), "start_ns": int(start_ns),
            "start_price": float(start_price), "atr_start": float(atr_start),
            "prior_end_close": float(prior_end_close),
        })

    def _build_episode_candidate_row(self, ev, *, price_at_T: float, ts_avail: int) -> Dict[str, Any]:
        atr_t = float(self.regime_engine.atr or 0.0)
        geom = self._population_runtime.episode_geometry_snapshot(
            candidate_ts=int(ev.candidate_ts), candidate_price=float(price_at_T),
            candidate_atr=atr_t if atr_t > 0 else 1e-9,
        )
        episode_state = {
            "prevailing_direction": int(ev.prevailing_direction),
            "episode_geometry": geom,
            "prior_deep_pullback_count": int(ev.prior_deep_pullback_count),
            "counter_regime_direction": int(ev.counter_regime_direction),
            "counter_regime_close_ts": int(ev.counter_regime_close_ts),
            "regime_expansion_atr_per_min": None,
        }
        feats: Dict[str, Any] = {}
        if self._provider_host is not None:
            # ATR_T for pullback / counter-regime / direction-normalized-delta geometry;
            # the prevailing 1m regime's FROZEN ATR for Family A (frozen Model-C parent
            # parity -- FLAG B).
            regime_frozen_atr = float(self.regime_frozen_atr or 0.0)
            feats = dict(self._provider_host.snapshot(
                decision_ts=int(ev.candidate_ts), price=float(price_at_T),
                atr=atr_t if atr_t > 0 else 1e-9, episode_state=episode_state,
                family_a_atr=regime_frozen_atr if regime_frozen_atr > 0 else (atr_t if atr_t > 0 else 1e-9),
            ))
        row: Dict[str, Any] = {
            "observation_ts": int(ev.candidate_ts),
            "regime_start_ns": int(ev.prevailing_regime_start_ns),
            "regime_direction": int(ev.prevailing_direction),
            "checkpoint_index": int(ev.arming_cycle_index),
            "prevailing_regime_start_ns": int(ev.prevailing_regime_start_ns),
            "episode_id": str(ev.episode_id),
            "arm_ts": int(ev.arm_ts),
            "candidate_ts": int(ev.candidate_ts),
            "triggering_completed_5s_ts": int(ev.triggering_completed_5s_ts),
            "pullback_start_ts": int(ev.pullback_start_ts),
            "prevailing_direction": int(ev.prevailing_direction),
            "counter_regime_close_ts": int(ev.counter_regime_close_ts),
            "frozen_atr_arm": float(ev.frozen_atr_arm),
            # Candidate-time ATR is generic target-time state (same key both population
            # paths); the TARGET runtime resolves the ordered-barrier entry_reference
            # from the forward tape, so no entry_price is synthesized here.
            "atr_t": atr_t,
            "target_frozen_atr": atr_t,
            "triggering_1s_ts_init": int(ts_avail),
            **feats,
        }
        # Every declared derived-input column is filled by _apply_derived_scores in
        # _append_candidate (RT-04: one implementation, all scorers, both population
        # types). The score obeys availability like any feature -- null inputs -> null
        # score, the candidate row still persists, the value is never fabricated.
        for _s in self._derived_scorers:
            row.setdefault(_s["name"], None)
        return row

    def _compute_running_mfe(self, direction: int) -> float:
        atr = self.regime_frozen_atr
        if atr <= 0:
            return 0.0
        if direction == 1:  # Bullish prevailing trend
            return max(0.0, self.highest_high_since_flip - self.regime_start_close) / atr
        else:  # Bearish prevailing trend
            return max(0.0, self.regime_start_close - self.lowest_low_since_flip) / atr

    def _compute_running_mae(self, direction: int) -> float:
        atr = self.regime_frozen_atr
        if atr <= 0:
            return 0.0
        if direction == 1:
            return max(0.0, self.regime_start_close - self.lowest_low_since_flip) / atr
        else:
            return max(0.0, self.highest_high_since_flip - self.regime_start_close) / atr

    def _get_context_features(self, T: int, atr: float) -> Dict[str, float]:
        ema_slope_short = 0.0
        if len(self.short_ema_history) >= 6:
            ema_slope_short = (self.short_ema_history[-1] - self.short_ema_history[-6]) / (5 * atr)

        ema_slope_long = 0.0
        if len(self.long_ema_history) >= 6:
            ema_slope_long = (self.long_ema_history[-1] - self.long_ema_history[-6]) / (5 * atr)

        ts_pd = pd.Timestamp(T, tz="UTC").tz_convert("America/Chicago")
        minutes_since_open = (ts_pd.hour - 8) * 60 + (ts_pd.minute - 30)
        # Canonical boundary, not a third inline re-derivation (this one previously
        # ended RTH at 15:00 while the accumulator above ended it at 15:15).
        is_rth = 1.0 if is_in_session(T, self.cfg.session) else 0.0

        return {
            "ema_slope_short": float(ema_slope_short),
            "ema_slope_long": float(ema_slope_long),
            "regime_age_bars": float(self.bars_in_regime),
            "is_rth": is_rth,
            "minutes_since_rth_open": float(minutes_since_open),
        }

    def _evaluate_checkpoint(
        self,
        T: int,
        price_at_T: float,
        direction: int,
        triggering_1s_ts_init: Optional[int] = None,
    ) -> None:
        if triggering_1s_ts_init is not None and triggering_1s_ts_init != T:
            raise RuntimeError(
                f"CAUSAL_TIMESTAMP_VIOLATION: triggering_1s_ts_init ({triggering_1s_ts_init}) != checkpoint T ({T})"
            )

        regime_age_s = (T - self.regime_start_ns) / NS
        atr = self.regime_frozen_atr
        if atr <= 0:
            return
        # Target-time ATR: the latest causally completed 1m Wilder ATR(14) available AT T
        # (target_contract atr_source / atr_frozen_at: decision_ts).  Distinct from ``atr``
        # (regime-start frozen ATR used for feature normalization) -- carried separately so
        # the ordered-barrier half-width is frozen at T identically to the episode path.
        target_atr_t = float(self.regime_engine.atr or 0.0)

        current_mfe = self._compute_running_mfe(direction)
        current_mae = self._compute_running_mae(direction)
        current_pnl = (direction * (price_at_T - self.regime_start_close)) / atr
        retained = (current_pnl / current_mfe) if current_mfe > 0 else 0.0

        # Population qualification: an explicit frozen identity allowlist, when declared,
        # is the ONLY test applied -- it supersedes the established filter rather than
        # combining with it, since the two express mutually exclusive population
        # definitions (a live threshold/persistence rule vs. an externally frozen
        # membership set).
        if self._required_identities is not None:
            if (self.regime_start_ns, self.next_checkpoint_index) not in self._required_identities:
                return
        elif self.cfg.established_required:
            if not (
                regime_age_s >= self.cfg.age_gate_seconds
                and current_mfe >= self.cfg.running_mfe_atr_gte
                and self.mfe_progress_count >= self.cfg.new_progress_windows_gte
                and retained >= self.cfg.retained_mfe_ratio_gte
            ):
                return

        # Declared-session gate, resolved through the canonical boundary module.
        # This previously read `510 <= minute_of_day < 900` (08:30-15:00), silently
        # disagreeing with the 08:30-15:15 window used elsewhere in this same file.
        if not is_in_session(T, self.cfg.session):
            return

        # Warmup/lookahead bars are allowed to update state and dispose pending
        # targets, but they must never create primary output rows.  The bounds are
        # injected by the generic partition runner and are absent for normal runs.
        if self.cfg.primary_start_ts is not None and T < self.cfg.primary_start_ts:
            return
        if self.cfg.primary_end_ts is not None and T > self.cfg.primary_end_ts:
            return

        trade_dir = -direction

        if self._requires_fused_ring_snapshot and self.ring:
            # 1. Structural features (27)
            structural_feats = self.structural_geometry_tracker.snapshot(
                checkpoint_ns=T,
                current_price=price_at_T,
                checkpoint_atr=atr,
                five_provenance_close_ts=self.structural_geometry_tracker._five_close_ts,
            )
            regime_exp_speed = structural_feats.get("regime_expansion_atr_per_min")

            # 2. Rolling features (8)
            rolling_feats = self.rolling_productivity_tracker.snapshot(
                checkpoint_ns=T,
                direction=direction,
                current_regime_start_atr=atr,
                regime_expansion_atr_per_min=regime_exp_speed,
            )

            # 3. Base 25 Features
            ot = self.ohlcv_tracker
            obs_ts = T
            
            if not ot._rth_active:
                rth_vol = rth_abs_delta = rth_elapsed = None
            else:
                rth_vol = ot._rth_vol_cum
                rth_abs_delta = ot._rth_abs_delta_cum
                rth_elapsed = (obs_ts - ot._rth_start_ts) / NS if ot._rth_start_ts else 0.0

            ring = self.ring
            n = ring.count
            head = ring.head
            if n < ring.capacity:
                ts_slice = ring.ts[:n]
                opens_slice = ring.opens[:n]
                highs_slice = ring.highs[:n]
                lows_slice = ring.lows[:n]
                closes_slice = ring.closes[:n]
                vols_slice = ring.volumes[:n]
                deltas_slice = ring.deltas[:n]
                bear_vol_slice = ring.bear_vols[:n]
            else:
                idx = np.arange(head, head + n) % ring.capacity
                ts_slice = ring.ts[idx]
                opens_slice = ring.opens[idx]
                highs_slice = ring.highs[idx]
                lows_slice = ring.lows[idx]
                closes_slice = ring.closes[idx]
                vols_slice = ring.volumes[idx]
                deltas_slice = ring.deltas[idx]
                bear_vol_slice = ring.bear_vols[idx]

            # Window 30s
            c30 = obs_ts - 30 * NS
            m30 = ts_slice > c30
            cnt30 = int(m30.sum())
            if ts_slice[0] <= c30 + NS and cnt30 > 0:
                wc30, wo30 = closes_slice[m30], opens_slice[m30]
                p_chg_30s = float(wc30[-1] - wo30[0])
                p_chg_atr_30s = (p_chg_30s / atr) if atr > 0 else None
            else:
                p_chg_30s = p_chg_atr_30s = None

            # Window 60s
            c60 = obs_ts - 60 * NS
            m60 = ts_slice > c60
            cnt60 = int(m60.sum())
            if ts_slice[0] <= c60 + NS and cnt60 > 0:
                wc60, wo60 = closes_slice[m60], opens_slice[m60]
                p_chg_60s = float(wc60[-1] - wo60[0])
                p_chg_atr_60s = (p_chg_60s / atr) if atr > 0 else None
            else:
                p_chg_60s = p_chg_atr_60s = None

            # Window 300s
            c300 = obs_ts - 300 * NS
            m300 = ts_slice > c300
            cnt300 = int(m300.sum())
            if ts_slice[0] <= c300 + NS and cnt300 > 0:
                est_bear_vol_300s = float(bear_vol_slice[m300].sum())
            else:
                est_bear_vol_300s = None

            # Window 1800s
            c1800 = obs_ts - 1800 * NS
            m1800 = ts_slice > c1800
            cnt1800 = int(m1800.sum())
            if ts_slice[0] <= c1800 + NS and cnt1800 > 0:
                w_h1800 = highs_slice[m1800]
                w_l1800 = lows_slice[m1800]
                w_c1800 = closes_slice[m1800]
                w_o1800 = opens_slice[m1800]
                w_v1800 = vols_slice[m1800]
                w_d1800 = deltas_slice[m1800]
                rng_pts_1800 = float(w_h1800.max() - w_l1800.min())
                est_delta_1800 = float(w_d1800.sum())
                up_m = w_c1800 > w_o1800
                dn_m = w_c1800 < w_o1800
                up_v = float(w_v1800[up_m].sum())
                dn_v = float(w_v1800[dn_m].sum())
                up_dn_ratio_1800 = up_v / max(dn_v, 1e-9)
                vol_max_1s_1800 = float(w_v1800.max())
            else:
                rng_pts_1800 = est_delta_1800 = up_dn_ratio_1800 = vol_max_1s_1800 = None

            plt = self.price_level_tracker
            raw_levels = plt._raw_levels()
            available_prices = {name: price for name, (price, family) in raw_levels.items() if price is not None}

            r_5m_low = available_prices.get("rolling_5m_low")
            r_15m_high = available_prices.get("rolling_15m_high")
            r_60m_high = available_prices.get("rolling_60m_high")
            r_15m_low = available_prices.get("rolling_15m_low")
            r_30m_low = available_prices.get("rolling_30m_low")
            r_30m_high = available_prices.get("rolling_30m_high")
            or_low_dev = available_prices.get("opening_range_30m_low_developing")
            or_low_fin = available_prices.get("opening_range_30m_low_final")
            pd_close = available_prices.get("prior_day_close")
            pd_low = available_prices.get("prior_day_low")

            tol = max(plt.tick_size, plt.touch_tolerance_ticks * plt.tick_size)
            n_levels_below = sum(1 for p in available_prices.values() if price_at_T > p + tol)
            if available_prices:
                lo = min(available_prices.values())
                hi = max(available_prices.values())
                w_pts = hi - lo
                full_env_w_atr = (w_pts / atr) if atr else None
                price_pos_env = ((price_at_T - lo) / w_pts) if w_pts > 0 else None
            else:
                full_env_w_atr = price_pos_env = None

            n_avail = len(available_prices)
            if n_avail > 0:
                if trade_dir == -1:
                    behind_prices = [p for p in available_prices.values() if p > price_at_T]
                else:
                    behind_prices = [p for p in available_prices.values() if p < price_at_T]
                pct_behind = len(behind_prices) / n_avail
            else:
                pct_behind = None

            cand_record = {
                "observation_ts": T,
                "regime_start_ns": self.regime_start_ns,
                "regime_direction": direction,
                "checkpoint_index": self.next_checkpoint_index,
                "regime_age_seconds": regime_age_s,
                "close": price_at_T,
                "atr": atr,
                "target_frozen_atr": target_atr_t,
                "running_mfe_atr": current_mfe,
                "running_mae_atr": current_mae,
                "current_pnl_atr": current_pnl,
                "new_progress_windows": self.mfe_progress_count,
                "retained_mfe_ratio": retained,
                "triggering_1s_ts_init": triggering_1s_ts_init if triggering_1s_ts_init is not None else T,
            }

            all_computed_60 = {
                # Base 25:
                "rolling_5m_low_signed_distance_atr": ((price_at_T - r_5m_low) / atr) if (r_5m_low is not None and atr) else None,
                "rth_elapsed_seconds": rth_elapsed,
                "rolling_15m_high_signed_distance_atr": ((price_at_T - r_15m_high) / atr) if (r_15m_high is not None and atr) else None,
                "rolling_60m_high_signed_distance_atr": ((price_at_T - r_60m_high) / atr) if (r_60m_high is not None and atr) else None,
                "rolling_15m_low_signed_distance_atr": ((price_at_T - r_15m_low) / atr) if (r_15m_low is not None and atr) else None,
                "rolling_30m_low_signed_distance_atr": ((price_at_T - r_30m_low) / atr) if (r_30m_low is not None and atr) else None,
                "price_change_points_60s": p_chg_60s,
                "rolling_30m_high_signed_distance_atr": ((price_at_T - r_30m_high) / atr) if (r_30m_high is not None and atr) else None,
                "range_points_1800s": rng_pts_1800,
                "opening_range_30m_low_developing_signed_distance_points": (price_at_T - or_low_dev) if or_low_dev is not None else None,
                "est_bear_vol_sum_300s": est_bear_vol_300s,
                "full_level_envelope_width_atr": full_env_w_atr,
                "rth_vol_cum": rth_vol,
                "est_delta_sum_1800s": est_delta_1800,
                "price_change_atr_60s": p_chg_atr_60s,
                "prior_day_close_signed_distance_atr": ((price_at_T - pd_close) / atr) if (pd_close is not None and atr) else None,
                "up_down_vol_ratio_1800s": up_dn_ratio_1800,
                "price_change_atr_30s": p_chg_atr_30s,
                "pct_levels_behind_trade": pct_behind,
                "prior_day_low_signed_distance_points": (price_at_T - pd_low) if pd_low is not None else None,
                "opening_range_30m_low_final_signed_distance_points": (price_at_T - or_low_fin) if or_low_fin is not None else None,
                "vol_max_1s_1800s": vol_max_1s_1800,
                "price_position_in_full_envelope": price_pos_env,
                "rth_abs_delta_cum": rth_abs_delta,
                "n_levels_below": n_levels_below,

                # Structural 27:
                **structural_feats,

                # Rolling 8:
                **rolling_feats,
            }

            for col in (self._study_feature_aliases or self.cfg.feature_list or all_computed_60.keys()):
                cand_record[col] = all_computed_60.get(col, None)

            self._append_candidate(cand_record)
            self._track_pending(cand_record, T)
            return

        if self._compact_surface:
            # Exact compact V2 surface.  All stateful providers have already
            # consumed the completed input stream; only now, after the cheap
            # population gates pass, calculate the declared snapshot.
            if not self.structural_geometry_tracker.can_snapshot(
                T, self.structural_geometry_tracker._five_close_ts,
            ):
                return
            if getattr(self, "_benchmark_mode", "") in {"checkpoint_only", "baseline"}:
                structural_feats, rolling_feats, velocity_feats = {}, {}, {}
            else:
                structural_feats = self.structural_geometry_tracker.snapshot(
                checkpoint_ns=T,
                current_price=price_at_T,
                checkpoint_atr=atr,
                five_provenance_close_ts=self.structural_geometry_tracker._five_close_ts,
                )
                regime_exp_speed = structural_feats.get("regime_expansion_atr_per_min")
                rolling_feats = self.rolling_productivity_tracker.snapshot(
                checkpoint_ns=T,
                direction=direction,
                current_regime_start_atr=atr,
                regime_expansion_atr_per_min=regime_exp_speed,
                )
                velocity_feats = (
                self.velocity_tracker.calculate(atr=atr)
                if self._execution_plan.calculate_velocity_at_checkpoint and self.velocity_tracker
                else {}
                )
            # Providers retain their small internal output vocabularies.  Bind
            # those outputs to the canonical FeatureInstance keys here, once per
            # eligible checkpoint.  Previously the compact path copied only exact
            # key matches, so canonical arrival/rolling/EMA instances silently
            # became all-null columns even though their state was being updated.
            compact_feats = {
                **structural_feats,
                "rolling_300s_retention_ratio": rolling_feats.get("rolling_5m_retention_ratio"),
                "rolling_300s_current_progress_atr": rolling_feats.get("rolling_5m_current_progress_atr"),
                "rolling_300s_max_progress_atr": rolling_feats.get("rolling_5m_max_progress_atr"),
                "rolling_300s_giveback_atr": rolling_feats.get("rolling_5m_giveback_atr"),
                "arrival_velocity": velocity_feats.get("arrival_vel_20s"),
                "arrival_acceleration": velocity_feats.get("arrival_accel_10s"),
                "ema_slope": self._get_context_features(T, atr).get("ema_slope_short"),
            }
            cand_record = {
                "observation_ts": T,
                "regime_start_ns": self.regime_start_ns,
                "regime_direction": direction,
                "checkpoint_index": self.next_checkpoint_index,
                "regime_age_seconds": regime_age_s,
                "close": price_at_T,
                "atr": atr,
                "target_frozen_atr": target_atr_t,
                "running_mfe_atr": current_mfe,
                "running_mae_atr": current_mae,
                "current_pnl_atr": current_pnl,
                "new_progress_windows": self.mfe_progress_count,
                "retained_mfe_ratio": retained,
                "triggering_1s_ts_init": triggering_1s_ts_init if triggering_1s_ts_init is not None else T,
            }
            for alias in self._study_feature_aliases:
                cand_record[alias] = compact_feats.get(alias)
            self._append_candidate(cand_record)
            self._track_pending(cand_record, T)
            return

        # Extract features causally from all trackers (general exploratory fallback)
        structural_feats = self.structural_geometry_tracker.snapshot(
            checkpoint_ns=T,
            current_price=price_at_T,
            checkpoint_atr=atr,
            five_provenance_close_ts=self.structural_geometry_tracker._five_close_ts,
        )
        regime_exp_speed = structural_feats.get("regime_expansion_atr_per_min")

        rolling_feats = self.rolling_productivity_tracker.snapshot(
            checkpoint_ns=T,
            direction=direction,
            current_regime_start_atr=atr,
            regime_expansion_atr_per_min=regime_exp_speed,
        )

        ohlcv_feats = self.ohlcv_tracker.calculate(atr=atr)
        price_feats = self.price_level_tracker.calculate(T, price_at_T, atr, direction=trade_dir)
        velocity_feats = self.velocity_tracker.calculate(atr=atr) if self.velocity_tracker else {}
        volume_feats = self.volume_tracker.calculate() if self.volume_tracker else {}
        pullback_1s_feats = PullbackTracker.calculate_1s(
            list(self.highs_1s), list(self.lows_1s), list(self.closes_1s), atr
        )
        touch_price = price_at_T
        breach_ref = self.breach_price or (self.short_ema_history[-1] if self.short_ema_history else price_at_T)
        pullback_1m_feats = PullbackTracker.calculate_1m(
            self.bars_since_breach_1m, breach_ref, touch_price, atr, trade_dir
        )
        context_feats = self._get_context_features(T, atr)
        wick_feats = self.wick_tracker.calculate()
        range_position_feats = self.range_position_tracker.calculate()

        merged_raw = {
            **ohlcv_feats,
            **price_feats,
            **structural_feats,
            **rolling_feats,
            **velocity_feats,
            **volume_feats,
            **pullback_1s_feats,
            **pullback_1m_feats,
            **context_feats,
            **wick_feats,
            **range_position_feats,
            # Canonical FeatureInstance alias bridge. These trackers retain their
            # legacy internal output keys (rolling_5m_*, arrival_vel_*/arrival_accel_*,
            # ema_slope_short) rather than the canonical alias names -- the compact
            # V2 surface bridges this explicitly (see its own comment above); this
            # general fallback path previously looked the canonical alias names up
            # directly against merged_raw and silently returned None for every one
            # of them, even though the underlying state was being updated.
            "rolling_300s_retention_ratio": rolling_feats.get("rolling_5m_retention_ratio"),
            "rolling_300s_current_progress_atr": rolling_feats.get("rolling_5m_current_progress_atr"),
            "rolling_300s_max_progress_atr": rolling_feats.get("rolling_5m_max_progress_atr"),
            "rolling_300s_giveback_atr": rolling_feats.get("rolling_5m_giveback_atr"),
            "arrival_velocity": velocity_feats.get("arrival_vel_20s"),
            "arrival_acceleration": velocity_feats.get("arrival_accel_10s"),
            "ema_slope": context_feats.get("ema_slope_short"),
            # est_delta_ratio (30s window): OHLCVDeltaTracker already computes this
            # exact windowed value under its legacy per-window key; GenericOHLCVDeltaProvider
            # (the registry-declared implementation) is itself a thin delegator to the
            # same tracker class, so reading the already-updated self.ohlcv_tracker here
            # is not an approximation -- it is the identical computation.
            "est_delta_ratio": ohlcv_feats.get("est_delta_ratio_30s"),
            # range_position / wick_imbalance: RangePositionTracker/WickTracker compute
            # byte-for-byte the same formulas as GenericRangePositionProvider/
            # GenericWickImbalanceProvider (verified against both implementations) --
            # same lookback default (5), same None-on-unavailable/flat-range semantics.
            "range_position": range_position_feats.get("latest_1m_close_position_prev5_range"),
            "wick_imbalance": wick_feats.get("latest_1m_wick_imbalance"),
            # relative_volume: genuinely wired to the canonical GenericArrivalVolumeProvider
            # (constructed in __init__), NOT the legacy ArrivalVolumeTracker -- the legacy
            # tracker's rvol_5s uses a different cold-start fallback (1.0 instead of None
            # below the full window), which is not the declared contract for this alias.
            "relative_volume": (
                self._relative_volume_provider.relative_volume(
                    aggregation_lookback=self._relative_volume_agg_lookback,
                    baseline_lookback=self._relative_volume_baseline_lookback,
                ) if self._relative_volume_provider is not None else None
            ),
        }

        study_universe = self._study_feature_aliases or self.cfg.feature_list or resolve_runtime_feature_aliases()
        feats_to_log = {k: merged_raw.get(k, None) for k in study_universe}

        cand_record = {
            "observation_ts": T,
            "regime_start_ns": self.regime_start_ns,
            "regime_direction": direction,
            "checkpoint_index": self.next_checkpoint_index,
            "regime_age_seconds": regime_age_s,
            "close": price_at_T,
            "atr": atr,
            "target_frozen_atr": target_atr_t,
            "running_mfe_atr": current_mfe,
            "running_mae_atr": current_mae,
            "current_pnl_atr": current_pnl,
            "new_progress_windows": self.mfe_progress_count,
            "retained_mfe_ratio": retained,
            "triggering_1s_ts_init": triggering_1s_ts_init if triggering_1s_ts_init is not None else T,
            **feats_to_log,
        }

        self._append_candidate(cand_record)
        self._track_pending(cand_record, T)

    def get_candidates_dataframe(self) -> pd.DataFrame:
        if not self.candidates_log:
            return pd.DataFrame()
        return pd.DataFrame(self.candidates_log)

    def get_observations_dataframe(self) -> pd.DataFrame:
        if not self.observations_log:
            return pd.DataFrame()
        return pd.DataFrame(self.observations_log)


# Canonical names for new studies.  The legacy class names remain available only
# inside this implementation module so historical behavior and old imports can
# be shimmed without making them active study identities.
GenericStudyCollector = FlipPredictionCollector
GenericStudyCollectorConfig = FlipPredictionCollectorConfig
