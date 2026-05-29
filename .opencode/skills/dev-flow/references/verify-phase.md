# Verify Phase — Detailed Workflow

## Entry Conditions

- Code handoff exists at `.handoffs/dev-flow/code.md`
- Code changes have been implemented

## Process

Run verification steps in order. Stop at first failure and report.

### 1. Detect Project Type
- Look for `package.json` → Node.js project
- Look for `Cargo.toml` → Rust project
- Look for `pyproject.toml` / `requirements.txt` → Python project
- Look for `go.mod` → Go project
- Use `ls` on project root to detect

### 2. Run Lint
```
# Node
npm run lint        # or yarn lint, pnpm lint

# Rust
cargo clippy

# Python
ruff check .        # or flake8, pylint

# Go
go vet ./...
```

**Pass condition:** Exit code 0, no errors.
**Fail:** Record lint errors in handoff.

### 3. Run Typecheck (if applicable)
```
# TypeScript
npx tsc --noEmit    # or npm run typecheck

# Rust
cargo check

# Python (pyright/mypy)
pyright .
mypy .
```

**Pass condition:** Exit code 0, no type errors.

### 4. Run Tests
```
# Find test command from package.json scripts or common conventions

# Node
npm test            # or npm run test

# Rust
cargo test

# Python
pytest              # or python -m pytest

# Go
go test ./...
```

**Pass condition:** All tests pass.
**Fail:** Record which tests failed and their output.

### 5. Run Build (if applicable)
```
# Node
npm run build       # or npm run build:prod

# Rust
cargo build

# Go
go build ./...
```

**Pass condition:** Exit code 0, build succeeds.

### 6. Output Handoff

Write to `.handoffs/dev-flow/verify.md`:

```markdown
# Verification: <title>

## Results

| Check | Status | Details |
|-------|--------|---------|
| Lint | ✅ Pass / ❌ Fail | <details> |
| Typecheck | ✅ Pass / ❌ Fail / ⏭ Skip | <details> |
| Tests | ✅ Pass / ❌ Fail | <details> |
| Build | ✅ Pass / ❌ Fail / ⏭ Skip | <details> |

## Overall Verdict

**PASS** — All checks passed. Changes are ready.

or

**NEEDS FIX** — <summary of failures, max 3 bullet points>

## Fix Loop Info
- Attempt: <1/3, 2/3, 3/3>
- Previous failures: <list>
```

## Fix Loop

If verification fails:
1. Read `verify.md` to understand failures
2. Return to Code phase to fix
3. Re-verify after fixes
4. Max 3 fix attempts total

## Anti-Patterns

- ❌ Skipping verification for "trivial" changes
- ❌ Not running the actual test command (guessing)
- ❌ Ignoring test failures that seem unrelated
- ❌ Exceeding max fix loops without asking user
- ❌ Not detecting the correct project type
