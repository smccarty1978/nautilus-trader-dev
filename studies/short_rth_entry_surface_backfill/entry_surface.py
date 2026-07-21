"""Score-independent short-RTH entry-surface generator.

Reuses the causal established-regime filter, RTH filter, and progress-window
logic already audited in `CODEX_5_X_run_established_fade.py`, but does not
require the frozen W4 score anywhere: a checkpoint is "eligible" (established,
RTH, prevailing-bullish) on its own atlas fields, independent of any W4 score.
This removes the in-sample/circular dependency that blocks 2021-2024 (see
`studies/short_rth_entry_surface_backfill/SPEC.md`).

Every established/RTH/prevailing-bullish checkpoint with a valid fill becomes
a surface row (not just the first W4-threshold crossing). The known
threshold-crossing candidate population (650/222 for 2025/2026) is a subset
of this surface, checked by `run_reconciliation.py`.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

ATLAS_COLS = [
    "observation_time", "regime_start_ns", "regime_end_ns", "direction",
    "entry_ts_event", "entry_open", "atr_at_entry", "atr_at_checkpoint",
    "regime_age", "current_pnl", "current_mfe", "current_mae",
    "running_mfe", "running_mae",
]


def load_atlas_stream(atlas_path) -> pd.DataFrame:
    """Load repaired-atlas checkpoint columns needed for the established
    filter. Deliberately does NOT merge any W4 score."""
    stream = pd.read_parquet(atlas_path, columns=ATLAS_COLS)
    if not np.allclose(stream["current_mfe"], stream["running_mfe"], rtol=0, atol=1e-12):
        raise RuntimeError("current_mfe/running_mfe alias violation")
    if not np.allclose(stream["current_mae"], stream["running_mae"], rtol=0, atol=1e-12):
        raise RuntimeError("current_mae/running_mae alias violation")
    if not (stream[["current_mfe", "current_mae"]] >= -1e-12).all().all():
        raise RuntimeError("negative repaired excursion")
    return stream.sort_values(["regime_start_ns", "observation_time"], kind="stable").reset_index(drop=True)


def build_surface(year: int, stream: pd.DataFrame, raw: pd.DataFrame, filt: dict,
                   is_rth, progress_window_counts) -> tuple[pd.DataFrame, dict]:
    """Every established/RTH/prevailing-bullish checkpoint with a valid fill.

    `is_rth` and `progress_window_counts` are passed in (reused verbatim from
    `CODEX_5_X_run_established_fade`) rather than reimplemented here, so this
    module cannot silently drift from the audited causal definitions.

    Returns (surface_rows, attrition), where attrition counts checkpoints and
    distinct regimes surviving each stage: all -> bullish_regime ->
    established -> rth -> valid_fill. No W4 score is used anywhere.
    """
    ts = raw.index.view(np.int64)
    opens = raw["open"].to_numpy(float)
    highs = raw["high"].to_numpy(float)

    stages = ["all", "bullish_regime", "established", "rth", "valid_fill",
              "rth_boundary_divergence"]
    stage_checkpoints = {s: 0 for s in stages}
    stage_regimes: dict[str, set] = {s: set() for s in stages}
    rows: list[dict] = []

    for regime_start, group in stream.groupby("regime_start_ns", sort=False):
        group = group.sort_values("observation_time", kind="stable")
        first = group.iloc[0]
        stage_checkpoints["all"] += len(group)
        stage_regimes["all"].add(int(regime_start))

        direction = int(first.direction)
        if direction != 1:          # prevailing long -> short-fade candidate only
            continue
        stage_checkpoints["bullish_regime"] += len(group)
        stage_regimes["bullish_regime"].add(int(regime_start))

        entry_ts, regime_end = int(first.entry_ts_event), int(first.regime_end_ns)
        atr_entry, anchor = float(first.atr_at_entry), float(first.entry_open)
        if not (np.isfinite(atr_entry) and atr_entry > 0):
            raise RuntimeError(f"non-positive atr_at_entry in regime {regime_start}")
        for col in ("direction", "entry_ts_event", "regime_end_ns", "atr_at_entry", "entry_open"):
            if group[col].nunique() != 1:
                raise RuntimeError(f"non-constant '{col}' within regime {regime_start}")
        a = int(np.searchsorted(ts, entry_ts, side="left"))
        b = int(np.searchsorted(ts, regime_end, side="left"))
        if a >= b or int(ts[a]) != entry_ts:
            raise RuntimeError(f"invalid regime raw path {regime_start}")
        favorable = highs[a:b] - anchor    # direction==1: long-regime favorable = up
        running = np.maximum.accumulate(np.maximum(favorable / atr_entry, 0.0))
        progress = progress_window_counts(running, ts[a:b])

        for cp in group.itertuples(index=False):
            decision = int(cp.observation_time)
            k = int(np.searchsorted(ts[a:b], decision, side="left") - 1)
            if k < 0 or decision >= regime_end:
                continue
            if not np.isclose(float(running[k]), float(cp.current_mfe), rtol=0, atol=1e-9):
                raise RuntimeError(f"MFE/raw mismatch {decision}")
            retained = (float(cp.current_pnl) / float(cp.current_mfe)
                        if float(cp.current_mfe) > 0 else np.nan)
            established = bool(
                float(cp.regime_age) >= filt["regime_age_s_min"]
                and float(cp.current_mfe) >= filt["running_mfe_atr_min"]
                and int(progress[k]) >= filt["new_progress_windows_min"]
                and retained >= filt["retained_mfe_ratio_min"])
            if not established:
                continue
            stage_checkpoints["established"] += 1
            stage_regimes["established"].add(int(regime_start))

            fill_i = int(np.searchsorted(ts, decision, side="left"))
            if fill_i >= len(ts):
                continue
            fill_ts, fill_px = int(ts[fill_i]), float(opens[fill_i])

            # Session is classified on the FILL timestamp, matching the
            # audited fable5_short_rth_threshold_ladder/run_ladder.py
            # convention (session = is_rth(fill_ts), not decision time) --
            # the SPEC's "entry filter" language means the trade's actual
            # entry, not the decision that triggered it. Divergence is rare
            # (only possible right at the 08:30/15:00 boundary) but tracked
            # explicitly rather than silently picking one convention.
            if is_rth(decision) != is_rth(fill_ts):
                stage_checkpoints["rth_boundary_divergence"] += 1
                stage_regimes["rth_boundary_divergence"].add(int(regime_start))
            if not is_rth(fill_ts):
                continue
            stage_checkpoints["rth"] += 1
            stage_regimes["rth"].add(int(regime_start))

            if fill_ts >= regime_end:
                continue
            stage_checkpoints["valid_fill"] += 1
            stage_regimes["valid_fill"].add(int(regime_start))

            rows.append({
                "year": year, "regime_start_ns": int(regime_start),
                "observation_time": decision, "confirm_flip_ns": regime_end,
                "prevailing_direction": direction, "entry_direction": -direction,
                "fill_ts": fill_ts, "fill_px": fill_px,
                "atr_at_checkpoint": float(cp.atr_at_checkpoint),
                "regime_age_s": float(cp.regime_age),
                "running_mfe_atr": float(cp.current_mfe),
                "running_mae_atr": float(cp.current_mae),
                "new_progress_windows": int(progress[k]), "retained_mfe_ratio": retained,
                "session": "RTH",
            })

    surface = pd.DataFrame(rows)
    attrition = {
        "checkpoints": stage_checkpoints,
        "distinct_regimes": {k: len(v) for k, v in stage_regimes.items()},
    }
    return surface, attrition
