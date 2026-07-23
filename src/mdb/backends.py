"""Optional authenticated extraction backends.

mdb's browser/compiler stays the default data plane.  This module is a
small, observable adapter boundary for pages that the native capture has
already classified as a wall or application shell.  External tools are
never installed or invoked implicitly: callers must select a backend or
enable fallback, and every returned bundle records its provenance.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable
from urllib.parse import parse_qs, urlparse

from . import EXTRACTOR_VERSION
from .reddit import is_reddit
from .x import is_x_status


class BackendError(RuntimeError):
    """A backend was unavailable, unsupported, or failed safely."""


@dataclass(frozen=True)
class Backend:
    name: str
    binary: str
    description: str
    install: str
    security: str


BACKENDS = {
    "opencli": Backend(
        name="opencli",
        binary="opencli",
        description="logged-in Chrome through the OpenCLI Browser Bridge",
        install="https://opencli.info/download",
        security="uses the active Chrome profile; the bridge can interact with pages",
    ),
    "twitter-cli": Backend(
        name="twitter-cli",
        binary="twitter",
        description="structured X data through authenticated private APIs",
        install="uv tool install twitter-cli",
        security="forwards X browser cookies to unofficial GraphQL endpoints",
    ),
}

_X_HOSTS = {"x.com", "www.x.com", "mobile.x.com",
            "twitter.com", "www.twitter.com", "mobile.twitter.com"}
_X_RESERVED = {
    "about", "compose", "download", "explore", "hashtag", "home", "i",
    "intent", "login", "logout", "messages", "notifications", "privacy",
    "search", "settings", "share", "tos",
}


def _x_route(url: str) -> tuple[str, str] | None:
    parsed = urlparse(url)
    if (parsed.hostname or "").lower() not in _X_HOSTS:
        return None
    tweet_id = is_x_status(url)
    if tweet_id:
        return "status", tweet_id
    path = parsed.path.strip("/")
    if path == "home":
        return "home", ""
    if path == "search":
        query = (parse_qs(parsed.query).get("q") or [""])[0].strip()
        return ("search", query) if query else None
    if (re.fullmatch(r"[A-Za-z0-9_]{1,15}", path)
            and path.lower() not in _X_RESERVED):
        return "profile", path
    return None


def command_for(url: str, backend: str) -> list[str] | None:
    """Return the read-only upstream command for this URL/backend pair."""
    x_route = _x_route(url)
    if backend == "opencli":
        if x_route:
            kind, value = x_route
            if kind == "status":
                return ["opencli", "twitter", "thread", value, "-f", "md"]
            if kind == "home":
                return ["opencli", "twitter", "timeline", "-f", "md"]
            if kind == "search":
                return ["opencli", "twitter", "search", value, "-f", "md"]
            if kind == "profile":
                return ["opencli", "twitter", "profile", value, "-f", "md"]
        parsed = urlparse(url)
        if is_reddit(parsed.hostname or "") and "/comments/" in parsed.path:
            return ["opencli", "reddit", "read", url, "-f", "md"]
    elif backend == "twitter-cli" and x_route:
        kind, value = x_route
        if kind == "status":
            return ["twitter", "tweet", url, "--json"]
        if kind == "home":
            return ["twitter", "feed", "--json"]
        if kind == "search":
            return ["twitter", "search", value, "--json"]
    return None


def supports(url: str, backend: str) -> bool:
    return command_for(url, backend) is not None


def installed(backend: str, which: Callable[[str], str | None] = shutil.which) -> bool:
    spec = BACKENDS.get(backend)
    return bool(spec and which(spec.binary))


def candidates(url: str, installed_only: bool = False) -> list[Backend]:
    """Supported backends in conservative preference order.

    OpenCLI comes first because it keeps authentication in the user's real
    Chrome session.  twitter-cli is richer for X, but exports cookies and
    impersonates private API traffic.
    """
    out = []
    for name in ("opencli", "twitter-cli"):
        if supports(url, name) and (not installed_only or installed(name)):
            out.append(BACKENDS[name])
    return out


def should_offer(url: str, manifest) -> bool:
    """Cheap OODA decision: only classified refusals on covered URLs."""
    return manifest.shape in ("wall", "app") and bool(candidates(url))


def _markdown_bundle(url: str, markdown: str, backend: str,
                     command: list[str], native_shape: str | None) -> dict:
    clean = markdown.strip()
    x_route = _x_route(url)
    if backend == "twitter-cli" and x_route:
        title = {
            "status": "X thread",
            "home": "X home timeline",
            "search": f"X search — {x_route[1]}",
        }.get(x_route[0], "X")
    else:
        title = ("Authenticated browser result"
                 if backend == "opencli" else "External result")
    return {
        "meta": {
            "url": url,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "mode": "external-authenticated",
            "extractor": EXTRACTOR_VERSION,
            "backend": backend,
            "backend_command": command,
            "fallback_reason": native_shape,
        },
        "doc": {
            "title": title,
            "lang": "",
            "textLen": len(re.sub(r"\s+", " ", clean)),
            "anchors": len(re.findall(r"\[[^\]]+\]\([^)]+\)", clean)),
            "interactive": 0,
            "blocks": [{
                "kind": "p",
                "landmark": "main",
                "md": clean,
                "text": "",
                "links": [],
                "images": [],
            }],
        },
    }


def _first(obj: dict, *names: str):
    for name in names:
        value = obj.get(name)
        if value not in (None, ""):
            return value
    return None


def _tweet_objects(value) -> list[dict]:
    """Find tweet-shaped objects without coupling to one schema revision."""
    found = []
    seen = set()

    def walk(node):
        if isinstance(node, dict):
            text = _first(node, "fullText", "full_text", "text", "articleText")
            ident = _first(node, "id", "id_str", "rest_id")
            if isinstance(text, str) and (ident or node.get("user") or node.get("author")):
                marker = (str(ident), text)
                if marker not in seen:
                    seen.add(marker)
                    found.append(node)
            for child in node.values():
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(value)
    return found


def _media_urls(value) -> list[str]:
    urls = []

    def walk(node):
        if isinstance(node, dict):
            for key in ("media_url_https", "mediaUrl", "image_url", "imageUrl"):
                candidate = node.get(key)
                if isinstance(candidate, str) and candidate.startswith("http"):
                    urls.append(candidate)
            for child in node.values():
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(value)
    return list(dict.fromkeys(urls))


def _md_text(value) -> str:
    return re.sub(r"([\\`*_\[\]])", r"\\\1", str(value or "")).strip()


def _twitter_markdown(payload: dict, url: str) -> str:
    if payload.get("ok") is False:
        error = payload.get("error") or {}
        raise BackendError(error.get("message") or error.get("code")
                           or "twitter-cli returned an error")
    data = payload.get("data", payload)
    tweets = _tweet_objects(data)
    if not tweets:
        raise BackendError("twitter-cli JSON contained no tweet-shaped data")

    route = _x_route(url)
    surface = route[0] if route else "status"
    if surface == "home":
        parts = ["# X home timeline"]
    elif surface == "search":
        parts = [f"# X search — {_md_text(route[1])}"]
    else:
        parts = []
    for index, tweet in enumerate(tweets):
        user = tweet.get("user") or tweet.get("author") or {}
        if not isinstance(user, dict):
            user = {}
        name = _first(user, "name", "displayName", "display_name") or ""
        handle = _first(user, "username", "screen_name", "screenName") or ""
        heading = " ".join(x for x in (_md_text(name),
                                        f"(@{_md_text(handle)})" if handle else "") if x)
        if surface == "status":
            if index == 0:
                parts.append(f"# {heading or 'X post'}")
            elif index == 1:
                parts.append("## Replies")
            if index:
                parts.append(f"### {heading or 'Reply'}")
        else:
            parts.append(f"## {heading or 'X post'}")
        text = _first(tweet, "articleText", "fullText", "full_text", "text")
        if text:
            parts.append(_md_text(text))
        for media_url in _media_urls(tweet):
            parts.append(f"![]({media_url})")
        ident = _first(tweet, "id", "id_str", "rest_id")
        if ident and index:
            parts.append(f"[View reply](https://x.com/i/web/status/{ident})")
    parts.append(f"[Open on X]({url})")
    return "\n\n".join(parts)


def capture(url: str, backend: str, native_shape: str | None = None,
            timeout: float = 45.0,
            runner: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> dict:
    """Run one explicitly selected, read-only adapter and normalize its result."""
    if backend not in BACKENDS:
        raise BackendError(f"unknown backend {backend!r}")
    command = command_for(url, backend)
    if command is None:
        raise BackendError(f"{backend} does not cover this URL")
    if not installed(backend):
        raise BackendError(
            f"{backend} is not installed; run `mdb setup backends` for instructions")
    try:
        result = runner(command, capture_output=True, text=True,
                        timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise BackendError(f"{backend} timed out after {timeout:g}s") from exc
    except OSError as exc:
        raise BackendError(f"could not start {backend}: {exc}") from exc
    if result.returncode:
        detail = (result.stderr or result.stdout or "no diagnostic").strip()
        raise BackendError(
            f"{backend} exited {result.returncode}: {detail[:300]}")
    if not result.stdout.strip():
        raise BackendError(f"{backend} returned an empty result")

    if backend == "twitter-cli":
        try:
            markdown = _twitter_markdown(json.loads(result.stdout), url)
        except json.JSONDecodeError as exc:
            raise BackendError("twitter-cli returned invalid JSON") from exc
    else:
        markdown = result.stdout
    return _markdown_bundle(url, markdown, backend, command, native_shape)


def offer_markdown(url: str, installed_only: bool = False) -> str:
    choices = candidates(url, installed_only=installed_only)
    if not choices:
        return ""
    lines = ["**Optional authenticated backends:**"]
    for spec in choices:
        state = "installed" if installed(spec.name) else "not installed"
        lines.append(f"- `{spec.name}` ({state}) — {spec.description}")
    lines.append("Run `mdb setup backends` for installation and security details.")
    return "\n".join(lines)


def setup_cli(argv: list[str]) -> int:
    if argv and argv != ["backends"]:
        print("usage: mdb setup backends")
        return 2
    print("Optional authenticated backends (never installed or invoked silently)\n")
    for spec in BACKENDS.values():
        state = "INSTALLED" if installed(spec.name) else "NOT INSTALLED"
        print(f"{spec.name:12} {state}")
        print(f"  enables:  {spec.description}")
        print(f"  install:  {spec.install}")
        print(f"  security: {spec.security}")
    print("\nStatus above detects binaries only, not login or adapter health. "
          "Run `opencli doctor` or `twitter status --json`, then verify the "
          "target site login before use. "
          "Select explicitly with --backend NAME, or opt in to "
          "--allow-external-fallback.")
    return 0
