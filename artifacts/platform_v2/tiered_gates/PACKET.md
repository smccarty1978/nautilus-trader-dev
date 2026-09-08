# PACKET — TIERED MERGE GATES

    role:        frontier architect. This is a genuine design question:
                 what test surface does each class of change actually require?
    branch:      chore/tiered_gates
    deliverable: a proven design first. Implementation only if the proof holds.
    result_card: python scripts/research.py study result --packet <this> --status <s> --report <md>

---

## 0. THE PROBLEM, STATED BY THE OWNER

> A 75-minute compile would be a master reconfiguration. Adding a new moving
> average to the feature registry, or a new module to the collection scope, is
> not that.

Today they cost the same. Every capability addition routes
`MISSING_CAPABILITY` → `CAPABILITY_GAP_HANDOFF` → chore worktree → **broad
`test_delta`, ~75 min** → merge → study resumes.

Since every genuinely novel study needs a feature, **the toll falls on research
pace, not on platform development.** That is the wrong place for it, and it is
the single largest friction remaining in this system.

**Target state:** add features in two or three terminals, alongside concurrent
studies, see the diffs, and merge them together under one lightweight check.

---

## 1. WHAT YOU ARE DESIGNING

**Not** a general-purpose file-to-test mapping. That was tried (W2.2b) and
escalated correctly — safe exemptions could not be proven in the abstract.

**Instead:** a small number of **change classes**, each with a derived test
surface, each provable against real history. A narrower question with a
defensible answer.

### 1.1 Classify

Propose the classes. A starting hypothesis, not a specification:

- **ADDITIVE_CAPABILITY** — a new registry entry, a new feature or tracker
  module, a new provider. Adds files; modifies no existing capability code, no
  compiler, no host, no lifecycle, no governance module.
- **MODIFIED_CAPABILITY** — changes an existing feature, tracker or provider
  that studies already bind.
- **CORE_SURFACE** — compiler, host, lifecycle, controller, closure, manifest,
  partitioning, grammar. Broad run, unchanged.

**Classification must be mechanical and conservative.** Derived from the diff,
not declared by the session. **Anything unclassifiable is CORE_SURFACE.** Fail
toward the expensive gate, never away from it.

### 1.2 Derive the surface per class

For ADDITIVE_CAPABILITY the surface is bounded and nameable: registry generation
and validation (`cap generate --check`), compiler binding for the new id, the
new module's own tests, closure and manifest tests, `lint_host`. Minutes.

Derive it, do not assert it. The question to answer for each class: **what could
a change of this class break, and which tests cover that?** If a plausible
breakage has no covering test, say so — that is a finding, not a reason to widen
the class back to broad.

### 1.3 Batched merge

The owner wants several features from several terminals merged together.

Design a merge queue: N branches of the same or compatible class combine, the
union of their test surfaces runs once, and they merge together. A CORE_SURFACE
branch in the batch promotes the whole batch to broad.

Address: how the writer lease and the chore surface claim interact with a batch;
what happens when one branch in the batch fails; whether the batch is tested as
a merged whole or per-branch. State the answers, do not leave them implied.

---

## 2. THE PROOF — THIS IS THE PACKET

A design that is merely plausible is worthless here. **Replay the repository's
real merge history through the proposed tiering and report what the cheap gate
would have missed.**

Cover at minimum every chore merge since Platform V2. For each: its class under
the proposal, what the broad run found, and whether the class's surface would
have found it.

**The named case that must be answered explicitly:**

- **F3, Wave 1 encoding corruption.** The one real branch-introduced defect the
  broad gate has caught. Wave 1 touched the compiler and the manifest, so it
  classifies **CORE_SURFACE** and still runs broad. Confirm that. If the
  proposed classification would have put Wave 1 in a cheap tier, the design is
  wrong and must change.

- **The three W0-era failures** (missing model artifact, provider-binding
  assertion, encoding) — class each, and state whether the cheap surface catches
  it.

**Verdict required:** for every historical defect the broad gate caught, either
the proposed tier catches it too, or the design is narrowed until it does.
**One miss invalidates the class.**

---

## 3. CONSTRAINTS

- The broad run stays as the CORE_SURFACE gate and as the fallback. This is
  about routing, not deletion.
- Fail toward broad. Ambiguity, an unmapped path, a mixed diff → broad.
- Classification is derived from the diff mechanically. A session must not be
  able to declare its own change cheap.
- Do not build on the W2.2b selector — sparse mappings, diff-against-HEAD, and a
  fallback that discovers only `scripts/tests`. Replacing it is in scope.
- Studies merge on their own branches with `--no-ff` and are unaffected. This
  changes chore merges only.
- Corrected classifier semantics from `e2e58fbf` stand: no loosening of
  environmental classification, changed-known-failure acceptance, return-code
  enforcement, scope-before-node ordering, or baseline matching.

---

## 4. DELIVERABLE

1. The change classes, with mechanical classification rules.
2. The test surface per class, with the derivation.
3. The batched-merge design, with lease and failure semantics answered.
4. **The historical replay table** — every chore merge, its class, what broad
   found, whether the tier catches it.
5. Measured or estimated duration per class, against the recorded 74m41s broad
   baseline.
6. A verdict: does the proof hold, and where is it weakest.

**Stop at the design.** Implement only if §2 shows no miss. If the replay finds
a case the tiering misses and no narrowing fixes it, report that — a proven
"this cannot be done safely" is a real result and better than a gate that leaks.

---

## 5. ESCALATE

- Any historical defect the cheap tier would have missed, where narrowing the
  class does not fix it without effectively restoring broad.
- A change class that cannot be derived mechanically from the diff.
- Batched merge requiring a weakening of the lease or the chore surface claim.
- A plausible ADDITIVE_CAPABILITY breakage with no covering test — report it;
  do not widen the class to hide it.

---

## 6. CONTEXT

Wave 2 is merging: sampled shadow default (`f7e2606b`) and five classifier fixes
(`e2e58fbf`). W2.2b, W2.3 and W2.4 escalated unfinished and stay unfinished —
they optimize the cost of *building* the platform. **This packet optimizes the
cost of using it, which is why it goes first.**
