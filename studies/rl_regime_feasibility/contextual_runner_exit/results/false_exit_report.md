# False Exit Context Analysis

## Definition
Costly false exit: E5 exited before E0 AND E0 later outperformed E5 by >= $25.
Success exit: E5 outperformed E0 by >= $25.

## Sample sizes
- False exits analyzed: 200
- Success exits analyzed: 200

## Context at exit time: False exits vs Successful exits

| Feature | False Exit | Success Exit | Diff |
|---------|-----------|-------------|------|
| RTH fraction | 0.12 | 0.07 | +0.05 |
| Trade MFE ATR | 4.33 | 1.69 | +2.64 |
| 5m regime aligned | 0.31 | 0.07 | +0.24 |

## Key finding
False exits occur more in RTH.
False exits occur in higher MFE trades.
5m alignment was positive at false exit time — model exited during healthy trend.
