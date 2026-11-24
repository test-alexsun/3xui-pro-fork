import importlib.util
import json
import os
import sqlite3
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

repo = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(repo / 'release'))
spec = importlib.util.spec_from_file_location('preview_install', repo / 'release/preview_install.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class PublishTest(unittest.TestCase):
    @unittest.skipUnless(os.name == 'posix' and os.geteuid() == 0, 'requires root Linux fixture')
    def test_new_web_directories_ignore_restrictive_umask_without_changing_existing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            module.WEB = root / 'site' / 'decoy' / 'index.html'
            mask = os.umask(0o077)
            try:
                module.ensure_web_directories()
            finally:
                os.umask(mask)
            self.assertEqual(module.WEB.parent.parent.stat().st_mode & 0o777, 0o755)
            self.assertEqual(module.WEB.parent.stat().st_mode & 0o777, 0o755)
            module.WEB.parent.chmod(0o700)
            with self.assertRaisesRegex(RuntimeError, 'not accessible'):
                module.ensure_web_directories()
            self.assertEqual(module.WEB.parent.stat().st_mode & 0o777, 0o700)

    def test_repeat_and_invalid_candidate_restore(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            module.DATA = root / 'data'; module.DATA.mkdir(mode=0o700)
            module.STATE = module.DATA / 'state.json'
            module.WEB = root / 'web' / 'index.html'; module.WEB.parent.mkdir()
            module.NGINX = root / 'conf' / 'site.conf'; module.NGINX.parent.mkdir()
            module.WEB.write_bytes(b'old html')
            module.NGINX.write_bytes(b'old config')
            old = {'phase': 'READY', 'domain': 'example.test', 'port': 18080,
                   'html': module.digest(b'old html'), 'nginx': module.digest(b'old config')}
            module.STATE.write_text(json.dumps(old)); module.STATE.chmod(0o600)
            calls = []
            def run(*args):
                calls.append(args)
                if args == ('nginx', '-t') and calls.count(args) == 1:
                    raise module.subprocess.CalledProcessError(1, args)
            with mock.patch.object(module, 'run', side_effect=run), mock.patch.object(module, 'check_http') as http:
                with self.assertRaisesRegex(RuntimeError, 'previous configuration restored'):
                    module.publish('example.test', 18080, b'new html')
                self.assertEqual(module.WEB.read_bytes(), b'old html')
                self.assertEqual(module.NGINX.read_bytes(), b'old config')
                self.assertEqual(json.loads(module.STATE.read_text()), old)
                http.assert_called_once_with('example.test', 18080, b'old html')
            with mock.patch.object(module, 'run'), mock.patch.object(module, 'check_http'):
                module.publish('example.test', 18080, b'new html')
                module.publish('example.test', 18080, b'new html')
            self.assertEqual(module.WEB.read_bytes(), b'new html')
            self.assertEqual(json.loads(module.STATE.read_text())['phase'], 'READY')
            before = module.NGINX.read_bytes()
            reloads = []
            def reload_fails_once(*args):
                if args == ('systemctl', 'reload', 'nginx'):
                    reloads.append(args)
                    if len(reloads) == 1:
                        raise module.subprocess.CalledProcessError(1, args)
            with mock.patch.object(module, 'run', side_effect=reload_fails_once), mock.patch.object(module, 'check_http'):
                with self.assertRaisesRegex(RuntimeError, 'previous configuration restored'):
                    module.publish('example.test', 18080, b'another html')
            self.assertEqual(module.WEB.read_bytes(), b'new html')
            self.assertEqual(module.NGINX.read_bytes(), before)
            self.assertEqual(len(reloads), 2)

    def test_unowned_and_changed_files_are_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            module.DATA = root; module.STATE = root / 'state.json'
            module.WEB = root / 'index.html'; module.NGINX = root / 'site.conf'
            module.WEB.write_bytes(b'user site')
            with self.assertRaisesRegex(RuntimeError, 'unowned path'):
                module.publish('example.test', 18080, b'new html')
            self.assertEqual(module.WEB.read_bytes(), b'user site')

    def test_nginx_conflicts_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            module.WEB = root / 'index.html'; module.NGINX = root / 'site.conf'
            def output(*args, **kw):
                if args[0][0] == 'nginx':
                    return 'server { server_name example.test; listen 80; }'
                raise AssertionError('listener check should not be reached')
            with mock.patch.object(module.subprocess, 'check_output', side_effect=output):
                with self.assertRaisesRegex(RuntimeError, 'server_name may conflict'):
                    module.preflight_nginx('example.test', 80)
            def occupied(*args, **kw):
                return 'server { server_name _; listen 80; }' if args[0][0] == 'nginx' else 'LISTEN 0 10 0.0.0.0:80 0.0.0.0:* users:(("other",pid=1,fd=2))'
            with mock.patch.object(module.subprocess, 'check_output', side_effect=occupied):
                with self.assertRaisesRegex(RuntimeError, 'non-nginx'):
                    module.preflight_nginx('example.test', 80)

    def test_first_publication_failure_keeps_recovery_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            module.DATA = root / 'data'; module.DATA.mkdir(mode=0o700)
            module.STATE = module.DATA / 'state.json'
            module.WEB = root / 'web' / 'index.html'; module.WEB.parent.mkdir()
            module.NGINX = root / 'conf' / 'site.conf'; module.NGINX.parent.mkdir()
            calls = []
            def run(*args):
                calls.append(args)
                if args == ('nginx', '-t') and calls.count(args) == 1:
                    raise module.subprocess.CalledProcessError(1, args)
            with mock.patch.object(module, 'preflight_nginx'), mock.patch.object(module, 'run', side_effect=run):
                with self.assertRaisesRegex(RuntimeError, 'RECOVERY_REQUIRED'):
                    module.publish('example.test', 18080, b'new html')
            self.assertFalse(module.WEB.exists())
            self.assertFalse(module.NGINX.exists())
            self.assertEqual(json.loads(module.STATE.read_text())['phase'], 'RECOVERY_REQUIRED')

    def test_sandbox_is_loopback_and_fail_closed_on_repeat(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            module.DATA = root / 'data'; module.DATA.mkdir(mode=0o700)
            module.STATE = module.DATA / 'state.json'
            module.WEB = root / 'web' / 'index.html'; module.WEB.parent.mkdir()
            module.NGINX = root / 'conf' / 'site.conf'; module.NGINX.parent.mkdir()
            sandbox = ('/tmp/sandbox-cert.pem', '/tmp/sandbox-key.pem')
            with mock.patch.object(module, 'preflight_nginx'), mock.patch.object(module, 'sandbox_listener_available') as probe, mock.patch.object(module, 'run'), mock.patch.object(module, 'check_http'), mock.patch.object(module, 'check_sandbox_https') as check:
                module.publish('example.test', 18080, b'html', sandbox)
                probe.assert_called_once()
                check.assert_called_once_with('example.test', b'html')
                text = module.NGINX.read_text()
                self.assertEqual(text.count('listen 127.0.0.1:18443 ssl;'), 2)
                self.assertIn('server_name panel.example.test;', text)
                self.assertIn('proxy_pass http://127.0.0.1:2053;', text)
                self.assertIn('location ^~ /.well-known/acme-challenge/', text)
                self.assertNotIn('try_files $uri /index.html', text)
                self.assertTrue(json.loads(module.STATE.read_text())['sandbox'])
                with self.assertRaisesRegex(RuntimeError, 'requires the original sandbox options'):
                    module.publish('example.test', 18080, b'html')

    def test_sandbox_rejects_occupied_port(self):
        with mock.patch.object(module.subprocess, 'check_output', side_effect=[
                'server { listen 127.0.0.1:18443 ssl; }']):
            with self.assertRaisesRegex(RuntimeError, 'already exists'):
                module.sandbox_listener_available()

    def test_subscription_settings_read_only_and_route_safety(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'panel.db'
            with sqlite3.connect(path) as db:
                db.execute('create table settings (key text, value text)')
                db.executemany('insert into settings values (?,?)', [
                    ('subEnable', 'true'), ('subListen', '127.0.0.1'),
                    ('subPort', '12996'), ('subPath', '/synthetic/'),
                    ('subURI', 'https://example.test:18443/synthetic/'),
                    ('subJsonEnable', 'false'), ('subClashEnable', 'false')])
            path.chmod(0o600)
            before = path.read_bytes()
            listener = 'LISTEN 0 128 127.0.0.1:12996 0.0.0.0:* users:(("x-ui",pid=42,fd=7))'
            with mock.patch.object(module.socket, 'create_connection'), mock.patch.object(module.subprocess, 'check_output', return_value=listener):
                route = module.subscription_config(path, 'example.test', 42)
            with mock.patch.object(module.subprocess, 'check_output', return_value=listener):
                with self.assertRaisesRegex(RuntimeError, 'not owned'):
                    module.subscription_config(path, 'example.test', 43)
            self.assertEqual(route, {'port': 12996, 'paths': ['/synthetic/']})
            self.assertEqual(path.read_bytes(), before)
            config = module.nginx_config('example.test', 18080, ('/cert', '/key'), route).decode()
            self.assertIn('location ^~ /synthetic/', config)
            self.assertIn('proxy_pass http://127.0.0.1:12996;', config)
            self.assertIn('access_log off;', config)
            self.assertIn('error_log /dev/null crit;', config)
            self.assertIn('proxy_cache off;', config)
            self.assertIn('add_header Referrer-Policy no-referrer always;', config)
            with sqlite3.connect(path) as db:
                db.execute("update settings set value='true' where key='subJsonEnable'")
                db.execute("insert into settings values ('subJsonPath','/json-fixture/')")
                db.execute("insert into settings values ('subJsonURI','https://example.test:18443/json-fixture/')")
            with mock.patch.object(module.socket, 'create_connection'), mock.patch.object(module.subprocess, 'check_output', return_value=listener):
                self.assertEqual(module.subscription_config(path, 'example.test', 42)['paths'], ['/synthetic/', '/json-fixture/'])
            with sqlite3.connect(path) as db:
                db.execute("update settings set value='/synthetic/child/' where key='subJsonPath'")
            with self.assertRaisesRegex(RuntimeError, 'overlapping subscription paths'):
                module.subscription_config(path, 'example.test', 42)
            with sqlite3.connect(path) as db:
                db.execute("update settings set value='false' where key='subJsonEnable'")
            with sqlite3.connect(path) as db:
                db.execute("update settings set value='' where key='subListen'")
            with self.assertRaisesRegex(RuntimeError, 'explicitly listen'):
                module.subscription_config(path, 'example.test', 42)
            with sqlite3.connect(path) as db:
                db.execute("update settings set value='127.0.0.1' where key='subListen'")
                db.execute("update settings set value='/panel/' where key='subPath'")
            with self.assertRaisesRegex(RuntimeError, 'reserved route'):
                module.subscription_config(path, 'example.test', 42)
            with sqlite3.connect(path) as db:
                db.execute("update settings set value='/synthetic/' where key='subPath'")
                db.execute("update settings set value='https://wrong.test/synthetic/' where key='subURI'")
            with self.assertRaisesRegex(RuntimeError, 'explicit subscription URL'):
                module.subscription_config(path, 'example.test', 42)


if __name__ == '__main__':
    unittest.main()
