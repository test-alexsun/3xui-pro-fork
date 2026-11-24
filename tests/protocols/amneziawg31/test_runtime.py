"""Unit tests for AmneziaWG 3.1 live listener ownership and AWG CLI wrappers."""
import base64
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'release'))
import preview_amneziawg31 as awg31

ALICE_PRIV = base64.b64encode(
    bytes.fromhex('77076d0a7318a57d3c16c17251b26645df4c2f87ebc0992ab177fba51db92c2a')
).decode('ascii')
ALICE_PUB = base64.b64encode(
    bytes.fromhex('8520f0098930a754748b7ddcb43ef75a0dbf3a0d26381af4eba4a98eaa9b4e6a')
).decode('ascii')


class AmneziaWG31RuntimeTests(unittest.TestCase):
    def test_verify_live_listener_passes_for_exact_panel_pid_and_inactive_standalone(self):
        def fake_check_output(cmd, **_kwargs):
            if cmd[:3] == ['systemctl', 'show', awg31.STANDALONE_UNIT]:
                return 'ActiveState=inactive\n'
            if cmd[:3] == ['ss', '-H', '-lunp']:
                return 'UNCONN 0 0 10.77.5.1:29177 0.0.0.0:* users:(("x-ui",pid=4242,fd=19))\n'
            raise AssertionError(f'unexpected command: {cmd}')

        with patch.object(awg31.subprocess, 'check_output', side_effect=fake_check_output):
            self.assertTrue(awg31.verify_live_listener(29177, 4242))

    def test_verify_live_listener_fails_when_standalone_unit_is_active(self):
        with patch.object(awg31.subprocess, 'check_output', return_value='ActiveState=active\n'):
            with self.assertRaisesRegex(RuntimeError, 'inactive'):
                awg31.verify_live_listener(29177, 4242)

    def test_verify_live_listener_fails_when_standalone_unit_not_inactive(self):
        for state in ('activating', 'failed', 'deactivating'):
            with patch.object(awg31.subprocess, 'check_output', return_value=f'ActiveState={state}\n'):
                with self.assertRaisesRegex(RuntimeError, 'inactive'):
                    awg31.verify_live_listener(29177, 4242)

    def test_verify_live_listener_fails_when_wrong_pid_owns_socket(self):
        def fake_check_output(cmd, **_kwargs):
            if cmd[0] == 'systemctl':
                return 'ActiveState=inactive\n'
            return 'UNCONN 0 0 10.77.5.1:29177 0.0.0.0:* users:(("awg",pid=9999,fd=7))\n'

        with patch.object(awg31.subprocess, 'check_output', side_effect=fake_check_output):
            with self.assertRaisesRegex(RuntimeError, 'unexpected PID'):
                awg31.verify_live_listener(29177, 4242)

    def test_verify_live_listener_fails_when_multiple_pids_own_socket(self):
        def fake_check_output(cmd, **_kwargs):
            if cmd[0] == 'systemctl':
                return 'ActiveState=inactive\n'
            return (
                'UNCONN 0 0 10.77.5.1:29177 0.0.0.0:* users:(("x-ui",pid=4242,fd=19))\n'
                'UNCONN 0 0 10.77.5.1:29177 0.0.0.0:* users:(("other",pid=5555,fd=3))\n'
            )

        with patch.object(awg31.subprocess, 'check_output', side_effect=fake_check_output):
            with self.assertRaisesRegex(RuntimeError, 'unexpected PID'):
                awg31.verify_live_listener(29177, 4242)

    def test_verify_live_listener_fails_when_socket_missing_or_unidentified(self):
        for ss_out in ('', '   \n', 'UNCONN 0 0 10.77.5.1:29177 0.0.0.0:*\n'):
            def fake_check_output(cmd, _out=ss_out, **_kwargs):
                if cmd[0] == 'systemctl':
                    return 'ActiveState=inactive\n'
                return _out

            with patch.object(awg31.subprocess, 'check_output', side_effect=fake_check_output):
                with self.assertRaises(RuntimeError):
                    awg31.verify_live_listener(29177, 4242)

    def test_key_generation_helpers_call_awg_binary(self):
        def fake_run(cmd, **_kwargs):
            if cmd[1] == 'genkey':
                return Mock(stdout=ALICE_PRIV + '\n')
            if cmd[1] == 'pubkey':
                return Mock(stdout=ALICE_PUB + '\n')
            raise AssertionError(f'unexpected awg subcommand: {cmd}')

        with patch.object(awg31.subprocess, 'run', side_effect=fake_run):
            priv, pub = awg31.generate_keypair('/mock/awg')
            self.assertEqual((priv, pub), (ALICE_PRIV, ALICE_PUB))
            self.assertEqual(awg31.public_key(ALICE_PRIV, '/mock/awg'), ALICE_PUB)
            self.assertEqual(awg31.generate_header_protection_key('/mock/awg'), ALICE_PRIV)

    def test_key_generation_fails_closed_on_subprocess_error(self):
        with patch.object(awg31.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, ['awg'])):
            with self.assertRaises(RuntimeError):
                awg31.generate_keypair('/mock/awg')


if __name__ == '__main__':
    unittest.main()
