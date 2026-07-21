"""Build the frozen-entry W4 score morphology diagnostic.

This is retrospective descriptive analysis. It does not retrain/rescore W4,
change entries, or claim causal policy performance for confirmation gates.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
STUDY = Path(__file__).resolve().parent
RESULTS = STUDY / "results"
AUDIT = STUDY / "audit"
CONFIG_PATH = STUDY / "config.json"
PRE_AUDIT = AUDIT / "pre_execution_audit.md"
PRE_AUTH = AUDIT / "pre_execution_authorization.json"
REPAIR = ROOT / "studies" / "CODEX_5_X_weakness_atlas_repair"
REPAIR_RESULTS = REPAIR / "results"
CLOCK = ROOT / "studies" / "codex_5_w4_fade_confirmation_clock"
CLOCK_RESULTS = CLOCK / "results"
NS = 1_000_000_000

import sys
sys.path.insert(0, str(REPAIR))
from CODEX_5_X_common import RAW_1S, sha256_file  # noqa: E402
from CODEX_5_X_run_established_fade import validate_raw_bars  # noqa: E402


def score_path(year: int) -> Path:
    return REPAIR_RESULTS / f"CODEX_5_X_repaired_w4_scores_{year}.parquet"


def trade_path(year: int) -> Path:
    return REPAIR_RESULTS / f"CODEX_5_X_established_fade_{year}_trades.parquet"


def script_hash() -> str:
    return sha256_file(Path(__file__).resolve())


def require_clean_audit() -> None:
    if not PRE_AUDIT.exists() or not PRE_AUTH.exists():
        raise RuntimeError("missing lookahead-auditor pre-execution authorization")
    text = PRE_AUDIT.read_text(encoding="utf-8")
    clean = (re.search(r"^\*\*Status:\*\*\s+\*\*PASS", text, re.MULTILINE)
             and re.search(r"^\*\*Findings:\*\*\s+\*\*0 CRITICAL, 0 WARNING\*\*\s*$",
                           text, re.MULTILINE))
    if not clean:
        raise RuntimeError("pre-execution audit is not a clean PASS")
    auth = json.loads(PRE_AUTH.read_text(encoding="utf-8"))
    expected = {"status": "PASS", "script_sha256": script_hash(),
                "config_sha256": sha256_file(CONFIG_PATH),
                "audit_sha256": sha256_file(PRE_AUDIT)}
    if any(auth.get(k) != v for k, v in expected.items()):
        raise RuntimeError("pre-execution audit authorization is stale")


def frozen_inputs() -> dict[str, str]:
    paths = {
        **{f"raw_{y}": RAW_1S[y] for y in (2025, 2026)},
        **{f"scores_{y}": score_path(y) for y in (2025, 2026)},
        **{f"trades_{y}": trade_path(y) for y in (2025, 2026)},
        "policy_diffs": CLOCK_RESULTS / "confirmation_clock_policy_trade_diffs.parquet",
        "path_diagnostics": CLOCK_RESULTS / "confirmation_clock_path_diagnostics.parquet",
        "repair_runner": REPAIR / "CODEX_5_X_run_established_fade.py",
        "repair_common": REPAIR / "CODEX_5_X_common.py",
        "clock_runner": CLOCK / "run_study.py",
        "clock_completion_audit": CLOCK / "audit" / "completion_audit.md",
    }
    for name, path in paths.items():
        if not path.exists():
            raise RuntimeError(f"missing frozen input: {name}: {path}")
    return {name: sha256_file(path) for name, path in paths.items()}


def load_trades() -> pd.DataFrame:
    frames = []
    for year in (2025, 2026):
        d = pd.read_parquet(trade_path(year)).sort_values("entry_fill_ts").reset_index(drop=True)
        d["trade_id"] = [f"{year}_{i:05d}" for i in range(len(d))]
        frames.append(d)
    trades = pd.concat(frames, ignore_index=True)
    if len(trades) != 4383 or trades.trade_id.nunique() != 4383:
        raise RuntimeError("repaired trade population is not the exact 4,383 unique entries")
    return trades


def add_outcomes(trades: pd.DataFrame, config: dict) -> pd.DataFrame:
    paths = pd.read_parquet(CLOCK_RESULTS / "confirmation_clock_path_diagnostics.parquet")
    diffs = pd.read_parquet(CLOCK_RESULTS / "confirmation_clock_policy_trade_diffs.parquet")
    policy = diffs[diffs.policy_id == config["policy_a_id"]].copy()
    if len(paths) != 4383 or len(policy) != 4383:
        raise RuntimeError("audited outcome inputs do not cover 4,383 trades")
    cols = ["trade_id", "time_to_aligning_flip_s", "outcome_group"]
    pcols = ["trade_id", "new_exit_reason", "new_net_pnl_usd"]
    out = trades.merge(paths[cols], on="trade_id", validate="one_to_one")
    out = out.merge(policy[pcols], on="trade_id", validate="one_to_one")
    if not out.entry_direction.isin([-1, 1]).all():
        raise RuntimeError("unexpected entry direction")
    out["trade_direction"] = np.where(out.entry_direction == 1, "long_fade", "short_fade")

    baseline_positive = out.net_pnl_usd > 0
    planned = out.exit_reason == "opposite_flip_against_countertrade"
    out["quick_winner"] = planned & baseline_positive & (out.time_to_aligning_flip_s <= 300)
    out["late_winner"] = planned & baseline_positive & (out.time_to_aligning_flip_s > 300)
    out["planned_loser"] = planned & ~baseline_positive
    out["stop_before"] = out.exit_reason == "stop_before_aligned_flip"
    out["policy_a_timeout"] = out.new_exit_reason == "confirmation_timeout_exit"
    out["policy_a_stop_after"] = out.new_exit_reason == "original_stop_after_aligned_flip"
    labels = np.select(
        [out.quick_winner, out.late_winner, out.planned_loser, out.stop_before],
        ["quick_aligning_planned_winner", "late_aligning_winner",
         "planned_exit_loser", "stop_before_aligning_flip"],
        default="other_baseline",
    )
    out["primary_baseline_group"] = labels
    return out


def load_score_windows(trades: pd.DataFrame, config: dict) -> pd.DataFrame:
    wanted = set(config["score_offsets_seconds"])
    frames = []
    for year, yt in trades.groupby("year", sort=True):
        scores = pd.read_parquet(score_path(int(year)), columns=[
            "observation_time", "regime_start_ns", "direction", "w4_score",
            "direction_threshold", "score_valid"])
        keys = yt[["trade_id", "regime_start_ns", "prevailing_direction",
                   "decision_ts", "entry_fill_ts"]]
        s = scores.merge(keys, left_on=["regime_start_ns", "direction"],
                         right_on=["regime_start_ns", "prevailing_direction"],
                         how="inner", validate="many_to_one")
        delta_ns = s.observation_time - s.decision_ts
        if (delta_ns % (5 * NS) != 0).any():
            raise RuntimeError("score observation is not on an exact 5-second trigger-relative checkpoint")
        s["offset_s"] = (delta_ns // NS).astype(int)
        s = s[s.offset_s.isin(wanted)].copy()
        s["score_margin"] = s.w4_score - s.direction_threshold
        grid = keys.loc[keys.index.repeat(len(wanted))].copy()
        grid["offset_s"] = np.tile(sorted(wanted), len(keys))
        grid["checkpoint_ts"] = grid.decision_ts + grid.offset_s * NS
        keep = ["trade_id", "offset_s", "observation_time", "w4_score",
                "direction_threshold", "score_valid", "score_margin"]
        grid = grid.merge(s[keep], on=["trade_id", "offset_s"], how="left",
                          validate="one_to_one")
        grid["flip_censored"] = grid.checkpoint_ts >= grid.trade_id.map(
            yt.set_index("trade_id").confirm_flip_ns)
        grid["administratively_censored"] = grid.checkpoint_ts > grid.regime_start_ns + 1800 * NS
        grid["score_censored"] = grid.flip_censored | grid.administratively_censored
        invalid_missing = grid.w4_score.isna() & ~grid.score_censored
        invalid_present = grid.w4_score.notna() & grid.score_censored
        if invalid_missing.any() or invalid_present.any():
            raise RuntimeError("score availability does not equal the entry-regime at-risk contract")
        frames.append(grid)
    path = pd.concat(frames, ignore_index=True)
    if not path.loc[~path.score_censored, "score_valid"].all():
        raise RuntimeError("invalid at-risk score in morphology window")
    counts = path.groupby("trade_id").offset_s.nunique()
    if len(counts) != 4383 or (counts != len(wanted)).any():
        raise RuntimeError("every trade must have every requested 5-second score checkpoint")
    entry = path[path.offset_s == 0].set_index("trade_id")
    source = trades.set_index("trade_id")
    if not np.array_equal(entry.loc[source.index, "observation_time"].to_numpy(np.int64),
                          source.decision_ts.to_numpy(np.int64)):
        raise RuntimeError("trigger checkpoint is not the stored causal decision timestamp")
    if not np.allclose(entry.loc[source.index, "w4_score"], source.w4_score, rtol=0, atol=1e-15):
        raise RuntimeError("trigger scores differ from frozen trades")
    return path


def price_features(trades: pd.DataFrame, config: dict) -> pd.DataFrame:
    rows = []
    offsets = config["price_offsets_seconds"]
    for year, group in trades.groupby("year", sort=True):
        raw = pd.read_parquet(RAW_1S[int(year)], columns=["open", "high", "low", "close", "volume"])
        validate_raw_bars(raw)
        ts = raw.index.view(np.int64)
        op, hi, lo, cl = (raw[c].to_numpy(float) for c in ("open", "high", "low", "close"))
        for t in group.itertuples(index=False):
            start = int(np.searchsorted(ts, int(t.entry_fill_ts), side="left"))
            if start >= len(ts) or int(ts[start]) != int(t.entry_fill_ts) or not np.isclose(op[start], t.entry_fill_open):
                raise RuntimeError(f"entry does not match raw open: {t.trade_id}")
            row = {"trade_id": t.trade_id}
            for sec in offsets:
                boundary = int(t.entry_fill_ts) + sec * NS
                end = int(np.searchsorted(ts, boundary, side="left"))
                if end <= start:
                    raise RuntimeError("no completed bars for price checkpoint")
                pnl = int(t.entry_direction) * (cl[end - 1] - float(t.entry_fill_open))
                fav = (hi[start:end].max() - t.entry_fill_open if t.entry_direction == 1
                       else t.entry_fill_open - lo[start:end].min())
                adv = (t.entry_fill_open - lo[start:end].min() if t.entry_direction == 1
                       else hi[start:end].max() - t.entry_fill_open)
                row[f"pnl_{sec}s_pts"] = float(pnl)
                row[f"mfe_{sec}s_pts"] = float(max(fav, 0.0))
                row[f"mae_{sec}s_pts"] = float(max(adv, 0.0))
                row[f"underwater_{sec}s"] = bool(pnl < 0)
                row[f"favorable_{sec}s"] = bool(pnl > 0)
            row["new_adverse_extreme_30s"] = bool(row["mae_30s_pts"] > 0)
            rows.append(row)
    return pd.DataFrame(rows)


def morphology_features(trades: pd.DataFrame, path: pd.DataFrame, price: pd.DataFrame) -> pd.DataFrame:
    pivot = path.pivot(index="trade_id", columns="offset_s", values="score_margin")
    rows = []
    for trade_id, g in path.groupby("trade_id", sort=False):
        g = g.sort_values("offset_s")
        pre60 = g[(g.offset_s >= -60) & (g.offset_s < 0)]
        pre120 = g[(g.offset_s >= -120) & (g.offset_s < 0)]
        post60 = g[(g.offset_s >= 0) & (g.offset_s <= 60)]
        post60_at_risk = post60[post60.w4_score.notna()]
        deltas = np.diff(pre120.score_margin.to_numpy(float))
        extrema = int(np.sum(np.diff(np.sign(deltas)) != 0)) if len(deltas) > 1 else 0
        signs = np.sign(pre120.score_margin.to_numpy(float))
        crosses = int(np.sum(signs[1:] != signs[:-1])) if len(signs) > 1 else 0
        above = post60_at_risk.score_margin.to_numpy(float) >= 0
        consecutive = 0
        for value in above:
            if not value:
                break
            consecutive += 1
        below = post60_at_risk.loc[post60_at_risk.score_margin < 0, "offset_s"]
        row = {"trade_id": trade_id,
               "overshoot": float(pivot.loc[trade_id, 0]),
               "delta_5s": float(pivot.loc[trade_id, 0] - pivot.loc[trade_id, -5]),
               "delta_10s": float(pivot.loc[trade_id, 0] - pivot.loc[trade_id, -10]),
               "delta_15s": float(pivot.loc[trade_id, 0] - pivot.loc[trade_id, -15]),
               "delta_30s": float(pivot.loc[trade_id, 0] - pivot.loc[trade_id, -30]),
               "delta_60s": float(pivot.loc[trade_id, 0] - pivot.loc[trade_id, -60]),
               "crossing_velocity_per_s": float((pivot.loc[trade_id, 0] - pivot.loc[trade_id, -5]) / 5),
               "crossing_acceleration_per_s2": float(((pivot.loc[trade_id, 0] - pivot.loc[trade_id, -5]) - (pivot.loc[trade_id, -5] - pivot.loc[trade_id, -10])) / 25),
               "pre60_within_0p05": int((pre60.score_margin.abs() <= .05).sum()),
               "pre60_within_0p10": int((pre60.score_margin.abs() <= .10).sum()),
               "pre60_just_below_seconds": int(((pre60.score_margin < 0) & (pre60.score_margin >= -.10)).sum() * 5),
               "pre60_monotonic_rising": bool((np.diff(pre60.score_margin) >= 0).all()),
               "pre60_delta_sign_changes": int(np.sum(np.diff(np.sign(np.diff(pre60.score_margin))) != 0)),
               "pre120_std": float(pre120.score_margin.std(ddof=1)),
               "pre120_range": float(pre120.score_margin.max() - pre120.score_margin.min()),
               "pre120_local_extrema": extrema, "pre120_threshold_crosses": crosses,
               "first_clean_crossing": bool(crosses == 0),
               "consecutive_checkpoints_above": consecutive,
               "first_below_s": float(below.iloc[0]) if len(below) else np.nan,
               "score_at_risk_seconds_first60": int((post60_at_risk.offset_s < 60).sum() * 5),
               "seconds_above_first60": int((post60_at_risk.loc[post60_at_risk.offset_s < 60, "score_margin"] >= 0).sum() * 5),
               "flip_censored_before_60s": bool(post60.flip_censored.any()),
               "admin_censored_before_60s": bool(post60.administratively_censored.any()),
               "post_collapse_by_60s": (bool((~above[1:]).any()) if (~above[1:]).any()
                                         else (False if len(post60_at_risk) == len(post60) else pd.NA))}
        for sec in (5, 10, 15, 30, 60):
            value = pivot.loc[trade_id, sec]
            checkpoint = post60[post60.offset_s == sec].iloc[0]
            available = bool(np.isfinite(value))
            row[f"score_available_{sec}s"] = available
            row[f"flip_censored_{sec}s"] = bool(checkpoint.flip_censored)
            row[f"admin_censored_{sec}s"] = bool(checkpoint.administratively_censored)
            row[f"margin_{sec}s"] = float(value) if available else np.nan
            # A confirmation gate rejects after a regime flip. Administrative
            # score unavailability is unevaluable and must not be called removal.
            row[f"above_{sec}s"] = (bool(value >= 0) if available
                                     else (False if checkpoint.flip_censored else pd.NA))
            row[f"delta_from_entry_{sec}s"] = float(value - pivot.loc[trade_id, 0]) if available else np.nan
            prior = post60_at_risk[(post60_at_risk.offset_s >= 0) & (post60_at_risk.offset_s < sec)].score_margin
            row[f"new_local_high_{sec}s"] = bool(value > prior.max()) if available and len(prior) else False
        prior30 = g[(g.offset_s >= -30) & (g.offset_s < 0)]
        row["near_build_gate"] = bool((prior30.score_margin.abs() <= .10).any())
        rows.append(row)
    features = trades.merge(pd.DataFrame(rows), on="trade_id", validate="one_to_one")
    return features.merge(price, on="trade_id", validate="one_to_one")


def outcome_memberships(d: pd.DataFrame) -> list[tuple[str, pd.Series]]:
    return [
        ("quick_aligning_planned_winner", d.quick_winner),
        ("late_aligning_winner", d.late_winner),
        ("planned_exit_loser", d.planned_loser),
        ("stop_before_aligning_flip", d.stop_before),
        ("policy_a_timeout_exit", d.policy_a_timeout),
        ("policy_a_stop_after_aligning_flip", d.policy_a_stop_after),
    ]


def summaries(features: pd.DataFrame, path: pd.DataFrame, config: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    groups = []
    for name, mask in outcome_memberships(features):
        ids = set(features.loc[mask, "trade_id"])
        groups.append(("outcome", name, ids))
    for col in ("year", "trade_direction", "session"):
        values = (features.year.astype(str) if col == "year" else features[col])
        for value in values.unique():
            groups.append((col, str(value), set(features.loc[values == value, "trade_id"])))
    metric_cols = ["consecutive_checkpoints_above", "crossing_velocity_per_s", "overshoot",
                   "post_collapse_by_60s", "pre60_within_0p05", "pre60_within_0p10",
                   "pre60_just_below_seconds", "pre120_std", "pre120_range",
                   "pre120_local_extrema", "pre120_threshold_crosses"]
    rows, path_rows = [], []
    for kind, label, ids in groups:
        g = features[features.trade_id.isin(ids)]
        row = {"group_type": kind, "group": label, "trade_count": len(g)}
        row["collapse_observable_count"] = int(g.post_collapse_by_60s.notna().sum())
        row["collapse_unresolved_count"] = int(g.post_collapse_by_60s.isna().sum())
        row["flip_censored_before_60s_count"] = int(g.flip_censored_before_60s.sum())
        row["admin_censored_before_60s_count"] = int(g.admin_censored_before_60s.sum())
        for col in metric_cols:
            row[f"{col}_median"] = g[col].median()
            row[f"{col}_p25"] = g[col].quantile(.25)
            row[f"{col}_p75"] = g[col].quantile(.75)
        rows.append(row)
        gp = path[path.trade_id.isin(ids) & path.offset_s.isin(config["reported_path_offsets_seconds"])]
        for offset, x in gp.groupby("offset_s"):
            path_rows.append({"group_type": kind, "group": label, "offset_s": int(offset),
                              "trade_count": x.trade_id.nunique(),
                              "score_at_risk_count": int(x.w4_score.notna().sum()),
                              "flip_censored_count": int(x.flip_censored.sum()),
                              "administratively_censored_count": int(x.administratively_censored.sum()),
                              "score_margin_p25": x.score_margin.quantile(.25),
                              "score_margin_median": x.score_margin.median(),
                              "score_margin_p75": x.score_margin.quantile(.75)})
    return pd.DataFrame(rows), pd.DataFrame(path_rows)


def gate_table(d: pd.DataFrame) -> pd.DataFrame:
    gates = {
        "GATE_1_ABOVE_AT_5S": d.above_5s,
        "GATE_2_ABOVE_AT_10S": d.above_10s,
        "GATE_4_NEAR_BUILD_PRIOR_30S": d.near_build_gate,
        "GATE_5_NONADVERSE_AT_10S": ~d.underwater_10s,
        "GATE_5_NONADVERSE_AT_30S": ~d.underwater_30s,
    }
    rows = []
    for gate, keep in gates.items():
        for subset_type, labels in [("overall", pd.Series("ALL", index=d.index)),
                                    ("year", d.year.astype(str)),
                                    ("direction", d.trade_direction), ("session", d.session)]:
            for label, idx in labels.groupby(labels).groups.items():
                g, k = d.loc[idx], keep.loc[idx]
                statuses = [("retained", k.fillna(False).astype(bool)),
                            ("removed", k.notna() & ~k.fillna(False).astype(bool)),
                            ("unevaluable", k.isna())]
                for status, mask in statuses:
                    x = g[mask]
                    rows.append({"gate": gate, "subset_type": subset_type, "subset": str(label),
                                 "status": status, "trade_count": len(x),
                                 "baseline_net_pnl_usd": x.net_pnl_usd.sum(),
                                 "baseline_winners": int((x.net_pnl_usd > 0).sum()),
                                 "quick_winners": int(x.quick_winner.sum()),
                                 "stop_before_losses": int(x.stop_before.sum()),
                                 "planned_losers": int(x.planned_loser.sum())})
    return pd.DataFrame(rows)


def effect_table(d: pd.DataFrame) -> pd.DataFrame:
    pairs = [("quick_vs_stop_before", d.quick_winner, d.stop_before),
             ("quick_vs_policy_a_timeout", d.quick_winner, d.policy_a_timeout),
             ("quick_vs_planned_loser", d.quick_winner, d.planned_loser),
             ("short_vs_long", d.trade_direction == "short_fade", d.trade_direction == "long_fade"),
             ("RTH_vs_ETH", d.session == "RTH", d.session == "ETH")]
    metrics = ["seconds_above_first60", "delta_5s", "crossing_velocity_per_s", "overshoot",
               "pre60_within_0p10", "pre120_threshold_crosses", "post_collapse_by_60s",
               "pnl_10s_pts", "pnl_30s_pts", "pnl_60s_pts", "mae_30s_pts", "mfe_60s_pts"]
    rows = []
    for pair, ma, mb in pairs:
        for label, mask in [("A", ma), ("B", mb)]:
            x = d[mask]
            for metric in metrics:
                rows.append({"comparison": pair, "side": label, "metric": metric,
                             "trade_count": len(x), "mean": x[metric].mean(),
                             "median": x[metric].median(), "p25": x[metric].quantile(.25),
                             "p75": x[metric].quantile(.75)})
    return pd.DataFrame(rows)


def report(d: pd.DataFrame, summary: pd.DataFrame, gates: pd.DataFrame) -> str:
    def med(mask, col): return float(d.loc[mask, col].median())
    def rate(mask, col):
        x = d.loc[mask, col].dropna().astype(bool)
        return float(x.mean()) if len(x) else np.nan
    quick, stop, planned, timeout = d.quick_winner, d.stop_before, d.planned_loser, d.policy_a_timeout
    quick_observable = int(d.loc[quick, "post_collapse_by_60s"].notna().sum())
    stop_observable = int(d.loc[stop, "post_collapse_by_60s"].notna().sum())
    yearly = []
    for year in (2025, 2026):
        y = d.year == year
        yearly.append(f"| {year} | {int((quick & y).sum())} | {med(quick & y, 'seconds_above_first60'):.1f} | {med(stop & y, 'seconds_above_first60'):.1f} | {med(quick & y, 'delta_5s'):.4f} | {med(stop & y, 'delta_5s'):.4f} |")
    overall_gates = gates[(gates.subset_type == "overall") & (gates.status == "retained")]
    gate_lines = [f"| {r.gate} | {int(r.trade_count)} | ${r.baseline_net_pnl_usd:,.2f} | {int(r.quick_winners)} | {int(r.stop_before_losses)} | {int(r.planned_losers)} |" for r in overall_gates.itertuples()]
    price_gap = med(quick, "pnl_30s_pts") - med(stop, "pnl_30s_pts")
    label = "NO_ENTRY_MORPHOLOGY_EDGE_VISIBLE"
    if price_gap > 0 and d.loc[stop, "underwater_30s"].mean() - d.loc[quick, "underwater_30s"].mean() >= .10:
        label = "PRICE_RESPONSE_CONFIRMATION_PROMISING"
    return f"""# W4 Entry Threshold Morphology Diagnostic - Final Report

## Scope and contract

This is retrospective descriptive analysis of the exact repaired **4,383** W4 fade entries. W4 was not retrained or rescored. Entry membership, fills, thresholds, baseline exits, and audited Policy A outcomes remain frozen. Score time zero is the causal 5-second trigger observation; price time zero is the next available 1-second entry-fill open. Post-entry price checkpoints use only completed 1-second bars.

The frozen W4 score exists only while the entry's prevailing regime remains active and only through the atlas's 30-minute regime-age horizon. Checkpoints at or after the aligning flip are flip-censored rather than filled with successor-regime scores; checkpoints beyond 30 minutes are administratively censored. Score-path tables include at-risk and both censor-cause counts at every offset. Confirmation gates treat a regime ending before confirmation as rejection, while administratively unavailable checkpoints are unevaluable. Persistence comparisons are descriptive competing-event summaries and do not drive the decision label.

Candidate confirmation tables below are selection diagnostics on the original entries and original PnL. They are **not causal policy results** because confirmation would delay fills.

## Main answers

1. **Persistence while at risk:** quick winners' median observed first-60s above-threshold time was **{med(quick, 'seconds_above_first60'):.1f}s**, versus **{med(stop, 'seconds_above_first60'):.1f}s** for stop-before losses, **{med(timeout, 'seconds_above_first60'):.1f}s** for Policy A timeouts, and **{med(planned, 'seconds_above_first60'):.1f}s** for planned losers. These durations end at an aligning flip and must be read with the at-risk counts, not as uncensored survival estimates.
2. **Spike-through:** median 5-second crossing delta was **{med(quick, 'delta_5s'):.4f}** for quick winners versus **{med(stop, 'delta_5s'):.4f}** for stop-before losses. The full distributions are in `comparison_tables.parquet`; no data-selected spike cutoff was created.
3. **Near-threshold build:** quick winners had a median **{med(quick, 'pre60_within_0p10'):.1f}** prior checkpoints within 0.10 of threshold versus **{med(stop, 'pre60_within_0p10'):.1f}** for stop-before losses.
4. **Immediate collapse among observable paths:** collapse by +60s occurred in **{rate(quick, 'post_collapse_by_60s'):.1%}** of **{quick_observable}** observable quick-winner paths versus **{rate(stop, 'post_collapse_by_60s'):.1%}** of **{stop_observable}** observable stop-before-loss paths. Censored-without-collapse paths are excluded rather than counted as non-collapses; full observable/unresolved and censor-cause counts are in the group summary.
5. **Immediate price response:** median directional PnL at +30s was **{med(quick, 'pnl_30s_pts'):.2f} points** for quick winners versus **{med(stop, 'pnl_30s_pts'):.2f} points** for stop-before losses; underwater rates were **{d.loc[quick, 'underwater_30s'].mean():.1%}** and **{d.loc[stop, 'underwater_30s'].mean():.1%}**, respectively.
6. **Replay candidates:** only gates showing meaningful descriptive separation should advance, and every such gate requires a separate delayed-entry replay at the first available 1-second open after confirmation.
7. **Year stability:**

| Year | Quick winners | Quick persistence median | Stop-before persistence median | Quick delta-5s median | Stop delta-5s median |
|---:|---:|---:|---:|---:|---:|
{chr(10).join(yearly)}

## Fixed descriptive gate retention

| Gate | Retained trades | Retained baseline net PnL | Retained quick winners | Retained stop-before losses | Retained planned losers |
|---|---:|---:|---:|---:|---:|
{chr(10).join(gate_lines)}

Administrative-unavailable gate cases are emitted with status `unevaluable` and are excluded from retained/removed counts. Gate 3 is intentionally distribution-only: the specification forbids freezing a numeric spike threshold before inspecting distributions. No optimized threshold or performance claim was created.

## Decision

`{label}`

This label nominates a hypothesis for causal delayed-entry replay; it does not amend Policy A or establish executable performance.

## Reproducible artifacts

- `trade_morphology_features.parquet`: one row per frozen trade.
- `score_paths.parquet`: exact requested score checkpoints.
- `group_morphology_summary.parquet`: morphology distributions by outcome/year/direction/session.
- `group_score_paths.parquet`: median and p25/p75 score-margin paths.
- `comparison_tables.parquet`: the five required compact comparisons.
- `candidate_gate_retention.parquet`: retained/removed baseline outcome accounting and splits.
- `run_manifest.json`: configuration, hashes, row counts, and decision label.
"""


def main() -> None:
    require_clean_audit()
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    input_hashes = frozen_inputs()
    trades = add_outcomes(load_trades(), config)
    path = load_score_windows(trades, config)
    price = price_features(trades, config)
    features = morphology_features(trades, path, price)
    summary, group_paths = summaries(features, path, config)
    gates = gate_table(features)
    comparisons = effect_table(features)
    text = report(features, summary, gates)
    RESULTS.mkdir(parents=True, exist_ok=True)
    outputs = {
        "trade_morphology_features.parquet": features,
        "score_paths.parquet": path,
        "group_morphology_summary.parquet": summary,
        "group_score_paths.parquet": group_paths,
        "comparison_tables.parquet": comparisons,
        "candidate_gate_retention.parquet": gates,
    }
    for name, frame in outputs.items():
        frame.to_parquet(RESULTS / name, index=False)
    (RESULTS / "final_report.md").write_text(text, encoding="utf-8")
    match = re.search(r"`([A-Z_]+)`\n\nThis label", text)
    manifest = {"status": "DIAGNOSTIC_OUTPUTS_COMPLETE_PENDING_COMPLETION_AUDIT",
                "study_id": config["study_id"], "trade_count": len(features),
                "score_path_rows": len(path), "decision_label": match.group(1),
                "config_sha256": sha256_file(CONFIG_PATH), "script_sha256": script_hash(),
                "pre_execution_audit_sha256": sha256_file(PRE_AUDIT),
                "input_sha256": input_hashes,
                "output_sha256": {name: sha256_file(RESULTS / name) for name in [*outputs, "final_report.md"]}}
    (RESULTS / "run_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"trades": len(features), "score_rows": len(path),
                      "decision": manifest["decision_label"]}, indent=2))


if __name__ == "__main__":
    main()
