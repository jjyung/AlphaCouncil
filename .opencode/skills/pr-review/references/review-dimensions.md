# Review Dimensions — Detailed Checklists

## 1. Correctness

### Logic
- [ ] Does the code correctly implement the intended behavior?
- [ ] Are all branches of conditionals covered?
- [ ] Are loop boundaries correct (off-by-one)?
- [ ] Return values handled properly?
- [ ] Error paths don't silently swallow exceptions?

### Data Flow
- [ ] Data transformations preserve invariants?
- [ ] No unintended mutation of inputs?
- [ ] Null/undefined/optional values handled?
- [ ] Type assertions safe?

### Concurrency
- [ ] Shared state properly synchronized?
- [ ] No deadlock or race condition risk?
- [ ] Async operations have proper error handling?
- [ ] Resource cleanup guaranteed (finally, dispose, defer)?

### Edge Cases
- [ ] Empty collections handled?
- [ ] Boundary values (max int, empty string, zero)?
- [ ] Network/filesystem failures?
- [ ] Unexpected input formats?

---

## 2. Security

### Input Validation
- [ ] All user inputs validated (type, range, format)?
- [ ] Injection prevention (SQL, command, XSS, path traversal)?
- [ ] File uploads validated (type, size, content)?
- [ ] URLs/redirects validated against open redirect?

### Authentication & Authorization
- [ ] Auth checks on all protected endpoints?
- [ ] Principle of least privilege followed?
- [ ] No auth bypass paths?
- [ ] Session management secure?

### Data Protection
- [ ] No secrets in code, logs, or error messages?
- [ ] Sensitive data encrypted at rest and in transit?
- [ ] PII handled according to regulations?
- [ ] Temporary files cleaned up?

### Dependencies
- [ ] New dependencies necessary? Any known vulnerabilities?
- [ ] Versions pinned?

See `references/security-checklist.md` for language-specific security patterns.

---

## 3. Code Quality

### Design
- [ ] Follows single responsibility principle?
- [ ] Good separation of concerns?
- [ ] Appropriate abstraction level (not over/under-engineered)?
- [ ] Follows project's architectural patterns?

### Readability
- [ ] Meaningful names (functions, variables, classes)?
- [ ] Functions do one thing (not too long)?
- [ ] Comments explain "why", not "what"?
- [ ] No commented-out code?

### Maintainability
- [ ] No duplicated code (DRY)?
- [ ] Dependencies explicit (not hidden globals)?
- [ ] Config/hardcoded values in right place?
- [ ] Backward compatibility considered?

### Performance
- [ ] No obvious performance issues (N+1 queries, unnecessary allocations)?
- [ ] Resource cleanup (connections, file handles, memory)?

---

## 4. Testing

### Coverage
- [ ] New code has corresponding tests?
- [ ] Happy path tested?
- [ ] Error/edge case paths tested?
- [ ] Integration points tested?

### Test Quality
- [ ] Tests deterministic (no flakiness)?
- [ ] Tests independent (no shared mutable state)?
- [ ] Test names describe behavior, not implementation?
- [ ] No test logic in production code?

### Test Maintenance
- [ ] Tests not too brittle (testing behavior, not implementation)?
- [ ] No excessive mocking?
- [ ] Test data clear and maintainable?

---

## 5. Style

### Consistency
- [ ] Follows project's lint/format config?
- [ ] Naming conventions consistent (camelCase, PascalCase, etc.)?
- [ ] Import/style order consistent?

### Diff Hygiene
- [ ] No formatting-only changes mixed with logic changes?
- [ ] No unrelated files changed?
- [ ] Commit messages descriptive?
