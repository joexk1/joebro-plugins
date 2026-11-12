"""Node runner (`joebro-agents node`) against a REAL JoeBro backend: a temp copy of prod-mac's Backend with a temp
HOME/data dir and the reference ext (nightnode_ref_ext.py) providing claim/report. Fake agent, throw-away git repo,
real tmux when installed. Skipped when the backend sources are not next to this repo.
Run: python3 -m unittest discover -s test"""
import json
import os
import pathlib
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
JOEBRO = os.path.join(ROOT, "bin", "joebro-agents")
BACKEND = os.environ.get("JOEBRO_BACKEND_SRC") or os.path.join(os.path.dirname(ROOT), "prod-mac", "JoeBro", "Backend")

FAKE_AGENT = r'''
import os, subprocess, sys
open("feature.py", "w").write("def answer():\n    return 42\n")
subprocess.run(["git", "add", "feature.py"]); subprocess.run(["git", "-c", "user.name=a", "-c", "user.email=a@a", "commit", "-qm", "add feature"])
push = subprocess.run(["git", "push", "origin", "HEAD"], capture_output=True, text=True)
os.makedirs(".joebro/night", exist_ok=True); open(".joebro/night/screenshot.png", "wb").write(b"\x89PNG fake")
print("PUSH_EXIT=%d cwd=%s" % (push.returncode, os.getcwd()))
print("SUMMARY: Added feature.py. task=%s" % os.environ.get("JOEBRO_NIGHT_TASK"))
print("LEARNED: Feature modules live at the repo root and are named feature.py.")
'''


def sh(cwd, *a):
    return subprocess.run(a, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@unittest.skipUnless(os.path.isfile(os.path.join(BACKEND, "joebro_backend.py")), "prod-mac backend sources not found")
class NodeRunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.home = os.path.join(cls.tmp, "home")
        os.makedirs(cls.home)
        be = os.path.join(cls.tmp, "backend")
        os.makedirs(be)
        for f in os.listdir(BACKEND):
            if f.endswith(".py") and not f.startswith("test_"):
                shutil.copy(os.path.join(BACKEND, f), be)
        ext = os.path.join(cls.tmp, "ext")
        os.makedirs(ext)
        shutil.copy(os.path.join(HERE, "nightnode_ref_ext.py"), ext)
        shutil.copy(os.path.join(ROOT, "runtime", "jb_nightworker.py"), ext)
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        cls.url = "http://127.0.0.1:%d" % port
        cls.env = dict(os.environ, HOME=cls.home, JOEBRO_EXT_DIR=ext, JOEBRO_URL=cls.url, JOEBRO_HOST="linuxbox",
                       JOEBRO_NODE_DIR=os.path.join(cls.tmp, "node"), PYTHONPATH=ext)
        for k in ("JOEBRO_TOKEN", "JOEBRO_PHONE_SESSION"):
            cls.env.pop(k, None)
        agent = os.path.join(cls.tmp, "fake_agent.py")
        with open(agent, "w") as f:
            f.write(FAKE_AGENT)
        cls.env["JOEBRO_TEST_NIGHT_COMMANDS"] = os.environ.get("JOEBRO_TEST_REAL_COMMANDS") or json.dumps({"claude": [sys.executable, agent, "{prompt}"], "claude_session": [sys.executable, "-c", "import time; time.sleep(60)"]})
        bindir = os.path.join(cls.tmp, "bin")                       # a stand-in tmux (the real one is not on every test box)
        os.makedirs(bindir)
        if not shutil.which("tmux"):
            shutil.copy(os.path.join(HERE, "fake_tmux.py"), os.path.join(bindir, "tmux"))
            os.chmod(os.path.join(bindir, "tmux"), 0o755)
            cls.env["PATH"] = bindir + os.pathsep + cls.env["PATH"]
            cls.env["FAKE_TMUX_DIR"] = os.path.join(cls.tmp, "tmuxstate")
        cls.proc = subprocess.Popen([sys.executable, "joebro_backend.py", "--port", str(port), "--data-dir", os.path.join(cls.tmp, "data")],
                                    cwd=be, env=cls.env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            try:
                urllib.request.urlopen(cls.url + "/api/night-shift", timeout=1)
                break
            except Exception:
                time.sleep(0.2)
        else:
            raise RuntimeError("backend did not start")

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    @classmethod
    def req(cls, method, path, body=None):
        r = urllib.request.Request(cls.url + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                   headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(r, timeout=20) as x:
                return json.loads(x.read() or b"{}")
        except urllib.error.HTTPError as e:
            return dict(json.loads(e.read() or b"{}"), _status=e.code)

    def make_repo(self):
        d = tempfile.mkdtemp(dir=self.tmp)
        repo, remote = os.path.join(d, "proj"), os.path.join(d, "remote.git")
        os.makedirs(repo)
        sh(d, "git", "init", "-q", "--bare", remote)
        sh(repo, "git", "init", "-q", "-b", "main")
        sh(repo, "git", "remote", "add", "origin", remote)
        with open(os.path.join(repo, "app.py"), "w") as f:
            f.write("print('hi')\n")
        sh(repo, "git", "add", ".")
        sh(repo, "git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init")
        sh(repo, "git", "push", "-q", "origin", "main")
        return repo, remote

    def node(self, *args):
        return subprocess.run([sys.executable, JOEBRO, "node"] + list(args), capture_output=True, text=True, env=self.env, timeout=120)

    def task(self, tid):
        return self.req("GET", "/api/night-shift/" + tid)["task"]

    def test_full_cycle_claim_run_report_approve_never_push(self):
        repo, remote = self.make_repo()
        t = self.req("POST", "/api/night-shift", {"repo": repo, "prompt": "add a feature", "title": "Add feature", "agent": "claude",
                                                    "test_command": "python3 -c 'import sys; sys.exit(0)'"})["task"]
        other = self.req("POST", "/api/night-shift", {"repo": repo, "prompt": "x", "host": "somewhere-else", "agent": "claude"})["task"]
        dry = self.node("tick", "--dry-run")
        self.assertIn("would claim " + t["id"], dry.stdout)
        self.assertNotIn(other["id"], dry.stdout)                      # another node's task is left alone
        r = self.node("tick")
        got = self.task(t["id"])
        self.assertIn("%s -> review" % t["id"], r.stdout + r.stderr + got["error"])
        self.assertEqual((got["status"], got["runner"], got["agent"]), ("review", "node:linuxbox", "claude"))
        self.assertIn("Added feature.py", got["result"]["summary"])
        self.assertEqual(got["result"]["diff"]["files"], 1)
        self.assertTrue(got["result"]["tests"]["passed"])
        self.assertTrue(got["result"]["screenshot"])
        self.assertTrue(got["worktree"].startswith(os.path.join(self.tmp, "node")), got["worktree"])
        self.assertTrue(os.path.isfile(os.path.join(got["worktree"], "feature.py")))        # ran in the worktree
        self.assertEqual(self.task(other["id"])["status"], "queued")
        # never pushed: the agent tried and failed; the remote still has only main's first commit
        self.assertEqual(sh(remote, "git", "rev-list", "--all", "--count"), "1")
        self.assertNotIn("PUSH_EXIT=0", pathlib.Path(self.tmp, "node", t["id"], "agent.log").read_text())
        # the backend parks the user's decision; the next pass executes it on the node
        self.req("POST", "/api/night-shift/%s/node-decide" % t["id"], {"action": "approve:keep"})
        r = self.node("tick")
        self.assertIn("approve:keep " + t["id"], r.stdout)
        self.assertEqual(self.task(t["id"])["status"], "approved")
        self.assertFalse(os.path.isdir(got["worktree"]))
        self.assertIn(got["branch"], sh(repo, "git", "branch", "--list", got["branch"]))
        self.assertEqual(sh(remote, "git", "rev-list", "--all", "--count"), "1")

    def test_reject_removes_worktree_and_branch(self):
        repo, _ = self.make_repo()
        t = self.req("POST", "/api/night-shift", {"repo": repo, "prompt": "add a feature", "agent": "claude"})["task"]
        self.node("tick")
        got = self.task(t["id"])
        self.assertEqual(got["status"], "review", got["error"])
        self.req("POST", "/api/night-shift/%s/node-decide" % t["id"], {"action": "reject"})
        self.node("tick")
        self.assertEqual(self.task(t["id"])["status"], "rejected")
        self.assertEqual(sh(repo, "git", "branch", "--list", got["branch"]), "")

    def test_session_job_launches_in_tmux(self):
        repo, _ = self.make_repo()
        t = self.req("POST", "/api/night-shift/_session", {"repo": repo, "prompt": "hello", "agent": "claude"})["task"]
        r = self.node("tick")
        self.assertIn("session %s -> launched" % t["id"], r.stdout)
        name = "jb-" + t["id"][3:]
        tmux = shutil.which("tmux", path=self.env["PATH"])
        try:
            self.assertEqual(subprocess.run([tmux, "has-session", "-t", name], capture_output=True, env=self.env).returncode, 0)
            self.assertEqual(self.task(t["id"])["status"], "launched")
        finally:
            subprocess.run([tmux, "kill-session", "-t", name], capture_output=True, env=self.env)

    def test_bare_path_gets_the_agent_dirs_and_no_tmux_still_resumes_headless(self):
        sys.path.insert(0, os.path.join(ROOT, "runtime"))
        import jb_node
        home = os.path.join(self.tmp, "h2"); fake = os.path.join(home, ".npm-global", "bin"); os.makedirs(fake)
        out = os.path.join(self.tmp, "args.txt")
        real_which = shutil.which
        pathlib.Path(fake, "claude").write_text("#!/bin/sh\necho \"$@\" > %s\n" % out)
        os.chmod(os.path.join(fake, "claude"), 0o755)
        old_home, old_path = os.environ["HOME"], os.environ["PATH"]
        os.environ["HOME"], os.environ["PATH"] = home, "/usr/bin:/bin"
        try:
            jb_node.fix_path()
            self.assertIn(fake, os.environ["PATH"].split(os.pathsep))
            with mock.patch("shutil.which", side_effect=lambda n, path=None: None if n == "tmux" else real_which(n, path=path)):
                task = {"id": "ns_abc", "repo": self.tmp, "prompt": "carry on", "agent": "claude", "resume_id": "sid-1"}
                rep = jb_node.run_session("pc", task, {"commands": {"claude": [os.path.join(fake, "claude"), "-p", "{prompt}"]}})
            self.assertEqual(rep["status"], "launched")
            for _ in range(50):
                if os.path.exists(out) and os.path.getsize(out):
                    break
                time.sleep(0.1)
            self.assertIn("carry on", open(out).read())
        finally:
            os.environ["HOME"], os.environ["PATH"] = old_home, old_path

    def test_runner_source_has_no_git_push(self):
        text = pathlib.Path(ROOT, "runtime", "jb_node.py").read_text().replace("never pushes", "")
        self.assertNotRegex(text, r"[\"']push[\"']")


if __name__ == "__main__":
    unittest.main()
