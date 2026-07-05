# mdbrowse — browse the web as faithful, deterministic markdown

`mdb` is a web → markdown **compiler** with a terminal browser on top.
It renders pages in headless Chromium, extracts structured truth from
inside the engine (geometry, landmarks, computed styles — never
re-parsed HTML strings), classifies each page's *shape*, and emits
clean, hierarchically correct markdown — the same page state producing
the same bytes, every time. Everything else is a frontend over that
compiler: a vim-style reader, an archive store, change-watching
sensors, an MCP server for agents, speech output, and a
screenshot-based fidelity oracle.

- **Browses as you.** Reads your Safari cookies by default — logged-in
  and paywalled-to-you pages render as you'd see them. `--private`
  sends none.
- **Shape-aware.** Articles come out as clean prose; feeds (HN, news
  fronts) as one linked line per story; index cards merge their
  fragments; data tables as markdown pipe tables (layout tables stay
  prose); app-shaped pages get a classified refusal instead of soup.
- **Deterministic and diffable.** Front-matter carries provenance
  (source, retrieved, mode, shape+confidence, extractor version) and a
  body content-hash. Same page state → identical body. Pages become
  versionable.

## Install

```bash
cd ~/Desktop/notebook/code/mdbrowse
uv venv && uv pip install -e .
.venv/bin/playwright install chromium
./mdb --version         # repo-root launcher; ~/bin/mdb points here
```

The venv is host-local (never synced); `./mdb` prints this recipe on a
machine that lacks one.

## Use

```bash
mdb                                  # Safari start page (bookmarks, reading list)
mdb news.ycombinator.com             # interactive reader (default in a terminal)
mdb <url> --plain                    # non-interactive render (centered; --no-center)
mdb <url> --raw                      # markdown document with front-matter
mdb <url> --save                     # archive to ~/mdbrowse-archive
mdb <url> --speak                    # the page talks (macOS say; --voice, MDBROWSE_VOICE)
mdb <url> --speak-out article.aiff   # page as an audio file
mdb search rust atomics              # web search (Mojeek; MDBROWSE_SEARCH_URL overrides)
mdb feed https://xkcd.com/atom.xml   # RSS/Atom as a feed page
mdb get <file-url>                   # authenticated download (~/Downloads)
mdb oracle <url>                     # judge markdown fidelity against a screenshot
mdb <url> --dump bundle|manifest|body  # inspect any compiler stage
mdb --selftest                       # re-emit the fixture corpus, diff vs goldens
```

### Watch sensors — versioned pages that fire on real change

```bash
mdb watch add https://example.com/pricing --name pricing
mdb watch scan          # check all; commits changes to a git store
mdb watch diff pricing  # last change as a patch
mdb watch digest        # Claude narrates the week's changes (briefing material)
```

Store: `~/mdbrowse-watch` (git; `git log -p <name>.md` is the page's
history). The trigger hashes **visible text only** — rotating URL
tokens never false-fire.

### The reader

Vim-style, with a single **focus ring** over links *and* images
(browser-like Tab). Two verbs: **Enter = go, Space = peek** (Quick Look
the focused image; page-down otherwise). Every keystroke's effect is
predictable from what is visibly highlighted.

| keys | |
|---|---|
| `Tab` / `S-Tab` | next / previous focusable — full-extent highlight, even wrapped |
| `Enter` / `o` · `Space` | go · peek |
| `y` / `Y` · `d` | yank focused / page URL · download focused target |
| `(` `)` · `{` `}` | heading / block motions |
| `j k` `C-d C-u` `C-f C-b` `gg G` `zt zz zb` | scrolling and placement |
| `/` `n` `N` | search |
| `H` / `L` · `r` | history back / forward · reload |
| `f` | fill the page's search form (GET), submit as navigation |
| `F` | open the page's advertised RSS feed |
| `S` / `a` | summarize / ask this page (Claude); answers are pages, `H` returns |
| `v` | speak from the focused element (`v` again stops; `--announce` speaks on focus) |
| `s` · `B` · `O` | archive · add to Safari Reading List · open in browser (`MDBROWSE_BROWSER`) |
| `:` | URL, `ddg terms`, `s terms`, `safari:start`, `feed:URL` |
| `?` · `q` | help overlay · quit |

Mouse: wheel scrolls, click follows, click 🖼 previews. (tmux: `set -g mouse on`.)

### Agents and speed

- **MCP server** (`mdb-mcp`, registered as `mdbrowse`): `fetch_page`
  (markdown + provenance; long pages paginate via `start_char`, the
  continuation served from the capture cache), `search_web` (results as
  linked lines), `page_links` (with a `pattern` regex filter),
  `archive_page` (returns the body hash — compare to detect change).
- **Agent probe suite** (`tests/agent_probes.py`): live regression
  guards for the actions agents actually perform — docs code fidelity,
  pipe tables, search, feed digests, link filtering, pagination
  stitching, hash determinism, fast classified failure.
- **Engine daemon**: warm Chromium behind `~/.mdb/engine.sock`,
  auto-spawned on first CLI capture, idle-exit after 30 min. Warm
  fetches run ~0.7–1.0s. `mdb daemon start|stop|status|run`;
  `MDBROWSE_DAEMON=off` disables.

## How it works

1. **Capture** — headless Chromium (Playwright), Safari cookies unless
   `--private`, stealth shim, tracker/image blocking, content-stability
   settle, 3s DNS preflight (black-holed names fail fast *with the
   why*). `walker.js` runs inside the page and emits leaf blocks with
   landmark, kind, inline-markdown, links, and geometry. `page.content()`
   is never taken.
2. **Classify** — a cheap shape manifest (`article | feed | page | app`
   with confidence) from bundle signals, before any emission.
3. **Emit** — per-shape assembly: repeated-unit detection collapses
   card fragments to one line per item (shared link target + signature
   periodicity); headings remap to a strict hierarchy; nav/aside/footer
   demote to link lists; forms stay out of documents (they're
   affordances — the reader's `f` uses them from the bundle).

Every stage is inspectable (`--dump`), every change is measured: the
fixture corpus (`tests/fixtures/`, 8 real sites) re-emits offline in
`--selftest`, and `mdb oracle` judges output against full-page
screenshots — pixels as judge, never as extractor.

## History

v1 (a single-file `mdbrowse.py`: fetch → strip → convert → repair) was
retired on 2026-07-04 after the v2 compiler exceeded it on every axis —
see `CHANGELOG.md` and git history. Its best parts (settle heuristic,
binarycookies parser, Safari integration, tracker lists) live on inside
v2.
