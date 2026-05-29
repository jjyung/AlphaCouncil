# Code Phase — Detailed Workflow

## Entry Conditions

- Plan handoff exists at `.handoffs/dev-flow/plan.md`
- Plan has been reviewed and approved by user

## Process

### 1. Read the Plan
- Load `.handoffs/dev-flow/plan.md`
- Understand the implementation steps
- Note which files to modify and how

### 2. Setup
- For each file to be modified, read the current content first
- Understand the existing code structure

### 3. Implement Step by Step
- Follow the implementation steps from the plan
- After each step, verify the change is coherent
- If you discover something the plan missed, note the deviation

### 4. Follow Project Conventions
- Look at neighboring files for style/pattern reference
- Match existing code style (naming, imports, formatting)
- Follow the project's established patterns

### 5. Self-Review
Before moving to Verify phase:
- [ ] All planned changes implemented
- [ ] No dead code or commented-out code
- [ ] Error handling in place
- [ ] Edge cases considered
- [ ] No secrets or debug logs committed
- [ ] Changes follow project conventions

### 6. Output Handoff

Write to `.handoffs/dev-flow/code.md`:

```markdown
# Code Changes: <title>

## Summary
<overview of what was changed>

## Files Changed
| File | Action | Description |
|------|--------|-------------|
| src/foo.ts | Modified | Added feature logic |

## Deviations from Plan
- <any changes from the original plan, with rationale>

## Pending Items
- <things that need attention before completion>

## Self-Review Checklist
- [ ] All changes tested locally
- [ ] No regressions introduced
- [ ] Code follows project conventions
```

## Anti-Patterns

- ❌ Modifying files without reading them first
- ❌ Copy-pasting code without understanding
- ❌ Leaving debug code, console.log, TODO comments
- ❌ Ignoring error handling
- ❌ Making unrelated changes
- ❌ Skipping the plan handoff read
