# KNN Continuous Health — Deterioration Timing (Study 2)

Best indicator = `hC`. Median bars between successive deterioration events (the core question: does health degrade BEFORE DETER or fire with it?).

| transition | median bars | n |
| --- | --- | --- |
| peak→10%dd | 1.0 | 25,912 |
| 10→20%dd | 0.0 | 25,825 |
| 20→30%dd | 0.0 | 25,713 |
| 30%dd→DETER | 0.0 | 6,465 |
| DETER→flip | 6.0 | 6,479 |

> If peak→10%dd→20%→30% accumulate several bars BEFORE 30%dd→DETER≈0, the health degrades continuously and the DETER label is the LATE end of the process. If 30%dd→DETER≈0 AND the earlier steps are also ~0, health collapses with DETER (no early lead).