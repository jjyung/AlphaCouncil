# Test Patterns — Language & Framework Specific

## TypeScript / JavaScript — Vitest

### Basic structure
```typescript
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { userService } from './userService'

describe('userService', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('should create a user with valid data', async () => {
    const user = await userService.create({ name: 'Alice', email: 'alice@test.com' })
    expect(user).toMatchObject({ name: 'Alice' })
    expect(user.id).toBeDefined()
  })

  it('should reject duplicate emails', async () => {
    await userService.create({ name: 'Alice', email: 'dup@test.com' })
    await expect(userService.create({ name: 'Bob', email: 'dup@test.com' }))
      .rejects.toThrow('Email already exists')
  })

  it('should handle empty name', async () => {
    await expect(userService.create({ name: '', email: 'x@test.com' }))
      .rejects.toThrow('Name is required')
  })
})
```

### Mocking external dependencies
```typescript
import { describe, it, expect, vi } from 'vitest'
import { sendEmail } from './emailService'
import { emailClient } from './emailClient'

vi.mock('./emailClient')

it('should send welcome email', async () => {
  vi.mocked(emailClient.send).mockResolvedValue({ id: 'msg_123' })
  const result = await sendEmail('user@test.com', 'Welcome!')
  expect(result.success).toBe(true)
  expect(emailClient.send).toHaveBeenCalledWith(
    expect.objectContaining({ to: 'user@test.com' })
  )
})
```

### Parametrized tests
```typescript
it.each([
  { input: '', expected: false },
  { input: 'a@b', expected: true },
  { input: '@b.com', expected: false },
])('should validate email: $input', ({ input, expected }) => {
  expect(validateEmail(input)).toBe(expected)
})
```

---

## TypeScript / JavaScript — Jest

Same patterns as Vitest with these differences:
- `jest.mock()` instead of `vi.mock()`
- `jest.fn()` instead of `vi.fn()`
- No built-in `it.each` (use `test.each` or `it.each` from `@jest/globals`)

```typescript
jest.mock('./emailClient')
jest.spyOn(console, 'error').mockImplementation(() => {})
```

---

## Python — Pytest

### Basic structure
```python
import pytest
from user_service import create_user

def test_create_user_with_valid_data():
    user = create_user(name="Alice", email="alice@test.com")
    assert user.name == "Alice"
    assert user.id is not None

def test_reject_duplicate_emails():
    create_user(name="Alice", email="dup@test.com")
    with pytest.raises(ValueError, match="Email already exists"):
        create_user(name="Bob", email="dup@test.com")

def test_handle_empty_name():
    with pytest.raises(ValueError, match="Name is required"):
        create_user(name="", email="x@test.com")
```

### Fixtures
```python
@pytest.fixture
def db_session():
    session = create_test_session()
    yield session
    session.close()

def test_user_query(db_session):
    users = db_session.query(User).all()
    assert len(users) > 0
```

### Parametrize
```python
@pytest.mark.parametrize("email,expected", [
    ("", False),
    ("a@b", True),
    ("@b.com", False),
])
def test_email_validation(email, expected):
    assert validate_email(email) == expected
```

### Mocking with mocker (pytest-mock)
```python
def test_send_email(mocker):
    mock_client = mocker.patch("email_service.email_client.send")
    mock_client.return_value = {"id": "msg_123"}
    result = send_email("user@test.com", "Welcome!")
    assert result["success"] is True
```

---

## Python — unittest

```python
import unittest
from unittest.mock import patch
from user_service import create_user

class TestUserService(unittest.TestCase):
    def test_create_user_valid(self):
        user = create_user(name="Alice", email="alice@test.com")
        self.assertEqual(user.name, "Alice")
        self.assertIsNotNone(user.id)

    def test_reject_duplicate(self):
        create_user(name="Alice", email="dup@test.com")
        with self.assertRaises(ValueError):
            create_user(name="Bob", email="dup@test.com")

    @patch("email_service.email_client.send")
    def test_send_email(self, mock_send):
        mock_send.return_value = {"id": "msg_123"}
        result = send_email("user@test.com", "Welcome!")
        self.assertTrue(result["success"])

if __name__ == "__main__":
    unittest.main()
```

---

## Rust

```rust
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_create_user_with_valid_data() {
        let user = User::new("Alice", "alice@test.com").unwrap();
        assert_eq!(user.name, "Alice");
        assert!(user.id.is_some());
    }

    #[test]
    fn test_reject_duplicate_emails() {
        User::new("Alice", "dup@test.com").unwrap();
        let result = User::new("Bob", "dup@test.com");
        assert!(result.is_err());
        assert_eq!(result.unwrap_err().to_string(), "Email already exists");
    }

    #[test]
    fn test_handle_empty_name() {
        let result = User::new("", "x@test.com");
        assert!(result.is_err());
    }
}
```

---

## Go

```go
package user

import "testing"

func TestCreateUser_ValidData(t *testing.T) {
    user, err := NewUser("Alice", "alice@test.com")
    if err != nil {
        t.Fatalf("unexpected error: %v", err)
    }
    if user.Name != "Alice" {
        t.Errorf("got name %q, want %q", user.Name, "Alice")
    }
}

func TestCreateUser_DuplicateEmail(t *testing.T) {
    NewUser("Alice", "dup@test.com")
    _, err := NewUser("Bob", "dup@test.com")
    if err == nil {
        t.Fatal("expected error for duplicate email")
    }
}

// Table-driven test
func TestValidateEmail(t *testing.T) {
    tests := []struct {
        email    string
        expected bool
    }{
        {"", false},
        {"a@b", true},
        {"@b.com", false},
    }
    for _, tc := range tests {
        got := ValidateEmail(tc.email)
        if got != tc.expected {
            t.Errorf("ValidateEmail(%q) = %v, want %v", tc.email, got, tc.expected)
        }
    }
}
```

---

## Test Structure Decision Tree

```
What kind of code?
├── Pure function / utility
│   └── Unit test — test input/output pairs, edge cases
├── Service / business logic
│   └── Unit test — mock external dependencies, test logic
├── API endpoint
│   └── Integration test — hit the endpoint, check response
├── Database query
│   └── Integration test — use test DB or in-memory DB
├── CLI command
│   └── Integration test — invoke CLI, check output
└── UI component
    └── Component test — render, interact, assert
```
