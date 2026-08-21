# Contract pre-execution audit — pass 02

**Verdict:** BLOCKED  
**Blocking findings:** 3  
**Warnings:** 0  
**Prior findings adjudicated:** C-01 FIXED

## C-01 — FIXED

The SPEC now contains a literal Deliverables Manifest with exact paths and
required artifact content.

## C-02 — Phase-zero prerequisite is not enforced

The collector can start without validating a persisted, current phase-zero
manifest. Add a fail-closed authorization check and tests for absent, stale,
and altered manifests.

## C-03 — Phase-zero source authentication is incomplete

Bind `study.yaml` to the manifest and replace self-asserted future-data claims
with an allowlisted collection-input contract plus explicit forbidden-year and
F3-lineage refusal checks.

## C-04 — Result-bound validation, seal, and promotion gate are absent

Implement exact-grid validation, result seal verification, evidence-derived
terminal classification, and a fail-closed promotion gate with adversarial
tests before execution.
