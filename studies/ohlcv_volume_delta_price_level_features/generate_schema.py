"""Generate feature_schema.csv/.md from the registry entries for the two new
families (ohlcv_est_delta, price_level_context). Machine-readable schema
required by SPEC.md Part C -- derived, not hand-maintained, so it can never
silently drift from what's actually registered.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from features.registry import FEATURE_REGISTRY  # noqa: E402

NEW_FAMILIES = ("ohlcv_est_delta", "price_level_context")

WINDOW_RE = re.compile(r"_(\d+)(s|m)(?:_|$)")

DESCRIPTIONS = {
    "bar_level": "Per-bar estimated bull/bear volume split by close position within the bar's own high-low range.",
    "rolling_window": "Rolling completed-time-window aggregate over 1s bars (5s-1800s).",
    "cross_window": "Short-vs-long window comparison (e.g. 15s minus 60s) capturing pressure divergence.",
    "regime_relative": "Cumulative volume/delta since the current prevailing 1m regime began, reset on regime change.",
    "rth_cumulative": "Cumulative volume/delta since the current RTH session began, reset each session.",
    "per_level_distance": "Price/availability/signed-distance/position for one approved base level (prior-day, overnight, RTH open, opening range, or rolling-window OHLC).",
    "session_state": "Session/opening-range state flags (developing vs. final, elapsed seconds).",
    "aggregate_counts": "Count/percent of raw levels above, below, or touched by the reference price, plus level_balance.",
    "nearest_geometry": "Nearest raw level above/below the reference price and the resulting space balance.",
    "density_envelope": "Level density within fixed ATR bands, plus the full level envelope (lowest/highest available level).",
    "clustering": "Deterministic median-price clustering of nearby raw levels, and nearest-cluster geometry.",
    "direction_normalized": "Ahead/behind reframing of levels relative to a known trade direction (short: ahead=below).",
}

UNITS = {
    "bar_zero_range": "bool", "window_available": "bool",
    "regime_available": "bool", "rth_available": "bool",
    "opening_range_30m_is_developing": "bool", "opening_range_30m_is_final": "bool",
    "_position": "enum(ABOVE|BELOW|TOUCH|UNAVAILABLE)",
    "_name": "str", "_available": "bool",
    "_atr": "ATR", "_ticks": "ticks", "_points": "points",
    "vol": "contracts", "n_": "count", "pct_": "fraction[0,1]",
    "_seconds": "seconds", "_ratio": "ratio",
}


def infer_units(name: str) -> str:
    for key, unit in UNITS.items():
        if key in name:
            return unit
    return "float"


def infer_window(name: str) -> str:
    m = WINDOW_RE.search(name)
    return f"{m.group(1)}{m.group(2)}" if m else ""


def infer_availability_rule(subfamily: str, name: str) -> str:
    if subfamily == "bar_level":
        return "always available once >=1 bar fed"
    if subfamily == "rolling_window":
        return "available once buffered history spans the full window (ohlcv_delta: time-span check; " \
               "see window_available_<W>s companion flag)"
    if subfamily == "cross_window":
        return "available iff both constituent windows are available"
    if subfamily == "regime_relative":
        return "available once reset_regime() has been called for the active regime"
    if subfamily == "rth_cumulative":
        return "available only while the current RTH session is active"
    if subfamily == "per_level_distance":
        return "available once the underlying level is causally established (see SPEC Part B1 per-level rule)"
    if subfamily == "session_state":
        return "available once RTH has opened for the current trading day"
    if subfamily in ("aggregate_counts", "nearest_geometry", "density_envelope", "clustering", "direction_normalized"):
        return "computed over currently-available raw levels only; count/percent fields are null if 0 levels available"
    return "see tracker implementation"


def main() -> None:
    rows = []
    for name, d in FEATURE_REGISTRY.items():
        if d.family not in NEW_FAMILIES:
            continue
        # subfamily inferred from the registry-generation loop structure in
        # registry.py (family + a small set of naming patterns).
        if d.family == "ohlcv_est_delta":
            if name.startswith("bar_"):
                subfamily = "bar_level"
            elif name.startswith("window_available_") or any(
                    name.endswith(f"_{w}s") for w in (5, 15, 30, 60, 120, 300, 900, 1800)):
                subfamily = "rolling_window"
            elif name.startswith("regime_"):
                subfamily = "regime_relative"
            elif name.startswith("rth_"):
                subfamily = "rth_cumulative"
            else:
                subfamily = "cross_window"
        else:
            if name.startswith(("n_level_clusters", "nearest_cluster", "max_cluster", "max_nearby_cluster")):
                subfamily = "clustering"
            elif name.startswith(("levels_ahead", "levels_behind", "pct_levels_ahead", "pct_levels_behind",
                                  "nearest_level_ahead", "nearest_level_behind", "nearest_cluster_ahead",
                                  "nearest_cluster_behind", "directional_space_balance")):
                subfamily = "direction_normalized"
            elif name.startswith(("level_density", "levels_above_within", "levels_below_within",
                                  "inverse_distance_density", "lowest_available_level",
                                  "highest_available_level", "full_level_envelope", "price_position_in_full_envelope",
                                  "distance_above_full_envelope", "distance_below_full_envelope")):
                subfamily = "density_envelope"
            elif name.startswith(("n_levels_", "pct_levels_", "level_balance", "n_prior_day_levels",
                                  "n_session_levels", "n_rolling_levels")):
                subfamily = "aggregate_counts"
            elif name.startswith("nearest_level_"):
                subfamily = "nearest_geometry"
            elif name.startswith(("nearest_space", "nearest_upside_downside")):
                subfamily = "nearest_geometry"
            elif name.startswith(("opening_range_30m_is_", "opening_range_30m_elapsed", "rth_open_elapsed")):
                subfamily = "session_state"
            else:
                subfamily = "per_level_distance"

        direction_or_absolute = "directional" if (
            d.family == "price_level_context" and subfamily == "direction_normalized"
        ) else "absolute"

        rows.append({
            "feature_name": name,
            "family": d.family,
            "subfamily": subfamily,
            "dtype": "bool" if ("available" in name or name.endswith(("_developing", "_final", "_touch"))
                               or name in ("bar_zero_range",)) else
                    ("str" if name.endswith("_name") or name.endswith("_position") else "float64"),
            "units": infer_units(name),
            "window": infer_window(name),
            "source": d.source_timeframe,
            "availability_rule": infer_availability_rule(subfamily, name),
            "normalization": d.normalizer,
            "directional_or_absolute": direction_or_absolute,
            "description": DESCRIPTIONS.get(subfamily, ""),
            "status": d.status,
            "implementation": d.implementation,
        })

    df = pd.DataFrame(rows).sort_values(["family", "subfamily", "feature_name"]).reset_index(drop=True)
    df.to_csv(HERE / "feature_schema.csv", index=False)

    lines = ["# Feature Schema — OHLCV Volume/Delta & Price-Level Context", "",
            f"Generated from `features/registry.py` — {len(df)} new features "
            f"({(df.family == 'ohlcv_est_delta').sum()} in `ohlcv_est_delta`, "
            f"{(df.family == 'price_level_context').sum()} in `price_level_context`). "
            "Regenerate with `python generate_schema.py` after any registry change; "
            "never hand-edit `feature_schema.csv`.", ""]
    for family in NEW_FAMILIES:
        fam_df = df[df.family == family]
        lines.append(f"## `{family}` ({len(fam_df)} features)")
        lines.append("")
        for subfamily in fam_df["subfamily"].unique():
            sub_df = fam_df[fam_df.subfamily == subfamily]
            lines.append(f"### {subfamily} ({len(sub_df)})")
            lines.append("")
            lines.append(sub_df.iloc[0]["description"])
            lines.append("")
            lines.append("| feature_name | dtype | units | window | source | normalization |")
            lines.append("|---|---|---|---|---|---|")
            for _, r in sub_df.iterrows():
                lines.append(f"| `{r.feature_name}` | {r.dtype} | {r.units} | {r.window or '-'} | "
                            f"{r.source} | {r.normalization} |")
            lines.append("")
    (HERE / "feature_schema.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote feature_schema.csv/.md: {len(df)} rows "
          f"({(df.family == 'ohlcv_est_delta').sum()} ohlcv_est_delta, "
          f"{(df.family == 'price_level_context').sum()} price_level_context)")


if __name__ == "__main__":
    main()
