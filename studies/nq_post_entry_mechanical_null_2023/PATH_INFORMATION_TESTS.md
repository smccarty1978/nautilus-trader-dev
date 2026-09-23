# Path information at exact anchors — primary variables, replication, power

## Method

**Statistic** (frozen before computing):
- For each anchor and variable, tercile cutpoints are fixed on the **discovery** block.
- Δ = mean(outcome − event null) in the top tercile minus the bottom tercile.
- The null depends on the outcome:
  - fixed race (A): N2;
  - terminal race (B): N3;
  - giveback (G): N3's P(giveback | +2A).

**Uncertainty:** session-cluster bootstrap. A trade's events at several anchors stay inside its session cluster.

**Speed** is tested stratified by RTH segment. The sensitivity run drops anchors in the last hour before the
close; it changed no conclusion.

**Pass rule** (frozen):
- **Discovery:** |Δ| ≥ 5pp with a CI excluding 0, at two or more adjacent anchors.
- **Replication:** same sign, at least half the discovery size, and replication MDE ≤ 0.10.

## Primary variables: Δ against the null, pooled development

Values are in percentage points; bold marks a result meaningful in discovery. The four primary variables are:
- **time to anchor** — seconds from entry to the first touch;
- **pullback from MFE** — how far the anchor bar closed below its running high, in A;
- **MAE so far** — worst adverse excursion before the anchor, in A;
- **ret30** — return over the last 30 s into the anchor, in A.

| outcome | variable | 0.25 | 0.50 | 0.75 | 1.00 | 1.25 | 1.50 | 2.00 |
|---|---|---|---|---|---|---|---|---|
| A fixed race − N2 | time to anchor (stratified) | −0.1 | +1.7 | −1.2 | +2.0 | +3.2 | +1.2 | |
| A | pullback from MFE | +0.6 | −3.5 | 0.0 | −0.1 | −0.3 | +2.7 | |
| A | MAE so far | +0.6 | +1.2 | +1.7 | +1.8 | +2.2 | −1.6 | |
| A | ret30 | −4.8 | −0.3 | −1.0 | −0.6 | −0.4 | −1.1 | |
| B terminal race − N3 | time to anchor (stratified) | −3.7 | −2.5 | −2.4 | −2.2 | −2.2 | −0.8 | |
| B | pullback from MFE | +1.5 | −0.9 | +1.8 | +0.7 | +0.6 | +1.9 | |
| B | MAE so far | +0.2 | −1.1 | −1.1 | −1.8 | −2.1 | −1.7 | |
| B | ret30 | −3.6 | +2.5 | −0.5 | +2.0 | +1.7 | −1.5 | |
| G giveback − N3 | time to anchor (stratified) | | | | −2.2 | | **−4.5** | **−5.9** |
| G | pullback from MFE | | | | −2.4 | | **+5.3** | −0.5 |
| G | MAE so far | | | | +2.6 | | +2.2 | +1.1 |
| G | ret30 | | | | +3.2 | | **+7.7** | **+9.3** |

**Discovery passes** (two adjacent meaningful anchors), all on giveback at +1.5A and +2A:

| variable | discovery Δ (+1.5A, +2.0A) | replication Δ | verdict under the frozen rule |
|---|---|---|---|
| ret30 | +9.1, +10.7 | +2.8, +4.8 | fails: below half magnitude, and replication MDE 0.12 |
| time to anchor (stratified) | −5.6, −6.8 | −1.2, −2.8 | fails: below half magnitude, and replication MDE 0.12 |

`pullback_from_mfe` was meaningful at +1.5A only, so it had no adjacent anchor.

**Robustness of the strongest candidate** (ret30 → giveback against N3, at +2A):
- same direction in every RTH segment: +9.8, +9.1, +10.1pp;
- same direction for both sides: short +12.0pp, long +6.2pp;
- same direction in 5 of 5 supported states, from +2.2 to +23.4pp.

It is consistent in development, but the replication shrank it.

## What the raw (null-free) numbers looked like

These are the effects a naive reading would call "path information" (discovery block):
- **Terminal race:** raw ret30 gives +4.4 to +8.8pp, and raw speed gives −3.8 to −5.7pp at every anchor.
- **Giveback:** raw ret30 gives +6.8 / +12.9 / +15.6pp and raw speed −5.1 / −10.0 / −15.2pp at +1A / +1.5A /
  +2A.
- **Fixed race:** raw effects are ≤ 5pp, and only one is meaningful, at a single anchor.

The engine null (N3) removes roughly half to two-thirds of the terminal and giveback effects. The fixed race
never had them.

## Secondary variables (reported; cannot decide the verdict)

- **Against N2, fixed race:** none meaningful.
- **Against N3, terminal race:** accel at 0.5A and ret15 at 1.0A are meaningful, isolated anchors.
- **Against N3, giveback:**
  - rv60 (recent realised volatility) gives +8.7 / +9.1 / +10.6pp at +1A / +1.5A / +2A;
  - ret15 and ret60 are meaningful at the top anchors.

  The volatility-and-recent-return family keeps reappearing for giveback. That is the same "sharp spike"
  phenomenon as ret30.

## Power

Minimum detectable tercile Δ at 80% power (1.3 design effect):

| | discovery | replication | pooled |
|---|---|---|---|
| fixed race | 0.065–0.080 | 0.113–0.140 | 0.056–0.069 |
| terminal race | 0.062–0.073 | 0.108–0.128 | 0.054–0.064 |
| giveback | 0.072 | 0.121 | 0.062 |

Replication could not confirm a true 5–10pp effect with adequate power. A null there is "not shown", not
"shown absent". The fixed-race *level* is a different matter: it is constrained to about ±1.7pp.

Machine-readable: `artifacts/PATH_EFFECTS.*` (every outcome × variable × anchor × block × variant, with CIs),
`artifacts/POWER.*`, `artifacts/ROBUSTNESS.*` and `artifacts/ANALYSIS_RESULTS.json` (`all_evaluations`).
