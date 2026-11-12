"""REFERENCE for the backend half of the node runner (see reports/requests.md). Loaded by test_node.py as a jb_ext
module into an unmodified prod-mac backend. It shows the three things the core still needs:
  GET  /api/night-shift                  lists tasks with pending_action filled in
  POST /api/night-shift/<id>/claim       {node} -> {ok, task, prompt, commands, default_agent}; 409 unless queued (atomic)
  POST /api/night-shift/<id>/report      {node, status, branch, ..., result, diff_text, screenshot_b64 | decision}
  POST /api/night-shift/<id>/node-decide {action: approve:keep|approve:merge|reject} parks a decision for the node
  POST /api/night-shift/_session         test helper: queue a kind=session task
"""
import base64
import json
import os
import time

import jb_nightworker as worker


def _pending(h):
    r = h.store.one("select value from prefs where key='node_pending'")
    return json.loads(r["value"]) if r else {}


def _set_pending(h, d):
    h.store.exec("insert or replace into prefs(key,value) values('node_pending',?)", (json.dumps(d),))


def route(h, method, path, q):
    if not path.startswith("/api/night-shift"):
        return False
    parts = [p for p in path[len("/api/night-shift"):].split("/") if p]
    if method == "GET" and not parts:
        h._night_table()
        pend = _pending(h)
        tasks = []
        for r in h.store.rows("select * from night_tasks order by position"):
            t = h.night_out(r)
            t["pending_action"] = pend.get(r["id"], "")
            tasks.append(t)
        h.json({"ok": True, "tasks": tasks})
        return True
    if method != "POST" or not parts:
        return False
    b = h._json_body() or {}
    if parts[0] == "_session":
        t = h.night_add(b, kind="session")
        h.json({"ok": True, "task": h.night_out(h.night_task(t["id"] if isinstance(t, dict) else t))})
        return True
    if len(parts) != 2 or parts[1] not in ("claim", "report", "node-decide"):
        return False
    tid, action = parts
    r = h.night_task(tid)
    if action == "claim":
        if r["status"] != "queued":
            h.json({"ok": False, "error": "not queued"}, 409)
            return True
        h._night_set(tid, status="running", runner="node:" + str(b.get("node")), started=time.time(), attempts=r["attempts"] + 1, error="", run_now=0)
        r = h.night_task(tid)
        branch = r["branch"] or "%s%s-%s" % (worker.BRANCH_PREFIX, tid, worker.slug(r["title"]))
        h.json({"ok": True, "task": h.night_out(r), "prompt": h._night_prompt(r, branch), "commands": h._night_commands(),
                "default_agent": h.night_config()["default_agent"]})
        return True
    if action == "node-decide":
        d = _pending(h)
        d[tid] = str(b.get("action") or "")
        _set_pending(h, d)
        h.json({"ok": True})
        return True
    # report
    if b.get("decision"):
        dec = dict(b["decision"], at=time.time())
        h._night_set(tid, status="approved" if dec["decision"] == "approve" else "rejected", decision=dec)
        d = _pending(h)
        d.pop(tid, None)
        _set_pending(h, d)
        h.json({"ok": True})
        return True
    fields = {k: b[k] for k in ("status", "branch", "worktree", "base_branch", "base_commit", "head_commit", "error", "resume_id", "agent") if k in b}
    if "result" in b:
        fields["result"] = b["result"]
    h._night_set(tid, finished=time.time(), **fields)
    os.makedirs(h._night_dir(tid), exist_ok=True)
    if b.get("diff_text"):
        open(os.path.join(h._night_dir(tid), "diff.patch"), "w").write(b["diff_text"])
    if b.get("screenshot_b64"):
        open(os.path.join(h._night_dir(tid), "screenshot.png"), "wb").write(base64.b64decode(b["screenshot_b64"]))
    h.json({"ok": True})
    return True


def setup(ext):
    # test only: commands for the fake agents come from the environment (no real agent ever runs)
    ext.on("pref_default", lambda key: json.loads(os.environ["JOEBRO_TEST_NIGHT_COMMANDS"]) if key == "night_shift_commands" and os.environ.get("JOEBRO_TEST_NIGHT_COMMANDS") else None)
