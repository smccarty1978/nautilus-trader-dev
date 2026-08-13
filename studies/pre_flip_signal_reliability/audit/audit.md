# Lookahead & Causal Audit Report — Pre-Flip Signal Reliability Study

## 1. Short Candidate Prevailing Regime Direction
**Verified.** In `collect_and_evaluate.py`, when evaluating the Short-RTH model (which predicts a bearish flip), the prevailing regime direction is processed as **bullish (+1)**. The implementation handles short candidates under this assumption for computing total and remaining prevailing-regime MFE.

## 2. Long Candidate Prevailing Regime Direction
**Verified.** In `collect_and_evaluate.py`, when evaluating the Long-RTH model (which predicts a bullish flip), the prevailing regime direction is processed as **bearish (-1)**. The implementation correctly handles long candidates under this assumption.

## 3. Remaining Prevailing-Regime MFE Formulas
**Verified.** The remaining MFE is strictly calculated in the prevailing regime direction before the signal, correctly measuring how much further the prevailing trend extends before flipping:
- For **Short** (Bullish prevailing): `rem_mfe_pts = max(0.0, np.max(rem_highs) - sig_px)` (max high after signal minus signal price).
- For **Long** (Bearish prevailing): `rem_mfe_pts = max(0.0, sig_px - np.min(rem_lows))` (signal price minus min low after signal).
*(This correctly uses `rem_highs` and `rem_lows` starting from `idx_s = idx_sig_arr[i] + 1` to prevent 1s intra-bar lookahead).*

## 4. Directional Trade PnL Signs
**Verified.** In `collect_and_evaluate.py`, directional trade PnL is properly aligned with trade direction:
- **Short Trade**: `pnl = (sig_px - flip_px)`
- **Long Trade**: `pnl = (flip_px - sig_px)`
*(This appropriately assigns Buckets based on whether this PnL is > 0).*

## 5. Canonical RTH Session Bounds
**Verified.** The `filter_rth` function in `collect_and_evaluate.py` correctly filters observations between `08:30:00` and `< 15:15:00` America/Chicago time before generating any signals.

## Conclusion
The study's implementation accurately enforces all specified constraints. No look-ahead leaks or causal inversion issues were found. The equations match the forecasting constraints for imminent regime exhaustion modeling.
