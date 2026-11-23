"""Full post-install smoke in the disposable 10.77.5.1/Pebble VM only."""
import os
os.umask(0o077)
import hashlib,json,os,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'release'))
import preview_panel_inbounds as n
assert json.loads(n.WEB_STATE.read_text())['public_address']=='10.77.5.1','DISPOSABLE LAB ONLY'
WORK=Path('/tmp/preview07a-smoke');WORK.mkdir(mode=0o700,exist_ok=True)
def run(label,args,env=None):
 with (WORK/(label+'.private.log')).open('w') as log:
  p=subprocess.run(args,stdout=log,stderr=subprocess.STDOUT,env=env)
 assert p.returncode==0,label+' failed; inspect private VM log'
 print(label,'PASS',flush=True)
def peer(*args):return ['ip','netns','exec','preview-client',*args]
n.verify_ready();print('NATIVE_LIVE_LISTENER_CRYPTO_USERS_PASS',flush=True)
import jsonschema
schema=json.loads((ROOT/'release/panel-inbounds-state.schema.json').read_text())
jsonschema.Draft202012Validator.check_schema(schema)
jsonschema.validate(n.read_journal(),schema,format_checker=jsonschema.FormatChecker())
print('ACTUAL_JOURNAL_JSON_SCHEMA_PASS',flush=True)
run('NGINX_SYNTAX',['nginx','-t'])
run('NATIVE_XRAY_CONFIG',[str(n.transport.XRAY),'run','-test','-config',str(n.CORE)])
source=json.loads(n.transport.CLIENTS.read_text());snapshot=WORK/'starters.private.json';snapshot.write_text(json.dumps({'profiles':{p:source[p]['outbounds'][0] for p in n.TAGS}}));snapshot.chmod(0o600)
fixture=WORK/'fixture.private.json';fixture.write_text('{}');fixture.chmod(0o600)
stats=lambda:{x['name']:int(x.get('value',0)) for x in n.core_api('statsquery','-pattern=inbound>>>').get('stat',[])}
before=stats()
run('ORIGINAL_STARTER_IDENTITIES_64K',peer('python3',str(ROOT/'tests/release/preview07a_clients.py'),'--fixture',str(fixture),'--snapshot',str(snapshot),'--output',str(WORK/'starter-results.json'),'--label','original-starters'))
after=stats();delta={p:{d:after.get('inbound>>>'+tag+'>>>traffic>>>'+d,0)-before.get('inbound>>>'+tag+'>>>traffic>>>'+d,0) for d in ['uplink','downlink']} for p,tag in n.TAGS.items()}
assert all(min(x.values())>=65536 for x in delta.values());print('STARTER_SERVER_COUNTERS',json.dumps(delta),flush=True)
# Existing authenticated cookies/CSRF/WebSocket, subscription formats and isolation gates.
web=ROOT/'tests/release/preview07_web.py';run('PANEL_EXPOSURE_FIXTURE',['python3',str(web),'setup'])
challenge=Path('/var/www/3xui-pro-fork/decoy/.well-known/acme-challenge/fixture');challenge.parent.mkdir(parents=True,exist_ok=True);challenge.write_text('synthetic-challenge\n');challenge.chmod(0o644)
run('HTTPS_PANEL_API_SUBSCRIPTIONS_ISOLATION',peer('python3',str(web),'verify'))
run('PANEL_LOG_SECRET_REDACTION',['python3',str(web),'logs'])
# AWG peer uses the existing installed client identity; only lab client lifecycle changes.
awg=Path('/opt/3xui-pro-fork/awg');keypaths=[n.DATA/'awg'/x for x in ['client.conf','server.setconf','metadata.json']]
original={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in keypaths}
setconf=WORK/'awg-client.private.setconf';setconf.write_text('\n'.join(x for x in keypaths[0].read_text().splitlines() if not x.startswith('Address = '))+'\n');setconf.chmod(0o600)
def start():
 log=(WORK/'awg-client.private.log').open('w');process=subprocess.Popen(peer(str(awg/'amneziawg-go'),'-f','awg07asmoke'),stdout=log,stderr=log);log.close()
 for _ in range(100):
  assert process.poll() is None
  if Path('/var/run/amneziawg/awg07asmoke.sock').exists():break
  time.sleep(.05)
 else:raise RuntimeError('lab AWG startup timeout')
 run('AWG_CLIENT_SETCONF',peer(str(awg/'awg'),'setconf','awg07asmoke',str(setconf)))
 subprocess.run(['ip','-n','preview-client','addr','add','10.88.31.2/30','dev','awg07asmoke'],check=True)
 subprocess.run(['ip','-n','preview-client','link','set','awg07asmoke','mtu','1420','up'],check=True)
 return process
def stop(process):
 process.terminate();process.wait(timeout=10)
 for _ in range(100):
  if not Path('/var/run/amneziawg/awg07asmoke.sock').exists():return
  time.sleep(.05)
 raise RuntimeError('lab AWG interface not released')
def matrix(label):
 probe=ROOT/'tests/release/awg_pmtu_probe.py'
 server=subprocess.Popen(['python3',str(probe),'server','--bind','10.88.31.1','--client','10.88.31.2','--interfaces','preview-host','xproawg0','--peer','10.77.5.2','--duration','90'],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
 assert server.stdout.readline().strip()==b'PMTU_SERVER_READY'
 run(label,peer('python3',str(probe),'client','--bind','10.88.31.1','--client','10.88.31.2','--interfaces','preview-peer','awg07asmoke','--peer','10.77.5.1','--trials','3','--output',str(WORK/(label+'.json'))))
 out,err=server.communicate(timeout=95);assert server.returncode==0
 data=json.loads((WORK/(label+'.json')).read_text());assert len(data['results'])==66 and all(x['received']==1 for x in data['results'])
 handshake=subprocess.check_output([str(awg/'awg'),'show','xproawg0','latest-handshakes'],text=True);assert any(int(x.split()[1])>0 for x in handshake.splitlines())
 print(label,'ALL_11_SIZES_BOTH_DIRECTIONS_HANDSHAKE_PASS',flush=True)
client=start()
try:matrix('AWG_NATIVE_INTEGRATION_BEFORE_RESTART')
finally:stop(client)
subprocess.run(['systemctl','restart','3xui-pro-fork-awg.service'],check=True);client=start()
try:matrix('AWG_NATIVE_INTEGRATION_AFTER_RESTART')
finally:stop(client)
assert original=={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in keypaths};print('AWG_KEYS_AND_CONFIG_UNCHANGED_PASS',flush=True)
lineage=Path('/var/lib/3xui-preview-acme/config/live/3xui-preview');old=hashlib.sha256((lineage/'fullchain.pem').read_bytes()).hexdigest();master=subprocess.check_output(['pgrep','-xo','nginx']).strip();workers=lambda:subprocess.check_output(['pgrep','-P',master],text=True).split()
prior=workers()
run('PRIVATE_ACME_RENEWAL',['certbot','renew','--force-renewal','--non-interactive','--no-random-sleep-on-renew','--cert-name','3xui-preview','--no-directory-hooks','--config-dir','/var/lib/3xui-preview-acme/config','--work-dir','/var/lib/3xui-preview-acme/work','--logs-dir','/var/lib/3xui-preview-acme/logs','--deploy-hook','/var/lib/3xui-preview-acme/renew-deploy'],env={**os.environ,'REQUESTS_CA_BUNDLE':'/tmp/preview06a-ca/ca.pem'})
assert old!=hashlib.sha256((lineage/'fullchain.pem').read_bytes()).hexdigest()
for _ in range(30):
 if workers()!=prior:break
 time.sleep(.2)
else:raise AssertionError('renewal did not reload nginx')
run('XONIX_HTTPS_AFTER_RENEWAL',peer('curl','-fsS','--cacert','/tmp/preview06a-ca/root.pem','https://de126.alexsun55.ru/','-o',str(WORK/'xonix.html')))
assert (WORK/'xonix.html').read_bytes()==(ROOT/'assets/decoy/xonix/index.html').read_bytes()
n.verify_ready();run('NGINX_AFTER_RENEWAL',['nginx','-t'])
print('PRIVATE_ACME_EXACT_TWO_SAN_RENEWAL_RELOAD_PASS',flush=True)
print('RESOURCE_MEMINFO',json.dumps({x.split(':')[0]:x.split(':')[1].strip() for x in Path('/proc/meminfo').read_text().splitlines() if x.split(':')[0] in ['MemTotal','MemAvailable','SwapTotal']}),flush=True)
oom=subprocess.check_output(['journalctl','-k','--no-pager','-o','cat'],text=True);assert not any(x in oom.lower() for x in ['out of memory:','killed process']);print('NO_KERNEL_OOM_PASS',flush=True)
print('PREVIEW07A_NATIVE_FULL_SMOKE_PASS',flush=True)
