"""Targeted guards for the opt-in laboratory utility; no production mutation."""
import argparse
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

RELEASE = Path(__file__).resolve().parents[2] / 'release'
sys.path.insert(0, str(RELEASE))
import preview_vpn_inbounds as vpn


class VpnGuards(unittest.TestCase):
    def args(self, **changes):
        values = dict(wg_port=51820, hy2_port=4433, lab=False, lab_handoff_awg=False)
        values.update(changes)
        return argparse.Namespace(**values)

    def rows(self):
        return [{'id': n, 'tag': tag, 'port': 41000 + n, 'enable': True}
                for n, tag in enumerate(vpn.native.TAGS.values(), 1)]

    def test_reserved_awg_port_never_assigned_to_wireguard(self):
        with self.assertRaisesRegex(RuntimeError, 'distinct valid'):
            vpn.plan(self.args(wg_port=29177), Mock())

    def test_disabled_database_row_still_reserves_port(self):
        api = Mock()
        rows = self.rows()
        rows[0].update(port=51820, enable=False)
        api.call.return_value = rows
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(vpn.native, 'verify_ready'), patch.object(vpn, 'STATE', Path(directory) / 'missing'):
                with self.assertRaisesRegex(RuntimeError, 'reserved by panel database'):
                    vpn.plan(self.args(), api)

    def test_existing_socket_is_refused_before_staging(self):
        api = Mock()
        api.call.return_value = self.rows()
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(vpn.native, 'verify_ready'), patch.object(vpn, 'STATE', Path(directory) / 'missing'), \
                 patch.object(vpn.ownership, 'service_properties', return_value={'ActiveState': 'inactive'}), \
                 patch.object(vpn, 'listener', return_value='occupied'):
                with self.assertRaisesRegex(RuntimeError, 'existing TCP/UDP listener'):
                    vpn.plan(self.args(), api)

    def test_production_apply_refused_even_if_marker_present(self):
        with self.assertRaisesRegex(RuntimeError, 'production apply refused'):
            vpn.assert_lab(self.args())

    def test_public_ip_refused_even_with_lab_flag(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / 'lab'
            marker.write_text('PREVIEW-XONIX-08\n')
            with patch.object(vpn, 'MARKER', marker), patch.object(vpn.ownership, 'regular_root_file'), \
                 patch.object(vpn.native, 'private_json', return_value={'public_address': '203.0.113.10'}):
                with self.assertRaisesRegex(RuntimeError, 'RFC1918'):
                    vpn.assert_lab(self.args(lab=True))

    def test_existing_journal_is_not_overwritten_by_plan(self):
        api = Mock()
        api.call.return_value = self.rows()
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory) / 'journal'
            journal.write_text('{"phase":"RECOVERY_REQUIRED"}')
            with patch.object(vpn.native, 'verify_ready'), patch.object(vpn, 'STATE', journal):
                with self.assertRaisesRegex(RuntimeError, 'existing VPN journal'):
                    vpn.plan(self.args(), api)
            self.assertEqual(json.loads(journal.read_text())['phase'], 'RECOVERY_REQUIRED')


if __name__ == '__main__':
    unittest.main()
