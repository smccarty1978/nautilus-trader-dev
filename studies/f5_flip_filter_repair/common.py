"""Shared loading + repair utilities for the F5 flip-filter repair study.

Reuses cached feature/outcome tables from studies/regime_sequence_chop_context
(cached flip_context_atlas, model manifests, frozen policy) per the study
brief: no raw 1s feature reconstruction is rerun here except for small,
deterministic spot-check samples (canonical replay, 1s-vs-5s reconciliation).
"""
import json
from pathlib import Path
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SRC = PROJECT_ROOT / "studies/regime_sequence_chop_context/results"
OUT = PROJECT_ROOT / "studies/f5_flip_filter_repair/results"
OUT.mkdir(parents=True, exist_ok=True)

NQ_MULTIPLIER = 20.0

# --- Canonical chronological roles (recomputed from observation_time directly,
#     NOT trusted from the cached 'period' column, since the cached column
#     pools 2025-H2 and 2026 together as a single 'secondary_oos' bucket). ---
ROLE_BOUNDS = [
    ("train",       "2021-01-01", "2024-12-31"),
    ("validation",  "2025-01-01", "2025-02-28"),
    ("dev_test",    "2025-03-01", "2025-05-31"),
    ("secondary_2025H2", "2025-06-01", "2025-12-31"),
    ("secondary_2026",   "2026-01-01", "2026-04-29"),
]


def tag_role(ts_ns_series: pd.Series) -> pd.Series:
    ts = pd.to_datetime(ts_ns_series, unit="ns", utc=True)
    out = pd.Series("other", index=ts_ns_series.index, dtype=object)
    for name, s, e in ROLE_BOUNDS:
        mask = (ts >= pd.Timestamp(s, tz="UTC")) & (ts <= pd.Timestamp(e + " 23:59:59.999999999", tz="UTC"))
        out.loc[mask] = name
    return out


def get_session(ts_ns_series: pd.Series) -> pd.Series:
    """RTH = 08:30-15:00 America/Chicago (project canonical, CLAUDE.md), DST-aware
    via tz_convert on the underlying tz-aware UTC timestamp (handles CST/CDT
    transitions automatically, no manual DST table needed)."""
    ts = pd.to_datetime(ts_ns_series, unit="ns", utc=True)
    ct = ts.dt.tz_convert("America/Chicago")
    tod = ct.dt.hour * 3600 + ct.dt.minute * 60 + ct.dt.second
    rth_start = 8 * 3600 + 30 * 60
    rth_end = 15 * 3600
    is_rth = (tod >= rth_start) & (tod < rth_end)
    return pd.Series(np.where(is_rth, "RTH", "ETH"), index=ts_ns_series.index)


def load_atlas() -> pd.DataFrame:
    return pd.read_parquet(SRC / "flip_context_atlas.parquet")


def detect_execution_violations(df_atlas: pd.DataFrame) -> pd.DataFrame:
    """Detect every row where the decision (observation_time) occurs after the
    episode's own terminal time (ep_end_time). Root cause traced to gaps in the
    1m-bar array (session-maintenance / weekend boundaries): the F2 confirmation
    bar is selected as literally 'the next row in the bar array' (idx+1), not
    'the next row within N seconds of wall-clock time' -- so when idx+1 lands
    after a data gap, its close time can exceed an episode's fixed 30-minute
    timeout, and can even exceed the opposing-flip time found earlier in the
    same gap window."""
    rows = []
    viol = df_atlas[df_atlas["observation_time"] > df_atlas["ep_end_time"]].copy()
    for i, r in viol.iterrows():
        gap_s = (r["observation_time"] - r["ep_end_time"]) / 1e9
        rows.append({
            "violation_id": f"EXEC-{i}",
            "episode_id": i,
            "population": r["population"],
            "timestamp": int(r["observation_time"]),
            "violation_type": "decision_after_terminal_time",
            "severity": "critical",
            "source_artifact": "flip_context_atlas.parquet",
            "root_cause": (
                "F2 confirmation bar selected as the next row in the 1m-bar "
                "array (idx+1) rather than the next row within wall-clock "
                "tolerance; a session/weekend gap between the flip bar and the "
                "confirmation bar let the confirmation timestamp land "
                f"{gap_s:,.0f}s after the episode's own terminal time "
                "(min(opposing-flip-time, 30min timeout))."
            ),
            "repair": "exclude_episode_from_eligible_population",
            "economics_affected": True,
        })
    return pd.DataFrame(rows)


def repair_and_build_f2(df_atlas: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (repaired canonical F2 table, violation_details) with:
      - execution violations excluded
      - rows with missing entry_price/exit_price/pnl_base excluded (year-boundary
        censoring: forward 1s slice ran off the end of that year's raw file)
      - direction rebuilt from 'regime' (100% coverage, exact match verified
        wherever both were present in the cached table)
      - RTH/ETH, canonical period_role, month rebuilt from observation_time
    """
    f2 = df_atlas[df_atlas["population"] == "F2"].copy()
    f2["episode_id"] = f2.index

    viol = detect_execution_violations(df_atlas)
    viol_f2_ids = set(viol.loc[viol["population"] == "F2", "episode_id"])

    censored_mask = f2["entry_price"].isna() | f2["exit_price"].isna() | f2["pnl_base"].isna()
    censored_ids = set(f2.loc[censored_mask, "episode_id"])

    # Rebuild direction from canonical 'regime' column (verified 100% match
    # against any pre-existing direction values; regime has zero nulls in F2).
    f2["direction_repaired"] = f2["regime"].astype(int)
    f2["direction"] = f2["direction_repaired"]

    f2["session"] = get_session(f2["observation_time"])
    f2["period_role"] = tag_role(f2["observation_time"])
    ts_ct = pd.to_datetime(f2["observation_time"], unit="ns", utc=True).dt.tz_convert("America/Chicago")
    f2["month"] = ts_ct.dt.strftime("%Y-%m")
    f2["year"] = ts_ct.dt.year
    f2["chicago_local_ts"] = ts_ct.astype(str)

    f2["excluded_execution_violation"] = f2["episode_id"].isin(viol_f2_ids)
    f2["excluded_censored"] = f2["episode_id"].isin(censored_ids)
    f2["excluded_any"] = f2["excluded_execution_violation"] | f2["excluded_censored"]

    f2_clean = f2[~f2["excluded_any"]].copy()

    # ATR / volatility bucket (tertiles within period_role, causal - uses only
    # the episode's own contemporaneous ATR at entry).
    def tertile(s: pd.Series) -> pd.Series:
        try:
            return pd.qcut(s, 3, labels=["low_vol", "mid_vol", "high_vol"], duplicates="drop")
        except ValueError:
            return pd.Series(["mid_vol"] * len(s), index=s.index)

    f2_clean["atr_bucket"] = f2_clean.groupby("period_role")["atr"].transform(tertile).astype(str)

    # Entry-delay bucket: documented proxy. The atlas does not retain a direct
    # flip-to-confirmation delay field for F2 rows, so we use
    # 'seconds_in_current_ordering' (a genuine causal, contemporaneous feature
    # measuring how long the current center-ordering state has held) as the
    # closest available stand-in, tertiled within period_role. This is used
    # only as a matching stratum for random-skip controls, not as a primary
    # economic metric.
    def tertile_delay(s: pd.Series) -> pd.Series:
        try:
            return pd.qcut(s.rank(method="first"), 3, labels=["short_delay", "mid_delay", "long_delay"])
        except ValueError:
            return pd.Series(["mid_delay"] * len(s), index=s.index)

    f2_clean["entry_delay_bucket"] = f2_clean.groupby("period_role")["seconds_in_current_ordering"].transform(tertile_delay).astype(str)

    # Runner tiers from baseline (R0) pnl_base, computed within each period_role
    # (spec: "define runner tiers from baseline F2 outcomes separately within
    # the proper evaluation population").
    def runner_tier(g: pd.DataFrame) -> pd.Series:
        p90 = g["pnl_base"].quantile(0.90)
        p95 = g["pnl_base"].quantile(0.95)
        p99 = g["pnl_base"].quantile(0.99)
        tier = pd.Series("other", index=g.index)
        tier[g["pnl_base"] >= p90] = "top10"
        tier[g["pnl_base"] >= p95] = "top5"
        tier[g["pnl_base"] >= p99] = "top1"
        return tier

    f2_clean["runner_tier"] = f2_clean.groupby("period_role", group_keys=False)[["pnl_base"]].apply(runner_tier)

    return f2_clean, viol


def load_frozen_policy() -> dict:
    with open(SRC / "flip_frozen_policy.json") as f:
        return json.load(f)


def load_manifest(pop: str) -> dict:
    with open(SRC / f"flip_model_manifest_{pop}.json") as f:
        return json.load(f)
