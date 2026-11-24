"""Unit tests for Hysteria2 live UDP listener verification."""
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock

RELEASE = Path(__file__).resolve().parents[3] / 'release'
if str(RELEASE) not in sys.path:
    sys.path.insert(0, str(RELEASE))

import preview_hysteria2 as hy2


class Hysteria2RuntimeTests(unittest.TestCase):
    def test_verify_live_listener_passes_for_exact_xray_pid(self):
        ss_output = 'UNCONN 0 0 10.77.5.1:24443 0.0.0.0:* users:(("xray-linux-amd6",pid=4242,fd=19))\n'
        with mock.patch.object(hy2.subprocess, 'check_output', return_value=ss_output) as check_output:
            self.assertTrue(hy2.verify_live_listener(24443, 4242))
        check_output.assert_called_once_with(
            ['ss', '-H', '-lunp', 'sport = :24443'],
            text=True,
            stderr=subprocess.PIPE,
            timeout=15,
        )

    def test_verify_live_listener_fails_on_missing_listener(self):
        with mock.patch.object(hy2.subprocess, 'check_output', return_value='   \n'):
            with self.assertRaisesRegex(RuntimeError, 'missing UDP listener'):
                hy2.verify_live_listener(24443, 4242)

    def test_verify_live_listener_fails_on_wrong_or_competing_pid(self):
        wrong_pid = 'UNCONN 0 0 10.77.5.1:24443 0.0.0.0:* users:(("xray-linux-amd6",pid=9999,fd=19))\n'
        with mock.patch.object(hy2.subprocess, 'check_output', return_value=wrong_pid):
            with self.assertRaisesRegex(RuntimeError, 'unexpected PID'):
                hy2.verify_live_listener(24443, 4242)

        competing_pid = (
            'UNCONN 0 0 10.77.5.1:24443 0.0.0.0:* users:(("xray-linux-amd6",pid=4242,fd=19))\n'
            'UNCONN 0 0 10.77.5.1:24443 0.0.0.0:* users:(("other",pid=9999,fd=3))\n'
        )
        with mock.patch.object(hy2.subprocess, 'check_output', return_value=competing_pid):
            with self.assertRaisesRegex(RuntimeError, 'unexpected PID'):
                hy2.verify_live_listener(24443, 4242)

    def test_verify_live_listener_fails_on_unidentified_listener_or_command_error(self):
        unidentified = 'UNCONN 0 0 10.77.5.1:24443 0.0.0.0:*\n'
        with mock.patch.object(hy2.subprocess, 'check_output', return_value=unidentified):
            with self.assertRaisesRegex(RuntimeError, 'unidentified UDP listener'):
                hy2.verify_live_listener(24443, 4242)

        with mock.patch.object(
            hy2.subprocess,
            'check_output',
            side_effect=subprocess.CalledProcessError(1, ['ss']),
        ):
            with self.assertRaisesRegex(RuntimeError, 'failed to inspect'):
                hy2.verify_live_listener(24443, 4242)

    def test_verify_live_listener_rejects_invalid_port_or_pid(self):
        with self.assertRaises(ValueError):
            hy2.verify_live_listener(29177, 4242)
        for bad_pid in (0, -1, None, True):
            with self.subTest(bad_pid=bad_pid), self.assertRaises(ValueError):
                hy2.verify_live_listener(24443, bad_pid)


if __name__ == '__main__':
    unittest.main()
