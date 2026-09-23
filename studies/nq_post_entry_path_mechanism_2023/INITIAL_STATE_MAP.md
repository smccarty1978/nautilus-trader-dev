# Initial-state mechanism map (development trades; minimum support 150)

States are written as 1m/5m/15m/1h direction at T0. Three states have fewer than 150 trades and are not
interpreted: L/L/S/L (108), L/S/L/S (132) and S/S/L/S (78).

The alignment columns are blank for states whose 5m was already aligned at T0. For those states an
into-alignment transition would need two 5m flips inside the trade, and none occurred.

| state | N | +2A % | win % | giveback % of +2A | 5m turns (% of misaligned) | 5m turn before +0.5A | 5m turn after +1A | +2A runners: median s to +0.5A / +2A | 60 s EARLY AUC of MFE [CI] |
|---|---|---|---|---|---|---|---|---|---|
| L/L/L/L | 766 | 40.3 | 37.2 | 14.2 | — | — | — | 55 / 389 | 0.616 [0.576, 0.657] |
| L/L/L/S | 279 | 32.3 | 30.5 | 21.1 | — | — | — | 51 / 269 | 0.655 [0.572, 0.745] |
| L/L/S/S | 258 | 36.0 | 31.4 | 21.5 | — | — | — | 56 / 433 | 0.596 [0.514, 0.675] |
| L/S/L/L | 345 | 34.5 | 34.8 | 14.3 | 35.4 | 3.5 | 88.6 | 54 / 395 | 0.597 [0.526, 0.665] |
| L/S/S/L | 352 | 37.5 | 34.9 | 12.9 | 31.7 | 2.8 | 93.5 | 55 / 406 | 0.613 [0.548, 0.680] |
| L/S/S/S | 792 | 38.4 | 38.0 | 10.2 | 32.6 | 0.8 | 93.5 | 49 / 425 | 0.609 [0.562, 0.653] |
| S/L/L/L | 1,003 | 35.1 | 28.8 | 21.3 | 24.6 | 3.3 | 89.1 | 50 / 302 | 0.587 [0.542, 0.630] |
| S/L/L/S | 416 | 38.2 | 31.7 | 18.9 | 29.4 | 4.1 | 93.4 | 51 / 356 | 0.608 [0.537, 0.669] |
| S/L/S/L | 150 | 39.3 | 31.3 | 20.3 | 29.3 | 2.3 | 86.0 | 52 / 316 | 0.616 [0.502, 0.730] |
| S/L/S/S | 379 | 33.8 | 31.4 | 15.6 | 34.0 | 4.8 | 88.1 | 62 / 391 | 0.646 [0.572, 0.719] |
| S/S/L/L | 214 | 40.2 | 31.3 | 26.7 | — | — | — | 58 / 326 | 0.589 [0.508, 0.669] |
| S/S/S/L | 224 | 32.6 | 29.0 | 15.1 | — | — | — | 43 / 244 | 0.612 [0.515, 0.711] |
| S/S/S/S | 528 | 36.0 | 31.4 | 20.0 | — | — | — | 48 / 360 | 0.647 [0.590, 0.706] |

**Long vs short.** Longs and shorts have almost the same +2A rate (37.8% vs 35.9%) and the same 60 s
separation (AUC 0.612 [0.588, 0.637] vs 0.608 [0.583, 0.632]). Shorts win less (30.4% vs 36.0%) and give
back more (19.6% vs 14.1% of +2A trades).

## Reading

The mechanism is **homogeneous**:
- **5m ordering:** in every state with a misaligned 5m, the 5m turn comes after the move. It lands before
  +0.5A in only 0.8–4.8% of cases and after +1A in 86–94%.
- **Early separation:** the 60 s price-location separation has overlapping CIs in all 13 states
  (0.59–0.66).
- **No early-information state:** no initial configuration shows information emerging earlier.
- **Symmetry:** the mechanism is symmetric long/short. The one asymmetry is terminal: shorts give back more.

Cells are small, and per-state differences in +2A rate (32–40%) are within the range the atlas already
failed to replicate.

Machine-readable: `artifacts/INITIAL_STATE_MAP.*`.
