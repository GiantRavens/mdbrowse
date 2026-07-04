"""Speech frontend: the page talks, via macOS `say`.

Builds spoken text from the reader's logical lines (labels already clean:
no URLs, no markdown syntax). Structure becomes prosody with embedded
`[[slnc N]]` silences — the audio version of the loose-list fix:

  headings   -> "Section: …" with a long pause before
  feed items -> item text with a pause between items
  code       -> "Code block, N lines, skipped." (reading code aloud is
                torture; the reader is one keypress away if needed)
  quotes     -> "Quote: …"

Content is sanitized so a page can't inject say-commands: literal "[["
never reaches the synthesizer.

Voice: MDBROWSE_VOICE or --voice; otherwise the system default.
"""

import os
import subprocess
import tempfile

PAUSE_ITEM = "[[slnc 400]]"
PAUSE_PARA = "[[slnc 300]]"
PAUSE_SECTION = "[[slnc 700]]"


def _seg_text(segs) -> str:
    parts = []
    for text, _fid in segs:
        parts.append(text.replace("🖼  ", " image: ").replace("🖼", " image "))
    s = " ".join(" ".join(parts).split())
    return s.replace("[[", "( (")     # no say-command injection from content


def from_llines(llines, start: int = 0) -> str:
    """Logical lines -> speakable text with prosody pauses."""
    out, code_run = [], 0
    for ll in llines[start:]:
        if ll.style == "code":
            code_run += 1
            continue
        if code_run:
            out.append(f"Code block, {code_run} lines, skipped. {PAUSE_PARA}")
            code_run = 0
        if ll.style == "hr":
            out.append(PAUSE_SECTION)
            continue
        if not ll.segs:
            continue
        t = _seg_text(ll.segs)
        if not t:
            continue
        if ll.style == "h":
            out.append(f"{PAUSE_SECTION} Section: {t}. {PAUSE_PARA}")
        elif ll.style == "q":
            out.append(f"Quote: {t} {PAUSE_PARA}")
        elif ll.indent or t.startswith("- "):
            out.append(f"{t.lstrip('- ')} {PAUSE_ITEM}")
        else:
            out.append(f"{t} {PAUSE_PARA}")
    if code_run:
        out.append(f"Code block, {code_run} lines, skipped.")
    return "\n".join(out)


def _say_cmd(voice: str = None):
    cmd = ["say"]
    v = voice or os.environ.get("MDBROWSE_VOICE")
    if v:
        cmd += ["-v", v]
    return cmd


def speak(text: str, voice: str = None) -> subprocess.Popen:
    """Start speaking in the background; returns the process (kill to stop).
    Text goes via a temp file — pages outrun ARG_MAX."""
    fd, path = tempfile.mkstemp(suffix=".txt", prefix="mdb_say_")
    os.write(fd, text.encode("utf-8"))
    os.close(fd)
    return subprocess.Popen(_say_cmd(voice) + ["-f", path],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)


def stop(proc) -> None:
    if proc is not None and proc.poll() is None:
        try:
            proc.terminate()
        except Exception:
            pass


def render_to_file(text: str, out_path: str, voice: str = None) -> bool:
    """Render speech to an audio file (silent — used by tests, and handy
    for 'give me this article as audio')."""
    fd, path = tempfile.mkstemp(suffix=".txt", prefix="mdb_say_")
    os.write(fd, text.encode("utf-8"))
    os.close(fd)
    r = subprocess.run(_say_cmd(voice) + ["-f", path, "-o", out_path],
                       capture_output=True)
    return r.returncode == 0 and os.path.getsize(out_path) > 0
