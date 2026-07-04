"""Emit stage: capture bundle + manifest -> deterministic markdown.

Block-level assembly only. Inline serialization (links, emphasis, code)
already happened inside the browser; nothing here re-parses HTML or repairs
converter damage. Determinism is the contract: same bundle + same manifest
-> byte-identical body, hashed into front-matter.
"""

import json
import re

from . import EXTRACTOR_VERSION
from . import units
from .bundle import content_hash
from .classify import is_link_led as _link_led

_CHROME_LANDMARKS = ("nav", "aside", "footer")
_REGION_TITLES = {"nav": "⋯ menu", "aside": "⋯ sidebar", "footer": "⋯ footer"}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _title_of(doc: dict, body_blocks: list) -> str:
    if doc.get("title"):
        return doc["title"]
    for b in body_blocks:
        if b.get("kind") == "heading":
            return re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", b["md"])
    return ""


def _remap_headings(blocks: list) -> dict:
    """Hierarchically perfect: the title is the only H1; body heading levels
    are remapped order-preserving onto 2,3,4,… with no skips."""
    levels = sorted({b["level"] for b in blocks if b.get("kind") == "heading"})
    return {lv: i + 2 for i, lv in enumerate(levels)}


def _block_md(b: dict, level_map: dict, shape: str) -> str:
    kind = b.get("kind")
    if kind == "heading":
        return "#" * min(6, level_map.get(b["level"], 2)) + " " + b["md"]
    if kind == "code":
        return "```\n" + b.get("text", "") + "\n```"
    if kind == "quote":
        return "> " + b["md"]
    if kind == "img":
        return f"![{b.get('alt', '')}]({b['src']})"
    if kind == "hr":
        return "---"
    if kind == "li":
        marker = "1." if b.get("ordered") else "-"
        return "  " * b.get("depth", 0) + f"{marker} {b['md']}"
    if kind == "row":
        # Feed rows read as items; elsewhere they're just lines of content.
        return ("- " + b["md"]) if shape == "feed" else b["md"]
    if kind == "p":
        if shape == "feed" and _link_led(b):
            return "- " + b["md"]
        return b["md"]
    return b.get("md", "")


def _tight(kind: str) -> bool:
    """List items pack without blank lines; everything else gets a blank."""
    return kind in ("li",) or kind == "row"


def _region_links(blocks: list) -> str:
    seen, lines = set(), []
    for b in blocks:
        for l in b.get("links") or []:
            if l["href"] in seen:
                continue
            seen.add(l["href"])
            lines.append(f"- [{l['text']}]({l['href']})")
    return "\n".join(lines)


def _assemble(parts: list) -> str:
    out, prev_kind = [], None
    for kind, text in parts:
        if not text:
            continue
        if out:
            out.append("\n" if (_tight(kind) and _tight(prev_kind)) else "\n\n")
        out.append(text)
        prev_kind = kind
    return "".join(out)


def emit_body(bundle: dict, manifest) -> str:
    doc = bundle["doc"]
    blocks = doc.get("blocks", [])
    shape = manifest.shape

    if shape == "app":
        s = manifest.signals
        return (f"# {doc.get('title') or bundle['meta']['url']}\n\n"
                f"_This page is an application, not a document "
                f"({s['total_text']} chars of text, {s['interactive']} "
                f"interactive controls). Markdown cannot represent it "
                f"faithfully — open it in a real browser._")

    body_blocks = [b for b in blocks if b.get("landmark") not in _CHROME_LANDMARKS]
    chrome = {lm: [b for b in blocks if b.get("landmark") == lm]
              for lm in _CHROME_LANDMARKS}

    # For articles, trust the page's own main landmark when it carries the
    # substance; body-landmark leftovers there are usually related-content rails.
    if shape == "article":
        main_blocks = [b for b in body_blocks if b.get("landmark") == "main"]
        main_text = sum(len(b.get("md", "")) + len(b.get("text", "")) for b in main_blocks)
        if main_text >= 800:
            body_blocks = main_blocks

    level_map = _remap_headings(body_blocks)
    title = _title_of(doc, body_blocks)

    parts = []
    # Skip a body heading that just repeats the title.
    state = {"skipped_dup_title": False, "prev_md": None}

    def add_block(b):
        md = _block_md(b, level_map, shape)
        if not md.strip():
            return
        if (not state["skipped_dup_title"] and b.get("kind") == "heading" and title
                and (_norm(b["md"]) == _norm(title) or _norm(b["md"]) in _norm(title))):
            state["skipped_dup_title"] = True
            return
        if md == state["prev_md"]:   # mobile templates love duplicating blocks
            return
        state["prev_md"] = md
        # Feed bullets are "item" parts: loose-list spacing (blank line
        # between items), because feed lines are long and wrap — packed
        # tight they read as a wall of text. Article lists stay tight.
        kind = b.get("kind")
        if shape == "feed" and md.startswith("- "):
            kind = "item"
        parts.append((kind, md))

    if shape == "feed":
        # Repeated-unit detection: fragment runs collapse to one line per
        # item; section labels become pseudo-headings; everything else
        # (headings, prose) passes through the normal block path.
        for seg_kind, payload in units.segment(body_blocks):
            if seg_kind == "block":
                if units.is_boundary(payload):
                    parts.append(("heading", "### " + payload["md"]))
                else:
                    add_block(payload)
                continue
            if len(payload) < units.MIN_RUN:
                for b in payload:
                    add_block(b)
                continue
            for unit in units.detect_units(payload):
                line = units.unit_markdown(unit)
                if line and line != state["prev_md"]:
                    state["prev_md"] = line
                    parts.append(("item", line))
    else:
        for b in body_blocks:
            add_block(b)

    out = []
    if title:
        out.append(f"# {title}")
    body = _assemble(parts)
    if body:
        out.append(body)
    for lm in _CHROME_LANDMARKS:
        links = _region_links(chrome[lm])
        if links:
            out.append(f"---\n\n## {_REGION_TITLES[lm]}\n\n{links}")

    md = "\n\n".join(out)
    return re.sub(r"\n{3,}", "\n\n", md).strip()


def emit(bundle: dict, manifest) -> str:
    """Full document: YAML front-matter (provenance + manifest verdict +
    body hash) followed by the deterministic body."""
    body = emit_body(bundle, manifest)
    meta = bundle["meta"]
    doc = bundle["doc"]
    front = {
        "title": doc.get("title") or meta["url"],
        "source": meta["url"],
        "retrieved": meta["fetched_at"],
        "mode": meta["mode"],
        "shape": manifest.shape,
        "confidence": manifest.confidence,
        "extractor": meta.get("extractor", EXTRACTOR_VERSION),
        "hash": content_hash(body),
    }
    fm = "---\n" + "".join(f"{k}: {json.dumps(v, ensure_ascii=False)}\n"
                           for k, v in front.items()) + "---\n\n"
    return fm + body + "\n"
