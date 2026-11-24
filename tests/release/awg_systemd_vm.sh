#!/bin/bash
# Runs only in the disposable, network-disabled Debian test VM.
set -Eeuo pipefail
umask 077
trap 'echo "BUILD04_VM_FAIL line=$LINENO"; systemctl poweroff' ERR
[[ $(cat /proc/1/comm) == systemd && -c /dev/net/tun ]]
ip netns add client
ip link add underlay0 type veth peer name underlay1
ip link set underlay1 netns client
ip addr add 192.0.2.1/30 dev underlay0
ip link set underlay0 up
ip -n client addr add 192.0.2.2/30 dev underlay1
ip -n client link set underlay1 up
ip -n client link set lo up
mkdir -m 700 /tmp/package
tar -xzf /mnt/seed/candidate.tar.gz -C /tmp/package
cd /tmp/package
python3 install_candidate.py --awg-endpoint 192.0.2.1 --awg-subnet 10.88.31.0/30 --awg-port 29177
systemctl is-active --quiet 3xui-pro-fork.service
systemctl is-active --quiet 3xui-pro-fork-awg.service
ip address show dev xproawg0 | grep -q '10.88.31.1/30'
conf=/var/lib/3xui-pro-fork/awg
before=$(sha256sum "$conf/server.setconf" "$conf/client.conf")
test "$(stat -c %a "$conf")" = 700
test "$(stat -c %a "$conf/client.conf")" = 600
/opt/3xui-pro-fork/panel/bin/xray-linux-amd64 version | grep -q '^Xray 26.11.9 '
python3 - <<'PY'
import http.cookiejar,json,re,subprocess,time,urllib.parse,urllib.request
logs=subprocess.check_output(['journalctl','-u','3xui-pro-fork.service','-o','cat'],text=True)
match=re.search(r'Username: (\S+)\s+Password: (\S+)',logs)
assert match, 'initial login not found in private journal'
opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),urllib.request.ProxyHandler({}))
def request(path,data=None,token=None):
 headers={}
 if data is not None: headers['Content-Type']='application/x-www-form-urlencoded'
 if token: headers['X-CSRF-Token']=token
 with opener.open(urllib.request.Request('http://127.0.0.1:2053'+path,data=data,headers=headers),timeout=10) as res:
  value=json.load(res)
 assert value.get('success'), path
 return value.get('obj')
for attempt in range(30):
 try: token=request('/csrf-token'); break
 except OSError: time.sleep(1)
else: raise RuntimeError('panel HTTP unavailable')
request('/login',urllib.parse.urlencode({'username':match[1],'password':match[2]}).encode(),token)
request('/panel/api/inbounds/list')
print('PANEL_API_PASS')
PY
sed '/^Address = /d' "$conf/client.conf" >/tmp/client.setconf
ip netns exec client /opt/3xui-pro-fork/awg/amneziawg-go -f awgclient >/tmp/client.log 2>&1 & client_pid=$!
trap 'kill "$client_pid" 2>/dev/null || :; echo "BUILD04_VM_FAIL line=$LINENO"; systemctl poweroff' ERR
for _ in {1..100}; do [[ -S /var/run/amneziawg/awgclient.sock ]] && break; sleep .1; done
ip netns exec client /opt/3xui-pro-fork/awg/awg setconf awgclient /tmp/client.setconf
ip -n client addr add 10.88.31.2/30 dev awgclient
ip -n client link set awgclient up
python3 -c 'import socket; s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); s.bind(("10.88.31.1",9999)); s.settimeout(30); d,a=s.recvfrom(100); assert d==b"request"; s.sendto(b"response",a)' & echo_pid=$!
sleep .5
ip netns exec client python3 -c 'import socket; s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); s.settimeout(20); s.sendto(b"request",("10.88.31.1",9999)); d,_=s.recvfrom(100); assert d==b"response"'
wait "$echo_pid"
/opt/3xui-pro-fork/awg/awg show xproawg0 latest-handshakes | awk '$2 > 0 {found=1} END {exit !found}'
echo AWG_HANDSHAKE_BIDIRECTIONAL_UDP_PASS
systemctl stop 3xui-pro-fork-awg.service
if ip link show dev xproawg0 >/dev/null 2>&1; then echo AWG_STOP_INTERFACE_REMAINS; exit 1; fi
systemctl start 3xui-pro-fork-awg.service
systemctl is-active --quiet 3xui-pro-fork-awg.service
systemctl restart 3xui-pro-fork-awg.service
systemctl is-active --quiet 3xui-pro-fork-awg.service
ip link show dev xproawg0 >/dev/null
[[ "$before" == "$(sha256sum "$conf/server.setconf" "$conf/client.conf")" ]]
echo AWG_SYSTEMD_STOP_START_RESTART_CONFIG_PASS
kill "$client_pid"; wait "$client_pid" || :
echo BUILD04_VM_PASS
systemctl poweroff
