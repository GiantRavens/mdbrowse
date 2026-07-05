"""Benchmark: mdb against the ways agents actually get web content.

Six contenders, five pages, four questions:

  contenders                          approximates
  ----------                          ------------
  mdb         capture->classify->emit this tool's MCP fetch_page
  raw         httpx GET, raw HTML     naive fetch tools that feed HTML
  strip       tag-stripped raw HTML   cheap "html to text" converters
  innertext   Chromium body.innerText browser get_page_text tools
  trafilatura extraction library      the standard extractor (v1's core)
  jina        r.jina.ai remote reader a deployed LLM web-reader service

  questions: how many TOKENS does the agent pay? what fraction of the
  page's FACTS survive (recall against ground-truth signals)? how FAST?
  does STRUCTURE survive (code fences, pipe tables, navigable links)?
  is the output DETERMINISTIC (same page state -> same bytes)?

Ground truth is never a contender's output: static pages use known-fact
signal strings; HN's titles are regexed from the server-rendered HTML
by an independent parser at run time. Recall matching normalizes
backslash-escapes and whitespace on both sides so markdown escaping
neither helps nor hurts.

Token counts are chars/4 — approximate, but applied identically to
every contender, and relative cost is the question. Speed is per-fetch
wall time as measured here: mdb and innertext pay a Chromium render
(warm engine; the daemon/60s MCP cache amortize this in real use),
httpx-based contenders don't, jina pays a remote round trip.

This is an instrument, not a gate — run it by hand, cite the numbers:

    .venv/bin/python tests/benchmark.py              # everything
    .venv/bin/python tests/benchmark.py pydocs       # one page
    .venv/bin/python tests/benchmark.py --skip-jina  # no remote calls
    .venv/bin/python tests/benchmark.py --json       # machine-readable
"""

import html as html_mod
import json
import re
import sys
import time

import httpx

sys.path.insert(0, "src")

UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) "
      "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 "
      "Safari/604.1")


# ---------------------------------------------------------------- pages

def _hn_titles() -> list:
    """Ground truth for HN: story titles regexed from the server-rendered
    HTML by an independent parser — no contender defines truth."""
    r = httpx.get("https://news.ycombinator.com",
                  headers={"User-Agent": UA}, timeout=15)
    titles = re.findall(
        r'<span class="titleline"><a href="[^"]*"[^>]*>([^<]+)</a>', r.text)
    return [html_mod.unescape(t) for t in titles[:10]]


PAGES = [
    dict(name="pydocs",
         url="https://docs.python.org/3/library/functools.html",
         signals=["lru_cache", "cmp_to_key", "singledispatch",
                  "partialmethod", "cached_property", "total_ordering"],
         structure=[("code fences", lambda t: t.count("```") >= 2)]),
    dict(name="iana",
         url="https://www.iana.org/assignments/http-status-codes/http-status-codes.xhtml",
         signals=["Switching Protocols", "Early Hints", "Multi-Status",
                  "Permanent Redirect", "Misdirected Request",
                  "Unavailable For Legal Reasons"],
         structure=[("pipe table", lambda t: "| --- |" in t)]),
    dict(name="hn",
         url="https://news.ycombinator.com",
         signals=_hn_titles,
         structure=[]),
    dict(name="wiki",
         url="https://en.wikipedia.org/wiki/Hacker_News",
         signals=["Paul Graham", "Y Combinator", "2007", "Arc"],
         structure=[]),
    dict(name="apple",
         url="https://www.apple.com",
         signals=["iPhone", "iPad", "Mac", "Watch"],
         structure=[]),
]

DETERMINISM_PAGE = "pydocs"     # static docs: honest double-fetch target


# ------------------------------------------------------------ contenders

def fetch_mdb(eng, url):
    from mdb.classify import classify
    from mdb.emit import emit
    bundle = eng.capture(url)
    return emit(bundle, classify(bundle))


def fetch_raw(eng, url):
    r = httpx.get(url, headers={"User-Agent": UA},
                  follow_redirects=True, timeout=25)
    return r.text


def fetch_strip(eng, url):
    t = fetch_raw(eng, url)
    t = re.sub(r"(?is)<(script|style|noscript|template|svg)[^>]*>.*?</\1>",
               " ", t)
    t = re.sub(r"(?s)<!--.*?-->", " ", t)
    t = re.sub(r"(?s)<[^>]+>", " ", t)
    t = html_mod.unescape(t)
    return re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n", t)).strip()


def fetch_innertext(eng, url):
    eng._ensure()
    page = eng._context.new_page()
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(1500)
        return page.inner_text("body")
    finally:
        page.close()


def fetch_trafilatura(eng, url):
    import trafilatura
    t = trafilatura.extract(fetch_raw(eng, url), output_format="markdown",
                            include_links=True, include_tables=True,
                            favor_recall=True)
    return t or ""


def fetch_pandoc(eng, url):
    """The 'remote-control local tools' pipeline: fetch, pipe through
    pandoc html->gfm, read the result. Zero LLM tokens to produce —
    the question is what the agent then has to read."""
    import subprocess
    r = subprocess.run(["pandoc", "-f", "html", "-t", "gfm-raw_html"],
                       input=fetch_raw(eng, url),
                       capture_output=True, text=True, timeout=60)
    return r.stdout


def fetch_jina(eng, url):
    r = httpx.get(f"https://r.jina.ai/{url}", headers={"User-Agent": UA},
                  timeout=40)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}")
    time.sleep(2)          # be polite to the free tier
    return r.text


CONTENDERS = [("mdb", fetch_mdb), ("raw", fetch_raw), ("strip", fetch_strip),
              ("innertext", fetch_innertext),
              ("trafilatura", fetch_trafilatura), ("pandoc", fetch_pandoc),
              ("jina", fetch_jina)]


# --------------------------------------------------------------- scoring

def _norm(s: str) -> str:
    return re.sub(r"[\\\s]+", " ", s).lower()


def tokens(text: str) -> int:
    return len(text) // 4


def recall(text: str, signals: list) -> int:
    t = _norm(text)
    return sum(1 for s in signals if _norm(s) in t)


def uniq_links(text: str) -> int:
    return len(set(re.findall(r"https?://[^\s\"'<>)\]]+", text)))


def _stable(text: str) -> str:
    """Normalization for the determinism check: drop provenance
    timestamps every honest fetcher must vary."""
    lines = [l for l in text.split("\n")
             if not re.match(r'\s*"?(retrieved|hash|Published Time|Date|'
                             r'Warning|Expires|Last-Modified)', l, re.I)]
    return re.sub(r"\s+", " ", "\n".join(lines))


# ---------------------------------------------------------------- runner

def main() -> int:
    args = sys.argv[1:]
    as_json = "--json" in args
    skip_jina = "--skip-jina" in args
    pick = [a for a in args if not a.startswith("--")]

    from mdb.capture import Engine
    pages = [p for p in PAGES if not pick or p["name"] in pick]
    contenders = [(n, f) for n, f in CONTENDERS
                  if not (skip_jina and n == "jina")]
    results = []

    with Engine() as eng:
        for page in pages:
            signals = page["signals"]
            if callable(signals):
                signals = signals()
            for cname, fetch in contenders:
                t0 = time.time()
                try:
                    text = fetch(eng, page["url"])
                    dt = time.time() - t0
                    row = dict(page=page["name"], tool=cname,
                               tokens=tokens(text), secs=round(dt, 2),
                               recall=recall(text, signals),
                               of=len(signals), links=uniq_links(text),
                               structure={label: bool(check(text))
                                          for label, check in
                                          page["structure"]})
                except Exception as e:
                    row = dict(page=page["name"], tool=cname,
                               error=f"{type(e).__name__}: {str(e)[:80]}",
                               secs=round(time.time() - t0, 2))
                results.append(row)
                if not as_json:
                    if "error" in row:
                        print(f"  {page['name']:7} {cname:12} "
                              f"ERROR {row['error']} ({row['secs']}s)")
                    else:
                        st = " ".join(f"{k}={'y' if v else 'N'}"
                                      for k, v in row["structure"].items())
                        print(f"  {page['name']:7} {cname:12} "
                              f"{row['tokens']:>8,} tok  "
                              f"{row['recall']}/{row['of']} facts  "
                              f"{row['links']:>4} links  "
                              f"{row['secs']:>5.1f}s  {st}")

        # Determinism: double-fetch the static page, compare normalized.
        det_url = next(p["url"] for p in PAGES
                       if p["name"] == DETERMINISM_PAGE)
        determinism = {}
        if not pick or DETERMINISM_PAGE in pick:
            if not as_json:
                print(f"\n  determinism (double-fetch {DETERMINISM_PAGE}, "
                      "provenance lines excluded):")
            for cname, fetch in contenders:
                try:
                    same = _stable(fetch(eng, det_url)) == \
                           _stable(fetch(eng, det_url))
                except Exception:
                    same = None
                determinism[cname] = same
                if not as_json:
                    word = {True: "stable", False: "DRIFTS",
                            None: "unavailable"}[same]
                    print(f"    {cname:12} {word}")

    # Summary: what does a retained fact cost, per contender?
    summary = {}
    for cname, _ in contenders:
        rows = [r for r in results if r["tool"] == cname and "error" not in r]
        if not rows:
            continue
        tot_tok = sum(r["tokens"] for r in rows)
        tot_hit = sum(r["recall"] for r in rows)
        tot_of = sum(r["of"] for r in rows)
        summary[cname] = dict(
            pages=len(rows), total_tokens=tot_tok,
            recall_pct=round(100 * tot_hit / tot_of, 1) if tot_of else 0,
            tokens_per_fact=round(tot_tok / tot_hit) if tot_hit else None,
            links=sum(r["links"] for r in rows),
            structure_pass=sum(sum(r["structure"].values()) for r in rows),
            structure_of=sum(len(r["structure"]) for r in rows),
            mean_secs=round(sum(r["secs"] for r in rows) / len(rows), 2),
            determinism=determinism.get(cname))

    if as_json:
        print(json.dumps(dict(results=results, summary=summary), indent=1))
        return 0

    print(f"\n  {'tool':12} {'pages':>5} {'total tok':>10} {'recall':>7} "
          f"{'tok/fact':>9} {'links':>6} {'struct':>7} {'mean s':>7}"
          f"  deterministic")
    for cname, s in sorted(summary.items(),
                           key=lambda kv: kv[1]["tokens_per_fact"] or 1e9):
        det = {True: "yes", False: "no", None: "?"}[s["determinism"]]
        tpf = s["tokens_per_fact"]
        struct = (f"{s['structure_pass']}/{s['structure_of']}"
                  if s["structure_of"] else "—")
        print(f"  {cname:12} {s['pages']:>5} {s['total_tokens']:>10,} "
              f"{s['recall_pct']:>6}% {tpf if tpf else '—':>9} "
              f"{s['links']:>6} {struct:>7} {s['mean_secs']:>7.2f}  {det}")
    print("\n  tok/fact = tokens the agent pays per ground-truth fact "
          "retained (lower is\n  better) — but read it beside links and "
          "struct: the cheap contenders get\n  their price by discarding "
          "the affordances (hrefs, fences, tables) an agent\n  needs for "
          "the NEXT step. Facts-per-token measures reading; links and "
          "struct\n  measure being able to act on what was read.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
