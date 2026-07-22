# Complexity Assessment

Top103 expands the contract from 25 to 103 model columns and from 25 to 85 canonical runtime calculations. Both use the same two tracker dependencies/families, but Top103 exposes 78 additional contracts, several complete categorical groups, and a materially larger parity and drift surface.

| Risk | Top25 | Top103 | Evidence |
|---|---|---|---|
| Runtime Parity Risk | Low | High | 85 vs 25 canonical calculations and 103 vs 25 ordered outputs |
| Maintenance Burden | Low | High | 78 additional feature contracts and larger categorical parity surface |
| Future Retraining Cost | Low | Medium | same estimator, but wider materialization/scoring matrix |
| Debug Difficulty | Low | High | more failure points and interacting feature groups |
| Audit Complexity | Low | High | 4.1x columns and 3.4x canonical calculations |
| Feature Drift Exposure | Low | High | 103 monitored inputs versus 25 |

Incremental 2025 value per added feature: AUC 0.000064, AP 0.000124, Brier reduction 0.000015.
