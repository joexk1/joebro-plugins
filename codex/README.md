# Codex

## Hooks (live status + messages from JoeBro)

```sh
joebro-agents install --codex
```

This adds `joebro-agents report codex` to `~/.codex/hooks.json` for SessionStart,
UserPromptSubmit, PreToolUse, PermissionRequest and Stop, next to any hooks you
already have. Codex asks once to trust the new hooks.

The Stop hook is how queued messages reach a busy Codex: when its turn ends the
hook answers `{"decision": "block", "reason": "Message from JoeBro: …"}` and Codex
carries on with it.

By hand, each event gets:

```json
{"hooks": [{"type": "command", "command": "/Users/you/.local/bin/joebro-agents report codex", "timeout": 5}]}
```

## MCP server

`~/.codex/config.toml`:

```toml
[mcp_servers.joebro]
command = "joebro-agents"
args = ["mcp"]
```
