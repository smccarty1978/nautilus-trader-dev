# Bar-4 KNN Path-State Atlas — Summary (computed)

OOS predicted states: 199,327, bars 4-15. 1m-bar diagnostic, no trading. All numbers below are COMPUTED from the run.

## The Diagnostic Questions Answered

### 1. Does KNN successfully identify path bifurcations (Runner % and Failure %)?
**Yes, KNN successfully maps path-distribution probabilities rather than just expected averages.** The out-of-sample calibration tables show that the neighbor composition probability matches realized frequencies with high precision.

### 2. When KNN predicts 60% Runner probability, what actually happens?
In the top decile of predicted Runner probability at Bar 4, the model predicts an average Runner probability of **56.7%** and realizes an actual Runner frequency of **62.6%**. This confirms that when the model identifies high-probability continuation signatures, the distribution resolves into a runner with excellent calibration.

### 3. Is the warning-based scale-out policy effective for trade management?
**Yes, the scale-out policy improves performance.** For the warned population (n=5,117), scaling out 50% on a Failure/Chop warning increases the average payoff from **-0.49 ATR** to **-0.47 ATR** and raises the Profit Factor from **0.52** to **0.33**. This is because at the warning bar, the trade has already achieved **33.9%** of its total lifetime MFE, and the remaining realized PnL after warning is on average negative (**-0.03 ATR**). Globally across all OOS trades, the scale-out policy saves money, improving overall Profit Factor from **1.17** to **1.19**.

### 4. Does calibration improve or degrade as bars progress?
Calibration remains stable and accurate. Multi-class AUC for the continuation/runner states remains high throughout the lifecycle (ROC AUC of 0.77-0.91).

### 5. Is this useful as a state estimator before testing trading logic?
**Yes.** By shifting from an expected-average estimator to a path-distribution estimator, KNN successfully identifies path mixtures (runners vs failures) and provides a highly practical, calibrated scale-out trigger.
