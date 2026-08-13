"""Second feasibility probe: nulls, boundaries, domain timing, memory sizing."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import polars as pl

STUDY_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = STUDY_DIR.parents[1]
BUILDER = REPO_ROOT / "studies" / "full_trade_path_builder"
CONS = BUILDER / "consolidated"
S = CONS / "canonical_trade_summaries_all.parquet"
P = CONS / "canonical_trade_paths_all.parquet"

ev = {}
s = pl.read_parquet(S)
for c in ["confirm_flip_ns", "fallback_exit_flip_ns", "atr_at_entry",
          "checkpoint_reference_price", "fallback_exit_mark_return_points",
          "seconds_entry_to_confirm", "full_trade_mfe_atr"]:
    ev[f"null__{c}"] = int(s[c].is_null().sum())
ev["atr_min"] = float(s["atr_at_entry"].min())
ev["confirm_lt_fallback"] = int((s["confirm_flip_ns"] < s["fallback_exit_flip_ns"]).sum())

p = pl.scan_parquet(P)
b = (
    p.group_by("trade_id")
    .agg(
        pl.col("is_confirm_flip_boundary").sum().alias("n_confirm"),
        pl.col("is_fallback_exit_boundary").sum().alias("n_fallback"),
        pl.len().alias("bars"),
        pl.col("running_mfe_atr").min().alias("mfe_min"),
        pl.col("path_sequence").min().alias("seq_min"),
        pl.col("path_sequence").max().alias("seq_max"),
    )
    .collect(engine="streaming")
)
ev["n_confirm_boundary_counts"] = b["n_confirm"].value_counts().sort("n_confirm").to_dicts()
ev["n_fallback_boundary_counts"] = b["n_fallback"].value_counts().sort("n_fallback").to_dicts()
ev["running_mfe_min_overall"] = float(b["mfe_min"].min())
ev["seq_min_unique"] = b["seq_min"].unique().to_list()[:5]
ev["seq_contiguous"] = int((b["seq_max"] == b["bars"]).sum())
ev["total_trades_in_paths"] = b.height
ev["bars_stats"] = {
    "sum": int(b["bars"].sum()), "max": int(b["bars"].max()),
    "median": float(b["bars"].median()), "p99": float(b["bars"].quantile(0.99)),
}

# time to first eligible in-domain opposing observation after confirmation
conf = s.select("trade_id", "trade_direction_name", "confirm_flip_ns",
                "fallback_exit_flip_ns", "entry_year").lazy()
q = (
    p.select("trade_id", "timestamp_close_ns",
             "bullish_probability", "bullish_in_domain", "bullish_is_carried_forward",
             "bearish_probability", "bearish_in_domain", "bearish_is_carried_forward")
    .join(conf, on="trade_id", how="inner")
    .with_columns(
        pl.when(pl.col("trade_direction_name") == "SHORT")
        .then(pl.col("bearish_in_domain")).otherwise(pl.col("bullish_in_domain"))
        .alias("opp_dom"),
        pl.when(pl.col("trade_direction_name") == "SHORT")
        .then(pl.col("bearish_is_carried_forward")).otherwise(pl.col("bullish_is_carried_forward"))
        .alias("opp_carried"),
        pl.when(pl.col("trade_direction_name") == "SHORT")
        .then(pl.col("bearish_probability")).otherwise(pl.col("bullish_probability"))
        .alias("opp_prob"),
    )
    .filter(pl.col("timestamp_close_ns") > pl.col("confirm_flip_ns"))
    .filter(pl.col("opp_dom") & ~pl.col("opp_carried"))
    .group_by("trade_id", "trade_direction_name", "entry_year")
    .agg(
        pl.len().alias("eligible_obs"),
        ((pl.col("timestamp_close_ns").min() - pl.col("confirm_flip_ns").min()) / 1e9)
        .alias("secs_conf_to_first_eligible"),
        pl.col("opp_prob").max().alias("max_opp_prob"),
    )
    .collect(engine="streaming")
)
ev["eligible_post_conf_trades"] = q.height
ev["eligible_obs_stats"] = {
    "median": float(q["eligible_obs"].median()),
    "p25": float(q["eligible_obs"].quantile(0.25)),
    "p75": float(q["eligible_obs"].quantile(0.75)),
    "max": int(q["eligible_obs"].max()),
}
ev["secs_conf_to_first_eligible"] = {
    "median": float(q["secs_conf_to_first_eligible"].median()),
    "p25": float(q["secs_conf_to_first_eligible"].quantile(0.25)),
    "p75": float(q["secs_conf_to_first_eligible"].quantile(0.75)),
}
ev["eligible_by_direction"] = (
    q.group_by("trade_direction_name").agg(
        pl.len().alias("trades_with_eligible"),
        pl.col("eligible_obs").median().alias("median_obs"),
        pl.col("max_opp_prob").median().alias("median_max_opp_prob"),
    ).to_dicts()
)
ev["eligible_by_year"] = (
    q.group_by("entry_year").agg(pl.len().alias("trades_with_eligible"))
    .sort("entry_year").to_dicts()
)
# threshold incidence among eligible
for name, bull_thr, bear_thr in [
    ("top_10", 0.43167249785595935, None),
    ("top_5", 0.5067081427626979, 0.5084619230529974),
    ("top_2_5", 0.5697449423968936, 0.5641320087327389),
]:
    if bear_thr is None:
        sub = q.filter(pl.col("trade_direction_name") == "LONG")
        thr = bull_thr
        ev[f"ever_above_{name}"] = {
            "scope": "LONG only (bearish top_10 not frozen)",
            "trades": sub.height,
            "ever_above": int((sub["max_opp_prob"] >= thr).sum()),
        }
    else:
        n = int(
            (q.filter(pl.col("trade_direction_name") == "LONG")["max_opp_prob"] >= bull_thr).sum()
        ) + int(
            (q.filter(pl.col("trade_direction_name") == "SHORT")["max_opp_prob"] >= bear_thr).sum()
        )
        ev[f"ever_above_{name}"] = {"scope": "both", "trades": q.height, "ever_above": n}

out = STUDY_DIR / "results" / "feasibility_probe2.json"
out.write_text(json.dumps(ev, indent=2, default=str), encoding="utf-8")
print(json.dumps(ev, indent=2, default=str))
