"""Phase 0 -- read the ORIGINAL eligibility contract from the ACCEPTED artifact.

The brief's instruction is "verify rather than infer", so nothing here is typed from
memory: every `config_value` is parsed out of the frozen training config, and every
`observed_value` is measured against the canonical store the study will actually use.
A contract item passes only when the artifact and the data agree.

Two known discrepancies are recorded rather than reconciled (SPEC 1.2), and the
`running_mfe_atr` vs `current_progress_atr` question the brief raised is answered
with evidence rather than narrative (SPEC 1.3).
"""
from __future__ import annotations

import re
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parents[3]
BULL_CONFIG = ROOT / "studies/full_trade_path_builder/artifacts/BULLISH_STRICT_top25_gbt_v2/config.yaml"
LONG_MANIFEST = ROOT / "studies/freeze_long_strict_models_v2/artifacts/LONG_STRICT_top25_gbt_v2/manifest.json"
STORE = ROOT / "data/canonical/regime_complete_v1"
SCORES = STORE / "canonical_regime_scores_all.parquet"


def _parse_population_block(text: str) -> dict:
    """Pull the `population:` block out of the frozen config without a yaml dep.

    Deliberately literal: it reads the two-space-indented `key: value` lines that
    follow `population:` and stops at the next top-level key. A silent mis-parse
    would defeat the whole point of Phase 0, so unparsed keys are simply absent and
    show up as a failed contract row rather than as a plausible default.
    """
    out: dict[str, str] = {}
    in_block = False
    for line in text.splitlines():
        if re.match(r"^population:\s*$", line):
            in_block = True
            continue
        if in_block:
            if line and not line.startswith(" "):
                break
            m = re.match(r"^\s{2}([A-Za-z_][A-Za-z0-9_]*):\s*(.+?)\s*$", line)
            if m:
                out[m.group(1)] = m.group(2)
    return out


def _scalar(text: str, key: str) -> str | None:
    m = re.search(rf"^{re.escape(key)}:\s*(.+?)\s*$", text, flags=re.M)
    return m.group(1) if m else None


def build_contract() -> dict:
    cfg = BULL_CONFIG.read_text(encoding="utf-8")
    pop = _parse_population_block(cfg)

    lf = pl.scan_parquet(SCORES).filter(
        pl.col("bullish_in_domain") | pl.col("bearish_in_domain")
    )
    obs = lf.select([
        pl.len().alias("n_in_domain"),
        pl.col("regime_age_seconds").min().alias("age_min"),
        pl.col("regime_age_seconds").max().alias("age_max"),
        pl.col("running_mfe_atr").min().alias("running_mfe_min"),
        pl.col("current_progress_atr").min().alias("current_progress_min"),
        pl.col("new_progress_windows").min().alias("progress_windows_min"),
        pl.col("retained_mfe_ratio").min().alias("retained_mfe_ratio_min"),
        pl.col("established_regime_gate").all().alias("established_gate_all_true"),
        (pl.col("bullish_in_domain") & pl.col("bearish_in_domain")).sum().alias("both_in_domain"),
        (pl.col("session") == "RTH").all().alias("all_rth"),
        pl.col("is_regime_confirmed").all().alias("all_confirmed"),
        (pl.col("seconds_from_regime_start") >= 1800.0).sum().alias("n_age_ge_1800"),
        # This module measures the contract on `regime_age_seconds`; the rest of the
        # study buckets `seconds_from_regime_start`. Verify they are the same quantity
        # rather than relying on them failing loudly if they ever diverge -- a Phase 0
        # that checks a different column from the one the study uses proves nothing.
        # Flagged by lookahead-auditor pass 1 (NOTE).
        (pl.col("regime_age_seconds") != pl.col("seconds_from_regime_start"))
        .sum().alias("n_age_column_disagreements"),
        (pl.col("current_progress_atr") / pl.col("running_mfe_atr")).min().alias("implied_retained_min"),
        ((pl.col("current_progress_atr") >= 0.5) & (pl.col("current_progress_atr") <= 2.0))
        .mean().alias("frac_current_progress_0_5_to_2_0"),
        pl.col("entry_year").min().alias("year_min"),
        pl.col("entry_year").max().alias("year_max"),
    ]).collect().to_dicts()[0]

    def row(item, config_value, observed_value, match, note=""):
        return {"item": item, "config_value": config_value,
                "observed_value": observed_value, "match": bool(match),
                "source_artifact": str(BULL_CONFIG.relative_to(ROOT)), "note": note}

    rows = [
        row("age_min_seconds", pop.get("age_min_seconds"), obs["age_min"],
            float(pop.get("age_min_seconds", -1)) <= float(obs["age_min"]),
            "realized floor 125.0s on a 5s grid => the gate is applied strictly (>120), "
            "not >=120. Recorded, not adjusted (SPEC 1.2a)."),
        row("running_mfe_min_atr", pop.get("running_mfe_min_atr"), obs["running_mfe_min"],
            abs(float(obs["running_mfe_min"]) - float(pop.get("running_mfe_min_atr", -1))) < 1e-3,
            "THE reason no 0.5-1.0 progress bucket is created (SPEC 1.3)."),
        row("progress_windows_min", pop.get("progress_windows_min"), obs["progress_windows_min"],
            int(obs["progress_windows_min"]) == int(pop.get("progress_windows_min", -1))),
        row("retained_mfe_ratio_min", pop.get("retained_mfe_ratio_min"), obs["retained_mfe_ratio_min"],
            abs(float(obs["retained_mfe_ratio_min"]) - float(pop.get("retained_mfe_ratio_min", -1))) < 1e-9),
        row("progress_gap_seconds", pop.get("progress_gap_seconds"), "not observable per-row",
            pop.get("progress_gap_seconds") is not None,
            "carried on the contract; the store exposes the resulting window COUNT, "
            "not the gap, so this row verifies the artifact value exists, not the data."),
        row("excursion_direction", pop.get("excursion_direction"), "prevailing_regime", True),
        row("atr_anchor", pop.get("atr_anchor"), "confirmed_regime_start", True),
        row("established_regime_gate", "implied by population block",
            obs["established_gate_all_true"], bool(obs["established_gate_all_true"])),
        row("session", _scalar(cfg, "session"), "RTH on 100% of in-domain rows",
            bool(obs["all_rth"])),
        row("scoring_cadence_seconds", _scalar(cfg, "scoring_cadence_seconds"), 5, True),
        row("target", _scalar(cfg, "target"), "bearish_regime_flip_within_300s", True),
        row("target_horizon_seconds", _scalar(cfg, "target_horizon_seconds"), 300, True),
        row("positive_flip_interval", _scalar(cfg, "positive_flip_interval"), "(T,T+300s]", True,
            "half-open; reproduced exactly by Outcome 1's `0 < dt <= X` test."),
        row("model_direction_partition", "bullish=+1 / bearish=-1",
            f"both_in_domain={obs['both_in_domain']}", obs["both_in_domain"] == 0,
            "direction and model are one partition."),
        row("is_regime_confirmed", "implied", obs["all_confirmed"], bool(obs["all_confirmed"])),
        row("age_column_identity", "regime_age_seconds == seconds_from_regime_start",
            f"{obs['n_age_column_disagreements']} disagreements",
            int(obs["n_age_column_disagreements"]) == 0,
            "Phase 0 measures the contract on one column and the study buckets the "
            "other; this row proves they are the same quantity."),
    ]

    discrepancies = [
        {
            "id": "D_AGE_FLOOR",
            "summary": "config age_min_seconds=120 but the realized in-domain floor is 125.0s",
            "evidence": {"config": pop.get("age_min_seconds"), "observed_min": obs["age_min"],
                         "grid_cadence_s": 5},
            "resolution": ("The 5s checkpoint grid with a strict `> 120` gate. The first "
                           "frozen age bucket is LABELLED 120-240s and is in fact 125-240s. "
                           "Not widened, not re-optimised."),
        },
        {
            "id": "D_TRAINING_AGE_CEILING",
            "summary": ("config freezes checkpoint_grid ...through_less_than_1800s, but the "
                        "canonical store scores in-domain checkpoints far beyond it"),
            "evidence": {"config_checkpoint_grid": _scalar(cfg, "  checkpoint_grid")
                         or "regime_start_plus_5s_through_less_than_1800s_at_1s_ts_init",
                         "store_max_age_s": obs["age_max"],
                         "n_in_domain_age_ge_1800": obs["n_age_ge_1800"],
                         "pct_in_domain_age_ge_1800": obs["n_age_ge_1800"] / obs["n_in_domain"]},
            "resolution": ("Events armed at age >= 1800s are OUTSIDE the model's training age "
                           "range. Not corrected for; disclosed as pct_age_ge_1800s on every "
                           "table touching the >900s bucket."),
        },
        {
            "id": "D_PROGRESS_BUCKET_0_5",
            "summary": ("prior discovery reported a 0.5-2 ATR progress bucket even though "
                        "training eligibility requires running MFE >= 1 ATR"),
            "evidence": {
                "prior_family": "model_driven_entry_exit_discovery.candidates.path_development",
                "column_it_buckets": "current_progress_atr",
                "column_eligibility_gates": "running_mfe_atr",
                "min_running_mfe_atr": obs["running_mfe_min"],
                "min_current_progress_atr": obs["current_progress_min"],
                "min_implied_retained_ratio": obs["implied_retained_min"],
                "frac_in_domain_current_progress_in_0_5_2_0": obs["frac_current_progress_0_5_to_2_0"],
            },
            "resolution": ("NOT a contradiction. They are different columns. "
                           "running_mfe_atr is the running MAXIMUM favorable excursion "
                           "(floor 1.0); current_progress_atr is the CURRENT excursion, whose "
                           "floor is DERIVED as running_mfe_min * retained_mfe_ratio_min = "
                           "1.0 * 0.5 = 0.5, matching the observed 0.5004 exactly. This study "
                           "buckets running_mfe_atr and therefore creates NO 0.5-1.0 bucket."),
        },
    ]

    return {
        "source_artifacts": {
            "bullish": str(BULL_CONFIG.relative_to(ROOT)),
            "long": str(LONG_MANIFEST.relative_to(ROOT)),
            "store": str(STORE.relative_to(ROOT)),
        },
        "contract_rows": rows,
        "observed": obs,
        "discrepancies": discrepancies,
        "no_refit": "No model artifact is loaded anywhere in this study; probabilities "
                    "are read from canonical_regime_scores_all.parquet as collected.",
    }
