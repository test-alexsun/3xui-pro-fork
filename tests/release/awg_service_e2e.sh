#!/bin/bash
# Disposable-container fixture. The container and namespaces are the cleanup boundary.
set -Eeuo pipefail
umask 077
[[ -f /.dockerenv && -c /dev/net/tun && $(ip -o link show | wc -l) == 1 ]] || exit 2
mkdir -p /opt/3xui-pro-fork/awg /var/lib/3xui-pro-fork
cp /binaries/awg /binaries/amneziawg-go /fixture/awg_service.py /opt/3xui-pro-fork/awg/
chmod 700 /opt/3xui-pro-fork/awg/{awg,amneziawg-go,awg_service.py}
python3 /fixture/awg_config_candidate.py --awg /opt/3xui-pro-fork/awg/awg --output /var/lib/3xui-pro-fork/awg --endpoint-host 192.0.2.1 --port 29177 --subnet 10.88.31.0/30
conf=/var/lib/3xui-pro-fork/awg
before=$(sha256sum "$conf/server.setconf" "$conf/client.conf")
ip netns add client
ip link add underlay0 type veth peer name underlay1
ip link set underlay1 netns client
ip addr add 192.0.2.1/30 dev underlay0
ip link set underlay0 up
ip -n client addr add 192.0.2.2/30 dev underlay1
ip -n client link set underlay1 up
ip -n client link set lo up
ip netns exec client /opt/3xui-pro-fork/awg/amneziawg-go -f awgclient >/tmp/client.log 2>&1 &
client_pid=$!
server_pid=
trap '[[ -z $server_pid ]] || kill "$server_pid" 2>/dev/null || :; kill "$client_pid" 2>/dev/null || :' EXIT
for _ in {1..100}; do [[ -S /var/run/amneziawg/awgclient.sock ]] && break; sleep .1; done
sed '/^Address = /d' "$conf/client.conf" >/tmp/client.setconf
ip netns exec client /opt/3xui-pro-fork/awg/awg setconf awgclient /tmp/client.setconf
ip -n client addr add 10.88.31.2/30 dev awgclient
ip -n client link set awgclient up
start_server() {
  WG_UAPI_FD=123 python3 /opt/3xui-pro-fork/awg/awg_service.py >/tmp/server.log 2>&1 & server_pid=$!
  for _ in {1..100}; do
    kill -0 "$server_pid" || { cat /tmp/server.log; exit 1; }
    grep -q 'AWG interface ready' /tmp/server.log && return
    sleep .1
  done
  echo SERVER_NOT_READY; exit 1
}
traffic() {
  echo TRAFFIC_CHECK_STARTED
  python3 -c 'import socket; s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); s.bind(("10.88.31.1",9999)); s.settimeout(150); d,a=s.recvfrom(100); assert d==b"request"; s.sendto(b"response",a)' & local echo_pid=$!
  sleep .5
  if ! ip netns exec client python3 -c 'import socket; s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); s.settimeout(1)
for attempt in range(140):
 s.sendto(b"request",("10.88.31.1",9999))
 try:
  d,_=s.recvfrom(100); assert d==b"response"; break
 except TimeoutError: pass
else: raise SystemExit("tunnel did not reconnect")'; then
    ip -br addr; ip -n client -br addr; cat /tmp/server.log
    /opt/3xui-pro-fork/awg/awg show xproawg0 transfer | awk '{print "server rx/tx", $2, $3}'
    ip netns exec client /opt/3xui-pro-fork/awg/awg show awgclient transfer | awk '{print "client rx/tx", $2, $3}'
    exit 1
  fi
  wait "$echo_pid"
  /opt/3xui-pro-fork/awg/awg show xproawg0 latest-handshakes | awk '$2 > 0 {found=1} END {exit !found}'
}
start_server
if python3 /opt/3xui-pro-fork/awg/awg_service.py >/tmp/duplicate.log 2>&1; then echo DUPLICATE_ACCEPTED; exit 1; fi
traffic
kill "$server_pid"; wait "$server_pid"; server_pid=
if ip link show dev xproawg0 >/dev/null 2>&1; then echo INTERFACE_STILL_PRESENT; exit 1; fi
start_server
traffic
kill "$server_pid"; wait "$server_pid"; server_pid=
[[ "$before" == "$(sha256sum "$conf/server.setconf" "$conf/client.conf")" ]]
# An existing foreign TUN must not be attached to, modified, or deleted.
ip tuntap add dev xproawg0 mode tun
if python3 /opt/3xui-pro-fork/awg/awg_service.py >/tmp/conflict.log 2>&1; then echo FOREIGN_INTERFACE_ACCEPTED; exit 1; fi
ip link show dev xproawg0 >/dev/null
echo AWG_CONTROLLER_E2E_PASS
