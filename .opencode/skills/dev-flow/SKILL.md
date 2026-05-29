---
name: dev-flow
description: |
  Contract-first development workflow: contract → code → verify → fix (loop).
  Drives development from persistent specifications, enabling parallel frontend/backend work.
  Use PROACTIVELY when implementing features, fixing bugs, refactoring, or making code changes.
  Triggers on: "implement", "feature", "fix bug", "refactor", "add", "change", "build"
---

# Development Flow

Contract-first development workflow. Writes persistent specifications before coding, so frontend and backend can work in parallel from the same contract.

## When to Use

- Implementing a new feature
- Fixing a bug
- Refactoring existing code
- Making any non-trivial code change

## Phase Overview

```
[Phase 0: Architecture — ADR (optional)]
        │
        v
Phase 1: Contract ──→ docs/specs/<feature>/ (persistent, committed)
        │               Frontend & Backend can start in parallel
        v
Phase 2: Code
        │
        v
Phase 3: Verify ──→ against acceptance criteria from Phase 1
        │
        v
     [Fix loop] → back to Phase 2 (max 3 retries)
```

## Phase 0: Architecture (Optional)

**When:** An architectural decision needs recording (tech choice, structural change, cross-team impact).

**Output:** `docs/adr/NNNN-title.md` — Architecture Decision Record

**Agent:** architect

See `skills/adr/SKILL.md` for ADR workflow and template.

→ Then proceed to Phase 1 with the ADR as architectural context.

## Phase 1: Contract

**Goal:** Produce a persistent specification that records consensus and enables parallel implementation.

**Output (persistent, committed to repo):**
```
docs/specs/<feature>/
├── README.md       # Requirements, ACs, API contract, data model
├── api-spec.yaml   # OpenAPI spec (if applicable)
└── data-model.md   # Schema definitions (if applicable)
```

### Steps
1. **Analyze** — Read relevant files, existing ADRs, understand context
2. **Check ADRs** — Are there existing ADRs that constrain this feature? Reference them.
3. **Specify** — Write the contract document:
   - Functional requirements (RFC 2119: MUST/SHOULD/MAY)
   - Acceptance criteria (GIVEN/WHEN/THEN)
   - API contract (endpoints, request/response schemas)
   - Data model (entities, fields, types, constraints)
   - Out of scope (explicit exclusions)
4. **Review** — Present contract to user for approval

### Contract Document Template
```markdown
# Feature: <title>

## Requirements
FR-1: System MUST <behavior>

## Acceptance Criteria
- GIVEN <context> WHEN <action> THEN <result>

## API Contract
POST /api/xxx
Request: { field: type }
Response: { field: type }

## Data Model
| Entity | Field | Type | Constraints |

## Out of Scope
- <explicit exclusions>

## Architecture
References: ADR-001, ADR-003
```

### Agent: spec-writer
- Tools: Read, Grep, Glob, Bash, Write, Edit
- Writes to `docs/specs/<feature>/`, NOT to `.handoffs/`

See `references/contract-phase.md` for detailed contract workflow.

## Phase 2: Code

**Goal:** Implement the contract. Frontend and backend can proceed independently.

### Steps
1. **Read contract** — Load `docs/specs/<feature>/README.md` and referenced ADRs
2. **Implement** — Write code following the contract and project conventions
3. **Self-review** — Verify code matches the contract before moving on

### Key Principle
The contract in `docs/specs/` is the source of truth. If implementation reveals
issues with the contract, update the contract first, then code.

### Handoff (`.handoffs/dev-flow/code.md`)
Lightweight — references contract rather than duplicating it:
- Files changed
- Deviations from contract (with rationale)
- Pending items

### Agent: executor
- Tools: Read, Write, Edit, Bash, Grep, Glob
- Full read/write access

See `references/code-phase.md` for detailed coding workflow.

## Phase 3: Verify

**Goal:** Verify implementation against the acceptance criteria from Phase 1.

### Steps
1. **Lint** — Run linter
2. **Typecheck** — Run type checker if applicable
3. **Test** — Run tests, verify acceptance criteria are met
4. **Build** — Verify project builds

If any step fails → enter fix loop (back to Phase 2).

### Handoff (`.handoffs/dev-flow/verify.md`)
- Lint/typecheck/test/build results
- Acceptance criteria pass/fail from contract
- Final verdict: pass / needs fix

### Agent: verifier
- Tools: Read, Grep, Glob, Bash
- Read-only + execute tests

See `references/verify-phase.md` for detailed verification workflow.

## Fix Loop

If verification fails:
1. Read contract and verification output to understand failures
2. Fix issues (Phase 2)
3. Re-verify (Phase 3)
4. Max 3 iterations

## Quick Start

**Simple change (≤3 files, well-understood):**
```
Phase 0: Skip (no ADR needed)
Phase 1: Quick contract → Phase 2: Code → Phase 3: Verify
```

**Complex change (new feature, architectural impact):**
```
Phase 0: ADR first → Phase 1: Full contract with user review
→ Phase 2: Code (frontend + backend parallel) → Phase 3: Verify
```

## Artifact Summary

| Artifact | Location | Persistent | Purpose |
|----------|----------|------------|---------|
| ADR | `docs/adr/NNNN-title.md` | ✅ Committed | Architecture decisions |
| Contract | `docs/specs/<feature>/` | ✅ Committed | Requirements, ACs, API contract |
| Code handoff | `.handoffs/dev-flow/code.md` | ❌ Temporary | Implementation notes |
| Verify report | `.handoffs/dev-flow/verify.md` | ❌ Temporary | Verification results |

## Related Skills

- `adr` — Architecture Decision Records (Phase 0)
- `test-gen` — Generate tests from acceptance criteria
- `pr-review` — Review code against the contract
