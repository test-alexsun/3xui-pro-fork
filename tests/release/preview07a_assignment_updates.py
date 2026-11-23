"""Real native attach/detach and XHTTP path update in the disposable VM only."""
import os
os.umask(0o077)
import copy,json,subprocess,sys,time,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'release'))
import preview_panel_inbounds as n
assert json.loads(n.WEB_STATE.read_text())['public_address']=='10.77.5.1','DISPOSABLE LAB ONLY'
n.verify_ready();api=n.api_client();ids=n.read_journal()['profiles'];work=Path('/tmp/preview07a-assign');work.mkdir(mode=0o700,exist_ok=True)
fixture={'client':{'id':str(uuid.uuid4()),'email':'preview07a-assign','subId':uuid.uuid4().hex,'flow':'xtls-rprx-vision','enable':True,'expiryTime':0,'totalGB':0},'profiles':{'P0':ids['P0']}}
assert not any(x.get('client',x).get('email')==fixture['client']['email'] for x in api.call('clients/list'))
api.call('clients/add',{'client':fixture['client'],'inboundIds':[ids['P0']]})
original=api.call('inbounds/get/'+str(ids['P0']));changed=False;results={}
def test(label,fetch=True,negative=False,profiles=None,snapshot='current'):
 f=work/'fixture.private.json';f.write_text(json.dumps(fixture));f.chmod(0o600)
 args=['ip','netns','exec','preview-client','python3',str(ROOT/'tests/release/preview07a_clients.py'),'--fixture',str(f),'--snapshot',str(work/(snapshot+'.private.json')),'--output',str(work/(label+'.json')),'--label',label]
 if fetch:args.append('--fetch')
 if negative:args.append('--negative')
 if profiles:args+=['--profiles',*profiles]
 p=subprocess.run(args,capture_output=True);(work/(label+'.private.log')).write_bytes(p.stdout+p.stderr);assert p.returncode==0,label+' failed'
 results[label]=json.loads((work/(label+'.json')).read_text());print(label,'PASS',flush=True)
try:
 n.verify_ready();test('assigned_one_profile')
 api.call('clients/'+fixture['client']['email']+'/attach',{'inboundIds':[ids['P1'],ids['P3']]});fixture['profiles']=ids
 # Match the normal UI: select Vision after attaching a flow-capable inbound.
 api.call('clients/update/'+fixture['client']['email'],fixture['client']);n.verify_ready();test('assigned_three_profiles_with_selected_vision')
 (work/'three.private.json').write_bytes((work/'current.private.json').read_bytes())
 api.call('clients/'+fixture['client']['email']+'/detach',{'inboundIds':[ids['P3']]});fixture['profiles']={p:ids[p] for p in ['P0','P1']};n.verify_ready();test('detached_subscription_has_two_profiles');test('detached_p3_fresh_access_denied',fetch=False,negative=True,profiles=['P3'],snapshot='three')
 api.call('clients/'+fixture['client']['email']+'/attach',{'inboundIds':[ids['P3']]});fixture['profiles']=ids
 api.call('clients/update/'+fixture['client']['email'],fixture['client']);n.verify_ready();test('reattached_vision_works')
 update=copy.deepcopy(original);stream=n.object_value(update['streamSettings']);stream['xhttpSettings']['path']='/xhttp-07a-update/';update['streamSettings']=stream
 api.call('inbounds/update/'+str(ids['P0']),update);changed=True
 for _ in range(90):
  handler=next(x for x in n.core_api('lsi','-isOnlyTags=false')['inbounds'] if x['tag']==n.TAGS['P0'])
  settings=handler['receiverSettings']['streamSettings']['transportSettings']
  if any(x.get('settings',{}).get('path')=='/xhttp-07a-update/' for x in settings):break
  time.sleep(.2)
 else:raise RuntimeError('native inbound update not applied')
 fixture['xhttp_path']='/xhttp-07a-update/'
 # P1 retains its original path; only the P0 transport is updated by the real API.
 fixture['xhttp_paths']={'P0':'/xhttp-07a-update/','P1':'/xhttp/'}
 test('inbound_xhttp_update_applied',profiles=['P0'])
 test('old_xhttp_path_access_denied',fetch=False,negative=True,profiles=['P0'],snapshot='three')
 api.call('inbounds/update/'+str(ids['P0']),original);changed=False;fixture.pop('xhttp_path');fixture.pop('xhttp_paths');n.verify_ready();test('inbound_xhttp_original_restored')
finally:
 if changed:api.call('inbounds/update/'+str(ids['P0']),original)
 api.call('clients/del/'+fixture['client']['email'],{});n.verify_ready()
(work/'results.json').write_text(json.dumps(results,indent=2));print('ASSIGNMENT_AND_REAL_INBOUND_UPDATES_PASS',flush=True)
