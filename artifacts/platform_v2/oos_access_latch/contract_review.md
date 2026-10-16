# Contract review: OOS access latch (chore/oos_access_latch, 7f13e4d9 vs 8404c72e)

## SPEC items

1. **First opening recorded before any held-out read** — PASS. `lifecycle_v2.py:2131-2135` calls
   `oos_access.open_access` (atomic `O_CREAT|O_EXCL` write, `oos_access.py:74-87,118-134`) before
   `_collect_period("oos")` at line 2135. Test
   `test_oos_access_latch.py:166-179` asserts every held-out bar read happened after the record
   existed.
2. **Record binds identity** — PASS. `_oos_identity` (`lifecycle_v2.py:1419-1435`) composes
   study_id, plan_sha256, analysis_spec_sha256, execution_composite_sha256, composite_seal_hash,
   authorization_sha256, year_roles, dataset, and the TRAIN-freeze binding
   (`_FREEZE_BINDING`, line 1416, includes `model_hashes`/`model_canonical_sha256`). No separate
   claim/pre-registration artifact exists outside the plan, so `plan["analysis"]` is the only
   candidate and it is hashed.
3. **Conflicting-identity refusal** — PASS. `oos_access.check_identity`
   (`oos_access.py:104-115`) is invoked from `seal` (1862-863... line 862-863), `freeze`
   (2106-2107), `oos` (2131-2132 via `open_access`), and `analyze`/`_oos_analysis_gate`
   (1505-1522, 2216). `test_post_oos_amendment_is_refused_at_every_stage...` (line 198-214)
   exercises seal/freeze/analyze/oos.
4. **freeze/oos/analyze/resume cannot bypass** — PASS with one caveat. All four are latched.
   However the legacy (no declared `analysis:`) OOS-scoring branch in `analyze()`
   (`lifecycle_v2.py:2228-2284`) reads partitions and scores models directly, calling only the
   old `assert_oos_open` (TRAIN-freeze check, no identity/evidence latch). It is reached only
   after `_oos_analysis_gate(..., reads_held_out=True)` already ran at line 2216 when
   `chronology.dev` is non-empty — so in practice it is gated. **GAP (WARNING):** if `dev` is
   empty the gate at 2216 is skipped entirely and this branch runs ungated; it is currently safe
   only because `oos()` refuses to produce partitions without `dev` years (2116-2123), i.e. safety
   depends on that separate invariant holding, not on this branch itself ever checking the latch.
5. **Second OOS collection cannot silently replace evidence** — PASS.
   `record_completion`/`verify_evidence` (`oos_access.py:137-161`) compare partition byte-hashes;
   `test_replacing_or_deleting_held_out_evidence_is_refused_without_recollection` (line 255-274)
   covers delete-manifest, delete-partition, and re-collect-with-consistent-rehash.
6. **Original record/trace preserved** — PASS. Write-once via `O_CREAT|O_EXCL`; deleting the
   record is refused as `OOS_ACCESS_RECORD_MISSING` rather than silently reopening
   (`open_access`, line 124-127; test at 277-284). Deleting partitions does not reopen while the
   completion record survives (same test, line 282-284).
7. **Deterministic, typed refusals** — PASS. `OOSAccessRefused.code` values
   (`OOS_IDENTITY_CONFLICT`, `OOS_ACCESS_RECORD_MISSING`, `OOS_ACCESS_RECORD_CORRUPT`,
   `OOS_EVIDENCE_ALTERED`, `OOS_COLLECTION_INCOMPLETE`) written to
   `_work/controller/oos_access_refusal.json` by `write_refusal` (line 164-169).
8. **Amendment possible before first access, hard-refused after, no reopen** — PASS. Before
   `open_access` succeeds, nothing is latched so a reseal/refreeze is normal. After, every
   identity-changing path is refused and there is no code path that deletes/rewrites the record
   under program control (only manual file deletion, which is itself refused — item 6).
9. **G2 independent OOS partition verification** — PASS. `_reconcile_oos`
   (`lifecycle_v2.py:1457-1503`) re-derives year/authorization membership from
   `identity["year_roles"]` (not the manifest's own claim), recomputes parquet hashes, checks
   plan/seal/authorization lineage recorded in the manifest, checks the declared interval against
   `_expected_partition`, runs `_partition_population_findings`, and checks candidate/observation
   key parity and duplicates. The dataset check is intentionally skipped only when
   `read_digest is None and self.opts.bar_source is not None` (line 1478) — synthetic/injected bar
   sources only, not a general fail-open.
10. **TRAIN reconcile unchanged** — PASS (code-level: `reconcile()` at line 1524-1557 does not
    call any `oos_access` function and reuses the same `_partition_population_findings` helper
    that OOS reconcile now also uses; no new keys were added to the TRAIN `reconcile.json` payload
    construction visible in the diff). **NOT VERIFIED**: byte-stability of `reconcile.json`
    output was not confirmed by re-running; no before/after fixture diff was inspected in this
    pass.

## Severity-ranked findings

- **WARNING** — Item 4 caveat above: the ungated legacy OOS-scoring branch
  (`lifecycle_v2.py:2228-2284`) has no direct latch call; its safety is an emergent property of
  the `dev`-years-empty guard elsewhere, not a property of that branch. Smallest remediation: add
  an explicit `self._oos_latch("analyze", lambda oa: oa.check_identity(...))` at the top of that
  branch so it doesn't depend on an invariant maintained elsewhere.
- **NOTE** — Item 10 confirmed only by code reading, not by an executed before/after diff of
  `reconcile.json` on a dev-years-empty study.

## Blocking verdict: no BLOCKED items found; one WARNING (item 4) and one NOT VERIFIED (item 10) outstanding.

## Addendum (post-broad-gate fix, same chore)

- `seal()`, `freeze()` and `analyze()` now compare identities through `_oos_check`. It reads the access record first, so a corrupt record is still refused by `read_record`. It derives the current identity only when a record exists.
- With no record, `check_identity` already returned `None`, so the comparison is unchanged. The only behavioural difference is that a plan lacking `instruments` no longer raises `KeyError` before any record exists.
- `oos()` still derives the identity unconditionally before opening.
- Held-out analysis without a record is still refused with `OOS_ACCESS_RECORD_MISSING`.
- Spec items 1–10 are unaffected.
