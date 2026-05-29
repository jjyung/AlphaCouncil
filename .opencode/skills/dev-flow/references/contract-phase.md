# Contract Phase — Detailed Workflow

The Contract phase replaces the old Plan phase. It produces **persistent, committed** specification documents instead of temporary handoffs.

## Entry Conditions

- User request received (feature, bug, refactor)
- Dev-flow skill activated
- Optional: ADRs exist in `docs/adr/` that constrain this feature

## Analysis Process

### 1. Understand the Request
- Read the user's request carefully
- Ask clarifying questions if ambiguous (one at a time, with rationale)
- Identify the core goal, not just the surface request

### 2. Check Existing ADRs
- Read `docs/adr/README.md` for index
- Identify relevant ADRs that constrain or inform this feature
- Reference ADR numbers in the contract document

### 3. Explore the Codebase
- Read relevant files to understand current state
- Use Grep/Glob to find related code
- Identify patterns and conventions

### 4. Specify the Contract

Write to `docs/specs/<feature>/README.md`:

```markdown
# Feature: <title>

## Requirements
FR-1: System MUST <behavior>
FR-2: System SHOULD <behavior>
FR-3: System MAY <behavior>

## Acceptance Criteria
- GIVEN <context> WHEN <action> THEN <expected result>

## API Contract
- POST /api/xxx
  Request: { field: type }
  Response: { field: type }

## Data Model
| Entity | Field | Type | Constraints |

## Out of Scope
- <explicit exclusions>

## Architecture References
- ADR-001: <title>
- ADR-003: <title>
```

### 5. User Review
- Present contract to user
- Ask: "Does this contract look correct? Ready to implement?"
- Wait for approval before proceeding to Code phase

## Key Differences from Old Plan Phase

| Aspect | Old Plan (handoff) | New Contract (persistent) |
|--------|-------------------|--------------------------|
| Location | `.handoffs/dev-flow/plan.md` | `docs/specs/<feature>/README.md` |
| Persistence | Temporary (gitignored) | Committed to repo |
| Audience | Next phase only | All current and future developers |
| Granularity | Implementation steps | Requirements + ACs + API |
| Parallel work | Not supported | Frontend/backend can work in parallel |
| ADR integration | None | Explicit reference |

## Anti-Patterns

- ❌ Writing contracts in `.handoffs/` instead of `docs/specs/`
- ❌ Over-specifying implementation details (that's for Code phase)
- ❌ Ignoring existing ADRs
- ❌ Writing contracts in a different doc per code phase (update the single contract)
- ❌ Skipping user review for complex features
