#!/bin/bash
set -Eeuo pipefail
trap 'echo "PREVIEW04_VM_FAIL line=$LINENO"; systemctl poweroff' ERR
modprobe tun
command -v openssl >/dev/null || { apt-get update; DEBIAN_FRONTEND=noninteractive apt-get install -y openssl; }
mkdir -p /etc/3xui-preview-test
chmod 700 /etc/3xui-preview-test
openssl req -x509 -newkey rsa:2048 -nodes -days 1 -subj /CN=example.test -addext 'subjectAltName=DNS:example.test,DNS:panel.example.test' -keyout /etc/3xui-preview-test/key.pem -out /etc/3xui-preview-test/cert.pem >/dev/null 2>&1
chmod 600 /etc/3xui-preview-test/key.pem
mkdir -p /tmp/pkg /tmp/preview
tar -xzf /mnt/seed/candidate.tar.gz -C /tmp/pkg
tar -xzf /mnt/seed/preview.tar.gz -C /tmp/preview
cd /tmp/preview
bash install-preview.sh --domain example.test --test-mode --sandbox-tls-cert /etc/3xui-preview-test/cert.pem --sandbox-tls-key /etc/3xui-preview-test/key.pem --components /tmp/pkg --awg-subnet 10.88.31.0/30
systemctl is-active --quiet 3xui-pro-fork.service
systemctl is-active --quiet 3xui-pro-fork-awg.service
ip address show dev xproawg0 | grep -q '10.88.31.1/30'
/opt/3xui-pro-fork/panel/bin/xray-linux-amd64 version > /tmp/preview-xray-version
grep -q '^Xray 26.11.9 ' /tmp/preview-xray-version
python3 - <<'PY'
import http.cookiejar,json,re,subprocess,time,urllib.parse,urllib.request
logs=subprocess.check_output(['journalctl','-u','3xui-pro-fork.service','-o','cat'],text=True)
match=re.search(r'Username: (\S+)\s+Password: (\S+)',logs); assert match
opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),urllib.request.ProxyHandler({}))
def request(path,data=None,token=None):
 h={}
 if data is not None: h['Content-Type']='application/x-www-form-urlencoded'
 if token: h['X-CSRF-Token']=token
 with opener.open(urllib.request.Request('http://127.0.0.1:2053'+path,data=data,headers=h),timeout=10) as r: value=json.load(r)
 assert value.get('success'),path
 return value.get('obj')
for n in range(30):
 try: token=request('/csrf-token'); break
 except OSError: time.sleep(1)
else: raise RuntimeError('panel unavailable')
request('/login',urllib.parse.urlencode({'username':match[1],'password':match[2]}).encode(),token)
request('/panel/api/inbounds/list')
print('PREVIEW03_PANEL_API_PASS')
import os
found=False
for name in os.listdir('/proc'):
 if name.isdigit():
  try: found |= os.path.realpath('/proc/'+name+'/exe')=='/opt/3xui-pro-fork/panel/bin/xray-linux-amd64'
  except OSError: pass
assert found, 'Xray process not observed'
print('PREVIEW03_XRAY_PROCESS_PASS')
import socket,ssl
original=socket.getaddrinfo
def local_dns(host,port,*args,**kwargs):
 return original('127.0.0.1' if host=='panel.example.test' else host,port,*args,**kwargs)
socket.getaddrinfo=local_dns
opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),urllib.request.ProxyHandler({}),urllib.request.HTTPSHandler(context=ssl._create_unverified_context()))
def https_request(path,data=None,token=None):
 h={}
 if data is not None: h['Content-Type']='application/x-www-form-urlencoded'
 if token: h['X-CSRF-Token']=token
 with opener.open(urllib.request.Request('https://panel.example.test:18443'+path,data=data,headers=h),timeout=10) as r: value=json.load(r)
 assert value.get('success'),path
 return value.get('obj')
token=https_request('/csrf-token')
https_request('/login',urllib.parse.urlencode({'username':match[1],'password':match[2]}).encode(),token)
https_request('/panel/api/inbounds/list')
print('PREVIEW04_HTTPS_PANEL_API_PASS')
PY
python3 - <<'PY'
import urllib.request
r=urllib.request.Request('http://127.0.0.1:18080/',headers={'Host':'example.test'})
assert urllib.request.urlopen(r).read()==open('assets/decoy/xonix/index.html','rb').read()
PY
test "$(stat -c '%U:%G %a' /var/www/3xui-pro-fork/decoy/index.html)" = 'root:root 644'
sha256sum /var/lib/3xui-pro-fork/awg/server.setconf /var/lib/3xui-pro-fork/awg/client.conf > /tmp/awg-before
python3 - <<'PY'
import sqlite3
c=sqlite3.connect('/var/lib/3xui-pro-fork/x-ui.db');c.execute('create table preview03_sentinel (v text)');c.execute("insert into preview03_sentinel values ('unchanged')");c.commit();c.close()
PY
printf 'user fixture\n' >/var/www/html/preview03-user-fixture
bash install-preview.sh --domain example.test --test-mode --sandbox-tls-cert /etc/3xui-preview-test/cert.pem --sandbox-tls-key /etc/3xui-preview-test/key.pem --components /tmp/pkg --awg-subnet 10.88.31.0/30
sha256sum -c /tmp/awg-before
python3 - <<'PY'
import sqlite3
c=sqlite3.connect('/var/lib/3xui-pro-fork/x-ui.db');assert c.execute('select v from preview03_sentinel').fetchone()==('unchanged',);c.close()
PY
test "$(cat /var/www/html/preview03-user-fixture)" = 'user fixture'
test "$(find /etc/nginx/conf.d -name '3xui-pro-fork-preview.conf' | wc -l)" = 1
systemctl is-active --quiet 3xui-pro-fork.service
systemctl is-active --quiet 3xui-pro-fork-awg.service
echo PREVIEW03_REPEAT_PASS
mkdir -p /var/www/3xui-pro-fork/decoy/.well-known/acme-challenge
printf 'sandbox-token\n' >/var/www/3xui-pro-fork/decoy/.well-known/acme-challenge/fixture
chmod 755 /var/www/3xui-pro-fork/decoy/.well-known /var/www/3xui-pro-fork/decoy/.well-known/acme-challenge
chmod 644 /var/www/3xui-pro-fork/decoy/.well-known/acme-challenge/fixture
python3 - <<'PY'
import http.client
c=http.client.HTTPConnection('127.0.0.1',18080,timeout=10)
c.request('GET','/.well-known/acme-challenge/fixture',headers={'Host':'example.test'}); r=c.getresponse(); assert (r.status,r.read())==(200,b'sandbox-token\n'); c.close()
for path in ('/missing','/.hidden'):
 c=http.client.HTTPConnection('127.0.0.1',18080,timeout=10);c.request('GET',path,headers={'Host':'example.test'});r=c.getresponse();assert r.status==404;r.read();c.close()
print('PREVIEW04_ACME_SANDBOX_HTTP_PASS')
PY
python3 - <<'PY'
import sys
sys.path.insert(0,'release')
import preview_install as p
old=p.NGINX.read_bytes()
p.nginx_config=lambda domain,port,sandbox: b'invalid nginx directive;\n'
try: p.publish('example.test',18080,(p.REPO/'assets/decoy/xonix/index.html').read_bytes(), sandbox=('/etc/3xui-preview-test/cert.pem','/etc/3xui-preview-test/key.pem'))
except RuntimeError as e: assert 'previous configuration restored' in str(e),str(e)
else: raise AssertionError('injected error accepted')
assert p.NGINX.read_bytes()==old
p.check_http('example.test',18080,(p.REPO/'assets/decoy/xonix/index.html').read_bytes())
print('PREVIEW03_CONFIG_RECOVERY_PASS')
PY
systemctl is-active --quiet 3xui-pro-fork.service
systemctl is-active --quiet 3xui-pro-fork-awg.service
echo PREVIEW04_VM_PASS
echo PREVIEW04_BROWSER_READY
sleep 120
systemctl poweroff
