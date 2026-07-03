"""Capture bundle I/O. Bundles are the fixture format: captured once,
re-emitted forever, so classify/emit changes are testable offline."""

import hashlib
import json


def save(bundle: dict, path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(bundle, f, ensure_ascii=False, indent=1, sort_keys=True)


def load(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def content_hash(body_md: str) -> str:
    """Hash of the markdown *body* (front-matter excluded, so `retrieved`
    timestamps don't defeat change detection). 'Did this page change?' is a
    string compare on this value."""
    return hashlib.sha256(body_md.encode("utf-8")).hexdigest()[:16]
