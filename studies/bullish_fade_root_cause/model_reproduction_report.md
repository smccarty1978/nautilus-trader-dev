# Model Reproduction Report

Bullish frozen predictions reproduce bit-exactly (0.0 max difference). On the original 2025 target, AUC=0.67099, AP=0.41204, Brier=0.17311. The historical reliability event disagrees with the training target on 23.3% of checkpoints and captures only 6.3% of true <=300s flips. Scoring that legacy event gives AUC=0.74012, AP=0.04319. In the exact historical 2024–2025 first-signal replay, top-2.5% event rate is 7.0% (published 7.2%; difference -0.2%), versus 59.9% on the original target.

The published Bullish AUC 0.67099 is reproduced within floating-point tolerance; the artifact-to-frozen-reference predictions are bit-exact. AP, Brier, calibration, confusion matrices, lift and curves were recomputed because the upstream freeze report did not publish all of them.

| model                          |   rows |   prevalence |   roc_auc |   average_precision |     brier |   threshold_prevalence_matched |   precision_prevalence_matched |   recall_prevalence_matched |
|:-------------------------------|-------:|-------------:|----------:|--------------------:|----------:|-------------------------------:|-------------------------------:|----------------------------:|
| bullish_fade                   | 198255 |    0.249073  |  0.670995 |           0.412044  | 0.173106  |                       0.313863 |                      0.415301  |                   0.41531   |
| bearish_fade_top103            | 163397 |    0.262936  |  0.655289 |           0.410026  | 0.181866  |                       0.335727 |                      0.407234  |                   0.407234  |
| bullish_scores_vs_legacy_event | 198255 |    0.0156163 |  0.740124 |           0.0431861 | 0.0828476 |                       0.600046 |                      0.0723514 |                   0.0723514 |
