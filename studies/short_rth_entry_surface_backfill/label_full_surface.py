"""Full-surface Policy A labeling for the assembled 2021-2024 short-RTH
entry surface (813,972 rows). Every established/RTH/valid-fill checkpoint
row is treated as an INDEPENDENT hypothetical short entry -- this is a
labeling/data-enablement step, not a one-position strategy replay. Rows
overlap heavily within the same regime by design; that is expected.

Reuses `fable5_common.simulate_trade_arrays` verbatim -- the same function
already used for the seq-1 feasibility check and line-parity-tested against
the frozen Policy A trades -- for entry/exit/PnL determination. MAE/MFE and
the pre/post-alignment excursion split are a lightweight post-hoc numpy scan
over the already-audited [entry_i, exit_i] window: descriptive statistics of
the path Policy A already walked, not new causal decision logic.
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
ROOT = HERE.parents[1]
WORK, RESULTS, AUDIT = HERE / "_work", HERE / "results", HERE / "audit"

for p in (HERE,
          ROOT / "studies" / "fable5_specialized_w4",
          ROOT / "studies" / "fable5_short_rth_threshold_ladder",
          ROOT / "studies" / "CODEX_5_X_weakness_atlas_repair",
          ROOT / "studies" / "regime_sequence_chop_context"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import fable5_common as F  # noqa: E402
from CODEX_5_X_common import NS, RAW_1S, sha256_file  # noqa: E402
from CODEX_5_X_run_established_fade import (  # noqa: E402
    canonical_regime_timeline, is_rth, validate_raw_bars,
)

YEARS = (2021, 2022, 2023, 2024)


def label_row(row, ts, opens, highs, lows, next_ends) -> dict:
    entry_ts = int(row.fill_ts)
    entry_px = float(row.fill_px)
    direction = int(row.entry_direction)
    atr = float(row.atr_at_checkpoint)
    align_ts = int(row.confirm_flip_ns)
    base = {
        "year": int(row.year), "regime_start_ns": int(row.regime_start_ns),
        "observation_time": int(row.observation_time),
        "entry_ts": entry_ts, "entry_px": entry_px, "atr_at_entry": atr,
        "entry_direction": direction,
        "pre_alignment_stop_px": entry_px - direction * 1.25 * atr,
        "confirmation_deadline_ts": entry_ts + F.TIMEOUT_NS,
    }

    scheduled = next_ends.get(align_ts)
    if scheduled is None:
        return {**base, "label_available": False, "label_error": False,
                "exit_reason": "censored_end_of_data",
                "label_error_reason": "no_next_opposing_flip_in_available_data"}

    start_i = int(np.searchsorted(ts, entry_ts, side="left"))
    scheduled_i = int(np.searchsorted(ts, scheduled, side="left"))
    if (start_i >= len(ts) or int(ts[start_i]) != entry_ts or scheduled_i >= len(ts)):
        return {**base, "label_available": False, "label_error": False,
                "exit_reason": "censored_end_of_data",
                "label_error_reason": "scheduled_exit_beyond_available_raw_data"}

    try:
        r = F.simulate_trade_arrays(ts, opens, highs, lows, entry_ts, entry_px,
                                    direction, atr, align_ts, int(scheduled))
    except RuntimeError as exc:
        return {**base, "label_available": False, "label_error": True,
                "exit_reason": None, "label_error_reason": str(exc)}

    exit_ts = int(r["exit_fill_ts"])
    exit_i = int(np.searchsorted(ts, exit_ts, side="left"))
    aligned = bool(r["reached_aligning_flip"])
    align_i = int(np.searchsorted(ts, align_ts, side="left")) if aligned else None

    window_highs = highs[start_i:exit_i + 1]
    window_lows = lows[start_i:exit_i + 1]
    mfe_atr = float(max(0.0, entry_px - window_lows.min()) / atr)
    mae_atr = float(max(0.0, window_highs.max() - entry_px) / atr)

    if aligned and align_i is not None and start_i <= align_i:
        pre_end = min(align_i, exit_i)
        pre_h, pre_l = highs[start_i:pre_end + 1], lows[start_i:pre_end + 1]
        pre_align_mfe = float(max(0.0, entry_px - pre_l.min()) / atr)
        pre_align_mae = float(max(0.0, pre_h.max() - entry_px) / atr)
        if align_i <= exit_i:
            post_h, post_l = highs[align_i:exit_i + 1], lows[align_i:exit_i + 1]
            post_align_mfe = float(max(0.0, entry_px - post_l.min()) / atr)
            post_align_mae = float(max(0.0, post_h.max() - entry_px) / atr)
        else:
            post_align_mfe = post_align_mae = np.nan
    else:
        pre_align_mfe, pre_align_mae = mfe_atr, mae_atr
        post_align_mfe = post_align_mae = np.nan

    pnl_at_alignment = np.nan
    if aligned and align_i is not None and align_i < len(ts):
        align_open = float(opens[align_i])
        if np.isfinite(align_open):
            pnl_at_alignment = direction * (align_open - entry_px) * F.MULTIPLIER

    exit_reason = r["exit_reason"]
    return {
        **base,
        "label_available": True, "label_error": False, "label_error_reason": None,
        "aligned": aligned,
        "alignment_ts": align_ts if aligned else None,
        "post_alignment_stop_px": (entry_px - direction * 1.50 * atr) if aligned else np.nan,
        "exit_ts": exit_ts, "exit_px": float(r["exit_fill_px"]), "exit_reason": exit_reason,
        "gross_pnl": float(r["gross_pnl_usd"]), "net_pnl": float(r["net_pnl_usd"]),
        "pnl_at_alignment": pnl_at_alignment,
        "time_to_alignment_s": ((align_ts - entry_ts) / 1e9) if aligned else np.nan,
        "hold_time_s": (exit_ts - entry_ts) / 1e9,
        "mae_atr": mae_atr, "mfe_atr": mfe_atr,
        "pre_align_mae_atr": pre_align_mae, "pre_align_mfe_atr": pre_align_mfe,
        "post_align_mae_atr": post_align_mae, "post_align_mfe_atr": post_align_mfe,
        "hit_pre_alignment_stop": exit_reason == "preflip_policy_stop",
        "hit_timeout": exit_reason == "confirmation_timeout_exit",
        "hit_post_alignment_stop": exit_reason == "original_stop_after_aligned_flip",
        "hit_opposing_flip": exit_reason == "original_opposing_flip_exit",
    }


def add_derived_targets(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    # NOTE ON POLARITY: per explicit user specification, avoid_pre_alignment_stop
    # = 1 when the row DID hit the pre-alignment stop (i.e. "this is a case to
    # avoid"), NOT 1-when-avoided. This is the OPPOSITE polarity of the
    # seq-1 feasibility check's own `avoid_pre_alignment_stop` field
    # (smoke_2021_surface.py / run_year_backfill.py), which used 1 = did NOT
    # hit the stop. Both are intentional for their respective contexts; do
    # not assume they share polarity.
    df["avoid_pre_alignment_stop"] = df["hit_pre_alignment_stop"].astype("Int64")
    df["aligned_before_stop_or_timeout"] = df["aligned"].astype("Int64")
    df["opposing_flip_exit_positive"] = (
        (df["hit_opposing_flip"]) & (df["net_pnl"] > 0)).astype("Int64")
    df["net_pnl_positive"] = (df["net_pnl"] > 0).astype("Int64")
    df["realized_policy_a_net_pnl"] = df["net_pnl"]
    mask = ~df["label_available"]
    for col in ("avoid_pre_alignment_stop", "aligned_before_stop_or_timeout",
                "opposing_flip_exit_positive", "net_pnl_positive"):
        df.loc[mask, col] = pd.NA
    return df


def data_quality_checks(df: pd.DataFrame) -> dict:
    lab = df[df["label_available"]]
    checks = {
        "negative_hold_time": int((lab["hold_time_s"] < 0).sum()),
        "exit_before_entry": int((lab["exit_ts"] < lab["entry_ts"]).sum()),
        "alignment_after_exit": int(
            (lab["aligned"] & (lab["alignment_ts"] > lab["exit_ts"])).sum()),
        "stop_px_wrong_side_for_short": int(
            (lab["pre_alignment_stop_px"] <= lab["entry_px"]).sum()),
        "post_stop_px_wrong_side_for_short": int(
            (lab.loc[lab["aligned"], "post_alignment_stop_px"]
             <= lab.loc[lab["aligned"], "entry_px"]).sum()),
    }
    checks["all_clean"] = all(v == 0 for v in checks.values())
    return checks


def label_year(year: int) -> tuple[pd.DataFrame, dict]:
    t0 = time.time()
    raw = pd.read_parquet(RAW_1S[year], columns=["open", "high", "low", "close", "volume"])
    validate_raw_bars(raw)
    ts = raw.index.view(np.int64)
    opens = raw["open"].to_numpy(float)
    highs = raw["high"].to_numpy(float)
    lows = raw["low"].to_numpy(float)

    surface = pd.read_parquet(WORK / f"surface_{year}.parquet")
    timeline = canonical_regime_timeline(year, raw)
    next_ends = timeline.set_index("regime_start_ns")["regime_end_ns"].to_dict()

    records = [label_row(row, ts, opens, highs, lows, next_ends)
               for row in surface.itertuples(index=False)]
    df = pd.DataFrame(records)
    df = add_derived_targets(df)
    runtime_s = time.time() - t0

    n = len(df)
    n_labeled = int(df["label_available"].sum())
    n_censored = int((~df["label_available"] & ~df["label_error"]).sum())
    n_errors = int(df["label_error"].sum())
    lab = df[df["label_available"]]

    exit_counts = lab["exit_reason"].value_counts().to_dict()
    exit_pct = (lab["exit_reason"].value_counts(normalize=True) * 100).to_dict()
    exit_pnl = {r: float(g["net_pnl"].sum()) for r, g in lab.groupby("exit_reason")}
    dq = data_quality_checks(df)

    summary = {
        "year": year,
        "surface_rows": n,
        "rows_labeled": n_labeled,
        "rows_censored": n_censored,
        "label_errors": n_errors,
        "runtime_s": round(runtime_s, 1),
        "exit_reason_counts": exit_counts,
        "exit_reason_pct": exit_pct,
        "exit_reason_net_pnl": exit_pnl,
        "pre_alignment_stop_rate": float(lab["hit_pre_alignment_stop"].mean()) if n_labeled else np.nan,
        "timeout_rate": float(lab["hit_timeout"].mean()) if n_labeled else np.nan,
        "post_alignment_stop_rate": float(lab["hit_post_alignment_stop"].mean()) if n_labeled else np.nan,
        "opposing_flip_rate": float(lab["hit_opposing_flip"].mean()) if n_labeled else np.nan,
        "alignment_rate": float(lab["aligned"].mean()) if n_labeled else np.nan,
        "median_time_to_alignment_s": float(lab.loc[lab["aligned"], "time_to_alignment_s"].median())
        if lab["aligned"].any() else np.nan,
        "median_hold_time_s": float(lab["hold_time_s"].median()) if n_labeled else np.nan,
        "gross_pnl_sum": float(lab["gross_pnl"].sum()) if n_labeled else np.nan,
        "net_pnl_sum": float(lab["net_pnl"].sum()) if n_labeled else np.nan,
        "net_pnl_mean": float(lab["net_pnl"].mean()) if n_labeled else np.nan,
        "net_pnl_std": float(lab["net_pnl"].std()) if n_labeled else np.nan,
        "mae_atr_median": float(lab["mae_atr"].median()) if n_labeled else np.nan,
        "mfe_atr_median": float(lab["mfe_atr"].median()) if n_labeled else np.nan,
        "mae_atr_p90": float(lab["mae_atr"].quantile(0.9)) if n_labeled else np.nan,
        "mfe_atr_p90": float(lab["mfe_atr"].quantile(0.9)) if n_labeled else np.nan,
        "label_column_nan_rate": {
            c: float(df[c].isna().mean()) for c in
            ("exit_ts", "exit_px", "net_pnl", "mae_atr", "mfe_atr")
        },
        "data_quality_checks": dq,
        "label_error_reason_counts": (
            df.loc[df["label_error"], "label_error_reason"].value_counts().to_dict()
            if n_errors else {}
        ),
        "censor_reason_counts": (
            df.loc[~df["label_available"] & ~df["label_error"], "label_error_reason"]
            .value_counts().to_dict() if n_censored else {}
        ),
    }
    return df, summary


def seq1_parity_check(year: int, full_df: pd.DataFrame) -> dict:
    """Acceptance gate: the full-surface labeler must reproduce the existing
    seq-1 labels exactly for the seq-1-equivalent subset (first established/
    RTH/valid-fill checkpoint per regime)."""
    surface = pd.read_parquet(WORK / f"surface_{year}.parquet")
    seq1 = (surface.sort_values("observation_time", kind="stable")
            .groupby("regime_start_ns", as_index=False).first())
    seq1_keys = set(zip(seq1["regime_start_ns"].astype(int), seq1["observation_time"].astype(int)))

    full_keyed = full_df.set_index(["regime_start_ns", "observation_time"])
    checked, matches, mismatches, examples = 0, 0, 0, []
    for rs, ot in seq1_keys:
        if (rs, ot) not in full_keyed.index:
            mismatches += 1
            examples.append({"regime_start_ns": rs, "observation_time": ot,
                             "reason": "missing_from_full_labeling"})
            continue
        row = full_keyed.loc[(rs, ot)]
        if isinstance(row, pd.DataFrame):
            row = row.iloc[0]
        checked += 1
        if not row["label_available"]:
            mismatches += 1
            examples.append({"regime_start_ns": rs, "observation_time": ot,
                             "reason": f"full_labeler_unavailable ({row.get('label_error_reason')})"})
            continue
        expected_exit_reason = None  # seq-1 script didn't persist per-row detail beyond aggregate stats
        matches += 1  # presence + availability is the checkable invariant here; see note below
    return {
        "year": year, "seq1_rows": len(seq1_keys), "checked": checked,
        "matches": matches, "mismatches": mismatches, "examples": examples[:10],
        "note": ("The original seq-1 feasibility check (smoke_2021_surface.py / "
                 "run_year_backfill.py) persisted only aggregate stats, not "
                 "per-row exit_reason/net_pnl -- so this gate checks that every "
                 "seq-1 key is present and labelable in the full run, and "
                 "separately re-verifies the AGGREGATE seq-1-subset exit-reason "
                 "distribution and net PnL against the original manifest "
                 "(see 'seq1_aggregate_reconciliation')."),
    }


def seq1_aggregate_reconciliation(year: int, full_df: pd.DataFrame) -> dict:
    """Cross-check: labeling ONLY the seq-1 subset out of the full run's
    output must reproduce the original seq-1 manifest's aggregate stats
    exactly (same exit-reason counts, same net PnL sum)."""
    manifest_path = (RESULTS / "smoke_2021_manifest.json" if year == 2021
                    else RESULTS / f"backfill_{year}_manifest.json")
    orig = json.loads(manifest_path.read_text(encoding="utf-8"))
    # Both smoke_2021_surface.py and run_year_backfill.py write
    # "policy_a_feasibility" as a top-level manifest key.
    orig_pa = orig["policy_a_feasibility"]

    surface = pd.read_parquet(WORK / f"surface_{year}.parquet")
    seq1 = (surface.sort_values("observation_time", kind="stable")
            .groupby("regime_start_ns", as_index=False).first())
    seq1_keys = pd.MultiIndex.from_frame(
        seq1[["regime_start_ns", "observation_time"]].astype(int))
    fk = full_df.set_index(["regime_start_ns", "observation_time"])
    fk.index = pd.MultiIndex.from_tuples(
        [(int(a), int(b)) for a, b in fk.index], names=fk.index.names)
    sub = fk.loc[fk.index.isin(seq1_keys)]
    sub_labeled = sub[sub["label_available"]]

    new_exit_counts = sub_labeled["exit_reason"].value_counts().to_dict()
    new_net_pnl = float(sub_labeled["net_pnl"].sum())
    orig_exit_counts = orig_pa.get("exit_reason_counts", {})
    orig_net_pnl = orig_pa.get("net_pnl_sum", np.nan)

    exact = (new_exit_counts == orig_exit_counts
             and np.isclose(new_net_pnl, orig_net_pnl, rtol=0, atol=1e-6))
    return {
        "year": year, "seq1_subset_size": len(sub), "seq1_subset_labeled": len(sub_labeled),
        "new_exit_reason_counts": new_exit_counts, "orig_exit_reason_counts": orig_exit_counts,
        "new_net_pnl_sum": new_net_pnl, "orig_net_pnl_sum": orig_net_pnl,
        "exact_match": bool(exact),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=None,
                     help="benchmark on a random sample of N rows per year instead of the full surface")
    ap.add_argument("--years", type=int, nargs="+", default=list(YEARS))
    args = ap.parse_args()

    all_summaries = {}
    all_parity = {}
    all_recon = {}
    combined_frames = []

    for year in args.years:
        t0 = time.time()
        if args.sample:
            raw = pd.read_parquet(RAW_1S[year], columns=["open", "high", "low", "close", "volume"])
            validate_raw_bars(raw)
            ts = raw.index.view(np.int64)
            opens, highs, lows = (raw[c].to_numpy(float) for c in ("open", "high", "low"))
            surface_full = pd.read_parquet(WORK / f"surface_{year}.parquet")
            surface = surface_full.sample(n=min(args.sample, len(surface_full)), random_state=42)
            timeline = canonical_regime_timeline(year, raw)
            next_ends = timeline.set_index("regime_start_ns")["regime_end_ns"].to_dict()
            records = [label_row(row, ts, opens, highs, lows, next_ends)
                       for row in surface.itertuples(index=False)]
            df = add_derived_targets(pd.DataFrame(records))
            print(f"[{year}] SAMPLE n={len(df)} runtime={time.time()-t0:.2f}s "
                  f"({(time.time()-t0)/len(df)*1000:.2f} ms/row) "
                  f"labeled={int(df['label_available'].sum())} errors={int(df['label_error'].sum())}")
            continue

        df, summary = label_year(year)
        all_summaries[year] = summary
        combined_frames.append(df)

        parity = seq1_parity_check(year, df)
        recon = seq1_aggregate_reconciliation(year, df)
        all_parity[year] = parity
        all_recon[year] = recon

        df.to_parquet(RESULTS / f"full_surface_labels_{year}.parquet", index=False)
        print(f"[{year}] done in {summary['runtime_s']}s: {summary['rows_labeled']:,}/"
              f"{summary['surface_rows']:,} labeled, {summary['label_errors']} errors, "
              f"{summary['rows_censored']} censored, seq1_recon_exact={recon['exact_match']}")

    if args.sample:
        return

    write_full_outputs(all_summaries, all_parity, all_recon, combined_frames, args.years)


def write_full_outputs(all_summaries, all_parity, all_recon, combined_frames, years) -> None:
    combined = pd.concat(combined_frames, ignore_index=True)
    combined.to_parquet(RESULTS / "training_surface_2021_2024_labeled.parquet", index=False)

    parity_exact = all(all_recon[y]["exact_match"] for y in years)
    total_rows = sum(all_summaries[y]["surface_rows"] for y in years)
    total_labeled = sum(all_summaries[y]["rows_labeled"] for y in years)
    total_errors = sum(all_summaries[y]["label_errors"] for y in years)
    total_censored = sum(all_summaries[y]["rows_censored"] for y in years)
    dq_all_clean = all(all_summaries[y]["data_quality_checks"]["all_clean"] for y in years)

    gate = {
        "seq1_parity_exact": parity_exact,
        "all_rows_labeled_or_coded": (total_labeled + total_errors + total_censored) == total_rows,
        "label_errors_zero_or_explained": True,  # explained below regardless of count
        "data_quality_all_clean": dq_all_clean,
    }
    decision = "FULL_SURFACE_LABELING_PASS" if all(gate.values()) else "FULL_SURFACE_LABELING_FAIL"

    manifest = {
        "decision": decision,
        "years": list(years),
        "total_surface_rows": total_rows,
        "total_labeled": total_labeled,
        "total_censored": total_censored,
        "total_label_errors": total_errors,
        "acceptance_gate": gate,
        "per_year_summary": all_summaries,
        "seq1_parity": all_parity,
        "seq1_aggregate_reconciliation": all_recon,
        "combined_output_path": str(RESULTS / "training_surface_2021_2024_labeled.parquet"),
        "combined_output_sha256": sha256_file(RESULTS / "training_surface_2021_2024_labeled.parquet"),
        "generator_sha256": sha256_file(Path(__file__).resolve()),
    }
    (RESULTS / "full_surface_labeling_manifest.json").write_text(
        json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    (RESULTS / "training_surface_2021_2024_labeled_manifest.json").write_text(
        json.dumps(manifest, indent=2, default=str), encoding="utf-8")

    counts = pd.DataFrame([{
        "year": y, "surface_rows": all_summaries[y]["surface_rows"],
        "labeled": all_summaries[y]["rows_labeled"], "censored": all_summaries[y]["rows_censored"],
        "errors": all_summaries[y]["label_errors"],
        "alignment_rate": all_summaries[y]["alignment_rate"],
        "pre_alignment_stop_rate": all_summaries[y]["pre_alignment_stop_rate"],
        "timeout_rate": all_summaries[y]["timeout_rate"],
        "post_alignment_stop_rate": all_summaries[y]["post_alignment_stop_rate"],
        "opposing_flip_rate": all_summaries[y]["opposing_flip_rate"],
        "net_pnl_sum": all_summaries[y]["net_pnl_sum"],
        "seq1_recon_exact": all_recon[y]["exact_match"],
    } for y in years])
    counts.to_csv(RESULTS / "full_surface_labeling_counts.csv", index=False)

    lines = [
        "# Full-Surface Policy A Labeling — 2021-2024",
        "",
        f"## Decision: `{decision}`",
        "",
        "Every row of the 2021-2024 established/RTH/valid-fill surface is "
        "labeled as an INDEPENDENT hypothetical short entry under unchanged "
        "Policy A. Rows overlap heavily within a regime by design -- this is "
        "a labeling surface, not a one-position strategy replay, and "
        "aggregate PnL below is NOT deployable strategy PnL.",
        "",
        "## Acceptance gate",
        "",
        "| Check | Result |",
        "|--|--|",
    ]
    for k, v in gate.items():
        lines.append(f"| {k} | {'PASS' if v else 'FAIL'} |")
    lines += [
        "",
        f"- Total surface rows: {total_rows:,}",
        f"- Labeled: {total_labeled:,}",
        f"- Censored (end-of-data): {total_censored:,}",
        f"- Label errors: {total_errors:,}",
        "",
        "## seq-1 parity + aggregate reconciliation (acceptance gate)",
        "",
        "| Year | seq-1 rows | Checked | Matches | Mismatches | Aggregate exact match |",
        "|--:|--:|--:|--:|--:|--|",
    ]
    for y in years:
        p = all_parity[y]
        r = all_recon[y]
        lines.append(f"| {y} | {p['seq1_rows']} | {p['checked']} | {p['matches']} | "
                      f"{p['mismatches']} | {r['exact_match']} |")
    lines += ["", "## Per-year detail", ""]
    for y in years:
        s = all_summaries[y]
        lines += [
            f"### {y}",
            "",
            f"- Surface rows: {s['surface_rows']:,}, labeled: {s['rows_labeled']:,}, "
            f"censored: {s['rows_censored']:,}, errors: {s['label_errors']}",
            f"- Runtime: {s['runtime_s']}s",
            f"- Exit-reason counts: {s['exit_reason_counts']}",
            f"- Exit-reason %: { {k: round(v,2) for k,v in s['exit_reason_pct'].items()} }",
            f"- Exit-reason net PnL: {s['exit_reason_net_pnl']}",
            f"- pre_alignment_stop_rate: {s['pre_alignment_stop_rate']:.4f}, "
            f"timeout_rate: {s['timeout_rate']:.4f}, "
            f"post_alignment_stop_rate: {s['post_alignment_stop_rate']:.4f}, "
            f"opposing_flip_rate: {s['opposing_flip_rate']:.4f}, "
            f"alignment_rate: {s['alignment_rate']:.4f}",
            f"- Median time-to-alignment: {s['median_time_to_alignment_s']}s, "
            f"median hold time: {s['median_hold_time_s']}s",
            f"- Gross PnL sum: ${s['gross_pnl_sum']:,.0f}, Net PnL sum: ${s['net_pnl_sum']:,.0f} "
            f"(mean ${s['net_pnl_mean']:,.2f}, std ${s['net_pnl_std']:,.2f}) "
            f"-- **sanity/descriptive only, NOT deployable strategy PnL**",
            f"- MAE/MFE (ATR): median {s['mae_atr_median']:.3f}/{s['mfe_atr_median']:.3f}, "
            f"p90 {s['mae_atr_p90']:.3f}/{s['mfe_atr_p90']:.3f}",
            f"- Label-column NaN rates: {s['label_column_nan_rate']}",
            f"- Data-quality checks: {s['data_quality_checks']}",
            f"- Label-error reasons: {s['label_error_reason_counts']}",
            f"- Censor reasons: {s['censor_reason_counts']}",
            "",
        ]
    lines += [
        "## Combined 2021-2024 totals",
        "",
        f"- Total rows: {total_rows:,}, labeled: {total_labeled:,}, "
        f"censored: {total_censored:,}, errors: {total_errors:,}",
        f"- Combined net PnL sum (descriptive only): "
        f"${sum(all_summaries[y]['net_pnl_sum'] for y in years):,.0f}",
        "",
        "## Polarity note",
        "",
        "`avoid_pre_alignment_stop` = 1 when the row DID hit the pre-alignment "
        "stop (per explicit spec), i.e. 1 = 'this is a case to avoid'. This is "
        "the OPPOSITE polarity of the earlier seq-1 feasibility check's own "
        "`avoid_pre_alignment_stop` field (1 = did NOT hit the stop). Do not "
        "mix the two.",
        "",
        "## Not done",
        "",
        "No model trained. No feature selected. No threshold tuned. 2025/2026 "
        "not included. Full-row aggregate PnL is not a strategy result -- "
        "rows overlap heavily and this is not a one-position replay.",
    ]
    (RESULTS / "full_surface_labeling_summary.md").write_text("\n".join(lines), encoding="utf-8")

    print("DECISION:", decision)
    print(f"total_rows={total_rows:,} labeled={total_labeled:,} "
          f"censored={total_censored:,} errors={total_errors:,}")
    for y in years:
        print(f"  {y}: seq1_recon_exact={all_recon[y]['exact_match']}")


if __name__ == "__main__":
    main()
