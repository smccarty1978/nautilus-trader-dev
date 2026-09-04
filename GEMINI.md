# GEMINI.md — Gemini CLI entry point

Read `WORKFLOW.md` first, then `docs/QUICKSTART.md`. Roles and harness mechanics: `docs/AI_AGENTS.md`.
Shared agent core: `AGENTS.md`. System description: `docs/RESEARCH_WORKFLOW.md`.

Operating rules for Gemini in this repository:

1. Every platform operation goes through `python scripts/research.py ...` or
   `python scripts/run_governed_study.py ...`; never reimplement orchestration in prompts or scripts.
2. New research is a Platform V2 study: `research study new <id>`, a declarative `study.yaml`, zero
   study Python. Historical studies are references, never templates. The old runtime is legacy only.
3. A missing primitive is a typed `CapabilityGap` from `research study compile`; resolve it with
   `research cap search/describe`, or propose a reusable capability (`research cap propose`).
4. One writing agent per git worktree (`research study new` creates it); never work on `main`.
   **FOR A NEW RESEARCH PROJECT:** read `WORKFLOW.md` → §M *Concurrent research projects*, then use `python scripts/research.py study new <id>` and work only in the generated worktree. Never start a study by editing `main`.
   **BEFORE WRITING IN A STUDY WORKTREE:** launch through `scripts\launch_antigravity.cmd -Study <id>` (it sets `NT_RESEARCH_AGENT=antigravity` and a fresh per-session `NT_RESEARCH_AGENT_SESSION`), then run `python scripts/research.py ws whoami --expect antigravity` and continue ONLY on `STATUS: OK` -- `WRITER_IDENTITY_AMBIGUOUS` / `WRITER_IDENTITY_MISMATCH` means stop, do not write. Then `ws claim <id> --as antigravity` (or `study new <id> --as antigravity`); a live lease of another agent is refused (`STUDY_WORKTREE_OWNED_BY_ANOTHER_AGENT`). Read-only roles skip the claim.
5. Audits: hand `_work/controller/audit_packet_{causal,contract}.json` to the auditor roles
   (`.agents/agents_staging/lookahead-auditor.md`, `contract-checker.md`), then
   `research audit ingest --type causal|contract --report <md>`.
6. Long stages run detached and resume with the same command; do not poll by hand.
7. Return compact cards (STATUS, state, blocker_code, artifact), not narratives.
