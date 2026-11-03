# Changelog

## 1.0.0 (2026-11-03)

- `joebro-agents`: one stdlib Python file that links Claude Code, Codex and opencode to JoeBro (hook reporter), runs the `joebro` MCP server, builds plugins and pings your phone.
- Command channel: JoeBro can queue a follow-up for any agent; the agent's Stop hook hands it over the moment its turn ends.
- `joebro-ping` / `joebro_ping`: pings through JoeBro, rate limited per agent.
- Plugin standard `joebro.plugin/1` (tools, guardrails, panels) with `joebro-plugin init|push|test|source|rollback`.
- Claude Code plugin + marketplace, opencode plugin, Codex hooks.
- Example plugin: plant-care.
