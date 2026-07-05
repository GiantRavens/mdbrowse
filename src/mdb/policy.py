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

_USER_PATH = os.path.expanduser(
    os.environ.get("MDBROWSE_POLICY", "~/.mdb/policy.json"))


def _user_rules() -> dict:
    try:
        with open(_USER_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return {h: v if isinstance(v, list) else v.get("kill", [])
                for h, v in data.items()}
    except (OSError, ValueError):
        return {}


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
