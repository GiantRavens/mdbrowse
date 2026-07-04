"""Watch/diff sensors: versioned snapshots of pages, firing on real change.

Sensor-framework shape: each watched URL is a sensor; `mdb watch scan` is
the scan; each result is a reading (ok / changed / error) with the diff as
its sample and the snapshot path as its remediation pointer.

Store: a git repository (~/mdbrowse-watch, $MDBROWSE_WATCH_DIR). One
markdown document per watch, rewritten ONLY when content changes, then
committed — `git log -p <name>.md` is the page's full change history.

The change trigger is a **text hash**: the body with link/image URLs
stripped. Pages like HN rotate per-session auth tokens inside hrefs on
every fetch; hashing visible text means a watch fires when a reader would
say the page changed, never on URL churn. The stored snapshot itself keeps
full URLs (faithful); only the trigger ignores them.
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time

from .capture import Engine
from .classify import classify
from .emit import emit, emit_body

WATCH_DIR = os.path.expanduser(
    os.environ.get("MDBROWSE_WATCH_DIR", "~/mdbrowse-watch"))
_CONFIG = "watches.json"


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------
def _git(*args, check=True, capture=True):
    return subprocess.run(["git", "-C", WATCH_DIR, *args],
                          check=check, text=True,
                          capture_output=capture)


def _ensure_store():
    os.makedirs(WATCH_DIR, exist_ok=True)
    if not os.path.isdir(os.path.join(WATCH_DIR, ".git")):
        _git("init", "-q")


def _load():
    path = os.path.join(WATCH_DIR, _CONFIG)
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save(cfg):
    with open(os.path.join(WATCH_DIR, _CONFIG), "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=1, sort_keys=True)


def text_hash(body: str) -> str:
    """Hash of visible text: link/image URLs stripped, whitespace folded.
    Immune to per-session token churn inside hrefs."""
    t = re.sub(r"\]\([^)]*\)", "]", body)
    t = re.sub(r"\s+", " ", t)
    return hashlib.sha256(t.encode("utf-8")).hexdigest()[:16]


def _slug(url: str) -> str:
    from urllib.parse import urlparse
    p = urlparse(url)
    s = (p.netloc + "-" + p.path.strip("/").replace("/", "-"))
    s = re.sub(r"[^a-zA-Z0-9-]+", "-", s).strip("-").lower()
    return s[:60] or "page"


# ---------------------------------------------------------------------------
# Verbs
# ---------------------------------------------------------------------------
def _fetch(engine, url, private):
    bundle = engine.capture(url)
    manifest = classify(bundle)
    body = emit_body(bundle, manifest)
    return bundle, manifest, body


def add(url: str, name: str = None, private: bool = False) -> str:
    _ensure_store()
    cfg = _load()
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", url):
        url = "https://" + url
    name = name or _slug(url)
    if name in cfg:
        raise SystemExit(f"mdb watch: '{name}' already exists ({cfg[name]['url']})")
    with Engine(private=private) as eng:
        bundle, manifest, body = _fetch(eng, url, private)
    doc = emit(bundle, manifest)
    fname = f"{name}.md"
    with open(os.path.join(WATCH_DIR, fname), "w", encoding="utf-8") as f:
        f.write(doc)
    _git("add", fname)
    _git("commit", "-q", "-m", f"watch add: {name} ({bundle['meta']['url']})",
         check=False)
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    cfg[name] = {"url": bundle["meta"]["url"], "private": private,
                 "added": now, "last_checked": now, "last_changed": now,
                 "text_hash": text_hash(body)}
    _save(cfg)
    return name


def remove(name: str) -> None:
    cfg = _load()
    if name not in cfg:
        raise SystemExit(f"mdb watch: no watch named '{name}'")
    del cfg[name]
    _save(cfg)
    fname = f"{name}.md"
    if os.path.isfile(os.path.join(WATCH_DIR, fname)):
        _git("rm", "-q", fname, check=False)
        _git("commit", "-q", "-m", f"watch rm: {name}", check=False)


def scan(names=None, json_out: bool = False) -> int:
    """Fetch every watch, compare text hashes, commit + report changes.
    Exit code: 0 clean, 2 if any watch errored."""
    _ensure_store()
    cfg = _load()
    targets = {n: w for n, w in cfg.items() if not names or n in names}
    if not targets:
        print("mdb watch: nothing to scan (add one: mdb watch add URL)",
              file=sys.stderr)
        return 1

    readings, errors = [], 0
    with Engine() as eng_auth, Engine(private=True) as eng_priv:
        for name, w in sorted(targets.items()):
            now = time.strftime("%Y-%m-%dT%H:%M:%S")
            try:
                eng = eng_priv if w.get("private") else eng_auth
                bundle, manifest, body = _fetch(eng, w["url"], w.get("private"))
                th = text_hash(body)
                if th == w["text_hash"]:
                    w["last_checked"] = now
                    readings.append({"name": name, "status": "ok",
                                     "url": w["url"], "checked": now})
                    continue
                fname = f"{name}.md"
                with open(os.path.join(WATCH_DIR, fname), "w",
                          encoding="utf-8") as f:
                    f.write(emit(bundle, manifest))
                _git("add", fname)
                _git("commit", "-q", "-m",
                     f"{name}: changed ({w['url']})", check=False)
                stat = _git("show", "--stat", "--format=", "HEAD",
                            check=False).stdout.strip().split("\n")[-1].strip()
                sample = _diff_sample(fname)
                w.update(last_checked=now, last_changed=now, text_hash=th)
                readings.append({"name": name, "status": "changed",
                                 "url": w["url"], "checked": now,
                                 "stat": stat, "diff_sample": sample})
            except Exception as e:
                errors += 1
                readings.append({"name": name, "status": "error",
                                 "url": w["url"], "checked": now,
                                 "error": str(e)[:200]})
    _save(cfg)

    if json_out:
        print(json.dumps(readings, indent=1))
    else:
        for r in readings:
            if r["status"] == "ok":
                print(f"  {r['name']:28} ok         {r['url']}")
            elif r["status"] == "changed":
                print(f"  {r['name']:28} CHANGED    {r.get('stat', '')}")
                for line in r.get("diff_sample", [])[:12]:
                    print(f"      {line}")
                print(f"      full diff: mdb watch diff {r['name']}")
            else:
                print(f"  {r['name']:28} ERROR      {r['error']}")
        changed = sum(1 for r in readings if r["status"] == "changed")
        print(f"watch scan: {len(readings)} watched, {changed} changed, "
              f"{errors} errors")
    return 2 if errors else 0


def _diff_sample(fname: str, limit: int = 24):
    """Content lines of the last commit's diff for one file, front-matter
    churn excluded (retrieved/hash always move on a real change)."""
    out = _git("show", "--format=", "--unified=0", "HEAD", "--", fname,
               check=False).stdout
    lines = []
    for l in out.split("\n"):
        if not l or l.startswith(("+++", "---", "@@", "diff ", "index ")):
            continue
        if l[0] in "+-":
            if re.match(r"^[+-](retrieved|hash|extractor|confidence):", l):
                continue
            lines.append(l[:160])
        if len(lines) >= limit:
            break
    return lines


def diff(name: str) -> int:
    cfg = _load()
    if name not in cfg:
        raise SystemExit(f"mdb watch: no watch named '{name}'")
    r = _git("log", "-p", "--follow", "-1", "--format=commit %h  %ad  %s",
             "--date=format:%Y-%m-%d %H:%M", "--", f"{name}.md", check=False)
    print(r.stdout)
    return 0


def log(name: str) -> int:
    cfg = _load()
    if name not in cfg:
        raise SystemExit(f"mdb watch: no watch named '{name}'")
    r = _git("log", "--format=%h  %ad  %s",
             "--date=format:%Y-%m-%d %H:%M", "--", f"{name}.md", check=False)
    print(r.stdout.strip() or "(no history)")
    return 0


def digest(days: int = 7) -> int:
    """Morning-briefing material: what changed across all watches in the
    last N days, summarized by Claude from the git patches. Prints
    markdown — pipe it wherever the briefing lives."""
    from . import assist
    cfg = _load()
    if not cfg:
        print("watch digest: no watches configured")
        return 0
    chunks = []
    for name in sorted(cfg):
        patch = _git("log", f"--since={days} days ago", "-p", "--unified=0",
                     "--format=commit %ad  %s", "--date=format:%Y-%m-%d",
                     "--", f"{name}.md", check=False).stdout
        lines = [l for l in patch.split("\n")
                 if not re.match(r"^[+-](retrieved|hash|extractor|confidence):", l)]
        text = "\n".join(lines).strip()
        if text:
            chunks.append(f"## watch: {name} ({cfg[name]['url']})\n{text[:8000]}")
    if not chunks:
        print(f"watch digest: no changes in the last {days} days")
        return 0
    if not assist.available():
        print("watch digest: claude CLI not found", file=sys.stderr)
        return 1
    prompt = (
        "You are writing a morning-briefing item from web-page watch diffs "
        "(git patches of markdown page snapshots; deletions are old text, "
        "additions new). For each watch, say what actually changed in plain "
        "language — lead with the most significant change overall. If a "
        "watch shows only trivial churn, one short line. Plain markdown, "
        f"no preamble. Period: the last {days} days.")
    print(assist._run(prompt, "\n\n".join(chunks)[:50000]))
    return 0


def ls() -> int:
    cfg = _load()
    if not cfg:
        print("no watches. add one: mdb watch add URL [--name NAME]")
        return 0
    for name, w in sorted(cfg.items()):
        mode = "private" if w.get("private") else "auth"
        print(f"  {name:28} {mode:7} checked {w['last_checked']}  "
              f"changed {w['last_changed']}  {w['url']}")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def watch_cli(argv) -> int:
    ap = argparse.ArgumentParser(
        prog="mdb watch",
        description="Versioned page snapshots that fire on real content "
                    f"change. Store: {WATCH_DIR} (git; full history via "
                    "git log -p <name>.md).")
    sub = ap.add_subparsers(dest="verb", required=True)

    p = sub.add_parser("add", help="start watching a URL")
    p.add_argument("url")
    p.add_argument("--name", default=None)
    p.add_argument("--private", action="store_true")

    p = sub.add_parser("rm", help="stop watching")
    p.add_argument("name")

    p = sub.add_parser("scan", help="check all watches, commit + report changes")
    p.add_argument("names", nargs="*", help="limit to these watches")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("diff", help="show a watch's last change")
    p.add_argument("name")

    p = sub.add_parser("log", help="show a watch's change history")
    p.add_argument("name")

    p = sub.add_parser("digest", help="Claude-written summary of recent changes")
    p.add_argument("--days", type=int, default=7)

    sub.add_parser("ls", help="list watches")

    a = ap.parse_args(argv)
    if a.verb == "add":
        name = add(a.url, a.name, a.private)
        print(f"mdb watch: added '{name}' → {WATCH_DIR}/{name}.md")
        return 0
    if a.verb == "rm":
        remove(a.name)
        print(f"mdb watch: removed '{a.name}'")
        return 0
    if a.verb == "scan":
        return scan(a.names or None, json_out=a.json)
    if a.verb == "diff":
        return diff(a.name)
    if a.verb == "log":
        return log(a.name)
    if a.verb == "digest":
        return digest(a.days)
    if a.verb == "ls":
        return ls()
    return 1
