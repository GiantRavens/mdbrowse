"""Live form sweep — known-search-form sites must (a) render a Tab-reachable FORM in the
READER path and (b) return results on submit. Guards the whole reader form chain end-to-end:
walker form-detect -> emit_body render -> parse_body FORM focusable -> submit_form -> results.

This is the test that would have caught: the walker missing <textarea> search boxes (google),
and the reader's load() not threading the bundle into parse_body (so no FORM focusable).

Run:  .venv/bin/python tests/form_sweep.py
"""
import sys

from mdb.capture import Engine
from mdb.classify import classify
from mdb.emit import emit_body
from mdb.reader import FORM, parse_body

SITES = [
    ("google.com",      "https://www.google.com",   "freebsd ate my ram"),
    ("duckduckgo.com",  "https://duckduckgo.com",    "freebsd ate my ram"),
    ("reddit.com",      "https://www.reddit.com",    "freebsd"),
    ("wikipedia.org",   "https://en.wikipedia.org",  "Akamai Technologies"),
]


def run() -> bool:
    print(f"{'site':16} {'result':6} form  submit  field")
    print("-" * 60)
    fails = []
    with Engine(timeout=25.0) as eng:
        for name, url, query in SITES:
            try:
                # (a) reader path: exactly what the reader builds — a Tab-reachable FORM focusable
                b = eng.capture(url)
                body = emit_body(b, classify(b))
                _llines, foc = parse_body(body, b)
                forms = [f for f in foc if f.kind == FORM]
                has_form = bool(forms)
                # (b) submit returns real results
                got = False
                param = forms[0].param if forms else "-"
                if forms:
                    rb = eng.submit_form(url, {forms[0].param: query})
                    rm = classify(rb)
                    got = (rm.shape in ("feed", "article", "page")
                           and (rb["doc"].get("textLen") or 0) > 200)
                ok = has_form and got
                fails.append(name) if not ok else None
                print(f"{name:16} {'OK' if ok else 'FAIL':6} {str(has_form):5} "
                      f"{str(got):6}  {param}")
            except Exception as e:
                fails.append(name)
                print(f"{name:16} {'ERROR':6} {type(e).__name__}: {str(e)[:40]}")
    print("-" * 60)
    print(f"form sweep: {len(SITES) - len(fails)}/{len(SITES)} sites OK"
          + (f"  (failed: {', '.join(fails)})" if fails else ""))
    return not fails


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
