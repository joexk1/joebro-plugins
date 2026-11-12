"""Node runner: lets one linked computer (Mac, Linux box, Pi) run Night Shift tasks and start/resume
coding sessions for repos it has, on behalf of a JoeBro backend that lives somewhere else.

No daemon of its own: `joebro-agents node tick` is one pass (cron / launchd / a shell loop), and
`joebro-agents node run` is the same pass in a loop. A pass
  1. lists queued tasks (GET /api/night-shift?status=queued) and keeps those whose repo exists HERE
     and whose host is empty or this node's name,
  2. claims one (POST /api/night-shift/<id>/claim) so no other node or the backend runs it too,
  3. runs it in a git worktree through tmux (`tmux attach -t jb-<id>` to watch), with git push disabled,
  4. reports the result (POST /api/night-shift/<id>/report): summary, diff stats + diff text, tests, screenshot,
  5. executes decisions the backend parked for this node (task.pending_action approve:keep | approve:merge | reject).
It never pushes: every agent and test command runs with push URLs rewritten, and this file has no push call.
Stdlib only. The git/agent helpers are jb_nightworker.py (same file the backend uses)."""
import base64
import json
import os
import shutil
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jb_nightworker as worker  # noqa: E402

ROOT = os.environ.get("JOEBRO_NODE_DIR") or os.path.join(os.path.expanduser("~"), ".local", "share", "joebro", "night-shift")


def call(cfg, method, path, body=None, timeout=20):
    headers = {"Content-Type": "application/json"}
    if cfg.get("token"):
        headers["Authorization"] = "Bearer " + cfg["token"]
    req = urllib.request.Request(cfg["url"] + path, method=method, headers=headers,
                                 data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except ValueError:
            return e.code, {}
    except (OSError, ValueError):
        return 0, {}


EXTRA_PATH = ["~/.local/bin", "~/.npm-global/bin", "~/.opencode/bin", "~/.claude/local", "~/.cargo/bin", "~/bin",
              "/opt/homebrew/bin", "/opt/homebrew/sbin", "/usr/local/bin", "/usr/bin", "/bin"]


def fix_path():
    """systemd/launchd start us with a bare PATH: add where claude, codex, opencode and tmux usually live
    (including every nvm node version), so shutil.which finds them as in a login shell."""
    import glob
    have = os.environ.get("PATH", "").split(os.pathsep)
    extra = [os.path.expanduser(p) for p in EXTRA_PATH] + sorted(glob.glob(os.path.expanduser("~/.nvm/versions/node/*/bin")), reverse=True)
    os.environ["PATH"] = os.pathsep.join(have + [p for p in extra if p not in have and os.path.isdir(p)])


def is_repo(path):
    return bool(path) and os.path.isdir(path) and worker.git(path, "rev-parse", "--show-toplevel")[0] == 0


def pick_agent(task, claim):
    commands = claim.get("commands") or {}
    if task.get("agent") not in (None, "", "any"):
        return task["agent"], commands
    order = [claim.get("default_agent") or "claude"] + [a for a in worker.COMMANDS]
    return next((a for a in order if worker.installed(a, commands)), order[0]), commands


def runnable(task, host):
    return (task.get("status") == "queued" and task.get("host") in ("", None, host) and is_repo(task.get("repo")))


def log(msg):
    print("[node] " + msg, flush=True)


def run_task(cfg, host, task, claim, stop=None):
    tid, agent = task["id"], None
    agent, commands = pick_agent(task, claim)
    shot_dir = os.path.join(ROOT, tid)
    os.makedirs(shot_dir, exist_ok=True)
    rep = {"node": host, "agent": agent}
    try:
        if not worker.installed(agent, commands):
            raise ValueError("%s is not installed on %s" % (agent, host))
        prep = worker.prepare(task["repo"], tid, task["title"], os.path.join(ROOT, "worktrees"), task.get("branch") or "", task.get("worktree") or "")
        rep.update(branch=prep["branch"], worktree=prep["worktree"])
        if not prep.get("reused"):
            rep.update(base_branch=prep["base_branch"], base_commit=prep["base_commit"])
        base = rep.get("base_commit") or task.get("base_commit")
        argv = worker.agent_argv(agent, claim["prompt"], task.get("model") or "", task.get("budget_usd") or 0, commands, task.get("resume_id") or "")
        env = dict(worker.no_push_env(), JOEBRO_NIGHT_TASK=tid)
        run = worker.run_agent_tmux("jb-" + tid[3:], argv, prep["worktree"], task.get("max_minutes") or 60, env, stop,
                                    log_path=os.path.join(shot_dir, "agent.log"))
        parsed = worker.parse_output(run["output"])
        col = worker.collect(prep["worktree"], base, task["title"], task.get("test_command") or "", shot_dir=shot_dir)
    except (ValueError, OSError) as exc:
        rep.update(status="failed", error=str(exc)[:300])
        return rep
    text, truncated = worker.diff_text(prep["repo"], base, col["head_commit"])
    rep["result"] = {"summary": parsed["summary"], "learned": parsed["learned"], "cost_usd": parsed["cost_usd"], "commits": col["commits"],
                     "diff": col["diff"], "tests": col["tests"], "screenshot": col["screenshot"], "duration_s": run["duration_s"],
                     "agent_exit": run["exit"], "timed_out": run["timed_out"]}
    rep.update(head_commit=col["head_commit"], diff_text=text, diff_truncated=truncated, resume_id=parsed["session_id"] or task.get("resume_id") or "",
               status="review" if col["commits"] and not run["stopped"] else "failed",
               error=("cancelled" if run["stopped"] else "stopped at the %s minute cap" % task.get("max_minutes") if run["timed_out"]
                      else "the agent made no changes" if not col["commits"] else ""))
    shot = os.path.join(shot_dir, "screenshot.png")
    if col["screenshot"] and os.path.isfile(shot):
        rep["screenshot_b64"] = base64.b64encode(open(shot, "rb").read()).decode()
    return rep


def run_session(host, task, claim):
    agent, commands = pick_agent(task, claim)
    if not worker.installed(agent, commands):
        return {"node": host, "status": "failed", "error": "%s is not installed on %s" % (agent, host)}
    try:
        if not shutil.which("tmux") and agent in ("claude", "opencode"):
            return run_headless(host, task, agent, commands)       # no tmux: still carry the session on (just not attachable)
        argv = worker.session_argv(agent, task["prompt"], task.get("model") or "", task.get("resume_id") or "", commands)
        out = worker.tmux_launch("jb-" + task["id"][3:], task["repo"], argv, {"JOEBRO_NIGHT_TASK": task["id"]})
    except ValueError as exc:
        return {"node": host, "status": "failed", "error": str(exc)[:300]}
    return {"node": host, "agent": agent, "status": "launched", "result": {"launch": out, "summary": "Session started on %s." % host}}


def run_headless(host, task, agent, commands):
    """Without tmux: resume/start the session in the background in print mode (hooks still report it; install tmux to attach)."""
    import subprocess
    argv = worker.agent_argv(agent, task["prompt"], task.get("model") or "", 0, commands, task.get("resume_id") or "")
    logdir = os.path.join(os.path.expanduser("~"), ".local", "state", "joebro-agents")
    os.makedirs(logdir, exist_ok=True)
    logf = os.path.join(logdir, task["id"] + ".log")
    with open(logf, "ab") as f:
        subprocess.Popen(argv, cwd=task["repo"], stdin=subprocess.DEVNULL, stdout=f, stderr=subprocess.STDOUT, start_new_session=True,
                         env=dict(os.environ, **{"JOEBRO_NIGHT_TASK": task["id"]}))
    return {"node": host, "agent": agent, "status": "launched",
            "result": {"launch": {"log": logf}, "summary": "Session continued on %s in the background (no tmux there; log %s)." % (host, logf)}}


def do_pending(cfg, host, task):
    action, _, mode = str(task.get("pending_action") or "").partition(":")
    if action == "approve":
        res = worker.approve(task["repo"], task["branch"], task.get("worktree") or "", task.get("base_branch") or "", mode or "keep", task["title"])
        dec = {"decision": "approve", "mode": mode or "keep", **res}
    elif action == "reject":
        dec = {"decision": "reject", **worker.reject(task["repo"], task["branch"], task.get("worktree") or "")}
    else:
        return None
    return call(cfg, "POST", "/api/night-shift/%s/report" % task["id"], {"node": host, "decision": dec})


def tick(cfg, host, dry=False, stop=None):
    """One pass. Returns a list of what was done (strings)."""
    fix_path()
    done = []
    code, data = call(cfg, "GET", "/api/night-shift?node=" + urllib.parse.quote(host))
    if code != 200:
        return ["backend unreachable or not a JoeBro with Night Shift (HTTP %s)" % code]
    tasks = data.get("tasks") or []
    for t in tasks:        # decisions parked for this node first (they free worktrees)
        if t.get("runner") == "node:" + host and t.get("pending_action") and is_repo(t.get("repo")):
            if not dry:
                do_pending(cfg, host, t)
            done.append("%s %s" % (t["pending_action"], t["id"]))
    for t in sorted(tasks, key=lambda x: (not x.get("run_now"), x.get("position") or 0)):
        if not runnable(t, host):
            continue
        if dry:
            done.append("would claim %s (%s)" % (t["id"], t.get("title")))
            continue
        code, claim = call(cfg, "POST", "/api/night-shift/%s/claim" % t["id"], {"node": host})
        if code != 200 or not claim.get("ok"):
            continue                   # taken by another node, the backend, or not due yet
        task = claim.get("task") or t
        log("running %s (%s) on %s" % (task["id"], task.get("title"), host))
        rep = run_session(host, task, claim) if task.get("kind") == "session" else run_task(cfg, host, task, claim, stop)
        call(cfg, "POST", "/api/night-shift/%s/report" % task["id"], rep, timeout=60)
        done.append("%s %s -> %s" % (task.get("kind") or "task", task["id"], rep.get("status")))
        if task.get("kind") != "session":
            break                      # one long task per pass; the next pass picks up the rest
    return done


def run_loop(cfg, host, every=60, once=False):
    stop = threading.Event()
    while True:
        for line in tick(cfg, host, stop=stop):
            log(line)
        if once:
            return 0
        time.sleep(max(5, every))
