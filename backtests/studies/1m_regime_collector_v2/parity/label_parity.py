"""Gate 4 — label-origin parity (MFE/MAE grid + bracket outcomes).

For each fillable sampled checkpoint, re-derive the forward path labels
INDEPENDENTLY from raw 1s bars, using the collector-emitted
`fill_time_actual` and `fill_price` as the label origin. This proves the
collector's tracker math is faithful to §7.1 / §7.2 on the same input.

MFE/MAE rule (§7.1):
  - mfe_Ws_atr = max over 1s bars with fat ≤ ts_event ≤ fat+W of
                   max(0, (high - fp)/atr × d_adj) where d_adj is +1
                   for long, or equivalently max(0, (fp - low)/atr) for
                   short
  - mae_Ws_atr = analogous
  - Windows censored when event terminated before window fully closed

Bracket rule (§7.2):
  - First 1s bar where peak MFE ≥ pt_R × atr → PT hit (outcome=1)
  - First 1s bar where peak MAE ≥ sl_R × atr → SL hit (outcome=0)
  - Same-bar-both tie → "more-decisive crossing" (optimistic toward PT)

Tracker updates capped at max_lookahead_s (=max_checkpoint_s) to match
collector.
"""

from __future__ import annotations
import numpy as np
import pandas as pd

FWD_WINDOWS_S = [30, 60, 120, 180, 300, 600]
BRACKETS = [
    (1.0, 1.0, "pt100_before_sl100"),
    (1.5, 1.0, "pt150_before_sl100"),
    (2.0, 1.0, "pt200_before_sl100"),
    (3.0, 1.5, "pt300_before_sl150"),
]
MAX_LOOKAHEAD_S = 1800
EPS = 1e-9

MFE_TOL = 1e-9    # ATR-normalized, generous for float arithmetic
MAE_TOL = 1e-9
BRACKET_TIME_TOL_S = 0.0   # integer seconds from 1s bars; exact match
BRACKET_PRICE_TOL = 1e-9


def rederive_labels_for_row(
    fill_time_actual: int,
    fill_price: float,
    direction: int,
    atr: float,
    regime_exit_time: int,
    bars_1s: pd.DataFrame,
) -> dict:
    """Re-derive MFE/MAE grid + bracket outcomes from raw 1s bars.

    Exactly mirrors ForwardPathTracker semantics: includes the fill bar
    (ts_event == fill_time_actual), stops updates past the event's
    termination, respects the max-lookahead cap.
    """
    d = direction
    fp = fill_price
    atr_safe = max(atr, EPS)

    # Filter bars: fat ≤ ts_event ≤ min(regime_exit_time, fat+lookahead)
    lookahead_end_ns = (fill_time_actual
        + MAX_LOOKAHEAD_S * 1_000_000_000)
    hard_end_ns = min(lookahead_end_ns, regime_exit_time)
    # Note: collector processes bars with ts_event < hard_end (regime
    # exit fires on the 1m bar's ts_init which equals regime_exit_time,
    # and 1s bars at ts_event >= regime_exit_time process after the
    # termination — so exclusive upper bound).
    mask = ((bars_1s["ts_event"] >= fill_time_actual)
             & (bars_1s["ts_event"] < hard_end_ns))
    bars = bars_1s[mask].sort_values("ts_event").reset_index(drop=True)

    # Initialize state mirroring ForwardPathTracker
    running_peak_mfe = 0.0
    running_peak_mae = 0.0
    peak_mfe_by_window = {w: 0.0 for w in FWD_WINDOWS_S}
    peak_mae_by_window = {w: 0.0 for w in FWD_WINDOWS_S}
    window_observed = {w: False for w in FWD_WINDOWS_S}
    bracket_outcomes: dict[str, int | None] = {
        name: None for _, _, name in BRACKETS}
    bracket_resolution_time_s: dict[str, float | None] = {
        name: None for _, _, name in BRACKETS}
    bracket_resolution_price: dict[str, float | None] = {
        name: None for _, _, name in BRACKETS}

    for _, bar in bars.iterrows():
        ts = int(bar["ts_event"])
        h = float(bar["high"])
        l = float(bar["low"])
        elapsed_s = (ts - fill_time_actual) / 1_000_000_000.0
        # max_lookahead_s already enforced via hard_end_ns, but assert
        if elapsed_s > MAX_LOOKAHEAD_S:
            break

        if d == 1:
            bar_mfe = max(0.0, (h - fp) / atr_safe)
            bar_mae = max(0.0, (fp - l) / atr_safe)
        else:
            bar_mfe = max(0.0, (fp - l) / atr_safe)
            bar_mae = max(0.0, (h - fp) / atr_safe)

        prev_running_mfe = running_peak_mfe
        prev_running_mae = running_peak_mae

        if bar_mfe > running_peak_mfe:
            running_peak_mfe = bar_mfe
        if bar_mae > running_peak_mae:
            running_peak_mae = bar_mae

        for w in FWD_WINDOWS_S:
            if elapsed_s <= w:
                peak_mfe_by_window[w] = running_peak_mfe
                peak_mae_by_window[w] = running_peak_mae
                window_observed[w] = True
            # Note: window_observed fires on ANY tick with elapsed ≤ w;
            # full-window observation means elapsed reached w. We'll
            # compute censoring from event termination instead (below).

        # Bracket resolution
        for pt_R, sl_R, name in BRACKETS:
            if bracket_outcomes[name] is not None:
                continue
            pt_now = (running_peak_mfe >= pt_R
                       and prev_running_mfe < pt_R)
            sl_now = (running_peak_mae >= sl_R
                       and prev_running_mae < sl_R)
            if not (pt_now or sl_now):
                continue
            if pt_now and sl_now:
                pt_factor = bar_mfe / pt_R
                sl_factor = bar_mae / sl_R
                outcome = 1 if pt_factor > sl_factor else 0
            elif pt_now:
                outcome = 1
            else:
                outcome = 0
            bracket_outcomes[name] = outcome
            bracket_resolution_time_s[name] = elapsed_s
            if outcome == 1:
                level = fp + d * pt_R * atr_safe
            else:
                level = fp - d * sl_R * atr_safe
            bracket_resolution_price[name] = max(l, min(h, level))

    # Censoring: per §7.0 — window censored if event ended before window
    # fully elapsed. elapsed_terminal = (regime_exit - fat)/1e9
    elapsed_terminal_s = (regime_exit_time - fill_time_actual) / 1e9
    window_censored = {
        w: (elapsed_terminal_s < w) for w in FWD_WINDOWS_S}

    return {
        "mfe_by_w": peak_mfe_by_window,
        "mae_by_w": peak_mae_by_window,
        "window_censored": window_censored,
        "bracket_outcomes": bracket_outcomes,
        "bracket_time_s": bracket_resolution_time_s,
        "bracket_price": bracket_resolution_price,
    }


def run_label_parity(
    sample: pd.DataFrame,
    bars_1s: pd.DataFrame,
) -> pd.DataFrame:
    """Re-derive MFE/MAE + brackets; return per-(event, T) comparison df."""
    bars_sorted = bars_1s.sort_values("ts_event").reset_index(drop=True)
    bars_ts = bars_sorted["ts_event"].values

    results = []
    for _, row in sample.iterrows():
        if not bool(row["fillable_at_T"]):
            continue  # skip unfillable (labels are None by design)
        if pd.isna(row["fill_time_actual"]):
            continue

        fat = int(row["fill_time_actual"])
        fp = float(row["fill_price"])
        d = int(row["signal_direction"])
        atr = float(row["atr_at_signal"])
        ret = int(row["regime_exit_time"])

        # Slice bars: [fat, min(regime_exit, fat+1800))
        end_ns = min(ret, fat + MAX_LOOKAHEAD_S * 1_000_000_000)
        lo = np.searchsorted(bars_ts, fat, side="left")
        hi = np.searchsorted(bars_ts, end_ns, side="left")
        bars = bars_sorted.iloc[lo:hi]

        derived = rederive_labels_for_row(
            fill_time_actual=fat,
            fill_price=fp,
            direction=d,
            atr=atr,
            regime_exit_time=ret,
            bars_1s=bars,
        )

        rec: dict = {
            "event_id": int(row["event_id"]),
            "checkpoint_s": int(row["checkpoint_s"]),
            "is_rth": bool(row.get("is_rth_checkpoint", False)),
        }

        # MFE/MAE compare
        mfe_mismatch = 0
        mae_mismatch = 0
        max_mfe_delta = 0.0
        max_mae_delta = 0.0
        for w in FWD_WINDOWS_S:
            col_mfe = float(row[f"mfe_{w}s_atr"])
            col_mae = float(row[f"mae_{w}s_atr"])
            drv_mfe = derived["mfe_by_w"][w]
            drv_mae = derived["mae_by_w"][w]
            d_mfe = abs(col_mfe - drv_mfe)
            d_mae = abs(col_mae - drv_mae)
            if d_mfe > MFE_TOL:
                mfe_mismatch += 1
            if d_mae > MAE_TOL:
                mae_mismatch += 1
            max_mfe_delta = max(max_mfe_delta, d_mfe)
            max_mae_delta = max(max_mae_delta, d_mae)
        rec["mfe_mismatch_count"] = mfe_mismatch
        rec["mae_mismatch_count"] = mae_mismatch
        rec["max_mfe_delta"] = max_mfe_delta
        rec["max_mae_delta"] = max_mae_delta

        # Bracket compare
        br_mismatch = 0
        for pt_R, sl_R, name in BRACKETS:
            col_out = row[name]
            drv_out = derived["bracket_outcomes"][name]
            col_nan = pd.isna(col_out)
            drv_nan = drv_out is None
            if col_nan != drv_nan:
                br_mismatch += 1
            elif not col_nan:
                if int(col_out) != int(drv_out):
                    br_mismatch += 1
        rec["bracket_mismatch_count"] = br_mismatch

        rec["all_match"] = (mfe_mismatch == 0
                             and mae_mismatch == 0
                             and br_mismatch == 0)
        results.append(rec)
    return pd.DataFrame(results)
