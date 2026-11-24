"""Unit tests for Hysteria2 auth generation and client add/rotate-auth/disable payloads."""
import base64
from pathlib import Path
import re
import sys
import unittest

RELEASE = Path(__file__).resolve().parents[3] / 'release'
if str(RELEASE) not in sys.path:
    sys.path.insert(0, str(RELEASE))

import preview_hysteria2 as hy2


class Hysteria2ClientTests(unittest.TestCase):
    def test_generate_auth_is_unique_and_32_byte_urlsafe(self):
        tokens = [hy2.generate_auth() for _ in range(64)]
        self.assertEqual(len(set(tokens)), 64)
        for token in tokens:
            self.assertRegex(token, r'^[A-Za-z0-9_-]{43}$')
            padded = token + '=' * (-len(token) % 4)
            self.assertEqual(len(base64.urlsafe_b64decode(padded)), 32)

    def test_build_client_payload_generates_defaults_and_preserves_explicit_values(self):
        client = hy2.build_client_payload('hy2-user@example.test')
        self.assertEqual(client['email'], 'hy2-user@example.test')
        self.assertTrue(client['enable'])
        self.assertTrue(client['auth'])
        self.assertTrue(client['subId'])
        self.assertRegex(client['subId'], r'^[A-Za-z0-9_-]+$')

        explicit = hy2.build_client_payload(
            'hy2-explicit',
            auth='custom-auth-secret',
            enable=False,
            sub_id='custom-sub-id',
        )
        self.assertEqual(
            explicit,
            {
                'email': 'hy2-explicit',
                'enable': False,
                'auth': 'custom-auth-secret',
                'subId': 'custom-sub-id',
            },
        )

    def test_build_client_payload_rejects_empty_or_whitespace_fields(self):
        for bad in ('', ' ', 'bad email', 'line\nbreak'):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    hy2.build_client_payload(bad)
                with self.assertRaises(ValueError):
                    hy2.build_client_payload('valid-email', auth=bad)
                with self.assertRaises(ValueError):
                    hy2.build_client_payload('valid-email', sub_id=bad)

    def test_build_client_add_payload_matches_panel_contract(self):
        envelope = hy2.build_client_add_payload(6, 'hy2-user', auth='tok123', sub_id='sub123')
        self.assertEqual(
            envelope,
            {
                'client': {
                    'email': 'hy2-user',
                    'enable': True,
                    'auth': 'tok123',
                    'subId': 'sub123',
                },
                'inboundIds': [6],
            },
        )
        with self.assertRaises(ValueError):
            hy2.build_client_add_payload(0, 'hy2-user')
        with self.assertRaises(ValueError):
            hy2.build_client_add_payload(True, 'hy2-user')
        with self.assertRaises(ValueError):
            hy2.build_client_add_payload([], 'hy2-user')

    def test_build_client_update_payload_supports_disable_preserve_and_rotate_auth(self):
        # Disable without rotating auth: omits 'auth' so client_crud.go preserves existing auth.
        disable_payload = hy2.build_client_update_payload('hy2-user', enable=False, sub_id='sub123')
        self.assertEqual(
            disable_payload,
            {
                'email': 'hy2-user',
                'enable': False,
                'subId': 'sub123',
            },
        )
        self.assertNotIn('auth', disable_payload)

        # Rotate auth: non-empty 'auth' causes client_crud.go to update the secret.
        new_auth = hy2.generate_auth()
        rotate_payload = hy2.build_client_update_payload('hy2-user', enable=True, auth=new_auth, sub_id='sub123')
        self.assertEqual(
            rotate_payload,
            {
                'email': 'hy2-user',
                'enable': True,
                'auth': new_auth,
                'subId': 'sub123',
            },
        )

        with self.assertRaises(ValueError):
            hy2.build_client_update_payload('hy2-user')
        with self.assertRaises(ValueError):
            hy2.build_client_update_payload('hy2-user', enable=True, auth='')


if __name__ == '__main__':
    unittest.main()
