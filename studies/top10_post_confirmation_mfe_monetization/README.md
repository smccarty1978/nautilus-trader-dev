# Post-Confirmation MFE Monetization

Tests whether the first P90 warning of the fade model belonging to the NEW
confirmed regime can be used to exit or protect accumulated MFE, against a target
of recovering 35–50% of the ~0.89 ATR/original-entry giveback pool.

Frozen contract: [`SPEC.md`](SPEC.md) · Results: [`REPORT.md`](REPORT.md)

**Verdict: `F — NO ROBUST POST-CONFIRMATION MFE MONETIZATION FOUND`.** Best
recovery **0.6%**. P90 is a genuine exhaustion marker but fires after the giveback
has already happened.

---

## Three things to know first

### 1. Contract-valid P90 (stream A) is not measurable

It fires on 0.4% of `CONFIRMED_THEN_STOPPED` and 1.0% of `FINAL_FLIP_EXIT_LOSER`
but **47.9%** of `FINAL_FLIP_EXIT_WINNER`, because the in-domain flag needs the
new regime *established* (median 352–448s after confirmation) and only long-lived
trades get there. Its existence is nearly perfectly correlated with the outcome it
is meant to predict, so `P90A_EXIT`'s headline number is a survivorship artifact.
Labelled **NOT INTERPRETABLE — SURVIVORSHIP**, not merely "not deployable".

Stream B (raw causal) has 97–99.6% coverage on every outcome group and is the
primary object of study, labelled **EXPLORATORY_OUT_OF_DOMAIN** throughout. A and
B are never pooled.

### 2. Both denominators, always

Per-original-entry figures include the 4,245 trades stopped **before**
confirmation. Policies cannot touch those, so they cancel from every delta — but
omitting them from the level reports a baseline of **+0.4298** instead of the true
**−0.0765**. That single choice is the difference between an inflated study and a
reconciled one.

### 3. Two giveback pools

Measured over all confirmed trades the pool is 1.114 ATR/entry; the accepted
excursion study measures it flip-exit-only at 0.899. **Recovery is reported
against the accepted definition** (this study reproduces it at 0.898), with the
wider pool shown alongside.

---

## Reproducing

```bash
python scripts/causal_lint.py --study studies/top10_post_confirmation_mfe_monetization \
    --json studies/top10_post_confirmation_mfe_monetization/audit/lint.json
python -m studies.top10_post_confirmation_mfe_monetization.implementation.build
python -m studies.top10_post_confirmation_mfe_monetization.analysis.policies
```

`build` is the expensive step. It walks each confirmed trade **once** and
evaluates all 16 policies inline — a per-policy re-walk would let a subtle window
difference masquerade as an edge.

## Module map

| Path | Role |
|---|---|
| `implementation/engine.py` | the single-pass walk; all policies evaluated on identical bars |
| `implementation/build.py` | confirmed population, P90/P80 first-crossing location (A and B), panel |
| `analysis/policies.py` | Phases 5–12: economics, runner destruction, recovery, containment, stability |

## The result in one block

```text
P90B_EXIT, the best measurable policy:
  +2,157 ATR   saved containing confirmed losers (96.6% improved)
  -4,875 ATR   surrendered cutting 61.0% of >=3 ATR runners short
  ---------
    +45.6 ATR  over 8,950 entries = +0.0051/entry = 0.6% of the pool
```

Win rate 0.515 → 0.846 and median capture 0.059 → 0.282, all of it paid for out
of the right tail. **Capture ratio measures how tidily you harvest, not how much
you make.**

## Disclosures

- **2025 is NOT threshold-out-of-sample** (inherited waiver). 2026 untouched.
- `top_20` verified present for both models, `is_frozen=true`, provenance
  `RECONSTRUCTED_FROM_FROZEN_CALIBRATION_DISTRIBUTION`, so Phase 8 ran and no
  interpolated level was needed.
- No placebo control was run because no policy showed an effect to control for.
  If a future variant does, a count-matched random exit is mandatory first.
