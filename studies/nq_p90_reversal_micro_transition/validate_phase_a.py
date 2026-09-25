import json
from pathlib import Path
import numpy as np
import pandas as pd

STUDY_DIR = Path(r"C:\Users\Scott McCarty\Projects\Nautilus Trader-nq_p90_reversal_micro_transition\studies\nq_p90_reversal_micro_transition")
OUTPUT_DIR = STUDY_DIR / "analysis"
TARGET_DIR = STUDY_DIR / "analysis_3fv"
TARGET_DIR.mkdir(parents=True, exist_ok=True)

# Load artifacts
with open(OUTPUT_DIR / "project_verdict.json") as f:
    verdict = json.load(f)

with open(OUTPUT_DIR / "project_3f_summary.json") as f:
    summary = json.load(f)

with open(OUTPUT_DIR / "diagnostic_model_results.json") as f:
    model_res = json.load(f)

with open(OUTPUT_DIR / "interpretable_1s_frontier.json") as f:
    frontier = json.load(f)

with open(OUTPUT_DIR / "true_vs_false_event_comparison.json") as f:
    t_vs_f = json.load(f)

with open(OUTPUT_DIR / "mbp1_incremental_results.json") as f:
    mbp1 = json.load(f)

# Trajectories parquet for row counts
traj_path = OUTPUT_DIR / "aligned_1s_trajectories.parquet"
df_traj = pd.read_parquet(traj_path, columns=["is_true_start", "offset_seconds", "is_new_extreme", "range_1s", "range_10s"])

print("Loaded artifacts successfully.")
print(f"df_traj shape: {df_traj.shape}")

# Verify 10,618 TRUE starts, 10,618 FALSE pauses
df_t0 = df_traj[df_traj["offset_seconds"] == 0]
n_true = int(df_t0["is_true_start"].sum())
n_false = int((~df_t0["is_true_start"]).sum())
total_obs = len(df_traj)
n_regimes = verdict["metrics"]["population_regimes"]

print(f"n_true: {n_true}, n_false: {n_false}, total_obs: {total_obs}, n_regimes: {n_regimes}")

# Verify mode of terminal extreme
new_ext_pcts = {}
for off in range(-5, 1):
    sub = df_traj[(df_traj["offset_seconds"] == off) & (df_traj["is_true_start"] == True)]
    pct = float(sub["is_new_extreme"].mean())
    new_ext_pcts[f"T{off}s"] = pct

print("New extreme percentage by offset (TRUE events):", new_ext_pcts)

# Range expansion ~40% over 10s baseline
sub_thrust = df_traj[(df_traj["offset_seconds"].isin([-5, -4, -3])) & (df_traj["is_true_start"] == True)]
mean_rng_1s = sub_thrust["range_1s"].mean()
mean_rng_10s_base = (sub_thrust["range_10s"] / 10.0).mean()
rng_expansion = (mean_rng_1s - mean_rng_10s_base) / mean_rng_10s_base
print(f"Thrust range 1s mean: {mean_rng_1s:.3f}, 10s normalized baseline: {mean_rng_10s_base:.3f}, expansion: {rng_expansion*100:.1f}%")

# Cohen's d values
cd_dist_tminus1 = t_vs_f["-1"]["features"]["dist_from_ext_pts"]["cohen_d"]
cd_close_tminus1 = t_vs_f["-1"]["features"]["fade_close_loc"]["cohen_d"]
cd_close_t0 = t_vs_f["0"]["features"]["fade_close_loc"]["cohen_d"]
cd_dist_t0 = t_vs_f["0"]["features"]["dist_from_ext_pts"]["cohen_d"]
max_cd_before_tminus3 = max(abs(t_vs_f[str(off)]["features"][feat]["cohen_d"]) for off in range(-15, -3) for feat in t_vs_f[str(off)]["features"])
print(f"Max |Cohen d| before T-3s: {max_cd_before_tminus3:.4f}")
print(f"Cohen d fade_close_loc T-1s: {cd_close_tminus1:.4f}, T0: {cd_close_t0:.4f}")
print(f"Cohen d dist_from_ext_pts T-1s: {cd_dist_tminus1:.4f}, T0: {cd_dist_t0:.4f}")
