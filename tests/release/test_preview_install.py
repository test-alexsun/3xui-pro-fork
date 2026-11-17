import importlib.util
import json
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


if __name__ == '__main__':
    unittest.main()
