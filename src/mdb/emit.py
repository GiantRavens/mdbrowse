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
    if kind == "form":
        # Lynx-style affordance: a labelled underscore-run field + a submit button.
        # The reader turns this line into a FIELD + BUTTON focusable (edit + submit);
        # in plain markdown it just reads as a visible search box.
        label = (b.get("label") or "Search").strip()
        submit = (b.get("submit_label") or "Search").strip()
        return f"⌗ {label}  {'_' * 28}  [ {submit} ]"
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


def _row_cells(b: dict):
    """Positional per-cell markdown, present only in bundles captured since
    the walker learned tables (2.0.0a6). Older bundles fall through to the
    joined-md row path unchanged."""
    cells = b.get("cells")
    return cells if isinstance(cells, list) and cells else None


def _is_data_table(rows: list) -> bool:
    """Data table vs layout scaffolding: a real table announces itself with
    a header row, or repeats a regular >=2-column grid. Layout tables (HN
    story rows, spacer rows) have irregular cell counts and no headers."""
    if len(rows) < 2:
        return False
    counts = [len(_row_cells(b)) for b in rows]
    if max(counts) < 2:
        return False
    if rows[0].get("header"):
        return True
    return len(set(counts)) == 1


def _table_md(rows: list) -> str:
    """Pipe table from a row run. The first row is the header line (it is
    one when the source used <th>; otherwise markdown's required header
    slot is simply the first data row — the honest choice)."""
    width = max(len(_row_cells(b)) for b in rows)

    def line(cells: list) -> str:
        cells = [c.replace("|", "\\|") for c in cells]
        cells += [""] * (width - len(cells))
        return "| " + " | ".join(cells) + " |"

    out = [line(_row_cells(rows[0])), "|" + " --- |" * width]
    out += [line(_row_cells(b)) for b in rows[1:]]
    return "\n".join(out)


def _region_links(blocks: list) -> str:
    seen, lines = set(), []
    for b in blocks:
        for l in b.get("links") or []:
            if l["href"] in seen:
                continue
            seen.add(l["href"])
            lines.append(f"- [{l['text']}]({l['href']})")
    return "\n".join(lines)


def _is_pager_block(block: dict, pagination: dict) -> bool:
    """True when a content block consists only of detected pager links.

    Detection belongs to the walker; this is deliberately only identity
    matching. It prevents pagination rows from entering feed-unit grouping
    without re-deriving or second-guessing the walker's confidence verdict.
    """
    targets = {p.get("href") for p in (
        pagination.get("prev"), pagination.get("next")) if p}
    links = block.get("links") or []
    hrefs = {link.get("href") for link in links}
    return bool(hrefs) and hrefs <= targets


def _pagination_md(pagination: dict) -> str:
    lines = []
    prev = pagination.get("prev")
    nxt = pagination.get("next")
    if prev:
        lines.append(f"Previous page: [{prev.get('label') or 'Previous'}]({prev['href']})")
    if nxt:
        lines.append(f"Next page: [{nxt.get('label') or 'Next'}]({nxt['href']})")
    return "\n\n".join(lines)


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
    pagination = doc.get("pagination") or {}
    shape = manifest.shape

    if shape == "app":
        s = manifest.signals
        return (f"# {doc.get('title') or bundle['meta']['url']}\n\n"
                f"_This page is an application, not a document "
                f"({s['total_text']} chars of text, {s['interactive']} "
                f"interactive controls). Markdown cannot represent it "
                f"faithfully — open it in a real browser._")

    if shape == "wall":
        challenge = manifest.signals.get("challenge_iframes") or []
        cf = manifest.signals.get("challenge")
        if cf == "cloudflare":
            why = ("a Cloudflare bot-verification challenge ('Just a "
                   "moment…') that did not clear for this headless browser")
        elif challenge:
            why = ("a verification challenge is running in an iframe "
                   f"({challenge[0].split('/')[2]}) that mdb does not enter")
        else:
            why = ("the site served an empty shell to this browser — "
                   "commonly a bot check, or JS that refuses headless engines")
        return (f"# {doc.get('title') or bundle['meta']['url']}\n\n"
                f"_Nothing rendered: {why}. Retry with `--headed` (a real "
                f"browser window — verification walls usually clear for a "
                f"headed session), or open the page in your browser; once "
                f"the site trusts your session again, mdb browses with "
                f"its cookies._")

    # Forms render ONLY via the deduped top-of-body affordance below — drop them from the
    # normal block flow so a form in the body doesn't render twice (top + inline).
    body_blocks = [b for b in blocks
                   if b.get("landmark") not in _CHROME_LANDMARKS
                   and b.get("kind") != "form"
                   and not _is_pager_block(b, pagination)]
    chrome = {lm: [b for b in blocks if b.get("landmark") == lm
                   and not _is_pager_block(b, pagination)]
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

    # Forms (search boxes etc.) live in nav/header chrome that the body filter
    # strips — surface them as a top-of-page affordance regardless of landmark,
    # deduped by (param, action). The reader turns each into a FIELD + BUTTON.
    _seen_forms = set()
    for _b in blocks:
        if _b.get("kind") != "form":
            continue
        _key = (_b.get("param"), _b.get("action"))
        if _key in _seen_forms:
            continue
        _seen_forms.add(_key)
        parts.append(("form", _block_md(_b, level_map, shape)))

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
        # Table-aware walk: consecutive rows of one <table> that read as a
        # data table emit as a pipe table; everything else block-by-block.
        i = 0
        while i < len(body_blocks):
            b = body_blocks[i]
            if b.get("kind") == "row" and _row_cells(b):
                j = i
                while (j < len(body_blocks)
                       and body_blocks[j].get("kind") == "row"
                       and _row_cells(body_blocks[j])
                       and body_blocks[j].get("tbl") == b.get("tbl")):
                    j += 1
                run = body_blocks[i:j]
                if _is_data_table(run):
                    parts.append(("table", _table_md(run)))
                    state["prev_md"] = None
                else:
                    for rb in run:
                        add_block(rb)
                i = j
                continue
            add_block(b)
            i += 1

    out = []
    if title:
        out.append(f"# {title}")
    body = _assemble(parts)
    if body:
        out.append(body)
    pager_md = _pagination_md(pagination)
    if pager_md:
        out.append(f"---\n\n{pager_md}")
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
    # Removal is telemetry, never silent editing: say how many elements
    # the per-host policy dropped (promoted posts, ad slots).
    if meta.get("policy_killed"):
        front["policy_killed"] = meta["policy_killed"]
    if meta.get("image_requests_stubbed"):
        front["image_requests_stubbed"] = meta["image_requests_stubbed"]
    if meta.get("fallback_image_urls"):
        front["fallback_image_urls"] = meta["fallback_image_urls"]
    if meta.get("backend"):
        front["backend"] = meta["backend"]
    if meta.get("fallback_reason"):
        front["fallback_reason"] = meta["fallback_reason"]
    if meta.get("x_engagement_rows"):
        front["x_engagement_rows"] = meta["x_engagement_rows"]
    pagination = doc.get("pagination") or {}
    if pagination.get("next"):
        front["pagination_next"] = pagination["next"]["href"]
    if pagination.get("prev"):
        front["pagination_prev"] = pagination["prev"]["href"]
    fm = "---\n" + "".join(f"{k}: {json.dumps(v, ensure_ascii=False)}\n"
                           for k, v in front.items()) + "---\n\n"
    return fm + body + "\n"
