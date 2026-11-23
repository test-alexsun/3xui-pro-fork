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
export TMPDIR=/var/tmp
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
install_preview --panel-inbounds
echo PREVIEW07A_FRESH_NATIVE_INSTALL_PASS
nginx -t
XRAY=/opt/3xui-pro-fork/panel/bin/xray-linux-amd64
DATA=/var/lib/3xui-pro-fork
"$XRAY" run -test -config "$DATA/preview-xray.json"
for service in nginx 3xui-pro-fork.service 3xui-pro-fork-awg.service 3xui-preview-renew.timer; do
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
! systemctl is-active --quiet 3xui-preview-xray.service
test "$(systemctl is-enabled 3xui-preview-xray.service || :)" = disabled
echo PREVIEW07A_FRESH_NATIVE_READY
