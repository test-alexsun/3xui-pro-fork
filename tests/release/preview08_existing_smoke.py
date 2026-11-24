import json,sys,subprocess,copy,os,hashlib,sqlite3,time
from pathlib import Path
os.umask(0o077)
HERE=Path(__file__).resolve()
ROOT=HERE.parents[2]
sys.path[:0]=[str(ROOT/'release'),str(ROOT/'tests/release')]
import preview_panel_inbounds as n
import preview06a_transports as t
data=n.DATA;work=Path('/tmp/preview08-existing')
assert Path('/var/lib/3xui-preview08-lab').read_text().strip()=='PREVIEW-XONIX-08'
web_state=n.private_json(n.WEB_STATE)
assert web_state['public_address']=='10.77.5.1'
domain=web_state['domain']
sub_domain=web_state['layout']['subscription_domain']
work.mkdir(mode=0o700,exist_ok=True)
cert=os.environ.get('PREVIEW08_CA','/var/lib/3xui-preview-acme/config/live/3xui-preview/fullchain.pem')
if len(sys.argv)>1 and sys.argv[1]=='peer':
 configs=json.loads((work/'clients.private.json').read_text())
 from http.server import ThreadingHTTPServer
 import ssl,threading
 with ThreadingHTTPServer(('10.77.5.2',18099),t.Origin) as origin:
  ctx=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);ctx.load_cert_chain(str(work/'echo.pem'),str(work/'echo.key'));origin.socket=ctx.wrap_socket(origin.socket,server_side=True)
  threading.Thread(target=origin.serve_forever,daemon=True).start()
  for tag in (sys.argv[2:] or ['P0','P1','P3']):t.exercise(t.Path('/opt/3xui-pro-fork/panel/bin/xray-linux-amd64'),str(work/'echo.pem'),tag,configs[tag],'10.77.5.2')
  origin.shutdown()
 sys.exit(0)
n.verify_ready();api=n.api_client();rows=api.call('inbounds/list')
configs=n.private_json(data/'preview-xray-clients.json')
for profile,tag in n.TAGS.items():
 row=next(r for r in rows if r['tag']==tag);client=next(c for c in n.object_value(row['settings'])['clients'] if c.get('enable'))
 configs[profile]['outbounds'][0]['settings']['vnext'][0]['users'][0]['id']=client['id']
 if profile=='P1':configs[profile]['outbounds'][0]['streamSettings']['tlsSettings']['certificates']=[{'certificateFile':cert,'usage':'verify'}]
(work/'clients.private.json').write_text(json.dumps(configs))
subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1','-subj','/CN=10.77.5.2','-addext','subjectAltName=IP:10.77.5.2','-keyout',str(work/'echo.key'),'-out',str(work/'echo.pem')],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
selected=['P3'] if '--p3-only' in sys.argv else ['P0','P1','P3']
before=n.core_api('statsquery','-pattern=inbound>>>');p=subprocess.run(['ip','netns','exec','preview-client','python3',str(HERE),'peer',*selected],capture_output=True,timeout=180)
print(p.stdout.decode());(work/'peer.private.stderr').write_bytes(p.stderr)
result={'existing_protocols':'PASS' if not p.returncode else 'FAIL','selected_profiles':selected}
time.sleep(2) # Core counters may flush after the final client closes.
after=n.core_api('statsquery','-pattern=inbound>>>')
b={x['name']:int(x.get('value',0)) for x in before.get('stat',[])};a={x['name']:int(x.get('value',0)) for x in after.get('stat',[])}
result['counters']={profile:{d:a.get('inbound>>>'+tag+'>>>traffic>>>'+d,0)-b.get('inbound>>>'+tag+'>>>traffic>>>'+d,0) for d in ['uplink','downlink']} for profile,tag in n.TAGS.items() if profile in selected}
for profile,counts in result['counters'].items():
 if not all(v>=65536 for v in counts.values()):result['existing_protocols']='FAIL'
for host in [domain,sub_domain]:
 p=subprocess.run(['ip','netns','exec','preview-client','curl','--noproxy','*','--cacert',cert,'-sS','-w','%{http_code}','https://'+host+'/'],capture_output=True)
 expected=(p.stdout.endswith(b'200') and b'XONIX' in p.stdout) if host==domain else p.stdout.endswith(b'404')
 result[host+'_https']='PASS' if p.returncode==0 and expected else 'FAIL'
vless_row=next(r for r in rows if r.get('tag')==n.TAGS['P0'])
subid=next(c for c in n.object_value(vless_row['settings'])['clients'] if c.get('enable') and c.get('subId'))['subId']
result['vless_subscriptions']={}
for fmt in ['sub','json','clash']:
 p=subprocess.run(['ip','netns','exec','preview-client','curl','--noproxy','*','--cacert',cert,'-fsS','https://'+sub_domain+'/'+fmt+'/'+subid],capture_output=True)
 result['vless_subscriptions'][fmt]='PASS' if p.returncode==0 and bool(p.stdout) else 'FAIL'
result['nginx_syntax']='PASS' if subprocess.run(['nginx','-t'],capture_output=True).returncode==0 else 'FAIL'
with sqlite3.connect((data/'x-ui.db').as_uri()+'?mode=ro',uri=True) as db:result['sqlite_integrity']=db.execute('pragma integrity_check').fetchone()[0]
result['systemd']={unit:subprocess.check_output(['systemctl','is-active',unit],text=True).strip() for unit in ['3xui-pro-fork.service','nginx','3xui-preview-renew.timer']}
result['inbound_count']=len(rows);result['native_ready']=n.read_journal()['phase'];result['oom']=subprocess.check_output(['journalctl','-k','--no-pager','-o','cat'],text=True).lower().count('out of memory:')
Path('/tmp/preview08-existing-results.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
raise SystemExit(0 if result['existing_protocols']=='PASS' and all(v=='PASS' for v in result['vless_subscriptions'].values()) and result['sqlite_integrity']=='ok' and result['oom']==0 and all(result[h+'_https']=='PASS' for h in [domain,sub_domain]) else 1)
