#!/bin/bash
# Single two-scenario test for an isolated, already-installed Debian 13 VM.
set -Eeuo pipefail
umask 077
trap 'echo "BUILD05A_VM_FAIL line=$LINENO"; systemctl poweroff' ERR
[[ $(cat /proc/1/comm) == systemd && -c /dev/net/tun ]]
mkdir -m 700 /tmp/candidate
tar -xzf /mnt/seed/candidate.tar.gz -C /tmp/candidate
cd /tmp/candidate
systemctl is-active --quiet 3xui-pro-fork.service
systemctl is-active --quiet 3xui-pro-fork-awg.service
# Set test-only credentials and data while the owned panel is stopped.
systemctl stop 3xui-pro-fork.service
python3 - <<'PY'
import json,os,secrets,sqlite3,subprocess
from pathlib import Path
creds={'username':'fixture-'+secrets.token_hex(5),'password':secrets.token_urlsafe(24)}
path=Path('/root/prepare-health.json'); path.write_text(json.dumps(creds)); path.chmod(0o600)
extra=Path('/var/lib/3xui-pro-fork/fixture-config'); extra.mkdir(mode=0o700)
config=extra/'user.conf'; config.write_text('user-settings-preserved\n'); config.chmod(0o600)
runtime=Path('/opt/3xui-pro-fork/panel/bin/fixture-user-config.json')
runtime.write_text('{"fixture":true}\n'); runtime.chmod(0o600)
env={k:v for k,v in os.environ.items() if not k.startswith('XUI_')}
env.update(XUI_DB_FOLDER='/var/lib/3xui-pro-fork',XUI_DB_TYPE='sqlite',
           XUI_BIN_FOLDER='/opt/3xui-pro-fork/panel/bin',XUI_LOG_FOLDER='/var/log/3xui-pro-fork')
subprocess.run(['/opt/3xui-pro-fork/panel/x-ui','setting','-username',creds['username'],
                '-password',creds['password']],cwd='/opt/3xui-pro-fork/panel',env=env,
               check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
with sqlite3.connect('/var/lib/3xui-pro-fork/x-ui.db') as db:
 db.execute('CREATE TABLE IF NOT EXISTS build05a_fixture (value TEXT NOT NULL)')
 db.execute('DELETE FROM build05a_fixture')
 db.execute('INSERT INTO build05a_fixture VALUES (?)',('preserve-me',))
 db.commit()
PY
systemctl start 3xui-pro-fork.service
python3 - <<'PY'
from pathlib import Path
import prepare_candidate as p
p.await_health(Path('/root/prepare-health.json'))
print('PANEL_AND_AWG_PREFLIGHT_PASS')
PY
conf=/var/lib/3xui-pro-fork/awg
before=$(sha256sum "$conf/server.setconf" "$conf/client.conf" "$conf/metadata.json")
# Competing flock must be refused before service changes.
python3 - <<'PY'
import fcntl,os,subprocess
fd=os.open('/run/3xui-pro-fork-prepare.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
p=subprocess.run(['python3','install_candidate.py','--mode','prepare-upgrade',
                  '--health-credentials','/root/prepare-health.json'],capture_output=True,text=True,timeout=30)
assert p.returncode != 0 and 'PREPARE_LOCKED' in p.stderr
fcntl.flock(fd,fcntl.LOCK_UN); os.close(fd)
print('EXCLUSIVE_LOCK_REFUSAL_PASS')
PY
# Observe both systemd units actually inactive while the snapshot is taken.
python3 - <<'PY' & watcher=$!
import json,subprocess,time
from pathlib import Path
p=Path('/var/lib/3xui-pro-fork-transactions/current.json')
for _ in range(12000):
 try:
  state=json.loads(p.read_text())
  if state.get('phase')=='SNAPSHOTTING':
   for unit in ('3xui-pro-fork.service','3xui-pro-fork-awg.service'):
    r=subprocess.run(['systemctl','show',unit,'--property=ActiveState','--value'],capture_output=True,text=True,check=True)
    assert r.stdout.strip()=='inactive'
   Path('/run/prepare-observed').write_text('inactive')
   break
 except FileNotFoundError: pass
 time.sleep(.05)
else: raise SystemExit('snapshot phase not observed')
PY
python3 install_candidate.py --mode prepare-upgrade --health-credentials /root/prepare-health.json
wait "$watcher"
test "$(cat /run/prepare-observed)" = inactive
python3 - <<'PY'
import json,sqlite3
from pathlib import Path
import backup_candidate as b
state=json.loads(Path('/var/lib/3xui-pro-fork-transactions/current.json').read_text())
assert state['phase']=='PREPARED' and state['initial']=={'3xui-pro-fork.service':'active','3xui-pro-fork-awg.service':'active'}
events=[(v['phase'],v['unit']) for v in state['history']]
assert ('STOPPED','3xui-pro-fork.service') in events and ('STOPPED','3xui-pro-fork-awg.service') in events
assert ('SNAPSHOT_VERIFIED',None) in events
root=Path(state['backup']); manifest=b.verify_backup(root)
assert manifest['source_metadata']['units/3xui-pro-fork.service']['mode']==0o644
assert manifest['source_metadata']['awg/server.setconf']['mode']==0o600
assert manifest['source_metadata']['panel-data/fixture-config/user.conf']['mode']==0o600
assert (root/'panel-data/fixture-config/user.conf').read_text()=='user-settings-preserved\n'
assert (root/'components/panel/bin/fixture-user-config.json').read_text()=='{"fixture":true}\n'
assert manifest['source_metadata']['components/panel/bin/fixture-user-config.json']['mode']==0o600
runtime=Path('/opt/3xui-pro-fork/panel/bin/config.json')
if runtime.exists(): assert 'components/panel/bin/config.json' in manifest['files']
with sqlite3.connect(root/'database/x-ui.db') as db:
 assert db.execute('SELECT value FROM build05a_fixture').fetchone()==('preserve-me',)
print('COORDINATED_BACKUP_SQLITE_METADATA_PASS')
PY
[[ "$before" == "$(sha256sum "$conf/server.setconf" "$conf/client.conf" "$conf/metadata.json")" ]]
systemctl is-active --quiet 3xui-pro-fork.service
systemctl is-active --quiet 3xui-pro-fork-awg.service
# Inject a failure after a real file has been copied into an incomplete snapshot.
python3 - <<'PY'
import json,sqlite3
from pathlib import Path
from unittest.mock import patch
import backup_candidate,prepare_candidate
manifest=json.loads(Path('components-manifest.json').read_text())
root=Path('/var/backups/3xui-pro-fork')
before={p.name for p in root.iterdir()}
copy=backup_candidate.copy_private
def fail_after_copy(source,destination):
 copy(source,destination)
 raise OSError('controlled failure after a snapshot file')
try:
 with patch.object(backup_candidate,'copy_private',side_effect=fail_after_copy):
  prepare_candidate.prepare(manifest,Path('/root/prepare-health.json'))
except RuntimeError as exc:
 assert str(exc).startswith('PREPARE_FAILED_SERVICES_RECOVERED:'),str(exc)
else:
 raise AssertionError('injected failure was accepted')
state=json.loads(Path('/var/lib/3xui-pro-fork-transactions/current.json').read_text())
assert state['phase']=='FAILED_RECOVERED' and state['recovery_errors']==[]
assert state['stopped']==[] and set(state['recovery_confirmed_active'])=={
 '3xui-pro-fork.service','3xui-pro-fork-awg.service'}
created={p.name for p in root.iterdir()}-before
assert len(created)==1
partial=root/created.pop()
assert not (partial/'manifest.json').exists() and any(p.is_file() for p in partial.rglob('*'))
with sqlite3.connect('/var/lib/3xui-pro-fork/x-ui.db') as db:
 assert db.execute('SELECT value FROM build05a_fixture').fetchone()==('preserve-me',)
prepare_candidate.await_health(Path('/root/prepare-health.json'))
print('CONTROLLED_FAILURE_RECOVERY_AND_API_PASS')
PY
[[ "$before" == "$(sha256sum "$conf/server.setconf" "$conf/client.conf" "$conf/metadata.json")" ]]
# Pause the fixture only after the real atomic state write and directory fsync
# return. The foreign veth pair is a canary; the coordinator must not remove it.
binary_before=$(sha256sum /opt/3xui-pro-fork/panel/x-ui /opt/3xui-pro-fork/awg/amneziawg-go)
ip link add foreign05a type veth peer name peer05a
foreign_index=$(cat /sys/class/net/foreign05a/ifindex)
python3 - >/tmp/interrupted.log 2>&1 <<'PY' & prep_pid=$!
import hashlib,json,sqlite3,time
from pathlib import Path
import prepare_candidate as p
original=p.write_state
def gated(state):
 original(state)
 if state['phase']=='SNAPSHOTTING':
  h=hashlib.sha256()
  with sqlite3.connect('file:/var/lib/3xui-pro-fork/x-ui.db?mode=ro',uri=True) as db:
   for line in db.iterdump(): h.update(line.encode()+b'\n')
  Path('/run/fixture-db-digest').write_text(h.hexdigest())
  Path('/run/prepare-fsynced').write_text('ready')
  time.sleep(120)
p.write_state=gated
p.prepare(json.loads(Path('components-manifest.json').read_text()),Path('/root/prepare-health.json'))
PY
python3 - "$prep_pid" <<'PY'
import json,os,signal,sys,time
from pathlib import Path
pid=int(sys.argv[1]); p=Path('/var/lib/3xui-pro-fork-transactions/current.json')
for _ in range(12000):
 try:
  state=json.loads(p.read_text())
  if state.get('phase')=='SNAPSHOTTING' and Path('/run/prepare-fsynced').read_text()=='ready':
   assert [e['unit'] for e in state['history'] if e['phase']=='STOPPED']==[
       '3xui-pro-fork.service','3xui-pro-fork-awg.service']
   os.kill(pid,signal.SIGKILL)
   break
 except FileNotFoundError: pass
 time.sleep(.05)
else: raise SystemExit('snapshot phase not reached for interruption')
PY
if wait "$prep_pid" 2>/dev/null; then echo INTERRUPTION_DID_NOT_STOP_PROCESS; exit 1; fi
python3 - <<'PY'
import hashlib,json,sqlite3,subprocess
from pathlib import Path
p=Path('/var/lib/3xui-pro-fork-transactions/current.json')
raw=p.read_bytes(); state=json.loads(raw)
assert state['phase']=='SNAPSHOTTING'
assert state['initial']=={'3xui-pro-fork.service':'active','3xui-pro-fork-awg.service':'active'}
assert len(state['identities'])==2 and p.stat().st_mode & 0o077 == 0
run=subprocess.run(['python3','install_candidate.py','--mode','prepare-upgrade',
                    '--health-credentials','/root/prepare-health.json'],capture_output=True,text=True,timeout=30)
assert run.returncode != 0 and 'RECOVERY_REQUIRED' in run.stderr
assert p.read_bytes()==raw
with sqlite3.connect('file:/var/lib/3xui-pro-fork/x-ui.db?mode=ro',uri=True) as db:
 assert db.execute('PRAGMA integrity_check').fetchall()==[('ok',)]
 assert db.execute('SELECT value FROM build05a_fixture').fetchone()==('preserve-me',)
 h=hashlib.sha256()
 for line in db.iterdump(): h.update(line.encode()+b'\n')
 assert h.hexdigest()==Path('/run/fixture-db-digest').read_text()
print('INTERRUPTION_DURABLE_FAIL_CLOSED_PASS')
print('SQLITE_LOGICAL_CONTENT_AND_INTEGRITY_PASS')
PY
[[ "$binary_before" == "$(sha256sum /opt/3xui-pro-fork/panel/x-ui /opt/3xui-pro-fork/awg/amneziawg-go)" ]]
[[ "$foreign_index" == "$(cat /sys/class/net/foreign05a/ifindex)" ]]
echo AWG_KEYS_BINARIES_AND_FOREIGN_INTERFACE_PASS
systemctl start 3xui-pro-fork-awg.service
systemctl start 3xui-pro-fork.service
python3 - <<'PY'
from pathlib import Path
import prepare_candidate,sqlite3
prepare_candidate.await_health(Path('/root/prepare-health.json'))
with sqlite3.connect('file:/var/lib/3xui-pro-fork/x-ui.db?mode=ro',uri=True) as db:
 assert db.execute('PRAGMA integrity_check').fetchall()==[('ok',)]
 assert db.execute('SELECT value FROM build05a_fixture').fetchone()==('preserve-me',)
print('FIXTURE_MANUAL_SERVICE_RESTART_PASS')
PY
[[ "$before" == "$(sha256sum "$conf/server.setconf" "$conf/client.conf" "$conf/metadata.json")" ]]
[[ "$foreign_index" == "$(cat /sys/class/net/foreign05a/ifindex)" ]]
echo BUILD05A_VM_PASS
systemctl poweroff
