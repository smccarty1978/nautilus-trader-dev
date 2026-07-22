# Antigravity Agent Workflow

This workspace supports delegating tasks to specialized subagents to optimize context usage and control API costs. 

When running in **Antigravity**, these subagents run natively using Google Gemini models, which offer massive context windows and high execution speeds.

---

## Agent Roster and Gemini Model Mapping

| Subagent Name | Claude Model (Original) | Gemini Equivalent Model | Antigravity Model Flag | Purpose |
|---|---|---|---|---|
| `repo-scout` | Haiku | Gemini 3.6 Flash / Flash Lite | `flash` / `flash_lite` | Locate code and trace execution paths |
| `contract-checker` | Sonnet | Gemini Pro / 3.6 Flash | `pro` / `flash` | Verify specifications and invariant compliance |
| `results-triager` | Haiku | Gemini 3.6 Flash / Flash Lite | `flash` / `flash_lite` | Run test commands and triage results |
| `lookahead-auditor` | Sonnet | Gemini Pro | `pro` | Deep causal audit for look-ahead bias |


---

## Invoking Subagents in Antigravity

Antigravity handles subagent registration and calling natively via its model orchestration loop.

### How to Invoke
Simply request the flagship model to run the task on a subagent. For example:
> *"Invoke lookahead-auditor on strategies/short_rth_entry_surface_backfill/"*

The flagship model will use the `invoke_subagent` tool with the corresponding prompt template and target model flag.

### Coordination Rules
* **Parallel Checks**: Multiple read-only subagents (`repo-scout`, `contract-checker`) can run in parallel safely.
* **Context Preservation**: Subagents return condensed Markdown summaries rather than raw code dumps to keep the main conversation context clean.
* **Audit Enforcement**: The `lookahead-auditor` must be run on any modified strategy or data-loading script before declaring a study complete.

---

## Lean Workflow, Token Budgets, and Standing Authorization

These rules are harness-independent and are maintained in one place. See:

* `AGENTS.md` § Subagent Routing & Lean Workflow — risk tiers, per-agent output
  word caps, diff-first auditing, deterministic run bounding via
  `scripts/run_bounded_study.py`.
* `AGENTS.md` § Standing Authorization for Named Mandatory Agent Gates — which
  gates may be invoked without asking, and the limits on that authorization.

Antigravity-specific note: the Gemini model mapping above determines which model
backs each agent, but the output caps and gate scoping are identical to the
Claude and Codex harnesses.

