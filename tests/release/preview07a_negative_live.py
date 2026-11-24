import os
os.umask(0o077)
import json,subprocess,sys
from pathlib import Path
sys.path.insert(0,'/tmp/preview07a-src/release')
import preview_panel_inbounds as native
assert json.loads(native.WEB_STATE.read_text())['public_address']=='10.77.5.1'
native.verify_ready();api=native.api_client();registry=native.read_journal()['profiles'];web,source,clients=native.source_snapshot();blueprint,_=native.blueprints(source,clients,web['domain'])
config=native.private_json(native.CORE);port=next(i['port'] for i in config['inbounds'] if i['tag']=='api');endpoint='-server=127.0.0.1:'+str(port)
results={}
for case in ['missing_runtime_inbound','db_live_user_inconsistency']:
 if case=='missing_runtime_inbound':args=['rmi',endpoint,native.TAGS['P0']]
 else:
  inbound=api.call('inbounds/get/'+str(registry['P0']));email=native.object_value(inbound['settings'])['clients'][0]['email'];args=['rmu',endpoint,'-tag='+native.TAGS['P0'],email]
 subprocess.run([str(native.transport.XRAY),'api',*args],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 try:native.validate_live(api,registry,blueprint)
 except RuntimeError as error:results[case]={'status':'PASS','detected':str(error)}
 else:raise AssertionError('live inconsistency accepted')
 subprocess.run(['systemctl','restart',native.PANEL_UNIT],check=True);native.verify_ready()
print(json.dumps(results));print('LIVE_NEGATIVE_GUARDS_PASS')
