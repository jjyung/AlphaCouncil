---
name: test-gen
description: |
  Analyze source code and generate meaningful tests — unit, integration, and E2E.
  Detects project test framework, conventions, and existing test patterns automatically.
  Use PROACTIVELY when asked to "add tests", "write tests", "test this", "cover with tests", "increase coverage".
  Triggers on: "test", "coverage", "unit test", "integration test", "spec"
---

# Test Generation

Analyze source code, detect test framework, and generate meaningful tests following project conventions.

## When to Use

- Adding tests for new code
- Backfilling tests for existing code
- Converting manual test plans to automated tests
- Increasing test coverage in specific modules

## Workflow

```
Code Input → Framework Detection → Pattern Analysis → Test Generation → Verification
```

### Step 1: Framework Detection

Determine the test framework and runner:

#### Node.js (check `package.json` devDependencies)
| Detected | Framework | Runner |
|----------|-----------|--------|
| vitest | Vitest | `vitest` |
| jest | Jest | `jest` |
| mocha + chai | Mocha | `mocha` |
| ava | Ava | `ava` |

#### Python (check `pyproject.toml`, `requirements*.txt`, or installed tools)
| Detected | Framework | Runner |
|----------|-----------|--------|
| pytest | Pytest | `pytest` |
| unittest | unittest | `python -m unittest` |

#### Rust (check `Cargo.toml`)
| Detected | Framework | Runner |
|----------|-----------|--------|
| cargo | built-in test | `cargo test` |

#### Go
| Detected | Framework | Runner |
|----------|-----------|--------|
| testing | built-in test | `go test` |

If unclear, check for `test/` or `__tests__` directories, `*.test.*` or `*.spec.*` files, and examine one existing test to infer conventions.

See `references/framework-detection.md` for detailed detection logic.

### Step 2: Pattern Analysis

Read 2-3 existing tests in the project to understand:

- **File naming:** `*.test.ts`, `*.spec.ts`, `test_*.py`?
- **Directory structure:** co-located or `tests/` directory?
- **Setup patterns:** `beforeEach`/`setup_method`? Fixtures? Factories?
- **Mocking style:** jest.mock, unittest.mock, monkeypatch, dependency injection?
- **Assertion style:** `expect().toBe()`, `assertEqual`, `assert!`?
- **Naming conventions:** `describe/it`, `def test_`, `func Test`?

### Step 3: Test Generation

For each unit/module under test:

#### Unit Tests
- Happy path — expected inputs produce expected outputs
- Edge cases — empty, null, boundary values
- Error paths — invalid input, failure modes, exceptions
- State transitions — if applicable
- Focus on public API, not implementation details

#### Integration Tests (when applicable)
- Module interactions
- Database/file system round-trips
- API endpoint behavior

#### Test Structure Template
```typescript
describe('Module/Function', () => {
  beforeEach(() => {
    // setup
  })

  it('should handle happy path', () => {
    // arrange
    // act
    // assert
  })

  it('should handle edge case: <description>', () => {
    // ...
  })

  it('should handle error: <description>', () => {
    // ...
  })
})
```

### Step 4: Verification

Run the generated tests to confirm they pass:

```bash
# Framework detected in step 1
npm test -- --run         # vitest
npx jest                  # jest
pytest -v                 # pytest
python -m unittest -v     # unittest
cargo test                # Rust
go test ./...             # Go
```

## Test Quality Guidelines

| Quality | Criteria |
|---------|----------|
| ✅ Great | Tests behavior, covers edge cases, deterministic, fast |
| ⚠️ Adequate | Tests happy path only, some duplication |
| ❌ Poor | Tests implementation, brittle, flaky, no assertions |

## Anti-Patterns

- ❌ Testing implementation details (private methods, internal state)
- ❌ Snapshot testing without review (giant snapshots)
- ❌ Mocking everything (tests lose meaning)
- ❌ Flaky tests (time, random, network dependencies)
- ❌ No assertions (tests that can't fail)
- ❌ Copy-paste test patterns without adapting to context

## Related Skills

- `dev-flow` — Verify phase runs generated tests
- `pr-review` — Reviews test quality as part of code review
