"""Unit tests for WireGuard inbound runtime invariants and UDP listener ownership."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'release'))
import preview_wireguard as wg


class WireGuardRuntimeTests(unittest.TestCase):
    def test_verify_live_listener_passes_for_exact_xray_pid(self):
        ss_out = 'UNCONN 0 0 10.77.5.1:51820 0.0.0.0:* users:(("xray-linux-amd6",pid=4242,fd=12))\n'
        with patch.object(wg.subprocess, 'check_output', return_value=ss_out) as check_cmd, \
                patch.object(wg.Path, 'read_text', return_value='xray-linux-amd6\n') as read_comm:
            owner = wg.verify_live_listener(51820, 4242)
        self.assertEqual(owner, 4242)
        check_cmd.assert_called_once()
        self.assertEqual(check_cmd.call_args.args[0], ['ss', '-H', '-lunp', 'sport = :51820'])
        read_comm.assert_called_once()

    def test_verify_live_listener_fails_on_missing_socket(self):
        with patch.object(wg.subprocess, 'check_output', return_value=''):
            with self.assertRaisesRegex(RuntimeError, 'no live WireGuard UDP listener'):
                wg.verify_live_listener(51820, 4242)

    def test_verify_live_listener_fails_on_wrong_pid(self):
        ss_out = 'UNCONN 0 0 10.77.5.1:51820 0.0.0.0:* users:(("xray-linux-amd6",pid=9999,fd=12))\n'
        with patch.object(wg.subprocess, 'check_output', return_value=ss_out):
            with self.assertRaisesRegex(RuntimeError, 'expected Xray PID 4242'):
                wg.verify_live_listener(51820, 4242)

    def test_verify_live_listener_fails_on_wrong_process_comm(self):
        ss_out = 'UNCONN 0 0 10.77.5.1:51820 0.0.0.0:* users:(("amneziawg-go",pid=4242,fd=12))\n'
        with patch.object(wg.subprocess, 'check_output', return_value=ss_out), \
                patch.object(wg.Path, 'read_text', return_value='amneziawg-go\n'):
            with self.assertRaisesRegex(RuntimeError, 'forbidden AWG process'):
                wg.verify_live_listener(51820, 4242)

        with patch.object(wg.subprocess, 'check_output', return_value=ss_out), \
                patch.object(wg.Path, 'read_text', return_value='python3\n'):
            with self.assertRaisesRegex(RuntimeError, 'unexpected process'):
                wg.verify_live_listener(51820, 4242)

    def test_verify_live_listener_fails_on_duplicate_pids(self):
        two_distinct = (
            'UNCONN 0 0 10.77.5.1:51820 0.0.0.0:* users:(("xray-linux-amd6",pid=4242,fd=12))\n'
            'UNCONN 0 0 10.77.5.1:51820 0.0.0.0:* users:(("xray-linux-amd6",pid=4243,fd=13))\n'
        )
        with patch.object(wg.subprocess, 'check_output', return_value=two_distinct):
            with self.assertRaisesRegex(RuntimeError, 'duplicate or multiple'):
                wg.verify_live_listener(51820, 4242)

        two_same_pid = (
            'UNCONN 0 0 10.77.5.1:51820 0.0.0.0:* '
            'users:(("xray-linux-amd6",pid=4242,fd=12),("xray-linux-amd6",pid=4242,fd=13))\n'
        )
        with patch.object(wg.subprocess, 'check_output', return_value=two_same_pid):
            with self.assertRaisesRegex(RuntimeError, 'duplicate or multiple'):
                wg.verify_live_listener(51820, 4242)

    def test_verify_live_listener_rejects_awg_port_and_missing_proc_comm(self):
        with self.assertRaisesRegex(RuntimeError, '29177'):
            wg.verify_live_listener(29177, 4242)

        ss_out = 'UNCONN 0 0 10.77.5.1:51820 0.0.0.0:* users:(("xray-linux-amd6",pid=4242,fd=12))\n'
        with patch.object(wg.subprocess, 'check_output', return_value=ss_out), \
                patch.object(wg.Path, 'read_text', side_effect=FileNotFoundError('gone')):
            with self.assertRaisesRegex(RuntimeError, 'comm'):
                wg.verify_live_listener(51820, 4242)

    def test_nokerneltun_and_inbound_payload_enforced(self):
        priv, _ = wg.generate_keypair()
        inbound = wg.build_inbound_payload(
            listen_ip='10.77.5.1',
            port=51820,
            domain='vpn.example.test',
            subnet_str='10.89.8.0/24',
            server_private_key=priv,
        )
        self.assertEqual(inbound['protocol'], 'wireguard')
        self.assertEqual(inbound['tag'], 'WIREGUARD')
        self.assertEqual(inbound['remark'], 'WIREGUARD')
        self.assertEqual(inbound['streamSettings'], {})
        self.assertEqual(inbound['sniffing'], {'enabled': False})
        self.assertEqual(inbound['shareAddrStrategy'], 'custom')
        self.assertEqual(inbound['shareAddr'], 'vpn.example.test')
        self.assertTrue(inbound['settings']['noKernelTun'])
        self.assertEqual(inbound['settings']['subnetIp'], '10.89.8.0')
        self.assertEqual(inbound['settings']['subnetCidr'], 24)
        self.assertTrue(wg.verify_inbound_settings(inbound['settings'], inbound['streamSettings']))

        bad_false = dict(inbound['settings'], noKernelTun=False)
        with self.assertRaisesRegex(ValueError, 'noKernelTun=True'):
            wg.verify_inbound_settings(bad_false)

        bad_missing = {k: v for k, v in inbound['settings'].items() if k != 'noKernelTun'}
        with self.assertRaisesRegex(ValueError, 'noKernelTun=True'):
            wg.verify_inbound_settings(bad_missing)

        bad_kernel_mode = dict(inbound['settings'], kernelMode=True)
        with self.assertRaisesRegex(ValueError, 'kernelMode'):
            wg.verify_inbound_settings(bad_kernel_mode)

        bad_awg = dict(inbound['settings'], jc=4)
        with self.assertRaisesRegex(ValueError, 'AWG contamination'):
            wg.verify_inbound_settings(bad_awg)


if __name__ == '__main__':
    unittest.main()
