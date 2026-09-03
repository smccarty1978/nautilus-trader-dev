"""1m / 5m equivalence proof for Dataset V2.

Questions answered, per symbol and year (never 2024 unless --years says so explicitly):

  P1  V2 1m (build-time aggregation of native 1s)  ==  V0 catalog 1m stream?        exact OHLCV + timestamps
  P2  V2 1m  ==  independent integer-bucket aggregation of the V2 native 1s stream? exact
  P3  V0 catalog 5m (materialized from 1s, any-second rule)  ==  5m aggregated from V2 1m with
      (a) any-minute rule and (b) complete-5-minute rule?  -> which runtime rule reproduces V0, and how
      many buckets differ under the complete-bucket rule (those are buckets with missing minutes).

Decision rule written into the JSON: 1m is PROVABLE (P1 and P2 exact for every compared year) or NOT;
5m stays a runtime derivation either way -- the proof records the rule a runtime aggregator must use to
be equivalent to the historical external 5m stream.

    python scripts/prove_bar_equivalence.py --symbol NQ --years 2021 2022 2023 --out artifacts/platform_v2_do_soon/dataset_v2
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

NS = 1_000_000_000
PRICE_SCALE = 1e9


def read_nt_bars(bar_dir: Path, start_ns: int, end_ns: int) -> pd.DataFrame:
    """Decode NautilusTrader catalog bar parquet (fixed-size int64 price/size) into floats, ts_event in [start, end)."""
    frames = []
    for f in sorted(glob.glob(str(bar_dir / "*.parquet"))):
        t = pq.read_table(f).to_pandas()
        out = pd.DataFrame({"ts_event": t["ts_event"].astype("int64"), "ts_init": t["ts_init"].astype("int64")})
        for c in ("open", "high", "low", "close", "volume"):
            raw = np.frombuffer(b"".join(t[c].to_list()), dtype="<i8") if len(t) else np.array([], dtype="<i8")
            out[c] = raw / PRICE_SCALE
        frames.append(out[(out["ts_event"] >= start_ns) & (out["ts_event"] < end_ns)])
    df = pd.concat(frames) if frames else pd.DataFrame(columns=["ts_event", "ts_init", "open", "high", "low", "close", "volume"])
    df = df.sort_values("ts_event").drop_duplicates("ts_event").reset_index(drop=True)
    return df


def agg(df: pd.DataFrame, bucket_ns: int, *, complete: bool = False, src_ns: int | None = None) -> pd.DataFrame:
    key = df["ts_event"].to_numpy() // bucket_ns * bucket_ns
    g = df.groupby(key, sort=True)
    out = pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(), "low": g["low"].min(), "close": g["close"].last(), "volume": g["volume"].sum(), "n": g.size()})
    out.index.name = "ts_event"
    if complete and src_ns:
        out = out[out["n"] == bucket_ns // src_ns]
    return out.drop(columns=["n"]).reset_index()


def compare(a: pd.DataFrame, b: pd.DataFrame, label: str) -> dict:
    ka, kb = set(a["ts_event"]), set(b["ts_event"])
    common = sorted(ka & kb)
    ai = a.set_index("ts_event").loc[common]
    bi = b.set_index("ts_event").loc[common]
    cols = ["open", "high", "low", "close", "volume"]
    diff = (ai[cols].to_numpy() != bi[cols].to_numpy())
    bad_rows = np.flatnonzero(diff.any(axis=1))
    first = None
    if len(bad_rows):
        i = int(bad_rows[0])
        first = {"ts_event": int(common[i]), "ts_utc": str(pd.Timestamp(common[i], tz="UTC")), "a": ai.iloc[i][cols].to_dict(), "b": bi.iloc[i][cols].to_dict()}
    only_a, only_b = sorted(ka - kb), sorted(kb - ka)
    return {"label": label, "rows_a": int(len(a)), "rows_b": int(len(b)), "common": len(common), "only_a": len(only_a), "only_b": len(only_b),
            "value_mismatches": int(len(bad_rows)), "exact": bool(not only_a and not only_b and not len(bad_rows)),
            "first_only_a_utc": str(pd.Timestamp(only_a[0], tz="UTC")) if only_a else None, "first_only_b_utc": str(pd.Timestamp(only_b[0], tz="UTC")) if only_b else None,
            "first_value_mismatch": first}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbol", required=True)
    ap.add_argument("--years", nargs="+", type=int, required=True)
    ap.add_argument("--v2", help="V2 catalog dir (default: resolve <SYM>_1S_V2 through roots)")
    ap.add_argument("--v0", help="V0 catalog dir (default: resolve the product's V0 dataset through roots)")
    ap.add_argument("--out", default="artifacts/platform_v2_do_soon/dataset_v2")
    ns = ap.parse_args()
    from backtests.nt_runtime.data_plan import PRODUCT_CATALOGS
    from research_workflow.roots import resolve_dataset
    sym = ns.symbol.upper()
    prod = PRODUCT_CATALOGS[sym]
    v0 = Path(ns.v0) if ns.v0 else resolve_dataset(prod["dataset_id"], ROOT, catalog_rel_path=prod["catalog_rel_path"]).catalog_path
    v2 = Path(ns.v2) if ns.v2 else resolve_dataset(f"{sym}_1S_V2", ROOT).catalog_path
    inst = prod["instrument_id"]
    dirs = {"v0_1s": v0 / "data/bar" / f"{inst}-1-SECOND-LAST-EXTERNAL", "v0_1m": v0 / "data/bar" / f"{inst}-1-MINUTE-LAST-EXTERNAL", "v0_5m": v0 / "data/bar" / f"{inst}-5-MINUTE-LAST-EXTERNAL",
            "v2_1s": v2 / "data/bar" / f"{inst}-1-SECOND-LAST-EXTERNAL", "v2_1m": v2 / "data/bar" / f"{inst}-1-MINUTE-LAST-EXTERNAL"}
    report = {"symbol": sym, "v0": str(v0), "v2": str(v2), "years": ns.years, "per_year": {}, "generated_at_utc": pd.Timestamp.utcnow().isoformat()}
    out_dir = ROOT / ns.out
    out_dir.mkdir(parents=True, exist_ok=True)
    for year in ns.years:
        t0 = time.perf_counter()
        s, e = int(pd.Timestamp(f"{year}-01-01", tz="UTC").value), int(pd.Timestamp(f"{year + 1}-01-01", tz="UTC").value)
        v2_1s = read_nt_bars(dirs["v2_1s"], s, e)
        v0_1s = read_nt_bars(dirs["v0_1s"], s, e)
        v2_1m = read_nt_bars(dirs["v2_1m"], s, e)
        v0_1m = read_nt_bars(dirs["v0_1m"], s, e)
        v0_5m = read_nt_bars(dirs["v0_5m"], s, e) if dirs["v0_5m"].is_dir() else None
        yr = {"native_1s": compare(v2_1s, v0_1s, "V2 1s vs V0 1s (native rows identical?)"),
              "P1_v2_1m_vs_v0_1m": compare(v2_1m, v0_1m, "V2 1m vs V0 1m"),
              "P2_v2_1m_vs_independent_from_v2_1s": compare(v2_1m, agg(v2_1s, 60 * NS), "V2 1m vs integer-bucket aggregation of V2 1s"),
              "ts_init_contract_1m": bool(len(v2_1m) == 0 or ((v2_1m["ts_init"] - v2_1m["ts_event"]) == 60 * NS).all())}
        if v0_5m is not None:
            any_rule = agg(v2_1m, 300 * NS)
            complete_rule = agg(v2_1m, 300 * NS, complete=True, src_ns=60 * NS)
            yr["P3a_v0_5m_vs_any_minute_rule"] = compare(v0_5m, any_rule, "V0 5m vs 5m(any-minute) from V2 1m")
            yr["P3b_v0_5m_vs_complete_bucket_rule"] = compare(v0_5m, complete_rule, "V0 5m vs 5m(complete 5 minutes) from V2 1m")
            yr["buckets_with_missing_minutes"] = int(len(any_rule) - len(complete_rule))
        yr["elapsed_s"] = round(time.perf_counter() - t0, 1)
        report["per_year"][str(year)] = yr
        print(json.dumps({"year": year, "P1_exact": yr["P1_v2_1m_vs_v0_1m"]["exact"], "P2_exact": yr["P2_v2_1m_vs_independent_from_v2_1s"]["exact"],
                          "native_identical": yr["native_1s"]["exact"], "elapsed_s": yr["elapsed_s"]}), flush=True)
    years = report["per_year"].values()
    p1 = all(y["P1_v2_1m_vs_v0_1m"]["exact"] for y in years)
    p2 = all(y["P2_v2_1m_vs_independent_from_v2_1s"]["exact"] for y in years)
    p3a = all(y.get("P3a_v0_5m_vs_any_minute_rule", {}).get("exact", False) for y in years) if any("P3a_v0_5m_vs_any_minute_rule" in y for y in years) else None
    p3b = all(y.get("P3b_v0_5m_vs_complete_bucket_rule", {}).get("exact", False) for y in years) if p3a is not None else None
    report["verdict"] = {"1m_equivalence": "PROVABLE" if (p1 and p2) else "NOT_PROVABLE", "P1_all_exact": p1, "P2_all_exact": p2,
                         "5m_runtime_rule_matching_v0": ("any_minute" if p3a else ("complete_bucket" if p3b else "none")) if p3a is not None else "no_v0_5m_stream",
                         "5m_decision": "runtime derivation from completed 1m retained (V2 ships no 5m stream); an aggregator must use the rule named above to reproduce the historical external 5m stream"}
    path = out_dir / f"equivalence_{sym}.json"
    path.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"STATUS": "OK", "report": str(path), **report["verdict"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
