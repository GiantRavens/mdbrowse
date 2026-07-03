"""mdb CLI — thin frontend over capture -> classify -> emit.

Every stage is dumpable (--dump bundle|manifest|body) so a bad page is
diagnosed by inspecting the intermediate, not by rereading heuristics.

Fixtures: `mdb URL --fixture NAME` saves the capture bundle plus golden
body markdown under tests/fixtures/. `mdb --selftest` re-emits every saved
bundle offline and diffs against the golden — classify/emit changes are
measured, never vibes.
"""

import argparse
import datetime
import difflib
import glob
import json
import os
import re
import sys

from . import EXTRACTOR_VERSION
from . import bundle as bundle_io
from .capture import capture
from .classify import classify
from .emit import emit, emit_body
from .render import render

ARCHIVE_DIR = os.path.expanduser(os.environ.get("MDBROWSE_ARCHIVE", "~/mdbrowse-archive"))
FIXTURE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "tests", "fixtures")


def _err(msg: str) -> None:
    print(f"mdb: {msg}", file=sys.stderr)


def _normalize_url(url: str) -> str:
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", url):
        url = "https://" + url
    return url


def _slugify(s: str, maxlen: int = 60) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    return s[:maxlen].strip("-") or "page"


def _save_archive(doc_md: str, title: str, url: str) -> str:
    from urllib.parse import urlparse
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    now = datetime.datetime.now()
    host = urlparse(url).netloc or "local"
    fname = f"{now.strftime('%Y%m%d-%H%M%S')}-{_slugify(host + '-' + title)}.md"
    path = os.path.join(ARCHIVE_DIR, fname)
    with open(path, "w", encoding="utf-8") as f:
        f.write(doc_md)
    return path


def _strip_front_matter(doc_md: str) -> str:
    m = re.match(r"(?s)^---\n.*?\n---\n\n?", doc_md)
    return doc_md[m.end():] if m else doc_md


def selftest(update: bool = False) -> int:
    bundles = sorted(glob.glob(os.path.join(FIXTURE_DIR, "*.bundle.json")))
    if not bundles:
        _err(f"no fixtures in {FIXTURE_DIR} — capture some with: "
             "mdb URL --fixture NAME")
        return 1
    failures = 0
    for bpath in bundles:
        name = os.path.basename(bpath)[:-len(".bundle.json")]
        gpath = os.path.join(FIXTURE_DIR, f"{name}.golden.md")
        b = bundle_io.load(bpath)
        manifest = classify(b)
        body = emit_body(b, manifest)
        got = f"<!-- shape: {manifest.shape} -->\n{body}\n"
        if update or not os.path.exists(gpath):
            with open(gpath, "w", encoding="utf-8") as f:
                f.write(got)
            print(f"  {name}: golden {'updated' if update else 'created'} "
                  f"(shape={manifest.shape})")
            continue
        with open(gpath, encoding="utf-8") as f:
            want = f.read()
        if got == want:
            print(f"  {name}: OK (shape={manifest.shape})")
        else:
            failures += 1
            print(f"  {name}: FAIL (shape={manifest.shape})")
            diff = difflib.unified_diff(
                want.splitlines(True), got.splitlines(True),
                fromfile=f"{name}.golden.md", tofile=f"{name} (current)")
            sys.stdout.writelines(list(diff)[:60])
    total = len(bundles)
    print(f"selftest: {total - failures}/{total} fixtures match")
    return 1 if failures else 0


def main() -> None:
    ap = argparse.ArgumentParser(
        prog="mdb",
        description="Web -> deterministic markdown compiler (mdbrowse v2).")
    ap.add_argument("url", nargs="?", help="page to compile")
    ap.add_argument("--private", "--anonymous", dest="private",
                    action="store_true",
                    help="send no Safari cookies; add DNT/Sec-GPC")
    ap.add_argument("--wait", metavar="SELECTOR", default=None,
                    help="wait for this CSS selector before capturing")
    ap.add_argument("--raw", action="store_true",
                    help="print the full markdown document (front-matter + body)")
    ap.add_argument("--dump", choices=["bundle", "manifest", "body"],
                    help="print a pipeline intermediate and exit")
    ap.add_argument("--save", action="store_true",
                    help=f"archive the document (to {ARCHIVE_DIR})")
    ap.add_argument("--fixture", metavar="NAME",
                    help="save capture bundle + golden body to tests/fixtures/")
    ap.add_argument("--selftest", action="store_true",
                    help="re-emit all fixtures offline, diff against goldens")
    ap.add_argument("--update-goldens", action="store_true",
                    help="with --selftest: rewrite goldens from current output")
    ap.add_argument("--width", type=int, default=0)
    ap.add_argument("--no-pager", action="store_true")
    ap.add_argument("--version", action="version",
                    version=f"mdb {EXTRACTOR_VERSION}")
    args = ap.parse_args()

    if args.selftest:
        sys.exit(selftest(update=args.update_goldens))

    if not args.url:
        ap.error("a URL is required (or --selftest)")

    url = _normalize_url(args.url)
    try:
        b = capture(url, private=args.private, wait_selector=args.wait)
    except Exception as e:
        _err(f"could not capture {url}: {e}")
        sys.exit(1)

    manifest = classify(b)

    if args.dump == "bundle":
        json.dump(b, sys.stdout, ensure_ascii=False, indent=1)
        print()
        return
    if args.dump == "manifest":
        json.dump({"shape": manifest.shape, "confidence": manifest.confidence,
                   "signals": manifest.signals}, sys.stdout, indent=2)
        print()
        return

    doc_md = emit(b, manifest)
    body = _strip_front_matter(doc_md)

    if args.dump == "body":
        print(body)
        return

    if args.fixture:
        os.makedirs(FIXTURE_DIR, exist_ok=True)
        bpath = os.path.join(FIXTURE_DIR, f"{args.fixture}.bundle.json")
        gpath = os.path.join(FIXTURE_DIR, f"{args.fixture}.golden.md")
        bundle_io.save(b, bpath)
        with open(gpath, "w", encoding="utf-8") as f:
            f.write(f"<!-- shape: {manifest.shape} -->\n"
                    + emit_body(b, manifest) + "\n")
        print(f"mdb: fixture saved -> {bpath}")
        print(f"mdb: golden saved  -> {gpath}  (shape={manifest.shape}, "
              f"confidence={manifest.confidence})")
        return

    if args.save:
        path = _save_archive(doc_md, b["doc"].get("title") or url, url)
        print(f"mdb: saved archive -> {path}")
        if not args.raw:
            return

    if args.raw:
        print(doc_md)
        return

    render(body, b["meta"]["url"], width=args.width,
           use_pager=not args.no_pager)


if __name__ == "__main__":
    main()
