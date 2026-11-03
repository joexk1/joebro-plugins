// JoeBro agent report — OpenCode plugin. Feeds session activity to the JoeBro
// backend (Agents tab, Dynamic Island, personal agent) via the joebro-agents CLI (github.com/joexk1/joebro-plugins).
// Fire-and-forget: a detached child per event, never awaited, never throws.
import { spawn, execFile } from "node:child_process"
import { homedir } from "node:os"
import { join } from "node:path"

const JOEBRO = process.env.JOEBRO_BIN || join(homedir(), ".local", "bin", "joebro-agents")
const clip = (s, n = 200) => String(s ?? "").replace(/\s+/g, " ").trim().slice(0, n)

export const JoeBro = async ({ directory, client }) => {
  // Instructions queued for this session by JoeBro: delivered as a new prompt
  // when the session goes idle.
  const pulling = new Set()
  const deliver = (sid) => {
    if (pulling.has(sid)) return
    pulling.add(sid)
    try {
      execFile(JOEBRO, ["pull", "opencode", sid], { timeout: 3000 }, async (err, out) => {
        setTimeout(() => pulling.delete(sid), 2000)
        if (err) return
        let msgs = []
        try { msgs = JSON.parse(out || "[]") } catch { return }
        if (!msgs.length) return
        const text = msgs.map((m) => (!m.from || m.from.toLowerCase() === "joebro") ? `Message from JoeBro: ${m.text}` : `Message from ${m.from} via JoeBro: ${m.text}`).join("\n\n")
        try { await client.session.prompt({ path: { id: sid }, body: { parts: [{ type: "text", text }] } }) } catch {}
      })
    } catch {}
  }
  const send = (ev) => {
    try {
      const child = spawn(JOEBRO, ["report", "opencode"], { detached: true, stdio: ["pipe", "ignore", "ignore"] })
      child.on("error", () => {})
      child.stdin.on("error", () => {})
      child.stdin.end(JSON.stringify({
        cwd: directory, pid: process.pid,
        kitty_window_id: process.env.KITTY_WINDOW_ID, kitty_listen_on: process.env.KITTY_LISTEN_ON,
        tmux_pane: process.env.TMUX_PANE, ...ev,
      }))
      child.unref()
    } catch {}
  }
  return {
    "chat.message": async (input, output) => {
      const text = (output?.parts ?? []).filter((p) => p?.type === "text").map((p) => p.text).join(" ")
      send({ event: "prompt", session_id: input.sessionID, text: clip(text),
             model: input.model ? `${input.model.providerID}/${input.model.modelID}` : "" })
    },
    "tool.execute.before": async (input, output) => {
      const a = output?.args ?? {}
      const arg = a.description ?? a.command ?? a.filePath ?? a.path ?? a.pattern ?? a.url ?? ""
      send({ event: "tool", session_id: input.sessionID, tool: clip(input.tool, 60), text: clip(arg, 120) })
    },
    event: async ({ event }) => {
      const p = event?.properties ?? {}
      const sid = p.sessionID ?? p.info?.id
      if (!sid) return
      switch (event.type) {
        case "session.created": return send({ event: "start", session_id: sid, name: clip(p.info?.title, 80) })
        case "session.idle": deliver(sid); return send({ event: "stop", session_id: sid })
        case "session.status":
          if (p.status?.type === "idle") { deliver(sid); return send({ event: "stop", session_id: sid }) }
          return
        case "session.error": return send({ event: "stop", session_id: sid, text: "error" })
        case "session.deleted": return send({ event: "end", session_id: sid })
        case "permission.asked":
        case "permission.updated": return send({ event: "waiting", session_id: sid, text: clip(p.title ?? p.type ?? "needs approval", 160) })
      }
    },
  }
}
