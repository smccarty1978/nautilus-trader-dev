# The causal opposite-1m flip trigger and the terminal-race null

## The engine

`features/trackers/regime_dual_ema.py` implements `DualEmaRegimeTracker(short=3, long=9, atr=14)`, semantics
`dual_ema_hl_sticky_wilder_atr_v1`. It is fed completed 1m bars.

Rules:
- On each completed 1m bar, EMA3 and EMA9 of the bar HIGH and of the bar LOW are updated, including that bar.
- The regime becomes +1 if the close > EMA3_high and > EMA9_high, and −1 if the close < EMA3_low and < EMA9_low.
  Otherwise it stays where it was.
- **A long trade's terminal flip therefore needs a completed 1m close below both low-EMAs.** Intrabar prices
  never flip.

**Causal trigger primitive.** At any instant, take the engine state after the last completed minute:
- long: `min(EMA3_low, EMA9_low)`;
- short: `max(EMA3_high, EMA9_high)`.

This is the loosest completed close that could flip. The flip also needs the bar's own low or high absorbed,
which tightens it slightly. The level trails price and lags it.

**Parity.** Replaying the engine on `NQ.XCME-1-MINUTE-LAST-EXTERNAL` from 2022-12-20 to the development
boundary (2023-10-17 22:00 UTC) reproduces:
- **6,024 / 6,024 T0 flips**, with direction;
- **6,024 / 6,024 terminal flips**.

At every one of the 25k anchors the engine regime equals the trade direction. The trigger is exact, not
approximated.

## Terminal-race null (N3)

The N2 simulated paths are aggregated into real-clock 1m bars, including the real partial minute at the anchor.
They are then fed through the same dual-EMA update, initialised with the replayed engine state.
- **Outcome:** +2A touched strictly before the simulated flip.
- **Giveback:** the terminal exit, taken as the next simulated open after the flip, is at or below entry.
- **Truncation:** 6% of simulated paths are cut off at the session close or the 2 h cap.

| x | N | actual P(+2A before flip) | N3 | residual [CI] |
|---|---|---|---|---|
| 0.25 | 5,162 | 0.430 | 0.454 | −0.024 [−0.035, −0.012] |
| 0.50 | 4,519 | 0.491 | 0.513 | −0.022 [−0.035, −0.008] |
| 0.75 | 3,977 | 0.558 | 0.577 | −0.019 [−0.033, −0.004] |
| 1.00 | 3,528 | 0.629 | 0.651 | −0.022 [−0.036, −0.008] |
| 1.25 | 3,136 | 0.708 | 0.730 | −0.022 [−0.037, −0.007] |
| 1.50 | 2,791 | 0.795 | 0.811 | −0.016 [−0.028, −0.003] |

The **driftless engine null reproduces terminal continuation within about 2pp.** Real trades sit consistently
about 2pp *below* it, in both blocks. That is below the frozen 5pp "meaningful" bar, but it is uniform:
something slightly anti-persistent at the 1m-close scale, or a small cost of the next-bar-open fill, that the
null does not carry.

Giveback given +2A matches the engine null: pooled residuals are −0.6, −0.4 and +0.1pp at the +1A, +1.5A and
+2A anchors.

## Does trigger movement explain the speed effect?

**Largely, yes.** At each anchor, fast arrivals have the trigger much further below entry than slow ones.
The table shows the median trigger position relative to entry (in A) and the giveback rate by trigger
tercile, for trades that reached +2A:

| anchor | trigger, fast | trigger, slow | giveback by trigger tercile (low / mid / high) | speed Δ within trigger terciles [CI] |
|---|---|---|---|---|
| +1.0A | −1.31 | −0.71 | 19.1% / 17.5% / 13.8% | −4.6pp [−9.7, +0.6] |
| +1.5A | −1.14 | −0.34 | 22.7% / 16.8% / 11.1% | −1.8pp [−9.2, +5.4] |
| +2.0A | −0.92 | +0.09 | 25.5% / 17.3% / **7.7%** | −2.3pp [−9.7, +4.5] |

**Raw giveback speed effect vs what survives:**

| anchor | raw (slow − fast) | against N3 | within trigger terciles |
|---|---|---|---|
| +1.5A | −9.3pp | −4.5pp | −1.8pp |
| +2.0A | −14.3pp | −5.9pp | −2.3pp |

On the terminal race, the raw speed effect of about −5pp falls to −1 to −4pp within trigger terciles.

**Mechanism.** A fast spike to +2A outruns the lagging EMA-of-lows, so the trigger is still near or below
entry. When price reverses, the first 1m close below it exits at a loss. A slow advance drags the trigger
above entry, so the same reversal exits in profit. "Fast moves give back" is mainly moving-boundary geometry.

Machine-readable: `artifacts/TRIGGER_CONDITIONING.*`, `artifacts/BUILD_AUDIT.json`, and
`artifacts/EVENT_LEVEL.*` (columns `trig_rel_entry`, `dist_to_trig`, `trig_move60`, `null_p_term_reach2`,
`null_p_giveback_given_reach2`, `null_p_term_win`).
