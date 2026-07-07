# Pagination affordance — design spec

Status: **proposed**
Author seed: reader observation that HN's `More` (`?p=2`) link is captured
in the feed body but is only a plain link you follow by hand.

## 1. Problem

Many pages are page 1 of N: HN (`?p=2`), search results, blog archives
(`/page/2/`), forums, MediaWiki category listings, API-style feeds. The
"next page" link is *in* the page, but the reader treats it as ordinary
body content — so walking a multi-page thread means eyeballing the link,
yanking the URL, and re-fetching by hand. mdb already turns two other
non-body signals into first-class affordances:

- **GET search forms** → `kind:"form"` bundle blocks → reader `f`
- **RSS/Atom feeds** → `doc["feeds"]` → reader `F`

Pagination is the same shape: a *navigation affordance*, not content.
This spec adds a third, following those precedents exactly.

## 2. Principle

- **Affordance, not content.** Detected pagination is document-level
  metadata (`doc["pagination"]`), mirroring `doc["feeds"]`. It is
  *additive* — the body is NOT edited. Pixels stay the judge for the
  body; the "More" link keeps rendering where the extractor put it. This
  keeps the determinism contract and the feed extractor untouched.
- **Two signals, honest confidence.** Prefer the semantic standard
  (`rel=next`); fall back to a lexical+structural heuristic; never guess
  from lexical text alone. Record *how* each candidate was found (`via`)
  and a confidence — Level-2 telemetry, same discipline as the menu and
  skip-link fixes (structural AND lexical, both required).
- **Stateless chaining.** Each page self-describes its own next/prev, so
  the reader needs no cursor: `n` on page 2 re-detects page 2's `?p=3`.
  Pagination is just a pre-resolved `("go", url)` — it reuses the reader's
  existing fetch + history machinery verbatim (so `H` backs out of page 2).

## 3. Detection (walker) — OODA, cheapest signal first

A new harvest pass after `visit(document.body)`, beside the feeds and nav
harvests. Emits one `pagination` object (or `null`). Candidates are scored
and the best `next` / `prev` kept.

| Tier | Signal | `via` | conf | Notes |
|---|---|---|---|---|
| 1 | `<link rel="next"/"prev">` in `<head>` | `rel` | 0.95 | RFC 8288 web linking; zero ambiguity. Same place feeds are harvested. |
| 1 | `<a rel="next"/"prev">` in body | `rel` | 0.95 | WordPress, MediaWiki, many blogs emit these. |
| 2 | anchor whose text matches the next/prev vocab **and** whose href differs from the current URL only in a pagination **query param** (`?p=`, `?page=`, `?start=`, `?offset=`, `?after=`) | `param` | 0.8 | HN's `More` → `?p=2`. Learn the param name here. |
| 2 | ... differs only in a trailing **numeric path segment** (`/page/2/`, `/2/`) | `path` | 0.7 | archive-style URLs. |
| — | lexical text only, href unrelated to current URL | — | drop | too weak — that's a "more info" content link, not pagination. |

Vocabulary (case-insensitive, anchored, short — `<= 24` chars):
- **next**: `next`, `next page`, `more`, `load more`, `show more`,
  `older`, `older posts`, `older entries`, `»`, `→`, `›`, `⟩`
- **prev**: `previous`, `prev`, `newer`, `newer posts`, `back`,
  `«`, `←`, `‹`, `⟨`

Safety rails (mirror the skip-link/menu discipline):
- Tier-2 candidates require **same-origin** and a **structural URL delta**
  (param or path segment) vs the current page — the lexical match alone is
  never sufficient.
- A candidate whose resolved href `==` current URL is dropped (that's the
  disabled/last-page state — chain terminates correctly).
- `href="#…"`, `javascript:`, and non-http drop (reuse `cardHref`).
- **Button-only "Load more"** (no `href`, JS-driven infinite scroll) is
  *detected but unusable* browser-free → not emitted in Phase 1; counted
  in telemetry as `pagination_js_only` so the gap is visible, not silent.

### Bundle shape

```jsonc
"pagination": {
  "next": { "href": "https://news.ycombinator.com/?p=2",
            "label": "More", "via": "param", "confidence": 0.8 },
  "prev": null,
  "param": "p",              // when known (tier-2 param), enables synth-prev
  "candidates": 1            // how many next-ish anchors were seen (telemetry)
}
```

Top-level `doc["pagination"]`, exactly like `doc["feeds"]`. Absent/`null`
when nothing qualifies (correct for infinite-scroll SPAs — see §7).

## 4. Emit

- Body: **unchanged** (additive principle).
- Front-matter: add `pagination_next` / `pagination_prev` (bare URLs) when
  present, so a saved `.md`, the MCP `fetch_page` result, and an agent can
  all see the chain without re-parsing. Gated behind presence so existing
  goldens without pagination are byte-identical.

## 5. Reader UX

Key choice, checked against the live bind table: `n`/`N` are **taken**
(search-repeat from `/`), and `[` and `<` are bound too. Free and
mnemonic: **`.`** = next page, **`,`** = prev page — the conventional
"step forward / back" pair (`p` is also free if a letter is preferred,
but `,`/`.` avoids the search-`n` confusion and reads as a pair).

- `.` → if `doc["pagination"]["next"]`: `return ("go", next.href)`.
  Pushes history (existing machinery) so `H` returns to the prior page.
  Else `self.msg = "no next page detected"`.
- `,` → symmetric. If `prev` is null but `param` is known and the current
  URL carries it with value > 1, **synthesize** the prev URL (decrement) —
  low-cost, only when the param is confirmed by a real next link.
- Hint line (beside "RSS: F", "search form: f"): add **"next: ."** when
  `pagination.next` exists (and "prev: ," when applicable).

Chaining is automatic: page 2's capture yields its own `next` → `?p=3`.
No reader-side cursor state.

## 6. Phasing (graduation path)

- **Phase 1 (this spec)** — detect → `doc["pagination"]` → reader `n`/`p`
  jump + hint + front-matter. Smallest useful slice.
- **Phase 2 — continuous read.** `N` (or a `--paginate=K` capture flag)
  fetches up to K next-pages and concatenates their bodies into one scroll
  (dedup by item URL). Bounded, `log()`s where it stopped (cap hit / chain
  ended / dup ratio) — no silent truncation.
- **Phase 3 — programmatic.** MCP `fetch_page` already returns front-matter;
  surfacing `pagination_next` lets an agent walk "read the whole thread"
  without a browser. A thin `mdb --walk URL --pages K` CLI falls out of
  Phase 2's engine.

## 7. Interaction with infinite-scroll SPAs (the X.com case)

Sites like x.com paginate by JS fetch, not links — there is no `next`
anchor to detect, so `doc["pagination"]` is correctly `null`. That is the
*honest* outcome (we don't fabricate a chain we can't follow), and it's a
separate problem from *rendering* those pages, tracked elsewhere. The
`pagination_js_only` counter (§3) makes the "there's a Load-more button we
can't use" case visible rather than silent.

## 8. Test harness

- **hn** — extend the existing gate row: assert
  `bundle["doc"]["pagination"]["next"]["href"]` endswith `?p=2`, `via ==
  "param"`.
- **pydocs** — `docs.python.org` ships `<link rel="next">`; assert
  `via == "rel"`, confidence 0.95. (Already a gate site — free coverage.)
- New fixture `paginated-*` frozen bundle so the walker→pagination path is
  covered offline (goldens stay green; new assertion is additive).
- Determinism: pagination is a pure function of the DOM — no new nondeterminism.

## 9. Cognitive-honing audit

- **Manifest**: candidates scored with `via`+confidence before any follow.
- **Telemetry**: `via`, `candidates`, `pagination_js_only` — says *why*,
  not just *that*.
- **Shift-left**: one detector fixes the whole paginated-site class, no
  per-host list.
- **Graduation**: Phase 1 reader keystroke → Phase 2 engine → Phase 3
  CLI/MCP, each earning the next.
- **Sharpness**: two gate rows (param + rel) guard both detection tiers.
