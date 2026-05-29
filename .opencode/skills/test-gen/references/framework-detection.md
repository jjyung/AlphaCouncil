# Framework Detection — Detailed Reference

## Detection Order

1. Check project config files
2. Check for test directories (`test/`, `__tests__/`, `spec/`)
3. Check for existing test files (`*.test.*`, `*.spec.*`, `test_*`)
4. Read one existing test to confirm conventions

---

## Node.js / TypeScript

### Detection by config file

Look in `package.json` `devDependencies` and `scripts`:

| Pattern | Framework | Test Command |
|---------|-----------|-------------|
| `"vitest"` in devDeps | Vitest | `npm run test` or `npx vitest` |
| `"jest"` in devDeps | Jest | `npx jest` |
| `"mocha"` + `"chai"` in devDeps | Mocha + Chai | `npx mocha` |
| `"ava"` in devDeps | AVA | `npx ava` |
| `"test": "vitest"` in scripts | Vitest | `npm test` |
| `"test": "jest"` in scripts | Jest | `npm test` |

### Vitest specifics
- Config: `vitest.config.ts` or `vite.config.ts` with `test` block
- File patterns: `*.test.ts`, `*.spec.ts`, `**/__tests__/*.ts`
- Globals: `describe`, `it`, `expect`, `beforeEach` available without import
- `vi.mock()` for mocking
- Run: `npx vitest run` (single run) or `npx vitest` (watch)

### Jest specifics
- Config: `jest.config.ts` or `jest.config.js`
- File patterns: `*.test.ts`, `*.spec.ts`, `**/__tests__/*.ts`
- `jest.mock()` for mocking
- Run: `npx jest`

### File naming conventions

| Convention | Example | Framework |
|------------|---------|-----------|
| Co-located `.test.ts` | `user.ts` → `user.test.ts` | Vitest, Jest |
| Co-located `.spec.ts` | `user.ts` → `user.spec.ts` | Vitest, Jest |
| `__tests__/` dir | `__tests__/user.test.ts` | Jest |
| `test/` dir mirrored | `test/user.test.ts` | Mocha |

---

## Python

### Detection by config file

| File | Framework |
|------|-----------|
| `pyproject.toml` with `[tool.pytest]` | pytest |
| `pytest.ini` | pytest |
| `setup.cfg` with `[tool:pytest]` | pytest |

### Pytest specifics
- File patterns: `test_*.py`, `*_test.py`
- Function patterns: `def test_<name>()`
- Class patterns: `class Test<Name>` with `def test_<name>()`
- Fixtures: `@pytest.fixture`, conftest.py
- Parametrize: `@pytest.mark.parametrize`
- Mock: `unittest.mock` or `pytest-mock` (`mocker` fixture)
- Run: `pytest -v`, `pytest -v test_file.py`

### Unittest specifics
- File patterns: `test_*.py`
- Class: `class Test<Name>(unittest.TestCase)`
- Setup: `setUp()` / `setUpClass()`
- Assert: `self.assertEqual()`, `self.assertTrue()`, etc.
- Mock: `@unittest.mock.patch()`
- Run: `python -m unittest -v`

### File naming conventions
| Convention | Example |
|------------|---------|
| `tests/` dir | `tests/test_user.py` |
| Co-located | `user.py` → `test_user.py` (next to it) |

---

## Rust

### Built-in test framework
- Attribute: `#[test]` on functions
- File location: tests live in `tests/` (integration) or inside source files (unit)
- Unit tests: `#[cfg(test)] mod tests { ... }` at bottom of source file
- Integration tests: `tests/<name>.rs` files
- Assert: `assert!()`, `assert_eq!()`, `assert_ne!()`
- Run: `cargo test`, `cargo test <test_name>`

---

## Go

### Built-in test framework
- File patterns: `*_test.go`
- Function: `func Test<Name>(t *testing.T)`
- Table-driven tests common: `tests := []struct{ ... }`
- Assert: `t.Errorf()`, `t.Fatal()`, or `require`/`assert` from testify
- Run: `go test ./...`, `go test -v ./...`
