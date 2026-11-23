"""Opt-in native panel ownership of strict P0/P1/P3. No automatic production migration."""
import base64
import copy
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import subprocess
import time
import urllib.parse

import preview_transport as transport
import preview_two_domain as two
from preview_panel_api import PanelAPI, PanelAPIError
import upgrade_candidate as ownership

DATA=Path('/var/lib/3xui-pro-fork')
STATE=DATA/'preview-panel-inbounds.json'
WEB_STATE=DATA/'preview-web.json'
CORE=Path('/opt/3xui-pro-fork/panel/bin/config.json')
PANEL_UNIT='3xui-pro-fork.service'
TAGS={'P0':'VLESS-REALITY-XHTTP-H2','P1':'VLESS-TLS-XHTTP-H2','P3':'VLESS-REALITY-VISION'}
TERMINAL={'READY','ROLLED_BACK'}
PHASES=TERMINAL|{'PREPARING','STAGING','STAGED','STOPPING_STANDALONE','ACTIVATING_NATIVE','ROLLING_BACK','RECOVERY_REQUIRED'}

def object_value(value):
    for _ in range(3):
        if isinstance(value,dict):return value
        if not isinstance(value,str):break
        value=json.loads(value)
    raise RuntimeError('unsupported panel JSON object')

def private_json(path):
    ownership.regular_root_file(path,private=True)
    return json.loads(path.read_text())

def journal_value(value):
    if not isinstance(value,dict) or value.get('version')!=1 or value.get('phase') not in PHASES:
        raise RuntimeError('RECOVERY_REQUIRED: unsupported native transition journal')
    profiles=value.get('profiles')
    if not isinstance(profiles,dict) or not set(profiles)<=set(TAGS) or any(type(v) is not int or v<1 for v in profiles.values()):
        raise RuntimeError('RECOVERY_REQUIRED: invalid native profile registry')
    if len(set(profiles.values()))!=len(profiles):
        raise RuntimeError('RECOVERY_REQUIRED: duplicate native profile identity')
    if value['phase']=='READY' and set(profiles)!=set(TAGS):
        raise RuntimeError('RECOVERY_REQUIRED: incomplete native profile registry')
    return value

def read_journal():return journal_value(private_json(STATE))

def command(*args):
    try:return subprocess.check_output(args,text=True,stderr=subprocess.PIPE,timeout=30)
    except (OSError,subprocess.SubprocessError):
        raise RuntimeError('owned component command failed; output withheld') from None

def api_client():return PanelAPI(private_json(two.PANEL_STATE))

def requested(args):
    selected=getattr(args,'panel_inbounds',False)
    explicit=getattr(args,'migrate_panel_inbounds',False)
    if explicit and not selected:raise RuntimeError('--migrate-panel-inbounds requires --panel-inbounds')
    if selected and not args.layout:raise RuntimeError('panel inbounds require strict two-domain mode')
    journal=read_journal() if STATE.exists() or STATE.is_symlink() else None
    if journal and journal.get('phase') not in TERMINAL:
        raise RuntimeError('RECOVERY_REQUIRED: incomplete native panel transition; inspect private journal')
    if journal and journal['phase']=='READY' and not selected:
        raise RuntimeError('native deployment requires --panel-inbounds; automatic reversal refused')
    if selected and WEB_STATE.exists() and not (journal and journal['phase']=='READY') and not explicit:
        raise RuntimeError('existing standalone requires explicit --migrate-panel-inbounds')
    return bool(journal and journal['phase']=='READY')

def source_snapshot(web_state=None):
    web=private_json(WEB_STATE) if web_state is None else web_state
    if web.get('phase')!='READY' or not web.get('sandbox') or not web.get('layout'):
        raise RuntimeError('strict TLS READY installation required for native staging')
    for key,(path,mode) in transport.FILES.items():
        ownership.regular_root_file(path,private=mode==0o600)
        if path.stat().st_mode&0o777!=mode or hashlib.sha256(path.read_bytes()).hexdigest()!=web.get('transport',{}).get(key):
            raise RuntimeError('standalone transport ownership differs')
    return web,private_json(transport.CONFIG),private_json(transport.CLIENTS)

def blueprints(config,clients,domain):
    inbounds=config.get('inbounds',[])
    if len(inbounds)!=3 or {i.get('tag') for i in inbounds}!=set(TAGS):
        raise RuntimeError('exact standalone P0/P1/P3 required')
    if len({i.get('port') for i in inbounds})!=3:
        raise RuntimeError('duplicate standalone listener refused')
    result={};people={}
    for original in inbounds:
        profile=original['tag'];stream=copy.deepcopy(original['streamSettings'])
        if original['protocol']!='vless' or original['settings'].get('decryption')!='none':
            raise RuntimeError('unsupported standalone protocol')
        if profile=='P3':
            if stream.get('network') not in ('raw','tcp'):raise RuntimeError('Vision requires raw/TCP')
            stream['network']='tcp' # Native flow/subscription capability uses the equivalent TCP alias.
        elif stream.get('network')!='xhttp' or stream.get('xhttpSettings',{}).get('mode')!='stream-up':
            raise RuntimeError('XHTTP stream-up required')
        if profile in ('P0','P3'):
            if stream.get('security')!='reality':raise RuntimeError('REALITY required')
            stream['realitySettings']['settings']={'publicKey':clients[profile]['outbounds'][0]['streamSettings']['realitySettings']['password'],'fingerprint':'chrome','spiderX':'/'}
        else:
            if stream.get('security')!='none' or original.get('listen')!='127.0.0.1':raise RuntimeError('P1 must remain loopback H2 behind TLS Nginx')
            stream['externalProxy']=[{'forceTls':'tls','dest':domain,'port':443,'sni':domain,'alpn':['h2'],'fingerprint':'chrome'}]
        result[profile]={'tag':TAGS[profile],'remark':TAGS[profile],'enable':False,'listen':original['listen'],'port':original['port'],'protocol':'vless','settings':{'clients':[],'decryption':'none'},'streamSettings':stream,'sniffing':{'enabled':False,'destOverride':[]},'shareAddrStrategy':'custom','shareAddr':domain,'disableFlow':False,'expiryTime':0,'up':0,'down':0,'total':0}
        for user in original['settings']['clients']:
            if not user.get('id') or not user.get('email'):raise RuntimeError('standalone client identity missing')
            email=user['email'];entry=people.get(email)
            if entry and entry['client']['id']!=user['id']:raise RuntimeError('ambiguous standalone client identity')
            if not entry:
                client={'id':user['id'],'email':email,'enable':True,'expiryTime':0,'totalGB':0,'subId':secrets.token_urlsafe(24)}
                entry=people[email]={'client':client,'profiles':[]}
            if profile=='P3':
                if user.get('flow')!='xtls-rprx-vision':raise RuntimeError('existing Vision flow required')
                entry['client']['flow']='xtls-rprx-vision'
            entry['profiles'].append(profile)
    return result,people

def core_api(operation,*flags):
    config=private_json(CORE)
    matches=[i for i in config['inbounds'] if i.get('tag')=='api' and i.get('listen')=='127.0.0.1']
    if len(matches)!=1:raise RuntimeError('native loopback API not identifiable')
    return json.loads(command(str(transport.XRAY),'api',operation,'-server=127.0.0.1:'+str(matches[0]['port']),*flags))

def listener_pids(port):
    text=command('ss','-H','-ltnp','sport = :'+str(port))
    if not text.strip():return set()
    pids={int(x) for x in re.findall(r'pid=(\d+)',text)}
    if not pids:raise RuntimeError('unidentified listener refused')
    return pids

def native_pid():
    props=ownership.service_properties(PANEL_UNIT);parent=int(props.get('MainPID','0'))
    if props.get('ActiveState')!='active' or not parent:raise RuntimeError('owned panel not active')
    candidates=[]
    for p in Path('/proc').iterdir():
        if not p.name.isdigit():continue
        try:
            info=(p/'stat').read_text().split(') ',1)[1].split()
            if int(info[1])==parent and os.readlink(p/'exe')==str(transport.XRAY):candidates.append(int(p.name))
        except (FileNotFoundError,ProcessLookupError):pass
    if len(candidates)!=1:raise RuntimeError('exactly one native panel Xray child required')
    return candidates[0]

def equivalent_network(network):return {'raw':'tcp','splithttp':'xhttp'}.get(network,network)

def binary_value(value):
    if isinstance(value,list) and all(type(v) is int and 0<=v<=255 for v in value):return bytes(value)
    if isinstance(value,str):return base64.urlsafe_b64decode(value+'='*(-len(value)%4))
    raise RuntimeError('unsupported native binary setting')

def validate_live_transport(actual,want):
    stream=want['streamSettings']
    if stream['security']=='reality':
        security=[x for x in actual.get('securitySettings',[]) if x.get('_TypedMessage_')=='xray.transport.internet.reality.Config']
        if len(security)!=1:raise RuntimeError('native REALITY runtime settings missing')
        live=security[0];expected=stream['realitySettings']
        if binary_value(live.get('privateKey'))!=binary_value(expected['privateKey']):raise RuntimeError('native REALITY runtime key differs')
        if [binary_value(x) for x in live.get('shortIds',[])]!=[bytes.fromhex(x).ljust(8,b'\0') for x in expected['shortIds']]:raise RuntimeError('native REALITY runtime short IDs differ')
        if live.get('dest')!=expected.get('target') or sorted(live.get('serverNames',[]))!=sorted(expected['serverNames']):raise RuntimeError('native REALITY runtime target/SNI differs')
    if stream['network']=='xhttp':
        transports=[x.get('settings',{}) for x in actual.get('transportSettings',[]) if equivalent_network(x.get('protocolName'))=='xhttp']
        if len(transports)!=1 or any(transports[0].get(k)!=stream['xhttpSettings'][k] for k in ('host','path','mode')):raise RuntimeError('native XHTTP runtime settings differ')

def validate_live(api,registry,blueprint):
    entries={item['id']:item for item in api.call('inbounds/list') or []}
    live={item['tag']:item for item in core_api('lsi','-isOnlyTags=false').get('inbounds',[])}
    pid=native_pid();now=int(time.time()*1000)
    for profile,identity in registry.items():
        item=entries.get(identity);want=blueprint[profile]
        if not item or item.get('tag')!=want['tag']:raise RuntimeError('managed native inbound missing or identity changed')
        if any(item.get(k)!=want[k] for k in ('port','listen','protocol')):raise RuntimeError('native ingress identity changed')
        stream=object_value(item['streamSettings']);settings=object_value(item['settings'])
        if equivalent_network(stream.get('network'))!=want['streamSettings']['network'] or stream.get('security')!=want['streamSettings']['security']:
            raise RuntimeError('native transport differs')
        if profile in ('P0','P3'):
            reality=stream['realitySettings'];expected=want['streamSettings']['realitySettings']
            if any(reality.get(k)!=expected.get(k) for k in ('target','privateKey','shortIds','serverNames')):raise RuntimeError('managed REALITY identity changed')
        else:
            if item.get('disableFlow'):raise RuntimeError('unexpected P1 flow policy')
            if stream.get('externalProxy')!=want['streamSettings']['externalProxy']:
                raise RuntimeError('managed P1 public TLS subscription endpoint changed')
        if profile in ('P0','P1'):
            if any(stream.get('xhttpSettings',{}).get(k)!=want['streamSettings']['xhttpSettings'][k] for k in ('host','path','mode')):
                raise RuntimeError('managed XHTTP layout changed')
        if not item.get('enable'):
            if want['tag'] in live or listener_pids(want['port']):raise RuntimeError('disabled native inbound still listening')
            continue
        handler=live.get(want['tag'])
        if not handler:raise RuntimeError('native runtime inbound not applied')
        receiver=handler.get('receiverSettings',{});actual=receiver.get('streamSettings',{})
        if receiver.get('listen')!=want['listen'] or receiver.get('portList')!=want['port'] or equivalent_network(actual.get('protocolName'))!=want['streamSettings']['network']:
            raise RuntimeError('native runtime listener/transport differs')
        security=actual.get('securityType') or 'none'
        security={'xray.transport.internet.reality.Config':'reality','xray.transport.internet.tls.Config':'tls'}.get(security,security)
        if security!=want['streamSettings']['security']:
            raise RuntimeError('native runtime security differs')
        validate_live_transport(actual,want)
        if listener_pids(want['port'])!={pid}:raise RuntimeError('native listener owner differs')
        expected=set()
        for user in settings.get('clients',[]):
            expiry=user.get('expiryTime',0)
            if user.get('enable') and (not expiry or expiry<0 or expiry>now):expected.add((user['id'],user.get('flow',''),user['email']))
        users=core_api('inbounduser','-tag='+want['tag']).get('users',[])
        active={(u['account']['id'],u['account'].get('flow',''),u['email']) for u in users}
        if active!=expected:raise RuntimeError('native DB/live client inconsistency')
    return True

def wait_live(api,registry,blueprint):
    until=time.monotonic()+18
    while time.monotonic()<until:
        try:return validate_live(api,registry,blueprint)
        except (RuntimeError,ValueError,KeyError):time.sleep(.2)
    raise RuntimeError('native apply readiness failed; configuration not accepted as ready')

def verify_ready(web_state=None):
    journal=read_journal()
    if journal.get('phase')!='READY':raise RuntimeError('RECOVERY_REQUIRED: native transition incomplete')
    web,source,clients=source_snapshot(web_state)
    blueprint,_=blueprints(source,clients,web['domain'])
    if journal.get('identity')!={'domain':web['domain'],'address':web['public_address'],'layout':web['layout']}:
        raise RuntimeError('native deployment identity differs')
    if ownership.service_properties(transport.UNIT.name).get('ActiveState')!='inactive':
        raise RuntimeError('standalone Xray must remain inactive in native mode')
    return wait_live(api_client(),journal['profiles'],blueprint)

def configure_lab_origin(api,origin):
    if not origin:return
    if not ipaddress.ip_address(origin).is_private:raise RuntimeError('private ACME lab origin required')
    result=object_value(api.call('xray/',{}));template=object_value(result['xraySetting'])
    for outbound in template['outbounds']:
        if outbound.get('protocol')=='freedom' and outbound.get('tag')=='direct':
            outbound['settings']={'finalRules':[{'action':'allow','network':'tcp','port':18099,'ip':[origin+'/32']}]}
    rule={'type':'field','inboundTag':list(TAGS.values()),'ip':[origin+'/32'],'port':18099,'network':'tcp','outboundTag':'direct'}
    if rule not in template['routing']['rules']:template['routing']['rules'].insert(0,rule)
    api.call('xray/update',{'xraySetting':json.dumps(template),'outboundTestUrl':result.get('outboundTestUrl','')},form=True)

def migrate(manifest,atomic,test_origin=None):
    if STATE.exists() and read_journal().get('phase')=='READY':return verify_ready()
    ownership.inspect_installed(manifest)
    web,source,clients=source_snapshot();blueprint,people=blueprints(source,clients,web['domain']);api=api_client()
    existing=api.call('inbounds/list') or [];existing_clients=api.call('clients/list') or []
    for entry in existing:
        if entry.get('tag') in TAGS.values() or entry.get('port') in {p['port'] for p in blueprint.values()}:raise RuntimeError('existing panel inbound conflicts; adoption refused')
    for entry in existing_clients:
        record=entry.get('client',entry)
        if any(str(record.get('email','')).casefold()==email.casefold() or str(record.get('uuid','')).lower()==person['client']['id'].lower() for email,person in people.items()):raise RuntimeError('existing panel client conflicts; adoption refused')
    props=ownership.service_properties(transport.UNIT.name)
    if props.get('ActiveState')!='active' or props.get('FragmentPath')!=str(transport.UNIT) or props.get('DropInPaths') or props.get('NeedDaemonReload')!='no':raise RuntimeError('standalone unit ownership differs')
    old_pid=int(props['MainPID']);old_start=Path('/proc/'+str(old_pid)+'/stat').read_text().split(') ',1)[1].split()[19]
    for item in source['inbounds']:
        if listener_pids(item['port'])!={old_pid}:raise RuntimeError('standalone listener ownership differs')
    previous_enabled=command('systemctl','is-enabled',transport.UNIT.name).strip()
    backups=DATA/'preview-panel-migration-backups';backups.mkdir(mode=0o700,exist_ok=True);ownership.root_dir(backups,private=True)
    backup=backups/('before-'+secrets.token_hex(8));backup.mkdir(mode=0o700)
    atomic(backup/'web-state.json',WEB_STATE.read_bytes(),0o600)
    with sqlite3.connect((DATA/'x-ui.db').as_uri()+'?mode=ro',uri=True) as db,sqlite3.connect(backup/'x-ui.db') as target:db.backup(target)
    os.chmod(backup/'x-ui.db',0o600)
    with sqlite3.connect((backup/'x-ui.db').as_uri()+'?mode=ro',uri=True) as db:
        if db.execute('pragma integrity_check').fetchone()!=('ok',):raise RuntimeError('native backup integrity failed')
    journal={'version':1,'phase':'PREPARING','identity':{'domain':web['domain'],'address':web['public_address'],'layout':web['layout']},'profiles':{},'clients':people,'backup':str(backup),'previous_enabled':previous_enabled,'history':[]}
    def phase(value):
        journal['phase']=value;journal['history'].append({'phase':value,'time':int(time.time())});atomic(STATE,(json.dumps(journal)+'\n').encode(),0o600)
    phase('PREPARING');stopped=False;previous_template=None
    try:
        if test_origin:
            previous_template=object_value(api.call('xray/',{}))
            atomic(backup/'xray-template.json',(json.dumps(previous_template)+'\n').encode(),0o600)
        configure_lab_origin(api,test_origin)
        for profile,payload in blueprint.items():
            item=api.call('inbounds/add',payload);journal['profiles'][profile]=item['id'];phase('STAGING')
            if item.get('tag')!=payload['tag']:raise RuntimeError('native inbound tag differs')
        for email,person in people.items():
            person['inboundIds']=[journal['profiles'][p] for p in person['profiles']]
            person['create_requested']=True;phase('STAGING')
            api.call('clients/add',{'client':person['client'],'inboundIds':person['inboundIds']});person['created']=True;phase('STAGING')
        phase('STAGED')
        ownership.inspect_installed(manifest);source_snapshot()
        current=ownership.service_properties(transport.UNIT.name)
        if int(current['MainPID'])!=old_pid or Path('/proc/'+str(old_pid)+'/stat').read_text().split(') ',1)[1].split()[19]!=old_start:raise RuntimeError('standalone generation changed before handoff')
        phase('STOPPING_STANDALONE');command('systemctl','stop',transport.UNIT.name);stopped=True
        if any(listener_pids(p['port']) for p in blueprint.values()):raise RuntimeError('old listeners not released')
        phase('ACTIVATING_NATIVE')
        for identity in journal['profiles'].values():api.call('inbounds/setEnable/'+str(identity),{'enable':True})
        command('systemctl','restart',PANEL_UNIT)
        wait_live(api,journal['profiles'],blueprint)
        for profile,identity in journal['profiles'].items():
            users=core_api('inbounduser','-tag='+TAGS[profile]).get('users',[])
            wanted={u['id'] for u in next(x for x in source['inbounds'] if x['tag']==profile)['settings']['clients']}
            if not wanted<={u['account']['id'] for u in users}:raise RuntimeError('starter identities not preserved')
        command('systemctl','disable',transport.UNIT.name)
        web['panel_managed_inbounds']=True;atomic(WEB_STATE,(json.dumps(web)+'\n').encode(),0o600)
        phase('READY')
    except Exception as error:
        journal['failed_phase']=journal['phase'];journal['error_class']=type(error).__name__
        try:
            phase('ROLLING_BACK')
            known=set(journal['profiles'].values())
            if any(x.get('tag') in TAGS.values() and x['id'] not in known for x in api.call('inbounds/list') or []):
                raise RuntimeError('unrecorded staged inbound; automatic cleanup refused')
            for profile,identity in journal['profiles'].items():
                item=api.call('inbounds/get/'+str(identity))
                if item.get('tag')!=TAGS[profile]:raise RuntimeError('staged inbound ownership changed')
                api.call('inbounds/setEnable/'+str(identity),{'enable':False})
            if previous_template is not None:
                api.call('xray/update',{'xraySetting':json.dumps(object_value(previous_template['xraySetting'])),
                    'outboundTestUrl':previous_template.get('outboundTestUrl','')},form=True)
            if stopped:
                command('systemctl','restart',PANEL_UNIT)
                until=time.monotonic()+18
                while time.monotonic()<until:
                    try:
                        api.call('inbounds/list');core_api('lsi','-isOnlyTags=true');break
                    except (RuntimeError,ValueError,KeyError):time.sleep(.2)
                else:raise RuntimeError('panel not ready for scoped rollback')
                for _ in range(90):
                    if not any(listener_pids(p['port']) for p in blueprint.values()):break
                    time.sleep(.2)
                else:raise RuntimeError('native listeners not released; original will not start')
            current_clients={x.get('client',x).get('email'):x.get('client',x) for x in api.call('clients/list') or []}
            for email,person in people.items():
                if not person.get('create_requested') or email not in current_clients:continue
                obj=api.call('clients/get/'+urllib.parse.quote(email,safe=''));record=obj['client']
                if record.get('uuid')!=person['client']['id'] or record.get('subId')!=person['client']['subId'] or not set(obj['inboundIds'])<=set(person['inboundIds']):raise RuntimeError('staged client ownership changed')
                api.call('clients/del/'+urllib.parse.quote(email,safe=''),{})
            for identity in journal['profiles'].values():api.call('inbounds/del/'+str(identity),{})
            source_snapshot()
            if stopped:
                command('systemctl','start',transport.UNIT.name)
                if previous_enabled=='enabled':command('systemctl','enable',transport.UNIT.name)
            atomic(WEB_STATE,(backup/'web-state.json').read_bytes(),0o600)
            phase('ROLLED_BACK')
        except Exception:
            phase('RECOVERY_REQUIRED')
            raise RuntimeError('RECOVERY_REQUIRED: native handoff failed; private journal/backup retained') from None
        raise RuntimeError('native handoff failed; original configuration restored; private journal retained') from None
    print('PANEL_INBOUNDS_READY: native P0/P1/P3; secrets retained privately')
