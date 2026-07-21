# KNN Continuous Health — Profit-Protection Money Gate (Study 4, 1s stops)

Trigger = `hC` drawdown + open-profit gate; protective stop replayed at 1s (adverse-first), else flip. vs hold-to-flip & DETER-exit. Costs $20/pt, $5 RT, 1t stop/flip slip. Both-year robustness.

| Policy | avg/tr | 2025 | 2026 | PF | maxDD | p5 trade | #protected |
| --- | --- | --- | --- | --- | --- | --- | --- |
| hold-to-flip | $+0 | $+6 | $-16 | 1.00 | $189,308 | $-552 | 28,191 |
| P1 BE @20%dd,+0.5 | $-0 | $+4 | $-14 | 1.00 | $176,335 | $-518 | 15,661 |
| P2 lock0.5 @30%dd,+1 | $+2 | $+7 | $-11 | 1.02 | $148,572 | $-538 | 12,055 |
| P3 lock1.0 @40%dd,+2 | $+0 | $+5 | $-14 | 1.00 | $172,851 | $-548 | 7,394 |
| P4 graduated | $-0 | $+4 | $-14 | 1.00 | $176,335 | $-518 | 15,661 |
| P5 DETER exit | $+3 | $+7 | $-9 | 1.02 | $131,308 | $-472 | 6,479 |