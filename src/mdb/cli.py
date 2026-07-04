"""mdb CLI — thin frontend over capture -> classify -> emit.

Every stage is dumpable (--dump bundle|manifest|body) so a bad page is
diagnosed by inspecting the intermediate, not by rereading heuristics.

Fixtures: `mdb URL --fixture NAME` saves the capture bundle plus golden
body markdown under tests/fixtures/. `mdb --selftest` re-emits every saved
bundle offline and diffs against the golden — classify/emit changes are
measured, never vibes.
"""

import argparse
import difflib
import glob
import json
import os
import re
import sys

from . import EXTRACTOR_VERSION
from . import bundle as bundle_io
from .archive import ARCHIVE_DIR, save_archive
from .capture import capture
from .classify import classify
from .emit import emit, emit_body
from .render import render

FIXTURE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "tests", "fixtures")


def _err(msg: str) -> None:
    print(f"mdb: {msg}", file=sys.stderr)


def _normalize_url(url: str) -> str:
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", url):
        url = "https://" + url
    return url


def _speak_body(body_md: str, voice, out_path=None) -> int:
    from .reader import parse_body
    from . import speech
    text = speech.from_llines(parse_body(body_md)[0])
    if not text.strip():
        _err("nothing to speak")
        return 1
    if out_path:
        ok = speech.render_to_file(text, os.path.expanduser(out_path), voice)
        print(f"mdb: speech rendered -> {out_path}" if ok
              else "mdb: speech render failed")
        return 0 if ok else 1
    print("mdb: speaking… (Ctrl-C stops)")
    proc = speech.speak(text, voice)
    try:
        proc.wait()
    except KeyboardInterrupt:
        speech.stop(proc)
        print()
    return 0


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
    # Subcommand dispatch before flag parsing: `mdb watch ...`, `mdb get ...`
    if len(sys.argv) > 1 and sys.argv[1] == "watch":
        from .watch import watch_cli
        sys.exit(watch_cli(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "get":
        from .download import get_cli
        sys.exit(get_cli(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] in ("ddg", "search"):
        # `mdb ddg rust atomics` -> rewrite argv to the results URL and fall
        # through to the normal pipeline, so every flag still applies.
        from .search import ddg_url, search_url
        rest = sys.argv[2:]
        cut = next((i for i, a in enumerate(rest) if a.startswith("-")),
                   len(rest))
        terms, flags = rest[:cut], rest[cut:]
        if not terms:
            print("mdb: search needs query terms", file=sys.stderr)
            sys.exit(2)
        build = ddg_url if sys.argv[1] == "ddg" else search_url
        sys.argv = [sys.argv[0], build(" ".join(terms))] + flags

    ap = argparse.ArgumentParser(
        prog="mdb",
        description="Web -> deterministic markdown compiler (mdbrowse v2).")
    ap.add_argument("url", nargs="?",
                    help="page to compile (omit for the Safari start page)")
    ap.add_argument("--start", action="store_true",
                    help="Safari start page (homepage + reading list + bookmarks)")
    ap.add_argument("--bookmarks", action="store_true",
                    help="browse your Safari bookmarks")
    ap.add_argument("--reading-list", dest="reading_list", action="store_true",
                    help="browse your Safari reading list")
    ap.add_argument("--browse", action="store_true",
                    help="force the interactive reader (already the default "
                         "in a terminal)")
    ap.add_argument("--plain", action="store_true",
                    help="non-interactive render through the pager instead "
                         "of the reader (default when output is piped)")
    ap.add_argument("--no-center", dest="center", action="store_false",
                    help="left-align the plain render instead of the "
                         "Goyo-style centered column")
    ap.add_argument("--speak", action="store_true",
                    help="speak the page aloud (macOS say; Ctrl-C stops)")
    ap.add_argument("--speak-out", metavar="AUDIO_FILE", default=None,
                    help="render speech to an audio file instead of playing")
    ap.add_argument("--voice", default=None,
                    help="say voice name (or MDBROWSE_VOICE)")
    ap.add_argument("--announce", action="store_true",
                    help="in the reader, speak each element as focus lands on it")
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

    interactive = sys.stdout.isatty() and sys.stdin.isatty()

    # Resolve the target. Safari flags -> pseudo-pages; no URL at all ->
    # the Safari start page (mdb with no arguments is your front door).
    if args.bookmarks:
        url = "safari:bookmarks"
    elif args.reading_list:
        url = "safari:reading"
    elif args.start or not args.url:
        url = "safari:start"
    elif args.url.startswith("safari:"):
        url = args.url
    else:
        url = _normalize_url(args.url)

    # Safari pseudo-pages need no engine: emit directly for non-browse paths.
    if url.startswith("safari:"):
        from .safari import page_markdown
        if args.speak or args.speak_out:
            sys.exit(_speak_body(page_markdown(url.split(":", 1)[1] or "start"),
                                 args.voice, args.speak_out))
        if args.raw or args.dump == "body" or args.plain or not interactive:
            md = page_markdown(url.split(":", 1)[1] or "start")
            if args.raw or args.dump == "body" or not interactive:
                print(md)
            else:
                render(md, url, width=args.width,
                       use_pager=not args.no_pager, center=args.center)
            return
        from .reader import browse
        browse(url, private=args.private, width=args.width)
        return

    # In a terminal, mdb IS a browser: the interactive reader is the default.
    # Piped output, --plain, and the non-view verbs use the render pipeline.
    want_browse = args.announce or args.browse or (
        interactive and not (args.plain or args.raw or args.dump
                             or args.save or args.fixture
                             or args.speak or args.speak_out))
    if want_browse:
        from .reader import browse
        browse(url, private=args.private, width=args.width,
               voice=args.voice, announce=args.announce)
        return

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

    if args.speak or args.speak_out:
        sys.exit(_speak_body(body, args.voice, args.speak_out))

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
        path = save_archive(doc_md, b["doc"].get("title") or url, url)
        print(f"mdb: saved archive -> {path}")
        if not args.raw:
            return

    if args.raw:
        print(doc_md)
        return

    render(body, b["meta"]["url"], width=args.width,
           use_pager=not args.no_pager, center=args.center)


if __name__ == "__main__":
    main()
