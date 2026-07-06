"""Per-host element policy — the empathymachine idea applied to capture.

mdb already blocks tracker HOSTS (capture.TRACKER_HOSTS — the blocklist
idea). This layer handles what host-blocking can't touch: first-party
page furniture a research/reading tool has no reason to render —
promoted posts and ad slots served from the site's own DOM. Borrowed
shape: rules are declarative, per-host, and carry their WHY (every rule
is explainable, empathymachine-style); the walker skips matching
elements at capture; the kill count travels in bundle meta and
front-matter as policy_killed, so removal is visible telemetry, never
silent editing.

This is a reader's-choice layer, not stealth: it removes paid slotting
from a page the user is reading as text, exactly as reader modes do.

User rules: ~/.mdb/policy.json — {"host.com": ["selector", ...]} —
merge over the builtins (same host key extends; new keys add).
MDBROWSE_NO_POLICY=1 disables the whole layer.
"""

import json
import os

# Every entry names its evidence. Selectors are verified against the
# live site the day they land; the site probe that found them is the
# citation. Keep this list small and certain — over-broad selectors
# silently eat content, which is worse than showing an ad.
BUILTIN = {
    "reddit.com": {
        "kill": ["shreddit-ad-post", "shreddit-dynamic-ad-link",
                 "shreddit-comments-page-ad", "[data-promoted=\"true\"]"],
        "note": "promoted posts + ad links (56 elements on one front page, "
                "probed 2026-07-05)",
    },
    "*": {
        "kill": ["ins.adsbygoogle"],
        "note": "AdSense slots are unambiguous by contract",
    },
}

# Hosts that serve THIN content to a phone UA — the coverage lever.
# We present iPhone Safari by default (small pages, Safari cookies read
# naturally), but some sites collapse, truncate, or redirect their
# mobile view to a fraction of the desktop page. For these, capture with
# a desktop UA + viewport instead. Each entry names what desktop buys.
DESKTOP_HOSTS = {
    "wikipedia.org": "Minerva mobile skin lazy-collapses section bodies "
                     "(~1150 vs ~7000 chars); desktop serves them inline",
    "wikimedia.org": "same Minerva skin across the Wikimedia family",
    "wiktionary.org": "same Minerva skin",
    "stackoverflow.com": "mobile view truncates answers and hides the "
                         "sidebar of linked/related questions",
    "stackexchange.com": "same mobile truncation across the network",
    "reddit.com": "mobile web is a login-walled SPA stub; desktop old-"
                  "style renders threads as text",
}

_USER_PATH = os.path.expanduser(
    os.environ.get("MDBROWSE_POLICY", "~/.mdb/policy.json"))


def _user_data() -> dict:
    try:
        with open(_USER_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _user_rules() -> dict:
    return {h: v if isinstance(v, list) else v.get("kill", [])
            for h, v in _user_data().items() if h != "_desktop"}


def wants_desktop(host: str) -> bool:
    """True when this host is served better with a desktop UA. Builtins
    plus a user list under the reserved "_desktop" key in policy.json
    (e.g. {"_desktop": ["example.com"]}). MDBROWSE_NO_POLICY disables."""
    if os.environ.get("MDBROWSE_NO_POLICY"):
        return False
    host = (host or "").lower()
    user = _user_data().get("_desktop") or []
    hosts = set(DESKTOP_HOSTS) | {h.lower() for h in user}
    return any(host == h or host.endswith("." + h) for h in hosts)


def kill_selectors(host: str) -> list:
    """Effective kill selectors for a host: builtins + user rules, host
    matched by suffix (reddit.com covers www/old/np subdomains)."""
    if os.environ.get("MDBROWSE_NO_POLICY"):
        return []
    host = (host or "").lower()
    out = []
    merged = {h: list(v["kill"]) for h, v in BUILTIN.items()}
    for h, sels in _user_rules().items():
        merged.setdefault(h, [])
        merged[h] += [s for s in sels if s not in merged[h]]
    for h, sels in merged.items():
        if h == "*" or host == h or host.endswith("." + h):
            out += [s for s in sels if s not in out]
    return out
