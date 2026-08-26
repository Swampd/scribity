from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parent


class WindowsLauncherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.launcher = (ROOT / "scribity.bat").read_text(encoding="ascii")

    def test_uses_its_own_directory_and_current_server(self):
        self.assertIn('cd /d "%~dp0"', self.launcher)
        self.assertIn('scribity_server.py', self.launcher)
        self.assertNotIn(str(ROOT), self.launcher)

    def test_supports_both_standard_windows_python_commands(self):
        self.assertIn('py -3 --version', self.launcher)
        self.assertIn('python -c "import sys; sys.exit(sys.version_info[0] != 3)"', self.launcher)
        self.assertIn('set "SCRIBITY_PYTHON=py -3"', self.launcher)
        self.assertIn('set "SCRIBITY_PYTHON=python"', self.launcher)
        self.assertIn('%SCRIBITY_PYTHON% scribity_server.py', self.launcher)

    def test_keeps_failures_visible(self):
        self.assertIn('Python 3 was not found', self.launcher)
        self.assertIn('Scribity stopped with an error', self.launcher)
        self.assertIn('pause', self.launcher.lower())

    def test_every_goto_has_a_matching_label(self):
        labels = set(re.findall(r"(?im)^:([a-z0-9_]+)$", self.launcher))
        targets = set(re.findall(r"(?im)\bgoto\s+([a-z0-9_]+)\s*$", self.launcher))
        self.assertEqual(targets - labels, set())


if __name__ == "__main__":
    unittest.main()
