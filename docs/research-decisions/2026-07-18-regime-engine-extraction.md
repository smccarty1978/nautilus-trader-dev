# Decision: Regime Engine Extraction

## Context
The regime calculation logic (`_LiteRegimeEngine` and the state classification categories `_state_cat`) was previously embedded directly inside the strategy file `strategies/pullback_5s/strategy.py`. Because the same regime tracking algorithms ( Wilder ATR and EMA bands confirmation) are duplicated in other modules (like `backtests/baseline_flip_parity/strategy.py` and various offline collectors), this coupling hindered standalone unit testing, increased code duplication, and risked calculation drift during updates.

## Previous structure
- `_LiteRegimeEngine` and `_state_cat` were defined as private classes/methods directly in `strategies/pullback_5s/strategy.py`.
- standalone unit testing of these calculation routines was impossible without running the full NautilusTrader engine or mock-initializing strategy lifecycles.

## New structure
- **Shared Module:** Created [utils/regime_engine.py](file:///c:/Users/Scott McCarty/Projects/Nautilus Trader/utils/regime_engine.py) containing:
  - `LiteRegimeEngine` (the Wilder ATR and EMA bands sticky regime calculator).
  - `state_cat` (hC and state classification mapping).
  - Constants `IS_STALL_P33` and `IS_STALL_P67`.
- **Pullback Strategy:** Modified [strategies/pullback_5s/strategy.py](file:///c:/Users/Scott McCarty/Projects/Nautilus Trader/strategies/pullback_5s/strategy.py) to import these components from `utils.regime_engine`.
- **Standalone Verification:** Created [tests/test_regime_engine.py](file:///c:/Users/Scott McCarty/Projects/Nautilus Trader/tests/test_regime_engine.py) to test the math in isolation.

## Behavior preserved
- **Wilder ATR(14) Initialization:** First ATR calculation remains exactly equivalent.
- **EMA Calculation Coefficients:** `ALPHA3 = 0.5` and `ALPHA9 = 0.2` remain unchanged.
- **Classification Boundaries:** `IS_STALL_P33 = 0.044` and `IS_STALL_P67 = 0.304` remain unchanged.
- **Sticky Regime Rules:** The regime assignment remains sticky unless a full band breach is confirmed on bar close.

## Invariants
- Calculation outcomes are identical to the original implementation.
- Import structure avoids circular dependencies.
- No NautilusTrader state mutations are mixed with the calculations.

## Tests
- [tests/test_regime_engine.py](file:///c:/Users/Scott McCarty/Projects/Nautilus Trader/tests/test_regime_engine.py) verifies the transitions and ATR updates.

## Known limitations
- The engine still requires sequential bucket feed to maintain accurate state history (must be fed in chronologically sorted order).

## Rollback
- Revert the changes to [strategies/pullback_5s/strategy.py](file:///c:/Users/Scott McCarty/Projects/Nautilus Trader/strategies/pullback_5s/strategy.py) and remove `utils/regime_engine.py`.

## Audit status
- Extracted code is pure and side-effect free.
- The `lookahead-auditor` verified that no look-ahead or future data leaks are introduced.
