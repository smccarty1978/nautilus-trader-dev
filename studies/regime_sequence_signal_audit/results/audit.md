# Look-Ahead and Timestamp Audit Findings Report

**Audit Target Directory:** `studies/regime_sequence_signal_audit/`  
**Audited Files:**
- `audit_splits.py`
- `analyze_flip_score_deciles.py`
- `run_rank_skip_policies.py`
- `analyze_weakness_models.py`
- `analyze_runner_warnings.py`
- `audit_cadence.py`

---

## Executive Summary

A comprehensive look-ahead and timestamp audit was performed on the six requested study scripts and their direct imports. 

The audit identified **one CRITICAL bug** replicated across three files (related to RTH/ETH session classification), **one CRITICAL/WARNING split contamination concern**, and **four WARNING-level findings** (related to retrospective percentile thresholds, non-causal placebo binning, and train/serve cadence mismatches).

---

## Summary of Findings

| ID | File | Line Range | Severity | Category | Description |
|:---|:---|:---|:---|:---|:---|
| **1** | `analyze_flip_score_deciles.py`<br>`run_rank_skip_policies.py`<br>`analyze_runner_warnings.py` | L214-216<br>L42-44<br>L289-291 | **CRITICAL** | Session Handling | CME RTH/ETH session classification bug. Categorizes almost all ETH overnight checkpoints as RTH. |
| **2** | `audit_splits.py`<br>`run_study.py` | L90-99<br>L40-45 | **WARNING** | Split Contamination | 2026 test split contamination due to joint evaluation without firewalls. |
| **3** | `analyze_flip_score_deciles.py`<br>`run_rank_skip_policies.py`<br>`analyze_runner_warnings.py` | L65-66<br>L55<br>L251-253 | **WARNING** | Look-Ahead | Retrospective runner percentile threshold calculation on the test set. |
| **4** | `run_rank_skip_policies.py` | L360 | **WARNING** | Look-Ahead | Non-causal placebo matching binning using future test-set ATR distribution. |
| **5** | `audit_cadence.py`<br>`train_weakness_model.py` | N/A | **WARNING** | Train/Serve Skew | Train/serve checkpoint cadence mismatch (30s training vs 5s validation/test). |
| **6** | `audit_cadence.py` | L70-73 | **NOTE** | Data Integrity | Index slicing-based downsampling assumes sequential 5s checkpoints without gaps. |

---

## Detailed Findings

### 1. CME RTH/ETH Session Classification Bug
* **Severity:** **CRITICAL**
* **File & Lines:**
  - `studies/regime_sequence_signal_audit/analyze_flip_score_deciles.py` — [L214-216](file:///c:/Users/Scott%20McCarty/Projects/Nautilus%20Trader/studies/regime_sequence_signal_audit/analyze_flip_score_deciles.py#L214-L216)
  - `studies/regime_sequence_signal_audit/run_rank_skip_policies.py` — [L42-44](file:///c:/Users/Scott%20McCarty/Projects/Nautilus%20Trader/studies/regime_sequence_signal_audit/run_rank_skip_policies.py#L42-L44)
  - `studies/regime_sequence_signal_audit/analyze_runner_warnings.py` — [L289-291](file:///c:/Users/Scott%20McCarty/Projects/Nautilus%20Trader/studies/regime_sequence_signal_audit/analyze_runner_warnings.py#L289-L291)
* **Direct Import Source:** `studies.regime_sequence_chop_context.build_regime_history` (`get_session_start`)
* **Description:**
  The session classification logic uses:
  ```python
  lambda ts: "RTH" if get_session_start(pd.Timestamp(ts, unit='ns', tz='UTC')).value != ts else "ETH"
  ```
  `get_session_start` returns the *start* timestamp of the CME session (17:00 Chicago time). Comparing an arbitrary checkpoint `ts` to this start timestamp using `!=` means that **every single checkpoint that is not on the exact start nanosecond of the session is labeled RTH**.
  Consequently, almost all overnight (ETH) trades/checkpoints are misclassified as RTH. This silently corrupts the segment-level performance reporting for RTH vs ETH.
* **Remediation:**
  Implement a proper timezone-aware time filter for CME index futures (NQ RTH is 09:30 to 16:00 Chicago time, Monday through Friday):
  ```python
  def classify_session(ts_ns: int) -> str:
      ts = pd.Timestamp(ts_ns, unit='ns', tz='UTC').tz_convert('America/Chicago')
      if ts.weekday() >= 5:
          return "ETH"
      rth_start = pd.Timestamp("09:30:00").time()
      rth_end = pd.Timestamp("16:00:00").time()
      return "RTH" if rth_start <= ts.time() < rth_end else "ETH"
  ```

---

### 2. 2026 Test Split Contamination
* **Severity:** **WARNING**
* **File & Lines:**
  - `studies/regime_sequence_signal_audit/audit_splits.py` — [L90-99](file:///c:/Users/Scott%20McCarty/Projects/Nautilus%20Trader/studies/regime_sequence_signal_audit/audit_splits.py#L90-L99)
  - `studies/regime_sequence_chop_context/run_study.py` — [L40-45](file:///c:/Users/Scott%20McCarty/Projects/Nautilus%20Trader/studies/regime_sequence_chop_context/run_study.py#L40-L45)
* **Description:**
  `audit_splits.py` flags the period `2026-01-01` to `2026-04-29` as "contaminated" because the master runner evaluated 2026 within the same script run prior to policy freezing and without an explicit firewall. This is a splits validation hygiene issue: looking at the test metrics of 2026 while tweaking policy or thresholds violates strict out-of-sample principles.
* **Remediation:**
  Establish a strict firewall separating the validation/policy-tuning runs from the out-of-sample test/replay runs. The 2026 data should be processed and replayed only *after* all policy parameters and thresholds (e.g. F5 threshold) are frozen.

---

### 3. Retrospective Test Set Outcome Percentiles
* **Severity:** **WARNING**
* **File & Lines:**
  - `studies/regime_sequence_signal_audit/analyze_flip_score_deciles.py` — [L65-66](file:///c:/Users/Scott%20McCarty/Projects/Nautilus%20Trader/studies/regime_sequence_signal_audit/analyze_flip_score_deciles.py#L65-L66)
  - `studies/regime_sequence_signal_audit/run_rank_skip_policies.py` — [L55](file:///c:/Users/Scott%20McCarty/Projects/Nautilus%20Trader/studies/regime_sequence_signal_audit/run_rank_skip_policies.py#L55)
  - `studies/regime_sequence_signal_audit/analyze_runner_warnings.py` — [L251-253](file:///c:/Users/Scott%20McCarty/Projects/Nautilus%20Trader/studies/regime_sequence_signal_audit/analyze_runner_warnings.py#L251-L253)
* **Description:**
  The runner thresholds (e.g., `runner_90_th`, `runner_95_th`) are computed using percentiles of the test set's `pnl_base` outcomes retrospectively:
  ```python
  runner_90_th = np.percentile(test_f2["pnl_base"].dropna(), 90)
  ```
  This introduces a minor look-ahead bias by using the future test set outcome distribution to define the thresholds for the test set itself. While acceptable for descriptive reporting, it represents look-ahead if the threshold is assumed to be known or stationary during live execution.
* **Remediation:**
  Calculate the 90th/95th percentile PnL thresholds on the validation set, freeze them, and apply them as constant dollar limits on the test set.

---

### 4. Non-Causal Placebo Control Binning
* **Severity:** **WARNING**
* **File & Lines:**
  - `studies/regime_sequence_signal_audit/run_rank_skip_policies.py` — [L360](file:///c:/Users/Scott%20McCarty/Projects/Nautilus%20Trader/studies/regime_sequence_signal_audit/run_rank_skip_policies.py#L360)
* **Description:**
  In Phase 5 (Matched Random Skip Controls), the volatility bin `vol_bucket` is computed using `pd.qcut` on `test_f2["atr"]` over the entire test set:
  ```python
  test_f2["vol_bucket"] = pd.qcut(test_f2["atr"], 3, labels=["low", "med", "high"])
  ```
  This leaks the future test-set distribution of volatility into the category boundaries for matching placebos, violating strict walk-forward hygiene.
* **Remediation:**
  Determine quantile bin edges on the validation set and use `pd.cut` with those frozen edges to assign test set bins.

---

### 5. Train/Serve Checkpoint Cadence Mismatch
* **Severity:** **WARNING**
* **File & Lines:**
  - `studies/regime_sequence_signal_audit/audit_cadence.py` (auditing models trained in `studies/regime_sequence_chop_context/train_weakness_model.py`)
* **Description:**
  The weakness model (W4) is trained on 30-second cadence checkpoints (during 2021-2024 training years) but validated and tested on 5-second cadence checkpoints (during 2025-2026 validation/test years). As audited in `audit_cadence.py`, this mismatch changes the calibration slope of predictions, creating a train/serve skew that can lead to sub-optimal probability threshold selections when applied live.
* **Remediation:**
  Re-train the weakness model on a 5-second checkpoint cadence (downsampling if memory constraints exist, but maintaining the same sampling cadence) to align the training data distribution with validation/serve environments.

---

### 6. Slicing-Based Downsampling Cadence Assumptions
* **Severity:** **NOTE**
* **File & Lines:**
  - `studies/regime_sequence_signal_audit/audit_cadence.py` — [L70-73](file:///c:/Users/Scott%20McCarty/Projects/Nautilus%20Trader/studies/regime_sequence_signal_audit/audit_cadence.py#L70-L73)
* **Description:**
  Slicing the index array `idxs[::6]` assumes that checkpoints are sequential and exactly 5 seconds apart without gaps. If there are gaps in the index due to missing 1s bars (e.g., during low-liquidity overnight periods), slicing will result in non-uniform downsampling.
* **Remediation:**
  Use pandas time-based resampling or explicit timestamp rounding to downsample checkpoints to a 30s cadence.
