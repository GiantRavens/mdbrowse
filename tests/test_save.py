import datetime
import os
import tempfile
import unittest

from mdb.save import save_page, suggested_page_path


class SavePageTest(unittest.TestCase):
    def test_suggested_path_is_dated_markdown(self):
        got = suggested_page_path(
            "An Interesting Page", "https://example.com/story",
            dest_dir="/tmp/research",
            now=datetime.datetime(2026, 7, 23, 12, 0))
        self.assertEqual(
            got, "/tmp/research/20260723-example-com-an-interesting-page.md")

    def test_explicit_path_and_deduplication(self):
        with tempfile.TemporaryDirectory() as folder:
            wanted = os.path.join(folder, "evidence.md")
            first = save_page("# one\n", "Title", "https://example.com", wanted)
            second = save_page("# two\n", "Title", "https://example.com", wanted)
            self.assertEqual(first, wanted)
            self.assertEqual(second, os.path.join(folder, "evidence-1.md"))
            with open(second, encoding="utf-8") as handle:
                self.assertEqual(handle.read(), "# two\n")

    def test_directory_destination_uses_suggested_name(self):
        with tempfile.TemporaryDirectory() as folder:
            got = save_page("# page\n", "Title", "https://example.com", folder)
            self.assertEqual(os.path.dirname(got), folder)
            self.assertTrue(got.endswith(".md"))


if __name__ == "__main__":
    unittest.main()
