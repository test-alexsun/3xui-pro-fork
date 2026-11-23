"""Reproduce the measured one-way PMTU blackhole in disposable namespaces only."""
import os
os.umask(0o077)
from pathlib import Path
import hashlib
import json
import os
import subprocess
import tempfile
import time

assert json.loads(Path('/var/lib/3xui-pro-fork/preview-web.json').read_text())['public_address']=='10.77.5.1', 'LAB ONLY'
C,R,S='pmtu07ac','pmtu07ar','pmtu07as'
existing=subprocess.check_output(['ip','netns','list'],text=True)
assert not any(n in existing for n in [C,R,S])
work=Path(tempfile.mkdtemp(prefix='preview07a-pmtu-'));processes=[];created=[]
GO='/opt/3xui-pro-fork/awg/amneziawg-go';AWG='/opt/3xui-pro-fork/awg/awg';probe=str(Path(__file__).with_name('awg_pmtu_probe.py'))
def run(*args):return subprocess.run(args,check=True,capture_output=True,text=True).stdout
def net(ns,*args):return run('ip','netns','exec',ns,*args)
def link(ns,*args):return run('ip','-n',ns,*args)
def start(ns,interface,config,address,mtu=1420):
    with (work/(interface+'.log')).open('w') as log:
        child=subprocess.Popen(['ip','netns','exec',ns,GO,'-f',interface],stdout=log,stderr=log)
    processes.append(child)
    for _ in range(100):
        assert child.poll() is None,'lab AWG exited'
        if Path('/var/run/amneziawg/'+interface+'.sock').exists():break
        time.sleep(.05)
    net(ns,AWG,'setconf',interface,str(config));link(ns,'addr','add',address,'dev',interface);link(ns,'link','set',interface,'mtu',str(mtu));link(ns,'link','set',interface,'up')
    return child
def matrix(label):
    server=subprocess.Popen(['ip','netns','exec',S,'python3',probe,'server','--bind','10.89.31.1','--client','10.89.31.2','--interfaces','s0','pmtus7a','--peer','198.51.100.10','--duration','90'],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    assert server.stdout.readline().decode().strip()=='PMTU_SERVER_READY'
    result=subprocess.run(['ip','netns','exec',C,'python3',probe,'client','--bind','10.89.31.1','--client','10.89.31.2','--interfaces','c0','pmtuc7a','--peer','192.0.2.10','--trials','3','--timeout','.35','--output',str(work/(label+'-client.json'))],capture_output=True)
    stdout,stderr=server.communicate(timeout=95)
    (work/(label+'-stderr.log')).write_bytes(result.stderr+stderr)
    assert result.returncode==0 and server.returncode==0,'lab matrix failed'
    server_data=json.loads(stdout);(work/(label+'-server.json')).write_text(json.dumps(server_data))
    data=json.loads((work/(label+'-client.json')).read_text())
    summary={size:{d:sum(r['received'] for r in data['results'] if r['payload_bytes']==size and r['direction']==d) for d in ['client_to_server','server_to_client']} for size in data['sizes']}
    maximum=max(x['ip_bytes'] for x in data['capture'] if x['interface']=='c0' and x['direction']=='outgoing' and x['protocol']==17)
    return {'matrix':summary,'maximum_client_outer_ip_bytes':maximum,'client_counter_delta':data['counter_delta'],'server_counter_delta':server_data['counter_delta']}
try:
    for ns in [C,R,S]:run('ip','netns','add',ns);created.append(ns);link(ns,'link','set','lo','up')
    for a,b,na,nb in [('c0','rc0',C,R),('rs0','s0',R,S)]:
        run('ip','link','add',a,'type','veth','peer','name',b);run('ip','link','set',a,'netns',na);run('ip','link','set',b,'netns',nb)
    for ns,iface,address in [(C,'c0','198.18.1.2/30'),(R,'rc0','198.18.1.1/30'),(R,'rs0','198.18.2.1/30'),(S,'s0','198.18.2.2/30')]:
        link(ns,'addr','add',address,'dev',iface);link(ns,'link','set',iface,'mtu','1500');link(ns,'link','set',iface,'up')
    link(C,'addr','add','198.51.100.10/32','dev','lo');link(S,'addr','add','192.0.2.10/32','dev','lo')
    link(C,'route','add','192.0.2.10/32','via','198.18.1.1','src','198.51.100.10')
    link(R,'route','add','198.51.100.10/32','via','198.18.1.2');link(R,'route','add','192.0.2.10/32','via','198.18.2.2','mtu','1440')
    link(S,'route','add','198.51.100.10/32','via','198.18.2.1','src','192.0.2.10')
    net(R,'sysctl','-w','net.ipv4.ip_forward=1')
    # Reproduce the observed lost feedback to the container behind the external VPN/NAT.
    net(R,'iptables','-A','OUTPUT','-p','icmp','--icmp-type','fragmentation-needed','-j','DROP')
    run('python3','/tmp/preview06a/release/awg_config_candidate.py','--awg',AWG,'--output',str(work/'keys'),'--endpoint-host','192.0.2.10','--port','29177','--subnet','10.89.31.0/30')
    client_config=work/'client.setconf';client_config.write_text('\n'.join(l for l in (work/'keys/client.conf').read_text().splitlines() if not l.startswith('Address = '))+'\n')
    original={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (work/'keys').iterdir()}
    server=start(S,'pmtus7a',work/'keys/server.setconf','10.89.31.1/30');client=start(C,'pmtuc7a',client_config,'10.89.31.2/30')
    baseline=matrix('baseline')
    assert all(v['client_to_server']==(3 if size<=1280 else 0) and v['server_to_client']==3 for size,v in baseline['matrix'].items()),'baseline differs from measured production path'
    link(C,'link','set','pmtuc7a','mtu','1368')
    fixed=matrix('fixed')
    assert all(v=={'client_to_server':3,'server_to_client':3} for v in fixed['matrix'].values())
    assert fixed['maximum_client_outer_ip_bytes']<=1440
    for child in [client,server]:child.terminate();child.wait(timeout=10)
    for _ in range(100):
        if not Path('/var/run/amneziawg/pmtuc7a.sock').exists() and not Path('/var/run/amneziawg/pmtus7a.sock').exists():break
        time.sleep(.05)
    server=start(S,'pmtus7a',work/'keys/server.setconf','10.89.31.1/30');client=start(C,'pmtuc7a',client_config,'10.89.31.2/30',1368)
    restarted=matrix('restarted');assert all(v=={'client_to_server':3,'server_to_client':3} for v in restarted['matrix'].values())
    assert original=={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (work/'keys').iterdir()}
    result={'status':'PASS','route_mtu_client_to_server':1440,'server_to_client_mtu':1500,'s4':12,'outer_overhead_ipv4':72,'derived_client_tun_mtu':1368,'baseline':baseline,'fixed':fixed,'after_restart':restarted,'keys_preserved':True,'work':str(work)}
    Path('/tmp/preview07a-lab-pmtu-results.json').write_text(json.dumps(result,indent=2));print(json.dumps(result),flush=True)
finally:
    for child in reversed(processes):
        if child.poll() is None:child.terminate();child.wait(timeout=10)
    for ns in reversed(created):run('ip','netns','delete',ns)
