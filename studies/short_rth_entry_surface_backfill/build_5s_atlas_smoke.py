"""Single-year 5s-cadence repaired-atlas rebuild smoke (backfill Option A).

Forks `CODEX_5_X_build_repaired_atlas.build_raw_checkpoints` /
`attach_causal_w4_context` verbatim (both already pre-execution-audited,
`CODEX_5_X_weakness_atlas_repair/audit/CODEX_5_X_pre_execution_audit.md`),
but:

- forces `step_s=5` for every year, including <=2024 (the original always
  used 30s pre-2025 because that path is legacy-parity-gated);
- DOES NOT compare against the 30s legacy atlas (no such comparison target
  exists for a fresh 5s series pre-2025, and none is needed -- the legacy
  atlas exists only to prove a *different* rebuild reproduces legacy
  checkpoint identity, not to validate causality);
- instead re-applies every intrinsic causal/monotonicity/ATR assertion that
  `parity_and_merge` already enforces, verbatim, with the legacy-key
  reconciliation step removed.

This is a feasibility smoke, not a production rebuild: output is written
under this study's own `_work/`, never to the canonical repaired-atlas path,
and is not treated as authoritative until it passes its own audit.
"""
from __future__ import annotations

import argparse
import gc
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
WORK = HERE / "_work"
RESULTS, AUDIT = HERE / "results", HERE / "audit"
for d in (WORK, RESULTS, AUDIT):
    d.mkdir(parents=True, exist_ok=True)

CODEX_DIR = ROOT / "studies" / "CODEX_5_X_weakness_atlas_repair"
UPSTREAM = ROOT / "studies" / "regime_sequence_chop_context"
for p in (CODEX_DIR, UPSTREAM):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from CODEX_5_X_common import NS, RAW_1S, sha256_file  # noqa: E402
from CODEX_5_X_build_regime_history import build_completed_regimes  # noqa: E402
from CODEX_5_X_build_repaired_atlas import (  # noqa: E402
    attach_causal_w4_context, compute_activity_features_batched,
    compute_sequence_features_batched,
)
from build_weakness_atlas import build_weakness_checkpoints_for_regime  # noqa: E402
from reproduce_regimes import aggregate_and_run_regimes  # noqa: E402
from train_weakness_model import CENTER_FEATS, SEQUENCE_FEATS  # noqa: E402


def build_raw_checkpoints_5s(year: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Verbatim fork of CODEX_5_X_build_repaired_atlas.build_raw_checkpoints,
    with step_s forced to 5 regardless of year."""
    raw = pd.read_parquet(RAW_1S[year])
    if not raw.index.is_monotonic_increasing or not raw.index.is_unique:
        raise RuntimeError(f"{year} raw 1s index must be increasing and unique")
    df_1m = aggregate_and_run_regimes(raw, "1m")
    regimes = build_completed_regimes(df_1m, raw)
    raw_ns = raw.copy()
    raw_ns.index = raw_ns.index.view(np.int64)
    records: list[dict] = []
    contracts: list[dict] = []
    step_s = 5  # <-- the only behavioral change vs the original function

    atr_by_flip = dict(zip(
        df_1m["close_ts"].astype(np.int64), df_1m["atr"].astype(float)
    ))
    for reg in regimes.itertuples(index=False):
        direction = int(reg.direction)
        start = int(reg.start_time)
        end = int(reg.end_time)
        atr = float(atr_by_flip.get(start, np.nan))
        if not np.isfinite(atr) or atr <= 0:
            continue
        raw_index = raw_ns.index.to_numpy(dtype=np.int64, copy=False)
        entry_pos = int(np.searchsorted(raw_index, start, side="left"))
        if entry_pos >= len(raw_ns) or int(raw_index[entry_pos]) >= end:
            continue
        entry_ts = int(raw_index[entry_pos])
        entry_open = float(raw_ns.iloc[entry_pos]["open"])
        path = raw_ns.loc[entry_ts:end + 300 * NS]
        if int(path.index[0]) != entry_ts:
            raise RuntimeError("anchor timestamp must equal first path timestamp")
        contracts.append({
            "year": year, "regime_start_ns": start,
            "regime_end_ns": end, "direction": direction,
            "entry_ts_event": entry_ts, "entry_open": entry_open,
        })
        rows = build_weakness_checkpoints_for_regime(
            direction=direction, flip_ts=start, flip_close=entry_open,
            opp_flip_ts=end, atr_val=atr, df_1s_regime=path,
            df_regimes=regimes, step_s=step_s,
        )
        for row in rows:
            row["regime_start_ns"] = start
        records.extend(rows)
    out = pd.DataFrame(records)
    out = out.sort_values(["observation_time", "direction"], kind="stable")
    assert not out.duplicated(["observation_time", "direction"]).any()
    out = attach_causal_w4_context(raw, df_1m, regimes, out)
    del raw, raw_ns, df_1m, regimes
    gc.collect()
    contract = pd.DataFrame(contracts).drop_duplicates(
        ["year", "regime_start_ns", "direction"]
    )
    return out, contract


def intrinsic_causal_audit(year: int, out: pd.DataFrame) -> dict:
    """Every check `parity_and_merge` applies EXCEPT the legacy-atlas
    key reconciliation (there is no legacy 5s atlas pre-2025 to compare
    against -- that is the entire point of this backfill)."""
    if not set(out["direction"].dropna().unique()) <= {-1, 1}:
        raise RuntimeError("invalid direction in 5s atlas")
    if out["direction"].isna().any():
        raise RuntimeError("null direction in 5s atlas")
    if not (out["entry_ts_event"] >= out["flip_decision_ns"]).all():
        raise RuntimeError("entry precedes flip decision")
    if not (out["observation_time"] < out["regime_end_ns"]).all():
        raise RuntimeError("non-causal endpoint checkpoint survived")

    numeric = out[["current_mfe", "current_mae", "running_mfe", "running_mae"]]
    negative = int((numeric < -1e-12).sum().sum())
    mono_mfe = int((out.groupby("regime_start_ns", sort=False)["running_mfe"]
                    .diff().fillna(0) < -1e-12).sum())
    mono_mae = int((out.groupby("regime_start_ns", sort=False)["running_mae"]
                    .diff().fillna(0) < -1e-12).sum())
    if negative or mono_mfe or mono_mae:
        raise RuntimeError(
            f"causal audit failed: negative={negative} mono_mfe={mono_mfe} mono_mae={mono_mae}")
    if not np.allclose(out["current_mfe"], out["running_mfe"]):
        raise RuntimeError("current_mfe/running_mfe alias violation")
    if not np.allclose(out["current_mae"], out["running_mae"]):
        raise RuntimeError("current_mae/running_mae alias violation")
    atr_values = out[["atr_at_entry", "atr_at_checkpoint"]].to_numpy(dtype=float)
    if not np.isfinite(atr_values).all():
        raise RuntimeError("entry/checkpoint ATR must be finite")
    if not ((out["atr_at_entry"] > 0) & (out["atr_at_checkpoint"] > 0)).all():
        raise RuntimeError("entry/checkpoint ATR must be positive")
    missing = [c for c in CENTER_FEATS + SEQUENCE_FEATS if c not in out]
    if missing:
        raise RuntimeError(f"missing rebuilt W4 context columns: {missing}")
    return {
        "year": year, "rows": len(out),
        "distinct_regimes": int(out["regime_start_ns"].nunique()),
        "negative_excursion_cells": negative,
        "running_mfe_monotonicity_violations": mono_mfe,
        "running_mae_monotonicity_violations": mono_mae,
        "direction_values": sorted(int(d) for d in out["direction"].unique()),
        "feature_columns_present": len(CENTER_FEATS) + len(SEQUENCE_FEATS),
    }


def build_manifest_path(year: int) -> Path:
    # Deliberately NOT under results/ -- that namespace is owned by the
    # consolidated per-year report (smoke_2021_surface.py / run_year_backfill.py),
    # which reads this file. A shared path previously caused the consolidator
    # to clobber its own input on re-run (KeyError on the second run).
    return WORK / f"atlas_5s_backfill_{year}_build_manifest.json"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--force", action="store_true",
                     help="rebuild even if the atlas parquet already exists")
    args = ap.parse_args()
    year = args.year

    out_path = WORK / f"atlas_5s_backfill_{year}.parquet"
    if out_path.exists() and not args.force:
        print(f"{out_path.name} exists; recomputing audit only (use --force to rebuild)")
        out = pd.read_parquet(out_path)
        audit = intrinsic_causal_audit(year, out)
        audit["build_runtime_s"] = None
        audit["note"] = "reused existing atlas parquet; audit recomputed, not rebuilt"
    else:
        t0 = time.time()
        out, contracts = build_raw_checkpoints_5s(year)
        build_s = time.time() - t0
        audit = intrinsic_causal_audit(year, out)
        audit["build_runtime_s"] = round(build_s, 1)
        out.to_parquet(out_path, index=False, compression="zstd")
    audit["raw_sha256"] = sha256_file(RAW_1S[year])
    audit["runner_sha256"] = sha256_file(Path(__file__).resolve())
    audit["output_path"] = str(out_path)
    audit["output_sha256"] = sha256_file(out_path)

    build_manifest_path(year).write_text(
        json.dumps(audit, indent=2, default=str), encoding="utf-8")

    print(f"[{year}] 5s backfill: {audit['rows']:,} checkpoints, "
          f"{audit['distinct_regimes']:,} regimes, "
          f"build_runtime_s={audit['build_runtime_s']}, "
          f"causal audit clean (0 negative, 0 mono violations)")
    print(json.dumps(audit, indent=2, default=str))


if __name__ == "__main__":
    main()
