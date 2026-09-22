"""Compile the requesting atlas against this chore and execute its frozen analysis through registered ops.

Reads the study's OWN study.yaml (read-only), overlays ``outcome.entry_observation: true`` and the
analysis block of ``atlas_analysis_proof.yaml``, compiles with the production compiler into a scratch
directory, then runs the production analysis pipeline over a SYNTHETIC frame carrying exactly the
compiled plan's columns. No data is collected; no 2023/2024 outcome is read.

    python artifacts/platform_v2/entry_observation_and_atlas_ops/atlas_compile_proof.py \
        --study "../Nautilus Trader-nq_mtf_regime_structural_geometry_atlas/studies/nq_mtf_regime_structural_geometry_atlas" \
        --out artifacts/platform_v2/entry_observation_and_atlas_ops/atlas_compile_proof.json
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))

NS = 1_000_000_000


def compile_variant(study_yaml: dict, analysis: dict, work: Path, name: str):
    from research_workflow.grammar.compiler import compile_study, load_spec
    body = copy.deepcopy(study_yaml)
    body["outcome"].update(PROOF["outcome_overlay"])
    body["analysis"] = analysis
    d = work / "studies" / body["study"]["id"]
    d.mkdir(parents=True, exist_ok=True)
    (d / "study.yaml").write_text(yaml.safe_dump(body, sort_keys=False), encoding="utf-8")
    out = compile_study(load_spec(d), repo_root=ROOT)
    return out, d


def synthetic_frame(plan: dict, n: int, seed: int) -> pd.DataFrame:
    """Values of the right TYPE for every plan column; prices/levels/ATRs internally consistent enough for
    every derive branch (both directions, zero spans, missing priors, null entries) to be exercised."""
    rng = np.random.default_rng(seed)
    cols = plan["columns"]
    names = (list(cols["identity"]) + [m["column"] for m in cols["metadata"]] + list(cols["features"])
             + list(cols["derived"]) + list(cols["observation"]))
    names = list(dict.fromkeys(names))
    day = rng.integers(0, 240, n)
    t0 = 1_672_756_200 * NS + day.astype(np.int64) * 86_400 * NS + rng.integers(0, 6 * 3600, n).astype(np.int64) * NS
    f = {}
    E = 12_000 + rng.normal(0, 50, n)
    for c in names:
        if c in ("observation_ts", "decision_epoch_ts_ns"):
            f[c] = t0
        elif c == "checkpoint_index":
            f[c] = np.where(rng.random(n) < 0.8, 0, rng.integers(1, 20, n))
        elif re.fullmatch(r"(prev_)?dir_\w+|prior_dir_\w+|regime_direction", c):
            f[c] = rng.choice([-1, 1], n)
        elif c.startswith("prior_rotation_seq_"):
            f[c] = np.where(rng.random(n) < 0.05, 0, rng.integers(1, 500, n))
        elif c.endswith("_disposition") and c.startswith("fp_"):
            f[c] = rng.choice(["POSITIVE", "NEGATIVE", "CENSORED"], n, p=[0.45, 0.35, 0.2])
        elif c.endswith("_censor_reason") or c in ("censor_reason", "terminal_exit_unavailable_reason",
                                                   "executable_entry_unavailable_reason"):
            f[c] = np.array([None] * n, dtype=object)
        elif c == "terminal_flip_disposition":
            f[c] = rng.choice(["LABELED_POSITIVE", "CENSORED"], n, p=[0.97, 0.03])
        elif c == "disposition":
            f[c] = rng.choice(["LABELED_POSITIVE", "LABELED_NEGATIVE", "CENSORED"], n)
        elif c.endswith("_resolution_seconds"):
            f[c] = rng.integers(1, 3000, n).astype(float)
        elif c.endswith("_ts") or c.endswith("_ns") or c.endswith("_ts_ns"):
            f[c] = t0 + rng.integers(1, 3000, n).astype(np.int64) * NS
        elif "atr" in c:
            f[c] = np.abs(rng.normal(8, 2, n)) + 0.5
        elif "price" in c or "highest" in c or "lowest" in c or "close" in c:
            f[c] = E + rng.normal(0, 30, n)
        else:
            f[c] = rng.normal(0, 1, n)
    df = pd.DataFrame(f)
    # entry, levels, ATRs, terminal: consistent shapes + injected structure so nomination has claims
    df["executable_entry_price"] = E
    df.loc[rng.random(n) < 0.002, "executable_entry_price"] = np.nan          # entry unavailable
    df["executable_entry_ts"] = pd.array(t0 + NS, dtype="Int64")
    df["executable_entry_unavailable_reason"] = np.where(df["executable_entry_price"].isna(), "SESSION_END", None)
    for tf in ("5m", "15m", "1h"):
        hi = E + np.abs(rng.normal(20, 10, n))
        lo = E - np.abs(rng.normal(20, 10, n))
        span0 = rng.random(n) < 0.01
        hi[span0] = lo[span0] = E[span0]                                        # ZERO_SPAN
        df[f"highest_high_{tf}"], df[f"lowest_low_{tf}"] = hi, lo
        df[f"start_price_{tf}"] = (hi + lo) / 2
        df.loc[rng.random(n) < 0.01, f"frozen_atr_{tf}"] = 0.0                  # NO_ATR
    sd = df["dir_1m"] * (df["executable_entry_price"] - df["start_price_5m"]) / df["atr_entry_1m"]
    g = 0.15 * np.tanh(sd.fillna(0)) + rng.normal(0, 1, n)
    df["terminal_gross_pnl_atr"] = g
    df["terminal_gross_pnl_points"] = g * df["atr_entry_1m"]
    trunc = rng.random(n) < 0.01
    df.loc[trunc, ["terminal_gross_pnl_atr", "terminal_gross_pnl_points"]] = np.nan
    df["terminal_flip_ts"] = pd.array(t0 + rng.integers(60, 4000, n).astype(np.int64) * NS, dtype="Int64")
    df["_year"] = 2023
    return df


def main() -> int:
    global PROOF
    ap = argparse.ArgumentParser()
    ap.add_argument("--study", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--rows", type=int, default=60_000)
    a = ap.parse_args()
    PROOF = yaml.safe_load((HERE / "atlas_analysis_proof.yaml").read_text(encoding="utf-8"))
    study_dir = Path(a.study).resolve()
    study_yaml = yaml.safe_load((study_dir / "study.yaml").read_text(encoding="utf-8"))
    from research_workflow.analysis_pipeline import run_pipeline
    from research.analysis.expressions import expand_columns
    report: dict = {"study": str(study_dir.name), "study_yaml_sha256": hashlib.sha256((study_dir / "study.yaml").read_bytes()).hexdigest(),
                    "chore_root": str(ROOT), "outcomes_read": False, "collected": False}
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        # --- phase 1: discovery -------------------------------------------------------------------
        disc = copy.deepcopy(PROOF["analysis_discovery"])
        out, d1 = compile_variant(study_yaml, disc, work / "p1", "discovery")
        if not out.ok:
            report["discovery_compile"] = out.card()
            Path(a.out).write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
            return 1
        plan = out.plan.to_dict()
        oc = plan["outcome"]
        atlas_cols = [n for n, _ in expand_columns(disc["steps"][0]["params"]["columns"])]
        dist = [c for c in atlas_cols if re.fullmatch(r"(sd|ad)_(cur|pri)_(start|mfe|mae|end)_(5m|15m|1h)_[AB]", c)]
        report["discovery_compile"] = {
            "ok": True, "plan_sha256": plan["plan_sha256"], "closure_sha256": plan["closure"].get("closure_sha256"),
            "entry_observation": oc.get("entry_observation"), "terminal_outcome": oc.get("terminal_outcome"),
            "entry_columns": [c for c in oc["observation_columns"] if c.startswith("executable_entry")],
            "observation_columns_last": oc["observation_columns"][-1],
            "analysis_ops": plan["analysis"]["ops"], "n_steps": len(plan["analysis"]["steps"]),
            "closure_has_new_modules": sorted(f for f in plan["closure"]["files"] if f.startswith("research/analysis/")
                                              and any(k in f for k in ("derive_ops", "contrast_ops", "expressions"))),
            "derived_atlas_columns": len(atlas_cols), "distance_columns": len(dist),
            "distance_columns_by_denominator": {"A": sum(c.endswith("_A") for c in dist), "B": sum(c.endswith("_B") for c in dist)},
            "l2_dimensions": len(disc["steps"][4]["params"]["contrasts"][1]["dimensions"]),
        }
        # --- phase 1 execution on synthetic rows -----------------------------------------------------
        frame = synthetic_frame(plan, a.rows, seed=2023)
        (d1 / "artifacts").mkdir(exist_ok=True)
        ran = run_pipeline(plan["analysis"]["steps"], plan["analysis"]["artifacts"], {"frame": frame},
                           out_dir=d1 / "artifacts", context={"study_dir": str(d1)})
        claims_path = d1 / "artifacts" / "replication_claims.json"
        claims = json.loads(claims_path.read_text(encoding="utf-8"))
        atlas = pd.read_parquet(d1 / "artifacts" / "atlas_frame.parquet")
        report["discovery_execution"] = {
            "steps": ran["steps"], "artifacts": [{k: v for k, v in r.items() if k != "sha256"} for r in ran["artifacts"]],
            "atlas_rows": int(len(atlas)), "mtf_states": int(atlas["mtf_state"].nunique()),
            "null_categories_seen": sorted({v for c in atlas.columns if c.startswith("b_") for v in atlas[c].dropna().unique()
                                            if v in ("NO_PRIOR", "NO_ATR", "ZERO_SPAN")}),
            "nomination_summary": claims["summary"], "n_claims": len(claims["claims"]),
        }
        sha = hashlib.sha256(claims_path.read_bytes()).hexdigest()
        # --- phase 2: replication, same derive step + pinned scorecard -----------------------------------
        rep = PROOF["analysis_replication"]
        steps = [s for s in disc["steps"] if s["id"] in rep["steps_from_discovery"]]
        sc = copy.deepcopy(rep["scorecard"])
        sc["params"]["claims_sha256"] = sha
        out2, d2 = compile_variant(study_yaml, {"source": "train", "steps": steps + [sc], "artifacts": rep["artifacts"]}, work / "p2", "replication")
        if not out2.ok:
            report["replication_compile"] = out2.card()
            Path(a.out).write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
            return 1
        plan2 = out2.plan.to_dict()
        (d2 / "artifacts").mkdir(exist_ok=True)
        (d2 / "artifacts" / "replication_claims.json").write_bytes(claims_path.read_bytes())
        frame2 = synthetic_frame(plan2, a.rows, seed=2024)
        frame2["_year"] = 2024
        ran2 = run_pipeline(plan2["analysis"]["steps"], plan2["analysis"]["artifacts"], {"frame": frame2},
                            out_dir=d2 / "artifacts", context={"study_dir": str(d2)})
        card = json.loads((d2 / "artifacts" / "replication_scorecard.json").read_text(encoding="utf-8"))
        report["replication_compile"] = {"ok": True, "plan_sha256": plan2["plan_sha256"], "analysis_ops": plan2["analysis"]["ops"]}
        report["replication_execution"] = {"steps": ran2["steps"], "claims_sha256": sha, "n_claims": card["n_claims"],
                                           "rows": len(card["rows"]), "counts": card["counts"],
                                           "every_claim_retained": [r["claim_id"] for r in card["rows"]] == [c["claim_id"] for c in claims["claims"]]}
        # --- refusal checks through the same compiler ---------------------------------------------------
        bad = copy.deepcopy(disc)
        bad["steps"][0]["params"]["columns"].append({"name": "leak", "expr": "no_such_plan_column * 2"})
        out3, _ = compile_variant(study_yaml, bad, work / "p3", "bad")
        tampered = copy.deepcopy(claims)
        tampered["replication"]["min_ratio"] = 0.01
        (d2 / "artifacts" / "replication_claims.json").write_text(json.dumps(tampered, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        try:
            run_pipeline(plan2["analysis"]["steps"], plan2["analysis"]["artifacts"], {"frame": frame2}, out_dir=d2 / "artifacts",
                         context={"study_dir": str(d2)})
            tamper = "NOT_REFUSED"
        except Exception as exc:  # noqa: BLE001 - recorded verbatim
            tamper = str(exc).split(":")[0]
        report["refusals"] = {"unknown_column_compile_ok": out3.ok,
                              "unknown_column_gap": [g["detail_text"] if "detail_text" in g else g.get("message") for g in out3.card().get("gaps", [])][:2],
                              "tampered_claim_file": tamper}
    Path(a.out).write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("discovery_compile", "replication_execution", "refusals")}, indent=1, default=str)[:4000])
    return 0


PROOF: dict = {}

if __name__ == "__main__":
    raise SystemExit(main())
