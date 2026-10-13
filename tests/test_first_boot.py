"""Test refusal/command handling only; not a hardware boot test."""
import importlib.util
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("first_boot", ROOT / "scripts/check-first-boot.py")
first_boot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(first_boot)


class FirstBootTests(unittest.TestCase):
    def test_missing_tool_is_unknown(self):
        with patch.object(first_boot.shutil, "which", return_value=None):
            self.assertIsNone(first_boot.command("missing-tool"))

    def test_failed_command_does_not_print_arbitrary_stderr(self):
        result = subprocess.CompletedProcess(["test-tool"], 1, "", "private-error-text")
        with patch.object(first_boot.shutil, "which", return_value="/usr/bin/test-tool"), patch.object(first_boot.subprocess, "run", return_value=result):
            self.assertIsNone(first_boot.command("test-tool"))

    def test_refuses_without_physical_device_tree(self):
        with patch.object(first_boot.Path, "is_file", return_value=False), patch.object(first_boot, "command") as run, patch("sys.argv", ["check-first-boot.py"]), patch("builtins.print"):
            self.assertEqual(first_boot.main(), 2)
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
