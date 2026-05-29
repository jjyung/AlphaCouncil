# Orchestration Patterns

## Decomposition Strategies

### By Layer (frontend/backend/infra)
```
Frontend (executor)  ─┐
Backend (executor)    ├─→ Synthesis → Review
Infra (executor)      ┘
```

### By Phase (plan/implement/verify)
```
Planner ─→ Executor ─→ Verifier
(sequential pipeline)
```

### By Concern (feature A / feature B)
```
Planner (feature A) ─→ Executor (A) ─→ Verifier (A)  ─┐
                                                         ├─→ Synthesis
Planner (feature B) ─→ Executor (B) ─→ Verifier (B)  ─┘
```

## Agent Dispatch Reference

| Subtask Type | Agent | Max Parallel |
|-------------|-------|-------------|
| Architecture/planning | spec-writer | 3 |
| Implementation | executor | 5 |
| Code review | code-reviewer | 3 |
| Test generation | test-engineer | 3 |
| Verification | verifier | 1 |

## Handoff Format

All handoffs in `.handoffs/orchestrate/` follow this structure:

```markdown
## Subtask: <name>
**Agent:** <type>
**Status:** completed / failed / skipped

### Input
- <what was given to the agent>

### Output
- <what the agent produced>

### Files Changed
- path/to/file.ts (modified)
- path/to/new.test.ts (added)

### Notes
- <deviations, risks, pending items>
```
