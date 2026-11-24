"""Independent namespace E2E of native subscription profiles; never prints identities."""
import os
os.umask(0o077)
import argparse,copy,http.client,json,re,secrets,socket,ssl,subprocess,tempfile,threading,time,urllib.request,uuid
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path

MAIN='de126.alexsun55.ru';SUB='de126-sub.alexsun55.ru'
PORTS={8443:'P0',443:'P1',9443:'P3'}
def dial(outbound):
    settings=outbound['settings'];server=settings['vnext'][0] if 'vnext' in settings else settings
    user=server['users'][0] if 'users' in server else server
    return server,user

def fetch(fixture,ca):
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=ca)))
    try:
        with opener.open('https://'+SUB+'/json/'+fixture['client']['subId'],timeout=20) as response:data=json.load(response)
    except Exception:raise RuntimeError('native subscription fetch failed; details withheld') from None
    profiles={}
    for config in data if isinstance(data,list) else [data]:
        for outbound in config.get('outbounds',[]):
            if outbound.get('protocol')!='vless':continue
            server,user=dial(outbound);profile=PORTS.get(server['port'])
            if not profile:continue
            assert server['address']==MAIN and user['id']==fixture['client']['id'],'subscription endpoint/identity differs'
            stream=outbound['streamSettings'];assert stream['network']==('tcp' if profile=='P3' else 'xhttp')
            assert stream['security']==('tls' if profile=='P1' else 'reality')
            assert user.get('flow','')==('xtls-rprx-vision' if profile=='P3' else '')
            if profile=='P1':assert stream['tlsSettings']['alpn']==['h2'] and not stream['tlsSettings'].get('allowInsecure')
            else:assert not stream['realitySettings'].get('allowInsecure')
            if profile!='P3':assert stream['xhttpSettings']['mode']=='stream-up' and stream['xhttpSettings']['path']==fixture.get('xhttp_paths',{}).get(profile,'/xhttp/')
            profiles[profile]=outbound
    if set(profiles)!=set(fixture['profiles']):raise RuntimeError('subscription is missing real profiles')
    return {'uuid':fixture['client']['id'],'profiles':profiles}

class Origin(BaseHTTPRequestHandler):
    def do_POST(self):
        body=self.rfile.read(int(self.headers['Content-Length']));self.send_response(200);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body[::-1])
    def log_message(self,*a):pass

def exercise(args,profile,outbound,allowed):
    outbound=copy.deepcopy(outbound);stream=outbound['streamSettings']
    if profile=='P1':stream['tlsSettings']['certificates']=[{'certificateFile':args.ca,'usage':'verify'}]
    proxy=19600+['P0','P1','P3'].index(profile)
    config={'log':{'loglevel':'debug'},'inbounds':[{'listen':'127.0.0.1','port':proxy,'protocol':'http','settings':{}}],'outbounds':[outbound]}
    with tempfile.TemporaryDirectory() as tmp:
        path=Path(tmp)/'client.json';path.write_text(json.dumps(config));path.chmod(0o600)
        subprocess.run([args.binary,'run','-test','-config',str(path)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=15)
        logfile=Path(args.output).parent/('client-'+args.label+'-'+profile+'.private.log')
        with logfile.open('w') as log:
            process=subprocess.Popen([args.binary,'run','-config',str(path)],stdout=log,stderr=log)
            try:
                until=time.monotonic()+10
                while True:
                    assert process.poll() is None,'client exited during startup'
                    try:
                        with socket.create_connection(('127.0.0.1',proxy),timeout=.2):break
                    except OSError:
                        if time.monotonic()>until:raise RuntimeError('client startup timeout')
                        time.sleep(.05)
                success=False
                connection=http.client.HTTPSConnection('127.0.0.1',proxy,context=ssl.create_default_context(cafile=args.cert),timeout=20 if allowed else 3)
                connection.set_tunnel('10.77.5.2',18099)
                try:
                    payload=secrets.token_bytes(65536);connection.request('POST','/verified',body=payload);response=connection.getresponse();success=response.status==200 and response.read()==payload[::-1]
                except (OSError,http.client.HTTPException):success=False
                finally:connection.close()
                if success!=allowed:raise RuntimeError('unexpected '+profile+' authorization result')
            finally:
                process.terminate();process.wait(timeout=8)
        text=logfile.read_text()
        if allowed and profile in ['P0','P1']:assert re.search(r'HTTP\s+version\s+2\b',text,re.I),'H2 not observed'
        if allowed:assert '[Error]' not in text,'client errors on successful transfer'
    result={'profile':profile,'expected_allowed':allowed,'actual_allowed':success,'uploaded_payload_bytes':65536 if success else 0,'downloaded_verified_payload_bytes':65536 if success else 0,'h2':bool(success and profile in ['P0','P1'])}
    print(json.dumps(result),flush=True);return result

def main():
    p=argparse.ArgumentParser();p.add_argument('--fixture',required=True);p.add_argument('--snapshot',required=True);p.add_argument('--fetch-only',action='store_true');p.add_argument('--fetch',action='store_true');p.add_argument('--negative',action='store_true');p.add_argument('--wrong-uuid',action='store_true');p.add_argument('--output',required=True);p.add_argument('--label',default='check');p.add_argument('--profiles',nargs='+',choices=['P0','P1','P3']);p.add_argument('--binary',default='/opt/3xui-pro-fork/panel/bin/xray-linux-amd64');p.add_argument('--ca',default='/tmp/preview06a-ca/root.pem');p.add_argument('--cert',default='/tmp/preview06a-ca/pebble-cert.pem');p.add_argument('--key',default='/tmp/preview06a-ca/pebble-key.pem');args=p.parse_args()
    fixture=json.loads(Path(args.fixture).read_text())
    if args.fetch or args.fetch_only:
        snapshot=fetch(fixture,args.ca);Path(args.snapshot).write_text(json.dumps(snapshot));Path(args.snapshot).chmod(0o600)
    else:snapshot=json.loads(Path(args.snapshot).read_text())
    if args.fetch_only:print('NATIVE_SUBSCRIPTION_THREE_PROFILES_VALID');return
    if args.wrong_uuid:
        for outbound in snapshot['profiles'].values():dial(outbound)[1]['id']=str(uuid.uuid4())
    selected=args.profiles or [p for p in ['P0','P1','P3'] if p in snapshot['profiles']]
    assert selected and set(selected)<=set(snapshot['profiles']),'requested profile missing from snapshot'
    with ThreadingHTTPServer(('10.77.5.2',18099),Origin) as origin:
        ctx=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);ctx.load_cert_chain(args.cert,args.key);origin.socket=ctx.wrap_socket(origin.socket,server_side=True)
        thread=threading.Thread(target=origin.serve_forever,daemon=True);thread.start()
        try:results=[exercise(args,profile,snapshot['profiles'][profile],not args.negative) for profile in selected]
        finally:origin.shutdown();thread.join(timeout=5)
    Path(args.output).write_text(json.dumps({'status':'PASS','label':args.label,'results':results},indent=2))
if __name__=='__main__':main()
