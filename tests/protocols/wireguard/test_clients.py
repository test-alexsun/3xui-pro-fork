"""Unit tests for WireGuard IP allocation, client payloads, key rotation, and subnet limits."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'release'))
import preview_wireguard as wg


class WireGuardClientAllocationTests(unittest.TestCase):
    def test_allocate_skips_network_server_and_used_peers(self):
        self.assertEqual(wg.allocate_client_ip('10.89.8.0/24', []), '10.89.8.2')
        self.assertEqual(
            wg.allocate_client_ip('10.89.8.0/24', ['10.89.8.0/32', '10.89.8.1/32']),
            '10.89.8.2',
        )
        self.assertEqual(
            wg.allocate_client_ip('10.89.8.0/24', ['10.89.8.2/32', '10.89.8.4/32']),
            '10.89.8.3',
        )
        self.assertEqual(
            wg.allocate_client_ip('10.89.8.0/24', ['10.89.8.0/30']),
            '10.89.8.4',
        )

    def test_allocate_refuses_exhausted_subnet(self):
        self.assertEqual(wg.allocate_client_ip('192.168.99.0/30', []), '192.168.99.2')
        with self.assertRaisesRegex(ValueError, 'exhausted'):
            wg.allocate_client_ip('192.168.99.0/30', ['192.168.99.2/32'])

        all_24_clients = [f'10.89.8.{host}/32' for host in range(2, 255)]
        with self.assertRaisesRegex(ValueError, 'exhausted'):
            wg.allocate_client_ip('10.89.8.0/24', all_24_clients)

    def test_overlapping_subnet_refused(self):
        with self.assertRaisesRegex(ValueError, 'overlaps'):
            wg.validate_subnet_disjoint('10.89.8.0/24', ['10.89.0.0/16'])
        with self.assertRaisesRegex(ValueError, 'overlaps'):
            wg.validate_subnet_disjoint('10.89.8.0/24', ['10.89.8.128/25'])
        with self.assertRaisesRegex(ValueError, 'overlaps'):
            wg.allocate_client_ip(
                '10.89.8.0/24',
                used_cidrs=[],
                reserved_subnets=['10.89.8.0/24'],
            )
        wg.validate_subnet_disjoint('10.89.8.0/24', ['10.88.31.0/30', '10.77.5.0/24'])

    def test_build_client_payload_generates_and_validates_keys(self):
        client = wg.build_client_payload('alice', '10.89.8.2')
        self.assertEqual(client['email'], 'alice')
        self.assertTrue(client['enable'])
        self.assertEqual(client['allowedIPs'], ['10.89.8.2/32'])
        self.assertEqual(client['preSharedKey'], '')
        self.assertEqual(client['keepAlive'], 25)
        self.assertEqual(wg.public_key_from_private(client['privateKey']), client['publicKey'])
        self.assertGreaterEqual(len(client['subId']), 16)

        priv, pub = wg.generate_keypair()
        derived = wg.build_client_payload('bob', '10.89.8.3/32', private_key=priv)
        self.assertEqual(derived['publicKey'], pub)
        self.assertEqual(derived['allowedIPs'], ['10.89.8.3/32'])

        _, other_pub = wg.generate_keypair()
        with self.assertRaisesRegex(ValueError, 'does not match'):
            wg.build_client_payload('charlie', '10.89.8.4', private_key=priv, public_key=other_pub)
        with self.assertRaisesRegex(ValueError, 'private_key is required'):
            wg.build_client_payload('charlie', '10.89.8.4', public_key=pub)

    def test_build_client_payload_rejects_invalid_inputs(self):
        with self.assertRaises(ValueError):
            wg.build_client_payload('bad email', '10.89.8.2')
        with self.assertRaises(ValueError):
            wg.build_client_payload('alice', '10.89.8.2/24')
        with self.assertRaises(ValueError):
            wg.build_client_payload('alice', '10.89.8.2', keep_alive=-1)
        with self.assertRaises(ValueError):
            wg.build_client_payload('alice', '10.89.8.2', keep_alive=True)
        with self.assertRaises(ValueError):
            wg.build_client_payload('alice', '10.89.8.2', enable='yes')
        with self.assertRaises(ValueError):
            wg.build_client_payload('alice', '10.89.8.2', sub_id='bad/sub')

    def test_rotate_client_keys_preserves_identity_and_replaces_keypair(self):
        original = wg.build_client_payload('alice', '10.89.8.2', sub_id='sub-alice-0001')
        rotated = wg.rotate_client_keys(original)
        self.assertEqual(rotated['email'], original['email'])
        self.assertEqual(rotated['allowedIPs'], original['allowedIPs'])
        self.assertEqual(rotated['subId'], original['subId'])
        self.assertNotEqual(rotated['privateKey'], original['privateKey'])
        self.assertNotEqual(rotated['publicKey'], original['publicKey'])
        self.assertEqual(wg.public_key_from_private(rotated['privateKey']), rotated['publicKey'])

        with self.assertRaisesRegex(ValueError, 'differ'):
            wg.rotate_client_keys(original, private_key=original['privateKey'], public_key=original['publicKey'])


if __name__ == '__main__':
    unittest.main()
