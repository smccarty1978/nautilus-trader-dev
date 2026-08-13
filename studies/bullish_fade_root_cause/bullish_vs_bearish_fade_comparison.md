# Bullish vs Bearish Fade Comparison

Bullish frozen predictions reproduce bit-exactly (0.0 max difference). On the original 2025 target, AUC=0.67099, AP=0.41204, Brier=0.17311. The historical reliability event disagrees with the training target on 23.3% of checkpoints and captures only 6.3% of true <=300s flips. Scoring that legacy event gives AUC=0.74012, AP=0.04319. In the exact historical 2024–2025 first-signal replay, top-2.5% event rate is 7.0% (published 7.2%; difference -0.2%), versus 59.9% on the original target.

| Model | ROC-AUC | AP | Brier | Base rate |
|---|---:|---:|---:|---:|
| Bullish Fade Top25 V1 | 0.67099 | 0.41204 | 0.17311 | 0.249 |
| Bearish Fade Top103 V2 | 0.65529 | 0.41003 | 0.18187 | 0.263 |
| Bullish scores vs legacy reliability event | 0.74012 | 0.04319 | 0.08285 | 0.016 |

The first demonstrated asymmetry is evaluation construction: Bearish Fade uses the strict pure confirmed-flip event,
while the historical Bullish reliability run replaced missing `confirm_flip_ns` with a policy-conditioned
`hit_opposing_flip/exit_ts` event. Feature-importance and SHAP summaries are in `results/`.
