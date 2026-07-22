# Root Cause Report

## Classification: B — Training label differs from evaluation event

Bullish frozen predictions reproduce bit-exactly (0.0 max difference). On the original 2025 target, AUC=0.67099, AP=0.41204, Brier=0.17311. The historical reliability event disagrees with the training target on 23.3% of checkpoints and captures only 6.3% of true <=300s flips. Scoring that legacy event gives AUC=0.74012, AP=0.04319. In the exact historical 2024–2025 first-signal replay, top-2.5% event rate is 7.0% (published 7.2%; difference -0.2%), versus 59.9% on the original target.

The predeclared gates select **B**. The model is genuinely predictive of its original checkpoint target, but the historical reliability event is policy-conditioned and quantitatively recreates the apparent collapse. The original target is the next confirmed bearish regime flip within
300 seconds; the historical reliability event was reconstructed from an older trade-policy outcome and assigns no
flip whenever that simulated policy did not survive to `hit_opposing_flip`. This creates 46,284 false negatives
against the actual training target in 2025.

The disclosed one-second Bullish feature look-ahead is a secondary model-validity defect, but it does not explain the
        large reliability collapse. Join scores to the corrected pure-flip population by `(regime_start_ns, observation_time)` and use `confirm_flip_ns` directly. Do not retrain to repair this evaluation defect. For production validity, the one-second
attachment defect must subsequently be removed and the existing model rebuilt under the strict causal feature contract.

## Executive answers

1. Yes: ROC-AUC reproduces at 0.67099; artifact predictions are bit-exact. AP is 0.41204.
2. Yes, for its original target.
3. No.
4. The reliability event is conditioned on an older simulated trade surviving to an opposing-flip exit.
5. Not applicable; they are not identical.
6. Primary classification: B — Training label differs from evaluation event. Secondary defect: one-second feature look-ahead.
7. Join scores to the corrected pure-flip population by `(regime_start_ns, observation_time)` and use `confirm_flip_ns` directly. Do not retrain to repair this evaluation defect.
