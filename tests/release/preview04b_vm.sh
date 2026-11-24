#!/bin/bash
set -Eeuo pipefail
umask 077
trap 'echo "PREVIEW04B_VM_FAIL line=$LINENO"; systemctl poweroff' ERR
modprobe tun
mkdir -p /etc/3xui-preview-test /tmp/pkg /tmp/preview
chmod 700 /etc/3xui-preview-test
cert=/etc/3xui-preview-test/cert.pem
key=/etc/3xui-preview-test/key.pem
command -v openssl >/dev/null || { apt-get update; DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends openssl; }
openssl req -x509 -newkey rsa:2048 -nodes -days 1 -subj /CN=example.test \
    -addext 'subjectAltName=DNS:example.test,DNS:panel.example.test,DNS:p0.example.test,DNS:p3.example.test,IP:127.0.0.1' \
    -keyout "$key" -out "$cert" >/dev/null 2>&1
chmod 600 "$key"
tar -xzf /mnt/seed/candidate.tar.gz -C /tmp/pkg
tar -xzf /mnt/seed/preview.tar.gz -C /tmp/preview
cd /tmp/preview
args=(--domain example.test --test-mode --sandbox-tls-cert "$cert" --sandbox-tls-key "$key" --sandbox-transports
      --components /tmp/pkg --awg-subnet 10.88.31.0/30)
python3 - "${args[@]}" <<'PY'
from pathlib import Path
import socket, subprocess, sys
with socket.socket() as foreign:
    foreign.bind(('127.0.0.1',443))
    foreign.listen()
    result=subprocess.run(['bash','install-preview.sh',*sys.argv[1:]],capture_output=True,text=True,timeout=90)
    assert result.returncode == 1 and 'transport TCP 443 already has a listener' in result.stderr, result.stderr
    assert not Path('/var/lib/3xui-pro-fork').exists()
print('PREVIEW04B_FOREIGN_TCP_443_REFUSAL_PASS')
PY
udp443=$(ss -H -lun 'sport = :443')
bash install-preview.sh "${args[@]}"
nginx -t
XRAY=/opt/3xui-pro-fork/panel/bin/xray-linux-amd64
DATA=/var/lib/3xui-pro-fork
CLIENTS=$DATA/preview-xray-clients.json
"$XRAY" run -test -config "$DATA/preview-xray.json"
for port in 443 18443 19440 19441 19443 19444; do
    ss -H -ltn "sport = :$port" | grep -F "127.0.0.1:$port"
done
test "$(ss -H -lun 'sport = :443')" = "$udp443"
ss -H -lun 'sport = :29177' | grep -F ':29177'
echo PREVIEW04B_LISTENERS_PASS
python3 tests/release/preview04b_transports.py "$XRAY" "$CLIENTS" "$cert" "$key"
systemctl restart 3xui-preview-xray.service
for attempt in $(seq 1 30); do
    if ss -H -ltn 'sport = :19441' | grep -q 19441; then break; fi
    sleep .2
done
python3 tests/release/preview04b_transports.py "$XRAY" "$CLIENTS" "$cert" "$key"
echo PREVIEW04B_XRAY_RECONNECT_PASS
python3 - <<'PY'
import http.cookiejar,json,re,secrets,socket,subprocess,time,urllib.parse,urllib.request,uuid
logs=subprocess.check_output(['journalctl','-u','3xui-pro-fork.service','-o','cat'],text=True)
match=re.search(r'Username: (\S+)\s+Password: (\S+)',logs); assert match, 'fixture credentials unavailable'
username,password=match.groups()
def session():
 opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),urllib.request.ProxyHandler({}))
 def call(path,payload=None,csrf=None,form=False):
  headers={}; data=None
  if payload is not None:
   data=urllib.parse.urlencode(payload).encode() if form else json.dumps(payload).encode()
   headers['Content-Type']='application/x-www-form-urlencoded' if form else 'application/json'
   if csrf: headers['X-CSRF-Token']=csrf
  with opener.open(urllib.request.Request('http://127.0.0.1:2053'+path,data=data,headers=headers),timeout=15) as r: result=json.load(r)
  if not result.get('success'): raise RuntimeError('panel API failure at '+path+': '+str(result.get('msg',''))[:200])
  return result.get('obj')
 token=call('/csrf-token');call('/login',{'username':username,'password':password},token,True)
 return call,call('/csrf-token')
call,token=session()
settings=call('/panel/api/setting/all',{},token)
settings.update(subEnable=True,subListen='127.0.0.1',subPort=12996,subPath='/preview04a-sub/',subJsonEnable=False,subClashEnable=False,subCertFile='',subKeyFile='',subDomain='',subURI='https://example.test/preview04a-sub/',subJsonURI='',subClashURI='')
call('/panel/api/setting/update',settings,token)
subprocess.run(['systemctl','restart','3xui-pro-fork.service'],check=True)
for _ in range(60):
 try:
  with socket.create_connection(('127.0.0.1',12996),timeout=1): break
 except OSError: time.sleep(1)
else: raise RuntimeError('fixture subscription listener unavailable')
call,token=session()
inbound={'up':0,'down':0,'total':0,'remark':'fixture-04a','enable':True,'expiryTime':0,
 'listen':'127.0.0.1','port':20086,'protocol':'vless',
 'settings':json.dumps({'clients':[],'decryption':'none'}),
 'streamSettings':json.dumps({'network':'tcp','security':'none'}),
 'sniffing':json.dumps({'enabled':False,'destOverride':[]})}
obj=call('/panel/api/inbounds/add',inbound,token)
assert isinstance(obj,dict) and obj.get('id'), 'fixture inbound not created'
subid=secrets.token_urlsafe(24); identity=str(uuid.uuid4())
client={'client':{'id':identity,'email':'synthetic-04a@example.test','enable':True,'subId':subid},'inboundIds':[obj['id']]}
call('/panel/api/clients/add',client,token)
current=call('/panel/api/setting/all',{},token)
base=current.get('subURI')
assert base=='https://example.test/preview04a-sub/', 'panel subscription base differs'
with open('/run/preview04a-fixture.json','w') as f: json.dump({'subid':subid,'uuid':identity,'base':base,'username':username,'password':password},f)
import ssl
original=socket.getaddrinfo
socket.getaddrinfo=lambda host,port,*a,**k: original('127.0.0.1' if host=='panel.example.test' else host,port,*a,**k)
secure=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),urllib.request.ProxyHandler({}),urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile='/etc/3xui-preview-test/cert.pem')))
def secure_call(path,payload=None,csrf=None):
 headers={}; data=None
 if payload is not None:
  data=urllib.parse.urlencode(payload).encode(); headers['Content-Type']='application/x-www-form-urlencoded'
  if csrf: headers['X-CSRF-Token']=csrf
 with secure.open(urllib.request.Request('https://panel.example.test'+path,data=data,headers=headers),timeout=15) as r: result=json.load(r)
 assert result.get('success'),path
 return result.get('obj')
csrf=secure_call('/csrf-token');secure_call('/login',{'username':username,'password':password},csrf);secure_call('/panel/api/inbounds/list')
print('PREVIEW04B_PANEL_HTTPS_API_PASS')
print('PREVIEW04B_TEST_CLIENT_CREATED')
PY
bash install-preview.sh "${args[@]}" --sandbox-subscriptions
python3 - <<'PY'
import http.cookiejar,json,socket,ssl,urllib.parse,urllib.request
fixture=json.load(open('/run/preview04a-fixture.json'))
old=socket.getaddrinfo
socket.getaddrinfo=lambda host,port,*a,**k: old('127.0.0.1' if host=='panel.example.test' else host,port,*a,**k)
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile='/etc/3xui-preview-test/cert.pem')))
def req(path,data=None,csrf=None):
 headers={}
 if data is not None:
  data=urllib.parse.urlencode(data).encode();headers['Content-Type']='application/x-www-form-urlencoded'
  if csrf: headers['X-CSRF-Token']=csrf
 with opener.open(urllib.request.Request('https://panel.example.test'+path,data=data,headers=headers),timeout=15) as r: result=json.load(r)
 assert result.get('success'),path
 return result.get('obj')
csrf=req('/csrf-token');req('/login',{'username':fixture['username'],'password':fixture['password']},csrf);req('/panel/api/inbounds/list')
print('PREVIEW04B_PANEL_API_AFTER_ROUTE_PASS')
PY
install -d -m 0755 /var/www/3xui-pro-fork/decoy/.well-known/acme-challenge
printf 'synthetic-challenge\n' >/var/www/3xui-pro-fork/decoy/.well-known/acme-challenge/fixture
chmod 0644 /var/www/3xui-pro-fork/decoy/.well-known/acme-challenge/fixture
python3 - <<'PY'
import http.client
c=http.client.HTTPConnection('127.0.0.1',80,timeout=10);c.request('GET','/.well-known/acme-challenge/fixture',headers={'Host':'example.test'});r=c.getresponse();assert (r.status,r.read())==(200,b'synthetic-challenge\n');c.close()
for path in ('/missing','/.hidden'):
 c=http.client.HTTPConnection('127.0.0.1',80,timeout=10);c.request('GET',path,headers={'Host':'example.test'});r=c.getresponse();assert r.status==404;r.read();c.close()
print('PREVIEW04B_LOCATION_PRIORITY_PASS')
PY
python3 - <<'PY'
import base64,http.client,json,socket,ssl,subprocess,urllib.error,urllib.request
data=json.load(open('/run/preview04a-fixture.json'))
ctx=ssl.create_default_context(cafile='/etc/3xui-preview-test/cert.pem'); orig=socket.getaddrinfo
socket.getaddrinfo=lambda host,port,*a,**k: orig('127.0.0.1' if host=='example.test' else host,port,*a,**k)
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPSHandler(context=ctx))
def get(url):
 req=urllib.request.Request(url,headers={'User-Agent':'v2rayNG/1.9'})
 try:
  with opener.open(req,timeout=15) as r: return r.status,r.read()
 except urllib.error.HTTPError as e: return e.code,e.read()
path='/preview04a-sub/'+data['subid']
status,body=get(data['base']+data['subid'])
assert status==200 and b'XONIX' not in body
req=urllib.request.Request(data['base']+data['subid'],headers={'User-Agent':'v2rayNG/1.9'})
with opener.open(req,timeout=15) as r: assert r.headers.get('Referrer-Policy')=='no-referrer'
logs=subprocess.check_output(['journalctl','-u','3xui-pro-fork.service','-o','cat'],text=True)
for name in ('/var/log/nginx/access.log','/var/log/nginx/error.log'):
 try:
  with open(name,errors='replace') as f: logs+=f.read()
 except FileNotFoundError: pass
assert data['subid'] not in logs, 'synthetic subscription token appeared in service logs'
print('PREVIEW04B_TOKEN_LOG_AND_REFERRER_PASS')
decoded=body if b'vless://' in body else base64.b64decode(body+b'='*(-len(body)%4))
assert b'vless://' in decoded and data['uuid'].encode() in decoded
bad='/preview04a-sub/invalid-synthetic-token'
direct=get('http://127.0.0.1:12996'+bad)
proxied=get('https://example.test'+bad)
assert direct==proxied and data['uuid'].encode() not in proxied[1] and b'XONIX' not in proxied[1]
unknown=get('https://example.test/not-a-subscription/whatever')
assert unknown[0]==404 and b'XONIX' not in unknown[1]
print('PREVIEW04B_SUBSCRIPTION_PASS')
print('PREVIEW04B_SUB_NEGATIVE_PASS status='+str(proxied[0]))
PY
nginx -t
python3 - <<'PY'
from pathlib import Path
import sqlite3
with sqlite3.connect('/var/lib/3xui-pro-fork/x-ui.db') as db:
    db.execute('create table preview04b_sentinel (value text)')
    db.execute('insert into preview04b_sentinel values (?)', ('PRESERVE',))
Path('/etc/nginx/conf.d/77-preview04b-sentinel.conf').write_text('# private fixture sentinel\n')
PY
managed=( "$DATA/preview-xray.json" "$DATA/preview-xray-clients.json"
          "$DATA"/awg/*.conf /etc/nginx/conf.d/3xui-pro-fork-preview.conf
          /etc/nginx/modules-enabled/99-3xui-preview-stream.conf
          /etc/nginx/conf.d/77-preview04b-sentinel.conf )
sha256sum "${managed[@]}" >/tmp/preview04b-owned-before
bash install-preview.sh "${args[@]}" --sandbox-subscriptions
sha256sum --status -c /tmp/preview04b-owned-before
python3 - <<'PY'
import sqlite3
with sqlite3.connect('/var/lib/3xui-pro-fork/x-ui.db') as db:
    assert db.execute('select value from preview04b_sentinel').fetchall() == [('PRESERVE',)]
    assert db.execute('pragma integrity_check').fetchone() == ('ok',)
PY
nginx -T 2>/dev/null | grep -c '^    map $ssl_preread_server_name $preview_backend {' | grep -qx 1
echo PREVIEW04B_REPEAT_INSTALL_PASS
cp -a /tmp/preview /tmp/preview-fault
python3 - <<'PY'
from pathlib import Path
path=Path('/tmp/preview-fault/release/preview_install.py')
source=path.read_text()
old='    return config.encode()'
assert source.count(old)==1
path.write_text(source.replace(old, r"    return (config + '\npreview04b_invalid_directive;\n').encode()"))
PY
if bash /tmp/preview-fault/install-preview.sh "${args[@]}" --sandbox-subscriptions >/tmp/preview04b-fault.log 2>&1; then
    echo 'Fault injection incorrectly passed'
    exit 1
fi
grep -q 'unknown directive "preview04b_invalid_directive"' /tmp/preview04b-fault.log
grep -q 'previous configuration restored' /tmp/preview04b-fault.log
sha256sum --status -c /tmp/preview04b-owned-before
nginx -t
python3 tests/release/preview04b_transports.py "$XRAY" "$CLIENTS" "$cert" "$key"
echo PREVIEW04B_NGINX_RECOVERY_PASS
openssl x509 -in "$cert" -pubkey -noout | openssl pkey -pubin -outform DER | openssl dgst -sha256 -binary | openssl base64 -A | sed 's/^/PREVIEW04B_BROWSER_SPKI=/'
echo
python3 -u - <<'PY'
import socket,socketserver,threading

class Relay(socketserver.BaseRequestHandler):
    def handle(self):
        with socket.create_connection(('127.0.0.1',443),timeout=5) as upstream:
            upstream.settimeout(None)
            def copy(source,destination):
                try:
                    while block := source.recv(65536):
                        destination.sendall(block)
                except OSError:
                    pass
                try:
                    destination.shutdown(socket.SHUT_WR)
                except OSError:
                    pass
            outgoing=threading.Thread(target=copy,args=(self.request,upstream))
            outgoing.start()
            copy(upstream,self.request)
            outgoing.join(timeout=5)

with socketserver.ThreadingTCPServer(('0.0.0.0',18445),Relay) as relay:
    relay.daemon_threads=True
    threading.Timer(110,relay.shutdown).start()
    print('PREVIEW04B_BROWSER_READY')
    relay.serve_forever()
PY
echo PREVIEW04B_VM_PASS
systemctl poweroff
