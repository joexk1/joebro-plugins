# Antigravity (`agy`)

## Hooks + MCP (live status, chat, Shared Memory, Night Shift)

```sh
joebro-agents install --agy
```

This adds a `"joebro"` hook group to `~/.gemini/config/hooks.json` (SessionStart,
PreInvocation, PreToolUse, PostToolUse, Stop) and registers the `joebro` MCP server
in `~/.gemini/config/mcp_config.json`, next to any hooks and MCP servers you already have.

- **Dynamic Island & Agents panel**: turns, tool calls, assistant replies (from the
  session transcript), subagents (`invoke_subagent`), questions (`ask_question`) and
  errors/limits report live to your JoeBro backend.
- **Two-way chat / follow-ups**: messages sent from the Mac or iPhone app while
  Antigravity is busy are delivered mid-turn via `PreInvocation` (`injectSteps`) or at
  `Stop` (`{"decision": "continue", "reason": "…"}`). Idle sessions in Kitty/tmux receive
  them directly in the terminal.
- **Shared Memory**: `SessionStart` injects the project brief (`<= 400` tokens) as a
  system message, and the MCP server exposes `memory_recall` / `memory_remember` tagged
  with `agent: "agy"`.
- **Night Shift & session start/resume**: runs `agy -p … --output-format json` for
  unattended tasks and `agy --resume <id>` / `--prompt-interactive` for interactive sessions.

To remove JoeBro's hooks and MCP entry cleanly:

```sh
joebro-agents install --agy --uninstall
```
