# Changelog

All notable changes to mdbrowse. Newest first.

## Unreleased

### Compact X engagement rows

Native X timeline captures now present reply, repost, like, bookmark, and
view counts on one labeled metadata row, matching the compact structure of
the web feed. Sparse action rows remain sparse, analytics links are
preserved, and capture telemetry reports how many rows were compacted.

### Optional authenticated backends

mdb remains native-first, but a page classified as a wall or application
shell can now be retried through separately installed OpenCLI or twitter-cli
adapters. The reader exposes an `E` confirmation action; CLI and MCP callers
can select a named backend or explicitly permit fallback. External results
return through the normal bundle/compiler path with backend and fallback
provenance. `--private` cannot cross this authenticated boundary.

`mdb setup backends` reports binary availability and gives installation,
health-check, and security guidance. Supported routes and trust boundaries
are documented in `docs/gated-sites.md`.

### Image capture correctness

Blocked image payloads now receive a tiny successful GIF response instead of
an aborted request. This prevents site `onerror` handlers from replacing the
authored image URL with a generic fallback, while retaining byte-saving
behavior and emitting stub/fallback counters as telemetry. Daemon restart
readiness also verifies the new code generation before accepting captures.

## 2026-07-18 — 2.0.1: one playwright per worker thread

Found in the wild minutes after 2.0.0 shipped: a cookied fetch after a
--private fetch through the daemon failed with Playwright's misleading
"Sync API inside the asyncio loop" error. The daemon's EngineWorker
caches one engine per privacy identity in a single thread, and each
engine started its own sync Playwright — but sync Playwright allows
exactly one start() per thread. The worker now starts playwright once
and LENDS it to every engine it builds; an engine only stops what it
started. The checkin gate's daemon row now captures in both postures
through one worker to keep it fixed.

## 2026-07-18 — 2.0.0: public release

v2 graduates from alpha. First public release: MIT license, GitHub
(GiantRavens/mdbrowse), Homebrew tap install (`brew install
giantravens/tap/mdbrowse`). README repositioned around what the tool
is for: a token-efficient markdown surface for LLM agents and a
deterministic, provenance-carrying capture tool for open-source
intelligence work.

Checkin gate hardening while cutting the release: the wsj slot now
accepts EITHER a classified DataDome wall OR the real front page as a
feed (the wall is vantage-dependent; the invariant is "never a silent
ghost"), captured private via a dedicated cookie-free engine in its own
thread (sync Playwright refuses a second start per thread). Personal
task state (tasks/, .punchlist/) untracked from the public repo.

## 2026-07-17 — Pagers become navigation; previews keep focus (2.0.0a8)

Terminal feed rows such as Hacker News's `More` could be mistaken for a
repeated-unit attachment and glued onto item 30. The walker now classifies
pagination before emission: semantic `rel=next/prev` wins at confidence
0.95; same-origin lexical links qualify only with a pagination query/path
delta (0.8/0.7). Pager-only blocks move out of feed flow into an explicit
`Next page:` / `Previous page:` block, URLs are exported in front-matter,
and the reader follows the chain with `.` / `,`. Candidate counts, detection
method, confidence, and JS-only load-more controls remain visible telemetry.

macOS image previews now appear without taking keyboard focus from mdb, so
the existing second-Space toggle can close the preview as intended.

## 2026-07-07 — X status pages via the syndication side door (2.0.0a7 wave)

X status pages read as "numbers without context" — `17K 131K 307K 21K`
with no labels. Investigated: not a wall (they extract at feed/0.9/0.91
coverage), but the engagement nouns live only in SVG icons the walker
strips, the SPA hydrates nondeterministically (heading-vs-paragraph,
metrics present-or-not per load), and the headless *desktop* profile gets
a ~551-char shell — so a bigger viewport makes X worse. When the DOM is
the wrong substrate, use a different one: X's own public embed API,
`cdn.syndication.twimg.com/tweet-result?id=<id>` (login-free, cookieless,
deterministic, *labeled*), is the exact analogue of reddit's `.json` fast
path. New `x.py` builds a bundle from it — H1 author, date, linkified text
(t.co expanded, @mentions/#hashtags linked), inline media, and the counts
as one honest line (`Replies 17,946 · Likes 307,890` — only the metrics
the payload carries, never a faked 0). Wired into `capture.py` beside the
reddit hook; `/status/<id>` only, everything else (profiles, deleted-tweet
HTML tombstones, `--private` needs none since it's cookieless) falls
through to the walker. Fixture `x-status` + a network-free `x-adapter`
gate check (routing, labeled counts, linkify) guard it. Spec:
docs/x-adapter.md.

## 2026-07-06 — Skip-link suppression (2.0.0a7 wave)

"Skip to content" (WCAG bypass-blocks link) leaked in as a stray first
line — often promoted to a heading (github, bbc). It's visually hidden
OFF-SCREEN (clip / `position:absolute; left:-9999px`), which `hidden()`'s
display/opacity/aria test doesn't catch. The walker now drops it on two
signals together: structural (a same-page `#`-fragment anchor) AND
lexical (short `^skip to …`) — both required, so prose like "Skip to the
recipe" and long sentences survive. Applied at the heading and leaf
branches. Fixtures unchanged (walker doesn't re-run on frozen bundles;
the bbc golden keeps its historical snapshot).

## 2026-07-06 — The menu was there all along (2.0.0a7 wave)

congruity360.com's `⋯ menu` appendix showed two links (logo + "Let's
Talk") while the real 30-item navigation was missing. Not a bug — a
profile consequence: mdb captures as an iPhone (small pages, Safari-
cookie match, walls clear for a self-consistent mobile identity), and
responsive sites collapse their primary menu into a `display:none`
hamburger drawer at phone width. The walker's `hidden()` rightly drops
it from the body — pixels are the judge there.

But the menu appendix was never a faithful render: it already demotes
nav to a flat, deduped link list at the tail. So the fix scopes to it
alone. The walker now runs a visibility-independent harvest over
`nav,[role=navigation]` anchors — deduped by href, labels
de-concatenated (mega-menus stack title+`<span class=menu-description>`
inside one `<a>`; the anchor's direct text nodes are the title),
capped at 60. `emit._menu_links` merges the harvest with visible
nav-region links (header links on sites with no semantic `<nav>`).
Body stays render-faithful to mobile; only the menu gains the hidden
links. Fixes the whole hamburger-nav cohort, not just this host — no
per-site `DESKTOP_HOSTS` patch, no desktop re-fetch. Old bundles
(no `navLinks`) fall back to region links, so fixtures are unchanged.
Gate row `congruity` guards it (deep items "Enterprise Insights",
"Intelligent Cloud Migrations" appear ONLY via the harvest).

## 2026-07-05 — Walls classify; --headed walks through them (2.0.0a7 wave)

wsj.com rendered as a silent one-line ghost. Now: new shape `wall` —
an empty capture (no text, links, or controls) classifies with the
why, and a captcha-delivery iframe over the empty body names the
cause at 0.9 (walker now reports iframe srcs as a signal; it still
never enters them). Fixture `wall-challenge` + gate row `wsj` guard
both sides; `wsj-apex` separately guards the dead-but-resolving apex
fast-fail (TCP preflight, 30s hang → 6.5s classified answer).

And the wall is walkable: `--headed` captures through a visible real
browser wearing NO costume — Chrome channel, native UA, no device
emulation, no stealth shim, just your Safari cookies. DataDome's whole
job is catching identity contradictions; headed mode's premise is
having none. wsj.com: wall → full front page, feed 0.9. (The first
attempt kept the iPhone-Safari mask on a desktop window and was
correctly re-challenged — the lesson is the feature: honesty renders.)

Telemetry now leads the reports: per-capture `coverage`
(captured-vs-rendered text — walker misses surface as a number) and
gate drift baselines (~/.mdb/checkin-baseline.json — a >50% body-size
drop flags even when static assertions pass).

## 2026-07-05 — Element policy: no point showing an LLM the ads (2.0.0a7 wave)

Borrowed from empathymachine: declarative per-host rules that carry
their WHY. mdb already blocked tracker hosts; this layer reaches what
host-blocking can't — first-party ad furniture (reddit's promoted
posts: 56 `shreddit-ad-post`/`shreddit-dynamic-ad-link` elements on one
probed front page; AdSense `ins.adsbygoogle` slots). `policy.py` holds
the builtins (kept small and certain — an over-broad selector silently
eats content, worse than showing an ad); the walker skips matches and
counts them; the count rides bundle meta and front-matter as
`policy_killed`, so removal is telemetry, never silent editing. User
rules merge from `~/.mdb/policy.json`; `MDBROWSE_NO_POLICY=1` disables.

Same wave, from captain field reports: buried-article classify override
(foxnews leads with the story, not the rails — prose mass >=8 blocks /
>=2000 chars outvotes link-led counts; `fox-article` fixture), SVG
namespace KILL fix (reddit's Snoo stylesheet leaked as text — SVG tags
report lowercase tagName), DNS bypass (quantum.com browses through a
GlobalProtect-poisoned resolver via direct DNS + Chromium
host-resolver-rules), and the apple.com image triple-fix (aria-hidden
carousels, currentSrc data: shadowing, <picture> source fallback:
3 → 24 unique images).

## 2026-07-05 — Benchmark: what does an agent actually pay to read the web?

`tests/benchmark.py` — an instrument, not a gate. Seven contenders
(mdb, raw HTML, regex tag-strip, Chromium innerText, trafilatura,
pandoc html->gfm, Jina's r.jina.ai reader) over five pages, scored on
tokens (chars/4, applied identically), ground-truth fact recall,
navigable links, structure survival (code fences, pipe tables),
per-fetch speed, and double-fetch determinism. Ground truth is never a
contender's output: static pages use known-fact strings; HN titles are
regexed from the server HTML by an independent parser at run time.

First readings: mdb is the only contender with 100% recall AND links
AND structure (587 tok/fact, 355 links, 2/2 struct). innerText/strip
are cheaper per fact (344/413) but carry 1-2 links total across five
pages — an agent goes blind after one hop. Raw HTML: 5,031 tok/fact
(apple.com alone is 62K tokens; mdb emits 639). The "remote-control
local tools" pipeline (fetch + pandoc) scored worst on recall (66.7%):
pandoc emits 2 tokens for all of HN (layout tables collapse) and 10.7K
tokens of nav soup for apple.com — generic converters are fine on
document-shaped HTML and lost everywhere the modern web isn't.

## 2026-07-05 — The MCP grows memory and senses: archive search + the watch fleet

An agent could archive pages and manage nothing: the store was
write-only and the sensors CLI-only. Both surfaces now speak MCP.

### Added
- **`archive_search`** — term-AND full text over `~/mdbrowse-archive`
  with provenance per hit (path, title, source, retrieved, score,
  snippet). Index-free scan, honest at current size; the docstring
  carries the graduation trigger (visible lag → real FTS, the kf/df
  pattern). `archive_page` + `archive_search` = a personal web memory.
- **Watch fleet over MCP** — `watch_add`, `watch_list`, `watch_scan`,
  `watch_diff`, `watch_remove`. Scan readings are structured
  (ok / changed with diff sample / error with the why), so an agent can
  drive the change-detection fleet and react to what moved.
- Two agent probes: watch lifecycle and archive memory, both against
  scratch stores. The archive probe queries with the page's *own words*
  — its first run failed because example.com had quietly rewritten its
  copy since the hardcoded query was written, which is exactly the
  lesson: probes assert structure and round-trips, never live content.

### Changed
- `watch.py` split per doctrine — `scan_readings()` and `diff_text()`
  are pure data functions; the CLI verbs and MCP tools are both thin
  frontends over them. SystemExit stays a CLI dialect; the MCP wrapper
  translates it to a readable error.

## 2026-07-05 — Checkin gate: the real web signs off on every commit

`tests/checkin.py`, wired as a git pre-commit hook (`--install-hook`).
Phase 0 re-runs the offline fixture corpus; phase 1 sweeps an 11-site
manifest where each site earns its slot by stressing something the
others don't — HN (layout tables/unit detector), CNN (stretched-link
cards/overlay kill), BBC (card merging), apple.com (lazy marketing
pages), quantum.com (the split-DNS lesson), Wikipedia + Python docs
(article + code-fence fidelity), IANA (pipe tables), GitHub (chrome-
heavy SPA), xkcd (RSS discovery + images), Mojeek (the search
pipeline) — plus a double-capture determinism check. Assertions are
structural (shape, counts, fences), never content. Failures carry
their class (dns/timeout/tls/shape/thin); a DNS black-hole on an
`env_dns_warn` site (quantum.com under GlobalProtect) warns and points
at `mdb doctor` instead of blocking the commit, and a dead network
skips the sweep entirely — fixtures still gate. Full run: ~17s warm.

## 2026-07-05 — Agent-grade: data tables, MCP search + pagination, agent probe suite (2.0.0a6)

The audit question was "would an agent prefer this over its built-in web
tools?" Three gaps said not-yet; all three closed.

### Added
- **Data tables survive as pipe tables.** The walker now records per-cell
  markdown (`cells`), header-ness (`<th>` rows), and table ownership (`tbl`)
  as layout-engine facts; the emitter turns runs that read as data tables
  (header row, or a regular >=2-column grid) into markdown pipe tables, `|`
  escaped. Layout tables (HN story rows, irregular grids) still emit as
  prose/feed lines. Old bundles lack `cells` and emit byte-identically —
  goldens untouched. New offline fixture `table-basic` guards both sides.
- **MCP: `search_web(query)`** — the missing half of an agent's web verb
  pair. Results ride the same pipeline (Mojeek default, MDBROWSE_SEARCH_URL
  overrides) and come back as one linked line per result.
- **MCP: `fetch_page` paginates.** `start_char` slices long documents; the
  truncation note names the next offset, and the 60s bundle cache makes the
  continuation free (no re-render). `page_links` gains a `pattern` regex
  filter (text OR href) so navigation questions cost tokens proportional
  to the question.
- **Agent probe suite** (`tests/agent_probes.py`): eight live probes for
  the actions agents actually perform — docs code fidelity, pipe tables,
  search results, feed digest, filtered links, pagination stitching, hash
  determinism across fresh captures, fast classified failure. Its first
  run caught a bad assertion before it caught a bad feature: probes are
  telemetry about the suite too.

### Fixed
- **Decorative inline icons dropped.** Textless images measuring under
  ~600 px² (sort arrows, bullet gifs) no longer pollute prose or table
  cells; zero-size (lazy/unmeasured) images still pass, so card thumbnails
  survive.

## 2026-07-04 — v1 retired; v2 (`mdb`) is mdbrowse

The single-file v1 (`mdbrowse.py`, fetch → strip → convert → repair) is
retired per doctrine: its replacement passed its scans first. Evidence:
8-fixture corpus green (`mdb --selftest`), fidelity oracle scores 9-10/10
(article/HN), and v2 exceeds v1 on every capability axis — plus watch
sensors, MCP server, speech, search, forms, RSS, downloads, LLM assist,
and an engine daemon v1 never had. v1 remains in git history; its best
parts (settle heuristic, binarycookies parser, Safari integration,
tracker lists) live on inside v2. See README.md for the v2 story.


## 2026-06-27 — Markdown lint pass: guaranteed well-formed output

### Added
- **`_lint_md()` — a single normalization pass every rendered page leaves
  through**, regardless of which extraction path (trafilatura prose or
  whole-page) produced it. Guarantees: ATX headings with a space after the
  hashes and blank lines around them; one consistent `- ` bullet marker; spaces
  around inline links so words don't fuse to them (`sources](url)to` →
  `sources](url) to`); and stripping of leaked `<svg>`/`<script>`/stray HTML
  tags and inline CSS declaration blocks. Fenced code blocks are split out and
  passed through untouched, so a code sample's contents are never rewritten.

## 2026-06-27 — Fix x.com showing only the "JS disabled" wall

`mdbrowse https://x.com` rendered just the noscript wall + footer (7 lines),
no timeline. Three compounding causes, all fixed:

### Fixed
- **Premature capture.** The observe-first settle classified x.com's ~170-char
  app shell as "done" and captured before the timeline's XHR returned. Tweets
  are `<article>` elements that arrive a beat after the shell — so the settle
  now reserves the fast path for genuinely content-rich pages (≥800 chars at
  load) and, for smaller/ambiguous pages, waits for an `<article>` to attach.
  (networkidle is useless here — X holds long-poll sockets open, so it never
  fires; confirmed empirically.)
- **`<noscript>` wall extracted as the article.** `page.content()` serializes
  the `<noscript>` block even though JS rendered real content; trafilatura with
  `favor_recall=True` then picked the "enable JavaScript" text as the article.
  Now stripped before extraction.
- **Feed under-extraction.** trafilatura extracts ONE article, so on a timeline
  of many `<article>` posts it grabbed a single tweet and dropped the rest.
  Pages with ≥3 `<article>` elements now route to the whole-page converter,
  which keeps every post and its headings. x.com went from a 7-line wall to the
  full timeline with `#` headings and per-tweet links.

## 2026-06-27 — Speed: browser reuse and observe-first settle

The JS-by-default render was "super duper slow" (~4s/page, every page paying a
cold Chromium launch). Two fixes, profiled against the actual cost.

### Changed
- **Observe-first settle heuristic.** `_settle_page` now measures `innerText`
  immediately after load and classifies the page: if content is already
  present (server-rendered), it skips the landmark wait entirely and does a
  quick stability check; only near-empty SPA shells pay the
  `wait_for_selector` cost. Previously a server-rendered page with no
  `<main>`/`<article>` burned the full selector cap waiting for an element that
  would never appear. Server-rendered pages dropped **2.7s → 0.87s** each; SPAs
  (x.com) still settle correctly (~2.2s).
- **Warm browser reuse.** New `BrowserSession` holds the engine + context
  (cookies, stealth shim, tracker routing) open across page loads; browse-mode
  link-following reuses it instead of cold-launching Chromium per hop.
  `fetch_js` is now a one-shot wrapper over it. A 5-page browse session went
  from ~13.5s to ~3.9s end to end.

## 2026-06-27 — JavaScript by default; defeat "JS is disabled" walls

Heavy SPAs (x.com, instagram, …) served a "JavaScript is not available" wall.
Two root causes: the JS path was broken, and it wasn't the default, so the
static fetcher — which can't run JS — got walled.

### Changed
- **JavaScript rendering is now the default.** Every page renders through the
  headless browser engine so SPAs and lazy-loaded content come through. New
  `--static` (a.k.a. `--no-js`) opts into the fast no-engine path. `--js` still
  works (now a no-op default) and `--wait` still forces the engine.
- **Graceful degradation:** if Playwright isn't installed, the default silently
  falls back to the static fetcher (with a one-line hint); only an *explicit*
  `--js`/`--wait` hard-fails with install instructions.

### Added
- **Auto-escalation sensor.** Even on the `--static` fast path, if the fetched
  HTML matches a "JavaScript required" wall signature, mdbrowse transparently
  retries with the JS engine (and emits a telemetry line saying so) instead of
  rendering the wall.

### Fixed
- **The JS path was completely broken**: `new_context()` received `user_agent`
  both from the iPhone device descriptor and explicitly, raising a
  duplicate-keyword `TypeError` on every run. Context options are now merged
  through a dict so `IPHONE_UA` cleanly overrides the descriptor's UA.
- **Anti-bot "JS disabled" walls defeated.** A stealth init script runs before
  page scripts and aligns the headless-Chromium identity with the mobile-Safari
  UA we present: `navigator.webdriver` → undefined (the automation flag),
  `navigator.vendor` → `Apple Computer, Inc.` (Chromium reports `Google Inc.`,
  contradicting the Safari UA), and `maxTouchPoints` → 5. No second browser
  engine required — Chromium stays the only install dependency.

## 2026-06-25 — Authenticated browsing, semantic layout, reader UX, real-world fixes

A full pass turning mdbrowse from a clean anonymous reader into an
authenticated, OSINT-capable terminal browser with a polished reader.

### Added
- **Authenticated-by-default browsing.** Reads your Safari cookie jar
  (`Cookies.binarycookies`, hybrid-endian parser) and seeds both the static
  (`httpx`) and `--js` (Playwright) paths, scoped per host so cookies survive
  redirects without leaking. You browse as your logged-in self.
- **`--private` / `--anonymous`** restores the old cookie-free mode and adds
  `DNT` + `Sec-GPC`.
- **DOM-driven semantic layout.** Pages render as title → main content →
  menu / sidebar / footer link arrays. `<nav>`/`<aside>`/`<footer>` are
  extracted from the DOM first (so what remains *is* the main content) and
  demoted to deduped link lists. Cookie/consent/modal/paywall chrome is removed
  by id/class signature.
- **Reader actions** in the vim reader: `s` saves a timestamped Markdown archive
  with YAML front-matter (title/source/retrieved/mode), `p` opens a styled HTML
  reader preview, `O` opens the live page in Safari. Plus a `--save` CLI flag.
- **Image preview.** Images become `🖼 … [IMGn]` markers; `Space` (or click)
  pops the image in macOS Quick Look, pulled to the front via System Events.
- **Mouse support.** Wheel scrolls, click a link to follow it, click an image to
  preview it.
- **`--wait SELECTOR`** for `--js`: wait for a CSS selector before capturing
  late-painting SPAs (implies `--js`).

### Changed
- **`--js` wait strategy** moved from `networkidle` (which fires early because we
  block images/trackers) to a content-stability heuristic: probe for
  `<main>`/`<article>`, scroll-nudge lazy content, then wait until
  `document.body.innerText` stops growing (capped at 8s).
- Image/link/linked-image numbering unified into **one document-order pass** so
  `[n]`/`[IMGn]` follow visual position (Tab walks top-to-bottom).

### Fixed
- **Dead tabbing on image-heavy pages (CNN).** The article-vs-index classifier
  counted images as links (`[..](..)` inside `![..](..)`), misreading front
  pages as link-rich articles. Now counts real links only — CNN: 2 → 338
  tabbable links.
- **Grid pages showed one story (storagereview).** With no `<main>`, the code
  used the first `<article>`; listing pages make each card its own `<article>`.
  Branch on count — one = story, many = grid (use `<body>`). 1 → 21 stories.
- **Missing thumbnails.** Lazy-loaded images park a `data:` placeholder in `src`
  with the real URL in `data-src`/`srcset`; now resolved before conversion.
- **Linked-image cards** (`[pre ![alt](img) post](href)`) half-parsed, leaking
  `](url)` and losing the link; now `🖼 [IMGn] headline [n]` (preview + follow).
- **Run-together words** (`Analysisby Aaron`): markdownify dropped whitespace and
  joined adjacent inline elements; a space is now inserted at tag boundaries.
- **Apex domains that won't resolve** (e.g. `quantum.com`): retry once with
  `www.` prepended on connection failure.
- **Mouse clicks didn't register**: dropped `REPORT_MOUSE_POSITION` (xterm mode
  1003, which macOS Terminal.app rejects); also require a real button bit.
  (Inside tmux, needs `set -g mouse on`.)
- **Screen resize** now re-wraps the current page instead of leaving stale cells.
- Emoji-width click drift, glued image markers, redundant duplicate titles,
  leaked CSS `{}` remnants.

### Notes
- `--js` needs a one-time `playwright install chromium`.
- Image preview asks for a one-time macOS Automation permission (to raise Quick
  Look to the front); declining still works, just behind the terminal.
