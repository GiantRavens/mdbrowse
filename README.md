# mdbrowse — a private markdown web browser for your terminal

Fetches a web page, strips the cruft (ads, nav, chrome), converts what's left to
clean Markdown, and renders it in your terminal. Also previews local `.md` files.
The opposite of fighting with w3m.

- **Browses as you.** By default it reads your Safari cookies, so logged-in and
  paywalled-to-you pages render the same content you'd see in Safari. Great for
  OSINT and research. Add `--private` (a.k.a. `--anonymous`) to send **no**
  cookies and add `DNT` + `Sec-GPC` — a fresh, anonymous visit.
- **Pretends to be an iPhone.** Mobile pages are smaller and simpler, so less junk.
- **Reorders for reading.** Pulls `<main>` to the top under the page title, then
  demotes the nav, sidebar, and footer to compact link lists — and deletes
  cookie/consent banners and modal popups outright.
- **Blocks trackers.** In `--js` mode, known analytics/ad hosts are aborted
  (and images/fonts/media skipped during render — you only wanted text).
- **Fast by default**, with a real browser engine on demand (`--js`) for SPAs.
- **Browse mode** (`--browse`) gives w3m-style numbered link-following, usable.
  Tab between links, Space to Quick Look an image, `s` to archive the page.
- **Piggybacks on Safari** — no URL opens your homepage; `--start`/`--bookmarks`/
  `--reading-list` open those; `O` reopens the live page in Safari.
- **Saves clean archives** — `--save` (or `s` in the reader) writes timestamped
  Markdown with YAML front-matter, the shape LLMs and parsers love.
- **Local previews** — point it at a `.md` file; add `--html` for a styled
  browser preview.

## Install

Self-contained: a dedicated virtual environment lives inside the project folder,
and a small wrapper makes `mdbrowse` a command. (Already set up on this machine at
`~/Desktop/mdbrowse`.) To reproduce elsewhere:

```bash
cd ~/Desktop/mdbrowse
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# make `mdbrowse` a command:
mkdir -p ~/bin
printf '#!/bin/zsh\nexec "%s/.venv/bin/python" "%s/mdbrowse.py" "$@"\n' \
  ~/Desktop/mdbrowse ~/Desktop/mdbrowse > ~/bin/mdbrowse
chmod +x ~/bin/mdbrowse
echo 'export PATH="$HOME/bin:$PATH"' >> ~/.zshrc && source ~/.zshrc
```

Everything is contained in `~/Desktop/mdbrowse/.venv` — nothing touches system
Python, and `rm -rf .venv` fully uninstalls.

### Optional: JavaScript rendering (`--js`)

Only for sites that render entirely in the browser (React/Vue SPAs). On macOS
this is self-contained — no system packages, no `sudo`:

```bash
~/Desktop/mdbrowse/.venv/bin/pip install playwright
~/Desktop/mdbrowse/.venv/bin/playwright install chromium
```

## Usage

```bash
mdbrowse                            # open your Safari homepage
mdbrowse https://news.ycombinator.com --browse
mdbrowse README.md                  # preview a local markdown file in the terminal
mdbrowse README.md --html           # ...as a styled HTML page in your browser
mdbrowse --start                    # Safari start page: home + bookmarks + reading list
mdbrowse --bookmarks                # browse your Safari bookmarks
mdbrowse --reading-list             # browse your Safari reading list
mdbrowse example.com --raw          # print the markdown source
mdbrowse https://a-spa.dev --js     # render JS-heavy pages
mdbrowse example.com --full         # convert the whole page, don't strip to "article"
mdbrowse https://news.site --private  # anonymous: no cookies, DNT + Sec-GPC
mdbrowse https://news.site --save     # archive to ~/mdbrowse-archive (timestamped .md)
```

### Browse mode — vim-style navigation

In a real terminal, `--browse` (and your homepage) open a full-screen vim-style
reader. Links are numbered inline (`text [12]`); the selected link is highlighted.

| key | action |
|-----|--------|
| `j` / `k` | scroll down / up |
| `Ctrl-d` / `Ctrl-u` | half-page down / up |
| `Ctrl-f` / `Ctrl-b` | page down / up (also `PgDn` / `PgUp`) |
| `gg` / `G` | jump to top / bottom |
| `Tab` | next link (highlights & scrolls to it) |
| `Shift-Tab` | previous link |
| `Enter` / `o` / click | follow the highlighted (or clicked) link |
| `Space` | Quick Look the topmost on-screen image (else page down) |
| click an image | Quick Look that `🖼 … [IMGn]` image |
| `s` | save a timestamped Markdown archive of this page |
| `p` | open a styled HTML reader preview in your browser |
| `O` | open the live page in Safari (with your session) |
| `H` / `Backspace` | back |
| `r` | reload |
| `/` | search in page (jumps to first match, highlights all) |
| `n` / `N` | next / previous search match |
| `:` | type a URL or local path to go to |
| `?` | show the key map |
| `q` | quit |

The mouse works too: the wheel scrolls, clicking a link follows it, and clicking
an image (`🖼 … [IMGn]`) pops it in Quick Look.

Piping input, or passing `--simple`, falls back to a plain numbered prompt
(`number` to follow, `i<n>` to preview an image, `b` back, `u` new URL, `q` quit).

### Safari integration

No URL → your configured Safari homepage. `--start` shows a menu page built from
your homepage + Reading List + bookmarks (folders preserved), every entry a
followable link. Reads `~/Library/Safari/Bookmarks.plist`, read-only — nothing is
modified. On recent macOS this data is protected: if you see "permission needed,"
grant your terminal **Full Disk Access** (System Settings → Privacy & Security →
Full Disk Access), then reopen the terminal.

### Cookies & privacy

By default mdbrowse reads your Safari cookie jar
(`~/Library/Containers/com.apple.Safari/Data/Library/Cookies/Cookies.binarycookies`,
read-only) so you browse as your logged-in self — the same Full Disk Access
grant as above applies. Cookies are scoped to the requesting host (and honor
`Secure`), so a site only ever receives its own cookies, even across redirects.
Use **`--private`** to send none and add `DNT` + `Sec-GPC` instead. Saved
archives record which mode produced them in their front-matter (`mode:
authenticated` or `mode: private`).

## Flags

| flag | what it does |
|------|--------------|
| `--start` | Safari start page (homepage + bookmarks + reading list) |
| `--bookmarks` | browse your Safari bookmarks |
| `--reading-list` | browse your Safari reading list |
| `--private`, `--anonymous` | send no Safari cookies; add `DNT` + `Sec-GPC` (default is to browse as your logged-in self) |
| `--save` | save a timestamped Markdown archive (to `~/mdbrowse-archive`, or `$MDBROWSE_ARCHIVE`) |
| `--html` | render to styled HTML and open it in your browser |
| `--js` | render with a headless browser engine (for SPAs); seeds your Safari cookies unless `--private`, trackers blocked |
| `--wait SELECTOR` | with `--js`, wait until this CSS selector appears before capturing — for SPAs that paint late (implies `--js`) |
| `--raw` | print the Markdown source instead of the pretty render |
| `--browse` | interactive vim-style navigation / link following |
| `--simple` | use the plain prompt instead of vim-style navigation |
| `--full` | convert the whole page instead of extracting the main article |
| `--width N` | wrap to N columns (default: terminal width) |
| `--no-pager` | print straight to stdout instead of piping through a pager |

## How it works

1. **Fetch** — `httpx` GET with an iPhone User-Agent, sending your Safari
   cookies (read from `Cookies.binarycookies`, scoped per host so they survive
   redirects) — unless `--private`. With `--js`, headless Chromium via Playwright
   in a context seeded with the same cookies, trackers and images/fonts/media
   blocked. Local files are read directly.
2. **Strip & reorder** — `trafilatura` pulls the main article and emits Markdown
   with inline links. Link-heavy / full pages go through a DOM partition that
   extracts `<nav>`/`<aside>`/`<footer>` (demoted to link lists), removes
   cookie/consent/modal chrome, and renders title → main → menu → sidebar →
   footer.
3. **Render** — `rich` paints the Markdown in your terminal, the vim-style reader
   drives navigation, or (`--html` / `p`) a small template renders a styled web
   page. Images become `🖼 … [IMG N]` markers you can Quick Look.

## Notes & limits

- Best on article/content pages. Front pages and dashboards are inherently messy;
  `--browse` or `--full` handle those better than the default reading view.
- Some big sites (e.g. Wikipedia) rate-limit datacenter IPs; from home that's a
  non-issue.
- `--js` needs the one-time `playwright install chromium` step above.
- `--js` waits for content, not the network: it looks for `<main>`/`<article>`,
  nudges lazy content with a scroll, then waits until the page's text stops
  growing (it does *not* use the flaky `networkidle`). If an SPA still captures
  half-rendered, name its content container with `--wait '.article-body'`.
