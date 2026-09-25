"""Circular-shift null for the onset atlas materiality count (k = 0.5 and k = 1.5).

Outcome vectors (location residuals) are rotated by a random offset of >= 2,000 episodes within each block in time order, so
features and outcomes keep their own autocorrelation but lose their alignment. The material count is recomputed with the
same rule as atlas.py. 20 rotations.

    python studies/nq_regime_challenge_lifecycle_2023/null_shift.py
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

import atlas as at

OUT = Path(__file__).resolve().parent / "artifacts"


def main() -> None:
    ev = pd.read_parquet(OUT / "CHALLENGE_EVENTS.parquet")
    allres = {}
    for k in (0.5, 1.5):
        allres[str(k)] = run(ev, k)
    (OUT / "NULL_SHIFT_ONSET.json").write_text(json.dumps(allres, indent=2) + chr(10), encoding="utf-8")
    print(json.dumps(allres, indent=1))


def run(ev, k):
    t0 = time.time()
    e5 = at.add_baseline(ev[ev.k == k].copy(), "dist_flip_A", at.OUTC).sort_values("tc_ns").reset_index(drop=True)
    feats = [f for fam in at.FAMILY.values() for f in fam]
    outs = ["res_new_ext_res", "hold_A_res"]
    _, real = at.feature_atlas(e5, feats, outs, "real", ci=False)
    real_mat = at.verdict_table(real, "res_new_ext_res_spread", "hold_A_res_spread")
    rng = np.random.default_rng(7)
    counts = []
    for i in range(20):
        sh = e5.copy()
        for blk in ("A", "B"):
            idx = np.flatnonzero(sh.block.to_numpy() == blk)
            off = int(rng.integers(len(idx) // 10, len(idx) - len(idx) // 10))
            for o in outs:
                sh.loc[idx, o] = np.roll(sh.loc[idx, o].to_numpy(), off)
        _, sp = at.feature_atlas(sh, feats, outs, f"shift{i}", ci=False)
        v = at.verdict_table(sp, "res_new_ext_res_spread", "hold_A_res_spread")
        counts.append({o: int(v[v.outcome == o].material.sum()) for o in v.outcome.unique()} |
                      {f"{o}_same_sign": float(v[v.outcome == o].same_sign.mean()) for o in v.outcome.unique()})
    c = pd.DataFrame(counts)
    res = {"real_material": {o: int(real_mat[real_mat.outcome == o].material.sum()) for o in real_mat.outcome.unique()},
           "real_same_sign": {o: float(real_mat[real_mat.outcome == o].same_sign.mean()) for o in real_mat.outcome.unique()},
           "null_material_mean": c.filter(regex="spread$").mean().to_dict(), "null_material_p95": c.filter(regex="spread$").quantile(0.95).to_dict(),
           "null_same_sign_mean": c.filter(regex="same_sign$").mean().to_dict(), "n_features": int(real_mat.feature.nunique()), "rotations": 20,
           "runtime_s": round(time.time() - t0, 1)}
    return res


if __name__ == "__main__":
    main()
