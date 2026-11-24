#!/bin/bash
set -Eeuo pipefail
umask 077
mkdir -p /var/www/3xui-pro-fork/decoy /tmp/nginx-run /tmp/acme/.well-known/acme-challenge
install -m 0644 /asset/index.html /var/www/3xui-pro-fork/decoy/index.html
printf 'private\n' >/var/www/3xui-pro-fork/decoy/.secret
printf 'acme-fixture\n' >/tmp/acme/.well-known/acme-challenge/token
chmod 755 /var/www/3xui-pro-fork/decoy /tmp/acme /tmp/acme/.well-known /tmp/acme/.well-known/acme-challenge
chmod 644 /var/www/3xui-pro-fork/decoy/index.html /var/www/3xui-pro-fork/decoy/.secret /tmp/acme/.well-known/acme-challenge/token
test "$(stat -c '%U:%G %a' /var/www/3xui-pro-fork/decoy/index.html)" = 'root:root 644'
test "$(stat -c '%U:%G %a' /var/www/3xui-pro-fork/decoy)" = 'root:root 755'
openssl req -x509 -newkey rsa:2048 -nodes -days 1 -subj /CN=localhost -keyout /tmp/key.pem -out /tmp/cert.pem >/dev/null 2>&1
cat >/tmp/nginx.conf <<'EOF'
pid /tmp/nginx-run/nginx.pid;
master_process off;
error_log /tmp/nginx-run/error.log;
events { worker_connections 64; }
http {
 access_log off;
 client_body_temp_path /tmp/nginx-run/client;
 proxy_temp_path /tmp/nginx-run/proxy;
 fastcgi_temp_path /tmp/nginx-run/fastcgi;
 uwsgi_temp_path /tmp/nginx-run/uwsgi;
 scgi_temp_path /tmp/nginx-run/scgi;
 server {
  listen 127.0.0.1:18080;
  listen 127.0.0.1:18443 ssl;
  ssl_certificate /tmp/cert.pem;
  ssl_certificate_key /tmp/key.pem;
  autoindex off;
  location ^~ /.well-known/acme-challenge/ { root /tmp/acme; try_files $uri =404; }
  location ^~ /api/ { return 418; }
  location ^~ /sub/ { return 419; }
  include /asset/nginx.conf;
 }
}
EOF
nginx -t -c /tmp/nginx.conf
nginx -c /tmp/nginx.conf
trap 'nginx -s quit -c /tmp/nginx.conf >/dev/null 2>&1 || :' EXIT
python3 - <<'PY'
import http.client,ssl
asset=open('/asset/index.html','rb').read()
def get(port,path):
 c=http.client.HTTPSConnection('127.0.0.1',port,context=ssl._create_unverified_context(),timeout=5) if port==18443 else http.client.HTTPConnection('127.0.0.1',port,timeout=5)
 c.request('GET',path); r=c.getresponse(); data=r.read(); c.close(); return r.status,data
for port in (18080,18443):
 assert get(port,'/')==(200,asset)
 assert get(port,'/missing-file')[0]==404
 assert get(port,'/.secret')[0]==404
 assert get(port,'/api/missing')[0]==418
 assert get(port,'/sub/missing')[0]==419
 assert get(port,'/.well-known/acme-challenge/token')==(200,b'acme-fixture\n')
print('SYNTHETIC_NGINX_HTTP_HTTPS_AND_ROUTE_FIXTURES_PASS')
PY
