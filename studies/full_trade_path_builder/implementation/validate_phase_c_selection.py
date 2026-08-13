"""Exact independent parity validation of Phase C NT selections."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pyarrow.parquet as pq

from .phase_c_strategy import trade_id_for
from .run_phase_a_collect import atomic_json, sha256_file
from .run_phase_c_months import load_phase_c_contract, selected_state_hash


def validate(phase_b_root: Path, phase_c_root: Path, result_path: Path) -> dict:
    identity, bull_threshold, bear_threshold = load_phase_c_contract()
    expected_selected: set[str] = set()
    expected: list[tuple] = []
    actual: list[tuple] = []
    failures: list[str] = []
    running_actual_state: set[str] = set()
    for year in range(2021, 2026):
        for month in range(1, 13):
            bdir = phase_b_root / f"year={year}" / f"month={month:02d}"
            cdir = phase_c_root / f"year={year}" / f"month={month:02d}"
            bmanifest = json.loads((bdir / "manifest.json").read_text())
            cmanifest = json.loads((cdir / "manifest.json").read_text())
            score_path = bdir / "canonical_model_scores.parquet"
            selection_path = cdir / "selected_trade_entries.parquet"
            if sha256_file(score_path) != bmanifest["canonical_model_scores_sha256"]:
                failures.append(f"{year}-{month:02d}: Phase B score hash")
            if sha256_file(selection_path) != cmanifest["selection_sha256"]:
                failures.append(f"{year}-{month:02d}: Phase C output hash")
            if cmanifest["phase_c_identity"] != identity:
                failures.append(f"{year}-{month:02d}: Phase C identity")
            if cmanifest["prior_selected_state_sha256"] != selected_state_hash(
                running_actual_state
            ):
                failures.append(f"{year}-{month:02d}: prior state")
            rows = pq.read_table(score_path).to_pylist()
            for row in rows:
                for prefix, threshold, direction in (
                    ("bullish", bull_threshold, -1),
                    ("bearish", bear_threshold, 1),
                ):
                    if not row[f"{prefix}_in_domain"] or not row[
                        f"{prefix}_score_available"
                    ]:
                        continue
                    probability = row[f"{prefix}_probability"]
                    if probability is None or float(probability) < threshold:
                        continue
                    model_id = row[f"{prefix}_model_id"]
                    regime_key = json.dumps(
                        [row["instrument_id"], model_id, int(row["regime_start_ns"])],
                        separators=(",", ":"),
                    )
                    if regime_key in expected_selected:
                        continue
                    expected_selected.add(regime_key)
                    decision = int(row["checkpoint_decision_ns"])
                    expected.append(
                        (
                            trade_id_for(
                                row["instrument_id"],
                                model_id,
                                int(row["regime_start_ns"]),
                                decision,
                                direction,
                            ),
                            regime_key,
                            decision,
                            model_id,
                            direction,
                            float(probability),
                            threshold,
                        )
                    )
            selected_rows = pq.read_table(selection_path).to_pylist()
            for row in selected_rows:
                running_actual_state.add(row["selection_regime_key"])
                actual.append(
                    (
                        row["trade_id"],
                        row["selection_regime_key"],
                        int(row["checkpoint_decision_ns"]),
                        row["entry_model_id"],
                        int(row["trade_direction"]),
                        float(row["entry_probability"]),
                        float(row["entry_top_2_5_threshold"]),
                    )
                )
            if cmanifest["result_selected_state_sha256"] != selected_state_hash(
                running_actual_state
            ):
                failures.append(f"{year}-{month:02d}: result state")
    if expected != actual:
        expected_set, actual_set = set(expected), set(actual)
        failures.append(
            f"selection parity mismatch missing={len(expected_set-actual_set)} "
            f"extra={len(actual_set-expected_set)}"
        )
    if len({row[1] for row in actual}) != len(actual):
        failures.append("duplicate selected regime")
    global_manifest = json.loads(
        (phase_c_root / "global_selection_manifest.json").read_text()
    )
    if global_manifest.get("selected_trades") != len(actual):
        failures.append("global selection count")
    result = {
        "status": "PASS" if not failures else "FAIL",
        "selected_trades": len(actual),
        "expected_trades": len(expected),
        "long_trades": sum(row[4] == 1 for row in actual),
        "short_trades": sum(row[4] == -1 for row in actual),
        "unique_regimes": len({row[1] for row in actual}),
        "failures": failures,
        "threshold_reference_overlap_waiver": True,
    }
    atomic_json(result, result_path)
    if failures:
        raise RuntimeError(json.dumps(result, indent=2))
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase-b-root", required=True)
    parser.add_argument("--phase-c-root", required=True)
    parser.add_argument("--result", required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            validate(
                Path(args.phase_b_root), Path(args.phase_c_root), Path(args.result)
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
