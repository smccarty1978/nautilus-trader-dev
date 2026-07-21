---
name: pullback_5s_nt_hold_to_flip_dead
description: "NT streaming validation of 5s pullback with pure hold-to-flip exit: -$100/tr, 10% WR. Edge was in PT exits, not regime flip."
metadata:
  type: project
---

NT BacktestEngine validation of PullbackV1Strategy (Jun 2026). Pure hold-to-flip exit (SL at structural pullback low + regime flip, NO profit target).

**Results (2025+2026 OOS, 1-lot, $20/pt, $4.06 RT):**

| Depth | 2025 $/tr | 2026 $/tr | pooled WR | pooled exp | pooled PF |
|-------|-----------|-----------|-----------|-----------|-----------|
| 0.25  | -$100/tr  | -$111/tr  | 10.5%     | -$102     | 0.02      |
| 0.50  | -$106/tr  | -$106/tr  | 9.4%      | -$105     | 0.02      |
| 0.75  | -$107/tr  | -$99/tr   | 11.1%     | -$105     | 0.03      |

Trade counts: ~4,900-5,000 per depth (one per qualified regime, correct). Max drawdown $500-$520K pooled.

**Root cause of divergence from bar-mode +$33-40/tr:**

The offline study's `pnl_hold` metric INCLUDED PT05 exits — 26% of trades exited at +0.5 ATR because the intra-bar HIGH touched the PT level on the same bar the close crossed the SL. This is a "V-shape on the SL bar" mechanic. Those 26% exits were profitable. The NT strategy has NO PT logic, so those 26% trades convert to losses instead.

- Bar-mode "pnl_hold" exit distribution: 63% SL, 26% PT05 (intra-bar touch priority), 11% regime flip
- NT exit distribution: ~89% SL, ~11% regime flip
- The 26% PT conversions from gains → losses ≈ −$140/tr swing explains the full gap

**Conclusion:** The bar-mode edge was the PT exit mechanic, NOT the hold-to-flip exit. True hold-to-flip (SL + regime flip, no PT) is strongly negative at −$100/tr across all depths and both years.

**Next step:** Add PT exits to NT strategy (PT at +0.5 ATR intra-bar, checking 1s bar HIGH) and re-test. The bar-mode offline study showed pnl_pt05 = -$5/tr (exit ONLY at PT, never flip) and pnl_hold = +$39/tr (PT or flip), so the combined mechanic (PT if it fires, else hold-to-flip) is what produces edge.

**Why:** NT streaming validation is the deployment gate per project rules.
**How to apply:** Do NOT claim this strategy is deployable with hold-to-flip exit. Must add PT logic and re-validate.
