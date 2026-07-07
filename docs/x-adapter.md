# X (Twitter) host adapter — design spec

Status: **proposed**
Precedent: `src/mdb/reddit.py` (`is_reddit` → `json_bundle`, wired into
`capture.py` before the browser engine starts).

## 1. Problem

X status pages extract as `shape:"feed"` (0.9 conf, 0.91 coverage) but read
as **numbers without context**:

```
### 17K   ### 131K   ### 307K   ### 21K
```

Investigated (2026-07-06, `x.com/jack/status/20`). Root cause is not a wall
and not aria-strippable — it's three compounding facts:

1. **Icon-conveyed semantics.** The noun for each count (replies / reposts /
   likes / bookmarks) is carried *only* by an adjacent `<svg>` icon. The
   walker's `KILL` set drops SVGs (correct in general), leaving bare counts.
   Live probes found **no reliable `aria-label`** on the engagement buttons
   to recover from — so generic aria-join does NOT solve X.
2. **Nondeterministic hydration.** Across loads the tweet text was a heading
   in one capture and a paragraph in another; metrics were present in one
   load and absent in two. X's virtualized DOM differs per load — fatal to a
   deterministic extractor.
3. **Identity gating.** The headless *desktop* profile returns a ~551-char
   shell; the iPhone+Safari-cookies default renders *more*. So "capture at a
   bigger viewport" (which fixed congruity360) makes X **worse**, not better.

When the DOM is the wrong substrate, the fix is a different substrate — not a
better DOM reader. X provides one, login-free.

## 2. The substrate: syndication JSON

Verified live (`2026-07-06`):

```
GET https://cdn.syndication.twimg.com/tweet-result?id=<ID>&token=<any>
→ {"__typename":"Tweet",
   "text":"just setting up my twttr",
   "created_at":"2006-03-21T20:50:14.000Z",
   "favorite_count":307825,          // Likes  (the "307K")
   "conversation_count":17944,       // Replies (the "17K")
   "user":{"name":"jack","screen_name":"jack","is_blue_verified":true,
           "profile_image_url_https":"…"},
   "entities":{…}, "edit_control":{…} }
```

No login, no SPA, deterministic, **labeled**. This is the exact analogue of
reddit's `.json` fast path. (The minimal `tweet-result` payload carries text,
author, timestamp, `favorite_count`, `conversation_count`, and `entities`
media/urls; repost and bookmark counts are not always present — see §6.)

## 3. Principle

- **Host adapter, browser-free fast path.** Mirror `reddit.py` exactly: a
  `json_bundle`-style function returns a structured bundle, or `None` to fall
  back to the generic walker path unchanged. No new machinery — slot into the
  existing `capture.py` fast-path seam (line ~541).
- **JSON is the judge here, not pixels.** For X, the syndication payload is
  the truth; the rendered SPA is the lossy view. This does not weaken the
  pixels-are-judge invariant for the *walker* — it's a per-host bypass, the
  same exception reddit already earns.
- **Deterministic bundle.** Same `id` → byte-identical body (counts formatted
  once, no per-load variance). Fixes the nondeterminism in §1.2 for free.

## 4. Detection and routing

```python
# x.py
def is_x_status(host, path) -> str | None:
    # x.com / twitter.com / mobile.twitter.com … /<user>/status/<digits>
    # returns the numeric id, or None (profiles, search, home → walker)
```

- Match `(x|twitter|mobile.twitter|nitter?)\.com` host **and**
  `…/status(es)?/<digits>` path. Return the id.
- **Non-status X URLs** (profile, `/home`, `/search`, `/i/…`) return `None`
  → generic walker (which already renders those acceptably, and the nav
  harvest gives them a usable menu — see the dead-status capture, which
  surfaced Home/Search/Grok/Notifications correctly).

Wire in `capture.py` beside reddit:

```python
from .x import is_x_status, x_bundle
xid = is_x_status(host, path)
if not self._headed and not wait_selector and not screenshot_path and xid:
    xb = x_bundle(url, xid, private=self._private)
    if xb is not None:
        return xb
```

## 5. Bundle shaping

Build blocks in reading order (reuse reddit's `_bundle`/`_fmt_count` helpers,
factor them to a shared module or duplicate — small):

```
H1   {name} (@{screen_name}){verified ✓}
p    _{formatted date} · via X_
p    <tweet text, entities linkified: @mentions, #hashtags, t.co→expanded>
img  <media photos; video/GIF → poster image + link>            (kind:"img")
p    _💬 Replies 17,944 · ♻ Reposts — · ♥ Likes 307,825 · 🔖 Bookmarks —_
     (one labeled line; omit a metric when the payload lacks it, never "0"-fake)
row  quoted tweet, if any → indented author + text + link
---  (thread, §6)
```

- **Labels are the whole point:** every count gets its noun. Format with
  thousands separators (`307,825`) and keep the raw in a link title if useful.
- **`entities`** carries `user_mentions`, `hashtags`, `urls` (with
  `expanded_url`) and `media` — linkify inline so `t.co` shortlinks resolve.
- Meta: `mode:"authenticated"`, `source:"x-syndication"`, `shape` will
  classify as `article`/`feed` naturally; can pin `article` for a single tweet.

## 6. Thread / conversation handling

The minimal `tweet-result` gives the focal tweet + `conversation_count`, not
the reply list. Options, in order of preference:

1. **Focal tweet only (Phase 1).** Ship the single labeled tweet + counts +
   media + quoted tweet. Solves the reported problem (numbers-without-context)
   with the smallest, most reliable slice.
2. **Thread (Phase 2).** If a richer endpoint (`TweetDetail` GraphQL or the
   `tweet-result` `parent`/`quoted_tweet` fields) yields replies without auth,
   render them as a reddit-style comment tree (`_comment_blocks` precedent).
   Gate behind availability; `log()` when the thread can't be fetched rather
   than silently showing only the root.

## 7. Failure and fallback (honest, like reddit)

Return `None` (→ walker) when: `--private` (no token/cookies policy), the
endpoint 404s (deleted/protected tweet), non-JSON, or a shape we don't
understand. A protected/age-gated tweet that the API refuses falls through to
the walker, which will show X's own "this post is protected" shell — the
honest outcome. Telemetry: `meta["source"]="x-syndication"` on success so the
fast path's use is visible in front-matter, never silent.

## 8. Test harness

- **fixture `x-status`** — a frozen syndication JSON → bundle → golden, so the
  adapter is covered **offline and deterministically** (no live-X flake in the
  gate; live X is too nondeterministic to assert against, per §1.2).
- Assert: labeled counts present (`Likes 307,825`, `Replies 17,944`), tweet
  text present, author H1, no bare-number-only blocks.
- Optional live smoke (non-gating, like the network-down skip): fetch
  `status/20`, assert `favorite_count` round-trips to a labeled line.

## 9. Broader class this surfaces (shift-left note)

X is best solved by the JSON side door, but the underlying defect —
**an icon-labeled metric losing its noun when the SVG is stripped** — is a
*class* (any engagement bar, rating widget, stat row that labels with icons).
Worth a generic sensor later: a run of adjacent bare-number blocks inside
interactive elements → attempt label recovery from `data-testid` / SVG
`<title>` / nearest `[role=group][aria-label]`, and *count* the ones that stay
label-less as telemetry. Not built here (X doesn't reliably carry those
signals either), but filed so the class is visible, not just the instance.

## 10. Cognitive-honing audit

- **Observe-before-act**: investigation classified X as substrate-mismatch
  (not wall/app) before proposing a fix; the JSON endpoint was validated live
  before it was recommended.
- **Push logic down**: a tested adapter, not a walker special-case.
- **Telemetry**: `source:"x-syndication"`; thread-unavailable logged.
- **Graduation**: Phase 1 focal tweet → Phase 2 thread → possible generic
  icon-metric sensor (§9).
- **Determinism**: JSON in → byte-identical bundle, killing the SPA variance.
