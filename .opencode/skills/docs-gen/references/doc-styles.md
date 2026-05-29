# Doc Style Reference — Language-Specific Conventions

## TypeScript / JavaScript — JSDoc

```typescript
/**
 * Creates a new user in the system.
 *
 * @param name - The user's display name (2-50 chars)
 * @param email - The user's email address (must be unique)
 * @returns The created user object with generated ID
 * @throws {ValidationError} If name or email are invalid
 * @throws {ConflictError} If email already exists
 */
async function createUser(name: string, email: string): Promise<User> {
```

### JSDoc Tags
| Tag | When to Use |
|-----|-------------|
| `@param name - desc` | Every function parameter |
| `@returns` | Non-void functions |
| `@throws` | Documented exceptions |
| `@template T` | Generic type parameters |
| `@deprecated reason` | Deprecated APIs, with migration path |
| `@example` | Usage example (preferred over prose) |
| `@see` | Cross-reference to related code |

---

## TypeScript / JavaScript — TSDoc

```typescript
/**
 * Creates a new user in the system.
 *
 * @param name - The user's display name (2-50 chars)
 * @param email - The user's email address (must be unique)
 * @returns The created user
 *
 * @example
 * ```ts
 * const user = await createUser('Alice', 'alice@test.com')
 * ```
 */
```

TSDoc is a superset of JSDoc with better TypeScript integration. Prefer TSDoc in TypeScript projects.

---

## Python — Google Style Docstrings

```python
def create_user(name: str, email: str) -> User:
    """Create a new user in the system.

    Args:
        name: The user's display name (2-50 chars).
        email: The user's email address (must be unique).

    Returns:
        The created user object with generated ID.

    Raises:
        ValidationError: If name or email are invalid.
        ConflictError: If email already exists.
    """
```

---

## Python — NumPy Style Docstrings

```python
def create_user(name: str, email: str) -> User:
    """Create a new user in the system.

    Parameters
    ----------
    name : str
        The user's display name (2-50 chars).
    email : str
        The user's email address (must be unique).

    Returns
    -------
    User
        The created user object with generated ID.

    Raises
    ------
    ValidationError
        If name or email are invalid.
    """
```

---

## Python — reST Style (Sphinx)

```python
def create_user(name: str, email: str) -> User:
    """Create a new user in the system.

    :param name: The user's display name (2-50 chars).
    :param email: The user's email address (must be unique).
    :returns: The created user object with generated ID.
    :raises ValidationError: If name or email are invalid.
    :raises ConflictError: If email already exists.
    """
```

---

## Rust — rustdoc

```rust
/// Creates a new user in the system.
///
/// # Arguments
/// * `name` - The user's display name (2-50 chars)
/// * `email` - The user's email address (must be unique)
///
/// # Returns
/// The created `User` object
///
/// # Errors
/// Returns `ValidationError` if name or email are invalid.
/// Returns `ConflictError` if email already exists.
///
/// # Example
/// ```rust
/// let user = create_user("Alice", "alice@test.com")?;
/// ```
```

---

## Go — Godoc

```go
// CreateUser creates a new user in the system.
// It validates the input and checks for duplicate emails.
//
// Parameters:
//   - name: the user's display name (2-50 chars)
//   - email: the user's email address (must be unique)
//
// Returns the created user, or an error if validation fails
// or the email already exists.
func CreateUser(name string, email string) (*User, error) {
```

### Godoc Conventions
- First sentence is the summary (used in `go doc` listing)
- Use full sentences with proper punctuation
- Document function behavior, not implementation
- `//` only, no `/* */`

---

## ADR Template

```markdown
# ADR-001: Use PostgreSQL for Primary Database

**Date:** 2026-05-25
**Status:** Accepted

## Context
We need a primary database for storing user data.
The system needs strong consistency and complex queries.

## Decision
Use PostgreSQL 16 as the primary database.

## Consequences
- ✅ Strong consistency with ACID transactions
- ✅ Rich query capabilities (JSON, full-text search)
- ⚠️ Requires managed database service (increased cost)
- ⚠️ Schema migrations need careful planning

## Alternatives Considered
- MySQL: Similar capabilities but weaker JSON support
- MongoDB: Better horizontal scaling but eventual consistency
```

ADR numbering: sequential (`ADR-001`, `ADR-002`). Location: `docs/adr/`.

---

## CHANGELOG Template

```markdown
# Changelog

## [1.2.0] - 2026-05-25

### Added
- User creation API endpoint (POST /api/users)
- Email validation utility

### Changed
- Upgraded Express from 4.18 to 4.21
- Rate limiting now applied to all endpoints

### Fixed
- Memory leak in WebSocket connections
- Edge case in date parsing for timezone offsets

### Security
- Updated bcrypt dependency to patch CVE-2026-XXXX
```

Follow [Keep a Changelog](https://keepachangelog.com) convention unless project uses custom format.
