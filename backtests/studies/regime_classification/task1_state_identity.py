"""Task 1 — State-identity confound.

Does the static IS HMM's `state 3` coincide with the max-signature state
under the rolling-refit's ranking criterion?

  score = z(rv_300s) + z(range_atr_60s) + z(efficiency_300s) - z(chop_ratio_300s)

Method: load static state assignments + features on IS rows (2020-2022 only,
matching the static HMM's training window), compute per-state signature
score, rank, and emit a clear YES/NO.
"""
from __future__ import annotations
import os, sys
from pathlib import Path

import numpy as np
import pandas as pd

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

STATES_PATH = Path("studies/regime_classification/results/states_nq_1m.parquet")
FEATS_PATH  = Path("studies/regime_classification/results/features_nq_1m.parquet")
SIG_FEATURES = ["rv_300s", "range_atr_60s", "efficiency_300s", "chop_ratio_300s"]
SIG_SIGNS    = [+1.0,       +1.0,             +1.0,              -1.0]
IS_YEARS = (2020, 2021, 2022)


def main():
    print("Loading static state labels + signature features (IS years only)...")
    states = pd.read_parquet(STATES_PATH, columns=["hmm_4"])
    feats  = pd.read_parquet(FEATS_PATH, columns=SIG_FEATURES + ["year"])
    df = feats.join(states, how="inner")
    is_mask = df["year"].isin(IS_YEARS) & df[SIG_FEATURES].notna().all(axis=1) & (df["hmm_4"] >= 0)
    df_is = df.loc[is_mask].copy()
    print(f"  IS rows with valid features + state: {len(df_is):,}")
    print(f"  state distribution on IS:")
    for s in sorted(df_is["hmm_4"].unique()):
        n = (df_is["hmm_4"] == s).sum()
        print(f"    state {int(s)}: {n:>8,} bars ({n/len(df_is):.2%})")

    # === Method A: z-score across rows, then per-state mean (matches rolling_hmm.py) ===
    print(f"\n=== Method A: per-row z-score, then per-state mean (rolling_hmm.py method) ===")
    sig_vals = df_is[SIG_FEATURES].values
    mu = sig_vals.mean(axis=0)
    sd = sig_vals.std(axis=0) + 1e-9
    sig_z = (sig_vals - mu) / sd
    df_is_z = df_is.copy()
    for i, c in enumerate(SIG_FEATURES):
        df_is_z[f"z_{c}"] = sig_z[:, i]

    state_z_means = df_is_z.groupby("hmm_4")[[f"z_{c}" for c in SIG_FEATURES]].mean()
    scores_a = pd.Series(
        sum(SIG_SIGNS[i] * state_z_means[f"z_{SIG_FEATURES[i]}"] for i in range(len(SIG_FEATURES))),
        name="score_A"
    )
    print(f"\n  Per-state mean of (per-row z-score) on IS:")
    print(f"  {'state':<7}", end="")
    for c in SIG_FEATURES:
        print(f"{'z_' + c:>22}", end="")
    print(f"{'score_A':>11}")
    for s in sorted(state_z_means.index):
        row = state_z_means.loc[s]
        print(f"  s{int(s):<6}", end="")
        for c in SIG_FEATURES:
            print(f"{row[f'z_{c}']:>+22.4f}", end="")
        print(f"{scores_a[s]:>+11.4f}")
    max_a = int(scores_a.idxmax())
    print(f"\n  Method A max-score state: s{max_a}")

    # === Method B: z-score across STATE means (literal reading of the brief) ===
    print(f"\n=== Method B: per-state raw mean, then z-score across states ===")
    raw_means = df_is.groupby("hmm_4")[SIG_FEATURES].mean()
    # z-score across the 4 state-mean values for each feature
    z_across_states = raw_means.copy()
    for c in SIG_FEATURES:
        mu_s = raw_means[c].mean()
        sd_s = raw_means[c].std(ddof=0) + 1e-12
        z_across_states[c] = (raw_means[c] - mu_s) / sd_s
    scores_b = pd.Series(
        sum(SIG_SIGNS[i] * z_across_states[SIG_FEATURES[i]] for i in range(len(SIG_FEATURES))),
        name="score_B"
    )
    print(f"\n  Raw per-state means on IS:")
    print(f"  {'state':<7}", end="")
    for c in SIG_FEATURES:
        print(f"{c:>20}", end="")
    print()
    for s in sorted(raw_means.index):
        print(f"  s{int(s):<6}", end="")
        for c in SIG_FEATURES:
            print(f"{raw_means.loc[s, c]:>+20.5f}", end="")
        print()
    print(f"\n  Z-scored ACROSS states + summed signature score (Method B):")
    print(f"  {'state':<7}", end="")
    for c in SIG_FEATURES:
        print(f"{'z_' + c:>18}", end="")
    print(f"{'score_B':>11}")
    for s in sorted(z_across_states.index):
        print(f"  s{int(s):<6}", end="")
        for c in SIG_FEATURES:
            print(f"{z_across_states.loc[s, c]:>+18.4f}", end="")
        print(f"{scores_b[s]:>+11.4f}")
    max_b = int(scores_b.idxmax())
    print(f"\n  Method B max-score state: s{max_b}")

    # === The verdict ===
    print(f"\n{'='*92}")
    print(f"  VERDICT")
    print(f"{'='*92}")
    print(f"  Static IS HMM target state (production): s3")
    print(f"  Method A max-signature state: s{max_a}  ({'YES' if max_a == 3 else 'NO'} matches s3)")
    print(f"  Method B max-signature state: s{max_b}  ({'YES' if max_b == 3 else 'NO'} matches s3)")

    if max_a == 3 and max_b == 3:
        print(f"\n  → YES — static s3 IS the max-signature state.")
        print(f"    The rolling-refit experiments targeted the same state-content as the")
        print(f"    static finding. The rolling failures cannot be attributed to a state-")
        print(f"    identity mismatch — the comparison was valid.")
    elif max_a != 3 or max_b != 3:
        print(f"\n  → NO — static s3 is NOT the max-signature state.")
        print(f"    The rolling-refit experiments targeted a DIFFERENT state-content than")
        print(f"    the static finding. The 'rolling failed to lift' result is not yet")
        print(f"    established — the rolling tests were comparing apples to oranges.")
        print(f"\n    Recommended: re-run rolling with state selection that matches static s3's")
        print(f"    content, OR re-test static using the max-signature state as the target.")


if __name__ == "__main__":
    main()
