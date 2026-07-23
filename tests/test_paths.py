import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from mdb.paths import app_data_dir, data_path, downloads_dir


class PathsTest(unittest.TestCase):
    def test_macos_uses_application_support(self):
        got = app_data_dir(env={"HOME": "/Users/alice"}, platform="darwin")
        self.assertEqual(got, "/Users/alice/Library/Application Support/mdbrowse")

    def test_linux_uses_xdg_data_home(self):
        got = app_data_dir(env={"XDG_DATA_HOME": "/tmp/xdg"}, platform="linux")
        self.assertEqual(got, "/tmp/xdg/mdbrowse")

    def test_linux_falls_back_to_local_share(self):
        got = app_data_dir(env={"HOME": "/home/alice"}, platform="linux")
        self.assertEqual(got, "/home/alice/.local/share/mdbrowse")

    def test_windows_uses_local_app_data(self):
        got = app_data_dir(
            env={"LOCALAPPDATA": "/Users/alice/AppData/Local"},
            platform="win32")
        self.assertEqual(got, "/Users/alice/AppData/Local/mdbrowse")

    def test_base_override(self):
        got = data_path("watch", env={"MDBROWSE_HOME": "/tmp/mdb"},
                        platform="linux")
        self.assertEqual(got, "/tmp/mdb/watch")

    def test_store_override_wins(self):
        got = data_path("archive", "MDBROWSE_ARCHIVE",
                        env={"MDBROWSE_ARCHIVE": "/tmp/archive"},
                        platform="linux")
        self.assertEqual(got, "/tmp/archive")

    def test_macos_uses_safari_download_path(self):
        got = downloads_dir(
            env={"HOME": "/Users/alice"}, platform="darwin",
            safari_path="~/Desktop/Research")
        self.assertEqual(got, "/Users/alice/Desktop/Research")

    def test_download_override_wins(self):
        got = downloads_dir(
            env={"HOME": "/Users/alice",
                 "MDBROWSE_DOWNLOADS": "~/Files"},
            platform="darwin", safari_path="/ignored")
        self.assertEqual(got, "/Users/alice/Files")

    def test_download_fallback_is_visible_downloads_folder(self):
        got = downloads_dir(
            env={"HOME": "/home/alice"}, platform="linux",
            safari_path="")
        self.assertEqual(got, "/home/alice/Downloads")


if __name__ == "__main__":
    unittest.main()
