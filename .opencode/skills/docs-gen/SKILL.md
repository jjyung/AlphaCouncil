---
name: docs-gen
description: |
  Generate and update project documentation — README, API docs, code comments, ADRs, and CHANGELOG.
  Detects existing documentation conventions and matches project style.
  Use PROACTIVELY when asked to "document", "write docs", "add comments", "update README", "generate API docs".
  Triggers on: "document", "docs", "readme", "comment", "api docs", "changelog", "adr"
---

# Documentation Generator

Analyze code and project structure to generate meaningful, well-structured documentation.

## When to Use

- Adding API documentation for endpoints
- Generating JSDoc/docstring comments for code
- Creating or updating README
- Writing Architecture Decision Records (ADRs)
- Updating CHANGELOG for a release
- Documenting configuration, environment variables, or setup steps

## Workflow

```
Code/Feature Input → Convention Detection → Doc Type Selection → Generation → Placement
```

### Step 1: Convention Detection

Detect the project's documentation conventions:

#### Comment Style
| Detected | Style | File Clues |
|----------|-------|------------|
| JSDoc | `/** @param {string} name */` | `*.ts`, `*.js`, TypeScript project |
| TSDoc | `/** @param name - description */` | `*.ts`, TypeScript project |
| Docstring (reST) | `"""Summary.\n:param name:"""` | `*.py`, Sphinx project |
| Docstring (Google) | `"""Summary.\nArgs:\n    name:"""` | `*.py`, Google style |
| Docstring (NumPy) | `"""Summary.\nParameters\n----------\nname: type"""` | `*.py`, NumPy style |
| rustdoc | `/// Summary\n/// \n/// # Arguments` | `*.rs` |
| Godoc | `// Summary` | `*.go` |

#### README Style
Look at existing `README.md` — what sections does it have? What's the tone?

#### ADR Format
Check for `docs/adr/` or `docs/architecture/` directory.

#### CHANGELOG Format
Check for `CHANGELOG.md` — Keep a Changelog? Conventional Commits? Custom?

### Step 2: Doc Type Selection

| Task | Output | Key Sections |
|------|--------|-------------|
| API docs | Endpoint reference | Path, method, request/response schemas, auth, errors |
| Code comments | Inline annotations | Purpose, params, returns, throws, examples |
| README | Project README | Title, description, install, usage, API, config, contributing |
| ADR | ADR file | Context, decision, consequences, alternatives |
| CHANGELOG | Changelog entry | Added/Changed/Deprecated/Removed/Fixed/Security |
| Environment docs | `.env.example` | Variable name, description, required/optional, default |

### Step 3: Generation

#### API Documentation Template
```markdown
### `POST /api/users`

Create a new user.

**Auth:** Requires `admin` role token in `Authorization` header.

**Request Body:**
```json
{
  "name": "string (required)",
  "email": "string (required)",
  "role": "string (optional, default: 'user')"
}
```

**Response `201`:**
```json
{
  "id": "string",
  "name": "string"
}
```

**Errors:**
- `400` — Validation error (missing fields, invalid email)
- `409` — Email already exists
- `401` — Missing or invalid auth token
```
```

#### Code Comment Template
Detected style → generate matching format. Follow existing convention exactly.

#### README Template
```
# Project Name

<one-line description>

## Installation

<install instructions>

## Usage

<quick start example>

## API

<generated from source>

## Configuration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `PORT` | No | `3000` | Server port |

## Development

<setup, test, build commands>

## Contributing

<guidelines or link to CONTRIBUTING.md>
```

### Step 4: Placement

- **Code comments:** Added inline, near the documented code
- **API docs:** `docs/api/` or `README.md` section
- **README:** Project root `README.md`
- **ADRs:** `docs/adr/NNNN-title.md` (sequential numbering)
- **CHANGELOG:** `CHANGELOG.md` (insert at top)
- **Environment:** `.env.example` at project root

## Guiding Principles

1. **Document why, not what** — code says what, comments say why
2. **Keep docs near code** — inline comments > separate docs
3. **Match existing style** — consistency > personal preference
4. **Update docs with code** — doc changes in same PR as code changes
5. **Examples > descriptions** — a code example is worth a paragraph

## Anti-Patterns

- ❌ Obvious comments (`// increment i` for `i++`)
- ❌ Outdated documentation (docs that don't match code)
- ❌ Documenting internal implementation in public API docs
- ❌ No examples in API documentation
- ❌ Mixed documentation styles in same project

## Related Skills

- `pr-review` — Review doc quality alongside code
- `dev-flow` — Include doc updates in the plan phase
