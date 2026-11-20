from pathlib import Path
import socket
import sys
import unittest
from unittest import mock


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'release'))
import preview_install as installer
import preview_transport as transport


class PreviewTransportContracts(unittest.TestCase):
    def test_sni_routes_to_distinct_backends_and_rejects_unknown_handshakes(self):
        stream = transport.stream_config('example.test').decode()
        self.assertIn('listen 127.0.0.1:443;', stream)
        self.assertIn('p0.example.test 127.0.0.1:19440;', stream)
        self.assertIn('p3.example.test 127.0.0.1:19443;', stream)
        self.assertIn('panel.example.test 127.0.0.1:18443;', stream)
        self.assertIn('default 127.0.0.1:18443;', stream)
        self.assertNotIn('proxy_protocol', stream)
        web = installer.nginx_config('example.test', 80, ('/cert', '/key'), transports=True).decode()
        self.assertIn('ssl_reject_handshake on;', web)
        self.assertIn('grpc_pass grpc://127.0.0.1:19441;', web)
        self.assertIn('listen 127.0.0.1:19444 ssl;', web)
        self.assertIn('location ^~ /.well-known/acme-challenge/', web)
        self.assertIn('if ($ssl_server_name != panel.example.test) { return 421; }', web)

    def test_foreign_tcp_listener_is_refused_before_creating_any_file(self):
        with mock.patch.object(transport, 'FILES', {}), \
                mock.patch.object(transport.subprocess, 'check_output', return_value='LISTEN'), \
                mock.patch.object(socket, 'socket') as probe:
            with self.assertRaisesRegex(RuntimeError, 'TCP 443 already has a listener'):
                transport.check_available()
            probe.assert_not_called()
