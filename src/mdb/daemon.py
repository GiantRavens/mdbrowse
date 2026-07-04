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
IDLE_EXIT = float(os.environ.get("MDBROWSE_DAEMON_IDLE", "1800"))
_CAPTURE_TIMEOUT = 150.0


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------
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


def _spawn() -> bool:
    try:
        subprocess.Popen([sys.executable, "-m", "mdb.daemon"],
                         stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL,
                         start_new_session=True)
    except Exception:
        return False
    deadline = time.monotonic() + 6.0
    while time.monotonic() < deadline:
        if ping(0.3):
            return True
        time.sleep(0.15)
    return False


def capture_via_daemon(url: str, private: bool = False,
                       wait_selector: str = None):
    """Bundle from the daemon, auto-spawning it on first use.
    Returns None when the daemon path is unavailable/disabled (caller
    falls back to a local engine); raises on real page errors."""
    if os.environ.get("MDBROWSE_DAEMON", "auto").lower() in ("off", "never", "0"):
        return None
    for attempt in (0, 1):
        try:
            r = _request({"op": "capture", "url": url, "private": private,
                          "wait": wait_selector}, _CAPTURE_TIMEOUT)
        except (FileNotFoundError, ConnectionRefusedError, socket.timeout,
                ConnectionResetError):
            if attempt or not _spawn():
                return None
            continue
        except Exception:
            return None
        if r.get("ok"):
            return r["bundle"]
        raise RuntimeError(r.get("error", "daemon capture failed"))
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
    worker = EngineWorker()
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
                                "uptime": int(time.time() - started)}
                    elif op == "stop":
                        resp = {"ok": True, "stopping": True}
                        stopping = True
                    elif op == "capture":
                        bundle = worker.capture(req["url"],
                                                bool(req.get("private")),
                                                req.get("wait"))
                        resp = {"ok": True, "bundle": bundle}
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
        try:
            os.unlink(SOCK)
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
