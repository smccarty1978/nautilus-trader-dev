"""Collect aligned path + W4 checkpoints for the CODEX 5.X established-fade trades.

Diagnostic only: no thresholds are optimized and no alternative policy is
simulated. See SPEC.md for the causality contract. Key rules:

- W4 score at observation_time=t uses only data strictly before t, so the
  latest score with observation_time <= cp is causal at checkpoint cp.
- Price mark at cp = open of the first raw 1s bar with ts_event >= cp
  (identical to the frozen runner's fill semantics).
- Running MFE/MAE at cp use only bars with ts_event in [entry_fill_ts, cp);
  whole-second timestamps mean those bars are fully complete at cp.
- The exit bar is excluded from every MFE/peak computation (conservative);
  the exit fill price itself is included as a final mark.
- peak_mfe checkpoints and capture/giveback quantities are retrospective
  descriptors and are flagged as such.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

STUDY = Path(__file__).resolve().parent
ROOT = STUDY.parents[1]
CODEX = ROOT / "studies" / "CODEX_5_X_weakness_atlas_repair"
CODEX_RESULTS = CODEX / "results"
INPUT_CONTRACT = CODEX / "CODEX_5_X_policy_input_contract.json"
OUT = STUDY / "results"

NS = 1_000_000_000
MULT = 20.0
COST_RT = 10.0
OFFSETS_S = (30, 60, 90, 120, 180, 300)
SLOPE_WINDOWS_S = (15, 30, 60)
MFE_THRESHOLDS_ATR = (0.25, 0.50, 0.75, 1.00)

RAW_1S = {
    2025: ROOT / "data" / "raw" / "NQ_v0_1s_2025.parquet",
    2026: ROOT / "data" / "raw" / "NQ_v0_1s_2026_ytd.parquet",
}


def sha256_file(path: Path, block: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(block):
            h.update(chunk)
    return h.hexdigest()


def verify_frozen_inputs(year: int) -> None:
    """The diagnostic must run on the exact bytes the frozen policy used."""
    contract = json.loads(INPUT_CONTRACT.read_text(encoding="utf-8"))
    if contract.get("status") != "FROZEN_BEFORE_POLICY_EXECUTION":
        raise RuntimeError("upstream policy input contract is not frozen")
    expected = contract[str(year)]
    current = {
        "raw": sha256_file(RAW_1S[year]),
        "scores": sha256_file(
            CODEX_RESULTS / f"CODEX_5_X_repaired_w4_scores_{year}.parquet"),
    }
    for key, value in current.items():
        if expected.get(key) != value:
            raise RuntimeError(f"frozen input hash mismatch for {year} {key}")


def validate_raw_bars(raw: pd.DataFrame) -> None:
    ts = raw.index.view(np.int64)
    if (not isinstance(raw.index, pd.DatetimeIndex) or np.any(np.diff(ts) <= 0)):
        raise RuntimeError("raw 1s ts_event index must be ordered and unique")
    if np.any(ts % NS != 0):
        raise RuntimeError("raw 1s timestamps must be whole seconds")
    values = raw[["open", "high", "low"]].to_numpy(float)
    if not np.isfinite(values).all():
        raise RuntimeError("raw 1s OHLC contains non-finite values")
    o, h, l = (values[:, i] for i in range(3))
    if np.any(h < o) or np.any(l > o) or np.any(h < l):
        raise RuntimeError("raw 1s OHLC geometry is invalid")


class ScoreSeries:
    """Per-regime W4 observation series with causal as-of lookup."""

    __slots__ = ("obs", "val", "thr")

    def __init__(self, obs: np.ndarray, val: np.ndarray, thr: np.ndarray):
        if np.any(np.diff(obs) <= 0):
            raise RuntimeError("score observation times must be strictly increasing")
        self.obs, self.val, self.thr = obs, val, thr

    def at(self, cp: int):
        """Latest observation with observation_time <= cp, or None."""
        i = int(np.searchsorted(self.obs, cp, side="right")) - 1
        if i < 0:
            return None
        return int(self.obs[i]), float(self.val[i]), float(self.thr[i])

    def slope(self, cp: int, window_s: int):
        """Change per second between as-of lookups at cp-window and cp."""
        p1 = self.at(cp)
        p0 = self.at(cp - window_s * NS)
        if p0 is None or p1 is None or p1[0] <= p0[0]:
            return np.nan
        return (p1[1] - p0[1]) / ((p1[0] - p0[0]) / NS)


def load_score_series(year: int, needed: set[int]) -> dict[int, ScoreSeries]:
    scores = pd.read_parquet(
        CODEX_RESULTS / f"CODEX_5_X_repaired_w4_scores_{year}.parquet",
        columns=["observation_time", "regime_start_ns", "w4_score",
                 "direction_threshold", "score_valid"],
    )
    scores = scores[scores["regime_start_ns"].isin(needed)]
    if not scores["score_valid"].fillna(False).all() or scores["w4_score"].isna().any():
        raise RuntimeError("invalid or missing frozen W4 scores in needed regimes")
    scores = scores.sort_values(["regime_start_ns", "observation_time"])
    return {
        int(k): ScoreSeries(
            g["observation_time"].to_numpy(np.int64),
            g["w4_score"].to_numpy(float),
            g["direction_threshold"].to_numpy(float),
        )
        for k, g in scores.groupby("regime_start_ns", sort=False)
    }


def outcome_group(exit_reason: str, net: float) -> str:
    if exit_reason.startswith("stop"):
        return exit_reason
    return "opposite_flip_exit_winner" if net > 0 else "opposite_flip_exit_loser"


def process_year(year: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    trades = pd.read_parquet(
        CODEX_RESULTS / f"CODEX_5_X_established_fade_{year}_trades.parquet"
    )
    if trades["net_pnl_usd"].isna().any() or trades["exit_fill_ts"].isna().any():
        raise RuntimeError("unexpected censored trades in frozen result set")

    verify_frozen_inputs(year)
    raw = pd.read_parquet(RAW_1S[year], columns=["open", "high", "low"])
    validate_raw_bars(raw)
    ts = raw.index.view(np.int64)
    opens = raw["open"].to_numpy(float)
    highs = raw["high"].to_numpy(float)
    lows = raw["low"].to_numpy(float)

    needed = set(trades["regime_start_ns"].astype(np.int64)) | set(
        trades["confirm_flip_ns"].astype(np.int64)
    )
    series = load_score_series(year, needed)

    cp_rows: list[dict] = []
    diag_rows: list[dict] = []

    for t in trades.itertuples(index=False):
        d = int(t.entry_direction)
        p = int(t.prevailing_direction)
        ep = float(t.entry_fill_open)
        atr = float(t.atr_at_checkpoint)
        entry_ts = int(t.entry_fill_ts)
        exit_ts = int(t.exit_fill_ts)
        confirm = int(t.confirm_flip_ns)
        exit_px = float(t.exit_fill_px)
        group = outcome_group(t.exit_reason, float(t.net_pnl_usd))
        reached_flip = not t.exit_reason == "stop_before_aligned_flip"

        i0 = int(np.searchsorted(ts, entry_ts, side="left"))
        ie = int(np.searchsorted(ts, exit_ts, side="left"))
        if int(ts[i0]) != entry_ts or int(ts[ie]) != exit_ts or ie < i0:
            raise AssertionError(f"trade bars not found at {t.regime_start_ns}")

        b_ts = ts[i0 : ie + 1]
        b_hi = highs[i0 : ie + 1]
        b_lo = lows[i0 : ie + 1]
        if d == 1:
            fav = b_hi - ep
            adv = ep - b_lo
        else:
            fav = ep - b_lo
            adv = b_hi - ep
        # Core bars = all bars strictly before the exit bar (exit bar excluded).
        n_core = len(b_ts) - 1
        run_mfe = np.maximum.accumulate(np.maximum(fav[:n_core], 0.0)) if n_core else np.empty(0)
        run_mae = np.maximum.accumulate(np.maximum(adv[:n_core], 0.0)) if n_core else np.empty(0)

        exit_fav = max((exit_px - ep) * d, 0.0)
        exit_adv = max((ep - exit_px) * d, 0.0)
        final_mfe = max(float(run_mfe[-1]) if n_core else 0.0, exit_fav)
        final_mae = max(float(run_mae[-1]) if n_core else 0.0, exit_adv)

        if n_core and float(run_mfe[-1]) >= exit_fav and final_mfe > 0:
            k_peak = int(np.argmax(run_mfe >= final_mfe - 1e-12))
            t_peak = int(b_ts[k_peak])
        else:
            t_peak = exit_ts

        # Old prevailing regime extreme before trade entry, from the regime's
        # first raw bar at/after the flip decision (upstream entry convention).
        r0 = int(np.searchsorted(ts, int(t.regime_start_ns), side="left"))
        if r0 >= i0:
            raise AssertionError("regime entry bar not before trade entry bar")
        if p == 1:
            pre_ext = float(np.max(highs[r0:i0]))
            ext_prefix = np.maximum.accumulate(b_hi[:n_core]) if n_core else np.empty(0)
            new_ext = ext_prefix > pre_ext
            exit_beyond_ext = exit_px > pre_ext
        else:
            pre_ext = float(np.min(lows[r0:i0]))
            ext_prefix = np.minimum.accumulate(b_lo[:n_core]) if n_core else np.empty(0)
            new_ext = ext_prefix < pre_ext
            exit_beyond_ext = exit_px < pre_ext
        new_ext_ever = bool(new_ext.any()) or exit_beyond_ext
        if n_core and new_ext.any():
            t_new_ext = int(b_ts[int(np.argmax(new_ext))])
        elif exit_beyond_ext:
            t_new_ext = exit_ts
        else:
            t_new_ext = None

        faded = series.get(int(t.regime_start_ns))
        aligned = series.get(confirm)
        if faded is None:
            raise AssertionError(f"missing faded-regime scores at {t.regime_start_ns}")
        # Parity: the frozen trigger score must be reproducible from the stream.
        trig = faded.at(int(t.score_observation_ts))
        if trig is None or trig[0] != int(t.score_observation_ts) or not np.isclose(
            trig[1], float(t.w4_score), rtol=0, atol=1e-12
        ):
            raise AssertionError(f"trigger score parity failure at {t.regime_start_ns}")

        def w4_fields(cp: int) -> dict:
            if cp < confirm:
                s, regime_lbl = faded, "faded"
            else:
                s, regime_lbl = aligned, "aligned"
            out = {
                "w4_regime": regime_lbl if s is not None else None,
                "w4_score_cp": np.nan, "w4_threshold_cp": np.nan,
                "w4_staleness_s": np.nan, "w4_above_threshold": np.nan,
                "w4_change_from_entry": np.nan,
                "w4_slope_15s": np.nan, "w4_slope_30s": np.nan, "w4_slope_60s": np.nan,
            }
            if s is None:
                return out
            res = s.at(cp)
            if res is None:
                return out
            obs, val, thr = res
            out.update({
                "w4_score_cp": val, "w4_threshold_cp": thr,
                "w4_staleness_s": (cp - obs) / NS,
                "w4_above_threshold": float(val >= thr),
            })
            if regime_lbl == "faded":
                out["w4_change_from_entry"] = val - float(t.w4_score)
            for w in SLOPE_WINDOWS_S:
                out[f"w4_slope_{w}s"] = s.slope(cp, w)
            return out

        def path_at(cp: int) -> dict:
            """Causal path state at cp; bars with ts_event < cp only."""
            j = int(np.searchsorted(b_ts, cp, side="left"))
            j = min(j, n_core)
            mfe = float(run_mfe[j - 1]) if j > 0 else 0.0
            mae = float(run_mae[j - 1]) if j > 0 else 0.0
            m = int(np.searchsorted(ts, cp, side="left"))
            mark = float(opens[m])
            pnl_pts = (mark - ep) * d
            extreme = bool(new_ext[j - 1]) if j > 0 else False
            return {"pnl_pts": pnl_pts, "mfe_pts": mfe, "mae_pts": mae,
                    "old_regime_new_extreme": extreme}

        def cp_row(label: str, cp: int, retrospective: bool = False,
                   pnl_pts_override: float | None = None,
                   mfe_override: float | None = None,
                   mae_override: float | None = None) -> dict:
            state = path_at(cp)
            if pnl_pts_override is not None:
                state["pnl_pts"] = pnl_pts_override
            if mfe_override is not None:
                state["mfe_pts"] = mfe_override
            if mae_override is not None:
                state["mae_pts"] = mae_override
            row = {
                "year": year, "regime_start_ns": int(t.regime_start_ns),
                "outcome_group": group, "entry_direction": d, "session": t.session,
                "checkpoint": label, "cp_ts": cp, "retrospective": retrospective,
                "time_since_entry_s": (cp - entry_ts) / NS,
                "time_since_flip_s": (cp - confirm) / NS if cp >= confirm else np.nan,
                "aligned_flip_occurred": cp >= confirm,
                "pnl_pts": state["pnl_pts"],
                "pnl_usd": state["pnl_pts"] * MULT,
                "pnl_atr": state["pnl_pts"] / atr,
                "mfe_atr": state["mfe_pts"] / atr,
                "mae_atr": state["mae_pts"] / atr,
                "old_regime_new_extreme": state["old_regime_new_extreme"],
                "net_pnl_usd_final": float(t.net_pnl_usd),
            }
            row.update(w4_fields(cp))
            return row

        # Offset checkpoints require cp < exit_ts strictly: a checkpoint that
        # lands on the exit bar would mark the trade "alive" at its open while
        # the exit (possibly an intra-bar stop) happens within the same second.
        rows = [cp_row("entry", entry_ts)]
        for off in OFFSETS_S:
            cp = entry_ts + off * NS
            if cp < exit_ts:
                rows.append(cp_row(f"t+{off}s", cp))
        if reached_flip and confirm < exit_ts:
            rows.append(cp_row("aligned_flip", confirm))
            for off in (60, 120):
                cp = confirm + off * NS
                if cp < exit_ts:
                    rows.append(cp_row(f"flip+{off}s", cp))
        if t_peak < exit_ts:
            rows.append(cp_row("peak_mfe", t_peak, retrospective=True))
        rows.append(cp_row(
            "exit", exit_ts, retrospective=False,
            pnl_pts_override=(exit_px - ep) * d,
            mfe_override=final_mfe, mae_override=final_mae,
        ))
        # Old-regime extreme flag at exit should include the exit mark.
        rows[-1]["old_regime_new_extreme"] = new_ext_ever
        cp_rows.extend(rows)

        # ---- per-trade scalar diagnostics ----
        diag = {
            "year": year, "regime_start_ns": int(t.regime_start_ns),
            "outcome_group": group, "exit_reason": t.exit_reason,
            "entry_direction": d, "session": t.session,
            "atr_at_checkpoint": atr, "hold_s": float(t.hold_s),
            "gross_pnl_usd": float(t.gross_pnl_usd), "net_pnl_usd": float(t.net_pnl_usd),
            "w4_entry": float(t.w4_score), "w4_threshold": float(t.direction_threshold),
            "peak_mfe_atr": final_mfe / atr, "peak_mfe_usd": final_mfe * MULT,
            "final_mae_atr": final_mae / atr,
            "t_peak_s": (t_peak - entry_ts) / NS,
            "t_peak_to_exit_s": (exit_ts - t_peak) / NS,
            "t_flip_s": (confirm - entry_ts) / NS if reached_flip else np.nan,
            "reached_flip": reached_flip,
            "old_regime_new_extreme_ever": new_ext_ever,
            "t_old_regime_new_extreme_s": (
                (t_new_ext - entry_ts) / NS if t_new_ext is not None else np.nan),
            "capture_ratio": (
                ((exit_px - ep) * d) / final_mfe if final_mfe > 0 else np.nan),
            "giveback_from_peak_atr": (final_mfe - (exit_px - ep) * d) / atr,
            "giveback_from_peak_usd": (final_mfe - (exit_px - ep) * d) * MULT,
        }
        for thr_atr in MFE_THRESHOLDS_ATR:
            key = f"reached_{str(thr_atr).replace('.', '')}_atr"
            diag[key] = final_mfe / atr >= thr_atr

        # Last available faded-regime W4 observation strictly before exit.
        last = faded.at(exit_ts - 1)
        if last is not None:
            diag["w4_last_preexit"] = last[1]
            diag["w4_last_staleness_s"] = (exit_ts - last[0]) / NS
            diag["w4_last_above_threshold"] = float(last[1] >= last[2])
            diag["w4_change_entry_to_last"] = last[1] - float(t.w4_score)
        else:
            diag["w4_last_preexit"] = np.nan
            diag["w4_last_staleness_s"] = np.nan
            diag["w4_last_above_threshold"] = np.nan
            diag["w4_change_entry_to_last"] = np.nan

        # ---- post-flip diagnostics (flip-reaching trades only) ----
        if reached_flip:
            m = int(np.searchsorted(ts, confirm, side="left"))
            flip_mark = float(opens[m])
            diag["pnl_at_flip_pts"] = (flip_mark - ep) * d
            diag["pnl_at_flip_usd"] = diag["pnl_at_flip_pts"] * MULT
            diag["pnl_at_flip_atr"] = diag["pnl_at_flip_pts"] / atr

            post = b_ts[:n_core] >= confirm
            post_fav = np.maximum(fav[:n_core][post], 0.0) if post.any() else np.empty(0)
            post_adv = np.maximum(adv[:n_core][post], 0.0) if post.any() else np.empty(0)
            post_max_adv = max(float(post_adv.max()) if len(post_adv) else 0.0, exit_adv)
            # Post-flip adverse excursion measured from the ENTRY price: >0 means
            # price revisited the countertrade entry after the aligning flip.
            diag["post_flip_max_adverse_atr"] = post_max_adv / atr
            diag["post_flip_revisit_entry"] = post_max_adv > 0
            diag["post_flip_adverse_beyond_025_atr"] = post_max_adv / atr >= 0.25
            diag["post_flip_adverse_beyond_05_atr"] = post_max_adv / atr >= 0.50
            post_peak = max(float(post_fav.max()) if len(post_fav) else 0.0, exit_fav)
            diag["post_flip_peak_mfe_atr"] = post_peak / atr
            if len(post_fav) and float(post_fav.max()) >= exit_fav and post_peak > 0:
                post_ts = b_ts[:n_core][post]
                k = int(np.argmax(np.maximum.accumulate(post_fav) >= post_peak - 1e-12))
                t_post_peak = int(post_ts[k])
            else:
                t_post_peak = exit_ts
            diag["t_flip_to_post_peak_s"] = (t_post_peak - confirm) / NS
            diag["post_flip_giveback_atr"] = (post_peak - (exit_px - ep) * d) / atr
            diag["post_flip_giveback_usd"] = (post_peak - (exit_px - ep) * d) * MULT

            # First adverse W4 signal from the aligned regime before exit:
            # first observation at/above its own direction threshold.
            warn = None
            if aligned is not None:
                mask = (aligned.obs > confirm) & (aligned.obs <= exit_ts)
                idx = np.flatnonzero(mask & (aligned.val >= aligned.thr))
                if len(idx):
                    warn = int(aligned.obs[idx[0]])
            diag["w4_warn_ts"] = warn
            if warn is not None:
                mw = int(np.searchsorted(ts, warn, side="left"))
                warn_mark = float(opens[mw])
                diag["t_flip_to_warn_s"] = (warn - confirm) / NS
                diag["pnl_at_warn_usd"] = (warn_mark - ep) * d * MULT
                diag["warned_before_exit"] = True
            else:
                diag["t_flip_to_warn_s"] = np.nan
                diag["pnl_at_warn_usd"] = np.nan
                diag["warned_before_exit"] = False
        diag_rows.append(diag)

    return pd.DataFrame(cp_rows), pd.DataFrame(diag_rows)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    cp_frames, diag_frames = [], []
    for year in (2025, 2026):
        cps, diags = process_year(year)
        n_trades = diags.shape[0]
        print(f"{year}: {n_trades} trades, {len(cps)} checkpoint rows")
        cp_frames.append(cps)
        diag_frames.append(diags)
    checkpoints = pd.concat(cp_frames, ignore_index=True)
    diagnostics = pd.concat(diag_frames, ignore_index=True)
    checkpoints.to_parquet(OUT / "path_checkpoints.parquet", index=False)
    diagnostics.to_parquet(OUT / "trade_diagnostics.parquet", index=False)
    print(f"saved {len(checkpoints)} checkpoint rows, {len(diagnostics)} trade rows")


if __name__ == "__main__":
    main()
