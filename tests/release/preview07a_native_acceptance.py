import os
os.umask(0o077)
import copy,hashlib,json,os,sqlite3,subprocess,sys,time,uuid
from pathlib import Path
sys.path.insert(0,'/tmp/preview07a-src/release')
import preview_panel_inbounds as native
assert json.loads(native.WEB_STATE.read_text())['public_address']=='10.77.5.1'
api=native.api_client();fixture_file=Path('/tmp/preview07a-customer.private.json');fixture=json.loads(fixture_file.read_text());work=Path('/tmp/preview07a-e2e');work.mkdir(mode=0o700,exist_ok=True)
progress_file=work/'progress.json';progress=json.loads(progress_file.read_text()) if progress_file.exists() else {}
helper='/tmp/preview07a-src/tests/release/preview07a_clients.py'
def save():progress_file.write_text(json.dumps(progress,indent=2));progress_file.chmod(0o600)
def stage(name,func):
    if name in progress:return
    value=func();progress[name]=value if value is not None else {'status':'PASS'};save();print(name,'PASS',flush=True)
def stats():return {x['name']:int(x.get('value',0)) for x in native.core_api('statsquery','-pattern=inbound>>>').get('stat',[])}
def client(label,fetch=False,negative=False,wrong=False,snapshot='current',fixture_path=None):
    before=stats();out=work/(label+'.json');args=['ip','netns','exec','preview-client','python3',helper,'--fixture',str(fixture_path or fixture_file),'--snapshot',str(work/(snapshot+'.private.json')),'--output',str(out),'--label',label]
    if fetch:args.append('--fetch')
    if negative:args.append('--negative')
    if wrong:args.append('--wrong-uuid')
    p=subprocess.run(args,capture_output=True);(work/(label+'.stdout')).write_bytes(p.stdout+p.stderr)
    if p.returncode:raise RuntimeError('E2E '+label+' failed; inspect private lab log')
    result=json.loads(out.read_text())
    if not negative:
        after=stats();delta={}
        for profile,tag in native.TAGS.items():
            delta[profile]={direction:after.get('inbound>>>'+tag+'>>>traffic>>>'+direction,0)-before.get('inbound>>>'+tag+'>>>traffic>>>'+direction,0) for direction in ['uplink','downlink']}
            assert all(n>=65536 for n in delta[profile].values()),'missing real inbound counter correlation'
        result['server_inbound_counter_delta']=delta;out.write_text(json.dumps(result,indent=2))
    return result
stage('subscription_and_three_profiles',lambda:client('initial',fetch=True))
stage('wrong_uuid_denied',lambda:client('wrong-uuid',negative=True,wrong=True))
def restart():
    subprocess.run(['systemctl','restart','3xui-pro-fork.service'],check=True);native.verify_ready();return client('after-panel-restart')
stage('customer_survives_panel_restart',restart)
def edit():
    (work/'old.private.json').write_bytes((work/'current.private.json').read_bytes())
    fixture['client']['id']=str(uuid.uuid4());api.call('clients/update/'+fixture['client']['email'],fixture['client']);fixture_file.write_text(json.dumps(fixture));native.verify_ready()
    old=client('old-uuid-after-edit',negative=True,snapshot='old');new=client('edited',fetch=True)
    return {'status':'PASS','old_uuid_denied':old,'new_subscription_uuid_works':new}
stage('uuid_edit_applies_without_manual_xray_sync',edit)
def repeat():
    paths=[native.DATA/'preview-xray.json',native.DATA/'preview-xray-clients.json',native.DATA/'awg/server.setconf',native.DATA/'awg/client.conf',native.DATA/'awg/metadata.json',Path('/var/lib/3xui-preview-acme/config/live/3xui-preview/fullchain.pem')]
    before={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths};customer=api.call('clients/get/'+fixture['client']['email'])['client'];ids=native.private_json(native.STATE)['profiles'];pid=native.native_pid()
    args=['sh','/tmp/preview07a-src/install-preview.sh','--public-bind','10.77.5.1','--domain','de126.alexsun55.ru','--subscription-domain','de126-sub.alexsun55.ru','--acme-email','rc-test@example.test','--awg-subnet','10.88.31.0/30','--acme-test-directory','https://10.77.5.2:14000/dir','--acme-test-ca','/tmp/preview06a-ca/ca.pem','--panel-inbounds']
    with (work/'repeat.private.log').open('w') as out:p=subprocess.run(args,stdout=out,stderr=subprocess.STDOUT,env={**os.environ,'TMPDIR':'/var/tmp'})
    assert p.returncode==0,'native repeat failed'
    assert before=={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    current=api.call('clients/get/'+fixture['client']['email'])['client'];assert all(current[k]==customer[k] for k in ['uuid','subId','email','enable'])
    assert ids==native.private_json(native.STATE)['profiles'] and pid==native.native_pid()
    with sqlite3.connect((native.DATA/'x-ui.db').as_uri()+'?mode=ro',uri=True) as db:assert db.execute('pragma integrity_check').fetchone()==('ok',)
    return {'status':'PASS','identities_keys_certificate_preserved':True,'native_process_not_restarted_by_repeat':True,'data':client('after-repeat',fetch=True)}
stage('native_repeat_preserves_edited_customer',repeat)
def expire():
    expired=copy.deepcopy(fixture);expired['client'].update(id=str(uuid.uuid4()),email='preview07a-expired',subId=uuid.uuid4().hex,expiryTime=int(time.time()*1000)-60000)
    api.call('clients/add',{'client':expired['client'],'inboundIds':list(fixture['profiles'].values())});native.verify_ready()
    snapshot=json.loads((work/'current.private.json').read_text())
    for outbound in snapshot['profiles'].values():
        settings=outbound['settings'];server=settings['vnext'][0] if 'vnext' in settings else settings;user=server['users'][0] if 'users' in server else server;user['id']=expired['client']['id']
    (work/'expired.private.json').write_text(json.dumps(snapshot));path=work/'expired-fixture.private.json';path.write_text(json.dumps(expired));result=client('expired',negative=True,snapshot='expired',fixture_path=path)
    api.call('clients/del/'+expired['client']['email'],{});native.verify_ready();return result
stage('expired_customer_denied',expire)
def disable():
    fixture['client']['enable']=False;api.call('clients/update/'+fixture['client']['email'],fixture['client']);fixture_file.write_text(json.dumps(fixture));native.verify_ready();return client('disabled',negative=True)
stage('disabled_customer_denied',disable)
def delete():
    api.call('clients/del/'+fixture['client']['email'],{});native.verify_ready();return client('deleted',negative=True)
stage('deleted_customer_denied',delete)
print('NATIVE_CUSTOMER_API_E2E_COMPLETE',flush=True)
