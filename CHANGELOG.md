# Changelog

## Unreleased
- Shared Memory gets used: every session starts with a short guide (check memory_recall before guessing, save durable facts with memory_remember the moment you learn them), shown even when the project has no memory yet, and in OpenCode's system prompt.
- Save nudge: once per session, when an agent did real work (3+ edits or commands) and saved nothing, its Stop hook asks it to save anything durable or just stop. Never twice, never for subagents, off with JOEBRO_MEMORY=off.
- Facts written from Codex and OpenCode are now tagged with the right agent (`JOEBRO_HARNESS` in the MCP registration; existing installs are upgraded by `install`) instead of the generic "agent".
- Shared Memory: MCP tools `memory_recall`, `memory_remember`, `memory_supersede`, `memory_forget`, `memory_project_brief`; a brief of at most 400 tokens at session start (Claude Code, Codex, OpenCode); `joebro-agents memory import [--write] [--include-instructions]` moves Claude Code's learned memory into the one store and adds a short pointer block to CLAUDE.md and AGENTS.md, leaving their instructions as they are.
- Night Shift: MCP tools `night_shift_add`, `night_shift_list`, `night_shift_cancel`.
- Node runner: `joebro-agents node tick|run` claims Night Shift tasks and sessions for repos on this computer, runs them in a worktree through tmux and reports back; never pushes (needs the claim/report routes, see reports/requests.md).
- Live subagents: Claude Code SubagentStart/SubagentStop hooks, Codex spawn_agent (best effort), OpenCode child sessions, all reported with the parent id.
- Fixed the headless Codex command line (`--full-auto` is gone in 0.167).
- `joebro-agents install` registers the MCP server with Codex and OpenCode.

## 1.0.0 (2026-11-03)

- `joebro-agents`: one stdlib Python file that links Claude Code, Codex and opencode to JoeBro (hook reporter), runs the `joebro` MCP server, builds plugins and pings your phone.
- Command channel: JoeBro can queue a follow-up for any agent; the agent's Stop hook hands it over the moment its turn ends.
- `joebro-ping` / `joebro_ping`: pings through JoeBro, rate limited per agent.
- Plugin standard `joebro.plugin/1` (tools, guardrails, panels) with `joebro-plugin init|push|test|source|rollback`.
- Claude Code plugin + marketplace, opencode plugin, Codex hooks.
- Example plugin: plant-care.
