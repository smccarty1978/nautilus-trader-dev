# Study Report: Pure Flip Score Entry-Trigger Policy Test

**Study directory:** `studies/short_rth_pure_flip_score_entry_policy/`
**Final decision: `FLIP_SCORE_POLICY_WEAK_BUT_USEFUL`**

## Summary

The pure bearish-flip probability model (`[[pure_flip_prediction_inconclusive]]`,
regime-level power weak but row-level signal real) **does** monetize as a
within-regime entry trigger under frozen Policy A — the selected variant
(`trig_B_top2.5`: enter the first checkpoint per regime where the score
freshly crosses above the top-2.5%-by-2025-distribution threshold) beats
Baseline A decisively on 2025 and **stays solidly positive on sealed 2026**
(unlike every other trading-oriented study in this line of work, which went
negative on 2026). But it doesn't clearly beat Baseline A's 2026 economics,
and a winner-clipping check on 2026 shows the trigger's filtering gives up
more in removed opposing-flip winners than it saves in avoided stops —
hence "weak but useful," not "promising."

## 1. Can the pure flip score monetize as an entry trigger under frozen Policy A?

Yes, in the qualified sense: **2025** — 596 trades, +$22,184 net
(+$37.22/tr, PF 1.196, MAR-like score 1.374, max DD $16,140) — comfortably
clears every 2025 minimum (net positive, PF > 1.129, max DD ≤ $18,686,
$/trade ≥ $23.64). **2026** — 181 trades, +$2,679 net (+$14.80/tr, PF
1.071) — stays net positive with PF > 1.05, but $/trade is only 48% of
Baseline A's 2026 $31.01/tr (below the 0.5× "not materially worse"
threshold), and the winner-clipping check (below) shows real value being
left on the table by filtering.

## 2. Which trigger family worked best on 2025?

Family B (strict crossing from below) at the tightest threshold (top 2.5%):
`trig_B_top2.5` (MAR 1.374) narrowly beats `trig_A_top2.5` (plain
threshold, MAR 1.364) — the "fresh crossing" requirement adds a small edge
over "just being above the bar." Family D (persistence) at
`top5`/`30s` reaches a respectable MAR of 0.873 with fewer, larger trades
(428 trades, +$15,615, PF 1.185) — a reasonable second-place candidate.
Family C (rising confirmation) and looser thresholds across all families
underperform materially (`results/trigger_grid_results.csv`, full 25-variant
grid). Best-by-$/trade and best-by-PF (diagnostic only, not selection
criteria) both independently point to the same `trig_B_top2.5`/`trig_A_top2.5`
pair, reinforcing the MAR-based selection rather than contradicting it.

## 3. Did the selected trigger survive sealed 2026?

Partially. Net PnL stayed positive (+$2,679) and PF stayed above 1.0
(1.071), so this is **not** an overfit collapse — a meaningfully different
and better outcome than `[[short_rth_enriched_retrain_overfits_2025]]`
(which went to −$1,177/−$3.11 per trade on 2026) or the pure-flip study's
own row-level-vs-regime-level divergence. But $/trade fell from $37.22 to
$14.80 (a 60% decline), and the trade count fell from 596 to 181 — a real,
substantial degradation, just not a sign-flip.

## 4. Does it beat the current W4 short-RTH baseline?

**2025: yes, decisively** (+$37.22/tr vs Baseline A's +$23.64/tr, PF 1.196
vs 1.129). **2026: no** (+$14.80/tr vs Baseline A's +$31.01/tr) — Baseline A
itself performs unusually well on 2026 (its $/trade is actually *higher*
in 2026 than 2025), and the trigger doesn't keep pace. The baseline-mapping
attribution (`results/baseline_mapping_attribution.csv`) sharpens this: of
Baseline A's 650 (2025) / 222 (2026) candidates, the trigger keeps 486/156
(74.8%/70.3%) — and those KEPT trades earn $50.57/tr in 2025 (more than
double Baseline A's own blended $23.64/tr) but only $16.08/tr in 2026
(*half* of Baseline A's own $31.01/tr) — the same 2025-strong/2026-weak
pattern shows up even within the exact same shared regime population, not
just in aggregate.

## 5. Does it beat or approach the fixed-807 pocket?

No, on either split. Baseline B's blended $33.47/tr is well above the
trigger's $37.22/tr (2025, actually beats it) but the trigger's 2026
$14.80/tr falls far short of Baseline B's own strength. Of Baseline B's
604 (2025) / 203 (2026) regimes, the trigger keeps 448/141 (74.2%/69.5%);
kept-trade quality mirrors the Baseline A comparison (strong 2025, weak
2026).

## 6. What is the actual flip-within-300s rate for triggered trades?

61.9% (2025) / 68.0% (2026) — well above the pure-flip study's own overall
population base rate (~25%, `[[pure_flip_prediction_inconclusive]]`) and
consistent with the top-decile lift (~2x) reported there. The trigger is
successfully concentrating on genuinely high-flip-probability checkpoints;
the gap between this row-level success and the weaker $/trade result is
attributable to Policy A's exit mechanics and path behavior (see §8-9), not
to the trigger failing at its own stated job.

## 7. What are the exit reason counts and PnL?

| Split | Exit reason | Count | % | Net PnL |
|--|--|--:|--:|--:|
| 2025 | opposing_flip_exit | 318 | 53.4% | +$98,620 |
| 2025 | preflip_policy_stop | 151 | 25.3% | −$54,395 |
| 2025 | confirmation_timeout | 90 | 15.1% | −$5,745 |
| 2025 | post_align_stop | 37 | 6.2% | −$16,296 |
| 2026 | opposing_flip_exit | 105 | 58.0% | +$25,565 |
| 2026 | preflip_policy_stop | 41 | 22.7% | −$16,775 |
| 2026 | confirmation_timeout | 21 | 11.6% | −$70 |
| 2026 | post_align_stop | 14 | 7.7% | −$6,041 |

Opposing-flip exits dominate both years (53-58% of trades) and are the
sole source of gross profit — consistent with §6's high flip-rate. The
pre-alignment stop remains the single largest loss driver in both years.

## 8. How many selected trades were winners before becoming losers?

Substantial, and this is the study's clearest actionable finding
(`results/winner_giveback_counts.csv`). In 2025 (596 trades): **504 (84.6%)**
were ever up ≥0.25 ATR at some point; of those, **326 (64.7% of the 504)**
still closed as losers. Even at the demanding ≥1.00 ATR threshold, **311
trades (52.2% of all trades)** reached it, and **146 of those (46.9%)**
still closed as losers. 2026 shows the same pattern (158/504-equivalent
rate ever up 0.25 ATR, 99 of those closing as losers). Restricting to
opposing-flip-exit trades specifically (the "winning" exit category)
doesn't eliminate this — even among opposing-flip exits, large fractions
were up substantially at some point before ultimately following the
post-alignment giveback path to a smaller realized gain or an outright
loss via the 1.50×ATR post-alignment stop.

## 9. Does the path suggest a future profit-protection exit could help?

**Yes, strongly** — this is the study's most actionable diagnostic
finding, though per SPEC no such exit is designed here. Nearly half of
trades that reach a full 1.0 ATR favorable excursion still end as losers.
Combined with §7's exit-reason table (post-alignment stops and
confirmation timeouts together account for real, avoidable-looking losses
on trades that were favorable at some point), this is a clear, well-
evidenced signal that a trailing-stop or partial-profit-taking mechanism
layered on top of Policy A — not touched in this study — is the most
promising next lever, independent of further entry-trigger refinement.

## 10. Should the next study be stop/exit design, symmetric exit-flip model, or reject?

**Stop/exit design**, specifically profit-protection/giveback mitigation
(§8-9), not entry-trigger refinement and not rejection. The entry trigger
itself is doing its stated job (§6: 62-68% actual flip rate, well above
base rate) and does not need further iteration — the gap between row-level
trigger quality and realized $/trade is a **management** problem (how much
of a favorable move gets given back before exit), not a **selection**
problem. A "symmetric exit-flip model" is not indicated: the flip-detection
signal is already being used correctly as an entry trigger; the open
question is what happens *after* alignment, which post_align_mfe_atr/
post_flip_giveback_atr in `results/path_diagnostics.csv` already
characterize as the natural starting point for that follow-up study.

## Audit

Two passes, per this project's pre-execution-audit standing rule:

1. **Pre-execution** (on `path_logic.py`, the new raw-bar path-scanning
   module, tested on synthetic data before being applied to real trades):
   0 CRITICAL, 3 WARNING — all fixed (asymmetric exact-match validation,
   untested long-direction branch, unguarded year-boundary truncation) —
   plus one additional real bug (`align_open_price`'s exact-match
   requirement spuriously rejecting legitimate raw-data single-second
   gaps) found and fixed while wiring the module into real data, before
   re-requesting review.
2. **Completion-gate** (full pipeline): 0 CRITICAL, 4 WARNING — 3 fixed
   (Family D's 15s persistence-window structural no-op guard; a
   silent-pass-on-missing-file pattern in the winner-clipping check; a
   missing merge-validation guard), 1 left as a documented, verified-correct
   but implicit dtype dependency. **No look-ahead bias found anywhere** —
   every trigger family's causality (positional shift, exact-time lookback,
   backward-only rolling window) was traced and confirmed backward-looking
   only; 2025-only cutoff freezing verified by tracing actual variable
   flow, not just comments; `path_logic.py` confirmed never imported by the
   entry-selection code (`trigger_grid.py`), preserving the
   diagnostic-only/entry-decision separation the SPEC requires.

Re-running the full pipeline after all fixes reproduced the identical
selected trigger and decision — the fixes only changed non-selected
variants' own numbers.

## Primary caveats

1. **Winner-clipping is real and unresolved** (`clip_ok = False` on 2026):
   removing regimes via this trigger's filtering gives up more in avoided
   opposing-flip winners than it saves in avoided pre-alignment stops.
   This is a genuine tension the "weak but useful" label is meant to
   capture, not paper over.
2. **The 2025-strong/2026-weak pattern recurs even within the exact same
   shared (kept) regime population** (§4) — this is not merely a
   composition-shift artifact (different regimes selected in different
   years); the SAME regimes perform differently by year, pointing at a
   genuine year-to-year regime-character shift this study does not
   explain.
3. Family D's audit-fixed persistence logic changed only non-selected
   variants' numbers — the selected trigger and final decision are
   unaffected, confirmed by direct re-comparison after the fix.

## Final decision: `FLIP_SCORE_POLICY_WEAK_BUT_USEFUL`

Real, non-collapsing signal that survives sealed 2026 in direction (stays
positive, PF > 1) but not in magnitude (well below Baseline A's own 2026
performance, and clipping real winners in the process). Not promising
enough to promote to NT validation as-is; the clear next step is
profit-protection/giveback exit design (§9-10), which this study's own
path diagnostics motivate directly.
