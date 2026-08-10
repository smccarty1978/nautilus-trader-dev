# Post-Confirmation Score Deterioration / Runner Protection

Exit / trade-management **diagnostic** study. Asks whether, after a regime
confirms, change in the model score can identify trades that will fail early
enough to preserve open profit, without ejecting the large runners.

Frozen contract: [`SPEC.md`](SPEC.md) · Results: [`REPORT.md`](REPORT.md) ·
Resumable state: [`CHECKPOINT.md`](CHECKPOINT.md)

**Verdict: `POST-CONFIRMATION SCORE PREDICTS FAILURE BUT TOO LATE TO MONETIZE`.**
The score predicts failure well (landmark AUC 0.684 → 0.780). It is unusable for
management: when the signal fires the position is already 0.20–1.04 ATR
underwater, and acting on it does not beat a matched random exit at **any** of 25
operating points.

---

## Three things to know before reading any artifact

### 1. The polarity is inverted relative to the obvious reading

After confirmation we hold a position **aligned with the new regime**. The model
whose domain is that regime predicts **its own flip** — i.e. the end of our
position.

```text
domain-model score RISING  = our regime is likely ending = DANGER
domain-model score FALLING = our regime is persisting    = RUNNER
```

Deterioration is **escalation**, not retreat. Events are named `ESCALATION_*` so
the sign error cannot creep back in through vocabulary.

### 2. There are three score streams and only one is usable

The `*_in_domain` flag is a **contract gate** (may this score qualify a trade?),
not an **availability gate** (does a number exist?).

| Stream | Definition | Coverage on failed trades |
|---|---|---:|
| **A** in-domain-flagged | where the `*_in_domain` flag is true | **7.7% — excluded** |
| **B** domain-model raw *(primary)* | the model matching the new regime's direction, ungated | **100%** |
| **C** other-model raw | the opposite column, exploratory | ~100% |

Stream A's availability is *determined by the outcome* — the established-regime
gate opens a median 352–448s after confirmation while failed trades die at a
median 217–300s. Do not resurrect it.

Stream B is read outside its contractual domain, so **the frozen Top-10/5/2.5/1
thresholds do not transfer to it.** Threshold-loss events are reported NOT
APPLICABLE rather than reconstructed from invented cutoffs.

### 3. Landmark evaluation is mandatory

Every diagnostic is evaluated at a **fixed elapsed time from confirmation, among
trades still open at that time**. Path summaries over a window ending at the
terminal event are confounded with duration, and that confound has corrupted a
result in this research line **twice** — the shape classes in the predecessor
study, and Phase 0 probe 1 here, where winners' apparently higher peak score
(0.540 vs 0.331) was almost entirely an artifact of 111 observations versus 16.

---

## Reproducing

```bash
python scripts/causal_lint.py --study studies/post_confirmation_score_deterioration \
    --json studies/post_confirmation_score_deterioration/audit/lint.json

python -m studies.post_confirmation_score_deterioration.implementation.build_panel
python -m studies.post_confirmation_score_deterioration.analysis.events
python -m studies.post_confirmation_score_deterioration.analysis.landmark_tradeoff
python -m studies.post_confirmation_score_deterioration.analysis.gate2_ledger
python -m studies.post_confirmation_score_deterioration.analysis.placebo
python -m studies.post_confirmation_score_deterioration.implementation.validate
```

`build_panel` is the only expensive step (~4 min; loads 5.7M RTH score rows and
writes a 658k-row panel). Everything else is a query over its parquet.

Depends on `studies/armed_fade_score_path_progression/results/armed_regime_score_paths.parquet`,
which is gitignored and regenerable from that study (~7 min).

## Module map

| Path | Role |
|---|---|
| `implementation/phase0_probe.py` | population reconciliation, polarity, score availability |
| `implementation/phase0_probe2.py` | established-gate timing vs trade duration; stream A verdict |
| `implementation/phase0_gate1.py` | Gate 1 landmark AUC on streams B and C |
| `implementation/build_panel.py` | the Phase 1 panel, one row per (trade, dispatch) |
| `analysis/events.py` | path-threshold events, economics, runner touch |
| `analysis/landmark_tradeoff.py` | Gate 2 sensitivity/damage curve |
| `analysis/gate2_ledger.py` | the ATR counterfactual ledger |
| `analysis/placebo.py` | **the control that decides the study** |
| `implementation/validate.py` | the nine SPEC §9 gates |

## Two results worth carrying forward

> **Path-threshold events are structurally useless on this substrate.** Over a
> trade carrying 41–179 dispatches the score is near-certain to rise 0.03–0.10
> off its running minimum at some point, so every escalation event fires on ~100%
> of trades with precision exactly equal to the base rate. This is a property of
> the event definition, not of the market, and it will recur for any
> retreat/re-expansion construction on a long window.

> **Any early-exit rule must be placebo-controlled against a matched random
> exit.** The baseline here — holding to the opposing flip — is known to be a bad
> exit, so anything that exits earlier looks profitable. The ledger showed +246
> ATR before the control and nothing after it.

## Disclosures

- **2025 is NOT threshold-out-of-sample.** Both calibration populations are
  calendar-2025 and overlap the evaluation window. Canonical waiver:
  `studies/full_trade_path_builder/THRESHOLD_OVERLAP_WAIVER.json`.
- **2026 untouched.**
- Phase 8 (policy simulation) was **not run**, per the brief's stop rule.
