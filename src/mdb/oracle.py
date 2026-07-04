"""Fidelity oracle: the screenshot as judge, never as extractor.

The founding insight of the v2 rebuild, closing its loop: the rendered
pixels are the ground truth of what a page showed. The compiler's output
is checked AGAINST them — capture once with a full-page screenshot, then
have Claude (via `claude -p`, which Reads the PNG) compare the markdown
to the pixels and report what the extraction missed, mangled, or
misordered.

This is telemetry, not pipeline: it runs on demand (`mdb oracle URL`),
costs a model call, and its findings feed the fixture corpus — a page
that scores badly becomes a fixture, the fix is measured, the score
re-run. Predicted vs actual, per the honing doctrine.
"""

import os
import re
import subprocess
import sys
import time

from .capture import Engine
from .classify import classify
from .emit import emit_body

ORACLE_DIR = os.path.join(
    os.path.expanduser(os.environ.get("MDBROWSE_RUNTIME", "~/.mdb")), "oracle")
BODY_CAP = 60_000
TIMEOUT = 300.0

PROMPT = """\
You are the fidelity oracle for mdbrowse, a web -> markdown compiler.
First use the Read tool on the full-page screenshot at: {png}
Then compare it against the compiled markdown, which arrives on stdin.

The compiler DELIBERATELY drops these — do not penalize them:
styling/layout/colors, ads, cookie banners, consent chrome, images
(rendered as links/markers), navigation menus (demoted to link lists at
the end), and interactive widgets.

Judge CONTENT fidelity only:
- missing: headlines, stories, body text, list items visible in the
  screenshot but absent from the markdown
- mangled: glued words, broken headings, wrong titles, garbled text
- misordered: content whose reading order contradicts the page
- shape: the compiler classified this page as "{shape}" — is that right?

Report in exactly this format:
score: N/10
shape_verdict: correct | wrong (should be X)
missing:
- item (or "- none")
mangled:
- item (or "- none")
misordered:
- item (or "- none")
verdict: one plain sentence for the log.
"""


def _slug(url: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "-", url).strip("-")[:60] or "page"


def run(url: str, private: bool = False) -> int:
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", url):
        url = "https://" + url
    os.makedirs(ORACLE_DIR, exist_ok=True)
    png = os.path.join(ORACLE_DIR, f"{_slug(url)}.png")

    t0 = time.monotonic()
    with Engine(private=private) as eng:
        bundle = eng.capture(url, screenshot_path=png)
    manifest = classify(bundle)
    body = emit_body(bundle, manifest)
    cap_s = time.monotonic() - t0

    print(f"oracle: captured {bundle['meta']['url']} "
          f"(shape={manifest.shape} conf={manifest.confidence}, {cap_s:.1f}s)")
    print(f"oracle: screenshot {png} "
          f"({os.path.getsize(png) // 1024} KB); judging via claude -p …")

    r = subprocess.run(
        ["claude", "-p", PROMPT.format(png=png, shape=manifest.shape),
         "--allowedTools", "Read"],
        input=body[:BODY_CAP], capture_output=True, text=True, timeout=TIMEOUT)
    if r.returncode != 0 or not r.stdout.strip():
        print(f"oracle: judge failed: {(r.stderr or r.stdout)[:300]}",
              file=sys.stderr)
        return 1
    print()
    print(r.stdout.strip())
    return 0


def oracle_cli(argv) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        prog="mdb oracle",
        description="Judge markdown fidelity against a full-page screenshot "
                    "(pixels as judge, never as extractor).")
    ap.add_argument("url")
    ap.add_argument("--private", action="store_true")
    a = ap.parse_args(argv)
    return run(a.url, private=a.private)
