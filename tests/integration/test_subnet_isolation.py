"""Subnet and route isolation contracts between WireGuard and AmneziaWG 3.1."""
import json
from pathlib import Path
import sys
import unittest
from unittest import mock

RELEASE = Path(__file__).resolve().parents[2] / 'release'
if str(RELEASE) not in sys.path:
    sys.path.insert(0, str(RELEASE))

import preview_vpn_inbounds as vpn


class SubnetIsolationTests(unittest.TestCase):
    def test_identical_or_overlapping_wg_awg_subnets_refused(self):
        overlaps = (
            ('10.89.8.0/24', '10.89.8.0/24'),
            ('10.89.8.0/24', '10.89.8.0/25'),
            ('10.88.0.0/16', '10.88.32.0/24'),
            ('192.168.100.0/24', '192.168.100.4/30'),
        )
        for wg_sub, awg_sub in overlaps:
            with self.subTest(wg_sub=wg_sub, awg_sub=awg_sub), self.assertRaisesRegex(RuntimeError, 'overlap'):
                vpn.validate_vpn_spec(51820, 29177, 24443, wg_sub, awg_sub, check_routes=False)

    def test_non_rfc1918_or_too_narrow_subnets_refused(self):
        for bad_wg, bad_awg in (
            ('198.18.0.0/24', '10.88.32.0/24'),
            ('10.89.8.0/24', '100.64.0.0/24'),
            ('10.89.8.0/31', '10.88.32.0/24'),
            ('10.89.8.0/24', '10.88.32.0/32'),
        ):
            with self.subTest(bad_wg=bad_wg, bad_awg=bad_awg), self.assertRaises(RuntimeError):
                vpn.validate_vpn_spec(51820, 29177, 24443, bad_wg, bad_awg, check_routes=False)

    def test_host_route_collision_refused_and_awg_handoff_exempts_only_awg(self):
        routes = json.dumps([
            {'dst': 'default', 'dev': 'ens3'},
            {'dst': '10.88.31.0/30', 'dev': 'xproawg0'},
            {'dst': '172.17.0.0/16', 'dev': 'docker0'},
        ])
        with mock.patch.object(vpn, 'command', return_value=routes):
            with self.assertRaisesRegex(RuntimeError, 'WireGuard subnet .* overlaps'):
                vpn.validate_vpn_spec(51820, 29177, 24443, '172.17.1.0/24', '10.88.32.0/24', check_routes=True)
            with self.assertRaisesRegex(RuntimeError, 'AmneziaWG 3.1 subnet .* overlaps'):
                vpn.validate_vpn_spec(51820, 29177, 24443, '10.89.8.0/24', '10.88.31.0/30', check_routes=True)
            # Explicit handoff ignores xproawg0 ONLY for AWG, never for WG.
            spec = vpn.validate_vpn_spec(
                51820, 29177, 24443, '10.89.8.0/24', '10.88.31.0/30',
                check_routes=True, ignore_awg_dev=True,
            )
            self.assertEqual(spec['awg_subnet'], '10.88.31.0/30')
            with self.assertRaisesRegex(RuntimeError, 'WireGuard subnet .* overlaps'):
                vpn.validate_vpn_spec(
                    51820, 29177, 24443, '10.88.31.0/30', '10.88.32.0/24',
                    check_routes=True, ignore_awg_dev=True,
                )


if __name__ == '__main__':
    unittest.main()
