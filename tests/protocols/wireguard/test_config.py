"""Unit tests for WireGuard cryptography, subnets, .conf rendering, and wireguard:// URIs."""
import ast
import base64
import ipaddress
from pathlib import Path
import sys
import unittest
import urllib.parse

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / 'release'))
import preview_wireguard as wg

AWG_ALL_KEYS = (
    'Jc', 'Jmin', 'Jmax',
    'S1', 'S2', 'S3', 'S4',
    'H1', 'H2', 'H3', 'H4',
    'I1', 'I2', 'I3', 'I4', 'I5',
    'HeaderProtectionKey',
    'ContentPaddingAddition',
    'RandomTrailers',
    'DisableCookies',
)


class WireGuardCryptoTests(unittest.TestCase):
    def test_clamp_scalar_sets_and_clears_rfc7748_bits(self):
        clamped = wg.clamp_scalar(b'\xff' * 32)
        self.assertEqual(len(clamped), 32)
        self.assertEqual(clamped[0] & 0b00000111, 0)
        self.assertEqual(clamped[31] & 0b10000000, 0)
        self.assertEqual(clamped[31] & 0b01000000, 0b01000000)
        with self.assertRaises(ValueError):
            wg.clamp_scalar(b'\x00' * 31)

    def test_rfc7748_section_6_1_diffie_hellman_vectors(self):
        alice_priv = bytes.fromhex('77076d0a7318a57d3c16c17251b26645df4c2f87ebc0992ab177fba51db92c2a')
        alice_pub_expected = bytes.fromhex('8520f0098930a754748b7ddcb43ef75a0dbf3a0d26381af4eba4a98eaa9b4e6a')
        bob_priv = bytes.fromhex('5dab087e624a8a4b79e17f8b83800ee66f3bb1292618b6fd1c2f8b27ff88e0eb')
        bob_pub_expected = bytes.fromhex('de9edb7d7b7dc1b4d35b61c2ece435373f8343c85b78674dadfc7e146f882b4f')
        shared_expected = bytes.fromhex('4a5d9d5ba4ce2de1728e3bf480350f25e07e21c947d19e3376f09b3c1e161742')

        basepoint = b'\x09' + (b'\x00' * 31)
        alice_pub = wg.x25519_scalarmult(alice_priv, basepoint)
        bob_pub = wg.x25519_scalarmult(bob_priv, basepoint)
        self.assertEqual(alice_pub, alice_pub_expected)
        self.assertEqual(bob_pub, bob_pub_expected)
        self.assertEqual(wg.x25519_scalarmult(alice_priv, bob_pub), shared_expected)
        self.assertEqual(wg.x25519_scalarmult(bob_priv, alice_pub), shared_expected)

        self.assertEqual(
            wg.public_key_from_private(base64.b64encode(alice_priv).decode('ascii')),
            base64.b64encode(alice_pub_expected).decode('ascii'),
        )

    def test_rfc7748_section_5_2_high_bit_and_iterated_vectors(self):
        k1 = bytes.fromhex('a546e36bf0527c9d3b16154b82465edd62144c0ac1fc5a18506a2244ba449ac4')
        u1 = bytes.fromhex('e6db6867583030db3594c1a424b15f7c726624ec26b3353b10a903a6d0ab1c4c')
        expected1 = bytes.fromhex('c3da55379de9c6908e94ea4df28d084f32eccf03491c71f754b4075577a28552')
        self.assertEqual(wg.x25519_scalarmult(k1, u1), expected1)

        k = b'\x09' + (b'\x00' * 31)
        u = b'\x09' + (b'\x00' * 31)
        for step in range(1, 1001):
            next_u = wg.x25519_scalarmult(k, u)
            u = k
            k = next_u
            if step == 1:
                self.assertEqual(
                    k.hex(),
                    '422c8e7a6227d7bca1350b3e2bb7279f7897b87bb6854b783c60e80311ae3079',
                )
        self.assertEqual(
            k.hex(),
            '684cf59ba83309552800ef566f2f4d3c1c3887c49360e3875f2eb94d99532c51',
        )

    def test_generate_keypair_roundtrip_and_agreement(self):
        priv_a, pub_a = wg.generate_keypair()
        priv_b, pub_b = wg.generate_keypair()
        self.assertEqual(wg.validate_key(priv_a), priv_a)
        self.assertEqual(wg.validate_key(pub_a), pub_a)
        self.assertEqual(wg.public_key_from_private(priv_a), pub_a)
        self.assertEqual(wg.public_key_from_private(priv_b), pub_b)
        self.assertNotEqual(priv_a, priv_b)

        raw_priv_a = base64.b64decode(priv_a)
        raw_pub_b = base64.b64decode(pub_b)
        raw_priv_b = base64.b64decode(priv_b)
        raw_pub_a = base64.b64decode(pub_a)
        self.assertEqual(
            wg.x25519_scalarmult(raw_priv_a, raw_pub_b),
            wg.x25519_scalarmult(raw_priv_b, raw_pub_a),
        )

    def test_invalid_keys_rejected(self):
        non_canonical = base64.b64encode(b'\x01' * 32).decode('ascii')[:-2] + 'B='
        bad_keys = [
            None,
            123,
            b'A' * 43 + b'=',
            '',
            'short',
            'A' * 43,
            'A' * 43 + '=',
            base64.b64encode(b'\x01' * 31).decode('ascii'),
            base64.b64encode(b'\x01' * 33).decode('ascii'),
            base64.urlsafe_b64encode(b'\xff' * 32).decode('ascii'),
            ' ' + base64.b64encode(b'\x02' * 32).decode('ascii'),
            base64.b64encode(b'\x02' * 32).decode('ascii') + '\n',
            non_canonical,
        ]
        for bad in bad_keys:
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    wg.validate_key(bad)


class WireGuardSubnetTests(unittest.TestCase):
    def test_valid_rfc1918_subnets(self):
        net, server_ip, clients = wg.validate_subnet('10.89.8.0/24')
        self.assertEqual(net, ipaddress.IPv4Network('10.89.8.0/24'))
        self.assertEqual(server_ip, '10.89.8.1')
        self.assertEqual(clients[0], '10.89.8.2')
        self.assertEqual(clients[-1], '10.89.8.254')
        self.assertEqual(len(clients), 253)

        net30, srv30, cli30 = wg.validate_subnet('192.168.50.0/30')
        self.assertEqual(net30, ipaddress.IPv4Network('192.168.50.0/30'))
        self.assertEqual(srv30, '192.168.50.1')
        self.assertEqual(cli30, ['192.168.50.2'])

        net16, srv16, cli16 = wg.validate_subnet('172.16.0.0/16')
        self.assertEqual(net16, ipaddress.IPv4Network('172.16.0.0/16'))
        self.assertEqual(srv16, '172.16.0.1')
        self.assertEqual(len(cli16), 65533)

    def test_invalid_subnets_rejected(self):
        invalid = [
            '8.8.8.0/24',
            '198.18.0.0/24',
            '100.64.0.0/24',
            '172.32.0.0/24',
            '192.169.1.0/24',
            '10.89.8.1/24',
            '10.0.0.0/8',
            '10.0.0.0/15',
            '10.89.8.0/31',
            '10.89.8.2/32',
            'fd00::/64',
            '10.89.8.0',
            'not-a-subnet',
        ]
        for subnet in invalid:
            with self.subTest(subnet=subnet):
                with self.assertRaises(ValueError):
                    wg.validate_subnet(subnet)


class WireGuardConfAndLinkTests(unittest.TestCase):
    def setUp(self):
        self.srv_priv, self.srv_pub = wg.generate_keypair()
        self.psk = base64.b64encode(b'\x55' * 32).decode('ascii')
        self.client = wg.build_client_payload(
            email='alice@example.test',
            client_ip='10.89.8.2',
            pre_shared_key=self.psk,
            keep_alive=25,
            sub_id='sub-token-0123456789',
        )

    def test_conf_render_and_parse_roundtrip(self):
        text = wg.render_client_conf(
            endpoint_host='10.77.5.1',
            port=51820,
            server_public_key=self.srv_pub,
            client=self.client,
            allowed_ips=('198.18.0.10/32', '10.89.8.0/24'),
            dns='1.1.1.1',
            mtu=1420,
        )
        parsed = wg.parse_client_conf(text)
        self.assertEqual(parsed['interface']['private_key'], self.client['privateKey'])
        self.assertEqual(parsed['interface']['addresses'], ['10.89.8.2/32'])
        self.assertEqual(parsed['interface']['mtu'], 1420)
        self.assertEqual(parsed['interface']['dns'], ['1.1.1.1'])
        self.assertEqual(parsed['peer']['public_key'], self.srv_pub)
        self.assertEqual(parsed['peer']['preshared_key'], self.psk)
        self.assertEqual(parsed['peer']['allowed_ips'], ['198.18.0.10/32', '10.89.8.0/24'])
        self.assertEqual(parsed['peer']['endpoint_host'], '10.77.5.1')
        self.assertEqual(parsed['peer']['endpoint_port'], 51820)
        self.assertEqual(parsed['peer']['persistent_keepalive'], 25)

    def test_awg_contamination_rejected_in_conf(self):
        base_conf = wg.render_client_conf('10.77.5.1', 51820, self.srv_pub, self.client)
        for key in AWG_ALL_KEYS:
            for variant in (key, key.lower(), key.upper()):
                with self.subTest(key=variant):
                    self.assertIn(variant, wg.AWG_CONTAMINATION_KEYS)
                    tainted = base_conf.replace('[Peer]', f'{variant} = 12\n\n[Peer]')
                    with self.assertRaisesRegex(ValueError, 'AWG contamination'):
                        wg.parse_client_conf(tainted)

    def test_conf_rejects_port_29177_and_malformed_sections(self):
        with self.assertRaises(ValueError):
            wg.render_client_conf('10.77.5.1', 29177, self.srv_pub, self.client)

        valid_conf = wg.render_client_conf('10.77.5.1', 51820, self.srv_pub, self.client)
        with self.assertRaises(ValueError):
            wg.parse_client_conf(valid_conf.replace('51820', '29177'))
        with self.assertRaises(ValueError):
            wg.parse_client_conf('[Interface]\nPrivateKey = ' + self.client['privateKey'] + '\n')
        with self.assertRaises(ValueError):
            wg.parse_client_conf(valid_conf + '\n[Peer]\nPublicKey = ' + self.srv_pub + '\n')

    def test_wireguard_link_parse_and_validate(self):
        priv_q = urllib.parse.quote(self.client['privateKey'], safe='')
        pub_q = urllib.parse.quote(self.srv_pub, safe='')
        psk_q = urllib.parse.quote(self.psk, safe='')
        addr_q = urllib.parse.quote('10.89.8.2/32', safe='')
        uri = (
            f'wireguard://{priv_q}@vpn.example.test:51820'
            f'?publickey={pub_q}&address={addr_q}&mtu=1420&keepalive=25'
            f'&presharedkey={psk_q}#WIREGUARD-alice'
        )
        parsed = wg.validate_wireguard_link(
            uri,
            expected_host='vpn.example.test',
            expected_port=51820,
            expected_server_pub=self.srv_pub,
            expected_client_priv=self.client['privateKey'],
            expected_address='10.89.8.2',
        )
        self.assertEqual(parsed['mtu'], 1420)
        self.assertEqual(parsed['keepalive'], 25)
        self.assertEqual(parsed['preshared_key'], self.psk)
        self.assertEqual(parsed['remark'], 'WIREGUARD-alice')

        with self.assertRaises(ValueError):
            wg.validate_wireguard_link(uri, 'other.example.test', 51820, self.srv_pub, self.client['privateKey'])
        with self.assertRaises(ValueError):
            wg.validate_wireguard_link(uri, 'vpn.example.test', 51821, self.srv_pub, self.client['privateKey'])
        with self.assertRaises(ValueError):
            wg.validate_wireguard_link(uri, 'vpn.example.test', 51820, self.client['publicKey'], self.client['privateKey'])
        with self.assertRaises(ValueError):
            wg.validate_wireguard_link(uri, 'vpn.example.test', 51820, self.srv_pub, self.srv_priv)
        with self.assertRaises(ValueError):
            wg.validate_wireguard_link(uri, 'vpn.example.test', 51820, self.srv_pub, self.client['privateKey'], '10.89.8.99')

    def test_wireguard_link_rejects_awg_params_and_wrong_scheme(self):
        priv_q = urllib.parse.quote(self.client['privateKey'], safe='')
        pub_q = urllib.parse.quote(self.srv_pub, safe='')
        base_uri = f'wireguard://{priv_q}@vpn.example.test:51820?publickey={pub_q}&address=10.89.8.2%2F32'

        for key in AWG_ALL_KEYS:
            for variant in (key, key.lower()):
                with self.subTest(key=variant):
                    tainted = f'{base_uri}&{variant}=12'
                    with self.assertRaisesRegex(ValueError, 'AWG contamination'):
                        wg.parse_wireguard_link(tainted)

        with self.assertRaises(ValueError):
            wg.parse_wireguard_link(base_uri.replace('wireguard://', 'vless://'))
        with self.assertRaises(ValueError):
            wg.parse_wireguard_link(base_uri.replace(':51820', ':29177'))

    def test_module_has_zero_awg_runtime_dependencies(self):
        for rel in (Path('release/preview_wireguard.py'), Path('tests/protocols/wireguard/test_e2e.py')):
            source = (REPO_ROOT / rel).read_text(encoding='utf-8')
            self.assertNotIn('/opt/3xui-pro-fork/awg', source)
            self.assertNotIn('amneziawg-go', source)
            tree = ast.parse(source)
            imported = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.update(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.add(node.module)
            self.assertFalse(any('awg' in name.lower() or 'amnezia' in name.lower() for name in imported))


if __name__ == '__main__':
    unittest.main()
