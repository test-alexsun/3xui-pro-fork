#!/bin/bash
set -Eeuo pipefail
umask 077
exec 3>/dev/ttyS1
exec </dev/null >&3 2>&1
on_error() {
    echo "PREVIEW05_VM_FAIL line=$1" >&3
    for file in /tmp/preview05-ca/dns.log /tmp/preview05-ca/pebble.log /tmp/preview05-ca/curl.log; do
        if [ -f "$file" ]; then tail -n 25 "$file" >&3; fi
    done
    sleep 3
    systemctl poweroff
}
trap 'on_error "$LINENO"' ERR
cd /tmp
export DEBIAN_FRONTEND=noninteractive
if ! command -v dnsmasq >/dev/null || ! command -v curl >/dev/null; then
    apt-get update -qq
    apt-get install -y -qq --no-install-recommends dnsmasq-base curl openssl
fi
modprobe tun
test ! -e /var/lib/3xui-pro-fork
for directory in /tmp/preview05 /tmp/preview05-ca; do
    if [ -d "$directory" ]; then
        if [ -f "$directory/pebble.log" ]; then tail -n 10 "$directory/pebble.log"; fi
        mv "$directory" "$directory.previous-$$"
    fi
    mkdir -m 700 "$directory"
done
if [ -f /mnt/seed/preview.tar.gz ]; then
    tar -xzf /mnt/seed/preview.tar.gz -C /tmp/preview05
else
    revision=$(cat /mnt/seed/revision)
    curl --fail --silent --show-error --location \
      "https://raw.githubusercontent.com/test-alexsun/3xui-pro-fork/$revision/bootstrap-preview.sh" \
      -o /tmp/preview05/bootstrap-preview.sh
    printf '%s  %s\n' "$(cat /mnt/seed/boot-sha)" /tmp/preview05/bootstrap-preview.sh | sha256sum -c -
fi
printf '%s  %s\n' 34595d915bbc2fc827affb3f58593034824df57e95353b031c8d5185724485ce \
  /mnt/seed/pebble.tgz | sha256sum -c -
tar --no-same-owner -xzf /mnt/seed/pebble.tgz -C /tmp/preview05-ca
pebble=/tmp/preview05-ca/pebble-linux-amd64/linux/amd64/pebble
chmod 0755 "$pebble"

ip netns add preview-client
ip link add preview-host type veth peer name preview-peer
ip link set preview-peer netns preview-client
ip addr add 10.77.5.1/24 dev preview-host
ip link set preview-host up
ip -n preview-client addr add 10.77.5.2/24 dev preview-peer
ip -n preview-client link set preview-peer up
ip -n preview-client link set lo up
echo PREVIEW05_NAMESPACE_READY
printf '%s\n' '10.77.5.1 example.test panel.example.test p0.example.test p3.example.test' >>/etc/hosts
peer() { ip netns exec preview-client "$@"; }
ip netns exec preview-client dnsmasq --no-daemon --bind-interfaces --listen-address=10.77.5.2 --port=8053 \
    --no-resolv --local=/example.test/ --address=/example.test/10.77.5.1 >/tmp/preview05-ca/dns.log 2>&1 &
openssl req -x509 -newkey rsa:2048 -nodes -days 1 -subj /CN=preview05-acme-test \
    -addext 'subjectAltName=IP:10.77.5.2' -keyout /tmp/preview05-ca/pebble-key.pem \
    -out /tmp/preview05-ca/pebble-cert.pem >/dev/null 2>&1
cat >/tmp/preview05-ca/pebble.json <<'JSON'
{"pebble":{"listenAddress":"10.77.5.2:14000","managementListenAddress":"10.77.5.2:15000",
"certificate":"/tmp/preview05-ca/pebble-cert.pem","privateKey":"/tmp/preview05-ca/pebble-key.pem",
"httpPort":80,"tlsPort":443,"externalAccountBindingRequired":false,
"profiles":{"default":{"description":"Default profile","validityPeriod":7776000}}}}
JSON
ip netns exec preview-client env PEBBLE_VA_NOSLEEP=1 PEBBLE_WFE_NONCEREJECT=0 "$pebble" \
    -config /tmp/preview05-ca/pebble.json -dnsserver 10.77.5.2:8053 >/tmp/preview05-ca/pebble.log 2>&1 &
ca_pid=$!
for _ in {1..120}; do
    if curl -fsS --noproxy '*' --connect-timeout 3 --max-time 6         --cacert /tmp/preview05-ca/pebble-cert.pem         https://10.77.5.2:15000/roots/0 -o /tmp/preview05-ca/root.pem 2>/tmp/preview05-ca/curl.log; then
        break
    fi
    kill -0 "$ca_pid"
    sleep 1
done
test -s /tmp/preview05-ca/root.pem
cat /tmp/preview05-ca/pebble-cert.pem /tmp/preview05-ca/root.pem >/tmp/preview05-ca/ca.pem
openssl x509 -in /tmp/preview05-ca/root.pem -noout
echo PREVIEW05_ACME_TEST_SERVER_READY
stat -c "test executable mode: %a" "$pebble"

cd /tmp/preview05
args=(--public-bind 10.77.5.1 --domain example.test --acme-email rc-test@example.test
      --awg-subnet 10.88.31.0/30 --acme-test-directory https://10.77.5.2:14000/dir
      --acme-test-ca /tmp/preview05-ca/ca.pem)
install_preview() {
  if [ -f /mnt/seed/preview.tar.gz ]; then
      sh ./install-preview.sh "${args[@]}" "$@"
  else
      sh ./bootstrap-preview.sh "$revision" "${args[@]}" "$@"
  fi
}
install_preview
echo PREVIEW05_STANDALONE_INSTALL_PASS
nginx -t
XRAY=/opt/3xui-pro-fork/panel/bin/xray-linux-amd64
DATA=/var/lib/3xui-pro-fork
"$XRAY" run -test -config "$DATA/preview-xray.json"
for service in nginx 3xui-preview-xray.service 3xui-pro-fork.service 3xui-pro-fork-awg.service 3xui-preview-renew.timer; do
    systemctl is-active --quiet "$service"
done
ss -H -ltn 'sport = :443' | grep -F '10.77.5.1:443'
for port in 18443 19440 19441 19443 19444 2053; do ss -H -ltn "sport = :$port" | grep -F "127.0.0.1:$port"; done
test -z "$(ss -H -lun 'sport = :443')"
ss -H -lun 'sport = :29177' | grep -F ':29177'
cmp /var/www/3xui-pro-fork/decoy/index.html /mnt/seed/xonix.html
[[ $(stat -c '%U:%G %a' /var/www/3xui-pro-fork/decoy/index.html) == 'root:root 644' ]]
peer curl -fsS --cacert /tmp/preview05-ca/root.pem https://example.test/ -o /tmp/preview05-site
cmp /tmp/preview05-site /mnt/seed/xonix.html
echo PREVIEW05_EXTERNAL_HTTPS_XONIX_PASS
transport_test() {
    peer python3 /mnt/seed/transport.py "$XRAY" "$DATA/preview-xray-clients.json" \
        /tmp/preview05-ca/pebble-cert.pem /tmp/preview05-ca/pebble-key.pem \
        --p1-ca /tmp/preview05-ca/root.pem
}
transport_test
systemctl restart 3xui-preview-xray.service
sleep 2
transport_test
echo PREVIEW05_XRAY_EXTERNAL_RECONNECT_PASS
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
socket.getaddrinfo=lambda host,port,*a,**k: original('10.77.5.1' if host=='panel.example.test' else host,port,*a,**k)
secure=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),urllib.request.ProxyHandler({}),urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile='/tmp/preview05-ca/root.pem')))
def secure_call(path,payload=None,csrf=None):
 headers={}; data=None
 if payload is not None:
  data=urllib.parse.urlencode(payload).encode(); headers['Content-Type']='application/x-www-form-urlencoded'
  if csrf: headers['X-CSRF-Token']=csrf
 with secure.open(urllib.request.Request('https://panel.example.test'+path,data=data,headers=headers),timeout=15) as r: result=json.load(r)
 assert result.get('success'),path
 return result.get('obj')
csrf=secure_call('/csrf-token');secure_call('/login',{'username':username,'password':password},csrf);secure_call('/panel/api/inbounds/list')
print('PREVIEW05_PANEL_HTTPS_API_PASS')
print('PREVIEW05_TEST_CLIENT_CREATED')
PY
install_preview --public-subscriptions
peer python3 - <<'PY'
import http.cookiejar,json,socket,ssl,urllib.parse,urllib.request
fixture=json.load(open('/run/preview04a-fixture.json'))
old=socket.getaddrinfo
socket.getaddrinfo=lambda host,port,*a,**k: old('10.77.5.1' if host=='panel.example.test' else host,port,*a,**k)
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile='/tmp/preview05-ca/root.pem')))
def req(path,data=None,csrf=None):
 headers={}
 if data is not None:
  data=urllib.parse.urlencode(data).encode();headers['Content-Type']='application/x-www-form-urlencoded'
  if csrf: headers['X-CSRF-Token']=csrf
 with opener.open(urllib.request.Request('https://panel.example.test'+path,data=data,headers=headers),timeout=15) as r: result=json.load(r)
 assert result.get('success'),path
 return result.get('obj')
csrf=req('/csrf-token');req('/login',{'username':fixture['username'],'password':fixture['password']},csrf);req('/panel/api/inbounds/list')
print('PREVIEW05_PANEL_API_AFTER_ROUTE_PASS')
PY
install -d -m 0755 /var/www/3xui-pro-fork/decoy/.well-known/acme-challenge
printf 'synthetic-challenge\n' >/var/www/3xui-pro-fork/decoy/.well-known/acme-challenge/fixture
chmod 0644 /var/www/3xui-pro-fork/decoy/.well-known/acme-challenge/fixture
python3 - <<'PY'
import http.client
c=http.client.HTTPConnection('127.0.0.1',80,timeout=10);c.request('GET','/.well-known/acme-challenge/fixture',headers={'Host':'example.test'});r=c.getresponse();assert (r.status,r.read())==(200,b'synthetic-challenge\n');c.close()
for path in ('/missing','/.hidden'):
 c=http.client.HTTPConnection('127.0.0.1',80,timeout=10);c.request('GET',path,headers={'Host':'example.test'});r=c.getresponse();assert r.status==404;r.read();c.close()
print('PREVIEW05_LOCATION_PRIORITY_PASS')
PY
python3 - <<'PY'
import base64,http.client,json,socket,ssl,subprocess,urllib.error,urllib.request
data=json.load(open('/run/preview04a-fixture.json'))
ctx=ssl.create_default_context(cafile='/tmp/preview05-ca/root.pem'); orig=socket.getaddrinfo
socket.getaddrinfo=lambda host,port,*a,**k: orig('10.77.5.1' if host=='example.test' else host,port,*a,**k)
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
print('PREVIEW05_TOKEN_LOG_AND_REFERRER_PASS')
decoded=body if b'vless://' in body else base64.b64decode(body+b'='*(-len(body)%4))
assert b'vless://' in decoded and data['uuid'].encode() in decoded
bad='/preview04a-sub/invalid-synthetic-token'
direct=get('http://127.0.0.1:12996'+bad)
proxied=get('https://example.test'+bad)
assert direct==proxied and data['uuid'].encode() not in proxied[1] and b'XONIX' not in proxied[1]
unknown=get('https://example.test/not-a-subscription/whatever')
assert unknown[0]==404 and b'XONIX' not in unknown[1]
print('PREVIEW05_SUBSCRIPTION_PASS')
print('PREVIEW05_SUB_NEGATIVE_PASS status='+str(proxied[0]))
PY
peer python3 - <<'PY'
import base64,json,ssl,urllib.request
with open('/run/preview04a-fixture.json') as file:
    fixture=json.load(file)
context=ssl.create_default_context(cafile='/tmp/preview05-ca/root.pem')
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPSHandler(context=context))
request=urllib.request.Request(fixture['base']+fixture['subid'],headers={'User-Agent':'v2rayNG/1.9'})
with opener.open(request,timeout=15) as response:
    body=response.read()
    assert response.status==200 and response.headers['Referrer-Policy']=='no-referrer'
decoded=body if b'vless://' in body else base64.b64decode(body+b'='*(-len(body)%4))
assert fixture['uuid'].encode() in decoded
print('PREVIEW05_EXTERNAL_SUBSCRIPTION_PASS')
PY
nginx -t
python3 - <<'PY'
from pathlib import Path
import sqlite3
with sqlite3.connect('/var/lib/3xui-pro-fork/x-ui.db') as db:
    db.execute('create table preview05_sentinel (value text)')
    db.execute('insert into preview05_sentinel values (?)', ('PRESERVE',))
Path('/etc/nginx/conf.d/77-preview05-sentinel.conf').write_text('# unrelated sentinel\n')
Path('/var/www/html/preview05-sentinel.html').write_text('Unrelated site content\n')
PY
managed=( "$DATA/preview-xray.json" "$DATA/preview-xray-clients.json" "$DATA/awg/client.conf" "$DATA/awg/server.setconf"
          /etc/nginx/conf.d/3xui-pro-fork-preview.conf
          /etc/nginx/modules-enabled/99-3xui-preview-stream.conf
          /etc/nginx/conf.d/77-preview05-sentinel.conf /var/www/html/preview05-sentinel.html
          /etc/systemd/system/3xui-preview-xray.service
          /etc/systemd/system/3xui-preview-renew.service
          /etc/systemd/system/3xui-preview-renew.timer
          /var/lib/3xui-preview-acme/config/live/3xui-preview/fullchain.pem
          /var/lib/3xui-preview-acme/config/live/3xui-preview/privkey.pem )
sha256sum "${managed[@]}" >/tmp/preview05-before
install_preview --public-subscriptions
sha256sum --status -c /tmp/preview05-before
python3 - <<'PY'
import sqlite3
with sqlite3.connect('/var/lib/3xui-pro-fork/x-ui.db') as db:
    assert db.execute('select value from preview05_sentinel').fetchall() == [('PRESERVE',)]
    assert db.execute('pragma integrity_check').fetchone() == ('ok',)
PY
nginx -T 2>/dev/null | grep -c '^    map $ssl_preread_server_name $preview_backend {' | grep -qx 1
echo PREVIEW05_REPEAT_INSTALL_PASS

awg=/opt/3xui-pro-fork/awg
conf=$DATA/awg
sed '/^Address = /d' "$conf/client.conf" >/tmp/preview05-client.setconf
start_awg_client() {
    ip netns exec preview-client "$awg/amneziawg-go" -f awgclient >/tmp/preview05-awg-client.log 2>&1 &
    client_pid=$!
    for _ in {1..100}; do
        [[ -S /var/run/amneziawg/awgclient.sock ]] && break
        kill -0 "$client_pid"
        sleep .1
    done
    peer "$awg/awg" setconf awgclient /tmp/preview05-client.setconf
    ip -n preview-client addr add 10.88.31.2/30 dev awgclient
    ip -n preview-client link set awgclient up
}
stop_awg_client() {
    kill "$client_pid"
    wait "$client_pid" || :
    for _ in {1..100}; do
        if ! ip -n preview-client link show dev awgclient >/dev/null 2>&1; then return; fi
        sleep .1
    done
    return 1
}
start_awg_client
awg_traffic() {
    python3 -c 'import socket; s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); s.bind(("10.88.31.1",9999)); s.settimeout(30); d,a=s.recvfrom(100); assert d==b"request"; s.sendto(b"response",a)' &
    local server=$!
    sleep .4
    peer python3 -c 'import socket; s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); s.settimeout(20); s.sendto(b"request",("10.88.31.1",9999)); d,_=s.recvfrom(100); assert d==b"response"'
    wait "$server"
    "$awg/awg" show xproawg0 latest-handshakes | awk '$2 > 0 {found=1} END {exit !found}'
}
awg_traffic
echo PREVIEW05_AWG_UDP_BEFORE_RESTART_PASS
stop_awg_client
systemctl restart 3xui-pro-fork-awg.service
start_awg_client
ip addr show dev xproawg0 | grep -F 10.88.31.1/30
awg_traffic
sha256sum --status -c /tmp/preview05-before
echo PREVIEW05_AWG_UDP_RECONNECT_PASS

systemd-analyze verify /etc/systemd/system/3xui-preview-renew.service /etc/systemd/system/3xui-preview-renew.timer
lineage=/var/lib/3xui-preview-acme/config/live/3xui-preview
old_cert_sha=$(sha256sum "$lineage/fullchain.pem")
master=$(pgrep -xo nginx)
workers_before=$(pgrep -P "$master" | sort -n)
REQUESTS_CA_BUNDLE=/tmp/preview05-ca/ca.pem certbot renew --force-renewal --non-interactive \
    --cert-name 3xui-preview --no-directory-hooks \
    --config-dir /var/lib/3xui-preview-acme/config --work-dir /var/lib/3xui-preview-acme/work \
    --logs-dir /var/lib/3xui-preview-acme/logs --deploy-hook /var/lib/3xui-preview-acme/renew-deploy
test "$old_cert_sha" != "$(sha256sum "$lineage/fullchain.pem")"
for _ in {1..20}; do
    if [ "$workers_before" != "$(pgrep -P "$master" | sort -n)" ]; then break; fi
    sleep .5
done
test "$workers_before" != "$(pgrep -P "$master" | sort -n)"
peer curl -fsS --cacert /tmp/preview05-ca/root.pem https://example.test/ -o /tmp/preview05-renewed
cmp /mnt/seed/xonix.html /tmp/preview05-renewed
echo PREVIEW05_ACME_RENEWAL_RELOAD_PASS

if [ -f /mnt/seed/preview.tar.gz ]; then
    cp -a /tmp/preview05 /tmp/preview05-fault
    python3 - <<'PY'
from pathlib import Path
path=Path('/tmp/preview05-fault/release/preview_install.py')
code=path.read_text()
old='    return config.encode()'
assert code.count(old)==1
path.write_text(code.replace(old,r"    return (config + '\npreview05_invalid_directive;\n').encode()"))
PY
    before_fault=$(sha256sum /etc/nginx/conf.d/3xui-pro-fork-preview.conf)
    if sh /tmp/preview05-fault/install-preview.sh "${args[@]}" --public-subscriptions >/tmp/preview05-fault.log 2>&1; then
        echo 'Fault injection incorrectly passed'
        exit 1
    fi
    grep -q 'unknown directive "preview05_invalid_directive"' /tmp/preview05-fault.log
    grep -q 'previous configuration restored' /tmp/preview05-fault.log
    test "$before_fault" = "$(sha256sum /etc/nginx/conf.d/3xui-pro-fork-preview.conf)"
    nginx -t
    transport_test
    echo PREVIEW05_NGINX_RECOVERY_PASS
fi
apt-get install -y -qq --no-install-recommends chromium nodejs
mkdir -m 700 /tmp/browser-node
tar -xzf /mnt/seed/browser.tgz -C /tmp/browser-node
peer env NODE_PATH=/tmp/browser-node PREVIEW_BROWSER_ADDRESS=10.77.5.1 PREVIEW_BROWSER_CA=/tmp/preview05-ca/root.pem     node /mnt/seed/browser.cjs https://example.test/ "$lineage/fullchain.pem"
echo PREVIEW05_BROWSER_PASS
stop_awg_client
echo PREVIEW05_INTEGRATION_PASS
sleep 3
systemctl poweroff
