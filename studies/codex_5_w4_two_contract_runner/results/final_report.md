# CODEX 5.X Original W4 Two-Contract PT + Runner Diagnostic

## Decision

**Final label: `PT_RUNNER_FAILS`**

Taking one contract off at +1.25A and holding a second contract to the frozen
opposing-regime-flip horizon did not improve the original repaired W4 entry set.
All runner variants lost money in 2025 development and combined. The results
reversed to profits in 2026, but that year instability is not a basis for
selection. The simple positive floors did not supply a stable remedy.

This is a **1-second OHLC research simulation**, not NT-native executable
validation and not tick-level touch-order validation.

## Population and controls

- Exact original repaired pooled-W4 first-crossing entries: **4,383**.
- 2025 development: **3,246**; 2026 selection-isolated final test: **1,137**.
- Long fades: 1,871; short fades: 2,512; ETH: 2,937; RTH: 1,446.
- Entry timestamp, next-open fill, direction, checkpoint ATR, bracket outcome,
  and frozen opposing-flip horizon reconcile to the audited bracket study.
- Policy A reconciles one-for-one on timestamp, fill, direction, session, and
  ATR, and its yearly totals reconcile to its frozen summary.
- No retraining, entry changes, re-entry, delayed entry, W4Exit/W4Reverse,
  filters, threshold search, or 2026-driven choice was used.

## Compact comparison

| Policy | Net PnL | $/entry | PF | Win rate | Max DD | PT1 rate | Runner net | 2025 net | 2026 net |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Policy A baseline | $9,873 | $2.25 | 1.016 | 31.51% | $34,574 | n/a | $0 | -$8,115 | $17,988 |
| Pure 1.25A bracket | -$46,753 | -$10.67 | 0.921 | 49.62% | $52,930 | 49.62% | $0 | -$48,050 | $1,297 |
| V0: PT1 + unprotected runner | -$56,372 | -$12.86 | 0.953 | 45.54% | $90,340 | 49.62% | -$6,298 | -$75,812 | $19,440 |
| V75_25 | -$55,893 | -$12.75 | 0.945 | 49.58% | $83,105 | 49.62% | -$5,819 | -$65,131 | $9,238 |
| V100_50 | -$66,687 | -$15.21 | 0.939 | 49.58% | $82,373 | 49.62% | -$16,613 | -$73,843 | $7,156 |

V75_25 was the least negative two-contract variant in 2025, but it remained
$17,081 worse than the pure bracket and $57,016 worse than Policy A in that
development year. It was positive in 2026, but its floor reduced V0 by $10,202
in 2026. The apparent improvement was therefore not stable.

## Two-leg decomposition

The new two-contract simulation applies an adverse-open fill to **both** legs
when price gaps through the shared initial stop. The imported pure-bracket
baseline retains its previously frozen fixed-level research convention. This
executable gap treatment reduces the first-leg result by $3,320 across the
population versus that baseline.

| Variant | Contract 1 net | Runner gross | Additional runner cost | Runner net | Total net |
|---|---:|---:|---:|---:|---:|
| V0 | -$50,074 | $37,532 | -$43,830 | -$6,298 | -$56,372 |
| V75_25 | -$50,074 | $38,011 | -$43,830 | -$5,819 | -$55,893 |
| V100_50 | -$50,074 | $27,217 | -$43,830 | -$16,613 | -$66,687 |

The favorable runner path did not overcome the second contract's $43,830 of
additional costs or the additional loss exposure. V0 runner net was -$25,261
in 2025 and +$18,962 in 2026.

| Variant | PnL on PT1-hit trades | PnL on SL-first trades | Runner net where PT1 preceded runner exit | Runner positive exits | PT1 winners made larger | Runner reduced total |
|---|---:|---:|---:|---:|---:|---:|
| V0 | $1,107,446 | -$1,163,818 | $568,240 | 1,305 | 1,291 | 3,053 |
| V75_25 | $958,809 | -$1,014,702 | $381,525 | 2,575 | 1,347 | 1,741 |
| V100_50 | $1,022,905 | -$1,089,591 | $429,362 | 2,377 | 1,605 | 2,001 |

## Direction and session

| Variant / split | Trades | Net PnL | $/entry | PF | Win rate | Runner net |
|---|---:|---:|---:|---:|---:|---:|
| V0 long | 1,871 | -$59,476 | -$31.79 | 0.895 | 44.68% | -$25,544 |
| V0 short | 2,512 | $3,104 | $1.24 | 1.005 | 46.18% | $19,245 |
| V0 ETH | 2,937 | -$36,984 | -$12.59 | 0.939 | 45.62% | -$8,779 |
| V0 RTH | 1,446 | -$19,388 | -$13.41 | 0.968 | 45.37% | $2,481 |
| V75_25 long | 1,871 | -$69,384 | -$37.08 | 0.856 | 48.96% | -$35,452 |
| V75_25 short | 2,512 | $13,491 | $5.37 | 1.025 | 50.04% | $29,633 |
| V75_25 ETH | 2,937 | -$45,195 | -$15.39 | 0.912 | 50.22% | -$16,990 |
| V75_25 RTH | 1,446 | -$10,698 | -$7.40 | 0.979 | 48.27% | $11,170 |
| V100_50 long | 1,871 | -$64,792 | -$34.63 | 0.875 | 48.96% | -$30,860 |
| V100_50 short | 2,512 | -$1,895 | -$0.75 | 0.997 | 50.04% | $14,247 |
| V100_50 ETH | 2,937 | -$35,054 | -$11.94 | 0.936 | 50.22% | -$6,848 |
| V100_50 RTH | 1,446 | -$31,633 | -$21.88 | 0.942 | 48.27% | -$9,765 |

The surviving pocket was short/RTH: V0 +$3,360, V75_25 +$23,621, and V100_50
+$5,121. Long fades remained the dominant drag, and all complete variants were
negative in both ETH and RTH. The result is therefore not stable across side or
session. This diagnostic does not authorize filtering to the favorable pocket.

## Runner-tail diagnostics

Among the 2,101 PT1-hit trades whose bracket resolved before the frozen horizon:

- 70.97% later reached +2A, 46.07% reached +3A, and 30.46% reached +4A.
- 36.76% (772/2,100 ordered labels) returned to entry before +2A. One of the
  2,101 eligible paths is excluded from this rate because entry and +2A share
  a one-second bar and their intrabar order is unknowable from OHLC.
- Additional MFE after PT1 averaged 2.744A; median was 1.579A.
- V0 realized capture ratio averaged 0.079 and had a 0.186 median.
- V0 giveback from full available MFE averaged 2.666A; median was 2.282A.
- V75_25 exited its floor before +2A on 61.92% of eligible paths; V100_50 did
  so on 60.73%. Their median capture ratios were 0.123 and 0.239 respectively,
  but the improvement in capture efficiency did not produce stable net PnL.

The tail exists descriptively. It is not monetized reliably by simply holding
to regime flip or by either fixed positive floor.

## Protective-floor diagnostic

| Variant / period | Armed | Floor exits | Avg saved | Avg lost | +2A / +3A / +4A runners clipped | Givebacks avoided | Net vs V0 |
|---|---:|---:|---:|---:|---:|---:|---:|
| V75_25 combined | 2,696 | 2,161 | $223 | -$491 | 801 / 547 / 385 | 1,481 | $479 |
| V75_25 2025 | 1,991 | 1,598 | $219 | -$469 | 588 / 404 / 284 | 1,101 | $10,681 |
| V75_25 2026 | 705 | 563 | $235 | -$549 | 213 / 143 / 101 | 380 | -$10,202 |
| V100_50 combined | 2,380 | 1,918 | $232 | -$522 | 705 / 508 / 368 | 1,309 | -$10,315 |
| V100_50 2025 | 1,748 | 1,401 | $224 | -$485 | 510 / 371 / 270 | 958 | $1,969 |
| V100_50 2026 | 632 | 517 | $255 | -$621 | 195 / 137 / 98 | 351 | -$12,284 |

V75_25 saved only $479 more combined giveback than it clipped, then reversed
from +$10,681 in 2025 to -$10,202 in 2026. V100_50 clipped more than it saved.
The direct answer is **no robust protective-floor edge is visible**.

## Execution and ambiguity accounting

- Horizon exits occur at the frozen decision timestamp's 1-second open before
  consuming that bar's range.
- Initial-stop and protective-floor exit bars are excluded from causal MFE
  because OHLC cannot order the stop touch and favorable extreme.
- An initial SL has priority over favorable events on its resolution bar.
- A floor arms after its arming bar and becomes active on later bars.
- PT1 plus an active floor defers the floor to later bars.
- There was one imported PT/SL same-bar tie, conservatively assigned SL-first.
- Arm/floor same-bar deferred diagnostics: 97 for each protected variant.
- Horizon/floor same-timestamp retrospective diagnostics: 10 for V75_25 and 7
  for V100_50. These inspect post-open range only as retrospective labels and
  never affect fills or PnL.
- PT1/active-floor deferred count and floor/+2A, +3A, +4A unordered counts were
  all zero in this population.
- In 309 V0 paths the runner's horizon preceded Contract 1 resolution; the
  runner exited at the horizon while Contract 1 continued its frozen bracket.

## Answers to the requested questions

1. **Improve over the pure bracket?** No. Best combined result, V75_25, was
   -$55,893 versus -$46,753 for the pure bracket.
2. **Improve over Policy A?** No. Policy A earned $9,873 combined and had much
   lower drawdown.
3. **Did the runner overcome second-contract risk?** No. Every runner net
   contribution was negative combined, and max drawdown rose to $82k-$90k.
4. **Did either floor improve the runner?** V75_25 improved V0 by only $479
   combined and failed the year-stability test; V100_50 reduced V0 by $10,315.
5. **Best on 2025 development?** V75_25, at -$65,131; it was still a failure.
6. **Hold up in 2026?** It remained positive at $9,238, but underperformed V0,
   Policy A, and its own floor contribution reversed sign.
7. **Stable by side/session?** No. Short/RTH survived, while long fades and the
   complete ETH/RTH groups remained negative.
8. **Test a W4-armed EMA/structural runner stop next?** Not from this evidence.
   The descriptive tail remains interesting, but simple runner monetization
   failed and does not justify a new structural-stop policy without a separate,
   predeclared hypothesis and fresh audit.

## Audit and artifacts

The initial pre-execution audit blocked the run with 2 CRITICAL and 2 WARNING
findings. All were repaired. The final pre-execution re-audit passed with
**0 CRITICAL, 0 WARNING**; deterministic sequencing tests passed **15/15**.
The completion audit is recorded separately in the study's `audit` folder.

Machine-readable deliverables in this folder:

- `w4_pt_runner_policy_results.parquet`
- `w4_pt_runner_trade_diffs.parquet`
- `w4_pt_runner_tail_diagnostics.parquet`
- `w4_pt_runner_protective_stop_diagnostics.parquet`
- `run_manifest.json`
