# W4 Countertrade Path Diagnostic — Final Report

**Decision label: `NO_MANAGEMENT_EDGE_VISIBLE`**

Exploratory diagnostic on the frozen CODEX 5.X repaired-W4 established-regime
fade trades (2025 development: 3,246 trades, net −$17,609; 2026 final test
through Apr 29: 1,137 trades, net +$7,596). Group totals reconcile exactly
with the frozen CODEX results. All excursions are in units of the trade's
frozen `atr_at_checkpoint` (the 1.5-ATR stop anchor); USD uses NQ $20/pt;
net = gross − $10 RT.

**Scope guards honored:** no threshold optimization, no policy backtest, no
2026-driven selection. Everything below is descriptive path measurement.
**Retrospective-descriptor rule:** in `trade_diagnostics.parquet` and
`post_flip_exit_diagnostic.parquet`, every path-derived per-trade scalar is
computed from the full realized path and is therefore retrospective — this
includes `peak_mfe_*`, `final_mae_atr`, `t_peak_*`, `capture_ratio`,
`giveback_*`, all `reached_*_atr` flags, `old_regime_new_extreme_ever` /
`t_old_regime_new_extreme_s`, `w4_last_*` / `w4_change_entry_to_last`,
`pnl_at_flip_*`, `post_flip_peak_mfe_atr`, `t_flip_to_post_peak_s`,
`post_flip_giveback_*`, `post_flip_max_adverse_atr`,
`post_flip_revisit_entry`, `post_flip_adverse_beyond_*_atr`, `w4_warn_ts`,
`t_flip_to_warn_s`, `pnl_at_warn_usd`, and `warned_before_exit`. Only the
entry-time fields (`w4_entry`, `w4_threshold`, `atr_at_checkpoint`,
direction/session) are decision-time causal. In `path_checkpoints.parquet`,
per-checkpoint state columns are causal at their `cp_ts` except rows flagged
`retrospective=True` (the `peak_mfe` checkpoint); `outcome_group` and
`net_pnl_usd_final` are post-hoc grouping labels. None of the retrospective
quantities may be used as decision inputs without a properly gated causal
test.

---

## 1. Executive summary

The policy's losses are **not** a trade-management problem that W4 can fix.

1. **Stop-before-flip trades (34% of trades, the largest loss bucket) are bad
   entries, not manageable pullbacks.** Median peak MFE before the stop is
   0.33 ATR (≈$60 gross), reached at a median of just 23s after entry; only
   34% ever reach +0.50 ATR. W4 collapses back below the trigger threshold in
   ~98% of them (median change entry→last −0.41), and the old regime reasserts
   *without* making a new extreme (only 11–12% print one). There is no
   monetizable MFE to harvest.
2. **The early window (+60s/+120s) separates eventual outcomes on identity
   but not on money.** AUC for "will eventually stop" from PnL@+120s is
   0.78/0.76 (2025/2026) — but **forward** PnL (final minus mark at the
   checkpoint) is flat across PnL and MAE quartiles and its sign is
   inconsistent across years. The apparent separation is money already lost
   plus mechanical proximity to the fixed stop. Cutting bad-looking trades
   early saves ~nothing in expectation. This is the same
   probability-vs-magnitude martingale surface seen in prior studies.
3. **Post-flip W4 is not a useful exit warning.** It fires before exit in
   77–89% of losing flip-reaching trades — but also in 83–91% of winners.
   Pooled counterfactual "exit at first warning" makes **less** money than
   the actual policy in both years (2025: $261K vs $291K; 2026: $113.5K vs
   $119K), because winners keep gaining after their W4 warnings.
4. **The one strong path asymmetry is price-based, not W4-based:** after the
   aligning flip, 98–100% of eventual losers revisit the countertrade entry
   price, vs only 37–39% of winners (stable across years). But an envelope
   calculation of a breakeven-at-flip stop is ≈ a wash (2025 ≈ −$5K worse,
   2026 ≈ +$7K better than actual, under generous exact-at-entry fills),
   because the 37% of winners it clips average +$446–480 each.

Bottom line: entries in the stop-before cohort fail immediately; survivors'
outcomes are decided by aligned-regime duration/magnitude, which nothing
observable at the checkpoints predicts in a monetizable way. This is an
**entry-quality / regime-duration problem**, consistent with the CODEX close
(`NO_MONETIZABLE_WEAKNESS_FADE`) and with the corpus-wide finding that
duration drives PnL and is unpredictable at decision time.

---

## 2. Key tables

### Outcome groups (split=all; full splits in `outcome_group_summary.parquet`)

| Year | Group | n | Mean net | Median peak MFE (ATR) | %≥0.25 | %≥0.50 | %≥0.75 | %≥1.00 | Med t_peak | Med peak→exit | Med capture | Med giveback |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2025 | stop_before | 1,107 | −$322 | 0.33 | 59% | 34% | 19% | 10% | 23s | 134s | −3.88 | $299 |
| 2025 | stop_after | 278 | −$250 | 0.86 | 87% | 75% | 58% | 42% | 105s | 160s | −1.71 | $310 |
| 2025 | flip-exit loser | 860 | −$122 | 1.41 | 99% | 94% | 86% | 74% | 229s | 243s | −0.40 | $285 |
| 2025 | flip-exit winner | 1,001 | +$513 | 3.86 | 100% | 100% | 100% | 100% | 842s | 297s | +0.41 | $360 |
| 2026 | stop_before | 369 | −$352 | 0.25 | 50% | 32% | 15% | 8% | 26s | 123s | −4.71 | $361 |
| 2026 | stop_after | 97 | −$341 | 1.03 | 93% | 78% | 63% | 53% | 131s | 155s | −1.45 | $451 |
| 2026 | flip-exit loser | 312 | −$149 | 1.39 | 98% | 94% | 85% | 74% | 254s | 225s | −0.42 | $390 |
| 2026 | flip-exit winner | 359 | +$604 | 3.81 | 100% | 100% | 100% | 99% | 809s | 314s | +0.42 | $445 |

### Early probation window (alive trades only; survivorship-conditioned by design)

At +60s / +120s after entry (medians; `early_window_summary.parquet` has full detail):

| Cp | Group (2025 / 2026) | PnL (ATR) | MFE | MAE | W4 Δentry | % flipped | % W4≥thr |
|---|---|---:|---:|---:|---:|---:|---:|
| +60s | stop_before | −0.36 / −0.39 | 0.27 / 0.21 | 0.67 / 0.68 | −0.11 / −0.12 | 0 / 0 | 30% / 28% |
| +60s | flip-exit winner | +0.26 / +0.27 | 0.61 / 0.58 | 0.29 / 0.27 | +0.02 / +0.02 | 32% / 30% | 45% / 48% |
| +120s | stop_before | −0.46 / −0.44 | 0.36 / 0.34 | 0.88 / 0.89 | −0.13 / −0.13 | 0 / 0 | 29% / 27% |
| +120s | flip-exit winner | +0.56 / +0.53 | 1.00 / 0.98 | 0.37 / 0.36 | +0.03 / 0.00 | 54% / 52% | 29% / 28% |

Note: "% flipped = 0" for stop_before is **definitional** (they stop before
the flip), not path information.

**Forward PnL by PnL-quartile at +120s (mean, gross USD after the checkpoint):**
2025: Q1 +$11, Q2 −$17, Q3 +$10, Q4 +$22. 2026: Q1 +$32, Q2 −$10, Q3 +$14,
Q4 +$40. At +60s: 2025 Q1 +$6, 2026 Q1 −$40 (sign flips across years). No
quartile carries a repeatable forward-money gradient; MAE quartiles are the
same. **This kills the early-exit hypothesis in expectation terms** despite
the strong identity AUC.

### Post-flip diagnostics (`post_flip_exit_diagnostic.parquet`)

| Year | Group | PnL at flip (med) | Post-flip peak (med ATR) | t to post-peak (med) | Giveback (med) | % W4-warned | t warn (med) | PnL at warn (med) |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| 2025 | stop_after | +$40 | 0.82 | 34s | $306 | 77% | 165s | −$80 |
| 2025 | flip loser | +$80 | 1.39 | 75s | $280 | 83% | 235s | −$30 |
| 2025 | winner | +$135 | 3.86 | 622s | $360 | 89% | 525s | +$225 |
| 2026 | stop_after | +$55 | 0.87 | 40s | $421 | 86% | 155s | −$115 |
| 2026 | flip loser | +$100 | 1.36 | 83s | $385 | 88% | 238s | −$45 |
| 2026 | winner | +$160 | 3.81 | 679s | $445 | 91% | 515s | +$258 |

**Post-flip revisit of entry price** (adverse excursion from entry after the
aligning flip): losers 98–99%, stop_after 100%, winners 37–39%. At a 0.25 ATR
buffer: losers 89–92%, stop_after 99–100%, winners 25%. At 0.50 ATR: losers
72–76%, stop_after 97–99%, winners 15–16%. (Three fixed descriptive levels;
no level selection was performed.)

**W4-warning exit counterfactual (pooled, warned flip-reaching trades):**
2025 actual $290.8K vs at-warning $261.3K; 2026 actual $119.2K vs at-warning
$113.5K. Warning-timed exit loses money both years.

---

## 3. Strongest path differences between winners and losers

Ranked by stability across both years:

1. **Post-flip entry revisit** (98–100% losers vs 37–39% winners) — the
   single largest separation found, price-based, visible only after the flip.
2. **Time-to-peak asymmetry**: stop_before peaks at ~23–26s and dies;
   winners' peaks arrive at ~14 min (median 809–842s from entry, 622–679s
   after the flip). Winner PnL is duration, not early velocity.
3. **W4 trajectory pre-stop**: stop_before W4 falls back below threshold in
   ~98% (median Δ −0.41); winners' faded-regime W4 drifts flat/slightly up
   pre-flip. Real signal about identity — but the forward-PnL conditioning
   shows no money in acting on it.
4. **Early MAE** (0.67–0.89 ATR for eventual stops vs 0.27–0.37 for winners
   at +60/+120s) — largely mechanical distance-to-stop; forward PnL flat.

## 4. Did stop-outs have monetizable MFE before failing?

**No.** Stop-before trades: median peak 0.33/0.25 ATR (≈$50–60 gross ≈
$40–50 net), 66% never reach +0.50 ATR, peak arrives at ~23s. Both fade
directions look the same (long fades: 0.34/0.26 ATR median peak; short fades:
0.32/0.25). Stop-after trades did carry ~0.85–1.0 ATR of post-flip MFE
(≈$150–170 gross) that fully evaporated into the entry-anchored stop — see
§5 for why harvesting it nets ≈ zero.

## 5. Did aligned-flip losers have preventable giveback?

**Giveback exists; no tested causal harvest keeps it.** Flip-exit losers were
+$80–100 at the flip and peaked +1.4 ATR post-flip before decaying; stop_after
trades peaked +0.85 ATR at 34–40s post-flip. But:

- The W4 warning arrives at ~155–238s post-flip — *after* the 34–83s
  post-flip peaks of the losing groups — with PnL already negative
  (−$30…−$115 median), and it fires indiscriminately in winners.
- The breakeven-at-flip envelope (the strongest discriminator, generous
  fills) is ≈ a wash: 2025 ≈ −$5K vs actual, 2026 ≈ +$7K. The sign flips
  across years; the winners it clips average +$446–480.

## 6. Is W4 progression useful for early or post-flip exit?

**Pre-flip:** W4 decay identifies future stop-outs (AUC ~0.64–0.67 at +60s)
but is weaker than price/MAE, and none of them carry forward money.
**Post-flip:** not selective (fires in ~9 of 10 winners); acting on it loses
money in both years. As an exit tool, W4 is **not useful** in this policy.

## 7. Recommended next policy hypotheses (max 3; expectations low)

Evidence-grounded candidates, **only** if this branch is pursued further —
each requires the Safe Exit Replay Framework, matched-placebo controls, and
a pre-execution audit (per the repo gates; prior stop-timing candidates have
repeatedly lost to matched placebos):

- **H1 — Post-flip adverse-excursion stop (BE or fixed small buffer at the
  aligning flip).** Grounded in the 98%-vs-37% revisit asymmetry. The
  BE-level envelope is a wash, so the test would be of the *buffered* form —
  but choosing the buffer is exactly the optimization this study forbids, so
  it must be a predeclared, placebo-gated test on pre-2026 data only.
  Expectation: LOW (envelope math nets ≈ zero; martingale surface).
- **H2 — W4 persistence confirmation at entry** (require the score to remain
  above threshold at the next 5s checkpoint(s) before filling). Grounded in
  stop-before trades' immediate W4 collapse and 23s peaks. Caution: the
  delayed-entry repair study found delay benefits are pure survival filters;
  this must be tested against a matched time-delay placebo.
- **No third candidate is recommended.** Post-flip add-ons/re-entries are
  ruled out by the probe-and-add dead branch, and early probation exits are
  ruled out by the flat forward-PnL result above.

## Limitations / evidence vs speculation

**Evidence:** all tables above; deterministic recomputation from frozen 1s
raw bars + frozen score streams (SHA-256-verified against the CODEX policy
input contract); trade-total reconciliation exact to the CODEX report.
**Speculation:** the H1/H2 mechanisms; the BE-stop envelope (assumes
exact-at-entry exit fills, ignores gap-through and re-entry effects; not a
simulation). The trades parquet itself is a runner output with no upstream
hash contract (verified only by exact PnL reconciliation). All of this is
1s-OHLC research measurement, not NT-native execution. Trades exiting before
a checkpoint are absent from that checkpoint's aggregates (alive-conditioning
is explicit via `n_alive`/`pct_alive`).

## Artifacts

- `path_checkpoints.parquet` — 44,252 rows (4,383 trades × up to 12 checkpoints)
- `trade_diagnostics.parquet` — per-trade scalars
- `outcome_group_summary.parquet`, `early_window_summary.parquet`,
  `post_flip_exit_diagnostic.parquet`
- Audit: `audit/pre_execution_audit.md` (PASS after fixes; re-audit section)
