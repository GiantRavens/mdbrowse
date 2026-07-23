"""Engine daemon: warm Chromium behind a Unix socket — sub-second CLI.

One-shot `mdb URL` invocations pay the Chromium launch (~2-4s) every
time. The daemon holds warm engines (authenticated + private) behind
~/.mdb/engine.sock; the CLI's capture() tries the socket first and
auto-spawns the daemon on first use. Long-lived surfaces (reader, watch
scans, MCP) keep their own warm engines and never touch this.

Protocol: one connection per request; client sends a JSON object and
half-closes; server replies with one JSON object and closes. Page
errors travel back as errors — the client re-raises rather than
silently re-fetching, so diagnoses (DNS preflight!) surface once.

Lifecycle: exits after MDBROWSE_DAEMON_IDLE seconds (default 1800)
without a request — no zombie Chromium. MDBROWSE_DAEMON=off disables
daemon use entirely.
"""

import json
import os
import socket
import subprocess
import sys
import time

RUNTIME_DIR = os.path.expanduser(os.environ.get("MDBROWSE_RUNTIME", "~/.mdb"))
SOCK = os.path.join(RUNTIME_DIR, "engine.sock")
PIDFILE = os.path.join(RUNTIME_DIR, "engine.pid")
IDLE_EXIT = float(os.environ.get("MDBROWSE_DAEMON_IDLE", "1800"))

# Timeout ladder: the server's worker gives up at 40s (page budget 30s
# plus settle slack) and REPLIES with the error; the client waits 50s —
# always longer than the server's own cap, so "stuck loading" cannot
# outlive one page budget. The server is single-threaded per request: a
# wedged capture used to hold every later call (pings included) hostage
# for the old 150s client timeout.
_SERVER_CAPTURE_TIMEOUT = 40.0
_CAPTURE_TIMEOUT = 50.0


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------
def _code_stamp() -> int:
    """Newest mtime across the package's source files. A daemon whose
    stamp differs from the client's is running different code — version
    bump or not. The extractor version alone missed exactly this: a
    same-version daemon serving hours-old behavior."""
    root = os.path.dirname(os.path.abspath(__file__))
    newest = 0
    try:
        for name in os.listdir(root):
            if name.endswith((".py", ".js")):
                st = os.stat(os.path.join(root, name))
                newest = max(newest, int(st.st_mtime))
    except OSError:
        pass
    return newest


def _request(payload: dict, timeout: float):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect(SOCK)
        s.sendall(json.dumps(payload).encode("utf-8"))
        s.shutdown(socket.SHUT_WR)
        buf = b""
        while True:
            chunk = s.recv(1 << 16)
            if not chunk:
                break
            buf += chunk
        return json.loads(buf.decode("utf-8"))
    finally:
        s.close()


def ping(timeout: float = 0.5):
    try:
        r = _request({"op": "ping"}, timeout)
        return r if r.get("ok") else None
    except Exception:
        return None


def _spawn(expected_stamp: int = None) -> bool:
    try:
        subprocess.Popen([sys.executable, "-m", "mdb.daemon"],
                         stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL,
                         start_new_session=True)
    except Exception:
        return False
    deadline = time.monotonic() + 6.0
    while time.monotonic() < deadline:
        generation = ping(0.3)
        if generation and (
                expected_stamp is None
                or generation.get("stamp") == expected_stamp):
            return True
        time.sleep(0.15)
    return False


def _force_kill() -> None:
    """A daemon that can't answer inside the client timeout is wedged
    (its worker already had 40s to reply with an error). Kill it by
    pidfile and clear the socket so the next spawn starts clean."""
    import signal
    try:
        with open(PIDFILE, encoding="utf-8") as f:
            os.kill(int(f.read().strip()), signal.SIGKILL)
    except (OSError, ValueError):
        pass
    for path in (SOCK, PIDFILE):
        try:
            os.unlink(path)
        except OSError:
            pass


def _stop_and_wait(timeout: float = 6.0) -> bool:
    """Stop the current generation and wait until its PID is truly gone.

    A stop acknowledgement only means the server loop set `stopping=True`;
    EngineWorker still has to close Chromium. Spawning during that window can
    ping the old socket, mistake it for the new generation, and then return a
    second stale bundle. Worse, the old process can unlink the new socket in
    its finally block. PID exit is the generation boundary.
    """
    generation = ping(0.5)
    if not generation:
        return True
    pid = generation.get("pid")
    if not isinstance(pid, int):
        return False
    try:
        _request({"op": "stop"}, 5.0)
    except Exception:
        try:
            os.kill(pid, 9)
        except OSError:
            pass

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except OSError:
            return True
        time.sleep(0.05)

    try:
        os.kill(pid, 9)
    except OSError:
        return True
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except OSError:
            return True
        time.sleep(0.05)
    return False


def capture_via_daemon(url: str, private: bool = False,
                       wait_selector: str = None, desktop: bool = False):
    """Bundle from the daemon, auto-spawning it on first use.
    Returns None when the daemon path is unavailable/disabled (caller
    falls back to a local engine); raises on real page errors.

    Two recovery rules learned in the field: a client-side timeout
    means the daemon is WEDGED (kill it, respawn once); a bundle
    carrying the wrong extractor version means the daemon is STALE —
    code moved under a running process (restart it, recapture). Both
    were 'works after restart' bugs until the restart became automatic.
    """
    if os.environ.get("MDBROWSE_DAEMON", "auto").lower() in ("off", "never", "0"):
        return None
    from . import EXTRACTOR_VERSION
    for attempt in (0, 1):
        try:
            r = _request({"op": "capture", "url": url, "private": private,
                          "wait": wait_selector, "desktop": desktop},
                         _CAPTURE_TIMEOUT)
        except socket.timeout:
            _force_kill()
            if attempt or not _spawn():
                return None
            continue
        except (FileNotFoundError, ConnectionRefusedError,
                ConnectionResetError):
            if attempt or not _spawn():
                return None
            continue
        except Exception:
            return None
        if not r.get("ok"):
            raise RuntimeError(r.get("error", "daemon capture failed"))
        bundle = r["bundle"]
        served = bundle.get("meta", {}).get("extractor")
        stale = (served != EXTRACTOR_VERSION
                 or r.get("stamp") != _code_stamp())
        if stale:
            if not attempt:
                print(f"mdb: daemon is stale (code moved under it); "
                      f"restarting", file=sys.stderr)
                expected = _code_stamp()
                if _stop_and_wait() and _spawn(expected):
                    continue
            # Never serve a bundle known to come from the wrong generation.
            # None makes capture() fall back to a fresh local Engine.
            return None
        return bundle
    return None


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------
def serve() -> int:
    from .capture import EngineWorker
    os.makedirs(RUNTIME_DIR, exist_ok=True)
    if os.path.exists(SOCK):
        if ping(0.5):
            print("mdb daemon: already running", file=sys.stderr)
            return 1
        os.unlink(SOCK)                    # stale socket from a dead daemon

    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(SOCK)
    srv.listen(8)
    srv.settimeout(5.0)
    with open(PIDFILE, "w", encoding="utf-8") as f:
        f.write(str(os.getpid()))
    worker = EngineWorker()
    stamp = _code_stamp()          # what code THIS process is running
    started = time.time()
    last = time.monotonic()
    stopping = False
    try:
        while not stopping:
            try:
                conn, _ = srv.accept()
            except socket.timeout:
                if time.monotonic() - last > IDLE_EXIT:
                    break
                continue
            last = time.monotonic()
            with conn:
                buf = b""
                try:
                    conn.settimeout(10.0)
                    while True:
                        chunk = conn.recv(1 << 16)
                        if not chunk:
                            break
                        buf += chunk
                    req = json.loads(buf.decode("utf-8"))
                    op = req.get("op")
                    if op == "ping":
                        resp = {"ok": True, "pid": os.getpid(),
                                "uptime": int(time.time() - started),
                                "stamp": stamp}
                    elif op == "stop":
                        resp = {"ok": True, "stopping": True}
                        stopping = True
                    elif op == "capture":
                        bundle = worker.capture(req["url"],
                                                bool(req.get("private")),
                                                req.get("wait"),
                                                timeout=_SERVER_CAPTURE_TIMEOUT,
                                                desktop=bool(req.get("desktop")))
                        resp = {"ok": True, "bundle": bundle,
                                "stamp": stamp}
                    else:
                        resp = {"ok": False, "error": f"unknown op {op!r}"}
                except Exception as e:
                    resp = {"ok": False, "error": str(e)[:500]}
                try:
                    conn.sendall(json.dumps(resp).encode("utf-8"))
                except Exception:
                    pass
    finally:
        worker.close()
        srv.close()
        for path in (SOCK, PIDFILE):
            try:
                os.unlink(path)
            except OSError:
                pass
    return 0


# ---------------------------------------------------------------------------
# CLI: mdb daemon start | stop | status | run
# ---------------------------------------------------------------------------
def daemon_cli(argv) -> int:
    verb = argv[0] if argv else "status"
    if verb == "run":                      # foreground (launchd-friendly)
        return serve()
    if verb == "start":
        if ping(0.5):
            print("mdb daemon: already running")
            return 0
        ok = _spawn()
        print("mdb daemon: started" if ok else "mdb daemon: failed to start")
        return 0 if ok else 1
    if verb == "stop":
        try:
            _request({"op": "stop"}, 5.0)
            print("mdb daemon: stopped")
        except Exception:
            print("mdb daemon: not running")
        return 0
    if verb == "status":
        r = ping(0.5)
        if r:
            print(f"mdb daemon: running (pid {r['pid']}, up {r['uptime']}s, "
                  f"socket {SOCK})")
        else:
            print("mdb daemon: not running")
        return 0
    print("usage: mdb daemon [start|stop|status|run]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(serve())
