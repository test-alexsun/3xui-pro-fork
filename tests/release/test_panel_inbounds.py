"""Native ownership/identity contracts; real API/transport gates run in Debian VM."""
import copy
import base64
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'release'))
import preview_panel_inbounds as native
import preview_install as install
from preview_panel_api import PanelAPI,PanelAPIError

MAIN='de126.alexsun55.ru';SUB='de126-sub.alexsun55.ru'
IDS={'P0':'00000000-0000-4000-8000-000000000001','P1':'00000000-0000-4000-8000-000000000002','P3':'00000000-0000-4000-8000-000000000003'}

def fixture():
    config={'inbounds':[]};clients={}
    for p in ['P0','P1','P3']:
        stream={'network':'raw' if p=='P3' else 'xhttp','security':'none' if p=='P1' else 'reality'}
        if p!='P3':stream['xhttpSettings']={'host':MAIN,'path':'/xhttp/','mode':'stream-up'}
        if p!='P1':stream['realitySettings']={'target':'127.0.0.1:19444','serverNames':[MAIN],'privateKey':'A'*43,'shortIds':['0123456789abcdef']}
        user={'id':IDS[p],'email':'preview-'+p}
        if p=='P3':user['flow']='xtls-rprx-vision'
        config['inbounds'].append({'tag':p,'protocol':'vless','listen':'127.0.0.1' if p=='P1' else '179.254.154.126','port':{'P0':8443,'P1':19441,'P3':9443}[p],'settings':{'clients':[user],'decryption':'none'},'streamSettings':stream})
        clients[p]={'outbounds':[{'streamSettings':{'realitySettings':{'password':'public-key-'+p}}}]}
    return config,clients

def live_fixture():
    source,clients=fixture();blueprints,people=native.blueprints(source,clients,MAIN);registry={'P0':1,'P1':2,'P3':3};entries=[];runtime=[];users={}
    for profile,payload in blueprints.items():
        entry=copy.deepcopy(payload);entry.update(id=registry[profile],enable=True)
        person=people['preview-'+profile]['client'];entry['settings']['clients']=[copy.deepcopy(person)];entries.append(entry)
        runtime.append({'tag':payload['tag'],'receiverSettings':{'listen':payload['listen'],'portList':payload['port'],'streamSettings':{'protocolName':'splithttp' if profile!='P3' else 'tcp','securityType':payload['streamSettings']['security']}}})
        actual=runtime[-1]['receiverSettings']['streamSettings']
        if profile in ['P0','P3']:
            actual['securitySettings']=[{'_TypedMessage_':'xray.transport.internet.reality.Config','privateKey':[0]*32,'shortIds':[list(bytes.fromhex('0123456789abcdef'))],'dest':'127.0.0.1:19444','serverNames':[MAIN]}]
        if profile!='P3':actual['transportSettings']=[{'protocolName':'splithttp','settings':copy.deepcopy(payload['streamSettings']['xhttpSettings'])}]
        users[payload['tag']]=[{'email':person['email'],'account':{'id':person['id'],'flow':person.get('flow','')}}]
    return blueprints,registry,entries,runtime,users

class NativeBlueprintContracts(unittest.TestCase):
    def test_preserves_real_uuid_private_key_short_id_and_listener(self):
        original,clients=fixture();snapshot=copy.deepcopy(original);blueprints,people=native.blueprints(original,clients,MAIN)
        self.assertEqual(original,snapshot)
        for source in original['inbounds']:
            p=source['tag'];self.assertEqual(people['preview-'+p]['client']['id'],IDS[p]);self.assertEqual(blueprints[p]['port'],source['port']);self.assertFalse(blueprints[p]['enable'])
            if p!='P1':
                for key in ['privateKey','shortIds','serverNames','target']:self.assertEqual(blueprints[p]['streamSettings']['realitySettings'][key],source['streamSettings']['realitySettings'][key])
    def test_p1_native_loopback_and_subscription_tls443_h2_override(self):
        s,c=fixture();b,_=native.blueprints(s,c,MAIN);p=b['P1'];self.assertEqual((p['listen'],p['port'],p['streamSettings']['security']),('127.0.0.1',19441,'none'))
        ep=p['streamSettings']['externalProxy'][0];self.assertEqual((ep['dest'],ep['port'],ep['forceTls'],ep['alpn']),(MAIN,443,'tls',['h2']));self.assertNotIn('allowInsecure',ep)
    def test_raw_alias_becomes_native_tcp_with_vision_preserved(self):
        s,c=fixture();b,p=native.blueprints(s,c,MAIN);self.assertEqual(b['P3']['streamSettings']['network'],'tcp');self.assertEqual(p['preview-P3']['client']['flow'],'xtls-rprx-vision')
    def test_shared_identity_is_one_native_customer_attached_to_three(self):
        s,c=fixture()
        for inbound in s['inbounds']:inbound['settings']['clients'][0].update(id=IDS['P0'],email='shared')
        _,people=native.blueprints(s,c,MAIN);self.assertEqual(len(people),1);self.assertEqual(people['shared']['profiles'],['P0','P1','P3']);self.assertEqual(people['shared']['client']['flow'],'xtls-rprx-vision')
    def test_ambiguous_source_customer_refused_without_regenerating_uuid(self):
        s,c=fixture();s['inbounds'][1]['settings']['clients'][0]['email']='preview-P0'
        with self.assertRaisesRegex(RuntimeError,'ambiguous'):native.blueprints(s,c,MAIN)
    def test_duplicate_listener_refused_before_api(self):
        s,c=fixture();s['inbounds'][2]['port']=8443
        with self.assertRaisesRegex(RuntimeError,'duplicate'):native.blueprints(s,c,MAIN)
    def test_missing_or_unqualified_protocol_refused(self):
        s,c=fixture();s['inbounds'].pop()
        with self.assertRaises(RuntimeError):native.blueprints(s,c,MAIN)
        s,c=fixture();s['inbounds'][0]['streamSettings']['network']='ws'
        with self.assertRaisesRegex(RuntimeError,'XHTTP'):native.blueprints(s,c,MAIN)
    def test_vision_is_never_silently_downgraded(self):
        s,c=fixture();s['inbounds'][2]['settings']['clients'][0].pop('flow')
        with self.assertRaisesRegex(RuntimeError,'Vision'):native.blueprints(s,c,MAIN)

class NativeSelectionContracts(unittest.TestCase):
    def check(self,journal,selected=False,explicit=False,web=True):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);state=root/'journal';webfile=root/'web'
            if journal is not None:state.write_text('{}')
            if web:webfile.write_text('{}')
            args=SimpleNamespace(panel_inbounds=selected,migrate_panel_inbounds=explicit,layout={'subscription_domain':SUB})
            with mock.patch.multiple(native,STATE=state,WEB_STATE=webfile),mock.patch.object(native,'read_journal',return_value=journal):return native.requested(args)
    def test_existing_standalone_requires_separate_explicit_opt_in(self):
        with self.assertRaisesRegex(RuntimeError,'explicit'):self.check(None,selected=True)
        self.assertFalse(self.check(None,selected=True,explicit=True))
    def test_fresh_opt_in_and_ready_repeat_are_distinct(self):
        self.assertFalse(self.check(None,selected=True,web=False));self.assertTrue(self.check({'phase':'READY'},selected=True))
    def test_no_automatic_reversal_of_native_deployment(self):
        with self.assertRaisesRegex(RuntimeError,'reversal'):self.check({'phase':'READY'})
    def test_nonterminal_journal_fails_before_any_api_mutation(self):
        with self.assertRaisesRegex(RuntimeError,'RECOVERY_REQUIRED'):self.check({'phase':'ACTIVATING_NATIVE'},selected=True,explicit=True)

class NativeJournalContracts(unittest.TestCase):
    def test_unknown_version_or_phase_fails_closed(self):
        for value in [{'version':2,'phase':'READY','profiles':{}},{'version':1,'phase':'GUESS','profiles':{}}]:
            with self.assertRaisesRegex(RuntimeError,'RECOVERY_REQUIRED'):native.journal_value(value)
    def test_ready_requires_three_positive_integer_registry_ids(self):
        for registry in [{'P0':1},{'P0':1,'P1':2,'P3':'delete/3'},{'P0':1,'P1':2,'P3':True}]:
            with self.assertRaisesRegex(RuntimeError,'RECOVERY_REQUIRED'):native.journal_value({'version':1,'phase':'READY','profiles':registry})
        self.assertEqual(native.journal_value({'version':1,'phase':'READY','profiles':{'P0':1,'P1':2,'P3':3}})['phase'],'READY')

    def test_duplicate_profile_id_is_not_an_owned_registry(self):
        with self.assertRaisesRegex(RuntimeError,'duplicate'):native.journal_value({'version':1,'phase':'READY','profiles':{'P0':1,'P1':1,'P3':3}})

class NativeLiveContracts(unittest.TestCase):
    def validate(self,change=None,pids=None):
        b,r,e,l,u=live_fixture()
        if change:change(b,r,e,l,u)
        api=mock.Mock();api.call.return_value=e
        def core(operation,*flags):return {'inbounds':l} if operation=='lsi' else {'users':u[flags[0].split('=',1)[1]]}
        with mock.patch.object(native,'core_api',side_effect=core),mock.patch.object(native,'native_pid',return_value=77),mock.patch.object(native,'listener_pids',return_value={77} if pids is None else pids):return native.validate_live(api,r,b)
    def test_live_validation_uses_xray_users_not_stale_generated_file(self):self.assertTrue(self.validate())
    def test_real_client_addition_is_preserved_and_validated(self):
        def add(b,r,e,l,u):
            person=copy.deepcopy(e[0]['settings']['clients'][0]);person['id']='00000000-0000-4000-8000-000000000004';person['email']='new';e[0]['settings']['clients'].append(person);u[native.TAGS['P0']].append({'email':'new','account':{'id':person['id']}})
        self.assertTrue(self.validate(add))
    def test_disabled_client_must_be_absent_from_real_core(self):
        with self.assertRaisesRegex(RuntimeError,'inconsistency'):self.validate(lambda b,r,e,l,u:e[0]['settings']['clients'][0].update(enable=False))
    def test_expired_client_is_absent_from_core(self):
        def expire(b,r,e,l,u):e[0]['settings']['clients'][0]['expiryTime']=1;u[native.TAGS['P0']]=[]
        self.assertTrue(self.validate(expire))
    def test_wrong_listener_owner_refused(self):
        with self.assertRaisesRegex(RuntimeError,'owner'):self.validate(pids={88})
    def test_wrong_live_security_refused(self):
        def change(b,r,e,l,u):l[0]['receiverSettings']['streamSettings']['securityType']='tls'
        with self.assertRaisesRegex(RuntimeError,'security'):self.validate(change)
    def test_live_reality_key_drift_is_refused_even_when_db_is_correct(self):
        def change(b,r,e,l,u):l[0]['receiverSettings']['streamSettings']['securitySettings'][0]['privateKey']=[1]*32
        with self.assertRaisesRegex(RuntimeError,'runtime key differs'):self.validate(change)
    def test_live_xhttp_path_drift_is_refused_even_when_db_is_correct(self):
        def change(b,r,e,l,u):l[0]['receiverSettings']['streamSettings']['transportSettings'][0]['settings']['path']='/wrong/'
        with self.assertRaisesRegex(RuntimeError,'runtime settings differ'):self.validate(change)
    def test_p1_public_subscription_override_drift_is_refused(self):
        def change(b,r,e,l,u):e[1]['streamSettings']['externalProxy'][0]['port']=19441
        with self.assertRaisesRegex(RuntimeError,'public TLS'):self.validate(change)
    def test_missing_native_inbound_refused(self):
        with self.assertRaisesRegex(RuntimeError,'missing'):self.validate(lambda b,r,e,l,u:e.pop())

class PanelAPIContracts(unittest.TestCase):
    def setUp(self):self.state={'domain':MAIN,'layout':{'panel_path':'/console-0123456789abcdef/'},'api_token':'sensitive-credential'}
    def test_loopback_only_and_form_content_type(self):
        api=PanelAPI(self.state);response=mock.Mock(status=200);response.read.return_value=b'{"success":true,"obj":{"ok":true}}';api.opener=mock.Mock();api.opener.open.return_value.__enter__=mock.Mock(return_value=response);api.opener.open.return_value.__exit__=mock.Mock(return_value=False)
        self.assertEqual(api.call('xray/update',{'xraySetting':'{}'},form=True),{'ok':True})
        request=api.opener.open.call_args.args[0];self.assertTrue(request.full_url.startswith('http://127.0.0.1:2053/'));self.assertEqual(request.get_header('Content-type'),'application/x-www-form-urlencoded')
    def test_errors_do_not_reveal_token_or_private_path(self):
        api=PanelAPI(self.state);api.opener=mock.Mock();api.opener.open.side_effect=OSError(self.state['api_token']+self.state['layout']['panel_path'])
        with self.assertRaises(PanelAPIError) as caught:api.call('inbounds/list')
        self.assertNotIn(self.state['api_token'],str(caught.exception));self.assertNotIn(self.state['layout']['panel_path'],str(caught.exception))
    def test_redirect_handler_refuses_credential_forwarding(self):
        api=PanelAPI(self.state);handler=next(h for h in api.opener.handlers if type(h).__name__=='NoRedirect')
        with self.assertRaisesRegex(PanelAPIError,'redirect refused'):handler.redirect_request(None,None,None,None,None,None)
    def test_operation_traversal_refused(self):
        with self.assertRaises(PanelAPIError):PanelAPI(self.state).call('../other')


class NativePublicationContracts(unittest.TestCase):
    def test_pending_web_transaction_validates_native_against_previous_ready_state(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);data=root/'data';data.mkdir(mode=0o700);state=data/'web-state';web=root/'index.html';nginx=root/'nginx.conf'
            web.write_bytes(b'old');nginx.write_bytes(b'old config');web.chmod(0o644);nginx.chmod(0o644)
            layout={'subscription_domain':SUB,'panel_path':'/console-0123456789abcdef/','p0_port':8443,'p3_port':9443,'subscription_port':2096}
            previous={'phase':'READY','domain':MAIN,'port':80,'layout':layout,'public_address':'179.254.154.126','sandbox':True,'http_redirect':True,'panel_managed_inbounds':True,'html':install.digest(b'old'),'nginx':install.digest(b'old config'),'transport':{'archived':'unchanged'}}
            state.write_text(json.dumps(previous));state.chmod(0o600);checked=[]
            def verify(**kwargs):
                current=json.loads(state.read_text())
                if current['phase']=='RECOVERY_REQUIRED':self.assertEqual(kwargs,{'web_state':previous})
                else:self.assertEqual(kwargs,{})
                checked.append(current['phase'])
            with mock.patch.multiple(install,DATA=data,STATE=state,WEB=web,NGINX=nginx),mock.patch.object(install.transport,'FILES',{}),mock.patch.object(install,'run'),mock.patch.object(install,'check_http_redirect'),mock.patch.object(install,'check_sandbox_https'),mock.patch.object(native,'verify_ready',side_effect=verify):
                install.publish(MAIN,80,b'new',sandbox=('/cert','/key'),transports=True,public_address='179.254.154.126',layout=layout,panel_managed=True)
            self.assertEqual(checked,['READY','RECOVERY_REQUIRED']);self.assertTrue(json.loads(state.read_text())['panel_managed_inbounds'])

if __name__=='__main__':unittest.main()
