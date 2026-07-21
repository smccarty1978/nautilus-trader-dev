"""Phase 1 - Mirrored long-side (direction == -1) entry-surface builder.

Faithful fork of
`studies/short_rth_entry_surface_backfill/entry_surface.py:build_surface`.
ONLY these lines differ from the audited short-side function, everything else
(established filter, RTH-on-fill classification, progress windows, valid-fill
gate, attrition accounting) is byte-identical logic:

    short side                          long mirror
    ----------                          -----------
    if direction != 1: continue    ->   if direction != -1: continue
    favorable = highs[a:b]-anchor  ->   favorable = anchor - lows[a:b]
    prevailing_direction=+1,-dir   ->   prevailing_direction=-1, entry=+1

The established filter still reads `cp.current_mfe` (bearish-favorable in the
atlas for direction==-1 regimes), `cp.regime_age`, `progress[k]`,
`retained_mfe_ratio` unchanged.

Self-validation (mandatory): the re-derived bearish-favorable running MFE must
equal the atlas `cp.current_mfe` to 1e-9. This is an INDEPENDENT proof the atlas
excursion is bearish-oriented for direction==-1 regimes. Divergence => STOP
(LONG_SURFACE_DIRECTIONALITY_FAILED), never silently proceed.

Atlas sources (5s cadence, both directions, verified identical schema for the
44 center feats + all keys):
  2021-2024: short_rth_entry_surface_backfill/_work/atlas_5s_backfill_{y}.parquet
  2025,2026: CODEX_5_X_weakness_atlas_repair/_work/CODEX_5_X_repaired_years/
             CODEX_5_X_weakness_atlas_repaired_{y}.parquet
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
STUDY = HERE.parent
ROOT = STUDY.parents[1]
WORK, RESULTS = STUDY / "_work", STUDY / "results"
for d in (WORK, RESULTS):
    d.mkdir(parents=True, exist_ok=True)

ENTRY_SURFACE_DIR = ROOT / "studies" / "short_rth_entry_surface_backfill"
CODEX_DIR = ROOT / "studies" / "CODEX_5_X_weakness_atlas_repair"
for p in (ENTRY_SURFACE_DIR, CODEX_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

# Reuse the audited causal helpers verbatim - never reimplemented here.
from CODEX_5_X_common import RAW_1S, sha256_file  # noqa: E402
from CODEX_5_X_run_established_fade import (  # noqa: E402
    is_rth, progress_window_counts, validate_raw_bars,
)
import entry_surface as ES  # noqa: E402  (for ATLAS_COLS + load_atlas_stream reuse)

POLICY_PATH = (CODEX_DIR / "CODEX_5_X_established_fade_policy.json")

ATLAS_PATHS = {
    2021: ENTRY_SURFACE_DIR / "_work" / "atlas_5s_backfill_2021.parquet",
    2022: ENTRY_SURFACE_DIR / "_work" / "atlas_5s_backfill_2022.parquet",
    2023: ENTRY_SURFACE_DIR / "_work" / "atlas_5s_backfill_2023.parquet",
    2024: ENTRY_SURFACE_DIR / "_work" / "atlas_5s_backfill_2024.parquet",
    2025: CODEX_DIR / "_work" / "CODEX_5_X_repaired_years" / "CODEX_5_X_weakness_atlas_repaired_2025.parquet",
    2026: CODEX_DIR / "_work" / "CODEX_5_X_repaired_years" / "CODEX_5_X_weakness_atlas_repaired_2026.parquet",
}


def build_surface_long(year: int, stream: pd.DataFrame, raw: pd.DataFrame,
                       filt: dict) -> tuple[pd.DataFrame, dict]:
    """Every established/RTH/prevailing-BEARISH checkpoint with a valid fill."""
    ts = raw.index.view(np.int64)
    opens = raw["open"].to_numpy(float)
    lows = raw["low"].to_numpy(float)

    stages = ["all", "bearish_regime", "established", "rth", "valid_fill",
              "rth_boundary_divergence"]
    stage_checkpoints = {s: 0 for s in stages}
    stage_regimes: dict[str, set] = {s: set() for s in stages}
    rows: list[dict] = []
    n_mfe_checked = 0

    for regime_start, group in stream.groupby("regime_start_ns", sort=False):
        group = group.sort_values("observation_time", kind="stable")
        first = group.iloc[0]
        stage_checkpoints["all"] += len(group)
        stage_regimes["all"].add(int(regime_start))

        direction = int(first.direction)
        if direction != -1:          # prevailing bearish -> long-fade candidate only
            continue
        stage_checkpoints["bearish_regime"] += len(group)
        stage_regimes["bearish_regime"].add(int(regime_start))

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
        # MIRROR: bearish-favorable excursion = price drops below the entry anchor.
        favorable = anchor - lows[a:b]
        running = np.maximum.accumulate(np.maximum(favorable / atr_entry, 0.0))
        progress = progress_window_counts(running, ts[a:b])

        for cp in group.itertuples(index=False):
            decision = int(cp.observation_time)
            k = int(np.searchsorted(ts[a:b], decision, side="left") - 1)
            if k < 0 or decision >= regime_end:
                continue
            # SELF-VALIDATION: re-derived bearish MFE must match atlas current_mfe.
            if not np.isclose(float(running[k]), float(cp.current_mfe), rtol=0, atol=1e-9):
                raise RuntimeError(
                    f"LONG_SURFACE_DIRECTIONALITY_FAILED: re-derived bearish MFE "
                    f"{float(running[k]):.9f} != atlas current_mfe "
                    f"{float(cp.current_mfe):.9f} at regime {regime_start} obs {decision}")
            n_mfe_checked += 1
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
                "regime_start_time": int(regime_start),
                "prevailing_direction": direction, "entry_direction": -direction,
                "fill_ts": fill_ts, "fill_px": fill_px,
                "atr_at_entry": atr_entry,
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
        "mfe_directionality_checks_passed": n_mfe_checked,
    }
    return surface, attrition


def run_year(year: int) -> dict:
    t0 = time.time()
    atlas_path = ATLAS_PATHS[year]
    if not atlas_path.exists():
        raise RuntimeError(f"atlas missing for {year}: {atlas_path}")
    stream = ES.load_atlas_stream(atlas_path)
    raw = pd.read_parquet(RAW_1S[year], columns=["open", "high", "low", "close", "volume"])
    validate_raw_bars(raw)
    filt = json.loads(POLICY_PATH.read_text(encoding="utf-8"))["filter"]

    surface, attrition = build_surface_long(year, stream, raw, filt)
    out_path = WORK / f"surface_long_{year}.parquet"
    surface.to_parquet(out_path, index=False, compression="zstd")

    rep = {
        "year": year,
        "atlas_path": str(atlas_path),
        "atlas_sha256": sha256_file(atlas_path),
        "raw_sha256": sha256_file(RAW_1S[year]),
        "surface_rows": len(surface),
        "surface_regimes": int(surface["regime_start_ns"].nunique()) if len(surface) else 0,
        "attrition": attrition,
        "output_path": str(out_path),
        "output_sha256": sha256_file(out_path),
        "runtime_s": round(time.time() - t0, 1),
    }
    print(f"[{year}] {rep['runtime_s']}s surface_rows={rep['surface_rows']:,} "
          f"regimes={rep['surface_regimes']:,} "
          f"mfe_checks={attrition['mfe_directionality_checks_passed']:,} "
          f"bearish_cp={attrition['checkpoints']['bearish_regime']:,}")
    return rep


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=int, nargs="+",
                    default=[2021, 2022, 2023, 2024, 2025, 2026])
    args = ap.parse_args()
    reports = {}
    for y in args.years:
        reports[y] = run_year(y)
    (RESULTS / "phase1_surface_manifest.json").write_text(
        json.dumps({"generator_sha256": sha256_file(Path(__file__).resolve()),
                    "policy_sha256": sha256_file(POLICY_PATH),
                    "years": reports}, indent=2, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
