# Post-Bar3 Survivor Opportunity After Quick-Failure Rejection

OOS 2025-26 survivors (alive at Bar 3, n_post≥4): **30,730** regimes. Model B (features thru Bar 3, leak-corrected k=Nbar) QuickFailure head trained on IS 2021-24 survivors, scored OOS. Reject the worst-X% by P(QuickFail); enter survivors at **Bar 4 open** (causal — features end Bar 3, entry Bar 4).

> [!CAUTION]
> Barrier-touch probabilities and bracket net$ are 1m-bar resolution, which **OVERSTATES** barrier edge vs 1s/tick (memory: bar-mode overstates fade/touch strategies $15-25K/yr; BE/path checkpoints inflate $14K). Treat as a DIRECTIONAL SCREEN. Net$ also split by year below — a single pooled positive is not a monetizability verdict.

Costs: $20/pt, $5 RT, 0.5t entry slip, 1.0t exit slip. PT = limit fill at pt_px (no favorable slip); SL = market at sl_px − slip; same-bar PT+SL → SL first (conservative).

> [!NOTE]
> The model is walk-forward (trained IS-only), but the "reject worst X%" cut is an **OOS-rank-relative** percentile — inherent to a reject-worst-X% framing (you need the population to take a fraction of it). It is NOT an IS-derived pQ threshold, so "reject worst 20%" is not a portable deployment rule; a deployment gate would fix θ from the IS score distribution.

## Step 2a — Composition & remaining MFE/MAE (from Bar 4 entry, ATR-norm)

| Reject worst | n | Launch% | QuickFail% | Chop% | MFE avg/med/p75 | MAE avg/med/p75 |
| --- | --- | --- | --- | --- | --- | --- |
| baseline (none) | 30,730 | 4.0% | 8.3% | 87.7% | 2.26/1.25/2.87 | 1.18/0.99/1.56 |
| worst 10% | 27,657 | 4.4% | 6.3% | 89.3% | 2.32/1.30/2.93 | 1.22/1.03/1.60 |
| worst 20% | 24,584 | 4.8% | 4.7% | 90.5% | 2.37/1.34/2.99 | 1.25/1.07/1.65 |
| worst 30% | 21,511 | 5.2% | 3.5% | 91.2% | 2.42/1.39/3.05 | 1.29/1.11/1.69 |
| worst 40% | 18,438 | 5.7% | 2.6% | 91.8% | 2.47/1.43/3.13 | 1.32/1.15/1.74 |
| worst 50% | 15,365 | 6.0% | 1.9% | 92.1% | 2.52/1.48/3.18 | 1.37/1.20/1.80 |

## Step 2b — Barrier-touch probabilities P(PT before SL) [1m-bar, overstated]

| Reject worst | +0.5/−0.5 | +1.0/−0.5 | +1.5/−0.75 | +2.0/−1.0 |
| --- | --- | --- | --- | --- |
| baseline (none) | 45.3% | 32.2% | 31.1% | 28.6% |
| worst 10% | 45.4% | 32.3% | 31.4% | 29.0% |
| worst 20% | 45.4% | 32.3% | 31.5% | 29.3% |
| worst 30% | 45.2% | 32.1% | 31.6% | 29.6% |
| worst 40% | 45.1% | 32.1% | 31.9% | 29.8% |
| worst 50% | 44.8% | 31.9% | 31.9% | 30.1% |

## Step 2c — Net $/trade (pooled OOS) [1m-bar, overstated]

| Reject worst | B 0.5/0.5 | B 1.0/0.5 | B 1.5/0.75 | B 2.0/1.0 | Hold-to-flip | Bar10 exit |
| --- | --- | --- | --- | --- | --- | --- |
| baseline (none) | $-14.82 | $-10.85 | $-11.67 | $-10.96 | $-15.59 | $-12.79 |
| worst 10% | $-14.73 | $-10.53 | $-11.09 | $-10.46 | $-14.94 | $-12.34 |
| worst 20% | $-14.73 | $-10.49 | $-11.22 | $-10.90 | $-14.22 | $-13.41 |
| worst 30% | $-15.27 | $-11.22 | $-11.11 | $-10.74 | $-15.29 | $-13.66 |
| worst 40% | $-15.35 | $-10.88 | $-10.44 | $-10.57 | $-14.54 | $-13.84 |
| worst 50% | $-15.51 | $-11.22 | $-10.57 | $-10.76 | $-16.38 | $-14.74 |

## Step 2d — Year split (net $/trade), best bracket + hold-to-flip + bar10

A policy is monetizable only if net-positive in BOTH 2025 and 2026 (per methodology).

| Reject worst | B 1.5/0.75 25 | 26 | Hold-flip 25 | 26 | Bar10 25 | 26 |
| --- | --- | --- | --- | --- | --- | --- |
| baseline (none) | $-9.20 | $-19.14 | $-9.29 | $-34.69 | $-9.66 | $-22.25 |
| worst 10% | $-8.43 | $-19.11 | $-8.06 | $-35.68 | $-8.81 | $-23.01 |
| worst 20% | $-8.17 | $-20.42 | $-6.49 | $-37.50 | $-9.33 | $-25.67 |
| worst 30% | $-7.77 | $-21.15 | $-6.10 | $-42.94 | $-9.65 | $-25.71 |
| worst 40% | $-7.05 | $-20.59 | $-5.08 | $-42.97 | $-9.67 | $-26.34 |
| worst 50% | $-7.41 | $-19.94 | $-7.64 | $-42.36 | $-10.83 | $-26.36 |

## Verdict — is the surviving population monetizable?

> [!WARNING]
> **NO — rejecting predicted QuickFailures does NOT create a monetizable Bar-4 entry universe.** No retained population × exit policy is net-positive in BOTH 2025 and 2026, even at 1m-bar resolution (which OVERSTATES barrier edge). Composition improves (QuickFail% falls, MFE/MAE tilt up) but the surviving population's forward opportunity does not clear costs. The rejection power is real but **not monetizable** as a Bar-4 entry gate — consistent with it being an exit/management signal, not an entry edge (rejection_power.md D6).

Baseline (no filter) best policy: **B 1.0/0.5** at $-10.85/tr pooled OOS.