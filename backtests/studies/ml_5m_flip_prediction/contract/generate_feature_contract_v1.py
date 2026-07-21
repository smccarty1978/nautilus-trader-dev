"""Generate feature_contract_v1.json from feature_cols_2026.json.

For each of the 100 features, document:
  - name, index, dtype
  - source_timeframe (1m / 30s / 5m / 1s / derived)
  - definition (formula or source line in collector)
  - snap_point (signal_time / decision_time / static)
  - snap_call_order (where in the call stack it's read; matters for
                      features whose value depends on call ordering)
  - null_policy (disallow / nullable_explicit / default_filled)
  - default_value_if_applicable
  - is_required
  - parity_tolerance
  - parity_tolerance_category (bit_exact / tight / loose / looser)

Categories used for parity tolerance defaults:
  - bit_exact (1e-12): integer-valued (regime states, counts, flags)
  - tight (1e-9): single-step arithmetic (price ratios, ATR-norms)
  - loose (1e-6): EMA / SMA / accumulated stats over many bars
  - looser (1e-4): compound ratios of accumulated stats
"""

import sys
import os
import json
from pathlib import Path

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

FEATURE_COLS_PATH = "models/ml_5m_flip/feature_cols_2026.json"
OUT_PATH = "models/ml_5m_flip/feature_contract_v1.json"

CONTRACT_VERSION = "v1"
CONTRACT_DESCRIPTION = (
    "Feature contract v1 for the 5m-flip-prediction inverse-filter model. "
    "Freezes the 100-feature set as currently consumed by model_2026.txt. "
    "Snap call order matches the v3 collector "
    "(studies/1m_delayed_checkpoint_context/collector.py). Any change to "
    "names, definitions, null policy, default values, or call ordering "
    "requires a new contract version (v2)."
)

# Tolerance defaults per category
TOL = {
    "bit_exact": 1e-12,
    "tight": 1e-9,
    "loose": 1e-6,
    "looser": 1e-4,
}

# ------------------------------------------------------------------
# Snap call order anchors (referenced by individual features)
# ------------------------------------------------------------------
SNAP_POINTS = {
    "signal_time_check_confirmation": (
        "Read inside collector._check_confirmation(rec) which is called "
        "from collector._on_1m when bar+1 close fires. At this point: "
        "(1) atr_14.update_raw has run for bar+1, "
        "(2) regime_1m.update has run for bar+1 (regime is now sticky "
        "with the flip direction since bar+1 didn't reverse it), "
        "(3) _update_5m has run for bar+1 (5m may have updated if "
        "bar+1 minute_of_hour % 5 == 4), "
        "(4) _update_active_trades_on_1m has NOT yet run for bar+1. "
        "All sma20/sma50/ema indicators include bar+1 in their state."
    ),
    "signal_time_root_features": (
        "Same call point as signal_time_check_confirmation. The root "
        "features dict is built by collector._snap_root_features(...) "
        "which is invoked from inside _check_confirmation BEFORE the "
        "trade is appended to _active_trades."
    ),
    "decision_time_snap_checkpoint": (
        "Read inside collector._snap_checkpoint(ts_data, T, current_ts) "
        "called from collector._emit_30s_bar at NT processing time "
        "ts_init=signal_time+1s (the 1s bar with ts_event=signal_time). "
        "By this point bar+1's _on_1m has already run (1m bar's "
        "ts_init=signal_time, 1s bar's ts_init=signal_time+1s). "
        "Regime states reflect bar+1's update. Critical: this snap may "
        "fail to fire if there is no 1s bar at ts_event=signal_time "
        "(data gap), in which case checkpoint fields stay at default."
    ),
    "static_per_event": (
        "Set once when the trade is registered and never updated. "
        "Examples: signal_direction, decision_checkpoint_s."
    ),
}


# ------------------------------------------------------------------
# Per-feature contract entries
# ------------------------------------------------------------------

def make_entry(name, index, dtype, source_tf, definition, snap_point,
                snap_anchor, null_policy="disallow", default=None,
                is_required=True, tol_category="tight",
                value_range=None, notes=""):
    return {
        "name": name,
        "index": index,
        "dtype": dtype,
        "source_timeframe": source_tf,
        "definition": definition,
        "snap_point": snap_point,
        "snap_call_order_anchor": snap_anchor,
        "null_policy": null_policy,
        "default_value_if_applicable": default,
        "is_required": is_required,
        "parity_tolerance_category": tol_category,
        "parity_tolerance": TOL[tol_category],
        "value_range": value_range,
        "notes": notes,
    }


def build_contract():
    """Return list of 100 contract entries in model order."""
    e = []  # entries
    # Helper aliases
    sig = "signal_time_check_confirmation"
    sig_root = "signal_time_root_features"
    dec = "decision_time_snap_checkpoint"
    static = "static_per_event"

    # Index 0
    e.append(make_entry(
        "decision_checkpoint_s", 0, "int", "derived",
        "T_d in seconds (always 0 for current production)",
        "static", static,
        null_policy="disallow", tol_category="bit_exact",
        value_range="0",
        notes="Always 0 in current model; reserved for future delayed entries"))

    # Indices 1-2: ATR
    e.append(make_entry(
        "atr_14", 1, "float64", "1m",
        "AverageTrueRange(period=14) value at signal_time, AFTER atr_14."
        "update_raw(bar+1.h, bar+1.l, bar+1.c). This is NT's built-in "
        "indicator (Wilder smoothed). Same as atr_at_signal at signal_time.",
        "signal_time", sig_root,
        tol_category="loose",
        notes="Wilder smoothed ATR has FP accumulation drift over time"))
    e.append(make_entry(
        "atr_at_signal", 2, "float64", "1m",
        "Same as atr_14 — duplicate column maintained for legacy reasons.",
        "signal_time", sig_root, tol_category="loose",
        notes="Identical to atr_14"))

    # Indices 3-15: Flip bar anatomy (signal_time root features)
    e += [
        make_entry("flip_range_atr", 3, "float64", "1m",
                    "(flip_bar.h - flip_bar.l) / atr_14",
                    "signal_time", sig_root, tol_category="tight"),
        make_entry("flip_body_atr", 4, "float64", "1m",
                    "abs(flip_bar.c - flip_bar.o) / atr_14",
                    "signal_time", sig_root, tol_category="tight"),
        make_entry("flip_body_pct", 5, "float64", "1m",
                    "body / range, 0 if range==0",
                    "signal_time", sig_root, tol_category="tight",
                    value_range="[0, 1]"),
        make_entry("flip_close_location", 6, "float64", "1m",
                    "(c-l)/(h-l), 0.5 if range==0",
                    "signal_time", sig_root, tol_category="tight",
                    default=0.5, value_range="[0, 1]"),
        make_entry("flip_upper_wick_pct", 7, "float64", "1m",
                    "(h - max(o,c)) / range, 0 if range==0",
                    "signal_time", sig_root, tol_category="tight",
                    default=0.0, value_range="[0, 1]"),
        make_entry("flip_lower_wick_pct", 8, "float64", "1m",
                    "(min(o,c) - l) / range, 0 if range==0",
                    "signal_time", sig_root, tol_category="tight",
                    default=0.0, value_range="[0, 1]"),
        make_entry("flip_volume", 9, "float64", "1m",
                    "Total volume of flip bar",
                    "signal_time", sig_root, tol_category="bit_exact"),
        make_entry("flip_vol_vs_20avg", 10, "float64", "1m",
                    "flip_bar.v / mean of last 20 1m bar volumes (excluding "
                    "flip bar). Set in collector via _vol_vs_Navg(.., 20, 0).",
                    "signal_time", sig_root, tol_category="loose"),
        make_entry("flip_close_vs_prior_close_atr", 11, "float64", "1m",
                    "(flip_bar.c - prior_bar.c) * direction / atr_14. "
                    "Multiplied by signal_direction.",
                    "signal_time", sig_root, tol_category="tight"),
        make_entry("flip_high_vs_prior_high_atr", 12, "float64", "1m",
                    "(flip_bar.h - prior_bar.h) * direction / atr_14",
                    "signal_time", sig_root, tol_category="tight"),
        make_entry("flip_low_vs_prior_low_atr", 13, "float64", "1m",
                    "(flip_bar.l - prior_bar.l) * direction / atr_14",
                    "signal_time", sig_root, tol_category="tight"),
        make_entry("flip_bar_bullish_volume_pct", 14, "float64", "1m",
                    "Sum of up-candle 1s bar volumes inside the 1m / "
                    "(up + down volumes). Computed during _on_1s as "
                    "current_1m_up_vol / (up_vol + down_vol). Default 0.5.",
                    "signal_time", sig_root, tol_category="loose",
                    default=0.5, value_range="[0, 1]"),
        make_entry("flip_bar_vol_rank_20", 15, "float64", "1m",
                    "Rank of flip_bar.v among last 20 1m bar volumes "
                    "(0=lowest, 1=highest). Computed via _vol_rank_N.",
                    "signal_time", sig_root, tol_category="tight",
                    value_range="[0, 1]"),
    ]

    # Indices 16-29: Bar+1 anatomy
    e += [
        make_entry("bar1_range_atr", 16, "float64", "1m",
                    "(bar1.h - bar1.l) / atr_14",
                    "signal_time", sig_root, tol_category="tight"),
        make_entry("bar1_body_atr", 17, "float64", "1m",
                    "abs(bar1.c - bar1.o) / atr_14",
                    "signal_time", sig_root, tol_category="tight"),
        make_entry("bar1_body_pct", 18, "float64", "1m",
                    "bar1 body/range",
                    "signal_time", sig_root, tol_category="tight"),
        make_entry("bar1_close_location", 19, "float64", "1m",
                    "(bar1.c - bar1.l) / bar1.range",
                    "signal_time", sig_root, tol_category="tight",
                    default=0.5),
        make_entry("bar1_upper_wick_pct", 20, "float64", "1m",
                    "bar1 upper wick fraction of range",
                    "signal_time", sig_root, tol_category="tight",
                    default=0.0),
        make_entry("bar1_lower_wick_pct", 21, "float64", "1m",
                    "bar1 lower wick fraction of range",
                    "signal_time", sig_root, tol_category="tight",
                    default=0.0),
        make_entry("bar1_volume", 22, "float64", "1m",
                    "bar1 total volume",
                    "signal_time", sig_root, tol_category="bit_exact"),
        make_entry("bar1_vol_vs_flip_vol", 23, "float64", "1m",
                    "bar1.v / flip.v, 1.0 if flip.v == 0",
                    "signal_time", sig_root, tol_category="tight",
                    default=1.0),
        make_entry("bar1_vol_rank_20", 24, "float64", "1m",
                    "bar1 volume rank vs prior 20 1m bars",
                    "signal_time", sig_root, tol_category="tight",
                    value_range="[0, 1]"),
        make_entry("bar1_hh_amount_atr", 25, "float64", "1m",
                    "long: (bar1.h - flip.h)/atr; short: (flip.l - bar1.l)/atr",
                    "signal_time", sig_root, tol_category="tight"),
        make_entry("bar1_close_vs_flip_close_atr", 26, "float64", "1m",
                    "(bar1.c - flip.c) * direction / atr_14",
                    "signal_time", sig_root, tol_category="tight"),
        make_entry("bar1_close_above_flip_close", 27, "int", "1m",
                    "1 if (bar1.c - flip.c) * direction > 0 else 0",
                    "signal_time", sig_root, tol_category="bit_exact",
                    value_range="{0, 1}"),
        make_entry("bar1_close_above_50pct_range", 28, "int", "1m",
                    "Long: 1 if bar1_close_loc > 0.5; Short: 1 if loc < 0.5",
                    "signal_time", sig_root, tol_category="bit_exact",
                    value_range="{0, 1}"),
        make_entry("bar1_bullish_volume_pct", 29, "float64", "1m",
                    "bar1 up_vol / (up_vol + down_vol). Default 0.5.",
                    "signal_time", sig_root, tol_category="loose",
                    default=0.5),
    ]

    # Indices 30-35: Two-bar sequence
    e += [
        make_entry("two_bar_range_atr", 30, "float64", "1m",
                    "(max(flip.h, bar1.h) - min(flip.l, bar1.l)) / atr_14",
                    "signal_time", sig_root, tol_category="tight"),
        make_entry("two_bar_body_atr", 31, "float64", "1m",
                    "(bar1.c - flip.o) * direction / atr_14",
                    "signal_time", sig_root, tol_category="tight"),
        make_entry("two_bar_close_vs_open_pct", 32, "float64", "1m",
                    "(bar1.c - flip.o) / flip.o (relative pct move)",
                    "signal_time", sig_root, tol_category="tight"),
        make_entry("two_bar_volume_total", 33, "float64", "1m",
                    "flip.v + bar1.v",
                    "signal_time", sig_root, tol_category="bit_exact"),
        make_entry("two_bar_vol_vs_40avg", 34, "float64", "1m",
                    "(flip.v + bar1.v) / mean of last 40 1m bar volumes",
                    "signal_time", sig_root, tol_category="loose"),
        make_entry("flip_low_to_bar1_high_atr", 35, "float64", "1m",
                    "(max(flip.h, bar1.h) - min(flip.l, bar1.l)) / atr_14 "
                    "(intentionally same as two_bar_range_atr — legacy)",
                    "signal_time", sig_root, tol_category="tight",
                    notes="Identical to two_bar_range_atr by collector code"),
    ]

    # Indices 36-43: Pre-flip / 1m regime context
    e += [
        make_entry("prior_regime_duration_bars", 36, "int", "1m",
                    "Number of 1m bars the prior regime was active before "
                    "this flip (from collector flip_pending state)",
                    "signal_time", sig_root, tol_category="bit_exact"),
        make_entry("consecutive_trend_bars_pre_flip", 37, "int", "1m",
                    "Consecutive same-direction close-to-close moves in the "
                    "5 1m bars prior to flip. Computed in _snap_root_features.",
                    "signal_time", sig_root, tol_category="bit_exact"),
        make_entry("pre_flip_3bar_body_direction", 38, "int", "1m",
                    "Sign of cumulative body of 3 bars before flip "
                    "(+1, 0, -1)",
                    "signal_time", sig_root, tol_category="bit_exact",
                    value_range="{-1, 0, 1}"),
        make_entry("pre_flip_3bar_range_atr", 39, "float64", "1m",
                    "Sum of last 3 pre-flip 1m bar ranges / atr_14",
                    "signal_time", sig_root, tol_category="tight"),
        make_entry("pre_flip_5bar_range_atr", 40, "float64", "1m",
                    "Sum of last 5 pre-flip 1m bar ranges / atr_14",
                    "signal_time", sig_root, tol_category="tight"),
        make_entry("pre_flip_volume_trend", 41, "float64", "1m",
                    "Slope-like measure: (last_3_avg_vol - prior_3_avg_vol) "
                    "/ prior_3_avg_vol over pre-flip bars",
                    "signal_time", sig_root, tol_category="loose",
                    default=0.0),
        make_entry("regime_flips_last_30min", 42, "int", "1m",
                    "Count of regime flips in the 30 1m bars prior to "
                    "signal_time (collector counts flip_history within window)",
                    "signal_time", sig_root, tol_category="bit_exact"),
        make_entry("regime_flips_last_60min", 43, "int", "1m",
                    "Count of regime flips in the 60 1m bars prior",
                    "signal_time", sig_root, tol_category="bit_exact"),
    ]

    # Indices 44-51: 1m MA context (signal time)
    e += [
        make_entry("price_vs_sma20_atr", 44, "float64", "1m",
                    "(flip.c - sma20_1m.value) / atr_14, where sma20_1m "
                    "INCLUDES flip bar (updated before _check_confirmation)",
                    "signal_time", sig_root, tol_category="loose"),
        make_entry("price_vs_sma50_atr", 45, "float64", "1m",
                    "(flip.c - sma50_1m.value) / atr_14",
                    "signal_time", sig_root, tol_category="loose"),
        make_entry("sma20_slope_atr", 46, "float64", "1m",
                    "(sma20_1m.value - sma20 5 bars ago) / atr_14. "
                    "Uses _prev_sma20 deque maxlen=6 to look back.",
                    "signal_time", sig_root, tol_category="loose"),
        make_entry("sma20_vs_sma50_atr", 47, "float64", "1m",
                    "(sma20.value - sma50.value) / atr_14",
                    "signal_time", sig_root, tol_category="loose"),
        make_entry("sma50_slope_atr", 48, "float64", "1m",
                    "(sma50.value - sma50 10 bars ago) / atr_14. "
                    "Uses _prev_sma50 deque maxlen=11.",
                    "signal_time", sig_root, tol_category="loose"),
        make_entry("ema3_slope_atr", 49, "float64", "1m",
                    "(ema3.value - ema3 5 bars ago) / atr_14. "
                    "Uses _prev_ema3 deque maxlen=6.",
                    "signal_time", sig_root, tol_category="loose"),
        make_entry("ema_spread_atr", 50, "float64", "1m",
                    "(emaH3 - emaL3) / atr_14 from regime_1m state",
                    "signal_time", sig_root, tol_category="loose"),
        make_entry("ema3_ema9_spread_atr", 51, "float64", "1m",
                    "(ema3.value - ema9.value) / atr_14",
                    "signal_time", sig_root, tol_category="loose"),
    ]

    # Indices 52-57: 1m volume analysis
    e += [
        make_entry("vol_1m_20avg", 52, "float64", "1m",
                    "Mean of last 20 1m bar volumes (rolling)",
                    "signal_time", sig_root, tol_category="loose"),
        make_entry("vol_ratio_up_down_10bar", 53, "float64", "1m",
                    "Sum up_vol / sum down_vol over last 10 1m bars",
                    "signal_time", sig_root, tol_category="loose",
                    default=1.0),
        make_entry("vol_ratio_up_down_20bar", 54, "float64", "1m",
                    "Same over last 20 1m bars",
                    "signal_time", sig_root, tol_category="loose",
                    default=1.0),
        make_entry("vol_acceleration_5bar", 55, "float64", "1m",
                    "(last 5 bars avg vol - prior 5 bars avg vol) / "
                    "prior 5 bars avg vol",
                    "signal_time", sig_root, tol_category="loose",
                    default=0.0),
        make_entry("high_vol_bar_count_10", 56, "int", "1m",
                    "Count of bars in last 10 with vol > 1.5 × vol_1m_20avg",
                    "signal_time", sig_root, tol_category="bit_exact"),
        make_entry("cumulative_volume_bias_10", 57, "float64", "1m",
                    "Sum of (up_vol - down_vol) over last 10 1m bars / "
                    "sum total_vol",
                    "signal_time", sig_root, tol_category="loose"),
    ]

    # Indices 58-62: Session/timing at signal
    e += [
        make_entry("hour_of_day", 58, "int", "derived",
                    "Hour of CT timezone at signal_time",
                    "signal_time", sig_root, tol_category="bit_exact",
                    value_range="[0, 23]"),
        make_entry("minute_of_hour", 59, "int", "derived",
                    "Minute of hour at signal_time CT",
                    "signal_time", sig_root, tol_category="bit_exact",
                    value_range="[0, 59]"),
        make_entry("minutes_since_rth_open", 60, "int", "derived",
                    "ct_min - 510 (510 = 8:30 CT). Negative pre-RTH.",
                    "signal_time", sig_root, tol_category="bit_exact"),
        make_entry("distance_from_session_high_atr", 61, "float64", "derived",
                    "(session_high - flip.c) / atr_14. Session resets at "
                    "17:00 CT.",
                    "signal_time", sig_root, tol_category="tight"),
        make_entry("distance_from_session_low_atr", 62, "float64", "derived",
                    "(flip.c - session_low) / atr_14",
                    "signal_time", sig_root, tol_category="tight"),
    ]

    # Indices 63-65: State at signal + direction
    e += [
        make_entry("regime_30s_aligned_t0", 63, "int", "30s",
                    "1 if regime_30s.regime == signal_direction at signal_time, "
                    "else 0. Read in _check_confirmation (collector). "
                    "Reflects 30s state INCLUDING any 30s bars closed before "
                    "signal_time.",
                    "signal_time", sig_root, tol_category="bit_exact",
                    value_range="{0, 1}"),
        make_entry("regime_5m_aligned_t0", 64, "int", "5m",
                    "1 if regime_5m.regime == signal_direction at signal_time, "
                    "else 0. Read in _check_confirmation AFTER bar+1's "
                    "_update_5m may have updated regime_5m.",
                    "signal_time", sig_root, tol_category="bit_exact",
                    value_range="{0, 1}",
                    notes="Always 0 in current production (we exclude "
                          "aligned-at-signal trades)"),
        make_entry("signal_direction", 65, "int", "derived",
                    "+1 (long) or -1 (short)",
                    "static", static, tol_category="bit_exact",
                    value_range="{-1, 1}"),
    ]

    # Indices 66-99: Decision-time (_T) features
    e += [
        make_entry("atr_14_at_T", 66, "float64", "1m",
                    "atr_14.value at decision_time. For T=0, same as atr_at_signal.",
                    "decision_time", dec, tol_category="loose"),
        make_entry("regime_30s_T", 67, "int", "30s",
                    "regime_30s.regime at decision_time (-1, 0, 1)",
                    "decision_time", dec, tol_category="bit_exact",
                    value_range="{-1, 0, 1}"),
        make_entry("regime_30s_aligned_T", 68, "int", "30s",
                    "1 if regime_30s_T == signal_direction else 0",
                    "decision_time", dec, tol_category="bit_exact",
                    value_range="{0, 1}"),
        make_entry("regime_30s_duration_bars_T", 69, "int", "30s",
                    "regime_30s.bars_in_regime at decision_time",
                    "decision_time", dec, tol_category="bit_exact"),
        make_entry("ema3_slope_30s_atr_T", 70, "float64", "30s",
                    "Always 0.0 in current collector (placeholder, not "
                    "tracking 30s ema3 slope history)",
                    "decision_time", dec, tol_category="bit_exact",
                    value_range="0.0",
                    notes="Hardcoded 0.0 in collector — kept for parity"),
        make_entry("ema_spread_30s_atr_T", 71, "float64", "30s",
                    "(emaH_3.value - emaL_3.value) / atr_at_signal "
                    "from regime_30s state at decision_time",
                    "decision_time", dec, tol_category="loose"),
        make_entry("price_vs_sma20_30s_atr_T", 72, "float64", "30s",
                    "(current 1s close - sma20_30s.value) / atr_at_signal",
                    "decision_time", dec, tol_category="loose"),
        make_entry("bar_range_30s_current_atr_T", 73, "float64", "30s",
                    "Range of CURRENT in-progress 30s bar (max(h)-min(l) "
                    "of buffered 1s bars in _1s_for_30s) / atr_at_signal. "
                    "0 if buffer empty.",
                    "decision_time", dec, tol_category="tight",
                    default=0.0),
        make_entry("regime_5m_T", 74, "int", "5m",
                    "regime_5m.regime at decision_time (-1, 0, 1)",
                    "decision_time", dec, tol_category="bit_exact",
                    value_range="{-1, 0, 1}"),
        make_entry("regime_5m_duration_bars_T", 75, "int", "5m",
                    "regime_5m.bars_in_regime at decision_time",
                    "decision_time", dec, tol_category="bit_exact"),
        make_entry("ema3_slope_5m_atr_T", 76, "float64", "5m",
                    "Always 0.0 (placeholder)",
                    "decision_time", dec, tol_category="bit_exact",
                    value_range="0.0",
                    notes="Hardcoded 0.0 in collector"),
        make_entry("ema_spread_5m_atr_T", 77, "float64", "5m",
                    "(emaH_3.value - emaL_3.value) / atr_at_signal from "
                    "regime_5m state",
                    "decision_time", dec, tol_category="loose"),
        make_entry("price_vs_sma20_5m_atr_T", 78, "float64", "5m",
                    "(current 1s close - sma20_5m.value) / atr_at_signal",
                    "decision_time", dec, tol_category="loose"),
        make_entry("regime_5m_changed_during_delay_by_T", 79, "int", "5m",
                    "1 if regime_5m_T != regime_5m_at_signal else 0. "
                    "For T=0, this is 0 by construction.",
                    "decision_time", dec, tol_category="bit_exact",
                    value_range="{0, 1}"),
        make_entry("regime_1m_T", 80, "int", "1m",
                    "regime_1m.regime at decision_time. For T=0, equals "
                    "signal_direction (regime is sticky after the flip).",
                    "decision_time", dec, tol_category="bit_exact",
                    value_range="{-1, 1}"),

        # Micro features (last 12 1s bars from _recent_1s)
        make_entry("micro_same_dir_count_12s_T", 81, "int", "1s",
                    "Count of 1s bars in last 12 with close moving in trade "
                    "direction (close > prev_close for long)",
                    "decision_time", dec, tol_category="bit_exact",
                    value_range="[0, 11]"),
        make_entry("micro_opp_dir_count_12s_T", 82, "int", "1s",
                    "Count of opposite-direction 1s bars in last 12",
                    "decision_time", dec, tol_category="bit_exact",
                    value_range="[0, 11]"),
        make_entry("micro_aligned_T", 83, "int", "1s",
                    "1 if same_dir_count / total_count >= 0.583 (7/12) else 0",
                    "decision_time", dec, tol_category="bit_exact",
                    value_range="{0, 1}"),
        make_entry("micro_opposing_T", 84, "int", "1s",
                    "1 if opp_dir_count / total_count >= 0.583 else 0",
                    "decision_time", dec, tol_category="bit_exact",
                    value_range="{0, 1}"),
        make_entry("micro_net_return_atr_T", 85, "float64", "1s",
                    "(last_1s_close - first_1s_close in last 12) * direction "
                    "/ atr_at_signal",
                    "decision_time", dec, tol_category="tight"),
        make_entry("micro_range_compression_T", 86, "float64", "1s",
                    "Mean range of last 6 1s bars / mean range of prior 6. "
                    "1.0 if either is 0.",
                    "decision_time", dec, tol_category="loose",
                    default=1.0),
        make_entry("micro_body_pct_avg_T", 87, "float64", "1s",
                    "Mean of |c-o|/(h-l) across last 12 1s bars (skipping "
                    "bars with range==0). 0.5 if no valid bars.",
                    "decision_time", dec, tol_category="loose",
                    default=0.5),

        # Continuation (always 0 at T=0)
        make_entry("continuation_count_since_signal_T", 88, "int", "1m",
                    "Count of bars after signal where price moved in trade "
                    "direction. Always 0 at T=0.",
                    "decision_time", dec, tol_category="bit_exact",
                    default=0,
                    notes="Always 0 at T=0; informative at T>0"),
        make_entry("consecutive_continuation_bars_T", 89, "int", "1m",
                    "Consecutive continuation bars. Always 0 at T=0.",
                    "decision_time", dec, tol_category="bit_exact",
                    default=0),
        make_entry("bars_since_last_continuation_T", 90, "int", "1m",
                    "Bars since last continuation. Always 0 at T=0.",
                    "decision_time", dec, tol_category="bit_exact",
                    default=0),
        make_entry("checkpoint_bars_since_signal_1m_T", 91, "int", "1m",
                    "Number of 1m bars between signal_time and "
                    "decision_time. Always 0 at T=0.",
                    "decision_time", dec, tol_category="bit_exact",
                    default=0),

        # Session at decision (for T=0 same as signal)
        make_entry("is_rth_T", 92, "int", "derived",
                    "1 if 510 <= ct_min < 900 at decision_time else 0",
                    "decision_time", dec, tol_category="bit_exact",
                    value_range="{0, 1}"),
        make_entry("hour_of_day_T", 93, "int", "derived",
                    "Hour of CT at decision_time",
                    "decision_time", dec, tol_category="bit_exact",
                    value_range="[0, 23]"),
        make_entry("minute_of_hour_T", 94, "int", "derived",
                    "Minute of hour CT at decision_time",
                    "decision_time", dec, tol_category="bit_exact",
                    value_range="[0, 59]"),
        make_entry("minutes_since_rth_open_T", 95, "int", "derived",
                    "ct_min - 510 at decision_time",
                    "decision_time", dec, tol_category="bit_exact"),
        make_entry("distance_from_session_high_atr_T", 96, "float64", "derived",
                    "(session_high - current_1s_close) / atr_at_signal at "
                    "decision_time",
                    "decision_time", dec, tol_category="tight"),
        make_entry("distance_from_session_low_atr_T", 97, "float64", "derived",
                    "(current_1s_close - session_low) / atr_at_signal",
                    "decision_time", dec, tol_category="tight"),

        # Volume at decision
        make_entry("vol_total_30s_recent_T", 98, "float64", "1s",
                    "Sum of volumes of buffered 1s bars in current 30s "
                    "(_1s_for_30s). 0 if buffer empty.",
                    "decision_time", dec, tol_category="bit_exact",
                    default=0.0),
        make_entry("vol_vs_20avg_30s_T", 99, "float64", "30s",
                    "vol_total_30s_recent_T / mean of last 20 closed 30s "
                    "bar volumes. 1.0 if <20 bars buffered or avg==0.",
                    "decision_time", dec, tol_category="loose",
                    default=1.0),
    ]

    return e


def main():
    with open(FEATURE_COLS_PATH) as f:
        feature_cols = json.load(f)
    print(f"Model uses {len(feature_cols)} features")

    contract_features = build_contract()
    print(f"Contract has {len(contract_features)} entries")

    # Verify alignment
    assert len(contract_features) == len(feature_cols), (
        f"Length mismatch: contract={len(contract_features)}, "
        f"model={len(feature_cols)}")

    mismatches = []
    for i, (model_name, entry) in enumerate(zip(feature_cols,
                                                  contract_features)):
        if model_name != entry["name"]:
            mismatches.append(
                (i, model_name, entry["name"]))
    if mismatches:
        print("MISMATCHES (idx, model_name, contract_name):")
        for m in mismatches:
            print(f"  {m}")
        raise SystemExit(1)
    print("Feature names match model column order")

    # Build full contract document
    contract = {
        "contract_version": CONTRACT_VERSION,
        "description": CONTRACT_DESCRIPTION,
        "model_artifact": "models/ml_5m_flip/model_2026.txt",
        "feature_count": len(contract_features),
        "tolerance_categories": TOL,
        "snap_call_order_anchors": SNAP_POINTS,
        "decision_time_definitions": {
            "signal_time": "ts_event of bar+1 + 60_000_000_000 ns "
                            "(bar+1 close timestamp)",
            "decision_time": "signal_time + decision_checkpoint_s × 1e9 ns",
            "decision_fill_time": "decision_time + 30 × 1e9 ns",
            "decision_checkpoint_s": "T_d in seconds (production: always 0)",
        },
        "rth_definition": (
            "is_rth = 1 if 510 <= ct_min < 900 (8:30-15:00 America/Chicago)"),
        "venue_assumptions": {
            "instrument": "NQ continuous futures",
            "multiplier": 20,
            "commission_per_round_trip_usd": 5.0,
            "tick_size": 0.25,
        },
        "features": contract_features,
    }

    out_path = Path(OUT_PATH)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(contract, f, indent=2)
    print(f"\n  Saved: {out_path}")
    print(f"  Size: {out_path.stat().st_size:,} bytes")

    # Also output a summary table
    print(f"\nContract summary:")
    by_snap = {}
    by_tol = {}
    for entry in contract_features:
        sp = entry["snap_point"]
        by_snap[sp] = by_snap.get(sp, 0) + 1
        tc = entry["parity_tolerance_category"]
        by_tol[tc] = by_tol.get(tc, 0) + 1
    print(f"  By snap_point: {dict(by_snap)}")
    print(f"  By tolerance_category: {dict(by_tol)}")


if __name__ == "__main__":
    main()
