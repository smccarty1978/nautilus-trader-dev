"""Generate the non-authoritative Feature System V2 migration inventory.

This is intentionally a scratch reporting tool.  It reads the live registry and
writes a proposal mapping; it does not modify feature governance or runtime
behaviour.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from features.registry import FEATURE_REGISTRY


OUT = ROOT / "scratch" / "feature_system_v2_registry_mapping.json"


def _time_params(name: str) -> list[dict[str, object]]:
    out = []
    for value, unit in re.findall(r"(?<![a-zA-Z0-9])(\d+)([smr])(?=_|$)", name):
        out.append({"value": int(value), "unit": {"s": "seconds", "m": "minutes", "r": "regimes"}[unit]})
    return out


def _generic_name(name: str) -> str:
    """Produce a proposal only; low-confidence entries remain non-authoritative."""
    name = re.sub(r"_(?:\d+)[sm](?=_|$)", "", name)
    name = re.sub(r"^prior_", "", name)
    name = re.sub(r"^current_", "", name)
    return name


def _classify(name: str, definition) -> tuple[str, str, dict[str, object], str, str]:
    """Return classification, proposed canonical name, parameters, confidence, notes."""
    family = definition.family
    params: dict[str, object] = {}

    # The structural tracker has direct code evidence for all of these mappings.
    match = re.fullmatch(r"prior_(1m|5m)_regime_(.+)", name)
    if match:
        tf, metric = match.groups()
        return "TIMEFRAME_INSTANCE", f"regime_{metric}", {
            "timeframe": tf, "context": "prior", "regime": "completed",
        }, "HIGH", "StructuralRegimeGeometryTracker._completed emits the same metric for 1m and 5m completed regimes."
    match = re.fullmatch(r"current_5m_regime_(.+)", name)
    if match:
        return "TIMEFRAME_INSTANCE", f"regime_{match.group(1)}", {
            "timeframe": "5m", "context": "current", "regime": "completed_bar_state",
        }, "HIGH", "Structural tracker maintains completed 5m state; formula is parameterizable only after generalized tracker parity."
    if name == "current_5m_directional_displacement_atr":
        return "TIMEFRAME_INSTANCE", "regime_directional_displacement_atr", {
            "timeframe": "5m", "context": "current", "regime": "completed_bar_state",
        }, "HIGH", "Tracker normalizes completed 5m directional displacement by its 5m regime-start ATR."
    if name in {"distance_to_completed_5m_high_atr", "distance_to_completed_5m_low_atr"}:
        side = "high" if "_high_" in name else "low"
        return "CROSS_TIMEFRAME_INSTANCE", f"distance_to_completed_range_{side}_atr", {
            "source_timeframe": "1s_checkpoint", "reference_timeframe": "5m", "context": "current",
        }, "HIGH", "Tracker compares checkpoint price with a completed 5m regime extreme."
    if name == "current_1m_move_outside_completed_5m_range":
        return "CROSS_TIMEFRAME_INSTANCE", "move_outside_completed_range", {
            "source_timeframe": "1m", "reference_timeframe": "5m", "context": "current",
        }, "HIGH", "Tracker compares the current 1m regime/checkpoint state against completed 5m range state."
    if family == "structural_regime_geometry":
        if name.startswith("structural_") or name == "regime_expansion_atr_per_min":
            return "CONTEXT_INSTANCE", _generic_name(name), {"context": "structural_current_regime"}, "MEDIUM", "No timeframe is encoded; retain a distinct formula definition unless formula review establishes a shared regime metric."

    # This family is explicitly a 300-second 1s-bar window, not a 5m bar stream.
    if family == "rolling_5m_productivity":
        return "LOOKBACK_INSTANCE", name.replace("rolling_5m_", "rolling_productivity_"), {
            "window": 300, "window_unit": "seconds", "source_timeframe": "1s", "context": "current_regime",
        }, "HIGH", "Rolling5mProductivityTracker requires a contiguous completed 1s [T-300s, T] window."

    if family == "ohlcv_est_delta":
        if "_minus_" in name or "_vs_" in name:
            return "MULTI_PARAMETER_INSTANCE", re.sub(r"_\d+s", "", name), {
                "windows": _time_params(name), "source_timeframe": definition.source_timeframe,
            }, "HIGH", "Registry generator encodes two rolling windows in the physical alias."
        if _time_params(name):
            return "LOOKBACK_INSTANCE", _generic_name(name), {
                "window": _time_params(name)[-1], "source_timeframe": definition.source_timeframe,
            }, "HIGH", "Registry generator encodes rolling completed-time window in alias."
        if name.startswith(("regime_", "rth_")):
            context = "regime" if name.startswith("regime_") else "rth_session"
            return "CONTEXT_INSTANCE", name, {"context": context}, "HIGH", "Registry metadata already identifies event/session reset semantics."
        return "CANONICAL_ALREADY", name, {}, "HIGH", "Per-bar estimated-delta metric; no encoded instance parameter."

    if family == "price_level_context":
        if name.startswith("rolling_"):
            return "MULTI_PARAMETER_INSTANCE", re.sub(r"^rolling_\d+m_", "", name), {
                "reference_window": _time_params(name)[0] if _time_params(name) else None,
                "reference_kind": "rolling_ohlc_level",
            }, "HIGH", "Generated rolling level plus level-field alias."
        level = next((p for p in ("prior_day", "overnight", "rth_open", "opening_range") if name.startswith(p)), None)
        return "CONTEXT_INSTANCE", re.sub(r"^(prior_day|overnight|rth_open|opening_range_30m)_", "", name), {
            "reference_kind": level or "session_level",
        }, "MEDIUM", "Session/level type is an instance context; exact level construction remains a parameter-domain review."

    if family == "regime_median_center_slope_alignment":
        temporal = _time_params(name)
        if len(temporal) >= 2:
            return "MULTI_PARAMETER_INSTANCE", _generic_name(name), {"windows": temporal, "context": "regime_aligned"}, "MEDIUM", "Multiple windows/relations are encoded in the alias; tracker is presently hard-coded to selected windows."
        if temporal:
            return "LOOKBACK_INSTANCE", _generic_name(name), {"window": temporal[0], "context": "regime_aligned"}, "MEDIUM", "Window is encoded in alias; tracker support must become parameterized before migration."
        if name.startswith("seq_"):
            return "LOOKBACK_INSTANCE", re.sub(r"^seq_\d+r_", "sequence_", name), {"regime_count": int(re.search(r"seq_(\d+)r", name).group(1))}, "MEDIUM", "Completed-regime sequence length is an instance parameter."
        return "CONTEXT_INSTANCE", name, {"context": "regime_aligned"}, "LOW", "Name alone is insufficient to separate formula identity from regime context."

    if family in {"arrival_velocity", "arrival_volume"}:
        temporal = _time_params(name)
        if temporal:
            return "LOOKBACK_INSTANCE", _generic_name(name), {"window": temporal[0], "source_timeframe": definition.source_timeframe}, "HIGH", "Tracker receives 1s closes/volume; suffix denotes the rolling window."
        return "CANONICAL_ALREADY", name, {}, "MEDIUM", "No explicit instance parameter in alias."

    if family in {"pullback_1s", "pullback_1m"}:
        temporal = _time_params(name)
        if temporal:
            return "LOOKBACK_INSTANCE", _generic_name(name), {"window": temporal[0], "source_timeframe": definition.source_timeframe}, "MEDIUM", "Suffix is a time window, but pullback tracker has separate calculate_1s/calculate_1m code paths."
        tf = "1s" if family.endswith("1s") else "1m"
        return "GENUINELY_TIMEFRAME_SPECIFIC", _generic_name(name), {"timeframe": tf}, "LOW", "Existing tracker exposes separate 1s and 1m formulas; do not merge without formula parity review."

    if family == "range_position":
        return "MULTI_PARAMETER_INSTANCE", "close_position_in_prior_range", {
            "source_timeframe": "1m", "lookback_bars": 5, "context": "latest_completed",
        }, "HIGH", "Implementation maintains previous five completed 1m bars."
    if family == "wick_imbalance":
        return "TIMEFRAME_INSTANCE", "wick_imbalance", {"timeframe": "1m", "context": "latest_completed"}, "MEDIUM", "Formula appears bar-based but existing tracker only receives completed 1m bars."
    if family == "context":
        if name.startswith("ema_slope_"):
            return "CONTEXT_INSTANCE", "ema_slope", {"ema_span": name.removeprefix("ema_slope_")}, "MEDIUM", "Short/long EMA configuration is implicit in collector regime state."
        if name == "regime_age_bars":
            return "CONTEXT_INSTANCE", "regime_age", {"unit": "bars"}, "MEDIUM", "Bar frequency is supplied by the governing regime state, not the alias."
        return "CANONICAL_ALREADY", name, {}, "HIGH", "Session predicate/value has no encoded duration instance."

    return "AMBIGUOUS", name, {}, "LOW", "No safe normalization rule for this registry family."


def main() -> None:
    rows = []
    for name, definition in sorted(FEATURE_REGISTRY.items()):
        classification, canonical, params, confidence, notes = _classify(name, definition)
        rows.append({
            "current_feature": name,
            "current_status": definition.status,
            "current_implementation": definition.implementation,
            "classification": classification,
            "proposed_canonical_definition": canonical,
            "proposed_parameters": params,
            "physical_alias": name,
            "migration_confidence": confidence,
            "blocker": None if confidence == "HIGH" else "Formula/parameter-domain parity review required before migration",
            "notes": notes,
        })
    payload = {
        "schema_version": 1,
        "purpose": "NON_AUTHORITATIVE Feature System V2 inventory and migration proposal",
        "registry_sha256": hashlib.sha256((ROOT / "features" / "registry.py").read_bytes()).hexdigest(),
        "classification_counts": dict(sorted(Counter(row["classification"] for row in rows).items())),
        "features": rows,
    }
    OUT.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"path": str(OUT), "total": len(rows), "classification_counts": payload["classification_counts"]}, indent=2))


if __name__ == "__main__":
    main()
