"""Unit tests for AmneziaWG 3.1 server config, vpn:// decoding, validation, and setconf."""
import base64
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'release'))
import preview_amneziawg31 as awg31


def _b64_key(fill_byte):
    return base64.b64encode(bytes([fill_byte]) * 32).decode('ascii')


# Real RFC 7748 Section 6.1 Curve25519 pair for cryptographic pubkey checks.
ALICE_PRIV = base64.b64encode(
    bytes.fromhex('77076d0a7318a57d3c16c17251b26645df4c2f87ebc0992ab177fba51db92c2a')
).decode('ascii')
ALICE_PUB = base64.b64encode(
    bytes.fromhex('8520f0098930a754748b7ddcb43ef75a0dbf3a0d26381af4eba4a98eaa9b4e6a')
).decode('ascii')


def _sample_conf(server_settings, client_priv, client_ip='10.88.32.2/32', host='vpn.example.test', port=29177, extra_iface=()):
    lines = [
        '[Interface]',
        f'PrivateKey = {client_priv}',
        f'Address = {client_ip}',
        f"DNS = {server_settings['primaryDns']}, {server_settings['secondaryDns']}",
        f"MTU = {server_settings['mtu']}",
        f"Jc = {server_settings['jc']}",
        f"Jmin = {server_settings['jmin']}",
        f"Jmax = {server_settings['jmax']}",
        f"S1 = {server_settings['s1']}",
        f"S2 = {server_settings['s2']}",
        f"S3 = {server_settings['s3']}",
        f"S4 = {server_settings['s4']}",
        f"H1 = {server_settings['h1']}",
        f"H2 = {server_settings['h2']}",
        f"H3 = {server_settings['h3']}",
        f"H4 = {server_settings['h4']}",
        f"HeaderProtectionKey = {server_settings['headerProtectionKey']}",
        *extra_iface,
        '',
        '# AMNEZIAWG-3.1',
        '[Peer]',
        f"PublicKey = {server_settings['publicKey']}",
        'AllowedIPs = 0.0.0.0/0, ::/0',
        f'Endpoint = {host}:{port}',
        'PersistentKeepalive = 25',
    ]
    return '\n'.join(lines) + '\n'


class AmneziaWG31ConfigTests(unittest.TestCase):
    def setUp(self):
        self.srv_priv = _b64_key(1)
        self.srv_pub = _b64_key(2)
        self.hpk = _b64_key(3)

    def test_build_server_settings_defaults_and_mtu_1420(self):
        srv = awg31.build_server_settings('10.88.32.0/24', self.srv_priv, self.srv_pub, self.hpk)
        self.assertFalse(srv['kernelMode'])
        self.assertEqual(srv['mtu'], 1420)
        self.assertEqual(srv['subnetIp'], '10.88.32.0')
        self.assertEqual(srv['subnetCidr'], 24)
        self.assertEqual(srv['headerProtectionKey'], self.hpk)
        self.assertEqual(srv['primaryDns'], '1.1.1.1')
        self.assertEqual(srv['secondaryDns'], '8.8.8.8')
        for k, v in awg31.AWG31_OBFUSCATION_DEFAULTS.items():
            self.assertEqual(srv[k], v)
        self.assertIsInstance(srv['h1'], str)

    def test_rejects_kernel_mode_true(self):
        with self.assertRaisesRegex(ValueError, 'kernelMode'):
            awg31.build_server_settings('10.88.32.0/24', self.srv_priv, self.srv_pub, self.hpk, kernelMode=True)

    def test_rejects_missing_or_invalid_header_protection_key(self):
        for bad in ('', None, 'not-base64', _b64_key(0), base64.b64encode(b'short').decode()):
            with self.assertRaises(ValueError):
                awg31.build_server_settings('10.88.32.0/24', self.srv_priv, self.srv_pub, bad)

    def test_rejects_invalid_mtu_and_obfuscation_constraints(self):
        for bad_mtu in (1279, 65536, True, '1420'):
            with self.assertRaises(ValueError):
                awg31.build_server_settings('10.88.32.0/24', self.srv_priv, self.srv_pub, self.hpk, mtu=bad_mtu)
        with self.assertRaisesRegex(ValueError, 's4'):
            awg31.build_server_settings('10.88.32.0/24', self.srv_priv, self.srv_pub, self.hpk, s4=8)
        with self.assertRaisesRegex(ValueError, 's1/s2'):
            awg31.build_server_settings('10.88.32.0/24', self.srv_priv, self.srv_pub, self.hpk, s1=12, s2=68)
        with self.assertRaisesRegex(ValueError, 'overlap'):
            awg31.build_server_settings('10.88.32.0/24', self.srv_priv, self.srv_pub, self.hpk, h1='10-20', h2='15-30')

    def test_build_inbound_payload_matches_3xui_schema(self):
        srv = awg31.build_server_settings('10.88.32.0/24', self.srv_priv, self.srv_pub, self.hpk)
        payload = awg31.build_inbound_payload('10.77.5.1', 29177, 'vpn.example.test', srv)
        self.assertEqual(payload['protocol'], 'amneziawg')
        self.assertEqual(payload['tag'], 'AMNEZIAWG-3.1')
        self.assertEqual(payload['remark'], 'AMNEZIAWG-3.1')
        self.assertEqual(payload['listen'], '10.77.5.1')
        self.assertEqual(payload['port'], 29177)
        self.assertEqual(payload['streamSettings'], '{}')
        self.assertEqual(payload['sniffing'], '{"enabled": false}')
        self.assertEqual(payload['shareAddrStrategy'], 'custom')
        self.assertEqual(payload['shareAddr'], 'vpn.example.test')

    def test_decode_vpn_link_and_validate_awg31_conf(self):
        srv = awg31.build_server_settings('10.88.32.0/24', self.srv_priv, self.srv_pub, self.hpk)
        conf = _sample_conf(srv, ALICE_PRIV)
        raw_url_b64 = base64.urlsafe_b64encode(conf.encode('utf-8')).decode('ascii').rstrip('=')
        decoded = awg31.decode_vpn_link('vpn://' + raw_url_b64)
        self.assertEqual(decoded, conf)
        parsed = awg31.validate_awg31_conf(decoded, srv, ALICE_PRIV, 'vpn.example.test', 29177)
        self.assertEqual(parsed['Interface']['HeaderProtectionKey'], self.hpk)
        # Also verify matching by derived Curve25519 public key.
        awg31.validate_awg31_conf(decoded, srv, ALICE_PUB, 'vpn.example.test', 29177)

        for bad_uri in ('vless://abc', 'vpn://', 'vpn://***not-b64***'):
            with self.assertRaises(ValueError):
                awg31.decode_vpn_link(bad_uri)

    def test_validate_awg31_conf_rejects_plain_wg_and_missing_parameters(self):
        srv = awg31.build_server_settings('10.88.32.0/24', self.srv_priv, self.srv_pub, self.hpk)
        plain_wg = '\n'.join([
            '[Interface]',
            f'PrivateKey = {ALICE_PRIV}',
            'Address = 10.88.32.2/32',
            'MTU = 1420',
            '[Peer]',
            f'PublicKey = {self.srv_pub}',
            'AllowedIPs = 0.0.0.0/0',
            'Endpoint = vpn.example.test:29177',
        ])
        with self.assertRaises(ValueError):
            awg31.validate_awg31_conf(plain_wg, srv, ALICE_PRIV, 'vpn.example.test', 29177)

        full_conf = _sample_conf(srv, ALICE_PRIV)
        without_hpk = '\n'.join(l for l in full_conf.splitlines() if not l.startswith('HeaderProtectionKey'))
        with self.assertRaisesRegex(ValueError, 'HeaderProtectionKey'):
            awg31.validate_awg31_conf(without_hpk, srv, ALICE_PRIV, 'vpn.example.test', 29177)

        wrong_mtu = full_conf.replace('MTU = 1420', 'MTU = 1368')
        with self.assertRaisesRegex(ValueError, 'MTU'):
            awg31.validate_awg31_conf(wrong_mtu, srv, ALICE_PRIV, 'vpn.example.test', 29177)

    def test_conf_to_setconf_strips_wgquick_fields_and_serializes_booleans(self):
        srv = awg31.build_server_settings(
            '10.88.32.0/24', self.srv_priv, self.srv_pub, self.hpk,
            randomTrailers=True, disableCookies=False,
        )
        conf = _sample_conf(
            srv, ALICE_PRIV,
            extra_iface=('RandomTrailers = true', 'DisableCookies = false'),
        )
        setconf, addr, mtu = awg31.conf_to_setconf(
            conf, endpoint_override='10.77.5.1:29177', allowed_ips_override='198.18.0.10/32',
        )
        self.assertEqual(addr, '10.88.32.2/32')
        self.assertEqual(mtu, 1420)
        self.assertNotIn('Address =', setconf)
        self.assertNotIn('DNS =', setconf)
        self.assertNotIn('MTU =', setconf)
        self.assertIn('RandomTrailers = on', setconf)
        self.assertIn('DisableCookies = off', setconf)
        self.assertIn('H1 = 1', setconf)
        self.assertIn('Endpoint = 10.77.5.1:29177', setconf)
        self.assertIn('AllowedIPs = 198.18.0.10/32', setconf)
        self.assertIn(f'HeaderProtectionKey = {self.hpk}', setconf)


if __name__ == '__main__':
    unittest.main()
