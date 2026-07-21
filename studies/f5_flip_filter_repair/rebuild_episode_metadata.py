"""Phase 3: Persist the rebuilt F2 episode metadata (direction, RTH/ETH
session, Chicago-local timestamp, month/year, period_role, entry-delay
bucket, ATR/volatility bucket, runner tier) built by common.repair_and_build_f2,
plus the required audit assertions.
"""
import json
import pandas as pd
from common import OUT, load_atlas, repair_and_build_f2


KEEP_COLS = [
    "episode_id", "population", "observation_time", "chicago_local_ts",
    "direction", "direction_repaired", "session", "month", "year",
    "period_role", "entry_delay_bucket", "atr_bucket", "runner_tier",
    "entry_price", "exit_price", "pnl_base", "ep_end_time", "exit_type",
    "ridge_log_fail_prob",
]


def run():
    df_atlas = load_atlas()
    f2_clean, viol_df = repair_and_build_f2(df_atlas)

    out_cols = [c for c in KEEP_COLS if c in f2_clean.columns]
    f2_clean[out_cols].to_parquet(OUT / "rebuilt_episode_metadata.parquet", index=False)

    audit = {
        "n_episodes": int(len(f2_clean)),
        "missing_direction": int(f2_clean["direction"].isna().sum()),
        "missing_session": int(f2_clean["session"].isna().sum()),
        "missing_month": int(f2_clean["month"].isna().sum()),
        "missing_period_role": int((f2_clean["period_role"] == "other").sum() + f2_clean["period_role"].isna().sum()),
        "direction_source": "rebuilt from canonical 'regime' column (0 nulls in F2; verified 100% match against any pre-existing non-null direction values)",
        "session_source": "RTH = 08:30-15:00 America/Chicago (project canonical, CLAUDE.md), DST-aware via tz_convert on tz-aware UTC observation_time",
        "session_distribution": f2_clean["session"].value_counts().to_dict(),
        "period_role_distribution": f2_clean["period_role"].value_counts().to_dict(),
        "entry_delay_bucket_note": "proxy: tertile of seconds_in_current_ordering within period_role (no direct flip-to-confirmation delay field persisted in the cached atlas); used only as a matching stratum for R3 controls, not as a primary economic metric.",
        "atr_bucket_note": "tertile of contemporaneous entry-time ATR within period_role.",
        "runner_tier_note": "top10/top5/top1 percentile of R0 baseline pnl_base, computed within period_role.",
    }
    with open(OUT / "metadata_audit.json", "w") as f:
        json.dump(audit, f, indent=2, default=str)

    assert audit["missing_direction"] == 0, "missing_direction != 0"
    assert audit["missing_session"] == 0, "missing_session != 0"
    assert audit["missing_month"] == 0, "missing_month != 0"
    assert audit["missing_period_role"] == 0, "missing_period_role != 0"

    print("Metadata rebuild assertions all PASS:", {k: v for k, v in audit.items() if k.startswith("missing")})
    return f2_clean


if __name__ == "__main__":
    import os, sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from common import PROJECT_ROOT
    os.chdir(PROJECT_ROOT)
    run()
