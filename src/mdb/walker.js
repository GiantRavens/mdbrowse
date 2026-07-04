// mdb in-page walker: the capture stage's extractor.
//
// Runs inside the live page via page.evaluate(), where the layout engine's
// verdicts are queryable facts: computed styles, bounding boxes, visibility,
// stacking. Emits a flat list of leaf blocks — each with landmark region,
// kind, inline-serialized markdown, links, and geometry — plus document meta.
//
// Division of labor: JS owns *inline* serialization (links/bold/code keep
// their positions, which innerText loses); Python owns *block* assembly
// (ordering, regions, heading hierarchy, front-matter). Nothing downstream
// ever re-parses HTML strings.
() => {
  const VPW = Math.max(1, window.innerWidth);
  const VPH = Math.max(1, window.innerHeight);
  const KILL = new Set(["SCRIPT", "STYLE", "NOSCRIPT", "TEMPLATE", "SVG",
                        "IFRAME", "LINK", "META", "CANVAS", "VIDEO", "AUDIO",
                        "OBJECT", "EMBED", "MAP", "DIALOG"]);
  const BLOCKISH = new Set(["block", "flex", "grid", "table", "table-row",
                            "table-cell", "table-row-group", "list-item",
                            "flow-root"]);
  const blocks = [];

  const style = (el) => { try { return getComputedStyle(el); } catch { return null; } };

  function hidden(el, st) {
    if (!st) return true;
    if (st.display === "none" || st.visibility === "hidden") return true;
    if (parseFloat(st.opacity) === 0) return true;
    if (el.getAttribute("aria-hidden") === "true") return true;
    return false;
  }

  // A modal/consent overlay is a *geometric + stacking* fact: pinned
  // positioning, large viewport coverage, AND an explicit raised z-index —
  // modals stack above content; app-shell scroll wrappers (CNN) are also
  // fixed and full-viewport but ride the default stacking layer, and killing
  // them would blank the whole page. No class-name vocabulary needed.
  function overlay(el, st, r) {
    const role = el.getAttribute("role");
    if (role === "dialog" || role === "alertdialog") return true;
    if (el.getAttribute("aria-modal") === "true") return true;
    if (st.position === "fixed" || st.position === "sticky") {
      const cover = (r.width * r.height) / (VPW * VPH);
      const z = parseInt(st.zIndex, 10);
      if (cover > 0.25 && !isNaN(z) && z >= 10) return true;
    }
    return false;
  }

  function landmark(el) {
    if (el.closest("nav,[role=navigation]")) return "nav";
    if (el.closest("aside,[role=complementary]")) return "aside";
    if (el.closest("footer,[role=contentinfo]")) return "footer";
    if (el.closest("header:not(main header):not(article header)")) return "nav";
    if (el.closest("main,[role=main],article")) return "main";
    return "body";
  }

  function absURL(href) {
    try { return new URL(href, document.baseURI).href; } catch { return ""; }
  }

  // Lazy-image resolution: a data: placeholder with the real URL parked in
  // data-src/srcset (WordPress et al.). Same logic the v1 tool learned the
  // hard way, now applied at the source.
  function imgSrc(el) {
    let src = el.currentSrc || el.getAttribute("src") || "";
    if (!src || src.startsWith("data:")) {
      src = el.getAttribute("data-src") || el.getAttribute("data-lazy-src") ||
            el.getAttribute("data-original") || "";
      if (!src) {
        for (const k of ["srcset", "data-srcset", "data-lazy-srcset"]) {
          const v = el.getAttribute(k);
          if (v) { src = v.split(",")[0].trim().split(" ")[0]; break; }
        }
      }
    }
    if (!src || src.startsWith("data:")) return "";
    return absURL(src);
  }

  const escText = (s) => s.replace(/\s+/g, " ")
                          .replace(/([\\`*_[\]])/g, "\\$1");

  // Boundary padding: sites butt inline elements together with no
  // whitespace in the source ("…</a><p>England's…", "Attribution<a>…").
  // Pad only when BOTH sides lack separation — openers before and
  // closers after stay tight, and prose with real spaces is untouched.
  function needsPad(md, nxt) {
    if (!md || /[\s([{"'“‘\/\-–—]$/.test(md)) return false;
    if (!nxt || /^[\s,.;:!?)\]}%'"”’…]/.test(nxt)) return false;
    return true;
  }

  // Inline serializer for a leaf block: text nodes plus A/EM/STRONG/CODE/IMG.
  // Links come out as [text](abs-url) with their exact position preserved.
  function inlineMD(node, out) {
    for (const child of node.childNodes) {
      if (child.nodeType === Node.TEXT_NODE) {
        const t = escText(child.data);
        if (needsPad(out.md, t)) out.md += " ";
        out.md += t;
        continue;
      }
      if (child.nodeType !== Node.ELEMENT_NODE) continue;
      const el = child, tag = el.tagName;
      if (KILL.has(tag)) continue;
      const st = style(el);
      if (hidden(el, st)) continue;
      if (tag === "BR") { out.md += " "; continue; }
      if (tag === "IMG") {
        const src = imgSrc(el);
        if (src) {
          const alt = (el.getAttribute("alt") || "").trim();
          if (needsPad(out.md, "!")) out.md += " ";
          out.md += `![${escText(alt)}](${src})`;
          out.images.push(src);
        }
        continue;
      }
      if (tag === "A") {
        const raw = el.getAttribute("href") || "";
        const href = (!raw || raw.startsWith("#") || raw.startsWith("javascript:")
                      || raw.startsWith("mailto:") || raw.startsWith("tel:"))
                     ? "" : absURL(raw);
        const inner = { md: "", images: out.images, links: out.links };
        inlineMD(el, inner);
        const label = inner.md.trim();
        if (href && href.startsWith("http") && label) {
          if (needsPad(out.md, "[")) out.md += " ";
          out.md += `[${label}](${href})`;
          out.links.push({ text: label, href: href });
        } else {
          if (needsPad(out.md, inner.md)) out.md += " ";
          out.md += inner.md;
        }
        continue;
      }
      if (tag === "STRONG" || tag === "B") {
        const inner = { md: "", images: out.images, links: out.links };
        inlineMD(el, inner);
        const t = inner.md.trim();
        if (t) {
          if (needsPad(out.md, "*")) out.md += " ";
          out.md += `**${t}** `;
        }
        continue;
      }
      if (tag === "EM" || tag === "I") {
        const inner = { md: "", images: out.images, links: out.links };
        inlineMD(el, inner);
        const t = inner.md.trim();
        if (t) {
          if (needsPad(out.md, "*")) out.md += " ";
          out.md += `*${t}* `;
        }
        continue;
      }
      if (tag === "CODE") {
        const t = el.textContent.replace(/\s+/g, " ").trim();
        if (t) {
          if (needsPad(out.md, "`")) out.md += " ";
          out.md += "`" + t + "`";
        }
        continue;
      }
      inlineMD(el, out);
    }
  }

  function serialize(el) {
    const out = { md: "", images: [], links: [] };
    inlineMD(el, out);
    out.md = out.md.replace(/\s+/g, " ")
                   .replace(/\s+([.,;:!?)])/g, "$1").trim();
    return out;
  }

  function push(el, st, r, extra) {
    const b = Object.assign({
      landmark: landmark(el),
      bbox: [Math.round(r.left), Math.round(r.top),
             Math.round(r.width), Math.round(r.height)],
      fontSize: st ? parseFloat(st.fontSize) || 0 : 0,
      bold: st ? (parseInt(st.fontWeight, 10) || 400) >= 600 : false,
    }, extra);
    // Anchor inheritance for blocks that carry text but no links. Two card
    // patterns produce them: (1) a block-level <a> wrapping divs — the walker
    // recurses *through* it, so look up via closest(); (2) the stretched-link
    // card (CNN) — an *empty* overlay <a> beside the text, invisible to
    // inline serialization, so look down via containment. Containment only
    // inherits when exactly one distinct target exists; ambiguity keeps text.
    if (b.md && (!b.links || b.links.length === 0)) {
      let href = "";
      const a = el.closest("a[href]");
      if (a) {
        href = cardHref(a.getAttribute("href"));
      } else {
        const targets = new Set();
        for (const d of el.querySelectorAll("a[href]")) {
          const h = cardHref(d.getAttribute("href"));
          if (h) targets.add(h);
          if (targets.size > 1) break;
        }
        if (targets.size === 1) href = targets.values().next().value;
      }
      if (href) {
        const label = b.md;
        b.md = `[${label}](${href})`;
        b.links = [{ text: label, href: href }];
      }
    }
    blocks.push(b);
  }

  function cardHref(raw) {
    if (!raw || raw.startsWith("#") || raw.startsWith("javascript:")) return "";
    const href = absURL(raw);
    return href.startsWith("http") ? href : "";
  }

  function hasBlockChild(el) {
    for (const c of el.children) {
      if (KILL.has(c.tagName)) continue;
      const st = style(c);
      if (st && BLOCKISH.has(st.display)) return true;
    }
    return false;
  }

  function listDepth(el) {
    let d = 0, p = el.parentElement;
    while (p) { if (p.tagName === "UL" || p.tagName === "OL") d++; p = p.parentElement; }
    return Math.max(0, d - 1);
  }

  function visit(el) {
    const tag = el.tagName;
    if (KILL.has(tag)) return;
    const st = style(el);
    const r = el.getBoundingClientRect();
    if (hidden(el, st)) return;
    if (overlay(el, st, r)) return;

    const h = tag.match(/^H([1-6])$/);
    const ariaHeading = el.getAttribute("role") === "heading";
    if (h || ariaHeading) {
      const s = serialize(el);
      if (s.md) push(el, st, r, {
        kind: "heading",
        level: h ? +h[1] : (parseInt(el.getAttribute("aria-level"), 10) || 2),
        md: s.md, links: s.links, images: s.images,
      });
      return;
    }
    if (tag === "PRE") {
      const t = el.innerText.replace(/\s+$/, "");
      if (t) push(el, st, r, { kind: "code", text: t, md: "", links: [], images: [] });
      return;
    }
    if (tag === "BLOCKQUOTE") {
      const t = el.innerText.replace(/\s+/g, " ").trim();
      if (t) push(el, st, r, { kind: "quote", md: escTextKeep(t), links: [], images: [] });
      return;
    }
    if (tag === "LI") {
      // Own inline content first (excluding nested lists), then recurse into
      // nested lists so their items land at depth+1 in document order.
      const clone = { md: "", images: [], links: [] };
      for (const c of el.childNodes) {
        if (c.nodeType === Node.ELEMENT_NODE &&
            (c.tagName === "UL" || c.tagName === "OL")) continue;
        if (c.nodeType === Node.TEXT_NODE) { clone.md += escText(c.data); continue; }
        if (c.nodeType === Node.ELEMENT_NODE && !KILL.has(c.tagName)) {
          const cst = style(c);
          if (!hidden(c, cst)) inlineMD(c, clone), clone.md += " ";
        }
      }
      const md = clone.md.replace(/\s+/g, " ").trim();
      if (md) push(el, st, r, {
        kind: "li", depth: listDepth(el),
        ordered: el.parentElement && el.parentElement.tagName === "OL",
        md: md, links: clone.links, images: clone.images,
      });
      for (const c of el.children)
        if (c.tagName === "UL" || c.tagName === "OL") visit(c);
      return;
    }
    if (tag === "TR" && !el.querySelector("table")) {
      // Layout-table row (HN story rows): one row, one block. Cells joined
      // in order; the feed emitter later turns link-led rows into bullets.
      const parts = [];
      const rowOut = { md: "", images: [], links: [] };
      for (const cell of el.cells || []) {
        const cst = style(cell);
        if (hidden(cell, cst)) continue;
        const before = rowOut.md.length;
        inlineMD(cell, rowOut);
        const seg = rowOut.md.slice(before).replace(/\s+/g, " ").trim();
        rowOut.md = rowOut.md.slice(0, before);
        if (seg) parts.push(seg);
      }
      const md = parts.join(" ").replace(/\s+/g, " ").trim();
      if (md) push(el, st, r, { kind: "row", md: md,
                                links: rowOut.links, images: rowOut.images });
      return;
    }
    if (tag === "IMG") {
      const src = imgSrc(el);
      if (src && r.width * r.height > 2500) // skip tracking pixels / icons
        push(el, st, r, { kind: "img", md: "",
                          src: src, alt: (el.getAttribute("alt") || "").trim(),
                          links: [], images: [src] });
      return;
    }
    if (tag === "HR") { push(el, st, r, { kind: "hr", md: "", links: [], images: [] }); return; }
    if (tag === "FORM") {
      // GET forms with a text input are actionable without a browser:
      // submitting IS navigation. Captured as bundle data (kind "form"),
      // never emitted into the document — forms are affordances, not
      // content. Password forms are skipped: logging in is Safari's job.
      const method = (el.getAttribute("method") || "get").toLowerCase();
      if (method === "get" && !el.querySelector('input[type="password"]')) {
        const inp = el.querySelector(
          'input[type="search"], input[type="text"], input:not([type])');
        if (inp && inp.name) {
          const hidden = {};
          for (const h of el.querySelectorAll('input[type="hidden"]'))
            if (h.name) hidden[h.name] = h.value || "";
          push(el, st, r, {
            kind: "form", md: "", links: [], images: [],
            action: absURL(el.getAttribute("action") || location.href),
            param: inp.name,
            label: (inp.getAttribute("placeholder")
                    || inp.getAttribute("aria-label") || inp.name).trim(),
            hidden: hidden,
          });
        }
      }
      for (const c of el.children) visit(c);
      return;
    }

    if (!hasBlockChild(el)) {
      const s = serialize(el);
      if (s.md) push(el, st, r, { kind: "p", md: s.md,
                                  links: s.links, images: s.images });
      return;
    }
    for (const c of el.children) visit(c);
  }

  // quote text passes through escText already applied per node in serialize();
  // blockquote uses innerText, so escape once here.
  function escTextKeep(s) { return s.replace(/([\\`*_[\]])/g, "\\$1"); }

  visit(document.body);

  const interactive = document.querySelectorAll(
    "button,input,select,textarea,[role=button],[contenteditable=true]").length;

  const feeds = [];
  for (const l of document.querySelectorAll(
      'link[rel="alternate"][type*="rss"], link[rel="alternate"][type*="atom"]')) {
    const href = absURL(l.getAttribute("href") || "");
    if (href && feeds.length < 5)
      feeds.push({ title: (l.getAttribute("title") || "").trim(),
                   href: href, type: l.getAttribute("type") || "" });
  }

  return {
    url: location.href,
    title: (document.title || "").trim(),
    lang: document.documentElement.lang || "",
    feeds: feeds,
    description: (document.querySelector('meta[name="description"]') || {}).content || "",
    viewport: [VPW, VPH],
    docHeight: Math.round(document.documentElement.scrollHeight),
    interactive: interactive,
    anchors: document.querySelectorAll("a[href]").length,
    blocks: blocks,
  };
}
