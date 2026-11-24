"""Destructive failure exercise guarded to this disposable VM only."""
import os
os.umask(0o077)
import copy,hashlib,json,os,socket,subprocess,sys,time,uuid
from pathlib import Path
sys.path.insert(0,'/tmp/preview07a-src/release')
import preview_panel_inbounds as n
import preview_install as install
assert json.loads(n.WEB_STATE.read_text())['public_address']=='10.77.5.1','DISPOSABLE LAB ONLY'
api=n.api_client();journal=n.read_journal();assert journal['phase']=='READY'
assert len(api.call('inbounds/list'))==3
assert len(api.call('clients/list'))==len(journal['clients'])
for profile,identity in journal['profiles'].items():
 item=api.call('inbounds/get/'+str(identity));assert item['tag']==n.TAGS[profile]
 api.call('inbounds/setEnable/'+str(identity),{'enable':False})
for email,person in journal['clients'].items():
 item=api.call('clients/get/'+email)['client'];assert item['uuid']==person['client']['id'] and item['subId']==person['client']['subId']
 api.call('clients/del/'+email,{})
for identity in journal['profiles'].values():api.call('inbounds/del/'+str(identity),{})
subprocess.run(['systemctl','restart',n.PANEL_UNIT],check=True)
for _ in range(100):
 try:
  assert api.call('inbounds/list')==[];n.core_api('lsi','-isOnlyTags=true')
  assert not any(n.listener_pids(p) for p in [8443,19441,9443]);break
 except (RuntimeError,AssertionError):time.sleep(.2)
else:raise RuntimeError('lab baseline reset failed')
install.atomic(n.WEB_STATE,(Path(journal['backup'])/'web-state.json').read_bytes(),0o600)
n.STATE.rename(n.DATA/'lab07a-successful-native-journal.private.json')
subprocess.run(['systemctl','enable','--now',n.transport.UNIT.name],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
print('LAB_LEGACY_BASELINE_RESTORED',flush=True)
manifest={'panel':'3.11.0','xray':'26.11.9','awg_runtime':'3.1.20260828','awg_tools':'3.1.20260812','files':n.ownership.PINNED_FILES}
web,source,clients=n.source_snapshot();blueprint,_=n.blueprints(source,clients,web['domain'])
foreign=copy.deepcopy(blueprint['P1']);foreign.update(tag='lab07a-foreign-owned-by-test',remark='lab07a-foreign-owned-by-test',port=19007,enable=True)
foreign['streamSettings']={'network':'tcp','security':'none'};foreign_id=api.call('inbounds/add',foreign)['id']
foreign_client={'id':str(uuid.uuid4()),'email':'lab07a-foreign','subId':uuid.uuid4().hex,'enable':True,'flow':'','expiryTime':0,'totalGB':0}
api.call('clients/add',{'client':foreign_client,'inboundIds':[foreign_id]})
def preserved():
 obj=api.call('clients/get/'+foreign_client['email']);assert obj['client']['uuid']==foreign_client['id'] and obj['client']['subId']==foreign_client['subId'] and obj['inboundIds']==[foreign_id]
 assert api.call('inbounds/get/'+str(foreign_id))['tag']==foreign['tag']
paths=[n.WEB_STATE,*[x[0] for x in n.transport.FILES.values()],n.DATA/'awg/server.setconf',n.DATA/'awg/client.conf',n.DATA/'awg/metadata.json',Path('/var/lib/3xui-preview-acme/config/live/3xui-preview/fullchain.pem')]
before={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
template_before=n.object_value(api.call('xray/',{}))
old_pid=n.ownership.service_properties(n.transport.UNIT.name)['MainPID'];conflict=copy.deepcopy(blueprint['P0']);conflict['tag']='lab07a-port-conflict';conflict_id=api.call('inbounds/add',conflict)['id']
try:n.migrate(manifest,install.atomic)
except RuntimeError as e:assert 'conflicts' in str(e)
else:raise AssertionError('port conflict adopted')
assert not n.STATE.exists() and n.ownership.service_properties(n.transport.UNIT.name)['MainPID']==old_pid
api.call('inbounds/del/'+str(conflict_id),{});preserved();print('PORT_CONFLICT_PRE_MUTATION_REFUSAL_PASS',flush=True)
original=n.blueprints
def invalid(*args):
 b,p=original(*args);b['P0']['streamSettings']['realitySettings']['privateKey']='invalid-key';return b,p
n.blueprints=invalid
try:n.migrate(manifest,install.atomic,test_origin='10.77.5.2')
except RuntimeError as error:print('EXPECTED_MIGRATION_FAILURE',str(error),flush=True)
else:raise AssertionError('invalid Xray settings accepted')
finally:n.blueprints=original
state=n.read_journal();print('FAULT_FINAL_PHASE',state['phase'],flush=True);print('FAULT_HISTORY',[x['phase'] for x in state['history']],flush=True)
assert state['phase']=='ROLLED_BACK','scoped rollback did not complete'
assert template_before==n.object_value(api.call('xray/',{})),'lab template not restored'
assert before=={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
assert {i['id'] for i in api.call('inbounds/list')}=={foreign_id};preserved()
assert n.ownership.service_properties(n.transport.UNIT.name)['ActiveState']=='active'
with __import__('sqlite3').connect((n.DATA/'x-ui.db').as_uri()+'?mode=ro',uri=True) as db:assert db.execute('pragma integrity_check').fetchone()==('ok',)
print('REAL_XRAY_APPLY_FAILURE_SCOPED_ROLLBACK_PASS',flush=True)
args=['ip','netns','exec','preview-client','python3','/mnt/seed/transport.py',str(n.transport.XRAY),str(n.transport.CLIENTS),'/tmp/preview06a-ca/pebble-cert.pem','/tmp/preview06a-ca/pebble-key.pem','--p1-ca','/tmp/preview06a-ca/root.pem']
p=subprocess.run(args,capture_output=True);Path('/tmp/preview07a-rollback-data.private.log').write_bytes(p.stdout+p.stderr);assert p.returncode==0,'restored original starter E2E failed'
print('RESTORED_STANDALONE_ORIGINAL_STARTERS_64K_PASS',flush=True)
