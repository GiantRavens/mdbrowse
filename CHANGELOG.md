# Changelog

All notable changes to mdbrowse. Newest first.

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
