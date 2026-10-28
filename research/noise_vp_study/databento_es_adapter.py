"""
Databento ES Data Adapter & Indicator Pipeline (databento_es_adapter.py)
Location: research/noise_vp_study/databento_es_adapter.py

Ingests raw 1-minute Databento Parquet files or Nautilus ParquetDataCatalog for ES,
filters for Regular Trading Hours (RTH: 09:30–16:00 ET), computes Prior-Day Volume Profile
(POC, VAH, VAL), 15m ATR, and strictly causal Dynamic Noise Bands (Time-of-Day Volatility
Envelope shifted by 1 day), and serializes the result into a clean Parquet cache ready for NautilusTrader.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd


class DatabentoESAdapter:
    """
    Ingests raw 1-minute Databento Parquet files or Nautilus ParquetDataCatalog for ES,
    filters for RTH, computes Prior-Day Volume Profile (POC, VAH, VAL) and Dynamic Noise Bands,
    and outputs a feature-enriched Parquet cache for NautilusTrader.
    """

    def __init__(
        self,
        input_parquet_path: Optional[str | Path] = None,
        catalog_path: str | Path = "data/catalog/ES_1S_V2",
        output_cache_path: str | Path = "research/noise_vp_study/es_rth_cache.parquet",
        es_tick_size: float = 0.25,
        value_area_pct: float = 0.70,
        band_multiplier: float = 1.0,
        rolling_days: int = 14,
        start_date: str = "2024-01-01",
    ) -> None:
        self.input_path = Path(input_parquet_path) if input_parquet_path else None
        self.catalog_path = Path(catalog_path)
        self.output_path = Path(output_cache_path)
        self.tick_size = es_tick_size
        self.va_pct = value_area_pct
        self.band_multiplier = band_multiplier
        self.rolling_days = rolling_days
        self.start_date = start_date

    def load_data(self) -> pd.DataFrame:
        """Loads 1-minute bar data from raw parquet file or ParquetDataCatalog."""
        if self.input_path and self.input_path.exists() and not self.input_path.is_dir():
            print(f"[ESAdapter] Loading raw Databento file from {self.input_path}...")
            df = pd.read_parquet(self.input_path)

            if "ts_event" in df.columns:
                df["timestamp"] = pd.to_datetime(df["ts_event"])
            elif "timestamp" in df.columns:
                df["timestamp"] = pd.to_datetime(df["timestamp"])
            elif isinstance(df.index, pd.DatetimeIndex):
                df["timestamp"] = df.index
            else:
                raise ValueError("Parquet file must contain 'ts_event', 'timestamp' column or a DatetimeIndex.")

            if df["timestamp"].dt.tz is None:
                df["timestamp"] = df["timestamp"].dt.tz_localize("UTC")
            df["timestamp"] = df["timestamp"].dt.tz_convert("US/Eastern")
            df.set_index("timestamp", inplace=True)
            df.sort_index(inplace=True)
            return df

        # Fallback to loading from Nautilus ParquetDataCatalog
        print(f"[ESAdapter] Loading 1-minute bars from Nautilus Catalog: {self.catalog_path} (from {self.start_date})...")
        from nautilus_trader.persistence.catalog import ParquetDataCatalog

        catalog = ParquetDataCatalog(str(self.catalog_path))
        t0 = time.time()
        bars = catalog.bars(
            bar_types=["ES.XCME-1-MINUTE-LAST-EXTERNAL"],
            start=self.start_date,
        )
        print(f"[ESAdapter] Loaded {len(bars):,} bars from catalog in {time.time() - t0:.2f}s.")

        n = len(bars)
        closes = np.empty(n, dtype=np.float64)
        highs = np.empty(n, dtype=np.float64)
        lows = np.empty(n, dtype=np.float64)
        opens = np.empty(n, dtype=np.float64)
        vols = np.empty(n, dtype=np.float64)
        ts = np.empty(n, dtype=np.int64)

        for i, b in enumerate(bars):
            opens[i] = float(b.open)
            highs[i] = float(b.high)
            lows[i] = float(b.low)
            closes[i] = float(b.close)
            vols[i] = float(b.volume)
            ts[i] = b.ts_event

        df = pd.DataFrame({
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": vols,
            "ts_event": ts,
        })
        df["timestamp"] = pd.to_datetime(df["ts_event"], unit="ns", utc=True).dt.tz_convert("America/New_York")
        df.set_index("timestamp", inplace=True)
        df.sort_index(inplace=True)
        return df

    def process(self) -> pd.DataFrame:
        df = self.load_data()

        # 2. Filter for Regular Trading Hours (RTH: 09:30 - 16:00 ET)
        df["date"] = df.index.date
        df["time"] = df.index.time
        rth_mask = (df["time"] >= pd.to_datetime("09:30:00").time()) & (
            df["time"] <= pd.to_datetime("16:00:00").time()
        )
        df_rth = df.loc[rth_mask].copy()

        print(
            f"[ESAdapter] Filtered to {len(df_rth):,} RTH bars across "
            f"{df_rth['date'].nunique():,} sessions."
        )

        # 3. Compute Session VWAP and 15-Minute ATR
        print("[ESAdapter] Computing Session VWAP and 15m ATR...")
        df_rth["typical_price"] = (df_rth["high"] + df_rth["low"] + df_rth["close"]) / 3.0
        df_rth["pv"] = df_rth["typical_price"] * df_rth["volume"]

        grouped_date = df_rth.groupby("date")
        df_rth["cum_pv"] = grouped_date["pv"].cumsum()
        df_rth["cum_vol"] = grouped_date["volume"].cumsum()
        df_rth["vwap"] = df_rth["cum_pv"] / np.maximum(df_rth["cum_vol"], 1.0)

        # Intraday True Range (avoiding distortion from overnight gaps)
        high_low = df_rth["high"] - df_rth["low"]
        high_close_prev = np.abs(df_rth["high"] - grouped_date["close"].shift(1))
        low_close_prev = np.abs(df_rth["low"] - grouped_date["close"].shift(1))
        true_range = pd.concat([high_low, high_close_prev, low_close_prev], axis=1).max(axis=1)
        true_range = true_range.fillna(high_low)
        df_rth["atr_15m"] = grouped_date.apply(
            lambda g: true_range.loc[g.index].rolling(window=15, min_periods=1).mean(),
            include_groups=False,
        ).reset_index(level=0, drop=True)

        # 4. Compute Prior-Day Volume Profile (POC, VAH, VAL) using dual-expansion algorithm
        print("[ESAdapter] Computing Prior-Day Volume Profile (POC, VAH, VAL)...")
        dates = sorted(df_rth["date"].unique())
        daily_vp_map = {}

        for d in dates:
            day_data = df_rth[df_rth["date"] == d]
            if len(day_data) == 0:
                continue

            low_min = day_data["low"].min()
            high_max = day_data["high"].max()

            # Bin prices to ES tick size (0.25 pt)
            bins = np.arange(
                np.floor(low_min / self.tick_size) * self.tick_size,
                np.ceil(high_max / self.tick_size) * self.tick_size + self.tick_size,
                self.tick_size,
            )

            # Vectorized binning of volume
            bin_indices = np.clip(
                np.round((day_data["close"].values - bins[0]) / self.tick_size).astype(int),
                0,
                len(bins) - 2,
            )
            vol_profile = np.bincount(bin_indices, weights=day_data["volume"].values, minlength=len(bins) - 1)

            total_vol = vol_profile.sum()
            if total_vol <= 0:
                continue

            # Point of Control (POC) = bin with max volume
            poc_idx = int(np.argmax(vol_profile))
            poc = (bins[poc_idx] + bins[poc_idx + 1]) / 2.0

            # Value Area High (VAH) & Low (VAL) covering 70% of volume via dual expansion
            target_vol = total_vol * self.va_pct
            cur_vol = vol_profile[poc_idx]
            lo_idx = poc_idx
            hi_idx = poc_idx
            n_bins = len(vol_profile)

            while cur_vol < target_vol and (lo_idx > 0 or hi_idx < n_bins - 1):
                up_vol = vol_profile[hi_idx + 1] if hi_idx + 1 < n_bins else 0.0
                dn_vol = vol_profile[lo_idx - 1] if lo_idx - 1 >= 0 else 0.0

                if up_vol > dn_vol:
                    cur_vol += up_vol
                    hi_idx += 1
                elif dn_vol > up_vol:
                    cur_vol += dn_vol
                    lo_idx -= 1
                else:
                    cur_vol += up_vol + dn_vol
                    hi_idx = min(hi_idx + 1, n_bins - 1)
                    lo_idx = max(lo_idx - 1, 0)

            val = bins[lo_idx]
            vah = bins[hi_idx + 1]

            daily_vp_map[d] = {"prev_poc": float(poc), "prev_vah": float(vah), "prev_val": float(val)}

        # Shift Volume Profile metrics to become *Prior-Day* values for the next session (Strictly Causal)
        df_rth["prev_poc"] = np.nan
        df_rth["prev_vah"] = np.nan
        df_rth["prev_val"] = np.nan

        for i in range(1, len(dates)):
            prev_d = dates[i - 1]
            curr_d = dates[i]
            if prev_d in daily_vp_map:
                vp = daily_vp_map[prev_d]
                mask = df_rth["date"] == curr_d
                df_rth.loc[mask, "prev_poc"] = vp["prev_poc"]
                df_rth.loc[mask, "prev_vah"] = vp["prev_vah"]
                df_rth.loc[mask, "prev_val"] = vp["prev_val"]

        # 5. Compute Dynamic ES Noise Bands (Authoritative Time-of-Day Volatility Cone)
        print("[ESAdapter] Computing Dynamic Noise Bands (Anchor Envelope + Time-of-Day Sigma)...")
        df_rth["minute_idx"] = grouped_date.cumcount()

        daily_open = grouped_date["open"].first()
        daily_close = grouped_date["close"].last()
        prev_rth_close = daily_close.shift(1)

        daily_df = pd.DataFrame({
            "rth_open": daily_open,
            "prev_rth_close": prev_rth_close,
        })
        daily_df["anchor_high"] = np.maximum(daily_df["rth_open"], daily_df["prev_rth_close"])
        daily_df["anchor_low"] = np.minimum(daily_df["rth_open"], daily_df["prev_rth_close"])

        # Pivot to compute time-of-day standard deviation from session open across historical sessions
        move_pivot = df_rth.pivot(index="date", columns="minute_idx", values="close")
        open_pivot = daily_df["rth_open"].reindex(move_pivot.index)
        abs_move_pivot = move_pivot.sub(open_pivot, axis=0).abs()

        # Strict Zero-Lookahead: shift(1) across trading days
        sigma_tod_pivot = (
            abs_move_pivot.shift(1)
            .rolling(window=self.rolling_days, min_periods=5)
            .mean()
            .bfill(axis=1)
            .ffill(axis=1)
        )
        sigma_tod_series = sigma_tod_pivot.stack(future_stack=True).rename("sigma_tod")

        df_rth = df_rth.reset_index().set_index(["date", "minute_idx"])
        df_rth["sigma_tod"] = sigma_tod_series
        df_rth = df_rth.reset_index().set_index("timestamp").sort_index()

        df_rth = df_rth.join(
            daily_df[["anchor_high", "anchor_low", "prev_rth_close"]],
            on="date",
        )

        # Dynamic Noise Bands
        df_rth["upper_band"] = df_rth["anchor_high"] + (self.band_multiplier * df_rth["sigma_tod"])
        df_rth["lower_band"] = df_rth["anchor_low"] - (self.band_multiplier * df_rth["sigma_tod"])

        # Standardize helper columns
        df_rth["p_59s"] = df_rth["close"]
        df_rth["p_00s"] = df_rth["open"]
        df_rth.index.name = "ts_event"

        # 6. Save Processed Cache
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        df_rth.to_parquet(self.output_path)
        print(f"[ESAdapter] Successfully saved processed ES Parquet cache to {self.output_path}")

        return df_rth


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Databento ES Data Adapter & Indicator Pipeline")
    parser.add_argument("--input", type=str, default=None, help="Path to raw Databento parquet")
    parser.add_argument("--catalog", type=str, default="data/catalog/ES_1S_V2", help="Path to catalog")
    parser.add_argument("--output", type=str, default="research/noise_vp_study/es_rth_cache.parquet", help="Path to output cache")
    parser.add_argument("--multiplier", type=float, default=1.0, help="Noise band multiplier")
    parser.add_argument("--start", type=str, default="2024-01-01", help="Start date for catalog load")
    args = parser.parse_args()

    adapter = DatabentoESAdapter(
        input_parquet_path=args.input,
        catalog_path=args.catalog,
        output_cache_path=args.output,
        band_multiplier=args.multiplier,
        start_date=args.start,
    )
    df_out = adapter.process()
