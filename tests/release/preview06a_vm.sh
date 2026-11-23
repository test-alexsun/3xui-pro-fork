#!/bin/bash
set -Eeuo pipefail
umask 077
exec 3>/dev/ttyS1
exec </dev/null >&3 2>&1
on_error() {
    echo "PREVIEW06A_VM_FAIL line=$1" >&3
    for file in /tmp/preview06a-ca/dns.log /tmp/preview06a-ca/pebble.log /tmp/preview06a-ca/curl.log; do
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
for directory in /tmp/preview06a /tmp/preview06a-ca; do
    if [ -d "$directory" ]; then
        if [ -f "$directory/pebble.log" ]; then tail -n 10 "$directory/pebble.log"; fi
        mv "$directory" "$directory.previous-$$"
    fi
    mkdir -m 700 "$directory"
done
if [ -f /mnt/seed/preview.tar.gz ]; then
    tar -xzf /mnt/seed/preview.tar.gz -C /tmp/preview06a
else
    revision=$(cat /mnt/seed/revision)
    curl --fail --silent --show-error --location \
      "https://raw.githubusercontent.com/test-alexsun/3xui-pro-fork/$revision/bootstrap-preview.sh" \
      -o /tmp/preview06a/bootstrap-preview.sh
    printf '%s  %s\n' "$(cat /mnt/seed/boot-sha)" /tmp/preview06a/bootstrap-preview.sh | sha256sum -c -
fi
printf '%s  %s\n' 7e33cf3e426b67e9e647c44e8cc91683caa8ab331f7a99e5e27fcee291c4c7e2 \
  /mnt/seed/pebble.tgz | sha256sum -c -
tar --no-same-owner -xzf /mnt/seed/pebble.tgz -C /tmp/preview06a-ca
pebble=/tmp/preview06a-ca/pebble-linux-amd64/linux/amd64/pebble
chmod 0755 "$pebble"

ip netns add preview-client
ip link add preview-host type veth peer name preview-peer
ip link set preview-peer netns preview-client
ip addr add 10.77.5.1/24 dev preview-host
ip link set preview-host up
ip -n preview-client addr add 10.77.5.2/24 dev preview-peer
ip -n preview-client link set preview-peer up
ip -n preview-client link set lo up
echo PREVIEW06A_NAMESPACE_READY
printf '%s\n' '10.77.5.1 de126.alexsun55.ru de126-sub.alexsun55.ru' >>/etc/hosts
peer() { ip netns exec preview-client "$@"; }
ip netns exec preview-client dnsmasq --no-daemon --bind-interfaces --listen-address=10.77.5.2 --port=8053 \
    --no-hosts --no-resolv --local=/alexsun55.ru/ --host-record=de126.alexsun55.ru,10.77.5.1 --host-record=de126-sub.alexsun55.ru,10.77.5.1 >/tmp/preview06a-ca/dns.log 2>&1 &
openssl req -x509 -newkey rsa:2048 -nodes -days 1 -subj /CN=preview06a-acme-test \
    -addext 'subjectAltName=IP:10.77.5.2' -keyout /tmp/preview06a-ca/pebble-key.pem \
    -out /tmp/preview06a-ca/pebble-cert.pem >/dev/null 2>&1
cat >/tmp/preview06a-ca/pebble.json <<'JSON'
{"pebble":{"listenAddress":"10.77.5.2:14000","managementListenAddress":"10.77.5.2:15000",
"certificate":"/tmp/preview06a-ca/pebble-cert.pem","privateKey":"/tmp/preview06a-ca/pebble-key.pem",
"httpPort":80,"tlsPort":443,"externalAccountBindingRequired":false,
"profiles":{"default":{"description":"Default profile","validityPeriod":7776000}}}}
JSON
ip netns exec preview-client env PEBBLE_VA_NOSLEEP=1 PEBBLE_WFE_NONCEREJECT=0 "$pebble" \
    -config /tmp/preview06a-ca/pebble.json -dnsserver 10.77.5.2:8053 >/tmp/preview06a-ca/pebble.log 2>&1 &
ca_pid=$!
for _ in {1..120}; do
    if curl -fsS --noproxy '*' --connect-timeout 3 --max-time 6         --cacert /tmp/preview06a-ca/pebble-cert.pem         https://10.77.5.2:15000/roots/0 -o /tmp/preview06a-ca/root.pem 2>/tmp/preview06a-ca/curl.log; then
        break
    fi
    kill -0 "$ca_pid"
    sleep 1
done
test -s /tmp/preview06a-ca/root.pem
cat /tmp/preview06a-ca/pebble-cert.pem /tmp/preview06a-ca/root.pem >/tmp/preview06a-ca/ca.pem
openssl x509 -in /tmp/preview06a-ca/root.pem -noout
echo PREVIEW06A_ACME_TEST_SERVER_READY
stat -c "test executable mode: %a" "$pebble"

cd /tmp/preview06a
args=(--public-bind 10.77.5.1 --domain de126.alexsun55.ru --subscription-domain de126-sub.alexsun55.ru --acme-email rc-test@example.test
      --awg-subnet 10.88.31.0/30 --acme-test-directory https://10.77.5.2:14000/dir
      --acme-test-ca /tmp/preview06a-ca/ca.pem)
install_preview() {
  if [ -f /mnt/seed/preview.tar.gz ]; then
      sh ./install-preview.sh "${args[@]}" "$@"
  else
      sh ./bootstrap-preview.sh "$revision" "${args[@]}" "$@"
  fi
}
install_preview
echo PREVIEW06A_STANDALONE_INSTALL_PASS
nginx -t
XRAY=/opt/3xui-pro-fork/panel/bin/xray-linux-amd64
DATA=/var/lib/3xui-pro-fork
"$XRAY" run -test -config "$DATA/preview-xray.json"
for service in nginx 3xui-preview-xray.service 3xui-pro-fork.service 3xui-pro-fork-awg.service 3xui-preview-renew.timer; do
    systemctl is-active --quiet "$service"
done
ss -H -ltn 'sport = :443' | grep -F '10.77.5.1:443'
for port in 18443 19441 19444 2053 2096; do ss -H -ltn "sport = :$port" | grep -F "127.0.0.1:$port"; done
for port in 8443 9443; do ss -H -ltn "sport = :$port" | grep -F "10.77.5.1:$port"; done
python3 - <<'PY'
import subprocess
cert='/var/lib/3xui-preview-acme/config/live/3xui-preview/fullchain.pem'
text=subprocess.check_output(['openssl','x509','-in',cert,'-noout','-ext','subjectAltName'],text=True)
assert sorted(x.strip() for x in text.split('\n',1)[1].strip().split(','))==['DNS:de126-sub.alexsun55.ru','DNS:de126.alexsun55.ru']
print('PREVIEW06A_EXACT_TWO_SAN_PASS')
PY
test -z "$(ss -H -lun 'sport = :443')"
ss -H -lun 'sport = :29177' | grep -F ':29177'
cmp /var/www/3xui-pro-fork/decoy/index.html /mnt/seed/xonix.html
[[ $(stat -c '%U:%G %a' /var/www/3xui-pro-fork/decoy/index.html) == 'root:root 644' ]]
peer curl -fsS --cacert /tmp/preview06a-ca/root.pem https://de126.alexsun55.ru/ -o /tmp/preview06a-site
cmp /tmp/preview06a-site /mnt/seed/xonix.html
echo PREVIEW06A_EXTERNAL_HTTPS_XONIX_PASS
transport_test() {
    peer python3 /mnt/seed/transport.py "$XRAY" "$DATA/preview-xray-clients.json" \
        /tmp/preview06a-ca/pebble-cert.pem /tmp/preview06a-ca/pebble-key.pem \
        --p1-ca /tmp/preview06a-ca/root.pem
}
transport_test
systemctl restart 3xui-preview-xray.service
sleep 2
transport_test
echo PREVIEW06A_XRAY_EXTERNAL_RECONNECT_PASS
python3 /mnt/seed/web.py setup
install -d -m 0755 /var/www/3xui-pro-fork/decoy/.well-known/acme-challenge
printf 'synthetic-challenge\n' >/var/www/3xui-pro-fork/decoy/.well-known/acme-challenge/fixture
chmod 0644 /var/www/3xui-pro-fork/decoy/.well-known/acme-challenge/fixture
peer python3 /mnt/seed/web.py verify
python3 /mnt/seed/web.py logs
nginx -t
python3 - <<'PY'
from pathlib import Path
import sqlite3
with sqlite3.connect('/var/lib/3xui-pro-fork/x-ui.db') as db:
    db.execute('create table preview06a_sentinel (value text)')
    db.execute('insert into preview06a_sentinel values (?)', ('PRESERVE',))
Path('/etc/nginx/conf.d/77-preview06a-sentinel.conf').write_text('# unrelated sentinel\n')
Path('/var/www/html/preview06a-sentinel.html').write_text('Unrelated site content\n')
PY
managed=( "$DATA/preview-panel.json" "$DATA/preview-xray.json" "$DATA/preview-xray-clients.json" "$DATA/awg/client.conf" "$DATA/awg/server.setconf"
          /etc/nginx/conf.d/3xui-pro-fork-preview.conf
          /etc/nginx/modules-enabled/99-3xui-preview-stream.conf
          /etc/nginx/conf.d/77-preview06a-sentinel.conf /var/www/html/preview06a-sentinel.html
          /etc/systemd/system/3xui-preview-xray.service
          /etc/systemd/system/3xui-preview-renew.service
          /etc/systemd/system/3xui-preview-renew.timer
          /var/lib/3xui-preview-acme/config/live/3xui-preview/fullchain.pem
          /var/lib/3xui-preview-acme/config/live/3xui-preview/privkey.pem )
sha256sum "${managed[@]}" >/tmp/preview06a-before
install_preview
sha256sum --status -c /tmp/preview06a-before
python3 - <<'PY'
import sqlite3
with sqlite3.connect('/var/lib/3xui-pro-fork/x-ui.db') as db:
    assert db.execute('select value from preview06a_sentinel').fetchall() == [('PRESERVE',)]
    assert db.execute('pragma integrity_check').fetchone() == ('ok',)
PY
nginx -T 2>/dev/null | grep -c '^    map $ssl_preread_server_name $preview_backend {' | grep -qx 1
peer python3 /mnt/seed/web.py verify
python3 /mnt/seed/web.py logs
echo PREVIEW06A_REPEAT_INSTALL_PASS

awg=/opt/3xui-pro-fork/awg
conf=$DATA/awg
sed '/^Address = /d' "$conf/client.conf" >/tmp/preview06a-client.setconf
start_awg_client() {
    ip netns exec preview-client "$awg/amneziawg-go" -f awgclient >/tmp/preview06a-awg-client.log 2>&1 &
    client_pid=$!
    for _ in {1..100}; do
        [[ -S /var/run/amneziawg/awgclient.sock ]] && break
        kill -0 "$client_pid"
        sleep .1
    done
    peer "$awg/awg" setconf awgclient /tmp/preview06a-client.setconf
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
echo PREVIEW06A_AWG_UDP_BEFORE_RESTART_PASS
stop_awg_client
systemctl restart 3xui-pro-fork-awg.service
start_awg_client
ip addr show dev xproawg0 | grep -F 10.88.31.1/30
awg_traffic
sha256sum --status -c /tmp/preview06a-before
echo PREVIEW06A_AWG_UDP_RECONNECT_PASS

systemd-analyze verify /etc/systemd/system/3xui-preview-renew.service /etc/systemd/system/3xui-preview-renew.timer
lineage=/var/lib/3xui-preview-acme/config/live/3xui-preview
old_cert_sha=$(sha256sum "$lineage/fullchain.pem")
master=$(pgrep -xo nginx)
workers_before=$(pgrep -P "$master" | sort -n)
REQUESTS_CA_BUNDLE=/tmp/preview06a-ca/ca.pem certbot renew --force-renewal --non-interactive --no-random-sleep-on-renew \
    --cert-name 3xui-preview --no-directory-hooks \
    --config-dir /var/lib/3xui-preview-acme/config --work-dir /var/lib/3xui-preview-acme/work \
    --logs-dir /var/lib/3xui-preview-acme/logs --deploy-hook /var/lib/3xui-preview-acme/renew-deploy
test "$old_cert_sha" != "$(sha256sum "$lineage/fullchain.pem")"
for _ in {1..20}; do
    if [ "$workers_before" != "$(pgrep -P "$master" | sort -n)" ]; then break; fi
    sleep .5
done
test "$workers_before" != "$(pgrep -P "$master" | sort -n)"
peer curl -fsS --cacert /tmp/preview06a-ca/root.pem https://de126.alexsun55.ru/ -o /tmp/preview06a-renewed
cmp /mnt/seed/xonix.html /tmp/preview06a-renewed
echo PREVIEW06A_ACME_RENEWAL_RELOAD_PASS

if [ -f /mnt/seed/preview.tar.gz ]; then
    cp -a /tmp/preview06a /tmp/preview06a-fault
    python3 - <<'PY'
from pathlib import Path
path=Path('/tmp/preview06a-fault/release/preview_two_domain.py')
code=path.read_text()
old='    return config.encode()'
position=code.rindex(old)
path.write_text(code[:position]+code[position:].replace(old,r"    return (config + '\npreview06a_invalid_directive;\n').encode()"))
PY
    before_fault=$(sha256sum /etc/nginx/conf.d/3xui-pro-fork-preview.conf)
    if sh /tmp/preview06a-fault/install-preview.sh "${args[@]}" >/tmp/preview06a-fault.log 2>&1; then
        echo 'Fault injection incorrectly passed'
        exit 1
    fi
    grep -q 'unknown directive "preview06a_invalid_directive"' /tmp/preview06a-fault.log
    grep -q 'previous configuration restored' /tmp/preview06a-fault.log
    test "$before_fault" = "$(sha256sum /etc/nginx/conf.d/3xui-pro-fork-preview.conf)"
    nginx -t
    transport_test
    peer python3 /mnt/seed/web.py verify
    echo PREVIEW06A_NGINX_RECOVERY_PASS
fi
apt-get install -y -qq --no-install-recommends chromium nodejs
mkdir -m 700 /tmp/browser-node
tar -xzf /mnt/seed/browser.tgz -C /tmp/browser-node
peer env NODE_PATH=/tmp/browser-node PREVIEW_BROWSER_ADDRESS=10.77.5.1 PREVIEW_BROWSER_CA=/tmp/preview06a-ca/root.pem     node /mnt/seed/browser.cjs https://de126.alexsun55.ru/ "$lineage/fullchain.pem"
echo PREVIEW06A_BROWSER_PASS
stop_awg_client
echo PREVIEW06A_INTEGRATION_PASS
sleep 3
systemctl poweroff
