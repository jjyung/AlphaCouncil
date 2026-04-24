# OpenCode Agents (Migrated from OMC)

These agents were converted from `agents/*.md` into OpenCode markdown-agent format.

## Location

- Project-level agents: `.opencode/agents/*.md`

## Default model

- All agents are currently set to `openai/gpt-5.3-codex`.

If your OpenCode setup uses a different model ID, edit the `model:` field in each agent file.

## Notes

- All converted agents are set to `mode: subagent`.
- Original `disallowedTools: Write, Edit` was mapped to:

```yaml
permission:
  edit: deny
```

- Prompt bodies are preserved from the source files.
