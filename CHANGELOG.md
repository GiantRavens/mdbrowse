# Changelog

All notable changes to mdbrowse. Newest first.

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
