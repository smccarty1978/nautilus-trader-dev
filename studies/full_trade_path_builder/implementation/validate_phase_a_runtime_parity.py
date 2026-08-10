"""Independent NT replay parity for the frozen Bullish runtime package."""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import joblib
import numpy as np
import pyarrow.parquet as pq
from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.config import BacktestEngineConfig, LoggingConfig
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.enums import AccountType, OmsType
from nautilus_trader.model.identifiers import Venue
from nautilus_trader.model.objects import Money
from nautilus_trader.persistence.catalog import ParquetDataCatalog

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from studies.fable5_pre_flip_d10_reversal_entry.run_nt import create_instrument
from studies.full_trade_path_builder.implementation.phase_a_runtime import FrozenRuntimeCollector
from studies.full_trade_path_builder.implementation.phase_a_strategy import PhaseABullishCollectorConfig
from studies.full_trade_path_builder.implementation.run_phase_a_collect import BAR_1M, BAR_1S, CATALOG


def fhash(path: Path) -> str:
    h = hashlib.sha256(path.read_bytes()).hexdigest()
    return h


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--artifact-dir", required=True)
    p.add_argument("--collector-parquet", required=True)
    p.add_argument("--output", required=True)
    args = p.parse_args()
    artifact = Path(args.artifact_dir)
    start = datetime(2025, 3, 1, tzinfo=timezone.utc)
    end = datetime(2025, 4, 1, tzinfo=timezone.utc)
    load_start, load_end = start - timedelta(days=3), end + timedelta(seconds=301)
    catalog = ParquetDataCatalog(str(CATALOG))
    b1 = catalog.bars(bar_types=[BAR_1S], start=load_start, end=load_end)
    bm = catalog.bars(bar_types=[BAR_1M], start=load_start, end=load_end)
    engine = BacktestEngine(config=BacktestEngineConfig(
        trader_id="PHASE-A-RUNTIME-PARITY",
        logging=LoggingConfig(log_level="ERROR", bypass_logging=False),
    ))
    engine.add_venue(
        venue=Venue("XCME"), oms_type=OmsType.NETTING, account_type=AccountType.MARGIN,
        base_currency=USD, starting_balances=[Money(5_000_000, USD)],
        bar_execution=True, bar_adaptive_high_low_ordering=True,
    )
    engine.add_instrument(create_instrument())
    engine.add_data(b1)
    engine.add_data(bm)
    FrozenRuntimeCollector.artifact_dir = artifact
    runtime = FrozenRuntimeCollector(PhaseABullishCollectorConfig(repo_root=str(ROOT)))
    engine.add_strategy(runtime)
    engine.run(start=load_start, end=load_end)
    lo, hi = int(start.timestamp() * 1e9), int(end.timestamp() * 1e9)
    runtime_rows = {
        (r["regime_start_ns"], r["checkpoint_decision_ns"]): r
        for r in runtime.checkpoint_rows if lo <= r["checkpoint_decision_ns"] < hi
    }
    manifest = json.loads((artifact / "model_manifest.json").read_text(encoding="utf-8"))
    features = manifest["features"]
    null_cols = [f"{name}__is_null" for name in features]
    cols = ["regime_start_ns", "checkpoint_decision_ns", "feature_complete"] + features + null_cols
    collector_rows = pq.read_table(args.collector_parquet, columns=cols).to_pylist()
    collector = {(r["regime_start_ns"], r["checkpoint_decision_ns"]): r for r in collector_rows}
    model = joblib.load(artifact / "model.joblib")
    keys_equal = set(collector) == set(runtime_rows)
    vector_bad = probability_bad = suppression_bad = null_mask_bad = 0
    samples = []
    rng = random.Random(20250724)
    sample_keys = set(rng.sample(sorted(collector), min(100, len(collector))))
    for key in sorted(set(collector) & set(runtime_rows)):
        a, b = collector[key], runtime_rows[key]
        suppression_bad += bool(a["feature_complete"]) != bool(b["feature_complete"])
        null_mask_bad += [bool(a[name]) for name in null_cols] != [
            bool(b[name]) for name in null_cols
        ]
        av = [a[f] for f in features]
        bv = [b[f] for f in features]
        equal = all(
            (x is None and y is None) or
            (x is not None and y is not None and
             np.asarray(x, dtype="<f8").tobytes() == np.asarray(y, dtype="<f8").tobytes())
            for x, y in zip(av, bv)
        )
        vector_bad += not equal
        if a["feature_complete"] and b["feature_complete"]:
            pa = float(model.predict_proba(np.asarray(av).reshape(1, -1))[0, 1])
            pb = runtime.runtime_scores[key]
            probability_bad += np.asarray(pa, dtype="<f8").tobytes() != np.asarray(pb, dtype="<f8").tobytes()
        else:
            pa = pb = None
        if key in sample_keys:
            av_json = [None if x is None or not np.isfinite(float(x)) else float(x) for x in av]
            bv_json = [None if x is None or not np.isfinite(float(x)) else float(x) for x in bv]
            samples.append({
                "regime_start_ns": key[0], "checkpoint_decision_ns": key[1],
                "collector_vector": av_json, "frozen_adapter_runtime_vector": bv_json,
                "collector_null_mask": [bool(a[name]) for name in null_cols],
                "runtime_null_mask": [bool(b[name]) for name in null_cols],
                "collector_vector_sha256": hashlib.sha256(np.asarray(av, dtype="<f8").tobytes()).hexdigest()
                if a["feature_complete"] else None,
                "runtime_vector_sha256": hashlib.sha256(np.asarray(bv, dtype="<f8").tobytes()).hexdigest()
                if b["feature_complete"] else None,
                "collector_probability": pa, "runtime_probability": pb,
                "collector_complete": a["feature_complete"], "runtime_complete": b["feature_complete"],
            })
    payload = {
        "seed": 20250724, "sample_count": len(samples),
        "collector_rows": len(collector), "runtime_rows": len(runtime_rows),
        "key_sets_exact": keys_equal, "vector_mismatches": vector_bad,
        "probability_mismatches": int(probability_bad),
        "suppression_mismatches": suppression_bad,
        "null_mask_mismatches": null_mask_bad,
        "model_sha256": fhash(artifact / "model.joblib"),
        "adapter_sha256": fhash(artifact / "adapter.py"),
        "collector_parquet_sha256": fhash(Path(args.collector_parquet)),
        "samples": samples,
    }
    payload["verdict"] = "PASS" if (
        keys_equal and vector_bad == 0 and probability_bad == 0
        and suppression_bad == 0 and null_mask_bad == 0
    ) else "FAIL"
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({k: v for k, v in payload.items() if k != "samples"}, indent=2))


if __name__ == "__main__":
    main()
