"""
Phase 1 — reproduce repaired baselines (E0 regime exit, E5 fitted-Q) via the
sim_v2 stack, and check parity against the prior frozen numbers.

Prior frozen references (from the repaired baseline study / prior report):
    E0 val  EV = $8.60
    E5 val  EV = $10.13
    E0 test EV = $6.56
"""

from __future__ import annotations
import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor

import common as C
import sim_v2

PRIOR = {"E0_val": 8.60, "E5_val": 10.13, "E0_test": 6.56}


def _ep_meta(df):
    epx = "entry_px_y" if "entry_px_y" in df.columns else "entry_px"
    return df.groupby("episode_id").first()[[epx, "direction"]].rename(columns={epx: "entry_px"})


def main():
    print("=" * 70)
    print("Phase 1 — baseline reproduction")
    print("=" * 70)
    chk, trades = C.load_atlas()
    chk = chk[chk["period"].isin(["train", "val", "test"])].copy()
    bars = C.load_1s_full()

    tt = trades[trades["period"].isin(["train", "val", "test"])].copy()
    tt = sim_v2.resolve_terminal_events(tt, bars)
    chk = sim_v2.truncate_checkpoints(chk, tt)
    chk = sim_v2.compute_hold_advantage(chk)

    train = chk[chk["period"] == "train"]
    rows = []
    for tag in ["val", "test"]:
        df = chk[chk["period"] == tag].sort_values(["episode_id", "seconds_since_entry"]).reset_index(drop=True)
        ep_base = sim_v2.build_ep_base(df, tt[tt["period"] == tag])
        ep_meta = _ep_meta(df)
        elig = df["seconds_since_entry"] >= C.MIN_ELIG_S

        e0 = float(ep_base["e0_pnl"].mean())
        rows.append({"period": tag, "policy": "E0_regime", "ev": round(e0, 2)})

        if tag == "val":
            feats = [f for f in sim_v2.FULL_FEATS if f in train.columns]
            reg = LGBMRegressor(n_estimators=300, learning_rate=0.05, max_depth=4,
                                min_child_samples=100, num_leaves=15, reg_lambda=10.0,
                                random_state=42, n_jobs=4, verbose=-1)
            reg.fit(train[feats].fillna(0).values, train["hold_advantage"].fillna(0).values)
            s = reg.predict(df[feats].fillna(0).values)
            best = -1e9
            for q in np.arange(10, 91, 5):
                thr = np.percentile(s, q)
                sig = elig & (pd.Series(s, index=df.index) < thr)
                ev = sim_v2.simulate_policy_ev(df, sig, ep_base, ep_meta, bars)
                best = max(best, ev)
            rows.append({"period": "val", "policy": "E5_fitted_q", "ev": round(float(best), 2)})

    rep = pd.DataFrame(rows)
    rep.to_parquet(C.RESULTS / "baseline_reproduction.parquet", index=False)

    def get(period, pol):
        r = rep[(rep.period == period) & (rep.policy == pol)]
        return float(r["ev"].values[0]) if len(r) else np.nan

    audit = {
        "E0_val": {"reproduced": get("val", "E0_regime"), "prior": PRIOR["E0_val"]},
        "E5_val": {"reproduced": get("val", "E5_fitted_q"), "prior": PRIOR["E5_val"]},
        "E0_test": {"reproduced": get("test", "E0_regime"), "prior": PRIOR["E0_test"]},
    }
    for k, v in audit.items():
        v["abs_diff"] = round(abs(v["reproduced"] - v["prior"]), 2)
        v["parity"] = "OK" if v["abs_diff"] <= 1.5 else "CHECK"
    C.savej(audit, C.RESULTS / "baseline_parity_audit.json")
    print(rep.to_string(index=False))
    for k, v in audit.items():
        print(f"  {k}: repro ${v['reproduced']} vs prior ${v['prior']} -> {v['parity']}")


if __name__ == "__main__":
    main()
