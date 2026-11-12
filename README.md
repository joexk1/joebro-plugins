<h1 align="center">JoeBro Plugins</h1>

<p align="center">Link your coding agents to JoeBro, and make JoeBro do new things.</p>

<p align="center"><a href="https://joebro.pages.dev"><b>joebro.pages.dev</b></a> · <a href="https://github.com/joexk1/JoeBro">The Mac app</a> · <a href="https://github.com/joexk1/JoeBro-Mobile">The iPhone app</a></p>

## What's in here

**Agent link.** Claude Code, Codex and opencode report what they're doing to your own JoeBro backend. They show up in the Mac app's Agents panel, the iPhone app and the Dynamic Island: working, waiting for your approval, finished. JoeBro can read what they're up to, queue them a follow-up that they pick up the moment their turn ends, and they can ping your phone when they're done or stuck.

**Plugins.** A JoeBro plugin is a folder with a `joebro-plugin.json` manifest. It can give JoeBro new **tools**, an always-on **guardrail**, and its own **panel** in the Mac app. You can write one by hand, or ask JoeBro or any coding agent to build one for you. The standard is [SPEC.md](SPEC.md) (`joebro.plugin/1`).

Everything talks to *your* backend (on your Mac or your Pi) and nothing else. There's no account and no JoeBro server.

```
repo
├── bin/joebro-agents      the CLI, the hook reporter and the MCP server (one stdlib Python file)
├── claude-code/           Claude Code plugin: hooks + the MCP server
├── opencode/joebro.js     opencode plugin
├── codex/                 Codex hooks + MCP setup
├── SPEC.md                the plugin standard
├── runtime/               the reference plugin runtime (ships inside JoeBro)
└── examples/plant-care/   a complete plugin: tools, guardrail and a panel
```

## Install

You need Python 3.9 or newer (macOS ships it) and JoeBro 1.4 or newer (1.5 for Shared Memory and Night Shift).

```sh
git clone https://github.com/joexk1/joebro-plugins ~/.joebro-plugins
python3 ~/.joebro-plugins/bin/joebro-agents install        # puts joebro-agents on your PATH (~/.local/bin)
joebro-agents link http://127.0.0.1:8771                    # where your JoeBro backend runs
```

If your backend needs a token (any backend you reach over the network should), add `--token-file ~/path/to/token`. Running JoeBro on a Pi? Point it there: `joebro-agents link http://your-pi:8771 --token-file …`. `joebro-agents status` checks the link.

`joebro-agents install` adds the hooks to every agent it finds. Each config is backed up first (`*.before-joebro`), only JoeBro's own entries are ever touched, and `joebro-agents install --uninstall` takes them out again.

<table>
  <tr>
    <td width="50%" valign="top">
      <h3>Claude Code</h3>
      <p>Either the hooks from <code>joebro-agents install</code>, plus the MCP server:</p>
<pre>claude mcp add joebro -- joebro-agents mcp</pre>
      <p>or the plugin, which carries both:</p>
<pre>/plugin marketplace add joexk1/joebro-plugins
/plugin install joebro@joebro</pre>
    </td>
    <td width="50%" valign="top">
      <h3>Codex</h3>
      <p><code>joebro-agents install --codex</code> adds the hooks to <code>~/.codex/hooks.json</code>. Codex asks once to trust them. For the MCP server, add to <code>~/.codex/config.toml</code>:</p>
<pre>[mcp_servers.joebro]
command = "joebro-agents"
args = ["mcp"]</pre>
      <p>More in <a href="codex/README.md">codex/README.md</a>.</p>
    </td>
  </tr>
  <tr>
    <td width="50%" valign="top">
      <h3>opencode</h3>
      <p><code>joebro-agents install --opencode</code> copies <code>opencode/joebro.js</code> into <code>~/.config/opencode/plugins/</code>. Queued messages arrive as a new prompt when the session goes idle.</p>
    </td>
    <td width="50%" valign="top">
      <h3>JoeBro itself</h3>
      <p>Add the same MCP server in JoeBro under <b>Tools → MCP</b> (command <code>joebro-agents</code>, args <code>mcp</code>). Then you can ask JoeBro to check on your agents, nudge one, or build a plugin.</p>
    </td>
  </tr>
</table>

## Shared Memory and Night Shift (JoeBro 1.5)

**Shared Memory** is for what your agents learn as they work: decisions, gotchas, what was tried. Claude Code, Codex and OpenCode all read and write it through the MCP server (`memory_recall`, `memory_remember`), and each session starts with a brief of at most about 400 tokens. Your instructions (build commands, conventions, rules) stay in CLAUDE.md and AGENTS.md.

```sh
joebro-agents memory import            # dry run: shows what it would do
joebro-agents memory import --write    # moves Claude Code's learned memory across (backed up) and
                                       # adds a short pointer block to CLAUDE.md and AGENTS.md
```

`--write` never removes or rewrites what's already in CLAUDE.md or AGENTS.md; it only appends one pointer block, and running it again doesn't add a second. `--include-instructions` also copies facts out of those files into Shared Memory, still without changing them.

**Night Shift** runs queued coding tasks on the computers that have the repo. Run the node runner on each computer you want to take tasks:

```sh
joebro-agents node run --every 30      # keep it running (a systemd user unit or a LaunchAgent works well)
```

Each task runs in its own git worktree and branch, through tmux if it's installed (so you can attach and watch; Codex tasks need tmux), and reports the diff and test result back for review. It never pushes.

## Pings

Any agent (or script) can ping your phone through JoeBro:

```sh
joebro-ping "Migration finished, 2 tests still failing in auth/"
```

From the MCP server it's the `joebro_ping` tool. The notification says which agent and project it came from. Pings are rate limited to one a minute and 30 a day per agent, so a confused agent in a loop can't flood you.

## The MCP server

`joebro-agents mcp` is one MCP server for both jobs:

| Tool | What it does |
| --- | --- |
| `joebro_ping` | ping your phone |
| `coding_agents_list`, `coding_agent_detail`, `coding_agent_wait` | see every agent: running, waiting on you, idle |
| `coding_agent_send` | give an agent a follow-up. Idle agents in a controllable terminal get it typed in. Busy ones get it from their own Stop hook the moment their turn ends, and carry on. |
| `coding_agent_screen`, `coding_agent_control`, `coding_agent_launch` | read the terminal, approve/deny/interrupt, open a new agent (needs terminal control on that computer) |
| `joebro_plugin_spec`, `_list`, `_install`, `_source`, `_test`, `_rollback` | build, install, test and roll back JoeBro plugins |

## Building a plugin

```sh
joebro-plugin init plant-care      # a working skeleton: one tool, one panel
# edit joebro-plugin.json, tools.py, ui/index.html
joebro-plugin push plant-care      # validated, installed, off until you switch it on
joebro-plugin test plant-care plants_due
```

A plugin:

```json
{
  "schema": "joebro.plugin/1",
  "id": "plant-care",
  "name": "Plant care",
  "version": "1.0.0",
  "description": "Remembers when each plant was last watered.",
  "permission": "sandbox",
  "runtime": {"type": "python", "entry": "tools.py"},
  "contributes": {
    "tools": [{"name": "plants_due", "description": "Plants due for water. Use when…", "parameters": {"type": "object", "properties": {}}}],
    "guardrail": "When the user mentions watering a plant, record it with plant_watered.",
    "panels": [{"id": "plants", "title": "Plants", "icon": "leaf", "entry": "ui/index.html"}]
  }
}
```

- **Tools** are plain Python functions (or any MCP server, in any language). They run in their own process, in the plugin's folder, with a private data folder that survives updates.
- **Guardrails** are added to every turn while the plugin is on.
- **Panels** are HTML pages shown in the Mac app's Plugins tab. They have no network access. They talk to their own plugin through `await joebro.call("tool", {...})` and nothing else.
- **Permission** (`readonly`, `sandbox`, `full`) sets the agent access level a chat needs before the plugin's tools are offered.

Installs are all-or-nothing: every problem in the manifest is listed at once, Python is compile-checked, files are staged and swapped atomically, and the previous version is kept (`joebro-plugin rollback <id>`). A new plugin arrives switched **off**, with a ping saying what it adds.

The full standard is [SPEC.md](SPEC.md). [examples/plant-care](examples/plant-care) is a complete plugin to copy from.

## What gets sent

Hooks send JoeBro the session id, the folder it's in, its state, the tool it's using with a short argument (a file name, a command's description), the first 200 characters of your prompt and of the agent's last reply, the model, and which terminal it's in. That's it, and only to the backend you linked.

- **Nothing leaves your network.** No relay, no account, no telemetry.
- **Hooks never wait on the network.** They fork, send in the background and return at once. If you haven't linked, they do nothing at all.
- **Hooks stay quiet.** The only time one prints is to hand your agent a message JoeBro queued for it.

## Tests

```sh
python3 -m unittest discover -s test
```

## Licence

MIT. See [LICENSE](LICENSE). JoeBro itself is GPL-3.0.
