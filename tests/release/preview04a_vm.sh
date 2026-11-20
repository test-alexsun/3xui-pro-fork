#!/bin/bash
set -Eeuo pipefail
umask 077
trap 'echo "PREVIEW04A_VM_FAIL line=$LINENO"; systemctl poweroff' ERR
modprobe tun
command -v openssl >/dev/null || { apt-get update; DEBIAN_FRONTEND=noninteractive apt-get install -y openssl; }
mkdir -p /etc/3xui-preview-test /tmp/pkg /tmp/preview
chmod 700 /etc/3xui-preview-test
openssl req -x509 -newkey rsa:2048 -nodes -days 1 -subj /CN=example.test -addext 'subjectAltName=DNS:example.test,DNS:panel.example.test' -keyout /etc/3xui-preview-test/key.pem -out /etc/3xui-preview-test/cert.pem >/dev/null 2>&1
chmod 600 /etc/3xui-preview-test/key.pem
tar -xzf /mnt/seed/candidate.tar.gz -C /tmp/pkg
tar -xzf /mnt/seed/preview.tar.gz -C /tmp/preview
cd /tmp/preview
args=(--domain example.test --test-mode --sandbox-tls-cert /etc/3xui-preview-test/cert.pem --sandbox-tls-key /etc/3xui-preview-test/key.pem --components /tmp/pkg --awg-subnet 10.88.31.0/30)
bash install-preview.sh "${args[@]}"
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
settings.update(subEnable=True,subListen='127.0.0.1',subPort=12996,subPath='/preview04a-sub/',subJsonEnable=False,subClashEnable=False,subCertFile='',subKeyFile='',subDomain='',subURI='https://example.test:18443/preview04a-sub/',subJsonURI='',subClashURI='')
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
assert base=='https://example.test:18443/preview04a-sub/', 'panel subscription base differs'
with open('/run/preview04a-fixture.json','w') as f: json.dump({'subid':subid,'uuid':identity,'base':base,'username':username,'password':password},f)
import ssl
original=socket.getaddrinfo
socket.getaddrinfo=lambda host,port,*a,**k: original('127.0.0.1' if host=='panel.example.test' else host,port,*a,**k)
secure=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),urllib.request.ProxyHandler({}),urllib.request.HTTPSHandler(context=ssl._create_unverified_context()))
def secure_call(path,payload=None,csrf=None):
 headers={}; data=None
 if payload is not None:
  data=urllib.parse.urlencode(payload).encode(); headers['Content-Type']='application/x-www-form-urlencoded'
  if csrf: headers['X-CSRF-Token']=csrf
 with secure.open(urllib.request.Request('https://panel.example.test:18443'+path,data=data,headers=headers),timeout=15) as r: result=json.load(r)
 assert result.get('success'),path
 return result.get('obj')
csrf=secure_call('/csrf-token');secure_call('/login',{'username':username,'password':password},csrf);secure_call('/panel/api/inbounds/list')
print('PREVIEW04A_PANEL_HTTPS_API_PASS')
print('PREVIEW04A_TEST_CLIENT_CREATED')
PY
bash install-preview.sh "${args[@]}" --sandbox-subscriptions
python3 - <<'PY'
import http.cookiejar,json,socket,ssl,urllib.parse,urllib.request
fixture=json.load(open('/run/preview04a-fixture.json'))
old=socket.getaddrinfo
socket.getaddrinfo=lambda host,port,*a,**k: old('127.0.0.1' if host=='panel.example.test' else host,port,*a,**k)
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),urllib.request.HTTPSHandler(context=ssl._create_unverified_context()))
def req(path,data=None,csrf=None):
 headers={}
 if data is not None:
  data=urllib.parse.urlencode(data).encode();headers['Content-Type']='application/x-www-form-urlencoded'
  if csrf: headers['X-CSRF-Token']=csrf
 with opener.open(urllib.request.Request('https://panel.example.test:18443'+path,data=data,headers=headers),timeout=15) as r: result=json.load(r)
 assert result.get('success'),path
 return result.get('obj')
csrf=req('/csrf-token');req('/login',{'username':fixture['username'],'password':fixture['password']},csrf);req('/panel/api/inbounds/list')
print('PREVIEW04A_PANEL_API_AFTER_ROUTE_PASS')
PY
install -d -m 0755 /var/www/3xui-pro-fork/decoy/.well-known/acme-challenge
printf 'synthetic-challenge\n' >/var/www/3xui-pro-fork/decoy/.well-known/acme-challenge/fixture
chmod 0644 /var/www/3xui-pro-fork/decoy/.well-known/acme-challenge/fixture
python3 - <<'PY'
import http.client
c=http.client.HTTPConnection('127.0.0.1',18080,timeout=10);c.request('GET','/.well-known/acme-challenge/fixture',headers={'Host':'example.test'});r=c.getresponse();assert (r.status,r.read())==(200,b'synthetic-challenge\n');c.close()
for path in ('/missing','/.hidden'):
 c=http.client.HTTPConnection('127.0.0.1',18080,timeout=10);c.request('GET',path,headers={'Host':'example.test'});r=c.getresponse();assert r.status==404;r.read();c.close()
print('PREVIEW04A_LOCATION_PRIORITY_PASS')
PY
python3 - <<'PY'
import base64,http.client,json,socket,ssl,subprocess,urllib.error,urllib.request
data=json.load(open('/run/preview04a-fixture.json'))
ctx=ssl._create_unverified_context(); orig=socket.getaddrinfo
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
print('PREVIEW04A_TOKEN_LOG_AND_REFERRER_PASS')
decoded=body if b'vless://' in body else base64.b64decode(body+b'='*(-len(body)%4))
assert b'vless://' in decoded and data['uuid'].encode() in decoded
bad='/preview04a-sub/invalid-synthetic-token'
direct=get('http://127.0.0.1:12996'+bad)
proxied=get('https://example.test:18443'+bad)
assert direct==proxied and data['uuid'].encode() not in proxied[1] and b'XONIX' not in proxied[1]
unknown=get('https://example.test:18443/not-a-subscription/whatever')
assert unknown[0]==404 and b'XONIX' not in unknown[1]
print('PREVIEW04A_SUBSCRIPTION_PASS')
print('PREVIEW04A_SUB_NEGATIVE_PASS status='+str(proxied[0]))
PY
nginx -t
echo PREVIEW04A_BROWSER_READY
sleep 120
echo PREVIEW04A_VM_PASS
systemctl poweroff
