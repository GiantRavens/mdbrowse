"""Safari integration: start page (read) and Reading List saves (write).

READ — homepage, bookmarks, and Reading List come from
~/Library/Safari/Bookmarks.plist, strictly read-only (Full Disk Access
required on modern macOS; the error page explains how to grant it).

WRITE — one verb only: add the current page to the Reading List, via
AppleScript ('tell application "Safari" to add reading list item ...').
Never write Bookmarks.plist directly — iCloud sync owns that file and
will clobber or corrupt concurrent edits. The AppleScript route goes
through Safari itself, so the item syncs to all devices properly.
"""

import os
import plistlib
import subprocess

BOOKMARKS_PLIST = os.path.expanduser("~/Library/Safari/Bookmarks.plist")
_SKIP_FOLDERS = {"BookmarksBar", "BookmarksMenu", "com.apple.ReadingList"}

PERMISSION_PAGE = (
    "# Safari — permission needed\n\n"
    "macOS protects Safari's data. Give your terminal **Full Disk Access**:\n\n"
    "1. System Settings → Privacy & Security → **Full Disk Access**\n"
    "2. Enable your terminal app (Terminal, iTerm, …)\n"
    "3. Quit and reopen the terminal, then try again."
)


def homepage():
    try:
        r = subprocess.run(["defaults", "read", "com.apple.Safari", "HomePage"],
                           capture_output=True, text=True, timeout=5)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except Exception:
        pass
    return None


def _walk(node, folder, out, reading):
    kind = node.get("WebBookmarkType")
    if kind == "WebBookmarkTypeLeaf":
        url = node.get("URLString", "")
        title = (node.get("URIDictionary") or {}).get("title") or url
        (reading if "ReadingList" in node else out).append((folder, title, url))
        return
    title = node.get("Title", "")
    nxt = folder
    if title and title not in _SKIP_FOLDERS:
        nxt = f"{folder} / {title}" if folder else title
    for child in node.get("Children", []) or []:
        _walk(child, nxt, out, reading)


def read_bookmarks():
    """(bookmarks, reading_list) as lists of (folder, title, url).
    Raises PermissionError / FileNotFoundError for the caller to page."""
    with open(BOOKMARKS_PLIST, "rb") as f:
        data = plistlib.load(f)
    out, reading = [], []
    for child in data.get("Children", []) or []:
        _walk(child, "", out, reading)
    return out, reading


def _md_list(items):
    lines = []
    for folder, title, url in items:
        if not url:
            continue
        label = f"{folder} / {title}" if folder else title
        lines.append(f"- [{label}]({url})")
    return lines


def page_markdown(kind: str) -> str:
    """Render a safari: pseudo-page ('start' | 'bookmarks' | 'reading')."""
    try:
        bookmarks, reading = read_bookmarks()
    except FileNotFoundError:
        return f"# Safari\n\nNo Safari bookmarks found at `{BOOKMARKS_PLIST}`."
    except PermissionError:
        return PERMISSION_PAGE

    if kind == "reading":
        body = _md_list(reading) or ["_(reading list is empty)_"]
        return "# Safari Reading List\n\n" + "\n\n".join(body)
    if kind == "bookmarks":
        body = _md_list(bookmarks) or ["_(no bookmarks)_"]
        return "# Safari Bookmarks\n\n" + "\n\n".join(body)

    home = homepage()
    parts = ["# Safari"]
    if home:
        parts.append(f"## Homepage\n\n- [{home}]({home})")
    if reading:
        parts.append("## Reading List\n\n" + "\n\n".join(_md_list(reading)))
    parts.append("## Bookmarks\n\n"
                 + ("\n\n".join(_md_list(bookmarks)) or "_(none)_"))
    return "\n\n".join(parts)


def add_reading_list(url: str, title: str = None) -> bool:
    """Add a URL to the Safari Reading List (launches Safari if needed;
    first use asks for Automation permission: Terminal → Safari)."""
    if not url.startswith(("http://", "https://")):
        return False
    esc = lambda s: s.replace("\\", "\\\\").replace('"', '\\"')
    if title:
        script = (f'tell application "Safari" to add reading list item '
                  f'"{esc(url)}" with title "{esc(title)}"')
    else:
        script = f'tell application "Safari" to add reading list item "{esc(url)}"'
    try:
        r = subprocess.run(["osascript", "-e", script],
                           capture_output=True, text=True, timeout=15)
        return r.returncode == 0
    except Exception:
        return False
