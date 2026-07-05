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
  wall     nothing rendered at all          -> classified refusal (bot
           challenge / verification interstitial; the giveaway is a
           captcha-delivery iframe over an empty body — wsj.com's DataDome)
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
    prose_chars = sum(visible_len(b.get("md", "")) for b in prose_blocks)
    link_led = [b for b in blocks
                if b.get("kind") in ("p", "li", "row") and is_link_led(b)]
    total_text = sum(len(b.get("md", "")) + len(b.get("text", ""))
                     for b in blocks)
    main_text = sum(len(b.get("md", "")) + len(b.get("text", ""))
                    for b in blocks if b.get("landmark") == "main")
    main_share = main_text / max(1, total_text)
    interactive = doc.get("interactive", 0)

    # Coverage: how much of the page's rendered text did the walker
    # actually capture? A low ratio on a text-bearing page is the
    # walker-missed-content class (aria-hidden carousels, namespace
    # leaks) surfacing as a number instead of a captain's report.
    captured = sum(visible_len(b.get("md", "")) + len(b.get("text", ""))
                   for b in blocks)
    page_text = doc.get("textLen", 0)

    signals = {
        "blocks": len(blocks),
        "total_text": total_text,
        "coverage": round(captured / page_text, 2) if page_text else None,
        "prose_blocks": len(prose_blocks),
        "prose_chars": prose_chars,
        "link_led_blocks": len(link_led),
        "main_share": round(main_share, 2),
        "interactive": interactive,
        "anchors": doc.get("anchors", 0),
    }

    # Wall: nothing rendered — no text, no links, no controls. A silent
    # one-line ghost is a lie; say what happened. A captcha/challenge
    # iframe over the empty body names the cause with confidence.
    if total_text < 40 and doc.get("anchors", 0) <= 2 and interactive <= 2:
        challenge = [f for f in doc.get("iframes", [])
                     if re.search(r"captcha|challenge|datadome|perimeterx"
                                  r"|px-cloud|turnstile|cf-chl", f, re.I)]
        signals["challenge_iframes"] = challenge
        return Manifest("wall", 0.9 if challenge else 0.6, signals)

    # App: barely any document to speak of, lots of controls.
    if total_text < 400 and interactive > 20:
        return Manifest("app", 0.8, signals)

    # An article-grade prose mass overrides the feed count: news sites
    # bury the story under recommendation rails (foxnews: 49 link-led
    # blocks around 15 paragraphs), and repetition must not outvote
    # substance. Real fronts never carry this much prose — corpus max
    # is nasa-front at 6 blocks / 1298 chars; articles run 15-31 blocks.
    buried_article = len(prose_blocks) >= 8 and prose_chars >= 2000

    # Feed: the page is substantially a run of link-led items.
    if (not buried_article
            and len(link_led) >= 15 and len(link_led) > 2 * len(prose_blocks)):
        conf = 0.9 if len(link_led) >= 25 else 0.7
        return Manifest("feed", conf, signals)

    # Article: a real prose mass dominates.
    if len(prose_blocks) >= 4 and total_text >= 1500:
        conf = 0.9 if (main_share > 0.5 or len(prose_blocks) >= 8) else 0.6
        return Manifest("article", conf, signals)

    return Manifest("page", 0.5, signals)
