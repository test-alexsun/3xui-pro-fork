import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[2]


class LegacyInstallerTest(unittest.TestCase):
    def test_install_and_uninstall_refuse_before_legacy_body(self):
        entrypoint = REPO / 'x-ui-latest.sh'
        commands = [
            line.strip()
            for line in entrypoint.read_text(encoding='utf-8').splitlines()
            if line.strip() and not line.lstrip().startswith('#')
        ]
        # Check the guard before launching Bash so a broken guard cannot run
        # any of the retained installer body during this test.
        self.assertRegex(commands[0], r"^printf '%s\\n' 'INSTALL_DISABLED: [^']+' >&2$")
        self.assertEqual(commands[1], 'exit 1')

        bash = shutil.which('bash')
        self.assertIsNotNone(bash, 'the preview regression requires Bash')
        for args in ([], ['-install', 'y'], ['-uninstall', 'y']):
            with self.subTest(args=args), tempfile.TemporaryDirectory() as tmp:
                result = subprocess.run(
                    [bash, '--noprofile', '--norc', str(entrypoint), *args],
                    cwd=tmp, env={'PATH': os.defpath}, capture_output=True,
                    text=True, timeout=10, check=False,
                )
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stdout, '')
                self.assertEqual(len(result.stderr.splitlines()), 1)
                self.assertTrue(result.stderr.startswith('INSTALL_DISABLED: '), result.stderr)
                self.assertEqual(list(Path(tmp).iterdir()), [])
