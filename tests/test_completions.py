"""Contract tests for generated bash and zsh completions."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import unittest

from mdb.completions import COMMANDS, ROOT_OPTIONS, generate


class CompletionTests(unittest.TestCase):
    def test_bash_script_parses_and_covers_commands(self):
        script = generate("bash")
        for command in COMMANDS:
            self.assertIn(command, script)
        bash = shutil.which("bash")
        if bash:
            result = subprocess.run(
                [bash, "-n"], input=script, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_zsh_script_parses_and_covers_commands(self):
        script = generate("zsh")
        for command in COMMANDS:
            self.assertIn(command, script)
        zsh = shutil.which("zsh")
        if zsh:
            result = subprocess.run(
                [zsh, "-n"], input=script, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_root_option_catalog_has_not_drifted(self):
        result = subprocess.run(
            [sys.executable, "-m", "mdb.cli", "--help"],
            text=True, capture_output=True, check=True)
        help_options = set(re.findall(r"(?<!\\w)--[a-z][a-z-]*",
                                      result.stdout))
        self.assertEqual(help_options, {
            option for option in ROOT_OPTIONS if option.startswith("--")
        })

    def test_choice_values_are_present(self):
        for shell in ("bash", "zsh"):
            script = generate(shell)
            for value in ("native", "auto", "opencli", "twitter-cli",
                          "bundle", "manifest", "body"):
                self.assertIn(value, script)

    def test_unknown_shell_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "unsupported shell"):
            generate("fish")


if __name__ == "__main__":
    unittest.main()
