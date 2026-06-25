# mdbrowse — a private markdown web browser for your terminal

Fetches a web page, strips the cruft (ads, nav, chrome), converts what's left to
clean Markdown, and renders it in your terminal. Also previews local `.md` files.
The opposite of fighting with w3m.

- **Pretends to be an iPhone.** Mobile pages are smaller and simpler, so less junk.
- **Carries no state.** No cookies sent, none stored. Sends `DNT` + `Sec-GPC`.
  Every load is a fresh anonymous visit.
- **Blocks trackers.** In `--js` mode, known analytics/ad hosts are aborted
  (and images/fonts/media skipped — you only wanted text).
- **Fast by default**, with a real browser engine on demand (`--js`) for SPAs.
- **Browse mode** (`--browse`) gives w3m-style numbered link-following, usable.
- **Piggybacks on Safari** — no URL opens your homepage; `--start`/`--bookmarks`/
  `--reading-list` open those.
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
```

### Browse mode — vim-style navigation

In a real terminal, `--browse` (and your homepage) open a full-screen vim-style
reader. Links are numbered inline (`text [12]`); the selected link is highlighted.

| key | action |
|-----|--------|
| `j` / `k` | scroll down / up |
| `Ctrl-d` / `Ctrl-u` | half-page down / up |
| `Space` / `Ctrl-b` | page down / up |
| `gg` / `G` | jump to top / bottom |
| `Tab` | next link (highlights & scrolls to it) |
| `Shift-Tab` | previous link |
| `Enter` / `o` | follow the highlighted link |
| `H` / `Backspace` | back |
| `r` | reload |
| `/` | search in page (jumps to first match, highlights all) |
| `n` / `N` | next / previous search match |
| `:` | type a URL or local path to go to |
| `?` | show the key map |
| `q` | quit |

Piping input, or passing `--simple`, falls back to a plain numbered prompt
(`number` to follow, `b` back, `u` new URL, `q` quit).

### Safari integration

No URL → your configured Safari homepage. `--start` shows a menu page built from
your homepage + Reading List + bookmarks (folders preserved), every entry a
followable link. Reads `~/Library/Safari/Bookmarks.plist`, read-only — nothing is
modified. On recent macOS this data is protected: if you see "permission needed,"
grant your terminal **Full Disk Access** (System Settings → Privacy & Security →
Full Disk Access), then reopen the terminal.

## Flags

| flag | what it does |
|------|--------------|
| `--start` | Safari start page (homepage + bookmarks + reading list) |
| `--bookmarks` | browse your Safari bookmarks |
| `--reading-list` | browse your Safari reading list |
| `--html` | render to styled HTML and open it in your browser |
| `--js` | render with a headless browser engine (for SPAs); cookie-free, trackers blocked |
| `--raw` | print the Markdown source instead of the pretty render |
| `--browse` | interactive vim-style navigation / link following |
| `--simple` | use the plain prompt instead of vim-style navigation |
| `--full` | convert the whole page instead of extracting the main article |
| `--width N` | wrap to N columns (default: terminal width) |
| `--no-pager` | print straight to stdout instead of piping through a pager |

## How it works

1. **Fetch** — `httpx` GET with an iPhone User-Agent and no cookies (or, with
   `--js`, headless Chromium via Playwright in a fresh isolated context with
   trackers and images/fonts/media blocked). Local files are read directly.
2. **Strip** — `trafilatura` pulls the main article and emits Markdown, keeping
   inline links. Link-heavy index pages fall back to a full-page conversion so
   navigation still works.
3. **Render** — `rich` paints the Markdown in your terminal, or (`--html`) a
   small template renders it as a styled web page.

## Notes & limits

- Best on article/content pages. Front pages and dashboards are inherently messy;
  `--browse` or `--full` handle those better than the default reading view.
- Some big sites (e.g. Wikipedia) rate-limit datacenter IPs; from home that's a
  non-issue.
- `--js` needs the one-time `playwright install chromium` step above.
