"""Classify stage: cheap page-shape verdict before any emission.

The manifest step — observe before you act. Signals are counts over the
capture bundle; no network, no DOM, milliseconds. The verdict (and its
confidence) travels with the document in front-matter, so downstream
consumers never re-derive what kind of thing they're holding.

Shapes:
  article  one dominant prose mass          -> prose emitter, regions demoted
  feed     run of link-led items (HN, blog index) -> one bullet per item
  page     mixed/unknown document           -> generic: everything, in order
  app      thin text, dense interactivity   -> classified refusal
"""

import re
from dataclasses import dataclass, field


@dataclass
class Manifest:
    shape: str
    confidence: float
    signals: dict = field(default_factory=dict)


def visible_len(md: str) -> int:
    """Length of what a reader sees: link syntax reduced to its label, image
    syntax dropped. Raw md length lies — URLs (HN's tokenized hide-links!)
    dwarf the visible text."""
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", md)
    t = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", t)
    return len(t.strip())


def is_link_led(b: dict) -> bool:
    """A block whose visible text is essentially its link(s): a feed item."""
    links = b.get("links") or []
    if not links:
        return False
    vis = visible_len(b.get("md", ""))
    link_len = sum(len(l["text"]) for l in links)
    return vis > 0 and link_len / vis >= 0.6


def classify(bundle: dict) -> Manifest:
    doc = bundle["doc"]
    blocks = doc.get("blocks", [])

    prose_blocks = [b for b in blocks
                    if b.get("kind") in ("p", "quote")
                    and visible_len(b.get("md", "")) >= 120
                    and not is_link_led(b)]
    link_led = [b for b in blocks
                if b.get("kind") in ("p", "li", "row") and is_link_led(b)]
    total_text = sum(len(b.get("md", "")) + len(b.get("text", ""))
                     for b in blocks)
    main_text = sum(len(b.get("md", "")) + len(b.get("text", ""))
                    for b in blocks if b.get("landmark") == "main")
    main_share = main_text / max(1, total_text)
    interactive = doc.get("interactive", 0)

    signals = {
        "blocks": len(blocks),
        "total_text": total_text,
        "prose_blocks": len(prose_blocks),
        "link_led_blocks": len(link_led),
        "main_share": round(main_share, 2),
        "interactive": interactive,
        "anchors": doc.get("anchors", 0),
    }

    # App: barely any document to speak of, lots of controls.
    if total_text < 400 and interactive > 20:
        return Manifest("app", 0.8, signals)

    # Feed: the page is substantially a run of link-led items.
    if len(link_led) >= 15 and len(link_led) > 2 * len(prose_blocks):
        conf = 0.9 if len(link_led) >= 25 else 0.7
        return Manifest("feed", conf, signals)

    # Article: a real prose mass dominates.
    if len(prose_blocks) >= 4 and total_text >= 1500:
        conf = 0.9 if (main_share > 0.5 or len(prose_blocks) >= 8) else 0.6
        return Manifest("article", conf, signals)

    return Manifest("page", 0.5, signals)
