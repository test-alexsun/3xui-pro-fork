import os
os.umask(0o077)
import json,subprocess,sys
from pathlib import Path
sys.path.insert(0,'/tmp/preview07a-src/release')
import preview_panel_inbounds as native
assert json.loads(native.WEB_STATE.read_text())['public_address']=='10.77.5.1'
native.verify_ready();api=native.api_client();obj=api.call('clients/get/preview07a-ui');record=obj['client'];registry=native.read_journal()['profiles']
assert set(obj['inboundIds'])==set(registry.values())
assert record['flow']=='xtls-rprx-vision','UI-created client lacks Vision flow'
fixture=Path('/tmp/preview07a-ui-fixture.private.json');fixture.write_text(json.dumps({'client':{'id':record['uuid'],'email':record['email'],'subId':record['subId']},'profiles':registry}));fixture.chmod(0o600)
out=Path('/tmp/preview07a-ui-data.json');helper='/tmp/preview07a-src/tests/release/preview07a_clients.py'
stats=lambda:{x['name']:int(x.get('value',0)) for x in native.core_api('statsquery','-pattern=inbound>>>').get('stat',[])}
before=stats();p=subprocess.run(['ip','netns','exec','preview-client','python3',helper,'--fixture',str(fixture),'--snapshot','/tmp/preview07a-ui-sub.private.json','--fetch','--output',str(out),'--label','ui-created'],capture_output=True)
Path('/tmp/preview07a-ui-data.private.log').write_bytes(p.stdout+p.stderr);assert p.returncode==0,'UI-created actual subscription E2E failed'
after=stats();result=json.loads(out.read_text());result['server_counter_delta']={}
for profile,tag in native.TAGS.items():
    delta={d:after.get('inbound>>>'+tag+'>>>traffic>>>'+d,0)-before.get('inbound>>>'+tag+'>>>traffic>>>'+d,0) for d in ['uplink','downlink']}
    assert min(delta.values())>=65536;result['server_counter_delta'][profile]=delta
print(json.dumps({'ui_created_customer':'PASS','profiles':result}))
api.call('clients/del/preview07a-ui',{});native.verify_ready();print('UI_OWNED_CLIENT_CLEANUP_PASS')
