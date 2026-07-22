# Codex Multi-Agent Workflow

## Agent roster

| Agent | Model | Reasoning | Default access | Purpose |
|---|---|---|---|---|
| Main session | Current session model | Current session effort | User-selected permission mode | Plan, orchestrate, integrate, approve |
| `repo_scout` | `gemini-3.6-flash` | Low | Read-only | Repository discovery (Max 700w) |
| `contract_checker` | `gemini-3.5-pro` | Medium | Read-only | Specification compliance (Max 1000w) |
| `implementation_worker` | `gemini-3.5-pro` | Medium | Workspace write | Bounded implementation |
| `results_triager` | `gemini-3.6-flash` | Low | Guarded pytest only | Test-output reduction (Max 500w) |
| `lookahead_auditor` | `gemini-3.5-pro` | High | Read-only | Independent audit; parent persists report (Max 1500w, diff-first) |

---

## Risk Tiering & Gates

Before running subagents, classify the task into a risk tier:

* **Tier 1 (Diagnostic / Utility)**: Main session $\rightarrow$ run deterministic tests $\rightarrow$ local smoke check. No planning or audit agents.
* **Tier 2 (Normal Research Study)**: Main-session planning (`repo_scout` only if discovery is needed) $\rightarrow$ Main implementation $\rightarrow$ Staged runner (`scripts/run_bounded_study.py`) $\rightarrow$ Independent auditor (`lookahead_auditor`).
* **Tier 3 (Model Freeze / Deployment)**: `repo_scout` + `contract_checker` $\rightarrow$ Frozen task packet $\rightarrow$ Main-session implementation (or one bounded `implementation_worker`) $\rightarrow$ Staged runner $\rightarrow$ Independent auditor (`lookahead_auditor`).

---

## Token-Efficiency & Process Rules

1. **Deterministic Runner**: Use `scripts/run_bounded_study.py` to monitor runtime execution, timeouts, and stale log updates. Do not spend LLM tokens monitoring process state.
2. **Contextual Diff-First Audits**: `lookahead_auditor` reviews the contextual diff (`git diff -U20`) inside `audit_packet.json` first. Full source files are read only when structural dependencies or state flow are unresolved in the diff. It returns the complete report; the main session writes that response to the packet's requested audit path.
3. **Strict Word Caps**:
   * `repo_scout`: Max 700 words. Paths, symbols, and line numbers only.
   * `contract_checker`: Max 1,000 words. Compliance table and blocking verdict only.
   * `results_triager`: Max 500 words. Root cause test failures only.
   * `lookahead_auditor`: Max 1,500 words. Findings sorted by severity only.

---

## Standing Authorization for Named Mandatory Agent Gates

Named mandatory gates in this repository constitute standing user authorization for the main orchestrator to invoke the specifically named agent when that gate condition is reached.

This authorization applies only to:

- `repo_scout` where the selected risk tier requires it
- `contract_checker` where the selected risk tier requires it
- `results_triager` for exact approved test commands
- `lookahead_auditor` at mandatory causal or look-ahead audit gates

The invocation must remain limited to the scope of the named gate.

This standing authorization does not permit:

- discretionary agent use
- unnamed or general-purpose agents
- broad parallel fan-out
- nested delegation
- workers spawning subagents
- expanding the audit into implementation work
- code modifications by an audit-only agent

Session-level instructions prohibiting discretionary agent spawning remain in force. They do not prevent execution of a specifically named mandatory repository gate covered by this standing authorization.

If a mandatory gate and a session-level restriction appear to conflict, the orchestrator should:

1. invoke only the specifically named mandatory gate;
2. keep the scope limited to the gate’s defined responsibilities;
3. avoid all additional agent delegation; and
4. have the main session persist the read-only auditor's returned report and verdict in the study artifacts.

Passing criteria remain governed by the applicable frozen contract or SPEC. Standing authorization to invoke an auditor does not relax the audit acceptance standard. Do not mark the work finalized unless the audit satisfies the acceptance gate defined by the applicable frozen SPEC. At minimum, any CRITICAL finding blocks finalization. Any WARNING must either be remediated or explicitly adjudicated according to the SPEC; do not silently treat an unresolved WARNING as cleared.
