"""Build an immutable Dataset V2 catalog (native 1s, build-time 1m, reference tables, manifest).

    python scripts/build_dataset_v2.py --symbol NQ --years 2020 2021 2022 2023 2024 2025 2026_ytd
    python scripts/build_dataset_v2.py --symbol ES --years ... --catalog-root <dir>

Deterministic: same raw bytes + same builder -> same logical digest. Never overwrites: an existing
output directory or a V0 catalog path is refused. Prints one JSON card; the full manifest is written
to <catalog>/build_manifest.json and the DatasetSpec to research/datasets/<id>.yaml.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbol", required=True)
    ap.add_argument("--years", nargs="+", required=True)
    ap.add_argument("--raw-dir", help="directory of <SYM>_v0_1s_<year>.parquet (default: first configured catalog root's sibling data/raw, else repo data/raw)")
    ap.add_argument("--catalog-root", help="where <SYM>_1S_V2 is created (default: first configured catalog root)")
    ap.add_argument("--dataset-id")
    ap.add_argument("--no-spec", action="store_true", help="do not write research/datasets/<id>.yaml")
    ap.add_argument("--progress", help="progress file (one line per step)")
    ns = ap.parse_args()

    from research_workflow.dataset_v2 import DatasetV2Error, build_dataset_v2
    from research_workflow.roots import load_config
    cfg = load_config()
    roots = [Path(r) for r in cfg.catalog_roots] if cfg.catalog_roots else [ROOT / "data" / "catalog"]
    catalog_root = Path(ns.catalog_root) if ns.catalog_root else roots[0]
    raw_dir = Path(ns.raw_dir) if ns.raw_dir else (roots[0].parent / "raw" if (roots[0].parent / "raw").is_dir() else ROOT / "data" / "raw")
    prog = Path(ns.progress) if ns.progress else None

    def log(msg: str) -> None:
        line = f"{time.strftime('%H:%M:%S')} {msg}"
        if prog:
            with prog.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        else:
            print(line, file=sys.stderr, flush=True)

    t0 = time.perf_counter()
    try:
        m = build_dataset_v2(symbol=ns.symbol, years=ns.years, raw_dir=raw_dir, catalog_root=catalog_root, repo_root=ROOT,
                             dataset_id=ns.dataset_id, write_spec=not ns.no_spec, progress=log)
    except DatasetV2Error as exc:
        print(json.dumps({"STATUS": "FAIL", "error": str(exc)}))
        return 2
    card = {"STATUS": "OK", "dataset_id": m["dataset_id"], "catalog_path": m["catalog_path"], "logical_digest": m["logical_digest"], "reference_digest": m["reference_digest"],
            "rows": {k: v["rows"] for k, v in m["streams"].items()}, "coverage": m["coverage"], "spec_path": m.get("spec_path"), "elapsed_s": round(time.perf_counter() - t0, 1)}
    print(json.dumps(card, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
