# Canonical Corrected Pre-Flip Reliability Report

## Verdict

Both directions are evaluated exclusively on pure confirmed regime flips. Forecast quality and immediate-entry survival are separate; this study makes no execution-survival claim. The Bullish artifact has a disclosed inherited one-second feature look-ahead while Bearish is strict-causal, so cross-direction differences are artifact comparisons and cannot establish structural market asymmetry.

At Top 2.5%, Bullish Fade has 59.9% flip≤300 reliability (median 180s) and Bearish Fade has 60.6% (median 200s). The flip-rate difference is -0.8% (two-proportion p=0.732).

2025 development metrics: Bullish AUC/AP/Brier 0.6710/0.4120/0.1731; Bearish 0.6503/0.4003/0.1830. 2024 is in-sample and combined thresholds are retained only for continuity with the superseded reliability study.

## Executive answers

1. **Bullish reliability:** Top 1/2.5/5/10/25% results are in `threshold_summary.csv`; Top 2.5% is 59.9% within 300s and 74.9% within 600s.
2. **Bearish reliability:** Top 2.5% is 60.6% within 300s and 75.3% within 600s.
3. **Earlier warnings:** Bullish Fade at Top 2.5% by median time to confirmed flip.
4. **Stronger calibration:** Bullish Fade on 2025 Brier score.
5. **Larger remaining MFE:** Bearish Fade at Top 2.5%.
6. **Greater adverse excursion:** Bearish Fade at Top 2.5%.
7. **Asymmetry source:** No material Top-2.5% artifact forecasting asymmetry is established; path economics remain separate.
8. **Exit-signal sufficiency:** Both show useful enrichment, but neither is an executable exit policy; timing reliability must be consumed as a probabilistic warning, not a guaranteed exit trigger.
9. **Canonical benchmark:** Both Top25 artifacts form the requested event-corrected directional pair; Bullish Fade Top25 is the stronger 2025 discrimination reference. Bullish remains provisional and non-causal until rebuilt.
10. **Pure events only:** Yes. Events use only `confirm_flip_ns` joined by the frozen checkpoint key; policy-conditioned substitutions are prohibited and guarded.

## Forecast versus execution

Forecast question: did the opposing confirmed regime flip occur in the horizon? Execution question: would an immediate countertrend order survive the intervening path? Only the first is a reliability label. `economic_summary.csv` contains non-executable path marks for context.

## Reproduction and integrity

Bullish frozen-reference max prediction difference: 0.0e+00; Bearish fixture difference: 0.0e+00. No 2026 input was opened.
