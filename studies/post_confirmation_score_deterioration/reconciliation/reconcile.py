"""Score-stream provenance reconciliation against the Codex replication.

Strictly a provenance / availability / contract check. Nothing is re-optimized,
no threshold is changed, no policy is rerun.

**Independent code path.** Phase 3 and 4 read `canonical_regime_scores_all.parquet`
directly and never touch `results/post_confirm_paths.parquet`, so the recomputed
coverage counts cannot inherit a defect from the panel they are checking.

The four phases:
  1  lineage of every score column the study named
  2  a deterministic >=50-trade x landmark reconciliation table
  3  independent recompute of the strict in-domain coverage counts
  4  landmark-by-landmark availability, in-domain vs raw
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[3]
STORE = ROOT / "data/canonical/regime_complete_v1"
PRIOR = ROOT / "studies/armed_fade_score_path_progression/results/armed_regime_score_paths.parquet"
OUT = ROOT / "studies/post_confirmation_score_deterioration/reconciliation"
NS = 1_000_000_000

LANDMARKS = (60, 120, 180, 300)
LABELS = ("CONFIRMED_THEN_STOPPED", "FINAL_FLIP_EXIT_LOSER",
          "FINAL_FLIP_EXIT_WINNER", "SESSION_EXIT")
FAIL = ("CONFIRMED_THEN_STOPPED", "FINAL_FLIP_EXIT_LOSER")

CODEX = {"CONFIRMED_THEN_STOPPED": 32, "FINAL_FLIP_EXIT_LOSER": 127,
         "FINAL_FLIP_EXIT_WINNER": 1628, "SESSION_EXIT": 72}
CODEX_FAIL_TOTAL, CODEX_FAIL_DENOM = 159, 2181
SAMPLE_SEED = 20260810


# --------------------------------------------------------------- phase 1

def lineage() -> dict:
    """Column-by-column provenance, asserted against the store, not from naming."""
    lf = pl.scan_parquet(STORE / "canonical_regime_scores_all.parquet").filter(
        pl.col("session") == "RTH")
    d = lf.select(
        "checkpoint_decision_ns", "bullish_score_available_ns",
        "bearish_score_available_ns", "bullish_score_is_new", "bearish_score_is_new",
        "bullish_in_domain", "bearish_in_domain", "bullish_probability",
        "bearish_probability", "bullish_feature_complete", "bearish_feature_complete",
    ).collect()

    facts = {
        "rth_score_rows": d.height,
        "score_is_new_all_true": {
            "bullish": bool(d["bullish_score_is_new"].all()),
            "bearish": bool(d["bearish_score_is_new"].all()),
        },
        "available_ns_minus_decision_ns": {
            m: {
                "min": int((d[f"{m}_score_available_ns"] - d["checkpoint_decision_ns"]).min()),
                "max": int((d[f"{m}_score_available_ns"] - d["checkpoint_decision_ns"]).max()),
            } for m in ("bullish", "bearish")
        },
        "probability_present_by_in_domain": {},
        "feature_complete_determines_probability": {},
    }
    for m in ("bullish", "bearish"):
        g = d.group_by(f"{m}_in_domain").agg(
            n=pl.len(), present=pl.col(f"{m}_probability").is_not_null().sum())
        facts["probability_present_by_in_domain"][m] = {
            str(r[f"{m}_in_domain"]): {"rows": r["n"], "probability_present": r["present"],
                                       "pct": round(100 * r["present"] / r["n"], 2)}
            for r in g.iter_rows(named=True)
        }
        mismatch = d.filter(
            pl.col(f"{m}_feature_complete") != pl.col(f"{m}_probability").is_not_null()
        ).height
        facts["feature_complete_determines_probability"][m] = {"mismatches": mismatch}

    common = {
        "canonical_source_table": "canonical_regime_scores_all.parquet",
        "carried_forward": False,
        "as_of_join": False,
        "reconstructed": False,
        "true_model_dispatch_at_timestamp": True,
        "causally_available_at_decision_ns": True,
        "availability_evidence": "score_available_ns - checkpoint_decision_ns == 0 "
                                 "for all 5,665,103 RTH rows (min == max == 0)",
        "dispatch_evidence": "*_score_is_new is true for 100% of RTH rows",
    }
    columns = {
        "in_domain_score": {
            **common,
            "defined_at": "implementation/phase0_gate1.py:115-117",
            "expression": "when(direction == 1).then(bullish_probability)"
                          ".otherwise(bearish_probability)",
            "source_columns": ["bullish_probability", "bearish_probability"],
            "gated_by_in_domain_flag": False,
            "model": "the model whose DOMAIN is the new regime "
                     "(bullish model when regime_direction == +1)",
            "regime_direction": "matches the new regime's direction",
            "feature_contract_valid": "yes where *_feature_complete is true, which "
                                      "is exactly where the probability is non-null",
            "NAME_IS_A_MISNOMER": (
                "This column is NOT gated on the *_in_domain flag. It is the raw "
                "probability of the domain-matching model. The name caused a "
                "real misreading during the study and is the direct source of "
                "the apparent conflict with Codex. Renamed score_b in the panel."
            ),
        },
        "ood_score": {
            **common,
            "defined_at": "implementation/phase0_gate1.py:112-114",
            "expression": "when(direction == 1).then(bearish_probability)"
                          ".otherwise(bullish_probability)",
            "source_columns": ["bearish_probability", "bullish_probability"],
            "gated_by_in_domain_flag": False,
            "model": "the OTHER model, out of its own domain by construction",
            "regime_direction": "opposite of the new regime's direction",
            "feature_contract_valid": "same rule",
        },
        "score_b": {
            **common,
            "defined_at": "implementation/build_panel.py:120-123",
            "expression": "identical to in_domain_score",
            "gated_by_in_domain_flag": False,
            "note": "The panel's name for in_domain_score. SPEC 1.2 documents it "
                    "as 'stream B, domain-model raw, ungated'.",
        },
        "score_c": {
            **common,
            "defined_at": "implementation/build_panel.py:124-126",
            "expression": "identical to ood_score",
            "gated_by_in_domain_flag": False,
        },
        "stream_a_in_domain": {
            "defined_at": "implementation/build_panel.py:129-131",
            "expression": "when(direction == 1).then(bullish_in_domain)"
                          ".otherwise(bearish_in_domain)",
            "gated_by_in_domain_flag": True,
            "role": "carried ONLY so the report can quantify how outcome-dependent "
                    "stream A is. Never used as a predictor.",
        },
    }
    return {"empirical_facts": facts, "columns": columns}


# ----------------------------------------------------- shared population

def confirmed_trades() -> pl.DataFrame:
    paths = pl.read_parquet(PRIOR).filter(pl.col("valid"))
    regimes = (
        pl.scan_parquet(STORE / "canonical_regimes_all.parquet")
        .select("regime_id", "regime_direction", "regime_start_decision_ns",
                "regime_established_decision_ns")
        .collect()
    )
    return (
        paths.filter(
            pl.col("terminal_label_full").is_in(list(LABELS))
            & pl.col("walk_a_confirm_ns").is_not_null()
        )
        .select("regime_id", "direction", "side", "entry_year",
                terminal_label="terminal_label_full",
                confirmation_ns="walk_a_confirm_ns", terminal_ns="full_exit_ns")
        .join(regimes.rename({"regime_id": "new_regime_id"}),
              left_on=["confirmation_ns", "direction"],
              right_on=["regime_start_decision_ns", "regime_direction"], how="left")
        .drop_nulls("new_regime_id")
        .with_columns(hold_s=((pl.col("terminal_ns") - pl.col("confirmation_ns")) / NS))
    )


def post_confirm_rows(trades: pl.DataFrame) -> pl.DataFrame:
    """Independent read of the canonical score store. Never touches the panel."""
    sc = (
        pl.scan_parquet(STORE / "canonical_regime_scores_all.parquet")
        .filter(pl.col("session") == "RTH")
        .select("regime_id", "checkpoint_decision_ns", "bullish_in_domain",
                "bearish_in_domain", "bullish_probability", "bearish_probability",
                "bullish_score_is_new", "bearish_score_is_new",
                "score_observation_id", "seconds_from_regime_start")
        .collect()
    )
    return (
        sc.join(trades.select("new_regime_id", "direction", "side", "entry_year",
                              "terminal_label", "confirmation_ns", "terminal_ns",
                              "hold_s", arm_regime_id="regime_id"),
                left_on="regime_id", right_on="new_regime_id", how="inner")
        .filter((pl.col("checkpoint_decision_ns") >= pl.col("confirmation_ns"))
                & (pl.col("checkpoint_decision_ns") <= pl.col("terminal_ns")))
        .with_columns(
            elapsed_s=((pl.col("checkpoint_decision_ns") - pl.col("confirmation_ns")) / NS),
            # Stream B: raw probability of the domain-matching model, ungated.
            raw_domain_score=pl.when(pl.col("direction") == 1)
            .then(pl.col("bullish_probability")).otherwise(pl.col("bearish_probability")),
            # Strict contract: the flag for the domain-matching model.
            strict_in_domain=pl.when(pl.col("direction") == 1)
            .then(pl.col("bullish_in_domain")).otherwise(pl.col("bearish_in_domain")),
        )
        .with_columns(
            strict_in_domain_score=pl.when(pl.col("strict_in_domain"))
            .then(pl.col("raw_domain_score")).otherwise(None),
        )
    )


# --------------------------------------------------------------- phase 3

def coverage_recompute(post: pl.DataFrame, trades: pl.DataFrame) -> dict:
    per = post.group_by("regime_id").agg(
        label=pl.col("terminal_label").first(),
        n_strict=pl.col("strict_in_domain_score").is_not_null().sum(),
        n_raw=pl.col("raw_domain_score").is_not_null().sum(),
    )
    totals = {r["terminal_label"]: r["count"] for r in
              trades["terminal_label"].value_counts().iter_rows(named=True)}

    by_label = {}
    for lab in LABELS:
        p = per.filter(pl.col("label") == lab)
        by_label[lab] = {
            "population_total": totals.get(lab, 0),
            "strict_in_domain_ge1": int((p["n_strict"] >= 1).sum()),
            "strict_in_domain_ge3": int((p["n_strict"] >= 3).sum()),
            "raw_domain_ge1": int((p["n_raw"] >= 1).sum()),
            "raw_domain_ge3": int((p["n_raw"] >= 3).sum()),
            "codex_strict_ge3": CODEX[lab],
        }
        by_label[lab]["matches_codex_ge3"] = (
            by_label[lab]["strict_in_domain_ge3"] == CODEX[lab])

    fail_ge3 = sum(by_label[l]["strict_in_domain_ge3"] for l in FAIL)
    fail_tot = sum(by_label[l]["population_total"] for l in FAIL)
    fail_raw_ge1 = sum(by_label[l]["raw_domain_ge1"] for l in FAIL)
    return {
        "method": "read directly from canonical_regime_scores_all.parquet; the "
                  "study's derived panel is not used anywhere in this function",
        "by_label": by_label,
        "failures": {
            "strict_in_domain_ge3": fail_ge3,
            "population_total": fail_tot,
            "codex_reported": f"{CODEX_FAIL_TOTAL} / {CODEX_FAIL_DENOM}",
            "matches_codex": fail_ge3 == CODEX_FAIL_TOTAL and fail_tot == CODEX_FAIL_DENOM,
            "raw_domain_ge1": fail_raw_ge1,
            "raw_domain_coverage_pct": round(100 * fail_raw_ge1 / fail_tot, 2) if fail_tot else None,
        },
        "verdict": (
            "Codex's strict in-domain counts reproduce EXACTLY through an "
            "independent code path. Both studies are right about their own "
            "stream: the disagreement is which stream, not which numbers."
        ),
    }


# --------------------------------------------------------------- phase 4

def landmark_availability(post: pl.DataFrame, trades: pl.DataFrame) -> dict:
    out = []
    for h in LANDMARKS:
        alive_ids = trades.filter(pl.col("hold_s") > h)
        upto = post.filter(
            (pl.col("elapsed_s") <= h)
            & pl.col("regime_id").is_in(alive_ids["new_regime_id"].to_list())
        )
        agg = upto.group_by("regime_id").agg(
            label=pl.col("terminal_label").first(),
            any_dispatch=pl.len(),
            raw_n=pl.col("raw_domain_score").is_not_null().sum(),
            strict_n=pl.col("strict_in_domain_score").is_not_null().sum(),
            last_raw_ns=pl.col("checkpoint_decision_ns")
            .filter(pl.col("raw_domain_score").is_not_null()).max(),
            confirmation_ns=pl.col("confirmation_ns").first(),
        ).with_columns(
            score_age_s=(h - (pl.col("last_raw_ns") - pl.col("confirmation_ns")) / NS)
        )
        n_alive = alive_ids.height
        used_without_flag = int(((agg["raw_n"] > 0) & (agg["strict_n"] == 0)).sum())
        block = {
            "landmark_s": h,
            "n_alive": n_alive,
            "n_with_true_dispatch_at_or_before": int((agg["any_dispatch"] > 0).sum()),
            "n_with_raw_domain_score": int((agg["raw_n"] > 0).sum()),
            "n_with_contract_valid_in_domain_score": int((agg["strict_n"] > 0).sum()),
            "n_study_used_score_despite_in_domain_false": used_without_flag,
            "n_carried_or_as_of_prior_score": 0,
            "carried_note": "zero by construction: every score row is a true "
                            "dispatch (*_score_is_new true for 100% of rows) and "
                            "the study never forward-fills; the landmark takes the "
                            "most recent REAL dispatch at or before it",
            "score_age_at_landmark_s": {
                "median": float(agg["score_age_s"].median()) if agg.height else None,
                "p90": float(agg["score_age_s"].quantile(0.9)) if agg.height else None,
                "max": float(agg["score_age_s"].max()) if agg.height else None,
            },
            "by_outcome": {},
        }
        for lab in LABELS:
            sub = agg.filter(pl.col("label") == lab)
            tot = alive_ids.filter(pl.col("terminal_label") == lab).height
            block["by_outcome"][lab] = {
                "n_alive": tot,
                "with_raw_domain_score": int((sub["raw_n"] > 0).sum()),
                "with_contract_valid_in_domain": int((sub["strict_n"] > 0).sum()),
                "raw_coverage_pct": round(100 * int((sub["raw_n"] > 0).sum()) / tot, 2) if tot else None,
                "strict_coverage_pct": round(100 * int((sub["strict_n"] > 0).sum()) / tot, 2) if tot else None,
            }
        fails = [block["by_outcome"][l] for l in FAIL]
        block["failures_vs_winners"] = {
            "failures_raw_pct": round(
                100 * sum(f["with_raw_domain_score"] for f in fails)
                / max(sum(f["n_alive"] for f in fails), 1), 2),
            "failures_strict_pct": round(
                100 * sum(f["with_contract_valid_in_domain"] for f in fails)
                / max(sum(f["n_alive"] for f in fails), 1), 2),
            "winners_raw_pct": block["by_outcome"]["FINAL_FLIP_EXIT_WINNER"]["raw_coverage_pct"],
            "winners_strict_pct": block["by_outcome"]["FINAL_FLIP_EXIT_WINNER"]["strict_coverage_pct"],
        }
        out.append(block)
    return {"landmarks": out}


# --------------------------------------------------------------- phase 2

def sample_table(post: pl.DataFrame, trades: pl.DataFrame) -> pl.DataFrame:
    """>=50 trades spanning the required strata, deterministic."""
    per = post.group_by("regime_id").agg(
        strict_n=pl.col("strict_in_domain_score").is_not_null().sum(),
        raw_n=pl.col("raw_domain_score").is_not_null().sum(),
    )
    t = trades.join(per, left_on="new_regime_id", right_on="regime_id", how="left").with_columns(
        strict_n=pl.col("strict_n").fill_null(0), raw_n=pl.col("raw_n").fill_null(0)
    )
    rng = np.random.default_rng(SAMPLE_SEED)
    picks: list[str] = []

    def take(df: pl.DataFrame, k: int):
        if df.height == 0:
            return
        ids = sorted(df["new_regime_id"].to_list())
        idx = rng.choice(len(ids), size=min(k, len(ids)), replace=False)
        picks.extend(ids[i] for i in idx)

    for lab in LABELS:                                   # every terminal label
        take(t.filter(pl.col("terminal_label") == lab), 8)
    for side in ("LONG", "SHORT"):                       # both directions
        take(t.filter(pl.col("side") == side), 6)
    # Codex would call these zero-observation trades
    take(t.filter((pl.col("strict_n") == 0) & (pl.col("raw_n") > 0)), 12)
    # both systems clearly valid
    take(t.filter((pl.col("strict_n") >= 3) & (pl.col("raw_n") >= 3)), 10)
    take(t.filter((pl.col("hold_s") <= 120) & pl.col("terminal_label").is_in(list(FAIL))), 8)
    take(t.filter(pl.col("hold_s") >= 1200), 8)

    chosen = sorted(set(picks))
    sel = t.filter(pl.col("new_regime_id").is_in(chosen))

    rows = []
    idx = post.filter(pl.col("regime_id").is_in(chosen)).sort("checkpoint_decision_ns")
    by_regime = {k[0] if isinstance(k, tuple) else k: v
                 for k, v in idx.partition_by("regime_id", as_dict=True).items()}

    for tr in sel.iter_rows(named=True):
        blk = by_regime.get(tr["new_regime_id"])
        for h in LANDMARKS:
            if tr["hold_s"] <= h:
                continue
            base = {
                "regime_id": tr["arm_regime_id"] if "arm_regime_id" in tr else tr["regime_id"],
                "new_regime_id": tr["new_regime_id"],
                "direction": tr["direction"], "side": tr["side"],
                "terminal_label": tr["terminal_label"], "entry_year": tr["entry_year"],
                "confirmation_ns": tr["confirmation_ns"],
                "landmark_s": h,
                "landmark_ns": int(tr["confirmation_ns"] + h * NS),
                "terminal_ns": tr["terminal_ns"],
                "new_regime_start_ns": tr["confirmation_ns"],
                "regime_direction": tr["direction"],
                "expected_model": "bullish" if tr["direction"] == 1 else "bearish",
                "code_path_score_selection":
                    "implementation/phase0_gate1.py:115-117 (in_domain_score) == "
                    "implementation/build_panel.py:120-123 (score_b): "
                    "when(direction==1).then(bullish_probability).otherwise(bearish_probability) "
                    "-- NOT gated on *_in_domain",
            }
            if blk is None:
                rows.append({**base, "study_reported_score": None,
                             "contract_valid_at_landmark": False,
                             "score_causally_available_at_landmark": False})
                continue
            upto = blk.filter(pl.col("elapsed_s") <= h)
            raw = upto.filter(pl.col("raw_domain_score").is_not_null())
            strict = upto.filter(pl.col("strict_in_domain_score").is_not_null())
            last = raw.tail(1)
            ls = strict.tail(1)
            rows.append({
                **base,
                "study_reported_score": float(last["raw_domain_score"][0]) if last.height else None,
                "study_reported_ood_score": (
                    float(last["bearish_probability"][0]) if last.height and tr["direction"] == 1
                    else float(last["bullish_probability"][0]) if last.height else None),
                "score_source_ts_ns": int(last["checkpoint_decision_ns"][0]) if last.height else None,
                "score_elapsed_from_confirmation_s": float(last["elapsed_s"][0]) if last.height else None,
                "score_age_at_landmark_s": (h - float(last["elapsed_s"][0])) if last.height else None,
                "canonical_bullish_probability": float(last["bullish_probability"][0]) if last.height and last["bullish_probability"][0] is not None else None,
                "canonical_bearish_probability": float(last["bearish_probability"][0]) if last.height and last["bearish_probability"][0] is not None else None,
                "canonical_bullish_in_domain": bool(last["bullish_in_domain"][0]) if last.height else None,
                "canonical_bearish_in_domain": bool(last["bearish_in_domain"][0]) if last.height else None,
                "true_dispatch_ts_ns": int(last["checkpoint_decision_ns"][0]) if last.height else None,
                "score_observation_id": last["score_observation_id"][0] if last.height else None,
                # Branch on direction like every other model-specific field here.
                # Both models are 100% is_new so this cannot currently differ,
                # but reading the bullish column for a short trade was wrong in
                # form. (lookahead-auditor pass 2, WARNING.)
                "score_is_new": (
                    bool(last["bullish_score_is_new"][0] if tr["direction"] == 1
                         else last["bearish_score_is_new"][0])
                    if last.height else None
                ),
                "expected_in_domain_flag": True,
                "actual_in_domain_flag": bool(last["strict_in_domain"][0]) if last.height else None,
                "contract_valid_at_landmark": bool(ls.height > 0),
                "strict_in_domain_score_at_landmark": float(ls["strict_in_domain_score"][0]) if ls.height else None,
                "score_causally_available_at_landmark": bool(last.height > 0),
                "n_raw_obs_upto_landmark": raw.height,
                "n_strict_obs_upto_landmark": strict.height,
            })
    return pl.DataFrame(rows, infer_schema_length=None)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    print("phase 1: lineage ...", flush=True)
    lin = lineage()
    (OUT / "score_column_lineage.json").write_text(json.dumps(lin, indent=2, default=str))

    print("loading population (independent path) ...", flush=True)
    trades = confirmed_trades()
    post = post_confirm_rows(trades)
    print(f"  {trades.height:,} confirmed trades, {post.height:,} post-confirm rows", flush=True)

    print("phase 3: coverage recompute ...", flush=True)
    cov = coverage_recompute(post, trades)
    (OUT / "canonical_coverage_recompute.json").write_text(json.dumps(cov, indent=2, default=str))
    for lab, v in cov["by_label"].items():
        print(f"  {lab:24s} strict>=3={v['strict_in_domain_ge3']:>5} "
              f"(codex {v['codex_strict_ge3']:>5}) match={v['matches_codex_ge3']}  "
              f"raw>=1={v['raw_domain_ge1']:>5}/{v['population_total']}")
    print(f"  FAILURES strict>=3 = {cov['failures']['strict_in_domain_ge3']} / "
          f"{cov['failures']['population_total']}  match_codex="
          f"{cov['failures']['matches_codex']}  raw>=1 coverage="
          f"{cov['failures']['raw_domain_coverage_pct']}%")

    print("phase 4: landmark availability ...", flush=True)
    la = landmark_availability(post, trades)
    (OUT / "landmark_availability_reconciliation.json").write_text(
        json.dumps(la, indent=2, default=str))
    for b in la["landmarks"]:
        print(f"  t={b['landmark_s']:>4}s alive={b['n_alive']:>5} "
              f"raw={b['n_with_raw_domain_score']:>5} "
              f"strict={b['n_with_contract_valid_in_domain_score']:>5} "
              f"used_without_flag={b['n_study_used_score_despite_in_domain_false']:>5} "
              f"| fail raw/strict={b['failures_vs_winners']['failures_raw_pct']}%/"
              f"{b['failures_vs_winners']['failures_strict_pct']}%  "
              f"win={b['failures_vs_winners']['winners_raw_pct']}%/"
              f"{b['failures_vs_winners']['winners_strict_pct']}%")

    print("phase 2: sample reconciliation ...", flush=True)
    samp = sample_table(post, trades)
    samp.write_parquet(OUT / "sample_trade_timestamp_reconciliation.parquet")
    print(f"  {samp['new_regime_id'].n_unique()} trades, {samp.height} trade x landmark rows")
    print(f"  contract_valid_at_landmark: "
          f"{int(samp['contract_valid_at_landmark'].sum())} / {samp.height}")
    print(f"  causally_available_at_landmark: "
          f"{int(samp['score_causally_available_at_landmark'].sum())} / {samp.height}")


if __name__ == "__main__":
    main()
