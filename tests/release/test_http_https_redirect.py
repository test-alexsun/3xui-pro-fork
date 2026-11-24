"""Redirect and rollback contracts; earlier preview tests are preserved."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'release'))
import preview_install as install
import preview_two_domain as two

MAIN='de126.alexsun55.ru';SUB='de126-sub.alexsun55.ru'
SPEC={'subscription_domain':SUB,'p0_port':8443,'p3_port':9443,'subscription_port':2096,'panel_path':'/console-0123456789abcdef/'}

class RedirectContracts(unittest.TestCase):
    def test_bootstrap_keeps_http_content_until_tls_exists(self):
        config=two.nginx(MAIN,80,None,None,'179.254.154.126',SPEC).decode()
        self.assertIn('try_files /index.html =404;',config)
        self.assertNotIn('return 308 https://',config)

    def test_tls_redirects_fixed_two_authorities_and_preserves_http01(self):
        config=two.nginx(MAIN,80,('/cert','/key'),None,'179.254.154.126',SPEC).decode()
        http=config.split('map $http_upgrade')[0]
        self.assertNotIn('index.html',http)
        for name in (MAIN,SUB):
            self.assertIn('return 308 https://'+name+'$request_uri;',http)
        self.assertEqual(http.count('location ^~ /.well-known/acme-challenge/'),2)
        self.assertNotIn('https://$host',http)

    def test_readiness_waits_for_redirect_worker(self):
        stale=mock.Mock(status=200);stale.getheader.return_value=None
        fresh=mock.Mock(status=308);fresh.getheader.return_value='https://'+MAIN+'/'
        connections=[]
        def connection(*args,**kwargs):
            value=mock.Mock();value.getresponse.return_value=(stale if not connections else fresh)
            connections.append(value);return value
        with mock.patch.object(install.http.client,'HTTPConnection',side_effect=connection),mock.patch.object(install.time,'sleep'):
            install.check_http_redirect(MAIN,80)
        self.assertEqual(len(connections),2)
        self.assertTrue(all(x.close.called for x in connections))

    def test_readiness_rejects_different_redirect_authority(self):
        connection=mock.Mock();connection.getresponse.return_value.status=308
        connection.getresponse.return_value.getheader.return_value='https://'+SUB+'/'
        with mock.patch.object(install.http.client,'HTTPConnection',return_value=connection),mock.patch.object(install.time,'sleep'):
            with self.assertRaisesRegex(RuntimeError,'redirect verification failed'):
                install.check_http_redirect(MAIN,80)
        self.assertEqual(connection.request.call_count,30)

    def rollback_fixture(self,redirect):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);data=root/'data';data.mkdir(mode=0o700)
            web=root/'web.html';web.write_bytes(b'old html');web.chmod(0o644)
            nginx=root/'nginx.conf';nginx.write_bytes(b'old config');nginx.chmod(0o644)
            state=data/'state.json'
            old={'phase':'READY','domain':MAIN,'port':80,'public_address':'10.77.5.1','layout':SPEC,
                 'sandbox':True,'html':install.digest(b'old html'),'nginx':install.digest(b'old config')}
            if redirect:old['http_redirect']=True
            state.write_text(json.dumps(old));state.chmod(0o600)
            counter=0
            def run(*args):
                nonlocal counter
                if args==('nginx','-t'):
                    counter+=1
                    if counter==1:raise install.subprocess.CalledProcessError(1,args)
            with mock.patch.multiple(install,DATA=data,WEB=web,NGINX=nginx,STATE=state),mock.patch.object(install,'run',side_effect=run),mock.patch.object(install,'check_http') as body,mock.patch.object(install,'check_http_redirect') as location,mock.patch.object(install,'check_sandbox_https'):
                with self.assertRaisesRegex(RuntimeError,'previous configuration restored'):
                    install.publish(MAIN,80,b'new html',sandbox=('/cert','/key'),public_address='10.77.5.1',layout=SPEC)
                self.assertEqual(nginx.read_bytes(),b'old config')
                self.assertEqual(web.read_bytes(),b'old html')
                self.assertEqual(json.loads(state.read_text()),old)
                if redirect:
                    self.assertEqual(location.call_args_list,[mock.call(MAIN,80),mock.call(SUB,80)])
                    body.assert_not_called()
                else:
                    body.assert_called_once_with(MAIN,80,b'old html')
                    location.assert_not_called()

    def test_rollback_validates_previous_redirect_contract(self):
        self.rollback_fixture(True)

    def test_rollback_preserves_previous_http_content_contract(self):
        self.rollback_fixture(False)

if __name__=='__main__':unittest.main()
