"""Panel API six-inbound provisioning, fail-closed recovery, and CLI flag contracts."""
import base64
import contextlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

RELEASE = Path(__file__).resolve().parents[2] / 'release'
if str(RELEASE) not in sys.path:
    sys.path.insert(0, str(RELEASE))

import preview_amneziawg31 as awg31
import preview_panel_inbounds as native
import preview_vpn_inbounds as vpn


def _vless_rows():
    return [
        {
            'id': idx,
            'tag': tag,
            'protocol': 'vless',
            'port': port,
            'listen': '127.0.0.1' if idx == 2 else '10.77.5.1',
            'enable': True,
            'settings': '{"clients":[]}',
            'streamSettings': '{}',
            'sniffing': '{"enabled":false}',
            'shareAddr': 'vpn.example.test',
            'shareAddrStrategy': 'custom',
            'disableFlow': False,
        }
        for idx, (tag, port) in enumerate(
            (
                ('VLESS-REALITY-XHTTP-H2', 8443),
                ('VLESS-TLS-XHTTP-H2', 19441),
                ('VLESS-REALITY-VISION', 9443),
            ),
            1,
        )
    ]


class PanelApiProvisioningTests(unittest.TestCase):
    def test_provision_vpn_inbounds_creates_independent_wg_awg_hy2_and_preserves_vless(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = root / 'data'
            data.mkdir(mode=0o700)
            db_path = data / 'x-ui.db'
            with contextlib.closing(sqlite3.connect(db_path)) as db:
                with db:
                    db.execute('CREATE TABLE demo (k TEXT)')
                    db.execute("INSERT INTO demo VALUES ('ok')")
            native_state = data / 'preview-panel-inbounds.json'
            native_state.write_text('{"phase":"READY","profiles":{"P0":1,"P1":2,"P3":3}}')
            vpn_state = data / 'preview-vpn-inbounds.json'
            cert = root / 'fullchain.pem'
            key = root / 'privkey.pem'
            cert.write_text('cert')
            key.write_text('key')

            rows = _vless_rows()
            added_clients = []
            enabled_ids = []

            class FakeAPI:
                def call(self, route, payload=None, form=False):
                    if route == 'inbounds/list':
                        return list(rows)
                    if route == 'clients/list':
                        return []
                    if route == 'inbounds/add':
                        new_id = len(rows) + 1
                        row = dict(payload, id=new_id)
                        rows.append(row)
                        return row
                    if route == 'clients/add':
                        added_clients.append(payload)
                        return {'ok': True}
                    if route.startswith('inbounds/setEnable/'):
                        target_id = int(route.rsplit('/', 1)[-1])
                        enabled_ids.append(target_id)
                        for r in rows:
                            if r['id'] == target_id:
                                r['enable'] = payload['enable']
                        return {'ok': True}
                    raise AssertionError(f'unexpected route {route}')

            awg_srv_priv = base64.b64encode(bytes([3]) * 32).decode('ascii')
            awg_srv_pub = base64.b64encode(bytes([4]) * 32).decode('ascii')
            awg_cli_priv = base64.b64encode(bytes([5]) * 32).decode('ascii')
            awg_cli_pub = base64.b64encode(bytes([6]) * 32).decode('ascii')
            awg_hpk = base64.b64encode(bytes([7]) * 32).decode('ascii')

            def atomic_fn(path, data_bytes, mode):
                path.write_bytes(data_bytes)

            with mock.patch.multiple(vpn, DATA=data, STATE=vpn_state), \
                 mock.patch.object(native, 'STATE', native_state), \
                 mock.patch.object(vpn.native, 'verify_ready'), \
                 mock.patch.object(vpn.ownership, 'root_dir'), \
                 mock.patch.object(vpn.ownership, 'regular_root_file'), \
                 mock.patch.object(vpn.ownership, 'service_properties', return_value={'ActiveState': 'inactive'}), \
                 mock.patch.object(vpn, 'command', return_value='[]'), \
                 mock.patch.object(vpn, 'listener', return_value=''), \
                 mock.patch.object(vpn.hy2, 'DEFAULT_CERT', cert), \
                 mock.patch.object(vpn.hy2, 'DEFAULT_KEY', key), \
                 mock.patch.object(awg31, 'generate_keypair', side_effect=[(awg_srv_priv, awg_srv_pub), (awg_cli_priv, awg_cli_pub)]), \
                 mock.patch.object(awg31, 'generate_header_protection_key', return_value=awg_hpk), \
                 mock.patch.object(vpn, 'wait_vpn_ready', side_effect=lambda *a, **kw: list(rows)):
                result = vpn.provision_vpn_inbounds(
                    FakeAPI(),
                    {'domain': 'vpn.example.test', 'public_address': '10.77.5.1'},
                    wg_port=51820,
                    awg_port=29177,
                    hy2_port=24443,
                    wg_subnet='10.89.8.0/24',
                    awg_subnet='10.88.32.0/24',
                    atomic_fn=atomic_fn,
                )

            self.assertEqual(result['phase'], 'READY')
            self.assertEqual(result['profiles'], {'WIREGUARD': 4, 'AMNEZIAWG-3.1': 5, 'HYSTERIA2': 6})
            self.assertEqual(enabled_ids, [4, 5, 6])
            self.assertEqual(len(added_clients), 3)
            # Each protocol gets its own client record (never shared across WG & AWG).
            self.assertEqual([c['inboundIds'] for c in added_clients], [[4], [5], [6]])
            wg_cli = added_clients[0]['client']
            awg_cli = added_clients[1]['client']
            hy_cli = added_clients[2]['client']
            self.assertNotEqual(wg_cli['privateKey'], awg_cli['privateKey'])
            self.assertEqual(len({wg_cli['subId'], awg_cli['subId'], hy_cli['subId']}), 3)
            self.assertEqual(json.loads(vpn_state.read_text())['phase'], 'READY')
            # Native VLESS journal preserved verbatim.
            self.assertEqual(native_state.read_text(), '{"phase":"READY","profiles":{"P0":1,"P1":2,"P3":3}}')

    def test_failed_provision_transitions_to_recovery_required_without_deleting_vless(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = root / 'data'
            data.mkdir(mode=0o700)
            with contextlib.closing(sqlite3.connect(data / 'x-ui.db')) as db:
                with db:
                    db.execute('CREATE TABLE demo (k TEXT)')
            native_state = data / 'preview-panel-inbounds.json'
            native_state.write_text('{"phase":"READY","profiles":{"P0":1,"P1":2,"P3":3}}')
            vpn_state = data / 'preview-vpn-inbounds.json'
            cert = root / 'fullchain.pem'
            key = root / 'privkey.pem'
            cert.write_text('c')
            key.write_text('k')
            rows = _vless_rows()

            class FailingAPI:
                def call(self, route, payload=None, form=False):
                    if route == 'inbounds/list':
                        return list(rows)
                    if route == 'clients/list':
                        return []
                    if route == 'inbounds/add':
                        if payload.get('tag') == 'HYSTERIA2':
                            raise RuntimeError('simulated add failure')
                        row = dict(payload, id=len(rows) + 1)
                        rows.append(row)
                        return row
                    if route == 'clients/add':
                        return {'ok': True}
                    raise AssertionError(f'unexpected route {route}')

            with mock.patch.multiple(vpn, DATA=data, STATE=vpn_state), \
                 mock.patch.object(native, 'STATE', native_state), \
                 mock.patch.object(vpn.native, 'verify_ready'), \
                 mock.patch.object(vpn.ownership, 'root_dir'), \
                 mock.patch.object(vpn.ownership, 'regular_root_file'), \
                 mock.patch.object(vpn.ownership, 'service_properties', return_value={'ActiveState': 'inactive'}), \
                 mock.patch.object(vpn, 'command', return_value='[]'), \
                 mock.patch.object(vpn, 'listener', return_value=''), \
                 mock.patch.object(vpn.hy2, 'DEFAULT_CERT', cert), \
                 mock.patch.object(vpn.hy2, 'DEFAULT_KEY', key), \
                 mock.patch.object(
                     awg31,
                     'generate_keypair',
                     side_effect=[
                         (base64.b64encode(bytes([3]) * 32).decode('ascii'), base64.b64encode(bytes([4]) * 32).decode('ascii')),
                         (base64.b64encode(bytes([5]) * 32).decode('ascii'), base64.b64encode(bytes([6]) * 32).decode('ascii')),
                     ],
                 ), \
                 mock.patch.object(awg31, 'generate_header_protection_key', return_value=base64.b64encode(bytes([7]) * 32).decode('ascii')):
                with self.assertRaisesRegex(RuntimeError, 'RECOVERY_REQUIRED'):
                    vpn.provision_vpn_inbounds(
                        FailingAPI(),
                        {'domain': 'vpn.example.test', 'public_address': '10.77.5.1'},
                        wg_port=51820,
                        awg_port=29177,
                        hy2_port=24443,
                        wg_subnet='10.89.8.0/24',
                        awg_subnet='10.88.32.0/24',
                        atomic_fn=lambda p, b, m: p.write_bytes(b),
                    )
            self.assertEqual(json.loads(vpn_state.read_text())['phase'], 'RECOVERY_REQUIRED')
            self.assertEqual(native_state.read_text(), '{"phase":"READY","profiles":{"P0":1,"P1":2,"P3":3}}')


if __name__ == '__main__':
    unittest.main()
