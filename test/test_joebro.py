"""joebro CLI against a fake JoeBro backend: link, hooks (incl. the Stop-hook
handover), opencode pull, ping, MCP handshake/tools, plugin init/push, install.
Run: python3 -m unittest discover -s test"""
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JOEBRO = os.path.join(ROOT, "bin", "joebro-agents")


class Fake(BaseHTTPRequestHandler):
    log = []
    inbox = []

    def log_message(self, *a):
        pass

    def _send(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        Fake.log.append(("GET", self.path, self.headers.get("Authorization"), None))
        if self.headers.get("Authorization") != "Bearer sekrit":
            return self._send({"detail": "unauthorized"}, 401)
        if self.path.startswith("/api/coding-agents/inbox"):
            msgs, Fake.inbox[:] = list(Fake.inbox), []
            return self._send({"ok": True, "messages": msgs})
        if self.path == "/api/coding-agents":
            return self._send({"ok": True, "nodes": [{"id": "code:mac:claude:s1", "source": "claude", "host": "mac", "name": "proj",
                                                      "cwd": "/w/proj", "status": "running", "detail": ["Bash: make"], "terminal": {}}]})
        return self._send({"ok": True, "plugins": []})

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        Fake.log.append(("POST", self.path, self.headers.get("Authorization"), body))
        if self.path == "/api/coding-agents/ping":
            return self._send({"ok": True, "delivered": True, "title": "Claude Code · proj"})
        if self.path == "/api/plugins/install":
            return self._send({"ok": True, "plugin": {"id": "plugin_x", "files": sorted(body["files"])}})
        return self._send({"ok": True})


class JoeBroCLITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.url = "http://127.0.0.1:%d" % cls.srv.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def setUp(self):
        self.home = tempfile.mkdtemp()
        Fake.log.clear()
        Fake.inbox.clear()

    def run_cli(self, *args, stdin="", argv0=None, env=None):
        e = dict(os.environ, HOME=self.home)
        for k in list(e):
            if k.startswith(("JOEBRO_", "CLAUDE", "CODEX_", "OPENCODE")):
                e.pop(k)
        e.update(env or {})
        cmd = [sys.executable, JOEBRO] if not argv0 else [sys.executable, "-c",
               "import sys,runpy; sys.argv=[%r]+sys.argv[1:]; runpy.run_path(%r, run_name='__main__')" % (argv0, JOEBRO)]
        return subprocess.run(cmd + list(args), input=stdin, capture_output=True, text=True, env=e, timeout=30)

    def link(self):
        r = self.run_cli("link", self.url, "--token", "sekrit", "--host", "mac")
        self.assertEqual(r.returncode, 0, r.stderr)

    def wait_for(self, path):
        import time
        for _ in range(50):
            hits = [x for x in Fake.log if x[1] == path]
            if hits:
                return hits
            time.sleep(0.05)
        self.fail("no request to " + path)

    def test_link_writes_private_config_and_rejects_bad_token(self):
        bad = self.run_cli("link", self.url, "--token", "nope")
        self.assertNotEqual(bad.returncode, 0)
        self.link()
        cfg = os.path.join(self.home, ".config", "joebro", "agents.json")
        self.assertEqual(oct(os.stat(cfg).st_mode & 0o777), "0o600")
        self.assertEqual(json.load(open(cfg))["host"], "mac")

    def test_hook_is_silent_and_does_nothing_when_unlinked(self):
        r = self.run_cli("report", "claude", stdin=json.dumps({"hook_event_name": "Stop", "session_id": "s1"}))
        self.assertEqual((r.returncode, r.stdout), (0, ""))
        self.assertEqual(Fake.log, [])

    def test_tool_event_is_reported_in_background(self):
        self.link()
        r = self.run_cli("report", "claude", stdin=json.dumps({"hook_event_name": "PreToolUse", "session_id": "s1", "cwd": "/w/proj",
                                                                "tool_name": "Edit", "tool_input": {"file_path": "/w/proj/src/app.py"}}))
        self.assertEqual(r.stdout, "")
        ev = self.wait_for("/api/coding-agents/event")[0][3]
        self.assertEqual((ev["event"], ev["tool"], ev["text"], ev["host"], ev["source"]), ("tool", "Edit", "app.py", "mac", "claude"))

    def test_stop_hook_hands_over_queued_message(self):
        self.link()
        Fake.inbox.append({"from": "JoeBro", "text": "also run the tests"})
        r = self.run_cli("report", "claude", stdin=json.dumps({"hook_event_name": "Stop", "session_id": "s1"}))
        out = json.loads(r.stdout)
        self.assertEqual(out["decision"], "block")
        self.assertEqual(out["reason"], "Message from JoeBro: also run the tests")
        self.assertEqual(self.wait_for("/api/coding-agents/event")[0][3]["event"], "prompt")

    def test_legacy_alias_and_opencode_pull(self):
        self.link()
        Fake.inbox.append({"from": "Codex", "text": "rebase first"})
        r = self.run_cli("pull", "opencode", "s9", argv0="joebro-agent-report")
        self.assertEqual(json.loads(r.stdout), [{"from": "Codex", "text": "rebase first"}])

    def test_ping_names_the_harness(self):
        self.link()
        r = self.run_cli("ping", "Deploy finished", env={"CLAUDECODE": "1"})
        self.assertEqual(r.returncode, 0, r.stderr)
        body = self.wait_for("/api/coding-agents/ping")[0][3]
        self.assertEqual((body["message"], body["source"], body["host"]), ("Deploy finished", "claude", "mac"))
        self.assertEqual(self.run_cli("ping", argv0="joebro-ping").returncode != 0, True)

    def test_mcp_handshake_lists_and_calls_tools(self):
        self.link()
        reqs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "coding_agents_list", "arguments": {}}},
                {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "nope"}}]
        r = self.run_cli("mcp", stdin="\n".join(json.dumps(x) for x in reqs) + "\n")
        out = [json.loads(l) for l in r.stdout.splitlines()]
        self.assertEqual([o["id"] for o in out], [1, 2, 3, 4])
        self.assertEqual(out[0]["result"]["protocolVersion"], "2025-06-18")
        names = {t["name"] for t in out[1]["result"]["tools"]}
        self.assertTrue({"joebro_ping", "coding_agent_send", "joebro_plugin_install"} <= names)
        self.assertEqual(json.loads(out[2]["result"]["content"][0]["text"])["agents"][0]["status"], "running")
        self.assertIn("error", out[3])

    def test_plugin_init_then_push_sends_text_files(self):
        self.link()
        d = os.path.join(self.home, "my-plugin")
        r = self.run_cli("plugin", "init", "my-plugin", d)
        self.assertEqual(r.returncode, 0, r.stderr)
        m = json.load(open(os.path.join(d, "joebro-plugin.json")))
        self.assertEqual((m["schema"], m["id"]), ("joebro.plugin/1", "my-plugin"))
        os.makedirs(os.path.join(d, "__pycache__"))
        open(os.path.join(d, "__pycache__", "x.pyc"), "wb").write(b"\0")
        r = self.run_cli("plugin", "push", d)
        self.assertEqual(json.loads(r.stdout)["plugin"]["files"], ["joebro-plugin.json", "tools.py", "ui/index.html"])
        self.assertNotEqual(self.run_cli("plugin", "init", "Bad Id").returncode, 0)

    def test_install_merges_hooks_without_touching_others_and_uninstalls(self):
        os.makedirs(os.path.join(self.home, ".claude"))
        settings = os.path.join(self.home, ".claude", "settings.json")
        json.dump({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "/usr/bin/other-hook"}]}]}, "theme": "dark"},
                  open(settings, "w"))
        for _ in range(2):   # idempotent
            self.assertEqual(self.run_cli("install", "--claude").returncode, 0)
        d = json.load(open(settings))
        self.assertEqual(d["theme"], "dark")
        cmds = [h["command"] for g in d["hooks"]["Stop"] for h in g["hooks"]]
        self.assertEqual(cmds, ["/usr/bin/other-hook", os.path.join(self.home, ".local", "bin", "joebro-agents") + " report claude"])
        self.assertTrue(os.path.islink(os.path.join(self.home, ".local", "bin", "joebro-ping")))
        self.run_cli("install", "--claude", "--uninstall")
        d = json.load(open(settings))
        self.assertEqual([h["command"] for g in d["hooks"]["Stop"] for h in g["hooks"]], ["/usr/bin/other-hook"])
        self.assertNotIn("SessionStart", d["hooks"])


if __name__ == "__main__":
    unittest.main()
