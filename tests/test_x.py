"""Offline contracts for X's native bundle normalization."""

import unittest

from mdb.x import compact_engagement_rows


def _metric(x, action, count, y=734):
    return {
        "landmark": "main",
        "bbox": [x, y, 30, 20],
        "fontSize": 15,
        "bold": False,
        "kind": "p",
        "md": count,
        "links": [],
        "images": [],
        "uiAction": action,
    }


def _views(count="248K", y=734):
    url = "https://x.com/example/status/1/analytics"
    return {
        "landmark": "main",
        "bbox": [718, y, 41, 20],
        "fontSize": 15,
        "bold": False,
        "kind": "p",
        "md": f"[{count}]({url})",
        "links": [{"text": count, "href": url}],
        "images": [],
    }


class EngagementRowTests(unittest.TestCase):
    def test_full_row_compacts_with_web_order_and_labels(self):
        doc = {"blocks": [
            _metric(366, "reply", "47"),
            _metric(483, "retweet", "34"),
            _metric(601, "like", "481"),
            _views(),
        ]}

        count = compact_engagement_rows(doc, "https://x.com/home")

        self.assertEqual(count, 1)
        self.assertEqual(len(doc["blocks"]), 1)
        self.assertEqual(
            doc["blocks"][0]["md"],
            "_Replies 47 · Reposts 34 · Likes 481 · "
            "Views [248K](https://x.com/example/status/1/analytics)_",
        )
        self.assertEqual(doc["xEngagementRows"], 1)

    def test_sparse_row_uses_semantic_actions_not_sequence(self):
        doc = {"blocks": [
            _metric(601, "like", "1"),
            _views("70"),
        ]}

        compact_engagement_rows(doc, "https://x.com/home")

        self.assertEqual(
            doc["blocks"][0]["md"],
            "_Likes 1 · Views [70]"
            "(https://x.com/example/status/1/analytics)_",
        )

    def test_unrelated_numbers_and_non_x_pages_are_untouched(self):
        blocks = [
            _metric(366, "reply", "47"),
            {"landmark": "main", "bbox": [0, 900, 20, 20],
             "kind": "p", "md": "2026", "links": [], "images": []},
        ]
        doc = {"blocks": blocks.copy()}
        self.assertEqual(
            compact_engagement_rows(doc, "https://example.com/feed"), 0)
        self.assertEqual(doc["blocks"], blocks)

        x_doc = {"blocks": blocks.copy()}
        self.assertEqual(
            compact_engagement_rows(x_doc, "https://x.com/home"), 0)
        self.assertEqual(x_doc["blocks"], blocks)

    def test_views_only_is_labeled(self):
        doc = {"blocks": [_views("86")]}

        self.assertEqual(
            compact_engagement_rows(doc, "https://x.com/home"), 1)
        self.assertEqual(
            doc["blocks"][0]["md"],
            "_Views [86](https://x.com/example/status/1/analytics)_",
        )


if __name__ == "__main__":
    unittest.main()
