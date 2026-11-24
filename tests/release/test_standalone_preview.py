from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'release'), str(ROOT / 'tools')]
import fetch_preview_components as fetch
import preview_acme as acme
import preview_install as install
import preview_transport as transport
import preview_nginx_packages as nginx


class StandaloneContracts(unittest.TestCase):
    def test_awg_archive_checks_both_members_and_rejects_tampering(self):
        with tempfile.TemporaryDirectory() as folder:
            scratch = Path(folder)
            fetch.unpack_awg(fetch.AWG_ARCHIVE, scratch / 'awg')
            self.assertEqual({f.name for f in (scratch / 'awg').iterdir()}, {'awg', 'amneziawg-go'})
            damaged = scratch / 'damaged.tgz'
            damaged.write_bytes(fetch.AWG_ARCHIVE.read_bytes() + b'extra')
            with self.assertRaisesRegex(ValueError, 'SHA256 mismatch'):
                fetch.unpack_awg(damaged, scratch / 'refused')
            self.assertFalse((scratch / 'refused').exists())

    def test_public_listener_keeps_private_backends_and_http01_names(self):
        self.assertIn(b'listen 10.77.5.1:443;', transport.stream_config('example.test', '10.77.5.1'))
        self.assertIn(b'listen 127.0.0.1:443;', transport.stream_config('example.test'))
        http = install.nginx_config('example.test', 80, public_address='10.77.5.1')
        self.assertIn(b'server_name example.test panel.example.test p0.example.test p3.example.test;', http)
        self.assertIn(b'/.well-known/acme-challenge/', http)
        self.assertNotIn(b'proxy_pass', http)

    def test_acme_requires_exact_dns_and_refuses_test_net_for_public_ca(self):
        with self.assertRaisesRegex(RuntimeError, 'globally routable'):
            acme.validate_network('example.test', '10.77.5.1', None, None)
        answer = (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('10.77.5.9', 80))
        with mock.patch.object(socket, 'socket'), \
                mock.patch.object(socket, 'getaddrinfo', return_value=[answer]):
            with self.assertRaisesRegex(RuntimeError, 'DNS for example.test'):
                acme.validate_network('example.test', '10.77.5.1', 'https://10.77.5.2:14000/dir', Path('/ca.pem'))

    def test_renewal_uses_isolated_lineage_and_nginx_validation(self):
        entries = {path.name: value for path, value, _ in acme.renewal_files(None)}
        service = entries['3xui-preview-renew.service']
        self.assertIn(b'--config-dir /var/lib/3xui-preview-acme/config', service)
        self.assertIn(b'--cert-name 3xui-preview', service)
        self.assertIn(b'--deploy-hook /var/lib/3xui-preview-acme/renew-deploy', service)
        self.assertIn(b'Persistent=true', entries['3xui-preview-renew.timer'])
        self.assertIn(b'set -eu\n/usr/sbin/nginx -t\n/usr/bin/systemctl reload nginx', entries['renew-deploy'])


class PinnedNginxContracts(unittest.TestCase):
    def test_preserves_existing_different_nginx_version(self):
        old = mock.Mock(returncode=0, stdout='installed\t1.26.3-3+deb13u10')
        with mock.patch.object(nginx.subprocess, 'run', return_value=old):
            with self.assertRaisesRegex(RuntimeError, 'no automatic replacement'):
                nginx.missing()

    def test_missing_packages_and_exact_package_metadata(self):
        absent = mock.Mock(returncode=1, stdout='')
        with mock.patch.object(nginx.subprocess, 'run', return_value=absent):
            self.assertEqual(set(nginx.missing()), set(nginx.PACKAGES))
        def download(url, checksum, path):
            self.assertTrue(url.startswith(nginx.POOL))
            self.assertEqual(checksum, nginx.PACKAGES['nginx'][1])
            path.write_bytes(b'synthetic DEB')
        with tempfile.TemporaryDirectory() as temp, mock.patch.object(
                nginx.subprocess, 'check_output', side_effect=['nginx', nginx.VERSION, 'arm64']):
            with self.assertRaisesRegex(RuntimeError, 'invalid Architecture'):
                nginx.stage(Path(temp), ['nginx'], download)
