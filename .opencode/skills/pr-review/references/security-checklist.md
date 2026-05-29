# Security Checklist — Language-Specific Patterns

## TypeScript / JavaScript

### Injection
```
// ❌ DANGEROUS
eval(userInput)
innerHTML = userInput
new Function(userInput)
require(`./${userInput}`)
child_process.exec(`command ${userInput}`)

// ✅ SAFE
textContent = userInput
child_process.execFile('command', [userInput])
DOMPurify.sanitize(userInput)
```

### SQL
```
// ❌ DANGEROUS
`SELECT * FROM users WHERE id = ${userId}`

// ✅ SAFE
db.query('SELECT * FROM users WHERE id = ?', [userId])
```

### Auth
- [ ] JWT verified with proper library (jsonwebtoken.verify)
- [ ] No hardcoded tokens or API keys
- [ ] Rate limiting on auth endpoints

---

## Python

### Injection
```python
# ❌ DANGEROUS
os.system(f"command {user_input}")
subprocess.run(f"command {user_input}", shell=True)
eval(user_input)

# ✅ SAFE
subprocess.run(["command", user_input])
```

### SQL
```python
# ❌ DANGEROUS
cursor.execute(f"SELECT * FROM users WHERE id = {user_id}")

# ✅ SAFE
cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
```

### Pickle
```python
# ❌ DANGEROUS (arbitrary code execution)
data = pickle.loads(untrusted_input)

# ✅ SAFE
data = json.loads(untrusted_input)
```

---

## Go

### Injection
```go
// ❌ DANGEROUS
cmd := exec.Command("bash", "-c", userInput)

// ✅ SAFE
cmd := exec.Command("command", userInput)
```

### SQL
```go
// ❌ DANGEROUS
db.Query(fmt.Sprintf("SELECT * FROM users WHERE id = %s", userID))

// ✅ SAFE
db.Query("SELECT * FROM users WHERE id = ?", userID)
```

---

## Rust

### Unsafe
```rust
// ❌ DANGEROUS - verify necessity and safety invariants
unsafe { ... }

// ✅ SAFE - prefer safe abstractions
safe_api()
```

### Injection
```rust
// ❌ DANGEROUS
Command::new("sh").arg("-c").arg(user_input)

// ✅ SAFE
Command::new("command").arg(user_input)
```

---

## General Security Rules

1. **Never trust input** — validate type, range, format, length
2. **Least privilege** — minimal permissions, minimal scope
3. **Defense in depth** — don't rely on a single security measure
4. **Fail securely** — errors should default to denied/closed
5. **No secrets in code** — use env vars, secret managers, or vaults
6. **Log securely** — no secrets in logs, no user data in error messages
7. **Dependencies** — check for known CVEs, prefer maintained libraries
8. **Cryptography** — use established libraries, don't roll your own
