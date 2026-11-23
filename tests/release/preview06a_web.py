"""Disposable-fixture-only panel, subscription and exposure checks; never prints secrets."""
import base64
import hashlib
import http.client
import http.cookiejar
import json
import os
from pathlib import Path
import re
import secrets
import socket
import ssl
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid

MAIN='de126.alexsun55.ru'; SUB='de126-sub.alexsun55.ru'
STATE=Path('/var/lib/3xui-pro-fork/preview-panel.json')
FIXTURE=Path('/run/preview06a-fixture.json')
CA='/tmp/preview06a-ca/root.pem'
original=socket.getaddrinfo
socket.getaddrinfo=lambda host,port,*a,**k: original('10.77.5.1' if host in (MAIN,SUB) else host,port,*a,**k)
ctx=ssl.create_default_context(cafile=CA)


def opener(cookies=None):
    handlers=[urllib.request.ProxyHandler({}),urllib.request.HTTPSHandler(context=ctx)]
    if cookies is not None:handlers.append(urllib.request.HTTPCookieProcessor(cookies))
    return urllib.request.build_opener(*handlers)


def request(client,url,data=None,headers=None):
    try:
        with client.open(urllib.request.Request(url,data=data,headers=headers or {}),timeout=20) as r:
            return r.status,r.read(),r.headers
    except urllib.error.HTTPError as e:return e.code,e.read(),e.headers


def setup():
    state=json.loads(STATE.read_text());path=state['layout']['panel_path']
    client=opener()
    def api(route,payload):
        status,body,_=request(client,'http://127.0.0.1:2053'+path+'panel/api/'+route,
          json.dumps(payload).encode(),{'Authorization':'Bearer '+state['api_token'],'Content-Type':'application/json','Host':MAIN})
        result=json.loads(body);assert status==200 and result['success'], 'fixture API rejected'
        return result.get('obj')
    settings=api('setting/all',{})
    assert settings['webBasePath']==path and settings['subURI']=='https://'+SUB+'/sub/'
    inbound={'up':0,'down':0,'total':0,'remark':'fixture-06a','enable':True,'expiryTime':0,
      'listen':'127.0.0.1','port':20086,'protocol':'vless','settings':json.dumps({'clients':[],'decryption':'none'}),
      'streamSettings':json.dumps({'network':'tcp','security':'none'}),'sniffing':json.dumps({'enabled':False,'destOverride':[]})}
    obj=api('inbounds/add',inbound);assert obj['id']
    identity=str(uuid.uuid4());token=secrets.token_urlsafe(24)
    api('clients/add',{'client':{'id':identity,'email':'fixture-06a','enable':True,'subId':token},'inboundIds':[obj['id']]})
    logs=subprocess.check_output(['journalctl','-u','3xui-pro-fork.service','-o','cat'],text=True)
    match=re.search(r'Username: (\S+)\s+Password: (\S+)',logs);assert match,'initial credentials not available'
    os.umask(0o077)
    invalid={}
    for route,agent in (('/sub/','v2rayNG/1.9'),('/json/','fixture-json'),('/clash/','clash')):
        status,body,_=request(client,'http://127.0.0.1:2096'+route+'invalid-token',headers={'Host':SUB,'User-Agent':agent})
        invalid[route]=[status,hashlib.sha256(body).hexdigest()]
    FIXTURE.write_text(json.dumps({'invalid':invalid,'uuid':identity,'subid':token,'path':path,'username':match[1],'password':match[2]}))
    print('PREVIEW06A_AUTOMATIC_PANEL_SUBSCRIPTION_SETUP_PASS')


def verify():
    fixture=json.loads(FIXTURE.read_text());path=fixture['path'];jar=http.cookiejar.CookieJar();client=opener(jar)
    def panel(route,payload=None,csrf=None):
        headers={};data=None
        if payload is not None:
            headers['Content-Type']='application/x-www-form-urlencoded';data=urllib.parse.urlencode(payload).encode()
        if csrf:headers['X-CSRF-Token']=csrf
        status,body,headers=request(client,'https://'+MAIN+path+route,data,headers)
        assert status==200,'panel request status'
        value=json.loads(body);assert value['success'],'panel API success'
        return value.get('obj')
    csrf=panel('csrf-token')
    panel('login',{'username':fixture['username'],'password':fixture['password']},csrf)
    panel('panel/api/inbounds/list')
    csrf=panel('csrf-token');panel('panel/api/setting/all',{},csrf)
    cookies=list(jar);assert cookies and all(c.path==path and c.secure for c in cookies),'cookie scope/secure'
    assert any('HttpOnly' in c._rest for c in cookies),'cookie httponly'
    assert any(c._rest.get('SameSite','').lower()=='lax' for c in cookies),'cookie SameSite'
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self,*args,**kwargs):return None
    no_redirect=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPSHandler(context=ctx),NoRedirect())
    status,_,headers=request(no_redirect,'https://'+MAIN+path.rstrip('/'))
    assert status==308 and headers['Location']=='https://'+MAIN+path,'public panel redirect must omit backend port'
    status,_,_=request(client,'https://'+MAIN+path+'panel/api/setting/all',b'{}',{'Content-Type':'application/json'})
    assert status==403,'missing CSRF must fail'
    # Prove an authenticated WebSocket upgrade across the protected path.
    cookie='; '.join(c.name+'='+c.value for c in cookies)
    with socket.create_connection(('10.77.5.1',443),timeout=10) as raw:
        with ctx.wrap_socket(raw,server_hostname=MAIN) as tls:
            key=base64.b64encode(secrets.token_bytes(16)).decode()
            tls.sendall((f'GET {path}ws HTTP/1.1\r\nHost: {MAIN}\r\nOrigin: https://{MAIN}\r\nCookie: {cookie}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Version: 13\r\nSec-WebSocket-Key: {key}\r\n\r\n').encode())
            assert tls.recv(4096).startswith(b'HTTP/1.1 101'),'WebSocket upgrade'
    print('PREVIEW06A_PANEL_LOGIN_COOKIE_CSRF_API_WEBSOCKET_PASS')
    fresh=opener()
    for route,agent in (('/sub/','v2rayNG/1.9'),('/json/','fixture-json'),('/clash/','clash')):
        status,body,headers=request(fresh,'https://'+SUB+route+fixture['subid'],headers={'User-Agent':agent})
        assert status==200 and b'XONIX' not in body,'subscription response'
        if route=='/sub/':
            decoded=body if b'vless://' in body else base64.b64decode(body+b'='*(-len(body)%4))
            assert fixture['uuid'].encode() in decoded,'subscription identity'
        else:
            assert fixture['uuid'].encode() in body,'subscription format identity'
            if route=='/json/':assert isinstance(json.loads(body),(list,dict)),'JSON format'
        assert headers.get('Referrer-Policy')=='no-referrer'
        invalid=route+'invalid-token'
        proxy=request(fresh,'https://'+SUB+invalid,headers={'User-Agent':agent})
        assert fixture['invalid'][route]==[proxy[0],hashlib.sha256(proxy[1]).hexdigest()] and proxy[0]==404 and b'XONIX' not in proxy[1]
    blocked=('/', '/login', '/panel/', '/panel/api/inbounds/list',path,path+'login',path+'panel/api/inbounds/list',
             '/xhttp/', '/preview-xray.json','/preview-panel.json','/x-ui.db','/awg/client.conf','/awg/server.setconf','/.env','/missing/'+fixture['subid'])
    for route in blocked:
        status,body,_=request(fresh,'https://'+SUB+route+'?token='+fixture['subid'])
        assert status==404 and b'XONIX' not in body and fixture['uuid'].encode() not in body,'subscription isolation'
    for route in ('/login','/panel/api/inbounds/list','/preview-xray.json','/awg/client.conf','/x-ui.db','/.env'):
        assert request(fresh,'https://'+MAIN+route)[0]==404,'site exposure'
    for name in (MAIN,SUB):
        assert request(fresh,'http://'+name+'/.well-known/acme-challenge/fixture')[:2]==(200,b'synthetic-challenge\n')
    for host in (MAIN,SUB):
        other=SUB if host==MAIN else MAIN
        with socket.create_connection(('10.77.5.1',443),timeout=10) as raw:
            with ctx.wrap_socket(raw,server_hostname=host) as tls:
                tls.sendall(f'GET / HTTP/1.1\r\nHost: {other}\r\nConnection: close\r\n\r\n'.encode())
                response=http.client.HTTPResponse(tls);response.begin();assert response.status==421,'SNI/Host mismatch'
    for port in (8443,9443):
        with socket.create_connection(('10.77.5.1',port),timeout=10) as raw:
            with ctx.wrap_socket(raw,server_hostname=MAIN) as tls:
                tls.sendall(f'GET {path} HTTP/1.1\r\nHost: {MAIN}\r\nConnection: close\r\n\r\n'.encode())
                response=http.client.HTTPResponse(tls);response.begin();assert response.status==404,'REALITY fallback isolation'
    try:
        with socket.create_connection(('10.77.5.1',443),timeout=10) as raw:
            with ctx.wrap_socket(raw,server_hostname='invalid'):raise AssertionError('unknown SNI accepted')
    except ssl.SSLError:pass
    print('PREVIEW06A_SUBSCRIPTIONS_ALL_FORMATS_INVALID_UNKNOWN_EXPOSURE_SNI_PASS')


def logs():
    data=json.loads(FIXTURE.read_text())
    text=subprocess.check_output(['journalctl','-u','3xui-pro-fork.service','-u','nginx','-o','cat'],text=True)
    for p in Path('/var/log/nginx').glob('*.log'):text+=p.read_text(errors='replace')
    assert data['subid'] not in text,'subscription token leaked to logs'
    print('PREVIEW06A_TOKEN_LOG_REDACTION_PASS')

if __name__=='__main__':{'setup':setup,'verify':verify,'logs':logs}[sys.argv[1]]()
