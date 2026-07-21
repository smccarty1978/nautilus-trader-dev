"""
Phase 3 — checkpoint-level regime-quality state machine.

Fixes the prior collapse (5642/5660 -> ORDINARY) which had two causes:
  (1) episode state attributed from `groupby.first()` (the ~30s checkpoint,
      tiny MFE -> always ORDINARY), and
  (2) the saved artifact was a `.head(2000)` sample, not the population.

Here every positioned 5s checkpoint gets a causal state. Age-conditioned MFE
percentile lookup tables are built from TRAIN ONLY and frozen; val/test read
the frozen tables. State at the actual policy DECISION checkpoint is used for
attribution downstream (never the first checkpoint).

States: PROLIFIC_EXPANDING, HEALTHY_ESTABLISHED, ORDINARY, WEAKENING, TERMINAL.
No state uses future regime outcomes.
"""

from __future__ import annotations
import numpy as np
import pandas as pd
import common as C

# age buckets (seconds since entry) for MFE percentile conditioning
AGE_EDGES = np.array([0, 30, 60, 90, 120, 150, 180, 240, 300, 420, 600, 900, 1e9])

# frozen state thresholds (selected on train/val reasoning; NOT test)
PROLIFIC_PCTILE = 0.75
HEALTHY_PCTILE = 0.50
WEAK_RETURN = 0.0        # aligned 30s return below this == local weakness
TERMINAL_GIVEBACK = 0.5  # giveback fraction of MFE


def build_age_pctile_tables(train_chk: pd.DataFrame) -> dict:
    """For each age bucket, store sorted MFE-ATR array (train) for percentile lookup."""
    ab = np.digitize(train_chk["seconds_since_entry"].values, AGE_EDGES) - 1
    tables = {}
    mfe = train_chk["trade_mfe_atr"].values
    for b in range(len(AGE_EDGES) - 1):
        vals = np.sort(mfe[ab == b])
        tables[b] = vals if len(vals) else np.array([0.0])
    return tables


def apply_age_pctile(chk: pd.DataFrame, tables: dict) -> np.ndarray:
    ab = np.digitize(chk["seconds_since_entry"].values, AGE_EDGES) - 1
    mfe = chk["trade_mfe_atr"].values
    out = np.full(len(chk), np.nan)
    for b, sorted_vals in tables.items():
        m = ab == b
        if not m.any():
            continue
        pos = np.searchsorted(sorted_vals, mfe[m], side="right")
        out[m] = pos / len(sorted_vals)
    return np.clip(out, 0.0, 1.0)


def assign_states(chk: pd.DataFrame, pctile: np.ndarray) -> np.ndarray:
    """Hierarchical causal state assignment. All inputs are as-of the checkpoint."""
    n = len(chk)
    state = np.full(n, "ORDINARY", dtype=object)

    giveback = chk["giveback_fraction"].values
    ar30 = chk.get("aligned_return_30s", pd.Series(np.zeros(n))).values
    ar180 = chk.get("aligned_return_180s", pd.Series(np.zeros(n))).values
    eff180 = chk.get("directional_efficiency_180s", pd.Series(np.zeros(n))).values
    intact5m = chk.get("structure_intact_5m", pd.Series(np.ones(n))).values
    brk5m = chk.get("structure_break_against_5m", pd.Series(np.zeros(n))).values
    slope180 = chk.get("aligned_slope_180s", pd.Series(np.zeros(n))).values

    local_weak = (ar30 < WEAK_RETURN) | (np.nan_to_num(giveback) > 0.25)
    htf_strong = (np.nan_to_num(ar180) > 0) & (np.nan_to_num(intact5m, nan=1.0) > 0.5)
    htf_broken = (np.nan_to_num(brk5m) > 0.5) | (np.nan_to_num(ar180) < 0)

    # TERMINAL: deep giveback AND higher-tf deteriorating
    terminal = (np.nan_to_num(giveback) >= TERMINAL_GIVEBACK) & htf_broken & \
        (np.nan_to_num(eff180) < 0)
    # WEAKENING: local weakness AND (htf broken OR not strong), not terminal
    weakening = local_weak & (htf_broken | ~htf_strong)
    # PROLIFIC: top percentile, expanding, structure intact, no local weakness
    prolific = (pctile >= PROLIFIC_PCTILE) & (np.nan_to_num(slope180) > 0) & \
        htf_strong & ~local_weak
    # HEALTHY: solid percentile, structure intact, not weak
    healthy = (pctile >= HEALTHY_PCTILE) & htf_strong & ~local_weak

    state[healthy] = "HEALTHY_ESTABLISHED"
    state[prolific] = "PROLIFIC_EXPANDING"
    state[weakening] = "WEAKENING"
    state[terminal] = "TERMINAL"
    return state


def add_transitions(chk: pd.DataFrame) -> pd.DataFrame:
    """previous_state, state_start_time, seconds_in_state, ever/first/last prolific."""
    df = chk.sort_values(["episode_id", "seconds_since_entry"]).copy()
    ep = df["episode_id"].values
    st = df["state"].values
    t = df["observation_time"].values.astype(np.int64)
    n = len(df)

    prev = np.empty(n, dtype=object)
    start_t = np.empty(n, dtype=np.int64)
    reason = np.empty(n, dtype=object)
    ever_pro = np.zeros(n, dtype=bool)
    first_pro = np.zeros(n, dtype=np.int64)
    last_pro = np.zeros(n, dtype=np.int64)

    i = 0
    while i < n:
        j = i
        while j < n and ep[j] == ep[i]:
            j += 1
        cur_start = t[i]
        cur_first_pro = 0
        cur_last_pro = 0
        seen_pro = False
        for k in range(i, j):
            if k == i:
                prev[k] = "START"
                cur_start = t[k]
                reason[k] = "init:" + st[k]
            else:
                prev[k] = st[k - 1]
                if st[k] != st[k - 1]:
                    cur_start = t[k]
                    reason[k] = f"{st[k-1]}->{st[k]}"
                else:
                    reason[k] = "hold"
            start_t[k] = cur_start
            if st[k] == "PROLIFIC_EXPANDING":
                if not seen_pro:
                    cur_first_pro = t[k]
                    seen_pro = True
                cur_last_pro = t[k]
            # CAUSAL: as-of checkpoint k only (fixes future-trajectory leak).
            ever_pro[k] = seen_pro
            first_pro[k] = cur_first_pro
            last_pro[k] = cur_last_pro
        i = j

    df["previous_state"] = prev
    df["state_start_time"] = start_t
    df["seconds_in_state"] = (t - start_t) / 1e9
    df["state_transition_reason"] = reason
    df["ever_prolific"] = ever_pro
    df["first_prolific_time"] = first_pro
    df["last_prolific_time"] = last_pro
    return df


def build(full: pd.DataFrame):
    """full = atlas checkpoints merged with MTF context. Returns full+state cols."""
    print("=" * 70)
    print("Phase 3 — regime-quality state machine")
    print("=" * 70)
    train = full[full["period"] == "train"]
    tables = build_age_pctile_tables(train)
    print(f"  age-pctile tables built on {len(train):,} train checkpoints "
          f"({len(tables)} age buckets)")

    pctile = apply_age_pctile(full, tables)
    full = full.copy()
    full["mfe_age_pctile"] = pctile
    full["state"] = assign_states(full, pctile)
    full = add_transitions(full)

    # distribution audit ------------------------------------------------------
    dist = (full.groupby(["period", "state"]).size()
            .reset_index(name="n_checkpoints"))
    # episode-level: was the episode EVER in each state
    ep_state = (full.groupby("episode_id")["state"]
                .agg(lambda s: s.value_counts().index[0]))  # modal state (diagnostic only)
    ever = full.groupby(["period", "episode_id"])["ever_prolific"].max()
    print("\n  Checkpoint state distribution:")
    for period in ["train", "val", "test"]:
        sub = full[full["period"] == period]
        vc = sub["state"].value_counts()
        tot = len(sub)
        print(f"    [{period}] " + "  ".join(f"{k}={v}({v/tot:.1%})" for k, v in vc.items()))
        top_frac = vc.iloc[0] / tot
        pro_frac = (sub["state"] == "PROLIFIC_EXPANDING").mean()
        assert top_frac <= 0.98, f"DEGENERATE: {period} top state {top_frac:.1%} > 98%"
        assert pro_frac > 0.001, f"DEGENERATE: {period} prolific frac {pro_frac:.3%} ~ 0"

    # save artifacts
    keep = ["episode_id", "observation_time", "seconds_since_entry", "period",
            "direction", "state", "previous_state", "state_start_time",
            "seconds_in_state", "state_transition_reason", "ever_prolific",
            "first_prolific_time", "last_prolific_time", "mfe_age_pctile"]
    full[keep].to_parquet(C.RESULTS / "regime_state_checkpoints.parquet", index=False)
    trans = full[full["state_transition_reason"].str.contains("->", na=False)]
    trans[keep].to_parquet(C.RESULTS / "regime_state_transitions.parquet", index=False)
    dist.to_parquet(C.RESULTS / "regime_state_distribution.parquet", index=False)

    contract = {
        "states": ["PROLIFIC_EXPANDING", "HEALTHY_ESTABLISHED", "ORDINARY",
                   "WEAKENING", "TERMINAL"],
        "age_edges_seconds": AGE_EDGES.tolist(),
        "thresholds": {
            "prolific_pctile": PROLIFIC_PCTILE, "healthy_pctile": HEALTHY_PCTILE,
            "weak_return": WEAK_RETURN, "terminal_giveback": TERMINAL_GIVEBACK,
        },
        "causal_inputs": ["mfe_age_pctile (train-frozen)", "aligned_return_30s/180s",
                          "directional_efficiency_180s", "aligned_slope_180s",
                          "structure_intact_5m", "structure_break_against_5m",
                          "giveback_fraction"],
        "attribution_rule": "state attached at the DECISION checkpoint (never first).",
        "n_transitions": int(len(trans)),
    }
    C.savej(contract, C.RESULTS / "regime_state_contract.json")
    print(f"\n  transitions: {len(trans):,}  |  ever-prolific episodes: "
          f"{int(ever.sum()):,}/{ever.groupby(level=0).size().sum():,}")
    return full


if __name__ == "__main__":
    import build_full_mtf_context as B
    full = B.main(cache=True)
    atlas, _ = C.load_atlas()
    atlas = atlas[atlas["period"].isin(["train", "val", "test"])].reset_index(drop=True)
    # merge needed atlas fields
    merge_cols = ["giveback_fraction", "trade_mfe_atr", "current_progress_atr",
                  "max_progress_atr", "minutes_since_rth_open"]
    for c in merge_cols:
        full[c] = atlas[c].values
    build(full)
