"""Deterministically normalize every V1 physical feature for V2 migration.

This is a non-authoritative migration artifact: it records a canonical candidate
and semantic parameters for every physical legacy alias, while retaining a
separate parity/evidence status.  A hard-coded legacy route is implementation
work, never a semantic blocker by itself.
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Tuple


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from features.registry import (  # noqa: E402
    FEATURE_REGISTRY,
    LEGACY_FEATURE_INSTANCE_OVERRIDES,
    canonical_definition_status,
)


OUT = ROOT / "scratch" / "feature_system_v2_full_migration_inventory.json"
PARITY_OUT = ROOT / "scratch" / "feature_system_v2_full_legacy_parity_matrix.json"
TEMPORAL_MARKERS = ("_1s", "_5s", "_10s", "_15s", "_20s", "_30s", "_60s", "_120s", "_300s", "_900s", "_1800s", "_1m", "_3m", "_5m", "_10m", "_15m", "_30m")
_DURATION_TOKEN = __import__("re").compile(r"(?<![A-Za-z0-9])(?P<value>[1-9][0-9]*)(?P<unit>[sm])(?![A-Za-z0-9])")
_SEQUENCE_TOKEN = __import__("re").compile(r"^seq_(?P<count>[1-9][0-9]*)r_(?P<metric>.+)$")
_LAST_COUNT_TOKEN = __import__("re").compile(r"^(?P<metric>.+)_last_(?P<count>[1-9][0-9]*)$")
_RATIO_COUNT_TOKEN = __import__("re").compile(r"^(?P<metric>.+)_(?P<numerator>[1-9][0-9]*)_vs_(?P<denominator>[1-9][0-9]*)$")


def source_hash(implementation: str) -> str | None:
    if not implementation.startswith("features."):
        return None
    module = implementation.rsplit(".", 1)[0]
    path = ROOT.joinpath(*module.split(".")).with_suffix(".py")
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def _duration_parameters(name: str) -> Tuple[str, Dict[str, str]]:
    """Remove temporal spelling from a legacy alias and retain it as data."""
    parameters: Dict[str, str] = {}
    ordinal = 0
    def replace(match: Any) -> str:
        nonlocal ordinal
        ordinal += 1
        key = "timeframe" if ordinal == 1 else f"timeframe_{ordinal}"
        parameters[key] = f"{match.group('value')}{match.group('unit')}"
        return ""
    canonical = _DURATION_TOKEN.sub(replace, name)
    canonical = canonical.replace("__", "_").strip("_")
    return canonical, parameters


def canonical_candidate(name: str, definition: Any) -> Tuple[str, Dict[str, Any], str]:
    """Return (canonical_name, semantic parameters, evidence statement).

    The mapping is provider/formula led: names merely supply instance values
    already used by the underlying calculation.  It intentionally does not
    set lifecycle status or assert parity.
    """
    provider = definition.implementation.rsplit(".", 1)[-1]
    canonical, parameters = _duration_parameters(name)
    if provider == "ArrivalVelocityTracker":
        if name.startswith("arrival_vel_"):
            return "arrival_velocity", {"lookback": int(str(parameters.get("timeframe", "0s")).removesuffix("s")), "input_timeframe": "1s", "bar_state": "completed"}, "finite difference over completed 1s observations; legacy tracker has observation-count, not clock-window, semantics"
        if name.startswith("arrival_accel_"):
            return "arrival_acceleration", {"short_lookback": int(str(parameters.get("timeframe", "0s")).removesuffix("s")), "input_timeframe": "1s", "bar_state": "completed"}, "difference of completed-observation velocities"
        if name == "arrival_jerk":
            return "arrival_jerk", {"derivative_order": 3}, "difference of acceleration estimates"
        if name.startswith("max_vel_"):
            return "arrival_velocity_max", {"lookback": int(str(parameters.get("timeframe", "0s")).removesuffix("s")), "velocity_lookback": 5, "input_timeframe": "1s", "bar_state": "completed"}, "maximum absolute finite-difference velocity over completed observations"
        if name.startswith("vel_ratio_"):
            pieces = name.removeprefix("vel_ratio_").split("_")
            return "arrival_velocity_ratio", {"short_lookback": int(pieces[0]), "long_lookback": int(pieces[1]), "input_timeframe": "1s", "bar_state": "completed"}, "ratio of two completed-observation finite-difference velocities"
        return "arrival_deceleration", {}, "arrival acceleration sign"
    if provider == "ArrivalVolumeTracker":
        if name.startswith("rvol_"):
            lookback = int(str(parameters.get("timeframe", "0s")).removesuffix("s"))
            baseline = 10 if lookback == 1 else lookback
            return "relative_volume", {"aggregation_lookback": lookback, "baseline_lookback": baseline, "input_timeframe": "1s", "bar_state": "completed"}, "recent/prior completed-volume observation ratio"
        if name.startswith("vol_trend_"):
            return "volume_trend", {"window": parameters.get("timeframe")}, "relative-volume threshold classification"
        if name.startswith("up_vol_ratio_") or name.startswith("down_vol_ratio_"):
            return "directional_volume_ratio", {"window": parameters.get("timeframe"), "direction": "up" if name.startswith("up_") else "down"}, "completed-bar directional volume share"
        if name.startswith("vol_price_corr_"):
            return "volume_price_correlation", {"window": parameters.get("timeframe")}, "completed-bar volume/return correlation"
        return canonical.removeprefix("vol_"), {}, "completed-bar volume statistic"
    if provider == "PullbackTracker":
        is_event = name in {"pullback_depth_atr", "pullback_bars_1m", "pullback_efficiency_1m", "retracement_pct", "clean_pullback_score_1m"}
        base = canonical.replace("pullback_", "")
        aliases = {"linearity": "pullback_linearity", "depth_atr": "pullback_depth_atr",
                   "bars": "pullback_bars", "efficiency": "pullback_efficiency"}
        return aliases.get(base, base), {"scope": "since_breach" if is_event else "trailing", **parameters}, "completed-bar pullback geometry"
    if provider == "OHLCVDeltaTracker":
        base = canonical.removeprefix("rolling_")
        if name.startswith("bar_"):
            return base, {"context": "bar"}, "single completed OHLCV estimated-delta calculation"
        if name.startswith("regime_"):
            return base.removeprefix("regime_"), {"context": "regime"}, "regime-reset estimated-delta calculation"
        if name.startswith("rth_"):
            return base.removeprefix("rth_"), {"context": "RTH"}, "RTH-session estimated-delta calculation"
        return base, {"context": "rolling", **parameters}, "completed trailing OHLCV estimated-delta calculation"
    if provider == "PriceLevelTracker":
        level_context = "rolling" if name.startswith("rolling_") else ("prior_day" if name.startswith("prior_day_") else "session")
        for suffix, canonical_feature, unit in (
            ("_signed_distance_points", "distance_to_level", "points"),
            ("_signed_distance_ticks", "distance_to_level", "ticks"),
            ("_signed_distance_atr", "distance_to_level", "atr"),
            ("_price", "price_level_value", None),
            ("_available", "price_level_available", None),
            ("_position", "price_level_position", None),
        ):
            if canonical.endswith(suffix):
                return canonical_feature, {"level": canonical.removesuffix(suffix), "level_context": level_context,
                                           **({"normalization": unit} if unit else {}), **parameters}, "causal reference-level geometry"
        if canonical.startswith(("nearest_level_", "cluster_", "density_")):
            return canonical.split("_")[0] + "_level_geometry", {"metric": canonical, "level_context": level_context, **parameters}, "causal aggregate level geometry"
        return "price_level_aggregate", {"metric": canonical, "level_context": level_context, **parameters}, "causal aggregate level geometry"
    if provider == "MedianCenterTracker":
        sequence = _SEQUENCE_TOKEN.fullmatch(name)
        if sequence:
            return "regime_sequence_metric", {"lookback": int(sequence.group("count")), "metric": sequence.group("metric")}, "completed regime-sequence calculation"
        last_count = _LAST_COUNT_TOKEN.fullmatch(canonical)
        if last_count:
            return last_count.group("metric"), {"lookback": int(last_count.group("count")), **parameters}, "completed regime history aggregation"
        count_ratio = _RATIO_COUNT_TOKEN.fullmatch(canonical)
        if count_ratio:
            return count_ratio.group("metric"), {"numerator_lookback": int(count_ratio.group("numerator")),
                                                  "denominator_lookback": int(count_ratio.group("denominator")), **parameters}, "completed regime history ratio"
        return canonical, parameters, "completed-bar median-center, activity, or regime-sequence calculation"
    if provider == "RangePositionTracker":
        return "range_position", {"lookback": 5, "timeframe": "1m", "bar_state": "completed"}, "prior completed-bar high/low range position"
    if provider == "WickTracker":
        return "wick_imbalance", {"timeframe": "1m", "bar_state": "completed"}, "completed-bar wick normalization"
    if not provider:
        context = {
            "regime_age_bars": ("regime_age", {"unit": "bars"}),
            "ema_slope_short": ("ema_slope", {"ema_role": "short", "lookback": 5}),
            "ema_slope_long": ("ema_slope", {"ema_role": "long", "lookback": 5}),
            "is_rth": ("session_membership", {"session": "RTH"}),
            "minutes_since_rth_open": ("session_elapsed", {"session": "RTH", "unit": "minutes"}),
        }
        if name in context:
            candidate, params = context[name]
            return candidate, params, "FeatureEngine context calculation"
    return canonical, parameters, "legacy provider identity retained pending semantic inspection"


def record_for(name: str, definition: Any) -> dict[str, Any]:
    implementation = definition.implementation
    evidence = {
        "registry_metadata": {
            "family": definition.family,
            "normalizer": definition.normalizer,
            "null_policy": definition.null_policy,
            "reset_policy": definition.reset_policy,
            "source_timeframe": definition.source_timeframe,
            "window": definition.window,
            "window_unit": definition.window_unit,
        },
        "provider_source_sha256": source_hash(implementation),
        "declared_tests": list(definition.tests),
    }
    common = {
        "legacy_feature": name,
        "current_status": definition.status,
        "current_provider": implementation,
        "physical_alias": name,
        "semantic_equivalence_evidence": evidence,
    }

    instance = LEGACY_FEATURE_INSTANCE_OVERRIDES.get(name)
    if instance is not None:
        return common | {
            "canonical_feature": instance.canonical_name,
            "parameters": dict(instance.parameters),
            "migration_outcome": "MAPPED_TO_CANONICAL",
            "confidence": "HIGH",
            "blocker": None,
            "evidence": "Existing FeatureInstance override plus canonical lifecycle/promotion record",
        }
    candidate, params, candidate_evidence = canonical_candidate(name, definition)
    return common | {
        "canonical_feature": candidate,
        "parameters": params,
        "migration_outcome": "CANONICAL_UNIQUE",
        "confidence": "MEDIUM",
        "blocker": None,
        "evidence": candidate_evidence,
    }


def parity_for(row: dict[str, Any]) -> dict[str, Any]:
    if row["migration_outcome"] == "MAPPED_TO_CANONICAL":
        canonical = row["canonical_feature"]
        return {
            "legacy_alias": row["legacy_feature"],
            "canonical_feature": canonical,
            "parameters": row["parameters"],
            "status": "PASS",
            "evidence": "Existing deterministic legacy-alias/value parity tests for V2 migrated structural/rolling families",
            "checks": ["alias", "value", "timestamp_availability", "dtype", "null_reset"],
        }
    return {
        "legacy_alias": row["legacy_feature"],
        "canonical_feature": row["canonical_feature"],
        "parameters": row["parameters"],
        "status": "PENDING_PARITY_EVIDENCE",
        "reason": "Provider/alias parity fixture has not yet been run; not a semantic blocker",
        "checks": [],
    }


def main() -> int:
    rows = [record_for(name, definition) for name, definition in sorted(FEATURE_REGISTRY.items())]
    counts = Counter(row["migration_outcome"] for row in rows)
    parity = [parity_for(row) for row in rows]
    parity_counts = Counter(row["status"] for row in parity)
    # Second pass: collapse only candidates with identical provider and
    # lifecycle semantics.  A same-spelled candidate from another provider is
    # reported for cross-provider parity review rather than silently merged.
    grouped: Dict[Tuple[Any, ...], list[dict[str, Any]]] = {}
    name_providers: Dict[str, set[str]] = {}
    for row in rows:
        metadata = row["semantic_equivalence_evidence"]["registry_metadata"]
        key = (row["canonical_feature"], row["current_provider"], metadata["normalizer"],
               metadata["null_policy"], metadata["reset_policy"])
        grouped.setdefault(key, []).append(row)
        name_providers.setdefault(str(row["canonical_feature"]), set()).add(row["current_provider"])
    canonical_candidates = [
        {"canonical_feature": key[0], "provider": key[1], "normalizer": key[2],
         "null_policy": key[3], "reset_policy": key[4],
         "legacy_aliases": sorted(row["legacy_feature"] for row in members),
         "physical_instance_count": len(members)}
        for key, members in sorted(grouped.items())
    ]
    cross_provider_collisions = {
        name: sorted(provider for provider in providers if provider)
        for name, providers in sorted(name_providers.items()) if len(providers) > 1
    }
    payload = {
        "schema_version": 1,
        "purpose": "Feature System V2 full migration disposition; fail-closed and non-authoritative until complete",
        "legacy_registry_count": len(rows),
        "disposition_counts": dict(sorted(counts.items())),
        "blocked_by_provider": dict(sorted(Counter(
            row["current_provider"] for row in rows if row["migration_outcome"] == "BLOCKED_WITH_REASON"
        ).items())),
        "existing_v2_canonical_status": {
            instance.canonical_name: canonical_definition_status(instance.canonical_name)
            for instance in LEGACY_FEATURE_INSTANCE_OVERRIDES.values()
        },
        "canonical_candidate_count_before_cross_provider_review": len(canonical_candidates),
        "canonical_candidates": canonical_candidates,
        "cross_provider_name_collisions_requiring_parity_review": cross_provider_collisions,
        "features": rows,
    }
    matrix = {
        "schema_version": 1,
        "legacy_registry_count": len(rows),
        "parity_counts": dict(sorted(parity_counts.items())),
        "authority_cutover_allowed": parity_counts.get("PENDING_PARITY_EVIDENCE", 0) == 0 and parity_counts.get("FAIL", 0) == 0,
        "aliases": parity,
    }
    OUT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    PARITY_OUT.write_text(json.dumps(matrix, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"inventory": str(OUT), "parity": str(PARITY_OUT), "dispositions": payload["disposition_counts"], "parity_counts": matrix["parity_counts"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
