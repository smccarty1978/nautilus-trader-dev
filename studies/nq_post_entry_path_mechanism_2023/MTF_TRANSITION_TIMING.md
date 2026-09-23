# MTF transition timing — does the 5m turn lead the move or follow it?

**Population:** 2023 development sessions only (6,024 T0 trades).

**What is measured.** A transition is the first higher-timeframe regime that starts strictly inside
(T0, terminal flip) with direction equal to the trade's.
- **Transition time:** the regime's detection bar close (`start_ns`). It is exact: the regime-link chains
  reproduce the MTF directions on every checkpoint row we compared (0 mismatches over about 103k rows).
- **Favourable touch time:** the close of the 1s bar that first reaches each level, measured from the
  original T0 entry in `atr_entry_1m`.
- **Category:** the highest favourable level already touched *at or before* the transition. Ties at the same
  second are counted; there are 5 in total.

## 5m: trades whose 5m was against them at T0 and later turned their way (N = 1,048)

| 5m INTO-alignment happened… | N | % | median s to 5m | median s to +0.5A / +1A / +2A | win % | +2A % | +3A % | −1A % | next level never reached |
|---|---|---|---|---|---|---|---|---|---|
| **before +0.5A** | 29 | **2.8** | 105 | 166 / 229 / 423 | 51.7 | 62.1 | 44.8 | 41.4 | 6 |
| between +0.5A and +1A | 66 | 6.3 | 165 | 45 / 233 / 439 | 48.5 | 53.0 | 30.3 | 48.5 | 20 |
| between +1A and +1.5A | 114 | 10.9 | 285 | 70 / 169 / 544 | 57.0 | 55.3 | 41.2 | 39.5 | 23 |
| between +1.5A and +2A | 169 | 16.1 | 345 | 79 / 161 / 477 | 76.9 | 77.5 | 46.2 | 32.5 | 38 |
| **after +2A** (before +3A) | 356 | **34.0** | 525 | 54 / 156 / 374 | 91.3 | 100 | 67.7 | 21.3 | 115 |
| **after +3A** | 314 | **30.0** | 705 | 39 / 121 / 299 | 96.8 | 100 | 100 | 20.4 | — |

**The reverse view.** Of the 1,252 trades that reached +2A with a misaligned 5m at T0, the 5m turned their
way:
- before +0.5A in **1.4%**;
- at or before +2A in **19.9%**;
- after +2A in **53.4%**;
- never, before the terminal flip, in **26.8%**.

**15m and 1h are even later.** Their INTO-alignment comes after +2A in 83% (15m) and 68% (1h) of
occurrences, and it never happens before the terminal flip for 70.5% (15m) and 93.8% (1h) of misaligned +2A
trades.

**Trades whose 5m was aligned at T0.** A 5m transition *away* before the terminal flip is almost nonexistent
(0.08% of 2,392). The 1m flips first.

## Answer

**The move comes first and the 5m transition follows it.** In 97% of the trades where the 5m turns, the
trade is already at +0.5A or better when it turns, and in 64% it is already past +2A. The earlier finding
that "future 5m alignment goes with success" (87.5% +2A) is mostly the 5m regime *registering* a move that
has already happened.

This is an ordering statement, not a causal one. The 29 trades where the 5m led are too few to characterise.

Across every supported initial state the 5m turns before +0.5A in only 0.8–4.8% of cases and after +1A in
86–94% (`INITIAL_STATE_MAP.md`).

Machine-readable: `artifacts/MTF_TIMING.{csv,parquet}`, `artifacts/ANALYSIS_RESULTS.json` (`mtf_reverse_view`).
