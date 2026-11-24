"""Unit tests for Hysteria2 v2 inbound payload, URI parsing/validation, and Xray outbound generation."""
import json
from pathlib import Path
import sys
import unittest
import urllib.parse

RELEASE = Path(__file__).resolve().parents[3] / 'release'
if str(RELEASE) not in sys.path:
    sys.path.insert(0, str(RELEASE))

import preview_hysteria2 as hy2

MAIN_DOMAIN = 'de126.alexsun55.ru'
PUBLIC_IP = '10.77.5.1'


class Hysteria2ConfigTests(unittest.TestCase):
    def test_build_inbound_payload_matches_v2_tls_h3_contract(self):
        payload = hy2.build_inbound_payload(PUBLIC_IP, 24443, MAIN_DOMAIN)
        self.assertEqual(payload['protocol'], 'hysteria')
        self.assertEqual(payload['tag'], 'HYSTERIA2')
        self.assertEqual(payload['remark'], 'HYSTERIA2')
        self.assertEqual(payload['listen'], PUBLIC_IP)
        self.assertEqual(payload['port'], 24443)
        self.assertFalse(payload['enable'])
        self.assertEqual(payload['settings'], {'version': 2, 'clients': []})
        self.assertEqual(payload['sniffing'], {'enabled': False})
        self.assertEqual(payload['shareAddrStrategy'], 'custom')
        self.assertEqual(payload['shareAddr'], MAIN_DOMAIN)

        stream = payload['streamSettings']
        self.assertEqual(stream['network'], 'hysteria')
        self.assertEqual(stream['security'], 'tls')
        self.assertEqual(stream['hysteriaSettings'], {'version': 2, 'udpIdleTimeout': 60})
        self.assertEqual(
            stream['tlsSettings'],
            {
                'serverName': MAIN_DOMAIN,
                'alpn': ['h3'],
                'certificates': [
                    {
                        'certificateFile': '/var/lib/3xui-preview-acme/config/live/3xui-preview/fullchain.pem',
                        'keyFile': '/var/lib/3xui-preview-acme/config/live/3xui-preview/privkey.pem',
                    }
                ],
            },
        )
        self.assertNotIn('allowInsecure', stream['tlsSettings'])
        json.dumps(payload)

    def test_build_inbound_payload_rejects_invalid_inputs_and_reserved_awg_port(self):
        with self.assertRaises(ValueError):
            hy2.build_inbound_payload('not-an-ip', 24443, MAIN_DOMAIN)
        with self.assertRaisesRegex(ValueError, '29177'):
            hy2.build_inbound_payload(PUBLIC_IP, 29177, MAIN_DOMAIN)
        for bad_port in (0, -1, 65536, '24443', True):
            with self.subTest(bad_port=bad_port), self.assertRaises(ValueError):
                hy2.build_inbound_payload(PUBLIC_IP, bad_port, MAIN_DOMAIN)
        for bad_domain in ('', 'bad domain', 'https://de126.alexsun55.ru', 'localhost'):
            with self.subTest(bad_domain=bad_domain), self.assertRaises(ValueError):
                hy2.build_inbound_payload(PUBLIC_IP, 24443, bad_domain)
        with self.assertRaises(ValueError):
            hy2.build_inbound_payload(PUBLIC_IP, 24443, MAIN_DOMAIN, udp_idle_timeout=0)

    def test_validate_inbound_payload_rejects_v1_wrong_alpn_or_insecure_tls(self):
        base = hy2.build_inbound_payload(PUBLIC_IP, 24443, MAIN_DOMAIN)
        bad_version = json.loads(json.dumps(base))
        bad_version['settings']['version'] = 1
        with self.assertRaises(ValueError):
            hy2.validate_inbound_payload(bad_version)

        bad_network = json.loads(json.dumps(base))
        bad_network['streamSettings']['network'] = 'tcp'
        with self.assertRaises(ValueError):
            hy2.validate_inbound_payload(bad_network)

        bad_alpn = json.loads(json.dumps(base))
        bad_alpn['streamSettings']['tlsSettings']['alpn'] = ['h2']
        with self.assertRaises(ValueError):
            hy2.validate_inbound_payload(bad_alpn)

        insecure = json.loads(json.dumps(base))
        insecure['streamSettings']['tlsSettings']['allowInsecure'] = True
        with self.assertRaises(ValueError):
            hy2.validate_inbound_payload(insecure)

    def test_parse_and_validate_hysteria2_link_including_percent_encoded_auth(self):
        raw_auth = 'user+auth/1=test@colon:val%25'
        encoded_auth = urllib.parse.quote(raw_auth, safe='')
        uri = (
            f'hysteria2://{encoded_auth}@{MAIN_DOMAIN}:24443'
            f'?security=tls&alpn=h3&sni={MAIN_DOMAIN}#HYSTERIA2%20Edge'
        )
        parsed = hy2.parse_hysteria2_link(uri)
        self.assertEqual(parsed['scheme'], 'hysteria2')
        self.assertEqual(parsed['auth'], raw_auth)
        self.assertEqual(parsed['host'], MAIN_DOMAIN)
        self.assertEqual(parsed['port'], 24443)
        self.assertEqual(parsed['params'], {'security': 'tls', 'alpn': 'h3', 'sni': MAIN_DOMAIN})
        self.assertEqual(parsed['remark'], 'HYSTERIA2 Edge')

        validated = hy2.validate_hysteria2_link(uri, MAIN_DOMAIN, 24443, raw_auth, MAIN_DOMAIN)
        self.assertEqual(validated['auth'], raw_auth)

    def test_parse_hysteria2_link_handles_unencoded_colon_auth_and_ipv6_host(self):
        uri = f'hysteria2://user:pass@[2001:db8::1]:24443?security=tls&alpn=h3,h2&sni={MAIN_DOMAIN}#HY2'
        parsed = hy2.parse_hysteria2_link(uri)
        self.assertEqual(parsed['auth'], 'user:pass')
        self.assertEqual(parsed['host'], '2001:db8::1')
        self.assertEqual(parsed['port'], 24443)
        hy2.validate_hysteria2_link(uri, '2001:db8::1', 24443, 'user:pass', MAIN_DOMAIN)

    def test_validate_hysteria2_link_rejects_mismatches_and_insecure_params(self):
        base_query = f'hysteria2://secret123@{MAIN_DOMAIN}:24443?security=tls&alpn=h3&sni={MAIN_DOMAIN}'
        valid = base_query + '#HYSTERIA2'
        with self.assertRaises(ValueError):
            hy2.validate_hysteria2_link(valid.replace('hysteria2://', 'vless://'), MAIN_DOMAIN, 24443, 'secret123', MAIN_DOMAIN)
        with self.assertRaises(ValueError):
            hy2.validate_hysteria2_link(valid, 'other.example.test', 24443, 'secret123', MAIN_DOMAIN)
        with self.assertRaises(ValueError):
            hy2.validate_hysteria2_link(valid, MAIN_DOMAIN, 24444, 'secret123', MAIN_DOMAIN)
        with self.assertRaises(ValueError):
            hy2.validate_hysteria2_link(valid, MAIN_DOMAIN, 24443, 'wrong-secret', MAIN_DOMAIN)
        with self.assertRaises(ValueError):
            hy2.validate_hysteria2_link(valid, MAIN_DOMAIN, 24443, 'secret123', 'other.example.test')
        with self.assertRaises(ValueError):
            hy2.validate_hysteria2_link(valid.replace('security=tls', 'security=none'), MAIN_DOMAIN, 24443, 'secret123', MAIN_DOMAIN)
        with self.assertRaises(ValueError):
            hy2.validate_hysteria2_link(valid.replace('alpn=h3', 'alpn=h2'), MAIN_DOMAIN, 24443, 'secret123', MAIN_DOMAIN)
        with self.assertRaises(ValueError):
            hy2.validate_hysteria2_link(base_query + '&insecure=1#HYSTERIA2', MAIN_DOMAIN, 24443, 'secret123', MAIN_DOMAIN)
        with self.assertRaises(ValueError):
            hy2.validate_hysteria2_link(base_query + '&allowInsecure=true#HYSTERIA2', MAIN_DOMAIN, 24443, 'secret123', MAIN_DOMAIN)
        # Explicit insecure=0 preserves strict TLS verification and should pass.
        hy2.validate_hysteria2_link(base_query + '&insecure=0#HYSTERIA2', MAIN_DOMAIN, 24443, 'secret123', MAIN_DOMAIN)

    def test_client_outbound_from_link_enforces_explicit_ca_verification(self):
        raw_auth = 'tok/en+1=2'
        base_query = (
            f'hysteria2://{urllib.parse.quote(raw_auth, safe="")}@{MAIN_DOMAIN}:24443'
            f'?security=tls&alpn=h3&sni={MAIN_DOMAIN}'
        )
        uri = base_query + '#HYSTERIA2'
        outbound = hy2.client_outbound_from_link(uri, PUBLIC_IP, hy2.DEFAULT_CERT)
        self.assertEqual(
            outbound,
            {
                'protocol': 'hysteria',
                'settings': {
                    'version': 2,
                    'address': PUBLIC_IP,
                    'port': 24443,
                },
                'streamSettings': {
                    'network': 'hysteria',
                    'security': 'tls',
                    'hysteriaSettings': {
                        'version': 2,
                        'auth': raw_auth,
                    },
                    'tlsSettings': {
                        'serverName': MAIN_DOMAIN,
                        'alpn': ['h3'],
                        'certificates': [
                            {
                                'certificateFile': '/var/lib/3xui-preview-acme/config/live/3xui-preview/fullchain.pem',
                                'usage': 'verify',
                            }
                        ],
                    },
                },
            },
        )
        self.assertNotIn('allowInsecure', outbound['streamSettings']['tlsSettings'])

        with self.assertRaises(ValueError):
            hy2.client_outbound_from_link(base_query + '&insecure=1#HYSTERIA2', PUBLIC_IP, hy2.DEFAULT_CERT)
        with self.assertRaises(ValueError):
            hy2.client_outbound_from_link(base_query + '&allowInsecure=1#HYSTERIA2', PUBLIC_IP, hy2.DEFAULT_CERT)
        with self.assertRaises(ValueError):
            hy2.client_outbound_from_link(uri, PUBLIC_IP, '')

    def test_extract_hysteria2_links_handles_api_and_subscription_shapes(self):
        import base64

        uri = f'hysteria2://abc@{MAIN_DOMAIN}:24443?security=tls&alpn=h3&sni={MAIN_DOMAIN}#HYSTERIA2'
        self.assertEqual(hy2.extract_hysteria2_links([{'tag': 'P0', 'link': 'vless://x'}, {'tag': 'HYSTERIA2', 'link': uri}]), [uri])
        self.assertEqual(hy2.extract_hysteria2_links([uri]), [uri])
        b64_sub = base64.b64encode(f'vless://x\n{uri}\n'.encode('utf-8')).decode('ascii')
        self.assertEqual(hy2.extract_hysteria2_links(b64_sub), [uri])


if __name__ == '__main__':
    unittest.main()
