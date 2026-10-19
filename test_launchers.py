from pathlib import Path
import os
import re
import unittest
from unittest.mock import patch

import start_scribity


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

    def test_local_venv_is_checked_before_global_python_and_quoted(self):
        venv_check = 'if exist ".venv\\Scripts\\python.exe" goto run_with_venv'
        self.assertIn(venv_check, self.launcher)
        self.assertLess(self.launcher.index(venv_check), self.launcher.index('py -3 --version'))
        branch = self.launcher.split(':run_with_venv\n', 1)[1].split('\n:', 1)[0]
        self.assertIn('set SCRIBITY_PYTHON=".venv\\Scripts\\python.exe"', branch)
        self.assertIn('goto start_scribity', branch)

    def test_keeps_failures_visible(self):
        self.assertIn('Python 3 was not found', self.launcher)
        self.assertIn('Scribity stopped with an error', self.launcher)
        self.assertIn('pause', self.launcher.lower())

    def test_every_goto_has_a_matching_label(self):
        labels = set(re.findall(r"(?im)^:([a-z0-9_]+)$", self.launcher))
        targets = set(re.findall(r"(?im)\bgoto\s+([a-z0-9_]+)\s*$", self.launcher))
        self.assertEqual(targets - labels, set())


class PythonLauncherTests(unittest.TestCase):
    def test_server_uses_platform_venv_or_current_interpreter(self):
        # Exercise main without starting a server, browser, thread, or changing cwd.
        app_dir = os.path.join(os.path.sep, 'fixture project with spaces')
        for platform, parts in [('win32', ('Scripts', 'python.exe')),
                                ('darwin', ('bin', 'python')),
                                ('linux', ('bin', 'python'))]:
            venv = os.path.join(app_dir, '.venv', *parts)
            for available in (True, False):
                with self.subTest(platform=platform, venv_available=available):
                    with patch.object(start_scribity, '__file__', os.path.join(app_dir, 'start_scribity.py')), \
                         patch.object(start_scribity.sys, 'platform', platform), \
                         patch.object(start_scribity.sys, 'executable', '/fallback/python'), \
                         patch.object(start_scribity.os, 'chdir') as chdir, \
                         patch.object(start_scribity.os.path, 'isfile', side_effect=lambda path: available and path == venv), \
                         patch.object(start_scribity.threading, 'Thread'), \
                         patch.object(start_scribity.subprocess, 'run') as run, \
                         patch('builtins.print'):
                        start_scribity.main()
                    chdir.assert_called_once_with(app_dir)
                    run.assert_called_once_with([
                        venv if available else '/fallback/python',
                        os.path.join(app_dir, 'scribity_server.py'),
                    ], check=False)


if __name__ == "__main__":
    unittest.main()
