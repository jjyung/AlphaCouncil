# ADR Templates

## Standard (Michael Nygard)

```markdown
# ADR-NNN: <short title>

**Date:** YYYY-MM-DD
**Status:** Proposed | Accepted | Deprecated | Superseded by ADR-NNN

## Context
<What is the issue motivating this decision?
 What forces are at play (technical, political, social)?
 Mention specific constraints, requirements, or tradeoffs.>

## Decision
<What is the change being proposed or made?
 Be specific — technology name, version, pattern.>

## Consequences
<What becomes easier or harder?
 List positive and negative outcomes.>

## Alternatives
<What other options were considered, and why were they rejected?
 Keep brief — 1-2 sentences per alternative.>
```

---

## MADR (Markdown ADR) — More Structured

```markdown
# ADR-NNN: <short title>

**Date:** YYYY-MM-DD
**Status:** Proposed

## Context and Problem Statement
<Describe the problem in 2-3 sentences.>

## Decision Drivers
- <driver 1>
- <driver 2>

## Considered Options
- Option A: <summary>
- Option B: <summary>
- Option C: <summary>

## Decision Outcome
Chosen option: <option>, because <justification>.

## Pros and Cons of Options

### Option A
- Good: <point>
- Bad: <point>

### Option B
- Good: <point>
- Bad: <point>
```

---

## Lightweight (for quick decisions, 5 min write)

```markdown
# ADR-NNN: <short title>

We chose **<decision>** over **<alternatives>** because
<primary reason>.

## Context
<1-2 sentences>

## Consequences
<bullet points>
```

---

## ADR Index (`docs/adr/README.md`)

```markdown
# Architecture Decision Records

| ADR | Title | Status | Date |
|-----|-------|--------|------|
| 001 | Use PostgreSQL for primary DB | Accepted | 2026-05-01 |
| 002 | API versioning via URL prefix | Proposed | 2026-05-15 |
```

When superseding, update the old ADR's status and add the link:

```markdown
## Status
Superseded by [ADR-005: New Caching Strategy](005-new-caching.md)
```
