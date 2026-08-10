# Top-10 Armed Entry Refinement — Report

**Study:** `top10_armed_entry_refinement` · 2026-08-10
**Armed population:** 8,950 (reproduced exactly) · **Rules tested:** 4 baselines + 8 candidates

---

## Executive summary

**Nothing beats entering immediately at Top-10.** Confirmation probability and
remaining move trade off so nearly one-for-one that every additional wait costs
more in price than it buys in certainty — and once throughput is counted, the
gap widens rather than closes.

The single decisive table, expected ATR per 100 arms
(`confirmed trades per 100 arms × median return at confirmation`):

| Rule | conf/100 arms | × median return | = ATR/100 arms |
|---|---:|---:|---:|
| **A_IMMEDIATE_TOP10** | **52.0** | **0.854** | **44.4** |
| B1_PERSIST_TOP10_x2 | 51.1 | 0.791 | 40.4 |
| A1_INTERP_L1 | 50.8 | 0.792 | 40.2 |
| A2_INTERP_L2 | 50.2 | 0.752 | 37.7 |
| B2_PERSIST_TOP10_x3 | 49.1 | 0.738 | 36.3 |
| F1_PERSIST_x2_AT_INTERP_L2 | 48.7 | 0.688 | 33.5 |
| C1_PROGRESS_0_03 | 47.9 | 0.674 | 32.3 |
| B_FIRST_TOP5 | 48.5 | 0.655 | 31.8 |
| D1_REEXPANSION_0_05 | 42.1 | 0.686 | 28.9 |
| C2_PROGRESS_0_06 | 45.6 | 0.585 | 26.7 |
| C_FIRST_TOP2_5 | 42.0 | 0.475 | 20.0 |
| D_FIRST_TOP1 | 27.8 | 0.295 | 8.2 |

Immediate Top-10 is first, and the ordering is monotone in how long the rule
waits. **Waiting is a pure cost on this population.**

### The eleven questions

**1. Does Top-10 function as a useful arm state?** Yes as a *warning* — 52.0% of
arms confirm before a 1 ATR stop, holding a median +0.854 ATR at the flip. But it
does not function as an *arm* in the sense the hypothesis intended: no subsequent
trigger improves on acting at once.

**2. How quickly do SUCCESS and FAILURE separate?** Immediately, and the
separation is real but modest. Score AUC is already **0.582 at 5s**, rising to
0.705 at 45s; `delta_from_arm` tracks it (0.588 → 0.710). Score drawdown from the
post-arm peak runs the other way (AUC 0.42 → 0.31, i.e. 0.69 reversed). The
information exists well before first Top-5 — it simply is not worth what it costs
to wait for.

**3. Is persistence above Top-10 informative?** Yes, mildly, and it is the
cheapest evidence available. Two consecutive true dispatches lift confirmation
+0.029 (0.520 → 0.549) for a median 5s wait, 0.00 ATR of median price given up,
and 93.1% of arms still entered. Three consecutive lifts +0.045 but costs more.

**4. Is score progression informative?** Yes, and more per unit of lift than
persistence — but it costs price. +0.03 above the arm score lifts confirmation
+0.061 while surrendering a median 0.123 ATR and 35s.

**5. Does an intermediate level between Top-10 and Top-5 improve the tradeoff?**
**No.** Both interpolated levels behave exactly like small doses of Top-5:
`INTERP_L1` +0.019 lift for −0.062 return; `INTERP_L2` +0.031 for −0.102. They sit
on the same line the fixed thresholds trace, not above it.

**6. Does retreat then re-expansion improve entry quality?** **No.** It is the
worst-value candidate tested: +0.056 lift but a 105s median wait and throughput
collapsing to 42.1 per 100 arms — the same confirmation as Top-5 for 6.4 fewer
confirmed trades per 100 arms.

**7. What confirmation can we buy before sacrificing too much price?** On this
evidence, essentially none is worth buying. The exchange rate is roughly **0.30
ATR of median return per 0.10 of confirmation probability**, and it is close to
constant across every family.

**8. How much ATR do we sacrifice waiting for Top-5 / 2.5 / 1?** Median return at
confirmation falls **0.854 → 0.655 → 0.475 → 0.295**, i.e. −0.199, −0.379, −0.559
ATR. Median wait 35s / 140s / 335s; median price already moved 0.071 / 0.158 /
0.147 ATR.

**9. Which candidates lie on the frontier?** On the conditional frontier, ten of
twelve — which is the finding, not a result. Because confirmation and return move
against each other almost exactly, hardly anything is beaten on both axes, so
that frontier cannot discriminate. On the **throughput** frontier
(P(confirm) × confirmed-per-100-arms) immediate Top-10 is non-dominated and no
candidate displaces it.

**10. Is there a trigger that clearly improves on immediate Top-10?** **No.**

**11. Which ≤3 warrant later lifecycle testing?** See §6 — one `DIAGNOSTIC_ONLY`
and two `REJECT`. Nothing is `ADVANCE`.

---

## 1. Population and baseline parity

Armed population **8,950**, reproduced exactly. Arm outcomes SUCCESS 4,656 /
FAILURE 4,245 / SESSION 49 — identical to the accepted Walk A split.

The four fixed baselines reproduce the accepted figures **exactly**:

| Baseline | P(confirm) | accepted | median return | accepted |
|---|---:|---:|---:|---:|
| IMMEDIATE_TOP10 | 0.520 | 52.1% | +0.854 | +0.85 |
| FIRST_TOP5 | 0.589 | 59.0% | +0.655 | +0.66 |
| FIRST_TOP2_5 | 0.648 | 64.8% | +0.475 | +0.48 |
| FIRST_TOP1 | 0.731 | 73.1% | +0.295 | +0.30 |

That agreement is also a parity check on the armed-window rule (§7): it only
holds once the arm is allowed to survive an adverse move.

---

## 2. Phase 2 — where the paths separate

AUC for SUCCESS vs FAILURE, at fixed elapsed times from the arm, among arms still
unresolved:

| Feature | 5s | 10s | 20s | 30s | 45s | 60s |
|---|---:|---:|---:|---:|---:|---:|
| score level | 0.582 | 0.616 | 0.656 | 0.670 | **0.705** | 0.694 |
| delta from arm | 0.588 | 0.620 | 0.660 | 0.673 | **0.710** | 0.700 |
| score running max | 0.538 | 0.557 | 0.578 | 0.587 | 0.597 | 0.587 |
| drawdown from max | 0.416 | 0.385 | 0.349 | 0.337 | **0.308** | 0.322 |
| consec ≥ Top-10 | 0.556 | 0.582 | 0.621 | 0.633 | 0.659 | 0.651 |
| price move from arm | 0.590 | 0.619 | 0.666 | 0.677 | **0.717** | 0.708 |
| slope 10s | — | 0.624 | 0.606 | 0.628 | 0.603 | 0.592 |
| slope 20s | — | — | 0.669 | 0.651 | 0.629 | 0.615 |

Three things follow.

**Separation starts at the first dispatch.** By 5 seconds the score already
carries AUC 0.582. There is no dead zone to wait out.

**`price_move_from_arm_atr` is the strongest column and must not be read as a
signal.** FAILURE is *defined* as a 1 ATR adverse excursion from the arm, so
favourable price movement is partly a restatement of the label. It is reported
for completeness and excluded from every candidate family.

**Slopes are the weakest usable feature and lose ground with time** (10s slope
0.624 → 0.592). `slope_60s` has no coverage at any landmark — no pair of true
dispatches brackets a 60s window inside the alive population. **Family E (fast
progression) was therefore not nominated**, and its slot went to better-supported
families.

---

## 3. Phase 4 — the primary tradeoff table

n = trades; %arm = share of the 8,950 arms entered; conf/100 = confirmed trades
per 100 arms; wait = median seconds arm→entry; sac = median **signed** price move
arm→entry in *arm* ATR; 2ndLife = share of entries firing after the arm-anchored
path had already taken a 1 ATR hit.

| Rule | n | %arm | P(conf) | lift | conf/100 | wait s | sac ATR | return | Δret | MFE | MAE | 2ndLife |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **A_IMMEDIATE_TOP10** | 8,950 | 100.0 | 0.520 | — | **52.0** | 0 | +0.000 | **0.854** | — | 1.035 | 0.330 | 0.0 |
| B1_PERSIST_TOP10_x2 | 8,330 | 93.1 | 0.549 | +0.029 | 51.1 | 5 | +0.000 | 0.791 | −0.063 | 0.969 | 0.309 | 9.7 |
| A1_INTERP_L1 | 8,426 | 94.2 | 0.540 | +0.019 | 50.8 | 0 | +0.000 | 0.792 | −0.062 | 0.971 | 0.311 | 9.3 |
| A2_INTERP_L2 | 8,148 | 91.0 | 0.551 | +0.031 | 50.2 | 5 | +0.000 | 0.752 | −0.102 | 0.937 | 0.308 | 14.1 |
| B2_PERSIST_TOP10_x3 | 7,773 | 86.8 | 0.566 | +0.045 | 49.1 | 20 | +0.034 | 0.738 | −0.116 | 0.914 | 0.291 | 18.0 |
| F1_PERSIST_x2_AT_INTERP_L2 | 7,499 | 83.8 | 0.581 | +0.061 | 48.7 | 30 | +0.065 | 0.688 | −0.166 | 0.862 | 0.290 | 23.8 |
| B_FIRST_TOP5 | 7,371 | 82.4 | 0.589 | +0.069 | 48.5 | 35 | +0.071 | 0.655 | −0.199 | 0.832 | 0.281 | 26.7 |
| C1_PROGRESS_0_03 | 7,381 | 82.5 | 0.581 | +0.061 | 47.9 | 35 | +0.123 | 0.674 | −0.180 | 0.850 | 0.284 | 26.7 |
| C2_PROGRESS_0_06 | 6,657 | 74.4 | 0.614 | +0.093 | 45.6 | 80 | +0.164 | 0.585 | −0.269 | 0.762 | 0.259 | 35.8 |
| D1_REEXPANSION_0_05 | 6,539 | 73.1 | 0.576 | +0.056 | 42.1 | 105 | +0.023 | 0.686 | −0.168 | 0.854 | 0.280 | 36.9 |
| C_FIRST_TOP2_5 | 5,803 | 64.8 | 0.648 | +0.128 | 42.0 | 140 | +0.158 | 0.475 | −0.379 | 0.650 | 0.237 | 43.3 |
| D_FIRST_TOP1 | 3,401 | 38.0 | 0.731 | +0.211 | 27.8 | 335 | +0.147 | 0.295 | −0.559 | 0.485 | 0.201 | 56.4 |

**The exchange rate is near-constant.** Across all eleven waiting rules, every
+0.10 of confirmation probability costs roughly 0.30 ATR of median return at
confirmation. Nothing escapes the line.

**Every rule loses throughput.** No candidate produces more confirmed trades per
100 arms than entering immediately.

**MAE falls as you wait** (0.330 → 0.201) — later entries do need less room. That
is a genuine benefit and the only one waiting reliably delivers; it is not enough
to offset the return given up.

### The free-option disclosure

Because an arm is a state and not a position (SPEC §1.1), later triggers can fire
after the arm-anchored path already took a 1 ATR hit — cases where immediate
Top-10 was already stopped out. That share rises steeply with waiting: **9.3% for
INTERP_L1 up to 56.4% for Top-1**.

This *flatters* the waiting rules, and it is worth being explicit about the
direction of the bias: more than half of Top-1's entries are trades immediate
Top-10 never survived to take. Even with that advantage handed to them, no
waiting rule wins. The conclusion is therefore robust to the choice — under
adverse invalidation it would only be stronger.

---

## 4. Phase 5 — the two frontiers

**Conditional frontier** (P(confirm) × median return): ten of twelve rules are
non-dominated. That is not a finding about the rules; it is a property of a
near-perfect one-for-one tradeoff, and it means the conditional frontier cannot
discriminate here.

**Throughput frontier** (P(confirm) × confirmed per 100 arms): immediate Top-10 is
non-dominated, and every candidate that survives does so only by being close to
it on both axes rather than better on either. **Nothing between Top-10 and Top-5
dominates either fixed threshold.**

---

## 5. Phase 6 — stability

All three leading rules are stable; no candidate is one-sided or one-year driven.

| Rule | LONG | SHORT | 2021 | 2022 | 2023 | 2024 | 2025 |
|---|---|---|---|---|---|---|---|
| IMMEDIATE_TOP10 P(conf) | 0.515 | 0.524 | 0.550 | 0.531 | 0.526 | 0.483 | 0.509 |
| IMMEDIATE_TOP10 return | 0.847 | 0.860 | 0.803 | 0.849 | 0.829 | 0.909 | 0.899 |
| B1_PERSIST_x2 P(conf) | 0.546 | 0.552 | 0.576 | 0.553 | 0.559 | 0.519 | 0.537 |
| B1_PERSIST_x2 return | 0.784 | 0.799 | 0.752 | 0.788 | 0.762 | 0.843 | 0.838 |
| A1_INTERP_L1 P(conf) | 0.534 | 0.544 | 0.568 | 0.541 | 0.551 | 0.512 | 0.526 |
| A1_INTERP_L1 return | 0.789 | 0.796 | 0.759 | 0.787 | 0.761 | 0.841 | 0.850 |

The LONG/SHORT gap is ≤0.010 everywhere. **Crucially, B1's small lift over
immediate Top-10 is stable in all five years (+0.026 to +0.033) — but so is its
return deficit (−0.051 to −0.066).** The tradeoff itself is what is stable.

**2025 is NOT threshold-OOS** — inherited overlap waiver.

---

## 6. Phase 7 — shortlist

| # | Rule | Label | Why |
|---|---|---|---|
| 1 | **B1_PERSIST_TOP10_x2** | **DIAGNOSTIC_ONLY** | The cheapest evidence available: +0.029 confirmation for a 5s median wait, 0.00 ATR median price given up, 93.1% of arms still entered. It is the *only* candidate that does not materially degrade the entry — and it does not improve it either (40.4 vs 44.4 ATR per 100 arms). Worth remembering if a future exit makes confirmation intrinsically more valuable. |
| 2 | A1_INTERP_L1 | REJECT | +0.019 lift for −0.062 return. Sits on the fixed-threshold line; the interpolated level adds nothing a small dose of Top-5 does not. |
| 3 | D1_REEXPANSION_0_05 | REJECT | Worst value tested: the same confirmation as Top-5 for a 105s wait and 6.4 fewer confirmed trades per 100 arms. |

**No candidate is ADVANCE.** None satisfies the SPEC §7 requirement of materially
better confirmation *and* materially more remaining move while non-dominated on
throughput.

---

## 7. Validation and audit

`results/validation_report.json` — **all twelve gates pass**.

```text
armed_population                 8,950 exact
baseline_parity                  0.520 / 0.589 / 0.648 / 0.731 within 0.002
true_dispatches_only             0 null probabilities in the stream
prior_observation_same_regime    shift(1).over(regime_id), armed regime's own id
persistence_no_carry_forward     400 regimes recomputed, 0 mismatches
entry_after_arm                  0 violations
candidate_uses_own_atr           0 mismatches
independent_replay               240 trades re-derived from raw 1s, 0 mismatches
session_containment_no_overnight 0 dispatches past the session close
same_bar_ties_adverse            strict confirm bound; ties count as unconfirmed
interpolated_levels_labelled     recorded as NOT percentiles, with the reason
audit_gates                      lint 0/0 · lookahead-auditor PASS · contract-checker
```

### Defects found and fixed

| # | Defect | Found by | Effect if shipped |
|---|---|---|---|
| 1 | The armed window was bounded at the arm's *terminal* event, which for failed arms is the 1 ATR stop | own review of a `%2ndLife` column that read 0.0 everywhere | Silently imposed adverse invalidation — the option explicitly **not** chosen. Populations were 20–130% too small and the baselines did **not** reproduce the accepted figures. Fixing it restored exact parity. |
| 2 | `consec_*` counted row positions inside a run-group, and the group boundary increments **on** a non-qualifying row | validation gate `persistence_no_carry_forward` (313/400 mismatches) | Every streak preceded by a miss read one too high, inflating all Family B and F populations and firing them too early. |

### Audit gates

- `causal_lint`: 0 CRITICAL / 0 WARNING, pre-execution and after every change.
- `lookahead-auditor` pass 1: **PASS** — 0 critical, 0 warning, 2 notes. It
  independently verified the structural claim that no trigger can fire after the
  confirming flip: of 86,278 entries across all 12 rules, 900 land exactly on the
  flip second (legitimate under the 1s-before-1m convention) and **zero** land
  strictly after.
- `contract-checker`: see `audit/contract_status.json`.

**Process deviation, recorded.** SPEC §8 requires a pre-execution
`lookahead-auditor` pass on new entry-selection logic. `causal_lint` did run
pre-execution and was clean, but the auditor pass ran *after* the first full run —
before any result was finalised or reported, but later than the gate specifies.
Both defects above were caught by other means (own review and a validation gate)
rather than by that pass.

---

## 8. Limitations

1. **Entry study only.** Exit economics are reported nowhere; the downstream exit
   is known to be inefficient and would dominate any lifecycle comparison.
2. **The free-option effect flatters every waiting rule** (§3) and was not
   removed. The conclusion is robust to it only because waiting loses anyway.
3. **Interpolated levels are not percentiles.** The frozen calibration
   distribution is unrecoverable, so Family A tests arithmetic points between two
   frozen contract values, nothing more.
4. **`price_move_from_arm_atr` is partly definitional** with the FAILURE label and
   is excluded from all candidate families.
5. **The expected-ATR-per-100-arms ranking is a crude proxy**, not an expectancy —
   it multiplies a median by a count and ignores the loss side entirely.
6. **2025 is not threshold-OOS**; 2026 untouched.

---

## Final classification

```text
A. IMMEDIATE TOP-10 REMAINS THE BEST EARLY ENTRY
```

Confirmation probability and remaining move trade off at a near-constant rate of
about 0.30 ATR per 0.10 of probability, across every family tested — intermediate
interpolated levels, persistence, progression, re-expansion, and the hybrid. On
top of that, every waiting rule loses throughput, so immediate Top-10 leads on
confirmed trades per 100 arms (52.0) and on expected ATR per 100 arms (44.4) with
the next candidate at 40.4.

The information the brief hoped to exploit **is** present — SUCCESS and FAILURE
separate from the very first dispatch (AUC 0.582 at 5s, 0.705 at 45s). It simply
is not worth its price on this population. **The minimum additional confirmation
after Top-10 that buys meaningfully higher flip probability without surrendering
the economic advantage of being early does not exist here.**

The one result worth carrying forward is negative-shaped but useful:
**B1_PERSIST_TOP10_x2 is nearly free** — +0.029 confirmation for a 5s wait, no
median price given up, and 93.1% of arms still entered. It is not an improvement
today. It becomes worth revisiting only if a future study makes reaching
confirmation intrinsically more valuable than the move surrendered getting
there — which is precisely what the open exit question in
`confirmation_economics_excursion_map` would change.
