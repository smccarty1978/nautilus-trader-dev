"""Finalize an already-computed sealed stage-2 run without reopening 2026.

This script is intentionally read-only with respect to model selection and trade
simulation.  It validates the preserved outputs, then writes only the human report
and artifact manifest that the original run failed to render.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
SEAL = HERE / "_work" / "selection_seal.json"
RUNNER = HERE / "run_study.py"
TRUSTED_PRESERVED_SHA256 = {
    "results/stage2_report.json": "9518ada7440d35aaefa0668a893b9192a130ec6e4e9e5c7c57fb81e502a2c891",
    "results/economic_results.csv": "f8a5878bc0b16d1e9e590f8175970b1f0898bbc9b52c8e9bd0b4a7b4eb46a71f",
    "results/retention_band_results.csv": "424ef2e53999b175ad8d43a00dcac80ae77d1a434ebbb53b032c607f2efe43e7",
    "results/monthly_results.csv": "51478487e58f76b22711d029bc5017c625db6ed40cfcf142aacb74a894164d32",
    "results/exit_reason_attribution.csv": "a4c9c285ea95e9e7c9e6c99a8ddc2758fd7304fd886dec56267de7e729400757",
    "results/model_diagnostics.csv": "2d78a44ba6e7edd70b491e848626095c02a9251b5b3875a915baa299c653c027",
    "results/calibration_deciles.csv": "26a2fc5604e1eb70fd786e56eac1def1df164866d586e8bed4b4cebe12aae3d9",
    "results/data_readiness.csv": "05b0f0292f78aa0633051b3b9c0546faa91be86da7cc049a75931087fa177543",
    "results/feature_family_contribution.csv": "9c4ddd0d6729d9908275acb6f9fe0333796d9513d8ee3d7147be667f6795ebc7",
    "results/top_features.csv": "a86d04b8fc7354038a4a0740b1ad483fa8f36260b31906982ced02945d1f1083",
    "results/selected_model_oos_2026_trades.parquet": "b18c2f33a371f74dabbb74b42294432aac6f517f0c0ab03225829ec407083c10",
    "_work/selection_seal.json": "cea88d078c04e8c8680b477d85624fb45a46050d1275fde3dc00883a06fd61d6",
    "run_study.py": "c5334c8f2f5071762698b9b2db50809ad3be0cbef87b3b9a6fdd66974e592f44",
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def fail(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def main() -> None:
    for relative, expected in TRUSTED_PRESERVED_SHA256.items():
        path = HERE / relative
        fail(path.is_file() and sha256(path) == expected, f"trusted preserved hash mismatch: {relative}")
    for path in (SEAL, RUNNER, RESULTS / "stage2_report.json", RESULTS / "selected_model_oos_2026_trades.parquet"):
        fail(path.is_file() and path.stat().st_size > 0, f"missing/empty recovery input: {path.name}")
    seal = json.loads(SEAL.read_text(encoding="utf-8"))
    report = json.loads((RESULTS / "stage2_report.json").read_text(encoding="utf-8"))
    fail(all(k in seal for k in ("code_sha256", "result", "stage1_result_sha256")), "selection seal schema mismatch")
    fail(all(k in report for k in ("sealed_selection", "metrics", "survival", "exact_baseline_attribution", "decision", "input_2026")), "stage-2 report schema mismatch")
    chosen = report["sealed_selection"]
    fail(seal["code_sha256"] == sha256(RUNNER), "runner changed after sealed computation")
    fail("selection" in seal["result"], "selection seal result schema mismatch")
    fail(chosen == seal["result"]["selection"], "stage-2 selection differs from sealed 2025 selection")
    fail(chosen["schedule_id"] == "F3__logistic__rband0.2" and chosen["feature_set"] == "F3" and chosen["model"] == "logistic" and abs(float(chosen["band"]) - .2) <= 1e-12 and int(chosen["checks"]) == 5, "preserved selection does not match frozen study outcome")
    fail(report["input_2026"].get("sha256") == "877d907b29a4576993be43a47da16ff2dc5382bf91a80bbf9fa693de1001768a" and int(report["input_2026"].get("count", -1)) == 63021, "preserved 2026 input identity mismatch")

    expected_rows = {
        "economic_results.csv": 96, "retention_band_results.csv": 96,
        "monthly_results.csv": 768, "exit_reason_attribution.csv": 384,
        "model_diagnostics.csv": 24, "calibration_deciles.csv": 1200,
        "data_readiness.csv": 24, "feature_family_contribution.csv": 72,
        "top_features.csv": 204,
    }
    tables = {}
    for name, count in expected_rows.items():
        path = RESULTS / name
        fail(path.is_file() and path.stat().st_size > 0, f"missing/empty {name}")
        tables[name] = pd.read_csv(path)
        fail(len(tables[name]) == count, f"unexpected row count for {name}")

    econ = tables["economic_results.csv"]
    required_econ = {"schedule_id", "feature_set", "model", "band", "split", "selected", "trades", "net", "per_trade", "pf", "dd"}
    fail(required_econ <= set(econ.columns), "economic-results schema mismatch")
    selected_text = econ["selected"].astype(str).str.lower()
    fail(set(selected_text.unique()) <= {"true", "false"}, "invalid selected boolean encoding")
    fail(not econ.duplicated(["schedule_id", "split"]).any(), "duplicate economic schedule/split rows")
    fail(econ["schedule_id"].nunique() == 48 and set(econ["split"].astype(str)) == {"2025", "2026"}, "economic schedule/split coverage mismatch")
    selected_rows = econ.loc[selected_text == "true"]
    fail(len(selected_rows) == 2 and set(selected_rows["split"].astype(str)) == {"2025", "2026"}, "selected economics must contain exactly both splits")
    fail(set(selected_rows["schedule_id"]) == {chosen["schedule_id"]}, "selected schedule mismatch")
    row26 = selected_rows.loc[selected_rows["split"].astype(str) == "2026"].iloc[0]
    for key in ("trades", "net", "per_trade", "pf", "dd"):
        fail(abs(float(row26[key]) - float(report["metrics"][key])) <= 1e-8, f"2026 metric mismatch: {key}")

    row25 = selected_rows.loc[selected_rows["split"].astype(str) == "2025"].iloc[0]
    for key in ("trades", "net", "per_trade", "pf", "dd"):
        fail(abs(float(row25[key]) - float(chosen[key])) <= 1e-8, f"2025 sealed metric mismatch: {key}")

    retention = tables["retention_band_results.csv"]
    fail(not retention.duplicated(["schedule_id", "split"]).any() and retention["schedule_id"].nunique() == 48, "retention schedule coverage mismatch")
    monthly_table = tables["monthly_results.csv"]
    fail(not monthly_table.duplicated(["schedule_id", "split", "month_ct"]).any(), "duplicate monthly rows")
    exits_table = tables["exit_reason_attribution.csv"]
    fail(not exits_table.duplicated(["schedule_id", "split", "exit_reason"]).any(), "duplicate exit-attribution rows")

    trades = pd.read_parquet(RESULTS / "selected_model_oos_2026_trades.parquet")
    required_trade = {"regime_start_ns", "entry_ts", "exit_ts", "net_pnl", "exit_reason"}
    fail(required_trade <= set(trades.columns), "selected-trade schema mismatch")
    fail(not trades["regime_start_ns"].duplicated().any(), "duplicate selected regimes")
    fail(bool((trades["entry_ts"] <= trades["exit_ts"]).all()), "trade timestamp order mismatch")
    entry_years = pd.to_datetime(trades["entry_ts"], unit="ns", utc=True).dt.tz_convert("America/Chicago").dt.year
    fail(set(entry_years.unique()) == {2026}, "selected trades are not exclusively 2026")
    fail(len(trades) == int(report["metrics"]["trades"]), "selected 2026 trade count mismatch")
    fail(abs(float(trades["net_pnl"].sum()) - float(report["metrics"]["net"])) <= 1e-8, "selected 2026 PnL mismatch")
    fail(report["decision"] == "ENRICHED_RETRAIN_CLIPS_WINNERS", "unexpected preserved decision")

    required_survival = {"net_positive", "pertrade_90pct", "pf_90pct", "monthly_worst_25pct", "winner_clipping_exact", "stop_savings_gate"}
    fail(required_survival <= set(report["survival"]), "survival schema mismatch")
    fail(all(report["survival"][k] is False for k in ("net_positive", "pertrade_90pct", "pf_90pct", "monthly_worst_25pct", "winner_clipping_exact")), "survival claims mismatch")
    fail(report["survival"]["stop_savings_gate"] is True, "stop-savings gate mismatch")
    fail({"stop_savings_exact", "clipped_winners_exact"} <= set(report["exact_baseline_attribution"]), "attribution schema mismatch")
    fail(float(report["exact_baseline_attribution"]["clipped_winners_exact"]) > float(report["exact_baseline_attribution"]["stop_savings_exact"]) >= 0., "clipping/savings relationship mismatch")
    fail(report.get("overlay", {}).get("status") == "NOT_APPLICABLE", "fixed-807 overlay claim mismatch")

    survival = report["survival"]
    attribution = report["exact_baseline_attribution"]
    report_text = f"""# Enriched short-RTH retrain

## Executive summary

Decision: `{report['decision']}`. Selected schedule: `{chosen['schedule_id']}`. The enriched retrain passed all five frozen 2025 selection checks but failed sealed 2026 and clipped more baseline winners than its exact stop savings. Keep the current W4 Policy A; do not promote this retrain.

This is a 1-second-OHLC research analysis of accepted, precomputed NT-derived Policy-A labels; it is not NT-native executable validation.

## Selected economics

| Split | Trades | Net PnL | PnL/trade | PF | Max DD |
|---|---:|---:|---:|---:|---:|
| 2025 selection | {int(row25['trades'])} | {row25['net']:.2f} | {row25['per_trade']:.2f} | {row25['pf']:.3f} | {row25['dd']:.2f} |
| 2026 sealed | {int(row26['trades'])} | {row26['net']:.2f} | {row26['per_trade']:.2f} | {row26['pf']:.3f} | {row26['dd']:.2f} |

Baselines: A = 872 trades / $22,250 / $25.52 per trade / PF 1.129 / DD $18,686; B = 807 / $27,013 / $33.47 / PF 1.174 / DD $14,331; C NT benchmark = 807 / $23,270 / $28.84 / PF 1.149 / DD $15,000; D prior retrain selected GBT 35% and failed 2026 at -$10,970.

## Findings

- The frozen 2025 choice was F3 (combined volume/delta and price-level features), logistic regression, 20% qualifying-score retention.
- Sealed 2026 produced ${row26['net']:.2f} total and ${row26['per_trade']:.2f} per trade with PF {row26['pf']:.3f}; it did not survive the net, per-trade, PF, or monthly gates.
- Exact matched attribution found ${attribution['stop_savings_exact']:.2f} of stop savings but ${attribution['clipped_winners_exact']:.2f} of clipped winners.
- Survival gates: `{json.dumps(survival, sort_keys=True)}`.
- The fixed-807 overlay remains not applicable because that schedule lacks complete trade-level PnL/outcome semantics for exact keep/drop/move/add attribution.

## Decision

`ENRICHED_RETRAIN_CLIPS_WINNERS`

Do not promote to NT schedule validation. Keep the current W4 Policy A.

## Recovery provenance

The sealed computation completed and wrote all machine-readable outputs. A report-only NumPy-boolean formatting error prevented the original Markdown and manifest writes. This finalizer verified the unchanged runner hash against the 2025 seal, exact selected-schedule identity, required table row counts, selected 2025/2026 economic rows, and the 2026 trade count/PnL before writing this report. It did not refit, rescore, reselect, or reopen the 2026 input.
"""
    (HERE / "STUDY_REPORT.md").write_text(report_text, encoding="utf-8")

    artifact_paths = sorted(p for p in RESULTS.iterdir() if p.is_file() and p.name != "manifest.json")
    artifact_paths += [HERE / "STUDY_REPORT.md", HERE / "SPEC.md", HERE / "REPRODUCE.md", HERE / "baseline_2025.json", HERE / "sealed_2026.py", Path(__file__)]
    artifacts = [{"path": str(p.relative_to(HERE)).replace("\\", "/"), "bytes": p.stat().st_size, "sha256": sha256(p)} for p in artifact_paths]
    artifacts.append({"path": "audit/audit.md", "self_updating_completion_audit": True, "sha256": None})
    manifest = {"recovered_after_report_only_failure": True, "trusted_preserved_sha256": TRUSTED_PRESERVED_SHA256, "selection_seal_sha256": sha256(SEAL), "runner_sha256": sha256(RUNNER), "selected": chosen, "input_2026": report["input_2026"], "decision": report["decision"], "artifacts": artifacts}
    (RESULTS / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
