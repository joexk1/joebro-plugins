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
  const parents = new Map()   // child session id -> parent session id (OpenCode subagents are child sessions)
  const send = (ev) => {
    if (ev?.session_id && parents.has(ev.session_id) && !ev.parent_session_id) ev = { ...ev, parent_session_id: parents.get(ev.session_id) }
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
  // Shared Memory brief (<= 400 tokens), fetched once per plugin instance and added to the system prompt.
  let brief = null
  const loadBrief = () => new Promise((resolve) => {
    if (brief !== null || process.env.JOEBRO_MEMORY === "off") return resolve(brief || "")
    execFile(JOEBRO, ["brief"], { timeout: 3000, cwd: directory }, (err, out) => {
      brief = err || /^\(no memory/.test(out || "") ? "" : String(out || "").trim()
      resolve(brief)
    })
  })
  return {
    "experimental.chat.system.transform": async (_input, output) => {
      try { const text = await loadBrief(); if (text && Array.isArray(output?.system)) output.system.push(text) } catch {}
    },
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
        case "session.created":
          if (p.info?.parentID) {   // a child session = a subagent (the Task tool); the parent is another session
            parents.set(sid, p.info.parentID)
            return send({ event: "subagent_start", session_id: sid, parent_session_id: p.info.parentID, name: clip(p.info?.title, 80),
                          subagent_type: clip((p.info?.title || "").match(/\(@([\w-]+) subagent\)/)?.[1] || "subagent", 40) })
          }
          return send({ event: "start", session_id: sid, name: clip(p.info?.title, 80) })
        case "session.idle":
          if (parents.has(sid)) return send({ event: "subagent_stop", session_id: sid })   // the child's own idle closes it
          deliver(sid); return send({ event: "stop", session_id: sid })
        case "session.status":
          if (p.status?.type === "idle") {
            if (parents.has(sid)) return send({ event: "subagent_stop", session_id: sid })
            deliver(sid); return send({ event: "stop", session_id: sid })
          }
          return
        case "session.error": return send({ event: parents.has(sid) ? "subagent_stop" : "stop", session_id: sid, text: "error" })
        case "session.deleted": { const sub = parents.has(sid); const r = send({ event: sub ? "subagent_stop" : "end", session_id: sid }); parents.delete(sid); return r }
        case "permission.asked":
        case "permission.updated": return send({ event: "waiting", session_id: sid, text: clip(p.title ?? p.type ?? "needs approval", 160) })
      }
    },
  }
}
