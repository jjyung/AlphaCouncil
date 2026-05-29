---
name: adr
description: |
  Capture architecture decisions as lightweight ADR documents.
  Use when making design choices that affect project structure, technology selection,
  or architectural direction. Also use during code review when spotting implicit decisions.
  Triggers on: "adr", "architecture decision", "design decision", "why did we", "decision log"
---

# Architecture Decision Records

Capture, manage, and maintain architecture decisions using Michael Nygard's lightweight ADR format.

## When to Use

- Choosing a technology, framework, or library
- Defining project structure or module boundaries
- Making API design decisions (REST vs GraphQL, versioning strategy)
- Selecting database, cache, or infrastructure
- Changing existing architecture decisions
- During code review — if a PR introduces an architectural change without an ADR, flag it

## ADR Lifecycle

```
Proposed → Accepted → Deprecated → Superseded by ADR-NNN
                      ↘ Reinstated
```

| Status | Meaning |
|--------|---------|
| Proposed | Decision suggested, under review |
| Accepted | Decision adopted, implementation follows |
| Deprecated | No longer recommended, existing usage OK |
| Superseded | Replaced by another ADR (link to it) |
| Reinstated | Previously deprecated decision revived |

## Workflow

### Step 1: Detect Decision Moment

An ADR is needed when:
- A decision has long-term impact on the codebase
- Multiple alternatives exist with meaningful tradeoffs
- The decision affects how other teams/modules will work
- You find yourself explaining "why we chose X" more than once

### Step 2: Write ADR

Use the template from `references/templates.md`. Save to `docs/adr/NNNN-title.md`.

Number sequentially: check existing files in `docs/adr/` and increment.

### Step 3: Review

Share with team for feedback. ADRs benefit from:
- Architecture review
- Cross-team input (if decision affects others)
- At least one other person reading it

### Step 4: Update Status

As decisions evolve:
- Mark `Accepted` when implementation starts
- Mark `Deprecated` when better alternatives emerge
- Mark `Superseded by ADR-NNN` when replaced
- Link related ADRs in both directions

## ADR Location

All ADRs live in `docs/adr/` with an index:

```
docs/adr/
├── README.md              # Index of all ADRs
├── 001-use-postgres.md
├── 002-api-versioning.md
└── 003-monorepo-structure.md
```

## Keeping ADRs Alive

- **PR review hook:** If a PR changes architecture without a corresponding ADR, flag it
- **Regular index updates:** When superseding, update the old ADR's status and link
- **Not everything needs an ADR:** Bug fixes, routine feature additions, style choices → skip
- **But when in doubt, write one:** A 5-minute ADR saves hours of future confusion

## Related Skills

- `dev-flow` — Contract phase should reference ADRs for architectural context
- `pr-review` — Code review checks for missing ADRs on architectural changes
