# Contract pre-execution audit — pass 01

**Verdict:** INCOMPLETE  
**Blocking findings:** 1  
**Warnings:** 0  
**Prior findings adjudicated:** N/A (first pass)

## C-01 — Literal Deliverables Manifest is absent

`SPEC.md` lists artifact categories but does not prescribe their exact paths,
required columns/contents, hash and seal bindings, validation-grid/domain
expectations, or the promotion and terminal-decision requirements. The contract
cannot yet independently verify a materialized study run.

**Required remediation:** Add a literal Deliverables Manifest to `SPEC.md`.
It must bind every required artifact to exact paths and required contents,
require the 18 directional and 9 pooled reporting rows, specify the source and
result seals, make promotion fail closed, and state that only directional rows
may determine the terminal label.

The audit stopped after this contract-completeness finding by its mandatory
pre-execution stop rule; no downstream findings were assessed in this pass.
