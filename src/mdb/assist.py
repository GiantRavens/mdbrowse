"""LLM assist: the page, questioned — via the `claude` CLI.

Bridges the reader to Claude Code headless mode (`claude -p`): the page
body rides stdin, the instruction rides the argument, the user's existing
Claude Code auth rides along for free — no API key plumbing.

Answers come back as markdown and are displayed as synthetic PAGES in the
reader, so every existing verb works on them: scroll, search, speak (v),
archive (s), back (H). An LLM answer is just another document.
"""

import shutil
import subprocess

BODY_CAP = 60_000        # chars of page fed to the model
TIMEOUT = 180.0

SUMMARIZE = (
    "You are inside mdbrowse, a terminal markdown browser. The user is "
    "reading the page whose compiled markdown arrives on stdin. Write a "
    "tight summary: two to four sentences, then up to six bullet key "
    "points (most load-bearing facts first). Plain markdown, no preamble, "
    "no code fences around the whole answer."
)

ASK = (
    "You are inside mdbrowse, a terminal markdown browser. The user is "
    "reading the page whose compiled markdown arrives on stdin. Answer "
    "their question from the page's content; when the page does not "
    "contain the answer, say so plainly before adding anything else. "
    "Plain markdown, no preamble. Question: {q}"
)


def available() -> bool:
    return shutil.which("claude") is not None


def _run(instruction: str, body_md: str) -> str:
    r = subprocess.run(
        ["claude", "-p", instruction],
        input=body_md[:BODY_CAP],
        capture_output=True, text=True, timeout=TIMEOUT,
    )
    if r.returncode != 0:
        err = (r.stderr or r.stdout or "").strip()[:200]
        raise RuntimeError(f"claude -p failed: {err or 'no output'}")
    out = r.stdout.strip()
    if not out:
        raise RuntimeError("claude -p returned nothing")
    return out


def summarize(body_md: str, url: str = "") -> str:
    header = f"(page source: {url})\n\n" if url else ""
    return _run(SUMMARIZE, header + body_md)


def ask(body_md: str, question: str, url: str = "") -> str:
    header = f"(page source: {url})\n\n" if url else ""
    return _run(ASK.format(q=question.strip()), header + body_md)
