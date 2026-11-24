"""Port isolation contracts across VLESS, WireGuard, AmneziaWG 3.1, and Hysteria2."""
from pathlib import Path
import sys
import unittest
from unittest import mock

RELEASE = Path(__file__).resolve().parents[2] / 'release'
if str(RELEASE) not in sys.path:
    sys.path.insert(0, str(RELEASE))

import preview_vpn_inbounds as vpn


class PortIsolationTests(unittest.TestCase):
    def test_default_six_inbound_ports_are_disjoint_and_valid(self):
        spec = vpn.validate_vpn_spec(
            51820, 29177, 24443,
            '10.89.8.0/24', '10.88.32.0/24',
            reserved_ports=(8443, 9443, 2096),
            check_routes=False,
        )
        self.assertEqual(
            spec['ports'],
            {'WIREGUARD': 51820, 'AMNEZIAWG-3.1': 29177, 'HYSTERIA2': 24443},
        )

    def test_duplicate_ports_among_wg_awg_hy2_refused(self):
        for args in (
            (29177, 29177, 24443),
            (51820, 51820, 24443),
            (51820, 29177, 51820),
            (51820, 24443, 24443),
        ):
            with self.subTest(args=args), self.assertRaisesRegex(RuntimeError, 'distinct|reserved'):
                vpn.validate_vpn_spec(*args, '10.89.8.0/24', '10.88.32.0/24', check_routes=False)

    def test_port_29177_is_exclusively_reserved_for_awg(self):
        with self.assertRaisesRegex(RuntimeError, '29177'):
            vpn.validate_vpn_spec(29177, 29178, 24443, '10.89.8.0/24', '10.88.32.0/24', check_routes=False)
        with self.assertRaisesRegex(RuntimeError, '29177'):
            vpn.validate_vpn_spec(51820, 29178, 29177, '10.89.8.0/24', '10.88.32.0/24', check_routes=False)

    def test_reserved_system_and_vless_ports_refused(self):
        for bad_port in (443, 2053, 2096, 8443, 9443, 18443, 19441, 19444):
            with self.subTest(bad_port=bad_port), self.assertRaises(RuntimeError):
                vpn.validate_vpn_spec(bad_port, 29177, 24443, '10.89.8.0/24', '10.88.32.0/24', check_routes=False)
        with self.assertRaisesRegex(RuntimeError, 'collides'):
            vpn.validate_vpn_spec(
                51820, 29177, 24443,
                '10.89.8.0/24', '10.88.32.0/24',
                reserved_ports=(51820,),
                check_routes=False,
            )

    def test_invalid_port_types_and_ranges_refused(self):
        for bad in (True, 0, 80, 1023, 65536, '51820'):
            with self.subTest(bad=bad), self.assertRaises(RuntimeError):
                vpn.validate_vpn_spec(bad, 29177, 24443, '10.89.8.0/24', '10.88.32.0/24', check_routes=False)


if __name__ == '__main__':
    unittest.main()
