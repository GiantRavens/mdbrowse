"""Terminal render frontend: rich-painted markdown."""

from urllib.parse import urlparse


def render(md: str, url: str, width: int = 0, use_pager: bool = True) -> None:
    try:
        from rich.console import Console
        from rich.markdown import Markdown
        from rich.rule import Rule
    except ImportError:
        print(md)
        return

    console = Console(width=width if width else None)
    host = urlparse(url).netloc

    def _emit(c):
        c.print(Rule(f"[bold cyan]{host}[/]  [dim]{url}[/]"))
        c.print(Markdown(md, hyperlinks=False))

    if use_pager and console.is_terminal:
        with console.pager(styles=True):
            _emit(console)
    else:
        _emit(console)
