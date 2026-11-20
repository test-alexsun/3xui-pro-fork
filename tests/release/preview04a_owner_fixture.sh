#!/bin/sh
set -eu
mkdir -p /tmp/pkg /tmp/panel-data /tmp/panel-log
tar -xzf /candidate.tar.gz -C /tmp/pkg
export XUI_DB_FOLDER=/tmp/panel-data XUI_DB_TYPE=sqlite XUI_BIN_FOLDER=/tmp/pkg/panel/bin XUI_LOG_FOLDER=/tmp/panel-log
cd /tmp/pkg/panel
./x-ui setting -listenIP 127.0.0.1 -port 2053 >/dev/null
python3 - <<'PY'
import sqlite3
with sqlite3.connect('/tmp/panel-data/x-ui.db') as db:
 rows={'subEnable':'true','subListen':'127.0.0.1','subPort':'12996',
       'subPath':'/fixture/','subURI':'https://example.test:18443/fixture/',
       'subJsonEnable':'false','subClashEnable':'false','subCertFile':'',
       'subKeyFile':'','subDomain':'','subJsonURI':'','subClashURI':''}
 for key,value in rows.items():
  db.execute('delete from settings where key=?',(key,))
  db.execute('insert into settings(key,value) values(?,?)',(key,value))
PY
./x-ui >/tmp/panel.log 2>&1 &
panel_pid=$!
trap 'kill "$panel_pid" 2>/dev/null || :' EXIT
python3 - "$panel_pid" <<'PY'
import socket,sys,time
for _ in range(60):
 try:
  with socket.create_connection(('127.0.0.1',12996),timeout=.5): break
 except OSError: time.sleep(.5)
else: raise SystemExit('fixture subscription listener unavailable')
sys.path.insert(0,'/preview/release')
import preview_install as p
result=p.subscription_config(p.Path('/tmp/panel-data/x-ui.db'),'example.test',int(sys.argv[1]))
assert result=={'port':12996,'paths':['/fixture/']}
try: p.subscription_config(p.Path('/tmp/panel-data/x-ui.db'),'example.test',int(sys.argv[1])+1)
except RuntimeError as e: assert 'not owned' in str(e)
else: raise AssertionError('foreign PID accepted')
import urllib.error,urllib.request
canary='synthetic-secret-canary-04a'
try: urllib.request.urlopen('http://127.0.0.1:12996/fixture/'+canary, timeout=5).read()
except urllib.error.HTTPError: pass
time.sleep(.5)
assert canary not in p.Path('/tmp/panel.log').read_text(errors='replace'), 'subscription token appeared in panel log'
print('REAL_PANEL_SUBSCRIPTION_OWNER_AND_LOG_PASS')
PY
