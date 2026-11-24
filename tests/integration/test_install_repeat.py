"""Installer flag validation, safe repeat, and ownership contracts for 6 inbounds."""
import base64
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

RELEASE = Path(__file__).resolve().parents[2] / 'release'
if str(RELEASE) not in sys.path:
    sys.path.insert(0, str(RELEASE))

import preview_amneziawg31 as awg31
import preview_hysteria2 as hy2
import preview_install as install
import preview_vpn_inbounds as vpn
import preview_wireguard as wg
import upgrade_candidate as ownership


class InstallAndRepeatTests(unittest.TestCase):
    def test_verify_ready_preserves_operator_clients_and_refuses_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = root / 'preview-vpn-inbounds.json'
            wg_priv, _ = wg.generate_keypair()
            awg_priv = base64.b64encode(bytes([3]) * 32).decode('ascii')
            awg_pub = base64.b64encode(bytes([4]) * 32).decode('ascii')
            awg_hpk = base64.b64encode(bytes([5]) * 32).decode('ascii')
            awg_srv = awg31.build_server_settings('10.88.32.0/24', awg_priv, awg_pub, awg_hpk, mtu=1420)
            state_payload = {
                'version': 2,
                'phase': 'READY',
                'profiles': {'WIREGUARD': 4, 'AMNEZIAWG-3.1': 5, 'HYSTERIA2': 6},
                'ports': {'WIREGUARD': 51820, 'AMNEZIAWG-3.1': 29177, 'HYSTERIA2': 24443},
                'subnets': {'WIREGUARD': '10.89.8.0/24', 'AMNEZIAWG-3.1': '10.88.32.0/24'},
                'domain': 'vpn.example.test',
                'settings': {
                    'WIREGUARD': {'secretKey': wg_priv, 'mtu': 1420, 'noKernelTun': True, 'subnetIp': '10.89.8.0', 'subnetCidr': 24},
                    'AMNEZIAWG-3.1': {'server': awg_srv, 'clients': []},
                    'HYSTERIA2': {'version': 2, 'clients': []},
                },
            }
            state_path.write_text(json.dumps(state_payload))
            rows = [
                {
                    'id': 4,
                    'tag': 'WIREGUARD',
                    'port': 51820,
                    'enable': True,
                    'settings': json.dumps({**state_payload['settings']['WIREGUARD'], 'clients': [{'email': 'operator-added-wg'}]}),
                    'streamSettings': '{}',
                },
                {
                    'id': 5,
                    'tag': 'AMNEZIAWG-3.1',
                    'port': 29177,
                    'enable': True,
                    # 3x-ui Go serializer omits kernelMode when false (omitempty).
                    'settings': json.dumps({'server': {k: v for k, v in awg_srv.items() if k != 'kernelMode'}, 'clients': [{'email': 'operator-added-awg'}]}),
                    'streamSettings': '{}',
                },
                {
                    'id': 6,
                    'tag': 'HYSTERIA2',
                    'port': 24443,
                    'enable': True,
                    'settings': json.dumps({'version': 2, 'clients': [{'email': 'operator-added-hy2'}]}),
                    'streamSettings': json.dumps(
                        hy2.build_inbound_payload('10.77.5.1', 24443, 'vpn.example.test')['streamSettings']
                    ),
                },
            ]
            api = mock.Mock()
            with mock.patch.object(vpn, 'STATE', state_path), \
                 mock.patch.object(vpn.ownership, 'regular_root_file'), \
                 mock.patch.object(vpn.native, 'verify_ready'), \
                 mock.patch.object(vpn.native, 'api_client', return_value=api), \
                 mock.patch.object(vpn, 'wait_vpn_ready', return_value=rows):
                self.assertTrue(vpn.verify_ready(51820, 29177, 24443, '10.89.8.0/24', '10.88.32.0/24'))
                with self.assertRaisesRegex(RuntimeError, 'ports differ'):
                    vpn.verify_ready(51821, 29177, 24443, '10.89.8.0/24', '10.88.32.0/24')
                with self.assertRaisesRegex(RuntimeError, 'subnets differ'):
                    vpn.verify_ready(51820, 29177, 24443, '10.89.9.0/24', '10.88.32.0/24')

    def test_verify_ready_refuses_recovery_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / 'preview-vpn-inbounds.json'
            state_path.write_text('{"phase":"RECOVERY_REQUIRED"}')
            with mock.patch.object(vpn, 'STATE', state_path), mock.patch.object(vpn.ownership, 'regular_root_file'):
                with self.assertRaisesRegex(RuntimeError, 'RECOVERY_REQUIRED'):
                    vpn.verify_ready(51820, 29177, 24443, '10.89.8.0/24', '10.88.32.0/24')

    def test_inspect_installed_requires_inactive_standalone_awg_in_embedded_mode(self):
        manifest = {
            'panel': '3.11.0',
            'xray': '26.11.9',
            'awg_runtime': '3.1.20260828',
            'awg_tools': '3.1.20260812',
            'files': ownership.PINNED_FILES,
        }
        with tempfile.TemporaryDirectory() as tmp:
            fake_unit = Path(tmp) / 'unit'
            fake_unit.write_text('unit')

            def props(unit):
                if unit == '3xui-pro-fork-awg.service':
                    return {'ActiveState': 'active', 'MainPID': '1234'}
                return {
                    'FragmentPath': str(Path('/etc/systemd/system') / unit),
                    'DropInPaths': '',
                    'NeedDaemonReload': 'no',
                    'ActiveState': 'active',
                    'MainPID': str(os.getpid()),
                }

            orig_stat = Path.stat

            def patched_stat(path_obj, *args, **kwargs):
                if str(path_obj).startswith('/proc/'):
                    return SimpleNamespace(st_uid=0)
                return orig_stat(path_obj, *args, **kwargs)

            with mock.patch.object(ownership, 'root_dir'), \
                 mock.patch.object(ownership, 'regular_root_file'), \
                 mock.patch.object(ownership.os.path, 'samefile', return_value=True), \
                 mock.patch.object(Path, 'stat', patched_stat), \
                 mock.patch.object(ownership, 'sha', side_effect=lambda p: ownership.PINNED_FILES.get(str(p).replace('\\', '/').split('/3xui-pro-fork/')[-1], ownership.BASELINE_SCRIPTS.get(str(p).replace('\\', '/').split('/3xui-pro-fork/')[-1], ownership.UNITS.get(p.name, '')))), \
                 mock.patch.object(ownership, 'service_properties', side_effect=props):
                with self.assertRaisesRegex(RuntimeError, 'must remain inactive'):
                    ownership.inspect_installed(manifest, require_standalone_awg=False)

    def test_preview_install_refuses_incompatible_vpn_flags(self):
        bad_invocations = (
            ['prog', '--domain', 'a.example.test', '--awg-subnet', '10.88.32.0/24', '--add-vpn-inbounds'],
            ['prog', '--domain', 'a.example.test', '--awg-subnet', '10.88.32.0/24', '--handoff-standalone-awg'],
            ['prog', '--domain', 'a.example.test', '--awg-subnet', '10.88.32.0/24', '--panel-inbounds', '--add-vpn-inbounds', '--vless-only'],
        )
        for argv in bad_invocations:
            with self.subTest(argv=argv), mock.patch.object(sys, 'argv', argv):
                with self.assertRaises(RuntimeError):
                    install.main()


if __name__ == '__main__':
    unittest.main()
