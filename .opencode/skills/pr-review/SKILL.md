---
name: pr-review
description: |
  Systematic code review for pull requests. Analyzes diff across 5 dimensions:
  correctness, security, quality, testing, and style.
  Use PROACTIVELY when reviewing PRs, analyzing code changes, or asked to "review", "audit", "check".
  Triggers on: "review this PR", "code review", "review changes", "audit", "check my code"
---

# PR Review

Systematic pull request review across 5 dimensions: Correctness, Security, Code Quality, Testing, and Style.

## When to Use

- Reviewing a PR before merge
- Analyzing a diff for potential issues
- Preparing review comments for a colleague
- Auditing code changes for security or quality

## Review Workflow

```
Diff Input → 5-Dimension Analysis → Issue Classification → Review Report
```

### Step 1: Input Preparation

Determine what to review:

- **Branch diff:** `git diff main...HEAD` or `git diff <base>...<feature>`
- **Staged changes:** `git diff --cached`
- **Specific files:** `git diff <base>...<feature> -- <paths>`
- **GitHub PR:** Use `gh` CLI to fetch PR details and diff

Collect context:
- Read commit messages for intent
- Check linked issues if available
- Note which files are changed (added/modified/deleted)

### Step 2: 5-Dimension Analysis

Each dimension has specific checks:

| Dimension | Focus | Key Questions |
|-----------|-------|---------------|
| **Correctness** | Logic, edge cases, contracts | Does the code do what it intends? Are edge cases handled? Are there off-by-one, race conditions, or null dereferences? |
| **Security** | Vulnerabilities, hardening | Are inputs validated? Are there injection risks? Secrets exposed? Authz checks in place? |
| **Code Quality** | Maintainability, patterns | Does it follow project conventions? Is it readable? Over-engineering? Dead code? Tech debt introduced? |
| **Testing** | Coverage, test quality | Are new changes tested? Are tests meaningful? Edge cases covered? Test maintainability? |
| **Style** | Formatting, naming | Consistent with project style? Meaningful names? No unnecessary formatting changes mixed in? |

See `references/review-dimensions.md` for detailed per-dimension checklists.

### Step 3: Issue Classification

Each finding is classified by severity:

- **🔴 BLOCKING** — Must fix before merge (bug, security vulnerability, data loss)
- **🟡 WARNING** — Should fix (code smell, missing edge case, weak test)
- **🔵 SUGGESTION** — Nice to have (style preference, optional refactor)
- **⚪ PRAISE** — Positive feedback (good design, clever solution, thorough tests)

### Step 4: Output Report

Write review report to stdout with this structure:

```markdown
## PR Review: <brief title>

### Overview
<summary of changes, files changed (+/- stats), general assessment>

### Findings

#### 🔴 <issue title>
- **File:** `path/to/file.ts:42`
- **Severity:** blocking
- **Description:** <what and why>
- **Suggestion:** <how to fix>

... (more findings) ...

### Summary
- 🔴 Blocking: <count>
- 🟡 Warnings: <count>
- 🔵 Suggestions: <count>
- ⚪ Praise: <count>
- **Verdict:** Approve / Changes Requested / Needs Discussion
```

## Guiding Principles

1. **Be specific** — reference exact line numbers and file paths
2. **Explain why** — don't just say "this is wrong", explain the impact
3. **Offer solutions** — suggest concrete fixes, not just problems
4. **Prioritize** — focus on correctness and security over style
5. **Be constructive** — include praise for good code

## Anti-Patterns

- ❌ Nitpicking style while ignoring logic bugs
- ❌ Reviewing without reading full context (imports, types, etc.)
- ❌ Demanding changes without understanding tradeoffs
- ❌ Only negative feedback — missing good patterns
- ❌ Superficial review (LGTM without reading diff)

## Related Skills

- `dev-flow` — For implementing the fixes identified in review
