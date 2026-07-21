"""Build causal W4 scores and descriptive completed-regime metrics.

This is Stage 1 only.  No trading policy is evaluated here.  Regime identities
come from the upstream NT study artifact (F1 flip population); pandas is used
only for post-study path characterization.  Future path information is written
only to descriptive outcome columns and is never used to compute W4 scores.
"""
from __future__ import annotations

import json
import time

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from common import (
    AUDIT, FLIP_ATLAS, NS, RAW_1S, RESULTS, WEAKNESS_ATLAS, WORK,
    is_rth, load_model_bundle,
)

NAN_GATE = "aligned_price_minus_center_5m"
SCORE_PATH = WORK / "w4_scores_all_years.parquet"
METRICS_PATH = RESULTS / "stage1_regime_metrics.parquet"


def build_causal_scores() -> None:
    """Score every upstream checkpoint using causal feature columns only."""
    if SCORE_PATH.exists():
        # Fail closed on cache provenance: the chronology/feature contract is
        # cheap enough to rebuild and must never silently reuse an older file
        # that may contain secondary_oos/2026 rows.
        SCORE_PATH.unlink()
    bundle = load_model_bundle()
    model = bundle["model"]
    features = list(bundle["features"])
    cols = list(dict.fromkeys(
        features + [NAN_GATE, "observation_time", "regime_age", "direction", "period"]
    ))
    pf = pq.ParquetFile(WEAKNESS_ATLAS)
    writer = None
    total = valid_total = 0
    cutoff_2026 = pd.Timestamp("2026-01-01", tz="UTC").value
    max_observation_time = 0
    try:
        for rg in range(pf.num_row_groups):
            d = pf.read_row_group(rg, columns=cols).to_pandas()
            # Stage 1 may inspect discovery (2021-2024) and validation
            # (all of 2025) only. Upstream period labels overlap years, so the
            # chronology firewall is enforced by timestamp, not period name.
            d = d[d["observation_time"] < cutoff_2026].copy()
            if d.empty:
                continue
            valid = d[NAN_GATE].notna().to_numpy()
            score = np.full(len(d), np.nan, dtype=np.float64)
            if valid.any():
                score[valid] = model.predict_proba(
                    d.loc[valid, features].to_numpy()
                )[:, 1]
            obs = d["observation_time"].to_numpy(dtype=np.int64)
            age = np.rint(d["regime_age"].to_numpy()).astype(np.int64)
            out = pd.DataFrame({
                "observation_time": obs,
                "regime_start_ns": obs - age * NS,
                "direction": d["direction"].to_numpy(dtype=np.int8),
                "regime_age_s": d["regime_age"].to_numpy(dtype=float),
                "period": d["period"].astype(str).to_numpy(),
                "score_valid": valid,
                "w4_score": score,
            })
            table = pa.Table.from_pandas(out, preserve_index=False)
            if writer is None:
                writer = pq.ParquetWriter(SCORE_PATH, table.schema, compression="zstd")
            writer.write_table(table)
            total += len(out)
            valid_total += int(valid.sum())
            max_observation_time = max(
                max_observation_time, int(out["observation_time"].max())
            )
            print(f"score row-group {rg + 1}/{pf.num_row_groups}: {total:,}")
    finally:
        if writer is not None:
            writer.close()
    assert max_observation_time < cutoff_2026, "2026 score row crossed firewall"
    (AUDIT / "stage1_score_build.json").write_text(json.dumps({
        "rows": total,
        "valid_rows": valid_total,
        "invalid_rows_retained": total - valid_total,
        "max_observation_time": max_observation_time,
        "cutoff_exclusive": cutoff_2026,
        "feature_count": len(features),
        "nan_gate": NAN_GATE,
        "labels_loaded": [],
        "note": "Only causal W4 features and identity/timestamp fields were read.",
    }, indent=2), encoding="utf-8")


def load_regime_population() -> pd.DataFrame:
    """Regime identities from a fresh per-year RegimeEngine run.

    The flip_context_atlas F1 `direction` column is 100% NaN for 2021-2025
    and its `regime` column disagrees with true direction in ~25% of the one
    year where both exist (pass-2 audit CRITICAL), so regime identities are
    rebuilt from raw 1s data with the exact upstream engine — the same
    reproduction whose flip stream the prior D10 study's parity gate proved
    matches the atlas checkpoint keys exactly. Direction is additionally
    parity-checked against the weakness-atlas score stream in main()
    (fail-fast).
    """
    import sys as _sys
    from common import ROOT
    up = str(ROOT / "studies" / "regime_sequence_chop_context")
    if up not in _sys.path:
        _sys.path.insert(0, up)
    from reproduce_regimes import aggregate_and_run_regimes

    frames = []
    for year in range(2021, 2026):
        raw = pd.read_parquet(RAW_1S[year],
                              columns=["open", "high", "low", "close",
                                       "volume"])
        df_1m = aggregate_and_run_regimes(raw, "1m").sort_values("close_ts")
        prev = df_1m["regime"].shift(1).fillna(0).astype(int)
        flips = df_1m[(df_1m["regime"] != 0) & (prev != 0)
                      & (df_1m["regime"] != prev)]
        frows = list(flips.itertuples())
        rows = []
        for i, r in enumerate(frows[:-1]):  # trailing open regime: censored
            rows.append({
                "year": year,
                "regime_start_ns": int(r.close_ts),
                "regime_end_ns": int(frows[i + 1].close_ts),
                "direction": int(r.regime),
                "atr": float(r.atr),
                "end_censored": False,
            })
        frames.append(pd.DataFrame(rows))
        del raw, df_1m
        print(f"  regimes {year}: {len(rows):,} completed "
              f"(+1 censored tail excluded)")
    d = pd.concat(frames, ignore_index=True)
    assert int(d["year"].max()) <= 2025, "2026 regime row crossed firewall"
    d["rth"] = is_rth(d["regime_start_ns"].to_numpy())
    (AUDIT / "stage1_regime_source.json").write_text(json.dumps({
        "source": "fresh RegimeEngine per year from raw 1s (atlas F1 "
                  "direction column unusable for 2021-2025; pass-2 audit)",
        "completed_regimes": int(len(d)),
        "censored_excluded_per_year": {y: 1 for y in range(2021, 2026)},
    }, indent=2), encoding="utf-8")
    assert not d.duplicated("regime_start_ns").any()
    return d.sort_values("regime_start_ns").reset_index(drop=True)


def _last_close_before(ts: np.ndarray, closes: np.ndarray, boundary: int) -> float:
    idx = np.searchsorted(ts, boundary, side="left") - 1
    return float(closes[idx]) if idx >= 0 else np.nan


def characterize_year(reg: pd.DataFrame, year: int) -> list[dict]:
    raw = pd.read_parquet(RAW_1S[year], columns=["open", "high", "low", "close"])
    ts = raw.index.view(np.int64)
    highs = raw["high"].to_numpy(dtype=float)
    lows = raw["low"].to_numpy(dtype=float)
    closes = raw["close"].to_numpy(dtype=float)
    out: list[dict] = []

    for r in reg[reg["year"] == year].itertuples(index=False):
        if r.end_censored or not np.isfinite(r.atr) or r.atr <= 0:
            continue
        a = int(np.searchsorted(ts, r.regime_start_ns, side="left"))
        b = int(np.searchsorted(ts, r.regime_end_ns, side="left"))
        if b <= a:
            continue
        h = highs[a:b]
        l = lows[a:b]
        c = closes[a:b]
        t = ts[a:b]
        anchor = _last_close_before(ts, closes, int(r.regime_start_ns))
        exit_px = _last_close_before(ts, closes, int(r.regime_end_ns))
        if not np.isfinite(anchor) or not np.isfinite(exit_px):
            continue
        if r.direction == 1:
            fav = (h - anchor) / r.atr
            running_mfe = np.maximum.accumulate(fav)
        else:
            fav = (anchor - l) / r.atr
            running_mfe = np.maximum.accumulate(fav)
        pnl = r.direction * (c - anchor) / r.atr
        final_pnl = r.direction * (exit_px - anchor) / r.atr
        peak = float(np.max(running_mfe))
        peak_idx = int(np.argmax(running_mfe))

        def first_touch(level: float) -> tuple[float, int | None]:
            hit = np.flatnonzero(running_mfe >= level)
            if not len(hit):
                return np.nan, None
            i = int(hit[0])
            return (t[i] + NS - r.regime_start_ns) / NS, i

        t05, i05 = first_touch(0.5)
        t10, i10 = first_touch(1.0)

        # A new-progress window begins with a new favorable high/low after at
        # least 120 seconds without a prior new extreme.  The first extreme is
        # the first window; equal highs/lows do not create progress events.
        new_extreme = np.r_[True, running_mfe[1:] > running_mfe[:-1] + 1e-12]
        ext_idx = np.flatnonzero(new_extreme)
        n_windows = 0
        last_ext_ts = None
        for j in ext_idx:
            tj = int(t[j])
            if last_ext_ts is None or tj - last_ext_ts >= 120 * NS:
                n_windows += 1
            last_ext_ts = tj

        targets = {
            # Raw Databento 1s timestamps mark bar OPEN.  A touch/high/low in
            # that bar is known at its close, one second later.
            "qual": int(t[i10] + NS) if i10 is not None else None,
            "peak": int(t[peak_idx] + NS),
            "m60": int(r.regime_end_ns - 60 * NS),
            "m30": int(r.regime_end_ns - 30 * NS),
            "flip": int(r.regime_end_ns),
        }

        rec = {
            "regime_id": f"{year}_{int(r.regime_start_ns)}",
            "year": year,
            "period": "train" if year <= 2024 else ("validation" if year == 2025 else "test"),
            "regime_start_ns": int(r.regime_start_ns),
            "regime_end_ns": int(r.regime_end_ns),
            "direction": int(r.direction),
            "session": "RTH" if r.rth else "ETH",
            "atr_at_start": float(r.atr),
            "duration_s": (r.regime_end_ns - r.regime_start_ns) / NS,
            "final_flip_pnl_atr": float(final_pnl),
            "peak_mfe_atr": peak,
            "time_to_0p5_s": t05,
            "time_to_1p0_s": t10,
            "time_peak_to_flip_s": (r.regime_end_ns - (t[peak_idx] + NS)) / NS,
            "giveback_atr": peak - final_pnl,
            "new_progress_windows": n_windows,
        }
        for name, target in targets.items():
            rec[f"target_{name}_ns"] = target
            if target is None or target < r.regime_start_ns:
                rec[f"retained_{name}"] = np.nan
                continue
            # target is a wall-clock decision boundary; only bars opening
            # strictly before it have completed.
            k = int(np.searchsorted(t, target, side="left") - 1)
            if k < 0:
                rec[f"retained_{name}"] = np.nan
            else:
                denom = running_mfe[k]
                rec[f"retained_{name}"] = float(pnl[k] / denom) if denom > 0 else np.nan
        out.append(rec)
    return out


def attach_w4(metrics: pd.DataFrame) -> pd.DataFrame:
    """Attach last valid checkpoint score at or before each causal target."""
    scores = pd.read_parquet(SCORE_PATH)
    scores = scores[scores["score_valid"] & scores["w4_score"].notna()].copy()
    scores = scores.sort_values(
        ["regime_start_ns", "observation_time"], kind="stable"
    ).reset_index(drop=True)
    score_starts = scores["regime_start_ns"].to_numpy(dtype=np.int64)
    score_obs = scores["observation_time"].to_numpy(dtype=np.int64)
    score_vals = scores["w4_score"].to_numpy(dtype=float)
    unique_starts, first, counts = np.unique(
        score_starts, return_index=True, return_counts=True
    )
    slices = {
        int(k): (int(a), int(a + n))
        for k, a, n in zip(unique_starts, first, counts)
    }
    availability: dict[str, int] = {}
    for name in ("qual", "peak", "m60", "m30", "flip"):
        vals = np.full(len(metrics), np.nan)
        obs_used = np.full(len(metrics), np.nan)
        for i, r in enumerate(metrics.itertuples(index=False)):
            target = getattr(r, f"target_{name}_ns")
            if target is None or pd.isna(target):
                continue
            bounds = slices.get(int(r.regime_start_ns))
            if bounds is None:
                continue
            a, b = bounds
            obs = score_obs[a:b]
            # A checkpoint observed at T contains the completed [T,T+1) 1s
            # bar and is available at T+1s, so require T+1s <= target.
            j = int(np.searchsorted(obs, int(target) - NS, side="right") - 1)
            if j >= 0:
                availability_ns = int(obs[j] + NS)
                cadence_s = 30 if int(r.year) <= 2024 else 5
                # "At target" means a current checkpoint, not the last stale
                # score from the 1,800s coverage cap.
                if int(target) - availability_ns <= cadence_s * NS:
                    vals[i] = float(score_vals[a + j])
                    obs_used[i] = int(obs[j])
        metrics[f"w4_{name}"] = vals
        metrics[f"w4_{name}_observation_ns"] = obs_used
        availability[name] = int(np.isfinite(vals).sum())
    (AUDIT / "stage1_w4_attachment.json").write_text(json.dumps({
        "metric_rows": len(metrics),
        "score_rows_valid": len(scores),
        "availability_counts": availability,
        "selection_rule": "last valid observation_time with observation_time + 1s <= target inside exact regime_start_ns",
        "score_availability": "score from observation T is actionable at T+1s; Stage 1 is descriptive only",
    }, indent=2), encoding="utf-8")
    return metrics


def main() -> None:
    t0 = time.time()
    build_causal_scores()
    reg = load_regime_population()
    all_rows: list[dict] = []
    for year in range(2021, 2026):
        rows = characterize_year(reg, year)
        all_rows.extend(rows)
        print(f"{year}: {len(rows):,} completed regimes ({time.time() - t0:.0f}s)")
    metrics = pd.DataFrame(all_rows)
    assert int(metrics["year"].max()) <= 2025, "2026 metric row crossed firewall"
    assert not (metrics["period"] == "test").any(), "test period exposed before freeze"

    # fail-fast direction parity: engine-derived regime directions must match
    # the weakness-atlas score stream on every shared regime_start_ns
    sc = pd.read_parquet(SCORE_PATH, columns=["regime_start_ns", "direction"]) \
        .drop_duplicates("regime_start_ns")
    par = metrics.merge(sc, on="regime_start_ns", how="inner",
                        suffixes=("", "_score"))
    n_mm = int((par["direction"] != par["direction_score"]).sum())
    if n_mm:
        raise SystemExit(f"FAIL-FAST: {n_mm} direction mismatches between "
                         f"engine regimes and score stream")
    print(f"Direction parity: {len(par):,}/{len(metrics):,} regimes matched "
          f"against score stream, 0 mismatches")

    metrics = attach_w4(metrics)
    metrics.to_parquet(METRICS_PATH, index=False)
    (AUDIT / "stage1_build_reconciliation.json").write_text(json.dumps({
        "source_f1_rows": int(len(reg)),
        "censored_rows": int(reg["end_censored"].sum()),
        "completed_metric_rows": int(len(metrics)),
        "duplicate_regime_ids": int(metrics["regime_id"].duplicated().sum()),
        "invalid_chronology": int((metrics["regime_end_ns"] <= metrics["regime_start_ns"]).sum()),
        "years": metrics.groupby("year").size().astype(int).to_dict(),
    }, indent=2), encoding="utf-8")
    print(f"Wrote {len(metrics):,} rows ({time.time() - t0:.0f}s total)")


if __name__ == "__main__":
    main()
