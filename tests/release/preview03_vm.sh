#!/bin/bash
set -Eeuo pipefail
trap 'echo "PREVIEW03_VM_FAIL line=$LINENO"; systemctl poweroff' ERR
modprobe tun
mkdir -p /tmp/pkg /tmp/preview
tar -xzf /mnt/seed/candidate.tar.gz -C /tmp/pkg
tar -xzf /mnt/seed/preview.tar.gz -C /tmp/preview
cd /tmp/preview
bash install-preview.sh --domain example.test --components /tmp/pkg --awg-subnet 10.88.31.0/30
systemctl is-active --quiet 3xui-pro-fork.service
systemctl is-active --quiet 3xui-pro-fork-awg.service
ip address show dev xproawg0 | grep -q '10.88.31.1/30'
/opt/3xui-pro-fork/panel/bin/xray-linux-amd64 version | grep -q '^Xray 26.11.9 '
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
PY
python3 - <<'PY'
import urllib.request
r=urllib.request.Request('http://127.0.0.1:80/',headers={'Host':'example.test'})
assert urllib.request.urlopen(r).read()==open('assets/decoy/xonix/index.html','rb').read()
PY
test "$(stat -c '%U:%G %a' /var/www/3xui-pro-fork/decoy/index.html)" = 'root:root 644'
sha256sum /var/lib/3xui-pro-fork/awg/server.setconf /var/lib/3xui-pro-fork/awg/client.conf > /tmp/awg-before
python3 - <<'PY'
import sqlite3
c=sqlite3.connect('/var/lib/3xui-pro-fork/x-ui.db');c.execute('create table preview03_sentinel (v text)');c.execute("insert into preview03_sentinel values ('unchanged')");c.commit();c.close()
PY
printf 'user fixture\n' >/var/www/html/preview03-user-fixture
bash install-preview.sh --domain example.test --components /tmp/pkg --awg-subnet 10.88.31.0/30
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
python3 - <<'PY'
import sys
sys.path.insert(0,'release')
import preview_install as p
old=p.NGINX.read_bytes()
p.nginx_config=lambda domain,port: b'invalid nginx directive;\n'
try: p.publish('example.test',80,(p.REPO/'assets/decoy/xonix/index.html').read_bytes())
except RuntimeError as e: assert 'previous configuration restored' in str(e),str(e)
else: raise AssertionError('injected error accepted')
assert p.NGINX.read_bytes()==old
p.check_http('example.test',80,(p.REPO/'assets/decoy/xonix/index.html').read_bytes())
print('PREVIEW03_CONFIG_RECOVERY_PASS')
PY
systemctl is-active --quiet 3xui-pro-fork.service
systemctl is-active --quiet 3xui-pro-fork-awg.service
echo PREVIEW03_VM_PASS
systemctl poweroff
