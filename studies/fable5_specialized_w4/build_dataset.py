"""Build the specialized-W4 candidate dataset with per-candidate Policy A labels.

Every generated strict-crossing candidate is replayed INDEPENDENTLY from its
immediate causal fill under the frozen Policy A management contract. The
sequence-1 candidates restricted to the frozen executable regime set must
reproduce the frozen Policy A trades exactly before any training happens.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

import fable5_common as C


def load_candidates(year: int) -> pd.DataFrame:
    d = pd.read_parquet(C.candidate_path(year))
    if len(d) != C.YEAR_COUNTS["candidates"][year]:
        raise RuntimeError(f"candidate cardinality changed for {year}")
    if int(d.opportunity_id.nunique()) != C.YEAR_COUNTS["opportunities"][year]:
        raise RuntimeError(f"opportunity cardinality changed for {year}")
    if d[["opportunity_id", "candidate_seq"]].duplicated().any():
        raise RuntimeError("duplicate candidate sequence")
    return d.sort_values(["candidate_time", "candidate_seq"]).reset_index(drop=True)


def join_features(year: int, candidates: pd.DataFrame) -> pd.DataFrame:
    cols = list(dict.fromkeys(
        ["observation_time", "regime_start_ns", "direction"] + C.ATLAS_FEATURES))
    atlas = pd.read_parquet(C.year_atlas_path(year), columns=cols)
    atlas = atlas.rename(columns={"direction": "atlas_direction"})
    out = candidates.merge(
        atlas, how="left",
        left_on=["regime_start_ns", "candidate_time"],
        right_on=["regime_start_ns", "observation_time"],
        validate="one_to_one")
    if out["observation_time"].isna().any():
        raise RuntimeError("candidate lacks matching atlas checkpoint row")
    if (out["atlas_direction"].astype(int)
            != out["prevailing_direction"].astype(int)).any():
        raise RuntimeError("atlas/candidate prevailing-direction mismatch")
    # regime_age (atlas seconds) must agree with the frozen candidate field.
    if not np.allclose(out["regime_age"], out["regime_age_s"], rtol=0, atol=1e-9):
        raise RuntimeError("atlas/candidate regime_age mismatch")
    if not np.allclose(out["current_mfe"], out["running_mfe_atr"], rtol=0, atol=1e-9):
        raise RuntimeError("atlas/candidate running MFE mismatch")
    out["direction_flag"] = np.where(out["direction"] == "long_fade", 1.0, -1.0)
    out["session_flag"] = np.where(out["session"] == "RTH", 1.0, 0.0)
    return out.drop(columns=["observation_time", "atlas_direction"])


def replay_labels(year: int, d: pd.DataFrame, raw: pd.DataFrame) -> pd.DataFrame:
    from CODEX_5_X_run_established_fade import canonical_regime_timeline
    timeline = canonical_regime_timeline(year, raw)
    next_ends = timeline.set_index("regime_start_ns")["regime_end_ns"].to_dict()
    ts, opens, highs, lows = C.raw_arrays(raw)
    # Typed sentinels for non-replayable rows: nanosecond timestamps must
    # never pass through float64 (values ~1.7e18 exceed the exact-integer
    # range), so ts fields use pd.NA and become nullable Int64 below.
    empty = {"entry_fill_ts": pd.NA, "entry_fill_px": np.nan,
             "timeout_ts": pd.NA, "reached_aligning_flip": False,
             "exit_fill_ts": pd.NA, "exit_fill_px": np.nan, "exit_reason": "",
             "gross_pnl_pts": np.nan, "gross_pnl_usd": np.nan,
             "net_pnl_usd": np.nan}
    records = []
    for c in d.itertuples(index=False):
        fill_ts = c.candidate_fill_time
        if fill_ts is None or pd.isna(fill_ts):
            records.append({**empty, "replayable": False,
                            "not_replayable_reason": "missing_fill"})
            continue
        fill_ts = int(fill_ts)
        align_ts = int(c.confirm_flip_ns)
        if fill_ts >= align_ts:
            records.append({**empty, "replayable": False,
                            "not_replayable_reason": "aligning_flip_at_or_before_fill"})
            continue
        scheduled = next_ends.get(align_ts)
        if scheduled is None:
            raise RuntimeError(f"confirming regime lacks opposing flip: {c.candidate_id}")
        result = C.simulate_trade_arrays(
            ts, opens, highs, lows, fill_ts, float(c.candidate_fill_price),
            int(c.entry_direction), float(c.atr_at_checkpoint), align_ts,
            int(scheduled))
        records.append({"replayable": True, "not_replayable_reason": "", **result})
    labels = pd.DataFrame(records, index=d.index)
    # Nanosecond timestamps must never pass through float64 (values ~1.7e18
    # exceed the exact-integer range); keep them as nullable Int64 end to end.
    for column in ("entry_fill_ts", "exit_fill_ts", "timeout_ts"):
        labels[column] = pd.array(
            [pd.NA if pd.isna(v) else int(v) for v in labels[column]],
            dtype="Int64")
    out = pd.concat([d, labels], axis=1)
    replayable = out["replayable"].to_numpy(bool)
    out["net_pnl_atr"] = np.where(
        replayable, out["gross_pnl_pts"] / out["atr_at_checkpoint"], np.nan)
    out["label_net_positive"] = np.where(
        replayable, (out["net_pnl_usd"] > 0).astype(float), np.nan)
    out["label_alignment_5m"] = np.where(
        replayable, out["reached_aligning_flip"].astype(float), np.nan)
    out["label_avoids_prestop"] = np.where(
        replayable, (out["exit_reason"] != "preflip_policy_stop").astype(float),
        np.nan)
    return out


def reconcile_policy_a(year: int, d: pd.DataFrame) -> dict:
    """Seq-1 candidates on the frozen executable set must equal Policy A."""
    frozen = pd.read_parquet(C.frozen_trade_path(year)).sort_values(
        "entry_fill_ts").reset_index(drop=True)
    prior = pd.read_parquet(C.ISOLATION / "results" / "isolation_trade_diffs.parquet")
    prior = prior[(prior.policy_id == C.POLICY_A_ID) & (prior.year == year)]
    prior = prior.sort_values("entry_fill_ts").reset_index(drop=True)
    allowed = set(frozen.regime_start_ns.astype(np.int64))
    mine = d[(d.candidate_seq == 1) & d.regime_start_ns.isin(allowed)]
    mine = mine.sort_values("candidate_fill_time").reset_index(drop=True)
    expected = C.YEAR_COUNTS["policy_a_trades"][year]
    if not (len(mine) == len(frozen) == len(prior) == expected):
        raise RuntimeError("frozen Policy A cardinality mismatch")
    if not mine.replayable.all():
        raise RuntimeError("frozen executable candidate not replayable")
    mismatches = 0
    mismatches += int((mine.candidate_fill_time.to_numpy(np.int64)
                       != prior.entry_fill_ts.to_numpy(np.int64)).sum())
    mismatches += int((mine.exit_fill_ts.to_numpy(np.int64)
                       != prior.new_exit_fill_ts.to_numpy(np.int64)).sum())
    mismatches += int((~np.isclose(mine.exit_fill_px, prior.new_exit_fill_px,
                                   rtol=0, atol=1e-12)).sum())
    mismatches += int((mine.exit_reason.to_numpy()
                       != prior.new_exit_reason.to_numpy()).sum())
    mismatches += int((~np.isclose(mine.net_pnl_usd, prior.new_net_pnl_usd,
                                   rtol=0, atol=1e-8)).sum())
    mismatches += int((~np.isclose(mine.candidate_fill_price,
                                   frozen.entry_fill_open, rtol=0, atol=1e-12)).sum())
    mismatches += int((mine.entry_direction.to_numpy(int)
                       != frozen.entry_direction.to_numpy(int)).sum())
    mismatches += int((mine.session.to_numpy() != frozen.session.to_numpy()).sum())
    if mismatches:
        raise RuntimeError(f"Policy A reconciliation mismatch: {mismatches}")
    return {"frozen_trades": len(frozen), "matched": len(mine), "mismatches": 0,
            "policy_a_total_net_pnl_usd": float(prior.new_net_pnl_usd.sum()),
            "replayed_total_net_pnl_usd": float(mine.net_pnl_usd.sum())}


def assign_windows(year: int, d: pd.DataFrame) -> pd.DataFrame:
    if year == 2026:
        d["window"] = "2026_test"
        d["purged_from_train"] = False
        return d
    h1 = d.candidate_time < C.BOUNDARY_NS
    d["window"] = np.where(h1, "2025_H1_train", "2025_H2_dev")
    exit_ts = pd.array(d.exit_fill_ts, dtype="Int64")
    crosses = ((pd.Series(exit_ts, index=d.index).fillna(0).astype(np.int64)
                >= C.BOUNDARY_NS)
               | (d.opportunity_end_ts.astype(np.int64) >= C.BOUNDARY_NS))
    d["purged_from_train"] = h1 & crosses
    return d


def audit_rows(year: int, d: pd.DataFrame, reconciliation: dict) -> pd.DataFrame:
    rows = [{"year": year, "measure": "candidates", "value": float(len(d))},
            {"year": year, "measure": "opportunities",
             "value": float(d.opportunity_id.nunique())},
            {"year": year, "measure": "replayable",
             "value": float(d.replayable.sum())},
            {"year": year, "measure": "not_replayable_missing_fill",
             "value": float((d.not_replayable_reason == "missing_fill").sum())},
            {"year": year, "measure": "not_replayable_fill_after_flip",
             "value": float((d.not_replayable_reason
                             == "aligning_flip_at_or_before_fill").sum())},
            {"year": year, "measure": "purged_from_train",
             "value": float(d.purged_from_train.sum())},
            {"year": year, "measure": "feature_nan_rate",
             "value": float(d[C.RAW_FEATURES].isna().to_numpy().mean())}]
    for key, value in reconciliation.items():
        rows.append({"year": year, "measure": f"reconciliation_{key}",
                     "value": float(value)})
    for (direction, session), g in d[d.replayable].groupby(["direction", "session"]):
        rows.append({"year": year,
                     "measure": f"replayable_{direction}_{session}",
                     "value": float(len(g))})
        rows.append({"year": year,
                     "measure": f"net_positive_rate_{direction}_{session}",
                     "value": float(g.label_net_positive.mean())})
        rows.append({"year": year,
                     "measure": f"mean_net_pnl_usd_{direction}_{session}",
                     "value": float(g.net_pnl_usd.mean())})
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, choices=(2025, 2026), required=True)
    args = parser.parse_args()
    C.ensure_dirs()
    C.require_authorization()
    C.freeze_inputs_or_verify()
    if args.year == 2026:
        C.require_2026_open_allowed("build 2026 candidate dataset")
        if not C.dataset_path(2025).exists():
            raise RuntimeError("2025 dataset must exist before 2026")
    candidates = load_candidates(args.year)
    featured = join_features(args.year, candidates)
    raw = C.load_raw(args.year)
    labeled = replay_labels(args.year, featured, raw)
    reconciliation = reconcile_policy_a(args.year, labeled)
    final = assign_windows(args.year, labeled)
    for column in ("entry_fill_ts", "exit_fill_ts", "timeout_ts",
                   "candidate_fill_time"):
        final[column] = pd.array(final[column], dtype="Int64")
    final.to_parquet(C.dataset_path(args.year), index=False)
    audit = audit_rows(args.year, final, reconciliation)
    audit.to_parquet(C.WORK / f"dataset_audit_{args.year}.parquet", index=False)
    seal = {"year": args.year, "rows": len(final),
            "replayable": int(final.replayable.sum()),
            "reconciliation": reconciliation,
            "dataset_sha256": C.sha256_file(C.dataset_path(args.year))}
    (C.WORK / f"dataset_seal_{args.year}.json").write_text(
        json.dumps(seal, indent=2), encoding="utf-8")
    print(json.dumps(seal, indent=2))


if __name__ == "__main__":
    main()
