# mdbrowse

**Compile and browse the web in markdown.**

`mdb` is a web → markdown **compiler** with a terminal browser on top to make it possible to browse the full web from a terminal window.

Humans get a non-noisy way to browse the web in simple markdown, llms get a token-efficient way to browse the web.

**How it Works**

When you launch mdb in a terminal, mdb launches an actual Chromium/Chrome browser behind your terminal window. The page
loads with all the niceties of a full browser, from JavaScript loading, cookies and more - something W3M could never give you. 
From that browser window mdb extracts the structure and essence of that page (geometry, landmarks, computed styles — never re-parsed HTML
strings). The full DOM and page interaction stay inside the browser;
but humans get a zen-like no-fluff browsing experience, and agents get a highly token-efficient view of the web.
The compiler classifies each page's
*shape* and emits clean, hierarchically correct markdown that can be snapshotted to archive webpages as clean markdown.

mdb includes an archive store,
change-watching sensors, an MCP server for agents, speech output ideal for sight-challenged users.

- **Full browser feature-set** mdb reads your Safari cookies by default so your logged-in
  and paywalled-to-you pages render as you'd see them. Or use the `--private` flag to go without.
- **No fluff** Light DOM re-ordering ensures articles come out as clean prose that drops most ads and pushes all that menubar and sidebard junk down - and works well with feeds (HN, news
  sites) presenting one linked line per story
- **Site-smart.** Write site-handling rules as you like - by default thin-mobile sites (Wikipedia, Stack Overflow, Reddit)
  are captured with a desktop UA; Reddit uses its `.json` endpoint for
  a browser-free structured read (old.reddit HTML when unauthenticated);
  Cloudflare "Just a moment…" challenges are waited out before capture.
  Per-host rules live in `policy.py` (+ `~/.mdb/policy.json`).
- **Deterministic and diffable.** Front-matter carries provenance
  (source, retrieved, mode, shape+confidence, extractor version) and a
  body content-hash. Same page state → identical body. Pages become
  versionable.
- **Reader's-choice ad policy.** Tracker hosts are blocked at the
  network; first-party ad furniture (reddit promoted posts, AdSense
  slots) is dropped by per-host policy rules (`policy.py`) — each rule
  carries its why, removal is counted in front-matter
  (`policy_killed`), user rules merge from `~/.mdb/policy.json`, and
  `MDBROWSE_NO_POLICY=1` turns the layer off.

## Simple, Zen browsing from a terminal console

Terminal browsers have always been the calm way to read the web, but have been quietly broken for twenty years: lynx and w3m parse
HTML, meanwhile most sites are unreadable without a full JavaScript engine. 

mdbrowse is a spiritual
successor to those tools in a full browser processor, then delivers the text as md format in the terminal.
mdbrowse by default uses keyboard-first vim motions, tabs to hop to focusable
links, even forms work such as Wikipedia or DuckDuckGo. 

## Built for agents; sharp for analysts

Since LLMs charge per token, reading full HTML is highly inefficient - raw HTML costs
about 9× mdb's tokens per fact, and most "clean" extractors pay for
their cleanliness by dropping the links or flattening the structure.

In the benchmark suite of tools mdb is the only extractor with 100%
fact recall AND navigable links AND surviving structure — the suite
table below has the details. The MCP server (`mdb-mcp`) hands that
surface to any agent: fetch with provenance, web search, link
filtering, pagination slices served from the capture cache.

The same properties make it an exellent open-source intel tool:

- **Capture the web as citable 'point in time' snapshots:** Same page state → identical
  bytes, with front-matter provenance (source URL, retrieval time,
  auth mode, shape + confidence, extractor version) and a body
  content-hash. Captures are diffable, versionable, quotable evidence.
- **Watch pages for change over time:** `mdb watch` keeps versioned snapshots and fires
  only on real change — classified readings (ok / changed+diff /
  error+why), never a bare "page fetched".
- **Build your searchable web content memory** Everything captured lands in a
  full-text-searchable archive (`mdb search`, `archive_search`) that
  works offline.
- **Read failure feedback:** Sites that throw up bot-walls and paywalls come back classified as
  walls with the reason - you can simply key 'O' no a page to open the URL in your rich browser - likely the cookies you save will let mdb through the next time.

## Install

```bash
brew install giantravens/tap/mdbrowse     # installs mdb and mdb-mcp
```

mdb drives your installed Google Chrome when present. Without Chrome,
give Playwright its own engine once: `playwright install chromium`.

From source instead:

```bash
git clone https://github.com/GiantRavens/mdbrowse
cd mdbrowse
./mdb --version         # first run builds .venv (via uv) and installs Chromium
```

The project `.venv` is host-local. Not mandatory either: any Python
3.11+ environment works if you install mdb into it and give that same
environment a Chromium.

## Getting Started

This section assumes you are comfortable copying commands into Terminal,
but not necessarily comfortable debugging Python, virtual environments,
or browser automation.

### What you are installing

`mdb` is a command-line app. You run it from Terminal, and it opens web
pages through a real browser engine in the background. It then shows the
page as clean, keyboard-friendly markdown in your terminal.

Three pieces are involved:

- The `mdbrowse` project folder: the source code you are in now.
- A local Python environment: `.venv/` inside this folder. It keeps
  mdb's Python packages separate from the rest of your computer.
- A Playwright Chromium browser: the browser engine mdb uses for page
  capture. This is separate from Safari, Chrome, and Firefox.

### One-time setup

Open Terminal and go to the project folder. If you keep this repository
somewhere else, use that folder instead:

```bash
cd ~/Documents/mdbrowse
```

Run mdb once. The first run creates the local Python environment,
installs mdb into it, and installs the browser engine mdb needs:

```bash
./mdb --version
```

You will see first-run setup messages like:

```text
mdb: first-run setup
  project: /Users/you/.../mdbrowse
  venv:    /Users/you/.../mdbrowse/.venv
  phases:  create venv -> install mdb -> install Chromium
```

If that finishes by printing a version number, setup worked. Later runs
reuse the same `.venv` and start normally.

If you prefer to do the same setup by hand:

```bash
uv venv
uv pip install -e .
.venv/bin/playwright install chromium
```

Set `MDBROWSE_NO_BOOTSTRAP=1` if you want `./mdb` to fail instead of
building the `.venv` automatically.

### Using your own Python environment

You do not have to use the project `.venv`. If you already manage Python
environments with another tool, use Python 3.11 or newer, activate your
environment, then install mdb and its browser there:

```bash
cd ~/Desktop/notebook/code/mdbrowse
uv pip install -e .
python -m playwright install chromium
mdb --version
```

The important rule is that `mdb`, the Python packages, and Playwright's
Chromium install must belong to the same active environment. If you use
your own environment, run `mdb ...` instead of `./mdb ...`; the repo-root
`./mdb` launcher is designed around this checkout's `.venv`.

### Your first page

Start with a small, reliable page:

```bash
./mdb https://example.com --plain --no-pager
```

You should see a short markdown page. This proves the Python
environment, browser engine, network, and compiler are all working.

Now try the interactive reader:

```bash
./mdb https://news.ycombinator.com
```

Useful first keys:

- `j` and `k` move down and up.
- `Tab` moves to the next link or image.
- `Enter` opens the focused link.
- `H` goes back.
- `Space` previews the focused image, or scrolls when no image is
  focused. Press `Space` again to close that preview.
- `?` opens help.
- `q` quits.

Mouse wheel scrolling and clicking links also work in most terminals.

### Running mdb from anywhere

The safest command is always `./mdb` from inside the project folder.

If your shell has `~/bin` on `PATH`, this repository can also be exposed
as `mdb` from any folder:

```bash
mkdir -p ~/bin
ln -sf ~/Desktop/notebook/code/mdbrowse/mdb ~/bin/mdb
```

Open a new Terminal window and test:

```bash
mdb --version
```

If `mdb` says "command not found", use `./mdb` from the project folder
until your shell `PATH` includes `~/bin`.

### Common things to do

Read a page interactively:

```bash
./mdb https://www.wikipedia.org
```

Print a page without opening the reader:

```bash
./mdb https://example.com --plain
```

Search the web:

```bash
./mdb search "most useful open source intel tools"
```

Save a page to your personal archive:

```bash
./mdb https://example.com --save
```

Watch a page for future changes:

```bash
./mdb watch add https://example.com --name example
./mdb watch scan
```

Download a linked file:

```bash
./mdb get https://example.com/file.pdf
```

### Where files go

The project folder contains code. Generated user data goes somewhere
more appropriate for your operating system.

Saved pages and watch history default to:

- macOS: `~/Library/Application Support/mdbrowse/archive`
  and `~/Library/Application Support/mdbrowse/watch`
- Linux/BSD: `${XDG_DATA_HOME:-~/.local/share}/mdbrowse/archive`
  and `${XDG_DATA_HOME:-~/.local/share}/mdbrowse/watch`
- Windows: `%LOCALAPPDATA%\mdbrowse\archive`
  and `%LOCALAPPDATA%\mdbrowse\watch`

Downloads go to `~/Downloads` unless you choose another location.

Old folders named `~/mdbrowse-archive` or `~/mdbrowse-watch` are from
older defaults. They are safe to move into the new app-data folders, or
you can keep using them by setting `MDBROWSE_ARCHIVE` and
`MDBROWSE_WATCH_DIR`.

### Privacy basics

By default, mdb reads Safari cookies on macOS so pages look like they do
when you are signed in. That is useful for sites you already have access
to, but it also means mdb is browsing as you.

Use private mode when you do not want Safari cookies sent:

```bash
./mdb https://example.com --private
```

Saved archives are plain markdown files on your computer. Do not archive
private pages unless you are comfortable storing their text locally.

### If something goes wrong

If `uv` is missing, install it first. On macOS with Homebrew:

```bash
brew install uv
```

If first-run setup fails, run the setup steps manually from the project
folder so you can see exactly which phase failed:

```bash
uv venv
uv pip install -e .
```

If mdb says the browser is missing:

```bash
.venv/bin/playwright install chromium
```

If you are using your own Python environment instead of `.venv`, run:

```bash
python -m playwright install chromium
```

If a site blocks the background browser, try a visible browser window:

```bash
./mdb https://example.com --headed
```

If a page is acting strangely because of login state, compare normal and
private mode:

```bash
./mdb https://example.com
./mdb https://example.com --private
```

If you only want to check whether the installed copy still works:

```bash
./mdb --selftest
```

## Use

```bash
mdb                                  # Safari start page (bookmarks, reading list)
mdb news.ycombinator.com             # interactive reader (default in a terminal)
mdb <url> --plain                    # non-interactive render (centered; --no-center)
mdb <url> --raw                      # markdown document with front-matter
mdb <url> --save                     # archive to the mdbrowse app-data dir
mdb <url> --headed                   # visible real-Chrome window; verification walls (wall shape) trust it
mdb <url> --fallback-headed          # retry headed only after an explicit access-denied wall
mdb <url> --speak                    # the page talks (macOS say; --voice, MDBROWSE_VOICE)
mdb <url> --speak-out article.aiff   # page as an audio file
mdb search rust atomics              # web search (DuckDuckGo; MDBROWSE_SEARCH_ENGINE/URL overrides)
mdb feed https://xkcd.com/atom.xml   # RSS/Atom as a feed page
mdb get <file-url>                   # authenticated download (~/Downloads)
mdb oracle <url>                     # judge markdown fidelity against a screenshot
mdb <url> --dump bundle|manifest|body  # inspect any compiler stage
mdb --selftest                       # re-emit the fixture corpus, diff vs goldens
```

Search defaults to DuckDuckGo now that mdb runs a full Playwright browser.
Choose another built-in engine with `MDBROWSE_SEARCH_ENGINE=mojeek` or
`MDBROWSE_SEARCH_ENGINE=ddg-html`, or provide a custom template with
`MDBROWSE_SEARCH_URL='https://example.com/search?q={q}'`.

### Data locations

Archives and watch stores default to per-user application data, not the
visible home directory:

- macOS: `~/Library/Application Support/mdbrowse/{archive,watch}`
- Linux/BSD: `${XDG_DATA_HOME:-~/.local/share}/mdbrowse/{archive,watch}`
- Windows: `%LOCALAPPDATA%\mdbrowse\{archive,watch}`

`MDBROWSE_HOME` relocates both stores. `MDBROWSE_ARCHIVE` and
`MDBROWSE_WATCH_DIR` override the archive or watch store individually.
Older `~/mdbrowse-archive` and `~/mdbrowse-watch` folders are not moved
automatically; move them into the new paths or set the env vars above if
you want to keep using them in place.

### Watch sensors — versioned pages that fire on real change

```bash
mdb watch add https://example.com/pricing --name pricing
mdb watch scan          # check all; commits changes to a git store
mdb watch diff pricing  # last change as a patch
mdb watch digest        # Claude narrates the week's changes (briefing material)
```

Store: the app-data `watch` directory (git; `git log -p <name>.md` is
the page's history). The trigger hashes **visible text only** —
rotating URL tokens never false-fire.

### The reader

Vim-style, with a single **focus ring** over links, images, and forms
(browser-like Tab). Two verbs: **Enter = go, Space = peek** (preview or
close the focused image; page-down otherwise). Every keystroke's effect is
predictable from what is visibly highlighted.

Search forms are visible affordances, but they do not auto-focus on page
load. Press `f` for the prompt-driven search flow, or `Tab` into the
field when you want typed characters to go there.

| keys | |
|---|---|
| `Tab` / `S-Tab` | next / previous focusable — full-extent highlight, even wrapped |
| `Enter` / `o` · `Space` | go · peek |
| `y` · `u` / `Y` · `d` | yank focused URL · copy current URL · download focused target |
| `(` `)` · `{` `}` | heading / block motions |
| `j k` `C-d C-u` `C-f C-b` `gg G` `zt zz zb` | scrolling and placement |
| `/` `n` `N` | search |
| `H` / `L` · `r` | history back / forward · reload |
| `f` | fill the page's search form (GET), submit as navigation |
| `F` | open the page's advertised RSS feed |
| `.` / `,` | next / previous detected page |
| `S` / `a` | summarize / ask this page (Claude); answers are pages, `H` returns |
| `v` | speak from the focused element (`v` again stops; `--announce` speaks on focus) |
| `s` · `B` · `O` | archive · add to Safari Reading List · open in browser (`MDBROWSE_BROWSER`) |
| `:` | URL, `s terms`, `ddg terms`, `mojeek terms`, `safari:start`, `feed:URL` |
| `?` · `q` | help overlay · quit |

Mouse: wheel scrolls, click follows, click 🖼 previews. (tmux: `set -g mouse on`.)

### Agents and speed

- **MCP server** (`mdb-mcp`, registered as `mdbrowse`): `fetch_page`
  (markdown + provenance; long pages paginate via `start_char`, the
  continuation served from the capture cache), `search_web` (results as
  linked lines), `page_links` (with a `pattern` regex filter),
  `archive_page` (returns the body hash — compare to detect change),
  `archive_search` (full text over the archive: a personal web memory),
  and the watch fleet — `watch_add` / `watch_list` / `watch_scan`
  (structured readings: ok / changed+diff / error+why) / `watch_diff` /
  `watch_remove`.
- **Agent probe suite** (`tests/agent_probes.py`): live regression
  guards for the actions agents actually perform — docs code fidelity,
  pipe tables, search, feed digests, link filtering, pagination
  stitching, hash determinism, fast classified failure.
- **Engine daemon**: warm Chromium behind `~/.mdb/engine.sock`,
  auto-spawned on first CLI capture, idle-exit after 30 min. Warm
  fetches run ~0.7–1.0s. `mdb daemon start|stop|status|run`;
  `MDBROWSE_DAEMON=off` disables.
- **Browser execution, token-shaped output**: agents are not scraping a
  TUI transcript. They ride the same real browser capture as the reader,
  but only the classified markdown page, links, forms, provenance, and
  requested slices cross the MCP boundary.

## How it works

1. **Capture** — Chromium/Chrome via Playwright, Safari cookies unless
   `--private`, stealth shim, tracker/image/media blocking, autoplay
   suppression, content-stability settle, 3s DNS preflight (black-holed
   names fail fast *with the why*). `walker.js` runs inside the page and
   emits leaf blocks with landmark, kind, inline-markdown, links, and
   geometry, plus document-level feed and pagination affordances.
   `page.content()` is never taken.
2. **Classify** — a cheap shape manifest (`article | feed | page | app`
   with confidence) from bundle signals, before any emission.
3. **Emit** — per-shape assembly: repeated-unit detection collapses
   card fragments to one line per item (shared link target + signature
   periodicity); headings remap to a strict hierarchy; nav/aside/footer
   demote to link lists; forms stay out of documents (they're
   affordances — the reader's `f` uses them from the bundle).

Every stage is inspectable (`--dump`), every change is measured, across
five suite tiers:

| tier | guards | run |
|---|---|---|
| fixture corpus (10) | emit truths, offline, deterministic | `mdb --selftest` |
| live probes | network truths (hostile CDNs, DNS) | `tests/live_probes.py` |
| agent probes | task truths (the MCP verbs agents ride) | `tests/agent_probes.py` |
| checkin gate | fixtures + 11-site live sweep, every commit | `tests/checkin.py` (pre-commit hook: `--install-hook`) |
| fidelity oracle | pixel truths — screenshots as judge, never extractor | `mdb oracle URL` |
| benchmark | mdb vs other agent web tools: tokens, recall, links, structure, speed, determinism | `tests/benchmark.py` |

The benchmark compares seven approaches (mdb, raw
HTML, tag-strip, Chromium innerText, trafilatura, pandoc, Jina reader)
against ground-truth fact signals that no contender defines. Headline
numbers (2026-07-05): mdb is the only contender with 100% recall AND
navigable links AND surviving structure; raw HTML costs ~9× mdb's
tokens per fact; the pandoc pipeline emits 2 tokens for all of HN.

## History

v1 (a single-file `mdbrowse.py`: fetch → strip → convert → repair) was
retired on 2026-07-04 after the v2 compiler exceeded it on every axis —
see `CHANGELOG.md` and git history. Its best parts (settle heuristic,
binarycookies parser, Safari integration, tracker lists) live on inside
v2.
