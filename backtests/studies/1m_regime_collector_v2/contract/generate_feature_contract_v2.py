"""Generate feature_contract_v2.json per collector_v2_spec.md.

Output: models/ml_5m_flip/feature_contract_v2.json

Emits a locked contract for the v2 feature set. Every feature is
annotated with name, index, dtype, source_timeframe, definition,
snap_point, snap_call_order_anchor, null_policy, default, is_required,
parity_tolerance, tolerance_category, value_range, and notes.

Deferred features (per §15.10) are NOT in this contract; they will
enter v2.1 or an exit-study contract.
"""

import sys
import os
import json
from pathlib import Path

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

OUT_PATH = "models/ml_5m_flip/feature_contract_v2.json"

CONTRACT_VERSION = "v2"
CONTRACT_DESCRIPTION = (
    "Feature contract v2 for the 1m-regime / 30s-checkpoint collector. "
    "Snap semantics match collector_v2_spec.md §3.5 / §5.5 / §7.1. "
    "Any change to names, definitions, null policy, default values, or "
    "snap-call-order requires a new contract version (v3). Deferred "
    "features per §15.10 are not included and will enter v2.1."
)

# Tolerance defaults (same categories as v1)
TOL = {
    "bit_exact": 1e-12,
    "tight": 1e-9,
    "loose": 1e-6,
    "looser": 1e-4,
}

# Feature role taxonomy (NEW in v2)
ROLE_VALUES = {
    "model_feature": (
        "Actively used as ML model input. Varies across events and/or "
        "checkpoints."
    ),
    "metadata_only": (
        "Emitted in the feature table for downstream filtering or "
        "stratification but MUST NOT be used as ML model input."
    ),
    "compat_alias": (
        "Stores the same numeric value as another named feature "
        "(see `alias_of` in the feature entry). Kept for contract "
        "stability / semantic clarity with prior spec text. NOT "
        "recommended for ML inclusion alongside its source feature "
        "(redundant information)."
    ),
    "constant_by_construction": (
        "Value is fixed by the event-definition rules (e.g., always 1 "
        "for every emitted event). Zero-variance; NOT useful as a model "
        "feature. Kept for contract stability and as a sanity-check "
        "column."
    ),
}

# Null policy documentation
NULL_POLICY_DOCS = {
    "disallow": (
        "Column must be present and non-null for every emitted row. A "
        "null in this column is a bug and the row should not be emitted."
    ),
    "nullable_explicit": (
        "Column MUST exist in every row (required column), but values "
        "MAY be null under documented conditions (e.g., 'no prior "
        "regime exists'). Downstream consumers must handle null."
    ),
    "default_filled": (
        "Column is always populated. If the natural computation is "
        "undefined (e.g., zero denominator), the contract-specified "
        "default is used."
    ),
}

# Snap-call-order anchors (referenced by features)
SNAP_ANCHORS = {
    "signal_time_root": (
        "Snap at bar+1 close (signal_time) inside _check_confirmation, "
        "AFTER atr_14.update_raw(bar1), AFTER regime_1m.update(bar1), "
        "AFTER _update_5m(bar1) if bar1 is a 5m boundary, BEFORE the "
        "event is appended to the active-trades collection. Indicator "
        "state reflects all bars with ts_init <= signal_time."
    ),
    "checkpoint_time_dynamic": (
        "Snap at decision_time inside _snap_checkpoint(T, current_ts) "
        "called from _emit_30s_bar at NT processing time ts_init = "
        "decision_time + 1s. Ordering per §5.5: 30s aggregation fires "
        "first, then checkpoint snap reads regime_30s / regime_5m / "
        "regime_1m state AFTER the 30s update but BEFORE any 1m-bar "
        "update at the same shared ts_init."
    ),
    "static_per_event": (
        "Constant per event; set at registration, never updates."
    ),
    "checkpoint_derived": (
        "Derived at decision_time from indicator/state values snapped "
        "in checkpoint_time_dynamic. No additional state; pure function "
        "of snap-time inputs."
    ),
    "post_signal_evolution": (
        "Computed at decision_time from the 1s-bar buffer spanning "
        "[signal_time, decision_time]. Buffer is append-only; "
        "decision_time values reflect only bars with "
        "ts_event <= decision_time."
    ),
}


def mk(name, idx, dtype, tf, definition, snap_point, anchor,
       null_policy="disallow", default=None, is_required=True,
       tol_cat="tight", value_range=None, notes="",
       role="model_feature", alias_of=None):
    if role not in ROLE_VALUES:
        raise ValueError(
            f"Invalid role '{role}' for feature {name}. "
            f"Must be one of {list(ROLE_VALUES)}.")
    entry = {
        "name": name, "index": idx, "dtype": dtype,
        "source_timeframe": tf, "definition": definition,
        "snap_point": snap_point, "snap_call_order_anchor": anchor,
        "null_policy": null_policy,
        "default_value_if_applicable": default,
        "is_required": is_required,
        "parity_tolerance_category": tol_cat,
        "parity_tolerance": TOL[tol_cat],
        "value_range": value_range,
        "role": role,
        "notes": notes,
    }
    if alias_of is not None:
        entry["alias_of"] = alias_of
    return entry


def _set_role(features, name, role, alias_of=None, notes_append=None):
    """Post-process helper: tag a feature's role after construction."""
    for f in features:
        if f["name"] == name:
            f["role"] = role
            if alias_of is not None:
                f["alias_of"] = alias_of
            if notes_append:
                f["notes"] = (f["notes"] + " | " + notes_append
                               if f["notes"] else notes_append)
            return
    raise KeyError(f"Feature '{name}' not found for role assignment")


def _enum_features():
    """Return the ordered list of all v2 features. Each entry carries
    its own position via make_entry's index param."""
    out = []
    i = 0

    SIG = "signal_time"
    CKP = "decision_time"
    STATIC = "static"
    ANCH_ROOT = "signal_time_root"
    ANCH_STATIC = "static_per_event"
    ANCH_CKP = "checkpoint_time_dynamic"
    ANCH_POST = "post_signal_evolution"

    # ===== Static per-event =====
    out.append(mk(
        "signal_direction", i, "int", "derived",
        "+1 long, -1 short — signed direction of the confirmed flip.",
        STATIC, ANCH_STATIC, tol_cat="bit_exact",
        value_range="{-1, 1}")); i += 1
    out.append(mk(
        "atr_at_signal", i, "float64", "1m",
        "NT AverageTrueRange(14) value at signal_time, after bar+1 "
        "has been included in the indicator state. Canonical "
        "normalization denominator across the event.",
        SIG, ANCH_ROOT, tol_cat="loose",
        notes="Wilder smoothing accumulates FP drift; loose tolerance")); i += 1
    out.append(mk(
        "atr_at_checkpoint", i, "float64", "1m",
        "ATR(14) value at decision_time. Not used for normalization; "
        "provided raw for research into intra-event ATR drift.",
        CKP, ANCH_CKP, tol_cat="loose",
        notes="NOT a normalizer (see §3.5). Informational only.")); i += 1

    # ===== §6.1 Flip bar anatomy =====
    flip_anatomy = [
        ("flip_range_atr", "(flip_bar.h - flip_bar.l) / atr_at_signal"),
        ("flip_body_atr", "abs(flip_bar.c - flip_bar.o) / atr_at_signal"),
        ("flip_body_pct", "body / range, 0 if range==0"),
        ("flip_close_location", "(c - l) / (h - l), 0.5 if range==0"),
        ("flip_upper_wick_pct", "(h - max(o, c)) / range, 0 if range==0"),
        ("flip_lower_wick_pct", "(min(o, c) - l) / range, 0 if range==0"),
        ("flip_volume", "Total volume of flip bar"),
        ("flip_vol_vs_20avg", "flip_bar.v / mean volume of 20 prior 1m bars"),
        ("flip_close_vs_prior_close_atr",
            "(flip.c - prior.c) * signal_direction / atr_at_signal"),
        ("flip_high_vs_prior_high_atr",
            "(flip.h - prior.h) * signal_direction / atr_at_signal"),
        ("flip_low_vs_prior_low_atr",
            "(flip.l - prior.l) * signal_direction / atr_at_signal"),
        ("flip_bar_bullish_volume_pct",
            "sum(up-candle 1s vol) / (up + down vols), 0.5 default"),
        ("flip_bar_vol_rank_20",
            "Rank of flip.v among prior 20 1m bar volumes, [0, 1]"),
    ]
    for name, defn in flip_anatomy:
        if "bullish_volume" in name or "location" in name:
            default = 0.5
        elif "wick_pct" in name or "body_pct" in name:
            default = 0.0
        else:
            default = None
        tc = "tight"
        if name == "flip_volume":
            tc = "bit_exact"
        elif name == "flip_vol_vs_20avg":
            tc = "loose"
        out.append(mk(name, i, "float64" if name != "flip_volume" else "float64",
                       "1m", defn, SIG, ANCH_ROOT, tol_cat=tc,
                       default=default))
        i += 1

    # ===== §6.1 Bar+1 anatomy =====
    bar1_anatomy = [
        ("bar1_range_atr", "(bar1.h - bar1.l) / atr_at_signal"),
        ("bar1_body_atr", "abs(bar1.c - bar1.o) / atr_at_signal"),
        ("bar1_body_pct", "bar1 body/range"),
        ("bar1_close_location", "(bar1.c - bar1.l) / bar1.range, 0.5 default"),
        ("bar1_upper_wick_pct", "bar1 upper wick fraction of range"),
        ("bar1_lower_wick_pct", "bar1 lower wick fraction of range"),
        ("bar1_volume", "bar1 total volume"),
        ("bar1_vol_vs_flip_vol", "bar1.v / flip.v, 1.0 if flip.v==0"),
        ("bar1_vol_rank_20", "bar1 volume rank vs prior 20 1m bars"),
        ("bar1_hh_amount_atr",
            "long: (bar1.h - flip.h)/atr; short: (flip.l - bar1.l)/atr"),
        ("bar1_close_vs_flip_close_atr",
            "(bar1.c - flip.c) * signal_direction / atr_at_signal"),
        ("bar1_close_above_flip_close",
            "1 if (bar1.c - flip.c) * direction > 0 else 0"),
        ("bar1_close_above_50pct_range",
            "1 if bar1.close_location in favor of direction else 0"),
        ("bar1_bullish_volume_pct",
            "bar1 up_vol / (up + down), 0.5 default"),
        ("bar1_confirmed_hh_ll",
            "1 if HH (long) or LL (short) confirmed — by construction "
            "always 1 for events in this lineage; retained for contract "
            "stability"),
    ]
    for name, defn in bar1_anatomy:
        tc = "tight"
        default = None
        if "confirmed_hh_ll" in name or "close_above" in name:
            tc = "bit_exact"
            default = None
        elif name == "bar1_volume":
            tc = "bit_exact"
        elif "bullish_volume" in name or "close_location" in name:
            default = 0.5
        elif "wick_pct" in name or "body_pct" in name:
            default = 0.0
        elif name == "bar1_vol_vs_flip_vol":
            default = 1.0
            tc = "loose"
        out.append(mk(name, i, "float64" if "volume" in name else "float64",
                       "1m", defn, SIG, ANCH_ROOT, tol_cat=tc,
                       default=default,
                       value_range="{0, 1}" if "confirmed_hh_ll" in name or "close_above" in name else None))
        i += 1

    # ===== §6.1 Two-bar =====
    two_bar = [
        ("two_bar_range_atr",
            "(max(flip.h, bar1.h) - min(flip.l, bar1.l)) / atr_at_signal"),
        ("two_bar_body_atr",
            "(bar1.c - flip.o) * signal_direction / atr_at_signal"),
        ("two_bar_close_vs_open_pct",
            "(bar1.c - flip.o) / flip.o"),
        ("two_bar_volume_total", "flip.v + bar1.v"),
        ("two_bar_vol_vs_40avg",
            "(flip.v + bar1.v) / mean of prior 40 1m bar volumes"),
        ("flip_low_to_bar1_high_atr",
            "Same as two_bar_range_atr (legacy alias retained for contract "
            "stability)"),
    ]
    for name, defn in two_bar:
        tc = "tight"
        if "volume_total" in name:
            tc = "bit_exact"
        elif "vol_vs_40" in name:
            tc = "loose"
        out.append(mk(name, i, "float64", "1m", defn, SIG, ANCH_ROOT,
                       tol_cat=tc))
        i += 1

    # ===== §6.2 A — Pre-signal lookback features (N in {3,5,10}) =====
    pre_stems = [
        ("range_atr", "mean(B[j].high - B[j].low for j=1..N) / atr_at_signal", "tight", None),
        ("net_return_atr", "(B[N].close - B[1].open) * direction / atr_at_signal", "tight", None),
        ("body_efficiency",
            "abs(B[N].close - B[1].open) / sum(B[j].high - B[j].low for j=1..N), 0 if denom==0",
            "tight", 0.0),
        ("up_bar_fraction", "count(j in 1..N: B[j].close > B[j].open) / N", "tight", None),
        ("down_bar_fraction", "count(j in 1..N: B[j].close < B[j].open) / N", "tight", None),
        ("hh_count", "count(j in 2..N: B[j].high > B[j-1].high) / (N-1)", "tight", None),
        ("ll_count", "count(j in 2..N: B[j].low < B[j-1].low) / (N-1)", "tight", None),
        ("close_near_high_fraction",
            "count(j in 1..N with (B[j].close-B[j].low)/(B[j].high-B[j].low) >= 0.75) / N "
            "(bars with range=0 excluded from both numerator and denominator)",
            "tight", None),
        ("close_near_low_fraction",
            "count(j in 1..N with (B[j].close-B[j].low)/(B[j].high-B[j].low) <= 0.25) / N "
            "(bars with range=0 excluded from both numerator and denominator)",
            "tight", None),
        ("volume_total", "sum(B[j].volume for j=1..N)", "bit_exact", None),
        ("vol_vs_avg", "volume_total / (N × mean_vol_prior_20), 1.0 if denom=0", "loose", 1.0),
        ("mean_body_pct",
            "mean over j in 1..N of |B[j].close - B[j].open| / max(B[j].high - B[j].low, 1e-9)",
            "tight", None),
        ("mean_wickiness",
            "mean over j in 1..N of (B[j].high - max(B[j].open, B[j].close) + "
            "min(B[j].open, B[j].close) - B[j].low) / max(B[j].high - B[j].low, 1e-9)",
            "tight", None),
    ]
    for N in [3, 5, 10]:
        for suffix, defn, tc, default in pre_stems:
            name = f"pre_{N}_{suffix}"
            out.append(mk(name, i, "float64", "1m",
                           defn.replace("N", str(N)),
                           SIG, ANCH_ROOT, tol_cat=tc,
                           default=default))
            i += 1

    # ===== §6.2 B — Compression features =====
    comp = [
        ("pre_signal_range_compression_3v10",
            "mean_range(last_3) / max(mean_range(prior_7), 1e-9)"),
        ("pre_signal_body_compression_3v10",
            "mean(|c-o|) over last_3 / max(mean over prior_7, 1e-9)"),
        ("pre_signal_atr_ratio_3v10",
            "true_range_mean(last_3) / max(true_range_mean(prior_7), 1e-9)"),
        ("pre_signal_vol_compression_3v10",
            "mean(vol) over last_3 / max(mean over prior_7, 1e-9)"),
        ("pre_signal_breakout_from_compression_flag",
            "1 if range_compression_3v10 < 0.6 AND flip_range_atr > "
            "1.5 × mean_range(last_3)/atr_at_signal else 0"),
    ]
    for name, defn in comp:
        tc = "bit_exact" if name.endswith("flag") else "loose"
        vr = "{0, 1}" if name.endswith("flag") else None
        out.append(mk(name, i, "float64", "1m", defn, SIG, ANCH_ROOT,
                       tol_cat=tc, value_range=vr))
        i += 1

    # ===== §6.2 C — Local structure / location =====
    local = [
        ("dist_to_recent_high_5_atr",
            "(max high over B[1..5] - flip.close) / atr_at_signal"),
        ("dist_to_recent_low_5_atr",
            "(flip.close - min low over B[1..5]) / atr_at_signal"),
        ("dist_to_recent_high_10_atr",
            "(max high over B[1..10] - flip.close) / atr_at_signal"),
        ("dist_to_recent_low_10_atr",
            "(flip.close - min low over B[1..10]) / atr_at_signal"),
        ("dist_to_recent_midpoint_10_atr",
            "(flip.close - (max_high_10 + min_low_10)/2) / atr_at_signal "
            "— signed"),
        ("position_in_recent_range_10",
            "(flip.close - min_low_10) / max(max_high_10 - min_low_10, 1e-9); "
            "0.5 if denom=0; range [0,1]"),
        ("failed_push_count_pre_signal",
            "count j in 2..10 where (B[j].h > B[j-1].h AND B[j].c < B[j-1].h) "
            "OR (B[j].l < B[j-1].l AND B[j].c > B[j-1].l). Previous-bar "
            "reference."),
        ("swing_extension_at_signal_atr",
            "long: (flip.c - min_low_10)/atr; short: (max_high_10 - flip.c)/atr"),
    ]
    for name, defn in local:
        tc = "bit_exact" if name == "failed_push_count_pre_signal" else "tight"
        default = 0.5 if "position_in" in name else None
        out.append(mk(name, i, "int" if name.endswith("_count_pre_signal") else "float64",
                       "1m", defn, SIG, ANCH_ROOT, tol_cat=tc,
                       default=default))
        i += 1

    # ===== §6.2 D — Trend quality =====
    for N in [5, 10]:
        for suffix, defn in [
            ("trend_efficiency", f"|B[{N}].c - B[1].o| / sum of ranges, 0 if denom=0, range [0,1]"),
            ("chopiness", f"1 - trend_efficiency_{N}"),
            ("directional_consistency",
                f"count of bars with sign(B[j].c - B[j-1].c) == sign(B[{N}].c - B[1].o) / ({N}-1)"),
        ]:
            out.append(mk(f"pre_signal_{suffix}_{N}", i, "float64", "1m",
                           defn, SIG, ANCH_ROOT, tol_cat="tight",
                           value_range="[0, 1]" if "efficiency" in suffix or "consistency" in suffix or "chopiness" in suffix else None))
            i += 1

    # ===== §6.3 1m regime context =====
    rgc = [
        ("prior_regime_duration_bars", "int",
            "Number of 1m bars the prior regime lasted from its own flip "
            "through the bar BEFORE the current flip_bar (inclusive)",
            "bit_exact"),
        ("prior_regime_mfe_atr", "float64",
            "Peak favorable excursion of the immediately prior regime, "
            "from that prior regime's bar+1 close, normalized by "
            "atr_at_signal of CURRENT event. NaN if no prior or prior "
            "unconfirmed.", "loose"),
        ("regime_flips_last_30min", "int",
            "Count of regime flips in the 30 1m bars prior to signal_time",
            "bit_exact"),
        ("regime_flips_last_60min", "int",
            "Count of regime flips in the 60 1m bars prior to signal_time",
            "bit_exact"),
        ("avg_regime_duration_last_5", "float64",
            "Mean duration in 1m bars of the last 5 fully completed "
            "regimes before current signal. NaN if < 1 completed.",
            "loose"),
        ("consecutive_trend_bars_pre_flip", "int",
            "Consecutive same-direction close-to-close moves in the 5 "
            "1m bars prior to flip_bar", "bit_exact"),
    ]
    for name, dtype, defn, tc in rgc:
        nullable = "nullable_explicit" if name in ("prior_regime_mfe_atr", "avg_regime_duration_last_5") else "disallow"
        out.append(mk(name, i, dtype, "1m", defn, SIG, ANCH_ROOT,
                       null_policy=nullable, tol_cat=tc))
        i += 1

    # ===== §6.3 Signal-time MA / trend state =====
    ma = [
        ("atr_14", "float64", "1m",
            "Same as atr_at_signal. Duplicate column kept for contract "
            "stability with v1 consumers.", "loose"),
        ("price_vs_sma20_atr", "float64", "1m",
            "(flip.c - sma20_1m.value) / atr_at_signal; sma includes flip bar",
            "loose"),
        ("price_vs_sma50_atr", "float64", "1m",
            "(flip.c - sma50_1m.value) / atr_at_signal",
            "loose"),
        ("sma20_slope_atr", "float64", "1m",
            "(sma20.value - sma20 5 bars ago) / atr_at_signal",
            "loose"),
        ("sma50_slope_atr", "float64", "1m",
            "(sma50.value - sma50 10 bars ago) / atr_at_signal",
            "loose"),
        ("sma20_vs_sma50_atr", "float64", "1m",
            "(sma20.value - sma50.value) / atr_at_signal",
            "loose"),
        ("ema3_slope_atr", "float64", "1m",
            "(ema3.value - ema3 5 bars ago) / atr_at_signal",
            "loose"),
        ("ema_spread_atr", "float64", "1m",
            "(emaH_3 - emaL_3) / atr_at_signal from regime_1m state",
            "loose"),
        ("ema3_ema9_spread_atr", "float64", "1m",
            "(ema3.value - ema9.value) / atr_at_signal",
            "loose"),
    ]
    for name, dtype, tf, defn, tc in ma:
        out.append(mk(name, i, dtype, tf, defn, SIG, ANCH_ROOT,
                       tol_cat=tc))
        i += 1

    # ===== §6.3 Signal-time volume =====
    vol = [
        ("vol_1m_20avg", "Mean volume of last 20 1m bars (rolling)"),
        ("vol_ratio_up_down_10bar", "sum(up_vol)/sum(down_vol) last 10 bars; 1.0 default"),
        ("vol_ratio_up_down_20bar", "same over last 20 bars; 1.0 default"),
        ("vol_acceleration_5bar",
            "(last 5 avg vol - prior 5 avg vol) / prior 5 avg vol; 0.0 default"),
        ("high_vol_bar_count_10",
            "Count of last 10 bars with vol > 1.5 × vol_1m_20avg (int)"),
        ("cumulative_volume_bias_10",
            "sum(up_vol - down_vol) / sum(total_vol) over last 10 1m bars"),
    ]
    for name, defn in vol:
        dtype = "int" if "count" in name else "float64"
        tc = "bit_exact" if "count" in name else "loose"
        default = None
        if "ratio_up_down" in name:
            default = 1.0
        elif name == "vol_acceleration_5bar":
            default = 0.0
        out.append(mk(name, i, dtype, "1m", defn, SIG, ANCH_ROOT,
                       tol_cat=tc, default=default))
        i += 1

    # ===== §6.6 Session/timing at signal =====
    sess_sig = [
        ("is_rth", "int", "1 if 510 <= ct_min < 900 (8:30-15:00 CT) else 0",
            "bit_exact", "{0, 1}"),
        ("hour_of_day", "int", "Hour of CT at signal_time", "bit_exact", "[0, 23]"),
        ("minute_of_hour", "int", "Minute of hour CT", "bit_exact", "[0, 59]"),
        ("minutes_since_rth_open", "int", "ct_min - 510 (negative pre-RTH)",
            "bit_exact", None),
        ("distance_from_session_high_atr", "float64",
            "(session_high - flip.c) / atr_at_signal. Session resets at 17:00 CT.",
            "tight", None),
        ("distance_from_session_low_atr", "float64",
            "(flip.c - session_low) / atr_at_signal", "tight", None),
        ("distance_from_session_mid_atr", "float64",
            "(flip.c - (session_high + session_low)/2) / atr_at_signal",
            "tight", None),
        ("session_bars_since_open", "int",
            "1m bars elapsed since current session start (0 = first bar)",
            "bit_exact", None),
        ("session_warmup_flag", "int",
            "1 if session_bars_since_open < 10, else 0",
            "bit_exact", "{0, 1}"),
    ]
    for name, dtype, defn, tc, vr in sess_sig:
        out.append(mk(name, i, dtype, "derived", defn, SIG, ANCH_ROOT,
                       tol_cat=tc, value_range=vr))
        i += 1

    # ===== §6.4 Checkpoint-time dynamic features =====
    # A. Time/elapsed
    time_feats = [
        ("checkpoint_s", "int",
            "T_d in seconds (0, 30, 60, ...). Same as decision_checkpoint_s.",
            "bit_exact"),
        ("checkpoint_minutes", "float64",
            "checkpoint_s / 60.0", "tight"),
        ("checkpoint_bars_since_signal_1m", "int",
            "checkpoint_s // 60 — number of complete 1m bars between "
            "signal and this checkpoint.", "bit_exact"),
        ("checkpoint_bars_since_signal_30s", "int",
            "checkpoint_s // 30", "bit_exact"),
        ("time_since_last_1m_bar_close_s", "int",
            "Seconds since the most recent 1m bar close at or before "
            "decision_time. 0 if decision_time is itself a 1m boundary.",
            "bit_exact"),
        ("time_until_next_1m_bar_close_s", "int",
            "Seconds until the next 1m bar close after decision_time.",
            "bit_exact"),
        ("time_until_next_5m_bar_close_s", "int",
            "Seconds until the next 5m bar close (minute_of_hour % 5 == 4) "
            "after decision_time.", "bit_exact"),
    ]
    for name, dtype, defn, tc in time_feats:
        out.append(mk(name, i, dtype, "derived", defn, CKP,
                       "checkpoint_derived", tol_cat=tc))
        i += 1

    # B. Checkpoint price position
    price_pos = [
        ("price_vs_signal_close_atr",
            "(current_1s_close - bar1.close) * direction / atr_at_signal"),
        ("price_vs_flip_bar_high_atr",
            "(current_1s_close - flip.high) * direction / atr_at_signal"),
        ("price_vs_flip_bar_low_atr",
            "(current_1s_close - flip.low) * direction / atr_at_signal"),
        ("price_vs_bar1_high_atr",
            "(current_1s_close - bar1.high) * direction / atr_at_signal"),
        ("price_vs_bar1_low_atr",
            "(current_1s_close - bar1.low) * direction / atr_at_signal"),
        ("price_vs_sma20_30s_atr",
            "(current_1s_close - sma20_30s.value) / atr_at_signal"),
        ("price_vs_sma20_5m_atr",
            "(current_1s_close - sma20_5m.value) / atr_at_signal"),
        ("price_vs_ema3_30s_atr",
            "(current_1s_close - ema3_30s.value) / atr_at_signal"),
        ("price_vs_ema3_5m_atr",
            "(current_1s_close - ema3_5m.value) / atr_at_signal"),
    ]
    for name, defn in price_pos:
        out.append(mk(name, i, "float64", "checkpoint", defn, CKP,
                       "checkpoint_time_dynamic", tol_cat="tight"))
        i += 1

    # C. 30s state
    state_30s = [
        ("regime_30s_aligned", "int",
            "1 if regime_30s.regime == signal_direction else 0", "bit_exact",
            "{0, 1}"),
        ("regime_30s_direction", "int",
            "regime_30s.regime ∈ {-1, 0, 1}", "bit_exact", "{-1, 0, 1}"),
        ("regime_30s_duration_bars", "int",
            "regime_30s.bars_in_regime at decision_time", "bit_exact", None),
        ("ema3_slope_30s_atr", "float64",
            "(ema3_30s.value - ema3_30s 5 bars ago) / atr_at_signal",
            "loose", None),
        ("ema_spread_30s_atr", "float64",
            "(emaH_3_30s - emaL_3_30s) / atr_at_signal", "loose", None),
        ("bar_range_30s_current_atr", "float64",
            "Range of in-progress 30s bar: (max_h - min_l of buffered 1s) "
            "/ atr_at_signal; 0.0 if buffer empty", "tight", 0.0),
        ("bar_body_30s_current_atr", "float64",
            "abs(last_1s_close - first_1s_open in buffer) / atr_at_signal; "
            "0.0 if buffer empty", "tight", 0.0),
        ("bar_body_pct_30s_current", "float64",
            "body / max(range, 1e-9); 0.5 default", "tight", 0.5),
        ("bar_wickiness_30s_current", "float64",
            "(range - body) / max(range, 1e-9); 0.0 default", "tight", 0.0),
    ]
    for name, dtype, defn, tc, default in state_30s:
        out.append(mk(name, i, dtype, "30s", defn, CKP,
                       "checkpoint_time_dynamic", tol_cat=tc,
                       default=default,
                       value_range="{0, 1}" if name == "regime_30s_aligned" else ("{-1, 0, 1}" if name == "regime_30s_direction" else None)))
        i += 1

    # D. 1m state at checkpoint
    state_1m = [
        ("regime_1m_direction", "int",
            "regime_1m.regime at decision_time. For events where regime "
            "is still active, equals signal_direction. ∈ {-1, 1}.",
            "bit_exact", "{-1, 1}"),
        ("regime_1m_duration_bars", "int",
            "regime_1m.bars_in_regime at decision_time", "bit_exact", None),
        ("price_vs_sma20_1m_atr_checkpoint", "float64",
            "(current_1s_close - sma20_1m.value) / atr_at_signal",
            "loose", None),
        ("price_vs_ema3_1m_atr_checkpoint", "float64",
            "(current_1s_close - ema3_1m.value) / atr_at_signal",
            "loose", None),
        ("ema_spread_1m_atr_checkpoint", "float64",
            "(emaH_3_1m - emaL_3_1m) / atr_at_signal", "loose", None),
    ]
    for name, dtype, defn, tc, vr in state_1m:
        out.append(mk(name, i, dtype, "1m", defn, CKP,
                       "checkpoint_time_dynamic", tol_cat=tc,
                       value_range=vr))
        i += 1

    # E. 5m state at checkpoint
    state_5m = [
        ("regime_5m_aligned", "int",
            "1 if regime_5m.regime == signal_direction else 0",
            "bit_exact", "{0, 1}"),
        ("regime_5m_direction", "int",
            "regime_5m.regime ∈ {-1, 0, 1}", "bit_exact", "{-1, 0, 1}"),
        ("regime_5m_duration_bars", "int",
            "regime_5m.bars_in_regime at decision_time", "bit_exact", None),
        ("ema3_slope_5m_atr", "float64",
            "(ema3_5m.value - ema3_5m 5 bars ago) / atr_at_signal; "
            "0.0 if insufficient history", "loose", 0.0),
        ("ema_spread_5m_atr", "float64",
            "(emaH_3_5m - emaL_3_5m) / atr_at_signal", "loose", None),
    ]
    for name, dtype, defn, tc, default in state_5m:
        vr = None
        if name == "regime_5m_aligned":
            vr = "{0, 1}"
        elif name == "regime_5m_direction":
            vr = "{-1, 0, 1}"
        out.append(mk(name, i, dtype, "5m", defn, CKP,
                       "checkpoint_time_dynamic", tol_cat=tc,
                       default=default, value_range=vr))
        i += 1

    # F. Micro/1s state
    micro = [
        ("micro_same_dir_count_12s", "int",
            "count of last 12 1s bars with close moving in trade direction",
            "bit_exact", "[0, 11]"),
        ("micro_opp_dir_count_12s", "int",
            "count of last 12 1s bars with close moving opposite",
            "bit_exact", "[0, 11]"),
        ("micro_aligned", "int",
            "1 if same_dir_count / total >= 7/12 (>=0.583) else 0",
            "bit_exact", "{0, 1}"),
        ("micro_opposing", "int",
            "1 if opp_dir_count / total >= 7/12 else 0",
            "bit_exact", "{0, 1}"),
        ("micro_net_return_atr", "float64",
            "(last_1s_close - first_1s_close in last 12) * direction / "
            "atr_at_signal", "tight", None),
        ("micro_range_compression", "float64",
            "mean range last 6 1s / mean range prior 6 1s; 1.0 if denom=0",
            "loose", None),
        ("micro_body_pct_avg", "float64",
            "mean of |c-o|/max(h-l,1e-9) across last 12 1s bars; 0.5 default",
            "loose", None),
    ]
    for name, dtype, defn, tc, vr in micro:
        default = None
        if name == "micro_range_compression":
            default = 1.0
        elif name == "micro_body_pct_avg":
            default = 0.5
        out.append(mk(name, i, dtype, "1s", defn, CKP,
                       "checkpoint_time_dynamic", tol_cat=tc,
                       default=default, value_range=vr))
        i += 1

    # ===== §6.5 Post-signal evolution =====
    # A. Progress / pullback
    prog = [
        ("max_progress_since_signal_atr", "float64",
            "max(0, max_j((max_favorable_price_j - bar1.close) × d)) / "
            "atr_at_signal; clipped >= 0", "tight", None),
        ("max_pullback_since_signal_atr", "float64",
            "max(0, max_j((bar1.close - min_favorable_price_j) × d)) / "
            "atr_at_signal; always >= 0", "tight", None),
        ("current_progress_atr", "float64",
            "(last_1s_close - bar1.close) × d / atr_at_signal; signed",
            "tight", None),
        ("current_pullback_from_local_peak_atr", "float64",
            "(max_progress_price - last_1s_close) × d / atr_at_signal; "
            "0 if no progress achieved (T_peak == signal_time); always >= 0",
            "tight", 0.0),
        ("progress_efficiency_since_signal", "float64",
            "max_progress / max(max_progress + max_pullback, 1e-9); "
            "range [0, 1]", "tight", None),
        ("mfe_mae_ratio_so_far", "float64",
            "max_progress / max(max_pullback, 1e-9)", "loose", None),
    ]
    for name, dtype, defn, tc, default in prog:
        out.append(mk(name, i, dtype, "1s", defn, CKP, ANCH_POST,
                       tol_cat=tc, default=default))
        i += 1

    # B. Continuation / stalling
    cont = [
        ("continuation_count_since_signal", "int",
            "count of 1m bars in (signal_time, decision_time] where "
            "bar.high > prev.high (long) or bar.low < prev.low (short)",
            "bit_exact", None),
        ("consecutive_continuation_bars", "int",
            "longest run of consecutive continuation bars ending at the "
            "most recent completed 1m bar <= decision_time",
            "bit_exact", None),
        ("bars_since_last_continuation", "int",
            "number of 1m bars since the most recent continuation, counted "
            "from the most recent completed 1m bar <= decision_time",
            "bit_exact", None),
        ("new_progress_in_last_30s_flag", "int",
            "1 if max_progress was achieved in [decision_time - 30s, "
            "decision_time] else 0", "bit_exact", "{0, 1}"),
        ("new_progress_in_last_60s_flag", "int",
            "1 if max_progress achieved in last 60s else 0",
            "bit_exact", "{0, 1}"),
        ("stall_60s_flag", "int",
            "1 if (decision_time - T_peak) > 60s else 0, where T_peak is "
            "the earliest 1s bar achieving max_progress. If max_progress = 0 "
            "then T_peak = signal_time.", "bit_exact", "{0, 1}"),
        ("stall_90s_flag", "int",
            "Same as stall_60s_flag with 90s threshold",
            "bit_exact", "{0, 1}"),
    ]
    for name, dtype, defn, tc, vr in cont:
        out.append(mk(name, i, dtype, "1m/1s", defn, CKP, ANCH_POST,
                       tol_cat=tc, value_range=vr))
        i += 1

    # C. Extension / exhaustion (kept 2)
    ext = [
        ("extension_from_signal_atr", "float64",
            "Alias for current_progress_atr — kept for semantic clarity "
            "with §6.5 text", "tight"),
        ("extension_from_last_pullback_atr", "float64",
            "(last_1s_close - min_favorable_price_since_T_peak) × d / "
            "atr_at_signal. 'How much has price risen from the most "
            "recent local low since the peak?' >= 0 by construction.",
            "tight"),
    ]
    for name, dtype, defn, tc in ext:
        out.append(mk(name, i, dtype, "1s", defn, CKP, ANCH_POST,
                       tol_cat=tc))
        i += 1

    # ===== §6.6 Session at checkpoint =====
    sess_ckp = [
        ("is_rth_checkpoint", "int",
            "1 if 510 <= ct_min(decision_time) < 900 else 0",
            "bit_exact", "{0, 1}"),
        ("hour_of_day_checkpoint", "int",
            "Hour of CT at decision_time", "bit_exact", "[0, 23]"),
        ("minute_of_hour_checkpoint", "int",
            "Minute of hour CT at decision_time", "bit_exact", "[0, 59]"),
        ("minutes_since_rth_open_checkpoint", "int",
            "ct_min(decision_time) - 510", "bit_exact", None),
        ("distance_from_session_high_atr_checkpoint", "float64",
            "(session_high - current_1s_close) / atr_at_signal at "
            "decision_time", "tight", None),
        ("distance_from_session_low_atr_checkpoint", "float64",
            "(current_1s_close - session_low) / atr_at_signal at "
            "decision_time", "tight", None),
        ("distance_from_session_mid_atr_checkpoint", "float64",
            "(current_1s_close - (session_high + session_low)/2) / "
            "atr_at_signal at decision_time", "tight", None),
    ]
    for name, dtype, defn, tc, vr in sess_ckp:
        out.append(mk(name, i, dtype, "derived", defn, CKP,
                       "checkpoint_derived", tol_cat=tc,
                       value_range=vr))
        i += 1

    return out


def _normalize_dtypes(features):
    """Tighten dtypes based on value_range.

    Rules:
      - {0, 1} → 'bool'
      - {-1, 1}, {-1, 0, 1} → 'int8'
      - [0, 11], [0, 23], [0, 59] → 'int8' (small-range counts)
      - other int → 'int' (generic)
    """
    for f in features:
        vr = f.get("value_range")
        if f["dtype"] != "int":
            continue
        if vr == "{0, 1}":
            f["dtype"] = "bool"
        elif vr in ("{-1, 1}", "{-1, 0, 1}", "[0, 11]",
                     "[0, 23]", "[0, 59]"):
            f["dtype"] = "int8"
        # else stay "int"


def _apply_role_taxonomy(features):
    """Classify each feature into one of:
      model_feature / metadata_only / compat_alias / constant_by_construction.

    Default from mk() is model_feature; only flag the exceptions here.
    """
    # --- compat_alias: duplicate numeric content with another feature ---
    aliases = [
        ("atr_14", "atr_at_signal",
            "Same value as atr_at_signal. Retained for legacy consumers."),
        ("flip_low_to_bar1_high_atr", "two_bar_range_atr",
            "Same formula as two_bar_range_atr."),
        ("pre_signal_chopiness_5", "pre_signal_trend_efficiency_5",
            "By definition = 1 − pre_signal_trend_efficiency_5."),
        ("pre_signal_chopiness_10", "pre_signal_trend_efficiency_10",
            "By definition = 1 − pre_signal_trend_efficiency_10."),
        ("checkpoint_minutes", "checkpoint_s",
            "= checkpoint_s / 60.0."),
        ("checkpoint_bars_since_signal_1m", "checkpoint_s",
            "= checkpoint_s // 60."),
        ("checkpoint_bars_since_signal_30s", "checkpoint_s",
            "= checkpoint_s // 30."),
        ("time_until_next_1m_bar_close_s", "time_since_last_1m_bar_close_s",
            "= 60 − time_since_last_1m_bar_close_s within a 1m cycle."),
        ("bar_wickiness_30s_current", "bar_body_pct_30s_current",
            "= 1 − bar_body_pct_30s_current."),
        ("extension_from_signal_atr", "current_progress_atr",
            "Same value as current_progress_atr; kept for §6.5 semantic "
            "clarity."),
    ]
    for name, source, note in aliases:
        _set_role(features, name, "compat_alias", alias_of=source,
                   notes_append=note)

    # --- constant_by_construction ---
    constants = [
        ("bar1_confirmed_hh_ll",
            "Always 1 for every emitted event (the v2 event definition "
            "requires bar+1 HH/LL confirmation as a precondition for "
            "emission)."),
    ]
    for name, note in constants:
        _set_role(features, name, "constant_by_construction",
                   notes_append=note)

    # --- metadata_only ---
    metadata = [
        ("session_warmup_flag",
            "Research-side filter flag (per §3.6). NOT a model input; "
            "session bars_since_open is the informative signal."),
    ]
    for name, note in metadata:
        _set_role(features, name, "metadata_only", notes_append=note)


def main():
    features = _enum_features()
    _normalize_dtypes(features)
    _apply_role_taxonomy(features)
    print(f"Generated {len(features)} features")

    # Breakdown
    by_snap = {}
    by_tc = {}
    by_role = {}
    for f in features:
        by_snap[f["snap_point"]] = by_snap.get(f["snap_point"], 0) + 1
        by_tc[f["parity_tolerance_category"]] = by_tc.get(
            f["parity_tolerance_category"], 0) + 1
        by_role[f["role"]] = by_role.get(f["role"], 0) + 1
    print(f"  By snap_point: {dict(by_snap)}")
    print(f"  By tolerance: {dict(by_tc)}")
    print(f"  By role:      {dict(by_role)}")

    # Name uniqueness check
    names = [f["name"] for f in features]
    if len(names) != len(set(names)):
        from collections import Counter
        dupes = [n for n, c in Counter(names).items() if c > 1]
        raise SystemExit(f"Duplicate feature names: {dupes}")

    # Index continuity
    for idx, f in enumerate(features):
        assert f["index"] == idx, f"Index mismatch at {idx}: {f['name']}"

    # Role validity
    for f in features:
        assert f["role"] in ROLE_VALUES, f"Bad role at {f['name']}"

    # Alias references exist
    for f in features:
        if "alias_of" in f:
            if f["alias_of"] not in names:
                raise SystemExit(
                    f"Alias target '{f['alias_of']}' of {f['name']} "
                    f"not found in contract")

    # Count model-usable features (model_feature only; excludes
    # metadata_only, compat_alias, constant_by_construction)
    n_model = sum(1 for f in features if f["role"] == "model_feature")

    contract = {
        "contract_version": CONTRACT_VERSION,
        "description": CONTRACT_DESCRIPTION,
        "collector_version": "v2",
        "spec_file": "collector_v2_spec.md",
        "feature_count_total": len(features),
        "feature_count_model_usable": n_model,
        "role_taxonomy": ROLE_VALUES,
        "null_policy_docs": NULL_POLICY_DOCS,
        "tolerance_categories": TOL,
        "snap_call_order_anchors": SNAP_ANCHORS,
        "decision_time_definitions": {
            "signal_time": "bar+1 close timestamp (ts_event of bar+1 + 60e9 ns)",
            "decision_time": "signal_time + decision_checkpoint_s × 1e9 ns (always 30s-aligned)",
            "fill_time": "decision_time + 30e9 ns",
            "execution_price": "open of the 30s bar covering [fill_time, fill_time + 30s)",
        },
        "rth_definition": "is_rth = 1 if 510 <= ct_min < 900 (8:30-15:00 America/Chicago)",
        "venue_assumptions": {
            "instrument": "NQ continuous futures",
            "multiplier": 20,
            "commission_per_round_trip_usd": 5.0,
            "tick_size": 0.25,
        },
        "runtime_execution_assumption": (
            "Decide at checkpoint-bar close, fill at open of 30s bar "
            "starting at fill_time. Labels ONLY valid for strategies "
            "matching this execution model (see §7.1)."
        ),
        "ml_usage_guidance": (
            "Use ONLY features where role == 'model_feature' as ML "
            "model inputs. Features with role 'compat_alias' duplicate "
            "information already present in their alias_of source. "
            "'constant_by_construction' features have zero variance "
            "within the v2 event family. 'metadata_only' features are "
            "for research filtering and stratification, never direct "
            "model input. This partition is enforced at the contract "
            "level; downstream ML training code should reject or warn "
            "on accidental inclusion of non-model-feature columns."
        ),
        "features": features,
        "deferred_features_note": (
            "See §15.10: pre_signal_expansion_after_compression_flag, "
            "failed_continuation_count, compression_after_extension_flag, "
            "reversal_pressure_flag, momentum_decay_flag are deferred to "
            "a future contract version."
        ),
    }

    out_path = Path(OUT_PATH)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(contract, f, indent=2)
    print(f"\nSaved: {out_path}")
    print(f"Size: {out_path.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
