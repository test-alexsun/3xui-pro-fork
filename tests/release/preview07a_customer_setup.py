import os
os.umask(0o077)
import json,sys,uuid
from pathlib import Path
sys.path.insert(0,'/tmp/preview07a-src/release')
import preview_panel_inbounds as native
from preview_panel_api import PanelAPI
assert json.loads(native.WEB_STATE.read_text())['public_address']=='10.77.5.1'
api=native.api_client();journal=native.private_json(native.STATE);file=Path('/tmp/preview07a-customer.private.json');assert not file.exists()
client={'id':str(uuid.uuid4()),'email':'preview07a-shared','subId':uuid.uuid4().hex,'enable':True,'expiryTime':0,'totalGB':0,'flow':'xtls-rprx-vision'}
api.call('clients/add',{'client':client,'inboundIds':list(journal['profiles'].values())})
file.write_text(json.dumps({'client':client,'profiles':journal['profiles']}));file.chmod(0o600)
native.verify_ready()
print('NATIVE_SHARED_CUSTOMER_CREATED_AND_LIVE_ON_THREE_PROFILES')
