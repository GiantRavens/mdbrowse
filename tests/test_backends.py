"""Offline contracts for optional authenticated backends.

No browser, daemon, credentials, or network is touched. These tests assert
the routing manifest, normalization boundary, provenance telemetry, and the
MCP no-silent-auth rule.
"""

from __future__ import annotations

import json
import subprocess
import unittest
from unittest.mock import Mock, patch

from mdb import backends
from mdb.classify import classify
from mdb.emit import emit


X_URL = "https://x.com/example/status/1234567890"
X_SEARCH_URL = "https://x.com/search?q=browser%20agents&src=typed_query"
REDDIT_URL = "https://www.reddit.com/r/test/comments/abc123/a_post/"


def _wall(url=X_URL):
    return {
        "meta": {
            "url": url,
            "fetched_at": "2026-07-23T12:00:00+00:00",
            "mode": "browser",
            "extractor": "test",
        },
        "doc": {
            "title": "X",
            "textLen": 0,
            "anchors": 0,
            "interactive": 0,
            "blocks": [],
        },
    }


class RoutingTests(unittest.TestCase):
    def test_allowlisted_read_commands(self):
        self.assertEqual(
            backends.command_for(X_URL, "opencli"),
            ["opencli", "twitter", "thread", "1234567890", "-f", "md"],
        )
        self.assertEqual(
            backends.command_for(X_URL, "twitter-cli"),
            ["twitter", "tweet", X_URL, "--json"],
        )
        self.assertEqual(
            backends.command_for(REDDIT_URL, "opencli"),
            ["opencli", "reddit", "read", REDDIT_URL, "-f", "md"],
        )
        self.assertEqual(
            backends.command_for("https://x.com/home", "opencli"),
            ["opencli", "twitter", "timeline", "-f", "md"],
        )
        self.assertEqual(
            backends.command_for(X_SEARCH_URL, "twitter-cli"),
            ["twitter", "search", "browser agents", "--json"],
        )
        self.assertEqual(
            backends.command_for("https://x.com/jack", "opencli"),
            ["opencli", "twitter", "profile", "jack", "-f", "md"],
        )
        self.assertIsNone(
            backends.command_for("https://example.com/", "opencli"))

    def test_offer_requires_classified_refusal_and_covered_url(self):
        wall = classify(_wall())
        page = type("Manifest", (), {"shape": "page"})()
        self.assertTrue(backends.should_offer(X_URL, wall))
        self.assertFalse(backends.should_offer(X_URL, page))
        self.assertFalse(
            backends.should_offer("https://example.com/", wall))


class NormalizationTests(unittest.TestCase):
    @patch("mdb.backends.installed", return_value=True)
    def test_twitter_json_normalizes_to_mdb_bundle(self, _installed):
        payload = {
            "ok": True,
            "schema_version": "1",
            "data": {
                "id": "1234567890",
                "text": "The main post",
                "user": {"name": "Example", "username": "example"},
                "media": [{"media_url_https": "https://img.test/main.jpg"}],
                "replies": [{
                    "id": "987",
                    "fullText": "A useful reply",
                    "author": {"displayName": "Reader",
                               "screenName": "reader"},
                }],
            },
        }
        runner = Mock(return_value=subprocess.CompletedProcess(
            args=[], returncode=0, stdout=json.dumps(payload), stderr=""))

        bundle = backends.capture(
            X_URL, "twitter-cli", native_shape="wall", runner=runner)
        manifest = classify(bundle)
        document = emit(bundle, manifest)

        self.assertEqual(bundle["meta"]["backend"], "twitter-cli")
        self.assertEqual(bundle["meta"]["fallback_reason"], "wall")
        self.assertIn("backend: \"twitter-cli\"", document)
        self.assertIn("The main post", document)
        self.assertIn("A useful reply", document)
        self.assertIn("https://img.test/main.jpg", document)
        runner.assert_called_once()

    @patch("mdb.backends.installed", return_value=True)
    def test_opencli_markdown_preserves_content_and_provenance(self, _installed):
        runner = Mock(return_value=subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout="# Thread\n\nAuthenticated result.", stderr=""))

        bundle = backends.capture(
            X_URL, "opencli", native_shape="app", runner=runner)
        document = emit(bundle, classify(bundle))

        self.assertIn("Authenticated result.", document)
        self.assertIn("backend: \"opencli\"", document)
        self.assertIn("fallback_reason: \"app\"", document)

    @patch("mdb.backends.installed", return_value=True)
    def test_twitter_search_normalizes_as_posts_not_replies(self, _installed):
        payload = {
            "ok": True,
            "data": [
                {"id": "1", "text": "First result",
                 "user": {"name": "One", "username": "one"}},
                {"id": "2", "text": "Second result",
                 "user": {"name": "Two", "username": "two"}},
            ],
        }
        runner = Mock(return_value=subprocess.CompletedProcess(
            args=[], returncode=0, stdout=json.dumps(payload), stderr=""))

        bundle = backends.capture(
            X_SEARCH_URL, "twitter-cli", runner=runner)
        document = emit(bundle, classify(bundle))

        self.assertIn("# X search", document)
        self.assertIn("First result", document)
        self.assertIn("Second result", document)
        self.assertNotIn("## Replies", document)

    @patch("mdb.backends.installed", return_value=True)
    def test_backend_failure_is_classified_with_bounded_diagnostic(self, _installed):
        runner = Mock(return_value=subprocess.CompletedProcess(
            args=[], returncode=77, stdout="", stderr="authentication required"))
        with self.assertRaisesRegex(
                backends.BackendError, "exited 77: authentication required"):
            backends.capture(X_URL, "opencli", runner=runner)


class McpConsentTests(unittest.TestCase):
    def test_private_mcp_rejects_authenticated_fallback(self):
        from mdb import mcp as mcp_module

        with self.assertRaisesRegex(ValueError, "private capture"):
            mcp_module._emit_doc(
                X_URL, True, None, 80000, 0,
                allow_external_fallback=True)

    def test_default_mcp_result_offers_but_does_not_invoke_backend(self):
        from mdb import mcp as mcp_module

        external = Mock()
        with patch.object(mcp_module, "_get_bundle", return_value=_wall()), \
                patch("mdb.backends.capture", external):
            result = mcp_module._emit_doc(
                X_URL, False, None, 80000, 0)

        external.assert_not_called()
        self.assertIn("requires confirmation", result)
        self.assertIn('backend="opencli"', result)

    def test_auto_mcp_fallback_emits_backend_telemetry(self):
        from mdb import mcp as mcp_module

        external_bundle = {
            "meta": {
                "url": X_URL,
                "fetched_at": "2026-07-23T12:00:00+00:00",
                "mode": "external-authenticated",
                "extractor": "test",
                "backend": "opencli",
                "fallback_reason": "wall",
            },
            "doc": {
                "title": "X thread",
                "textLen": 100,
                "anchors": 0,
                "interactive": 0,
                "blocks": [{
                    "kind": "p",
                    "landmark": "main",
                    "md": "Authenticated thread content",
                    "text": "",
                    "links": [],
                    "images": [],
                }],
            },
        }
        ready = [backends.BACKENDS["opencli"]]
        with patch.object(mcp_module, "_get_bundle", return_value=_wall()), \
                patch("mdb.backends.candidates", return_value=ready), \
                patch("mdb.backends.capture", return_value=external_bundle):
            result = mcp_module._emit_doc(
                X_URL, False, None, 80000, 0, backend="auto")

        self.assertIn("retried read-only through `opencli`", result)
        self.assertIn("backend: \"opencli\"", result)
        self.assertIn("Authenticated thread content", result)


if __name__ == "__main__":
    unittest.main()
