# Databento Raw-Data Timestamp & Structure Forensic Report

**Date:** 2026-08-14  
**Audit Scope:** Repository-wide Databento market data, download manifests, raw parquet files, derived aggregation pipelines, and NautilusTrader catalog bars.

---

## Executive Summary

> **Canonical bar-availability contract:** Raw Databento OHLCV bars are open-stamped. Offline research may normalize derived bars to close-stamped indices. NautilusTrader catalogs preserve open-stamped `ts_event` and set `ts_init = ts_event + bar duration`. In all representations, complete OHLCV must not be observable before interval close.

1. **Raw Databento 1s Bars (`data/raw/*_1s_*.parquet`)** are strictly **OPEN-STAMPED** (`ts_event` index). A bar with timestamp `16:00:00` represents the interval $[16:00:00, 16:00:01)$. It is only causally complete and available at `16:00:01`.
2. **Higher Timeframes (1m, 3m, 5m)**:
   - 1s, 1m, 5m: **Empirically verified** on disk in active catalogs (`data/catalog/{NQ,ES}_v0_2020_2026`).
   - 3m: **Contract defined / derived** by canonical rule (`ts_init_delta = 180s`).
   - All higher timeframes are **DERIVED_FROM_1S** via Pandas resampling. No direct 1m/3m/5m raw downloads exist.
3. **NautilusTrader Catalogs (`data/catalog/NQ_v0_2020_2026/`, `data/catalog/ES_v0_2020_2026/`)** store two distinct timestamps:
   - `ts_event`: **Interval OPEN** time (e.g. `16:00:00` for both 1s and 1m).
   - `ts_init`: **Interval CLOSE / Causal Dispatch** time (e.g. `16:00:01` for 1s, `16:01:00` for 1m, `16:05:00` for 5m).
4. **Guardrail Verdict:** `CURRENT_TIMESTAMP_GUARDRAIL_PARTIALLY_CORRECT`.
   - The catalog on disk and the builder scripts apply `ts_init_delta = bar_duration` for ALL bar types (including 1s: +1s, 1m: +60s, 5m: +300s).
   - Legacy documentation in `CLAUDE.md` incorrectly claimed "1s bars need no adjustment (`delta=0`)". In reality, applying `delta=0` to open-stamped 1s bars produces a 1-second look-ahead bias in the NT event loop.
   - The guardrail validates semantic availability: `if nt_ts_event_semantic == "OPEN_STAMPED": ts_init - ts_event == bar_duration_ns`.

---

## 1. Raw Databento Data Discovered

| Dataset | Path | Schema | Format | Date Range | Stored Index | Semantic |
|---|---|---|---|---|---|---|
| **NQ Volume Continuous 1s** | `data/raw/NQ_v0_1s_{2016..2025,2026_ytd}.parquet` | `ohlcv-1s` (`rtype: 32`) | Parquet | 2016–2026 YTD | `ts_event` (UTC) | **Interval OPEN** |
| **ES Volume Continuous 1s** | `data/raw/ES_v0_1s_{2016..2025,2026_ytd}.parquet` | `ohlcv-1s` (`rtype: 32`) | Parquet | 2016–2026 YTD | `ts_event` (UTC) | **Interval OPEN** |
| **YM Volume Continuous 1s** | `data/raw/YM_v0_1s_{2016..2025,2026_ytd}.parquet` | `ohlcv-1s` (`rtype: 32`) | Parquet | 2016–2026 YTD | `ts_event` (UTC) | **Interval OPEN** |
| **NQ MBP-1 Ticks (2026)** | `data/raw/NQ_v0_mbp1_2026_{01..04}.parquet` | `mbp-1` (L1 + Trades) | Parquet | 2026-01 to 2026-04 | `ts_recv` (UTC) | **Receipt / Event Tick** |
| **ES MBP-1 Ticks (2026)** | `data/raw/ES_v0_mbp1_2026_{01..04}.parquet` | `mbp-1` (L1 + Trades) | Parquet | 2026-01 to 2026-04 | `ts_recv` (UTC) | **Receipt / Event Tick** |
| **YM MBP-1 Ticks (2026)** | `data/raw/YM_v0_mbp1_2026_{01..04}.parquet` | `mbp-1` (L1 + Trades) | Parquet | 2026-01 to 2026-04 | `ts_recv` (UTC) | **Receipt / Event Tick** |
| **Legacy Calendar Continuous** | `data/raw/legacy_c0/*.parquet` | `ohlcv-1s`, `trades`, `bbo`, `mbp-1` | Parquet | 2016–2026 | Mixed | Deprecated `.c.0` |

---

## 2. Actual Timestamp Structure & Consecutive Sample Evidence

### Raw 1s Bar Parquet (`data/raw/NQ_v0_1s_2024.parquet`)
- Schema: `['rtype', 'publisher_id', 'instrument_id', 'open', 'high', 'low', 'close', 'volume', 'symbol', 'ts_event']`
- Sample consecutive records:
  ```text
  ts_event (UTC)               open       high        low      close  volume  symbol
  2024-01-05 16:00:00+00:00  16563.75   16566.25   16563.25   16566.00     104  NQ.v.0
  2024-01-05 16:00:01+00:00  16566.50   16567.00   16565.75   16566.25      49  NQ.v.0
  2024-01-05 16:00:02+00:00  16566.00   16566.25   16565.25   16565.25      10  NQ.v.0
  ```
- **Proof of OPEN semantic:**
  In Databento's GLBX.MDP3 MDP 3.0 specification, `ts_event` marks the start of the 1-second interval. The trade prices occurring during `16:00:00.000` to `16:00:00.999` are aggregated into the record timestamped `16:00:00`. The final trade (`close`) is only finalized when the second ticks over to `16:00:01`.

---

## 3. Transformation Lineage

```text
Databento Raw Parquet (data/raw/*_1s_*.parquet)
    │  [Index: ts_event (OPEN Time, UTC)]
    │
    ├─── Offline Research Aggregation (utils/resampling.py)
    │        └─ resample("1min", label="right", closed="left")
    │           => DataFrame Index = Interval CLOSE Time (e.g. 10:01:00 CT)
    │
    └─── NautilusTrader Catalog Build (scripts/build_v0_multi_year_catalog.py)
             ├─ 1s Bars:
             │    BarDataWrangler.process(df, ts_init_delta=1_000_000_000)
             │    => ts_event = 16:00:00 (OPEN), ts_init = 16:00:01 (CLOSE)
             │
             ├─ 1m Bars:
             │    df.resample("1min", label="left", closed="left") [Index = OPEN]
             │    BarDataWrangler.process(df, ts_init_delta=60_000_000_000)
             │    => ts_event = 16:00:00 (OPEN), ts_init = 16:01:00 (CLOSE)
             │
             └─ 5m Bars:
                  df.resample("5min", label="left", closed="left") [Index = OPEN]
                  BarDataWrangler.process(df, ts_init_delta=300_000_000_000)
                  => ts_event = 16:00:00 (OPEN), ts_init = 16:05:00 (CLOSE)
```

---

## 4. End-to-End Concrete Interval Test

**Economic Interval:** 10:00:00.000 CT to 10:00:59.999 CT on 2024-01-05 (16:00:00 to 16:00:59 UTC).

| Stage / Representation | Timestamp Key | Timestamp Value (UTC) | Timestamp Value (CT) | Semantic |
|---|---|---|---|---|
| **Raw Databento 1s File** | `ts_event` (first bar) | `2024-01-05 16:00:00` | `2024-01-05 10:00:00` | Interval OPEN $[10:00:00, 10:00:01)$ |
| **Raw Databento 1s File** | `ts_event` (last bar) | `2024-01-05 16:00:59` | `2024-01-05 10:00:59` | Interval OPEN $[10:00:59, 10:01:00)$ |
| **NT Catalog 1s Bar** | `ts_event` | `2024-01-05 16:00:00` | `2024-01-05 10:00:00` | Interval OPEN |
| **NT Catalog 1s Bar** | `ts_init` | `2024-01-05 16:00:01` | `2024-01-05 10:00:01` | **Causal Availability / Dispatch** |
| **Offline Derived 1m Bar** | `Index` (`label='right'`) | `2024-01-05 16:01:00` | `2024-01-05 10:01:00` | **Causal Availability / Close** |
| **NT Catalog 1m Bar** | `ts_event` | `2024-01-05 16:00:00` | `2024-01-05 10:00:00` | Interval OPEN |
| **NT Catalog 1m Bar** | `ts_init` | `2024-01-05 16:01:00` | `2024-01-05 10:01:00` | **Causal Availability / Dispatch** |

---

## 5. RTH Session Boundary Interpretation

Because raw Databento data is OPEN-stamped and completed research/NT bars are CLOSE-stamped, session boundaries must be explicitly qualified:

| Clock Time (CT) | Meaning if OPEN-STAMPED (Raw Databento) | Meaning if CLOSE-STAMPED (NT `ts_init` / Offline) |
|---|---|---|
| **08:30:00 CT** | **RTH First Second** (Interval $[08:30:00, 08:30:01)$) | **ETH Pre-Open Bar** (Interval $[08:29:00, 08:30:00)$ formed during pre-market) |
| **08:31:00 CT** | **RTH Second Minute** (Interval $[08:31:00, 08:32:00)$) | **RTH First Complete 1m Bar** (Interval $[08:30:00, 08:31:00)$ completed) |
| **15:15:00 CT** | **ETH Post-Market Second** (Cash close has occurred) | **RTH Final Complete 1m Bar** (Interval $[15:14:00, 15:15:00)$ completed) |
| **15:16:00 CT** | **ETH Post-Market Minute** | **ETH Post-Close Bar** (Interval $[15:15:00, 15:16:00)$ formed after close) |

---

## 6. Current Guardrail Evaluation & Verdict

### Verdict: `CURRENT_TIMESTAMP_GUARDRAIL_PARTIALLY_CORRECT`

- **Correct:**
  - The actual catalog on disk and builder scripts apply `ts_init_delta = 60_000_000_000` (1m) and `300_000_000_000` (5m).
  - The catalog on disk applies `ts_init_delta = 1_000_000_000` (1s).
  - `utils/resampling.py` uses `resample("1min", label="right", closed="left")`, which correctly aligns completed bars to CLOSE time.

- **Incorrect in Documentation / Rules:**
  - `CLAUDE.md` Rule 3 previously stated: *"1s bars need no adjustment."*
  - This rule was mistaken: if 1s bars are wrangled with `delta=0`, then `ts_init = ts_event` (OPEN time), which allows NT event handlers running at 10:00:00 to see the trade prices that occur between 10:00:00 and 10:00:01.
  - The correct rule is: **`ts_init_delta == bar_duration_ns` for all discrete bar types**.

---

## 7. Recommended Canonical Contract

Formalize the repository metadata invariant:

```yaml
timestamp_contract:
  raw_source:
    format: "databento_ohlcv_1s"
    timestamp_semantic: "OPEN_STAMPED"
    timezone: "UTC"
  offline_research:
    aggregation: "resample('1min', label='right', closed='left')"
    timestamp_semantic: "CLOSE_STAMPED"
  nautilus_catalog:
    ts_event_semantic: "OPEN_STAMPED"
    ts_init_semantic: "CLOSE_STAMPED"
    ts_init_formula: "ts_event + bar_duration_ns"
```

For any bar duration $D$:
$$\text{ts\_init} = \text{ts\_event} + D$$
- 1s: $\text{ts\_init} = \text{ts\_event} + 1\,\text{s}$ ($1{,}000{,}000{,}000\,\text{ns}$)
- 1m: $\text{ts\_init} = \text{ts\_event} + 60\,\text{s}$ ($60{,}000{,}000{,}000\,\text{ns}$)
- 3m: $\text{ts\_init} = \text{ts\_event} + 180\,\text{s}$ ($180{,}000{,}000{,}000\,\text{ns}$)
- 5m: $\text{ts\_init} = \text{ts\_event} + 300\,\text{s}$ ($300{,}000{,}000{,}000\,\text{ns}$)
