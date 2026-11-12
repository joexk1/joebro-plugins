#!/usr/bin/env python3
"""Just enough tmux for the tests when it is not installed: new-session -d -s NAME -c DIR [-e K=V]... cmd..., has-session, kill-session."""
import os, signal, subprocess, sys
state = os.environ["FAKE_TMUX_DIR"]
os.makedirs(state, exist_ok=True)
a = sys.argv[1:]
if a[0] == "new-session":
    name = cwd = None
    env = dict(os.environ)
    i = 1
    while i < len(a) and a[i].startswith("-"):
        if a[i] == "-s": name = a[i + 1]; i += 2
        elif a[i] == "-c": cwd = a[i + 1]; i += 2
        elif a[i] == "-e": k, v = a[i + 1].split("=", 1); env[k] = v; i += 2
        else: i += 1
    p = subprocess.Popen(a[i:], cwd=cwd, env=env, start_new_session=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    open(os.path.join(state, name), "w").write(str(p.pid))
    sys.exit(0)
name = a[a.index("-t") + 1]
f = os.path.join(state, name)
if a[0] == "has-session":
    try:
        pid = int(open(f).read()); os.kill(pid, 0)
        # a finished-but-unreaped child still answers kill 0; treat zombies as gone
        sys.exit(1 if open("/proc/%d/stat" % pid).read().split()[2] == "Z" else 0)
    except (OSError, ValueError):
        sys.exit(1)
if a[0] == "kill-session":
    try: os.killpg(int(open(f).read()), signal.SIGKILL)
    except (OSError, ValueError): pass
    sys.exit(0)
