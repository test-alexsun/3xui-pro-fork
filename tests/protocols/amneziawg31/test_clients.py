"""Unit tests for AmneziaWG 3.1 subnet validation, IP allocation, and client payloads."""
import base64
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'release'))
import preview_amneziawg31 as awg31


def _b64_key(fill_byte):
    return base64.b64encode(bytes([fill_byte]) * 32).decode('ascii')


class AmneziaWG31ClientTests(unittest.TestCase):
    def test_validate_subnet_enforces_strict_rfc1918_prefix_range(self):
        for valid in ('10.88.32.0/24', '172.16.0.0/16', '192.168.40.0/30'):
            net = awg31.validate_subnet(valid)
            self.assertEqual(str(net), valid)

        for invalid in (
            '10.0.0.0/8',
            '10.88.0.0/15',
            '10.88.32.0/31',
            '10.88.32.0/32',
            '10.88.32.1/24',
            '100.64.0.0/24',
            '203.0.113.0/24',
            '172.32.0.0/24',
            'fd00::/64',
            '10.88.32.0',
        ):
            with self.assertRaises(ValueError, msg=invalid):
                awg31.validate_subnet(invalid)

    def test_validate_subnet_rejects_overlap_with_existing_subnets(self):
        with self.assertRaisesRegex(ValueError, 'overlaps'):
            awg31.validate_subnet('10.88.32.0/24', existing_subnets=['10.88.0.0/16'])
        with self.assertRaisesRegex(ValueError, 'overlaps'):
            awg31.validate_subnet('10.88.0.0/23', existing_subnets=['10.88.1.0/24'])
        net = awg31.validate_subnet('10.88.32.0/24', existing_subnets=['10.89.8.0/24'])
        self.assertEqual(str(net), '10.88.32.0/24')

    def test_allocate_client_ip_across_slash24_and_slash30(self):
        # First host (.1) is reserved for server; client allocations start at .2.
        self.assertEqual(awg31.allocate_client_ip('10.88.32.0/24', []), '10.88.32.2/32')
        self.assertEqual(awg31.allocate_client_ip('10.88.32.0/24', ['10.88.32.2/32']), '10.88.32.3/32')
        self.assertEqual(
            awg31.allocate_client_ip('10.88.32.0/24', ['10.88.32.2/32', '10.88.32.4/32']),
            '10.88.32.3/32',
        )
        # /30 has only .1 (server) and .2 (single client slot).
        self.assertEqual(awg31.allocate_client_ip('10.88.32.0/30', []), '10.88.32.2/32')

    def test_allocate_client_ip_exhaustion_and_overlap_errors(self):
        with self.assertRaisesRegex(ValueError, 'exhausted'):
            awg31.allocate_client_ip('10.88.32.0/30', ['10.88.32.2/32'])

        full_slash29 = [f'10.88.32.{host}/32' for host in range(2, 8)]
        with self.assertRaisesRegex(ValueError, 'exhausted'):
            awg31.allocate_client_ip('10.88.32.0/29', full_slash29)

        with self.assertRaisesRegex(ValueError, 'overlaps'):
            awg31.allocate_client_ip('10.88.32.0/24', ['10.88.32.0/25'])

    def test_build_client_payload_and_key_rotation(self):
        priv1, pub1 = _b64_key(10), _b64_key(11)
        payload = awg31.build_client_payload(
            'awg-user-1', '10.88.32.2', priv1, pub1, sub_id='subtoken-12345',
        )
        self.assertEqual(payload, {
            'email': 'awg-user-1',
            'enable': True,
            'privateKey': priv1,
            'publicKey': pub1,
            'allowedIPs': ['10.88.32.2/32'],
            'preSharedKey': '',
            'keepAlive': 25,
            'subId': 'subtoken-12345',
        })

        priv2, pub2 = _b64_key(12), _b64_key(13)
        rotated = awg31.build_client_payload(
            payload['email'],
            payload['allowedIPs'][0],
            priv2,
            pub2,
            sub_id=payload['subId'],
            enable=True,
        )
        self.assertEqual(rotated['email'], payload['email'])
        self.assertEqual(rotated['allowedIPs'], ['10.88.32.2/32'])
        self.assertEqual(rotated['subId'], payload['subId'])
        self.assertEqual(rotated['privateKey'], priv2)
        self.assertEqual(rotated['publicKey'], pub2)

    def test_build_client_payload_rejects_bad_inputs(self):
        priv, pub = _b64_key(10), _b64_key(11)
        for bad_ip in ('10.88.32.0/24', '10.88.32.2/24', 'not-an-ip', '::1/128'):
            with self.assertRaises(ValueError):
                awg31.build_client_payload('u1', bad_ip, priv, pub)
        with self.assertRaises(ValueError):
            awg31.build_client_payload('bad email', '10.88.32.2/32', priv, pub)
        with self.assertRaises(ValueError):
            awg31.build_client_payload('u1', '10.88.32.2/32', 'invalid', pub)
        with self.assertRaises(ValueError):
            awg31.build_client_payload('u1', '10.88.32.2/32', priv, pub, keep_alive=True)


if __name__ == '__main__':
    unittest.main()
