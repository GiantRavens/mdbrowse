"""Plain-render frontend: rich-painted markdown, Goyo-centered.

Rendered block-by-block because rich's Markdown collapses loose lists —
it eats the blank lines our feed emitter puts between items. Splitting on
blank lines (fence-aware) and printing each block separately keeps the
document's own spacing on screen, faithfully.
"""

from urllib.parse import urlparse

GOYO_WIDTH = 88


def _split_blocks(md: str):
    blocks, buf, fence = [], [], False
    for line in md.split("\n"):
        if line.lstrip().startswith("```"):
            fence = not fence
            buf.append(line)
            continue
        if not line.strip() and not fence:
            if buf:
                blocks.append("\n".join(buf))
                buf = []
            continue
        buf.append(line)
    if buf:
        blocks.append("\n".join(buf))
    return blocks


def render(md: str, url: str, width: int = 0, use_pager: bool = True,
           center: bool = True) -> None:
    try:
        from rich.console import Console
        from rich.markdown import Markdown
        from rich.padding import Padding
        from rich.rule import Rule
    except ImportError:
        print(md)
        return

    console = Console()
    term_w = console.width
    content_w = min(width or GOYO_WIDTH, max(20, term_w - 2))
    if center:
        pad_l = max(0, (term_w - content_w) // 2)
    else:
        pad_l = 0
    pad_r = max(0, term_w - content_w - pad_l)
    host = urlparse(url).netloc

    def _emit(c):
        c.print(Rule(f"[bold cyan]{host}[/]  [dim]{url}[/]"))
        c.print()
        for block in _split_blocks(md):
            c.print(Padding(Markdown(block, hyperlinks=False),
                            (0, pad_r, 0, pad_l)))
            c.print()

    if use_pager and console.is_terminal:
        with console.pager(styles=True):
            _emit(console)
    else:
        _emit(console)
