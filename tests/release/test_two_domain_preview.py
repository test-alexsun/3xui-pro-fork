"""Contracts for the public two-domain deployment; historical tests stay unchanged."""
import argparse
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'release'))
import preview_install as installer
import preview_two_domain as two
import preview_transport as transport
import preview_acme as acme

MAIN = 'de126.alexsun55.ru'
SUB = 'de126-sub.alexsun55.ru'
SPEC = {'subscription_domain': SUB, 'p0_port': 8443, 'p3_port': 9443,
        'subscription_port': 2096, 'panel_path': '/console-0123456789abcdef/'}


def options(**kw):
    args = dict(domain=MAIN, subscription_domain=SUB, public_bind='179.254.154.126',
                public_subscriptions=False, panel_path=SPEC['panel_path'], p0_port=8443,
                p3_port=9443, subscription_port=2096)
    args.update(kw)
    return argparse.Namespace(**args)


class TwoDomainContracts(unittest.TestCase):
    def test_only_two_acme_identifiers_and_dns_queries(self):
        asked = []
        def dns(host, *a, **kw):
            asked.append(host)
            return [(2, 1, 6, '', ('179.254.154.126', 80))]
        with mock.patch.object(acme.socket, 'socket'), mock.patch.object(acme.socket, 'getaddrinfo', side_effect=dns):
            acme.validate_network(MAIN, '179.254.154.126', None, None, SUB)
        self.assertEqual(asked, [MAIN, SUB])
        with mock.patch.object(acme, 'certificate', return_value=('cert', 'key')):
            run = mock.Mock()
            acme.issue(MAIN, 'fixture@example.test', acme.DEFAULT_DIRECTORY, None, Path('/web'), run, SUB)
        cmd = run.call_args.args
        self.assertEqual([cmd[i+1] for i, x in enumerate(cmd) if x == '-d'], [MAIN, SUB])

    def test_aaaa_and_conflicting_a_are_refused(self):
        for address in ('::1', '179.254.154.127'):
            with mock.patch.object(acme.socket, 'socket'), mock.patch.object(acme.socket, 'getaddrinfo', return_value=[(2,1,6,'',(address,80))]):
                with self.assertRaisesRegex(RuntimeError, 'solely'):
                    acme.validate_network(MAIN, '179.254.154.126', None, None, SUB)

    def test_exact_certificate_rejects_extra_san(self):
        text = 'X509v3 Subject Alternative Name:\n    DNS:' + MAIN + ', DNS:' + SUB
        with mock.patch.object(acme.subprocess, 'check_output', return_value=text):
            acme.exact_names('cert', MAIN, SUB)
        with mock.patch.object(acme.subprocess, 'check_output', return_value=text + ', DNS:panel.' + MAIN):
            with self.assertRaisesRegex(RuntimeError, 'exactly'):
                acme.exact_names('cert', MAIN, SUB)

    def test_cli_rejects_colliding_ports_domains_and_paths(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(two, 'PANEL_STATE', Path(tmp)/'absent'):
            self.assertEqual(two.layout(options(), lambda p: None), SPEC)
            for kw in ({'p0_port': 443}, {'p3_port': 8443}, {'subscription_port': 9443},
                       {'domain': SUB}, {'subscription_domain': 'bad;name'}, {'panel_path': '/panel/'},
                       {'panel_path': '/xhttp-0123456789abcdef/'}, {'public_subscriptions': True}):
                with self.subTest(kw=kw), self.assertRaises(RuntimeError):
                    two.layout(options(**kw), lambda p: None)

    def test_panel_path_reused_and_identity_change_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'panel.json';path.write_text(json.dumps({'layout':SPEC}));path.chmod(0o600)
            with mock.patch.object(two,'PANEL_STATE',path):
                self.assertEqual(two.layout(options(panel_path=None),lambda p:None),SPEC)
                with self.assertRaisesRegex(RuntimeError,'identity changed'):
                    two.layout(options(p0_port=8543),lambda p:None)

    def test_dedicated_subscription_vhost_has_no_panel_or_game(self):
        config=two.nginx(MAIN,80,('/cert','/key'),{'port':2096,'paths':['/sub/','/json/','/clash/']},'179.254.154.126',SPEC).decode()
        subblock=config.split('server_name '+SUB+';')[-1].split('server {')[0]
        self.assertIn('proxy_pass http://127.0.0.1:2096;',subblock)
        self.assertNotIn('2053',subblock);self.assertNotIn('index.html',subblock)
        self.assertIn('access_log off;',subblock);self.assertIn('location / { return 404; }',subblock)
        self.assertIn('proxy_cookie_flags ~ secure httponly samesite=lax;',config)
        self.assertIn('port_in_redirect off;',config)
        self.assertIn('proxy_set_header Connection $preview_connection_upgrade;',config)
        for prefix in ('panel.','p0.','p3.'):
            self.assertNotIn(prefix+MAIN,config)

    def test_profiles_keep_protocols_with_one_hostname_and_distinct_ports(self):
        with mock.patch.object(transport.subprocess,'run'), mock.patch.object(transport.subprocess,'check_output',return_value='PrivateKey: PRIVATE\nPassword: PUBLIC\n'):
            files=transport.new_files(MAIN,('/cert','/key'),'179.254.154.126',layout=SPEC)
        clients=json.loads(files['clients']);server=json.loads(files['xray'])
        for inbound,profile,port in zip(server['inbounds'],('P0','P1','P3'),(8443,443,9443)):
            outbound=clients[profile]['outbounds'][0]
            self.assertEqual(outbound['settings']['vnext'][0]['address'],MAIN)
            self.assertEqual(outbound['settings']['vnext'][0]['port'],port)
            stream=outbound['streamSettings']
            self.assertEqual(stream['security'],'tls' if profile=='P1' else 'reality')
            if profile=='P1':
                self.assertEqual(inbound['listen'],'127.0.0.1');self.assertEqual(inbound['port'],19441)
                self.assertEqual(stream['tlsSettings']['alpn'],['h2'])
            else:
                self.assertEqual(inbound['listen'],'179.254.154.126');self.assertEqual(inbound['port'],port)
                self.assertEqual(inbound['streamSettings']['realitySettings']['serverNames'],[MAIN])
                self.assertEqual(inbound['streamSettings']['realitySettings']['target'],'127.0.0.1:19444')
            if profile=='P3':self.assertEqual(outbound['settings']['vnext'][0]['users'][0]['flow'],'xtls-rprx-vision')

    def test_public_reality_port_conflict_refused(self):
        with mock.patch.object(transport,'FILES',{}), mock.patch.object(transport.socket,'socket'), mock.patch.object(transport.subprocess,'check_output',side_effect=lambda args,**kw:'foreign listener' if ':8443' in args[-1] else ''):
            with self.assertRaisesRegex(RuntimeError,'8443 already'):
                transport.check_available('179.254.154.126',SPEC)

    def test_repeat_refuses_settings_drift_without_api_or_cli_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            state=Path(tmp)/'panel.json';state.write_text(json.dumps({'phase':'READY','domain':MAIN,'layout':SPEC}));state.chmod(0o600)
            expected=two.desired_settings(MAIN,SPEC)
            with mock.patch.object(two,'PANEL_STATE',state),mock.patch.object(two,'settings',return_value=expected),mock.patch.object(two.subprocess,'run') as run:
                two.panel_setup(MAIN,SPEC,False,mock.Mock(),lambda p:None,mock.Mock())
                run.assert_not_called()
                expected['subListen']='0.0.0.0'
                with self.assertRaisesRegex(RuntimeError,'changed externally'):
                    two.panel_setup(MAIN,SPEC,False,mock.Mock(),lambda p:None,mock.Mock())
                run.assert_not_called()

    def test_reload_waits_for_new_worker_response(self):
        stale=mock.MagicMock();stale.__enter__.return_value.status=200;stale.__enter__.return_value.read.return_value=b'old vhost'
        fresh=mock.MagicMock();fresh.__enter__.return_value.status=200;fresh.__enter__.return_value.read.return_value=b'XONIX'
        client=mock.Mock();client.open.side_effect=[stale,fresh]
        with mock.patch.object(installer.urllib.request,'build_opener',return_value=client),mock.patch.object(installer.time,'sleep'):
            installer.check_http(MAIN,80,b'XONIX')
        self.assertEqual(client.open.call_count,2)

    def test_existing_unowned_panel_is_not_adopted(self):
        with tempfile.TemporaryDirectory() as tmp,mock.patch.object(two,'PANEL_STATE',Path(tmp)/'absent'),mock.patch.object(two.subprocess,'run') as run:
            with self.assertRaisesRegex(RuntimeError,'adoption refused'):
                two.panel_setup(MAIN,SPEC,False,mock.Mock(),lambda p:None,mock.Mock())
            run.assert_not_called()

if __name__=='__main__':unittest.main()
