import pandas as pd
import pyarrow.parquet as pq
import pyarrow as pa

c1 = pd.read_parquet("backtests/hmm_state_filtered/results/nq_kmeans_4_s0_sl1p5_ancflip_minatr15p0_vwapF_qty2_ptr2p0_2026/trades.parquet").iloc[0]

entry_ts = int(c1["entry_ts"])
exit_ts_nt = int(c1["exit_ts"])

start_dt = pd.to_datetime(entry_ts - 5 * 1_000_000_000, unit='ns', utc=True)
end_dt = pd.to_datetime(exit_ts_nt + 5 * 1_000_000_000, unit='ns', utc=True)

mbp_path = "data/raw/NQ_v0_mbp1_2026_01.parquet"
table = pq.read_table(
    mbp_path,
    columns=["ts_recv", "ts_event", "bid_px_00", "ask_px_00"], # Included ts_recv!
    filters=[
        ("ts_recv", ">=", pa.scalar(start_dt.to_pydatetime())),
        ("ts_recv", "<=", pa.scalar(end_dt.to_pydatetime()))
    ]
)
df_ticks = table.to_pandas()
print(f"Loaded {len(df_ticks)} ticks with ts_recv in columns.")
print("Index name:", df_ticks.index.name)
print("Index type:", type(df_ticks.index))
print("Head index:")
print(df_ticks.index[:5])

ts_ns = df_ticks.index.values.astype("int64")
print("ts_ns min:", ts_ns.min())
print("ts_ns max:", ts_ns.max())
print("ts_ns max - exit_ts_nt:", ts_ns.max() - exit_ts_nt)
