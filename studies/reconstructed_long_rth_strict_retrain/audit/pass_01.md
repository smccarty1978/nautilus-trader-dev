# Causal & Look-Ahead Audit — Pass 01 (Availability-Framed)

**Study:** `reconstructed_long_rth_strict_retrain`  
**Audited Code & Data Surface:**
- `strategies/flip_prediction_collector.py`
- `backtests/nt_runtime/engine_builder.py`
- `backtests/nt_runtime/data_plan.py`
- `backtests/nt_runtime/output_manager.py`
- `scripts/check_collect_equivalence.py`
- Candidate checkpoint grid, MFE/MAE progress tracking, and feature snapshot timing under availability (`ts_init`) semantics.

**Date:** 2026-08-14  
**Auditor:** `lookahead-auditor`  
**Verdict:** `PASS` (0 CRITICAL, 0 WARNING)

---

## 1. Timestamp Availability & Causal Contract Verification (A1–H4)

| Rule | Area | Finding / Verification | Status |
|---|---|---|---|
| **A1** | Bar Timestamps | All bar availability times are defined by `ts_init` (interval CLOSE), not raw open-stamped `ts_event` | `CLEAR` |
| **A2** | `ts_init_delta` | `data_plan.py` enforces canonical delta: 1s is $+1\text{s}$ (`1_000_000_000 ns`), 1m is $+60\text{s}$ (`60_000_000_000 ns`) | `CLEAR` |
| **A3** | Availability Invariant | For every candidate at $T$: last 1s bar $\text{ts\_init} \le T$, last 1m bar $\text{ts\_init} \le T$, feature source $\text{ts\_avail} \le T$ | `CLEAR` |
| **A4** | Callback Timing | NautilusTrader BacktestEngine event loop is the sole dispatcher; no synthetic or future clock events | `CLEAR` |
| **A5** | Multi-TF Causal Order | `add_bars_causal_order` registers 1s bars before 1m bars, ensuring 1s bars closing at $T$ process before coincident 1m bars closing at $T$ | `CLEAR` |
| **B1–B4** | Feature Look-Ahead | No negative shifts, no centered windows, indicators compute on completed bars only | `CLEAR` |
| **B9–B10** | Tracker Reuse | Reuses canonical `OHLCVDeltaTracker` and `PriceLevelTracker` with explicit ATR passing and full RTH lifecycle (`reset_rth`/`end_rth`) | `CLEAR` |
| **C1–C2** | Label Construction | Opposing flip target resolution occurs strictly on subsequent regime flip event in `_on_regime_flip` | `CLEAR` |
| **C3** | Chronology Domain | `data_plan.py` enforces prohibited domain guards (rejects 2026) | `CLEAR` |
| **F1–F3** | Hysteresis / Progress | MFE/MAE progress windows enforce 120s gap constraint and update on 1s stream | `CLEAR` |

---

## 2. Formal Proof: Invariant at Candidate Observation Instant $T$

For a candidate declared at observation timestamp $T = \text{regime\_start\_ns} + (k + 1) \times 5\text{s}$:
1. **1s Bar Availability:** The 1s bar triggering evaluation has $\text{ts\_init} \le T$. The candidate evaluation reads `self.last_close` (the close of the bar whose $\text{ts\_init} \le T$), ensuring zero intra-bar or future leakage.
2. **1m Bar Availability:** The most recent 1m bar processed has $\text{ts\_init} \le T$. Regime indicators (Wilder ATR, Dual EMA) and Price Level trackers are evaluated strictly on completed 1m bars closing at or before $T$.
3. **Feature Source Availability:** Every feature in `F3_top25_gbt_v1` is derived from state whose $\text{source\_availability\_ts} \le T$.
4. **State Transition Ordering:** Running extremes and progress window counts are updated with the current bar's High/Low only *after* all checkpoints $T \le \text{ts\_avail}$ have completed evaluation.

---

## 3. Summary Verdict

- **CRITICAL Findings:** 0
- **WARNING Findings:** 0
- **NOTE:** 0
- **Referred to contract-checker:** 0
- **Final Verdict:** `PASS`
