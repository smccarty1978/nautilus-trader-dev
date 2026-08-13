"""Phase 1: the post-confirmation panel, one row per (trade, score dispatch).

Checkpointed to parquet so every later phase is a cheap query over it. This is
the only expensive step in the study.

Two conventions are load-bearing and both are frozen in SPEC 4:

* **Excursions are measured from the CONFIRMATION price**, not the arm price.
  The trade already existed before confirmation, but this study's decision point
  is confirmation, and a manager acting on post-confirmation information is
  deciding what to do with the open position from there. Arm-anchored PnL is
  emitted alongside for continuity with the predecessor study.
* **Actual dispatch timing only.** No observation is synthesized at a missing
  timestamp and no value is forward-filled into one. The panel is sparse in time
  by construction, and the 5s modal cadence has real holes.

The panel deliberately carries NO path-summary column that reads to the terminal
event. Running MFE/MAE are expanding-to-date and therefore causal at each row;
anything that would require knowing the end of the trade belongs to the target
side and is joined in only as a label.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parents[3]
STORE = ROOT / "data/canonical/regime_complete_v1"
PRIOR = ROOT / "studies/armed_fade_score_path_progression/results/armed_regime_score_paths.parquet"
OUT = ROOT / "studies/post_confirmation_score_deterioration/results"
NS = 1_000_000_000
TICK = 0.25
COST_POINTS = 2 * TICK

LABELS = ("CONFIRMED_THEN_STOPPED", "FINAL_FLIP_EXIT_LOSER",
          "FINAL_FLIP_EXIT_WINNER", "SESSION_EXIT")
FAIL = ("CONFIRMED_THEN_STOPPED", "FINAL_FLIP_EXIT_LOSER")


def confirmed_trades() -> pl.DataFrame:
    """The 4,705 confirmed armed regimes, joined to their NEW regime."""
    paths = pl.read_parquet(PRIOR).filter(pl.col("valid"))
    regimes = (
        pl.scan_parquet(STORE / "canonical_regimes_all.parquet")
        .select("regime_id", "regime_direction", "regime_start_decision_ns",
                "regime_start_price", "atr_at_regime_start",
                "regime_established_decision_ns", "established_reached",
                "regime_end_decision_ns", "duration_seconds")
        .collect()
    )
    return (
        paths.filter(
            pl.col("terminal_label_full").is_in(list(LABELS))
            & pl.col("walk_a_confirm_ns").is_not_null()
        )
        .select(
            arm_regime_id="regime_id", direction="direction", side="side",
            entry_year="entry_year", terminal_label="terminal_label_full",
            arm_ns="arm_top10_ns", arm_price="arm_price", arm_atr="arm_atr",
            confirm_ns="walk_a_confirm_ns", terminal_ns="full_exit_ns",
            full_mfe_atr="full_mfe_atr", full_mae_atr="full_mae_atr",
            full_gross_atr="full_gross_atr", full_net_atr="full_net_atr",
            arm_score="arm_score", regime_age_at_arm_s="regime_age_at_arm_s",
            session_close_ns="session_close_ns",
        )
        .join(
            regimes.rename({"regime_id": "new_regime_id"}),
            left_on=["confirm_ns", "direction"],
            right_on=["regime_start_decision_ns", "regime_direction"],
            how="left",
        )
        .drop_nulls("new_regime_id")
        .with_columns(
            confirm_price=pl.col("regime_start_price"),
            atr_at_confirmation=pl.col("atr_at_regime_start"),
            hold_s=((pl.col("terminal_ns") - pl.col("confirm_ns")) / NS),
            is_failure=pl.col("terminal_label").is_in(list(FAIL)),
        )
    )


def build() -> pl.DataFrame:
    print("loading ...", flush=True)
    trades = confirmed_trades()
    print(f"  {trades.height:,} confirmed trades", flush=True)

    scores = (
        pl.scan_parquet(STORE / "canonical_regime_scores_all.parquet")
        .filter(pl.col("session") == "RTH")
        .select("regime_id", "checkpoint_decision_ns", "checkpoint_reference_price",
                "atr_at_checkpoint", "bullish_in_domain", "bearish_in_domain",
                "bullish_probability", "bearish_probability",
                "seconds_from_regime_start")
        .collect()
    )
    print(f"  {scores.height:,} RTH score rows", flush=True)

    panel = (
        scores.join(
            trades.select(
                "new_regime_id", "arm_regime_id", "direction", "side",
                "entry_year", "terminal_label", "is_failure", "confirm_ns",
                "terminal_ns", "confirm_price", "atr_at_confirmation",
                "arm_atr", "arm_price", "hold_s", "full_mfe_atr",
                "session_close_ns",
            ),
            left_on="regime_id", right_on="new_regime_id", how="inner",
        )
        .filter(
            (pl.col("checkpoint_decision_ns") >= pl.col("confirm_ns"))
            & (pl.col("checkpoint_decision_ns") <= pl.col("terminal_ns"))
        )
        .with_columns(
            elapsed_s=((pl.col("checkpoint_decision_ns") - pl.col("confirm_ns")) / NS),
            # Stream B: the model whose domain is the NEW regime -- it predicts
            # that regime's own flip, so a RISING value is danger to us.
            score_b=pl.when(pl.col("direction") == 1)
            .then(pl.col("bullish_probability"))
            .otherwise(pl.col("bearish_probability")),
            # Stream C: the other model, exploratory.
            score_c=pl.when(pl.col("direction") == 1)
            .then(pl.col("bearish_probability"))
            .otherwise(pl.col("bullish_probability")),
            # Stream A membership, retained ONLY so the report can quantify how
            # outcome-dependent it is. Never a predictor.
            stream_a_in_domain=pl.when(pl.col("direction") == 1)
            .then(pl.col("bullish_in_domain"))
            .otherwise(pl.col("bearish_in_domain")),
        )
        .filter(pl.col("score_b").is_not_null())
        .sort(["regime_id", "checkpoint_decision_ns"])
    )

    # Excursions from the CONFIRMATION price, in the trade's direction.
    panel = panel.with_columns(
        open_pnl_points=(
            (pl.col("checkpoint_reference_price") - pl.col("confirm_price"))
            * pl.col("direction")
        )
    ).with_columns(
        open_pnl_atr_conf=(pl.col("open_pnl_points") / pl.col("atr_at_confirmation")),
        open_pnl_atr_arm=(pl.col("open_pnl_points") / pl.col("arm_atr")),
    ).with_columns(
        # Expanding-to-date, therefore causal at every row.
        run_mfe_atr=pl.max_horizontal(
            pl.col("open_pnl_atr_conf"), pl.lit(0.0)
        ).cum_max().over("regime_id"),
        run_mae_atr=pl.min_horizontal(
            pl.col("open_pnl_atr_conf"), pl.lit(0.0)
        ).cum_min().over("regime_id").abs(),
        score_b_running_max=pl.col("score_b").cum_max().over("regime_id"),
        score_b_running_min=pl.col("score_b").cum_min().over("regime_id"),
        score_b_at_confirm=pl.col("score_b").first().over("regime_id"),
        obs_index=pl.int_range(pl.len()).over("regime_id"),
    ).with_columns(
        # Escalation is the deterioration direction on stream B (SPEC 1.1).
        escalation_from_confirm=(pl.col("score_b") - pl.col("score_b_at_confirm")),
        escalation_from_min=(pl.col("score_b") - pl.col("score_b_running_min")),
        retreat_from_max=(pl.col("score_b_running_max") - pl.col("score_b")),
        giveback_atr=(pl.col("run_mfe_atr") - pl.col("open_pnl_atr_conf")),
    )

    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / "post_confirm_paths.parquet"
    panel.write_parquet(out)
    print(f"\nwrote {out.relative_to(ROOT)}  ({panel.height:,} rows, "
          f"{panel['regime_id'].n_unique():,} trades)", flush=True)

    _manifest(trades, panel)
    return panel


def _manifest(trades: pl.DataFrame, panel: pl.DataFrame) -> None:
    # Hash the analysis modules too, not just implementation/ -- the diagnostics
    # are as much a part of what produced the numbers as the panel builder is.
    # (contract-checker pass 1, hygiene note.)
    study = Path(__file__).resolve().parents[1]
    hashes = {
        f"{p.parent.name}/{p.name}": hashlib.sha256(p.read_bytes()).hexdigest()[:16]
        for p in sorted(list((study / "implementation").glob("*.py"))
                        + list((study / "analysis").glob("*.py")))
    }
    per = panel.group_by("regime_id").agg(
        label=pl.col("terminal_label").first(), n=pl.len()
    )
    recon = {
        r["terminal_label"]: r["count"]
        for r in trades["terminal_label"].value_counts().iter_rows(named=True)
    }
    manifest = {
        "study": "post_confirmation_score_deterioration",
        "substrate": "data/canonical/regime_complete_v1",
        "predecessor": "studies/armed_fade_score_path_progression",
        "confirmed_trades": trades.height,
        "population_reconciliation": recon,
        "panel_rows": panel.height,
        "panel_trades": int(panel["regime_id"].n_unique()),
        "obs_per_trade_by_label": {
            r["label"]: r["med"] for r in
            per.group_by("label").agg(med=pl.col("n").median()).iter_rows(named=True)
        },
        "primary_stream": "B (domain-model raw, ungated) -- rising = danger",
        "secondary_stream": "C (other model, exploratory)",
        "excluded_stream": "A (in-domain-flagged) -- availability determined by outcome",
        "polarity_warning": (
            "The domain model predicts the NEW regime's own flip. Deterioration "
            "for our aligned position is the score RISING, not falling. Every "
            "brief event phrased as a retreat is sign-flipped on stream B."
        ),
        "excursion_anchor": "confirmation price; ATR at confirmation (arm-anchored emitted alongside)",
        "cost_points_round_turn": COST_POINTS,
        "no_synthesized_observations": True,
        "threshold_overlap_disclosure": (
            "Both calibration populations are calendar-2025 and overlap the "
            "evaluation window; 2025 is not threshold-OOS. Canonical waiver: "
            "studies/full_trade_path_builder/THRESHOLD_OVERLAP_WAIVER.json"
        ),
        "code_hashes": hashes,
    }
    (OUT / "partition_manifest.json").write_text(json.dumps(manifest, indent=2, default=str))
    (OUT / "population_reconciliation.json").write_text(
        json.dumps({
            "derived_counts": recon,
            "brief_quoted": {"CONFIRMED_THEN_STOPPED": 822,
                             "FINAL_FLIP_EXIT_LOSER": 1359,
                             "FINAL_FLIP_EXIT_WINNER": 2350,
                             "SESSION_EXIT": 174},
            "matches": {k: recon.get(k) == v for k, v in
                        {"CONFIRMED_THEN_STOPPED": 822,
                         "FINAL_FLIP_EXIT_LOSER": 1359,
                         "FINAL_FLIP_EXIT_WINNER": 2350,
                         "SESSION_EXIT": 174}.items()},
            "note": "Derived from the predecessor event table, not assumed. "
                    "Walk A confirmed 4,656 + 49 SESSION_CLOSE_UNRESOLVED = 4,705.",
        }, indent=2, default=str)
    )


if __name__ == "__main__":
    build()
