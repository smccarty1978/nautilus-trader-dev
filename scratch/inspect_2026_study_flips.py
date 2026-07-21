import pandas as pd

study_path = "studies/v_a_excursion_regime/results_v0/compression_vwap_study.parquet"
df_study = pd.read_parquet(study_path)
df_study_2026 = df_study[df_study["year"] == 2026].copy()

# Convert signal_time to ET
df_study_2026["datetime_et"] = pd.to_datetime(df_study_2026["signal_time"], utc=True).dt.tz_convert("America/New_York")
df_study_2026["time_et"] = df_study_2026["datetime_et"].dt.time
is_rth = (df_study_2026["time_et"] >= pd.to_datetime("09:30:00").time()) & (df_study_2026["time_et"] < pd.to_datetime("16:00:00").time())
is_long = df_study_2026["signal_direction"] == 1
is_compressed = df_study_2026["tot_slow"] < 22.0
is_near_away = df_study_2026["cell"] == "near-away"

study_cohort = df_study_2026[is_rth & is_long & is_compressed & is_near_away].copy()
print(f"Total 2026 flips in study parquet: {len(df_study_2026)}")
print(f"Total 2026 RTH LONG compressed near-away flips in study parquet: {len(study_cohort)}")
if len(study_cohort) > 0:
    print("\nFirst 10 RTH LONG compressed near-away flips in study parquet:")
    print(study_cohort[["signal_time", "datetime_et", "tot_slow", "cell"]].head(10))
