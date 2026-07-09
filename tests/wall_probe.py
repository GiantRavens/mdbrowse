"""Wall-probe harness — the OBSERVE manifest for bot-wall hardening.

Fetches a set of popular sites through ONE Engine and reports classify shape + signals
+ timing, so a fix can be measured (baseline vs patched) instead of guessed. Run:
    .venv/bin/python tests/wall_probe.py [--headed] [--desktop]
"""
import sys, time
from mdb.capture import Engine
from mdb.classify import classify

SITES = [
    ("adobe.com",        "https://www.adobe.com"),
    ("tesla.com",        "https://www.tesla.com"),
    ("nike.com",         "https://www.nike.com"),
    ("ticketmaster.com", "https://www.ticketmaster.com"),
    ("instagram.com",    "https://www.instagram.com"),
    ("g2.com",           "https://www.g2.com"),
    ("wikipedia.org",    "https://en.wikipedia.org/wiki/Akamai_Technologies"),  # control
]

headed = "--headed" in sys.argv
desktop = "--desktop" in sys.argv
mode = "headed-chrome" if headed else ("desktop-safari" if desktop else "iphone-safari")
print(f"=== mode: {mode} ===")
print(f"{'site':18} {'shape':7} {'conf':5} {'ms':>6} {'chars':>6}  title / signals")
print("-" * 92)

ok = walls = 0
with Engine(timeout=25.0, headed=headed, desktop=desktop) as eng:
    for name, url in SITES:
        t0 = time.monotonic()
        try:
            b = eng.capture(url)
            m = classify(b)
            doc = b.get("doc", {})
            title = (doc.get("title") or "")[:32]
            chars = doc.get("textLen") or 0
            sig = ("CHALLENGE " if doc.get("challenge") else "") + \
                  ",".join(f"{k}={v}" for k, v in list((m.signals or {}).items())[:3])
            print(f"{name:18} {m.shape:7} {m.confidence:<5.2f} {int((time.monotonic()-t0)*1000):>6} "
                  f"{chars:>6}  {title}  [{sig}]")
            if m.shape == "wall":
                walls += 1
            elif name != "wikipedia.org":
                ok += 1
        except Exception as e:
            print(f"{name:18} {'ERROR':7} {'-':5} {int((time.monotonic()-t0)*1000):>6}      -  "
                  f"{type(e).__name__}: {str(e)[:46]}")
print("-" * 92)
print(f"RESULT: {ok} content, {walls} wall, of {len(SITES)-1} non-control sites")
