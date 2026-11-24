"""Pinned profile renderer from lib/installer/modern_profiles.py at f6c478a."""
import copy
import re
import uuid

VERSION = '26.11.9'
PRIMARY = 'P0'
PROFILES = {
    'P0': ('vless', 'xhttp', 'reality', 'h2', 'stream-up'),
    'P1': ('vless', 'xhttp', 'tls', 'h2', 'stream-up'),
    'P2': ('vless', 'xhttp', 'tls', 'h3', 'stream-one'),
    'P3': ('vless', 'raw', 'reality', 'h2', None),
    'P4': ('vless', 'xhttp', 'reality', 'h2', 'stream-up'),
}


def render_pair(profile, p):
    if profile not in PROFILES or p.get('xray_version') != VERSION:
        raise ValueError('UNQUALIFIED_PROFILE_OR_VERSION')
    uuid.UUID(p['uuid'])
    if not re.fullmatch(r'[A-Za-z0-9.-]+', p['host']) or not re.fullmatch(r'/[A-Za-z0-9/_-]+/', p['path']):
        raise ValueError('INVALID_PROFILE_HOST_OR_PATH')
    if not isinstance(p['port'], int) or not 1 <= p['port'] <= 65535:
        raise ValueError('INVALID_PROFILE_PORT')
    _, network, security, alpn, mode = PROFILES[profile]
    if profile == 'P2' and p['port'] in p.get('occupied_udp', []):
        raise ValueError('UDP_PORT_CONFLICT')
    encryption, decryption = 'none', 'none'
    if profile == 'P4':
        encryption, decryption = p.get('encryption', ''), p.get('decryption', '')
        if not all(v.startswith('mlkem768x25519plus.') for v in (encryption, decryption)):
            raise ValueError('PQ_PAIR_REQUIRED_NO_FALLBACK')
    user = {'id': p['uuid'], 'encryption': encryption}
    if profile == 'P3':
        user['flow'] = 'xtls-rprx-vision'
    server_user = {k: v for k, v in user.items() if k != 'encryption'}
    ss = {'network': network, 'security': security}
    cs = copy.deepcopy(ss)
    if network == 'xhttp':
        ss['xhttpSettings'] = {'host': p['host'], 'path': p['path'], 'mode': mode}
        cs['xhttpSettings'] = copy.deepcopy(ss['xhttpSettings'])
    if security == 'reality':
        ss['realitySettings'] = {'target': p['target'], 'serverNames': [p['host']],
            'privateKey': p['private_key'], 'shortIds': [p['short_id']], 'show': False, 'xver': 0}
        cs['realitySettings'] = {'serverName': p['host'], 'password': p['public_key'],
            'shortId': p['short_id'], 'fingerprint': 'chrome', 'spiderX': '/'}
    else:
        ss['tlsSettings'] = {'alpn': [alpn], 'certificates': [{'certificateFile': p['cert'], 'keyFile': p['key']}]}
        cs['tlsSettings'] = {'serverName': p['host'], 'alpn': [alpn], 'fingerprint': 'chrome',
            'certificates': [{'certificateFile': p['cert'], 'usage': 'verify'}]}
    listen, server_port = '127.0.0.1', p['port']
    if profile == 'P1' and p.get('unix_socket'):
        listen, server_port = p['unix_socket'], 0
        ss['security'] = 'none'
        ss.pop('tlsSettings')
    if p.get('accept_proxy'):
        ss['sockopt'] = {'acceptProxyProtocol': True}
    server = {'log': {'loglevel': 'debug'}, 'inbounds': [{'listen': listen, 'port': server_port,
        'protocol': 'vless', 'tag': profile, 'settings': {'clients': [server_user], 'decryption': decryption},
        'streamSettings': ss}], 'outbounds': [{'protocol': 'freedom', 'tag': 'direct'}]}
    client = {'log': {'loglevel': 'debug'}, 'inbounds': [{'listen': '127.0.0.1', 'port': p['proxy_port'],
        'protocol': 'http', 'settings': {}}], 'outbounds': [{'protocol': 'vless', 'tag': profile,
        'settings': {'vnext': [{'address': '127.0.0.1', 'port': p['port'], 'users': [user]}]}, 'streamSettings': cs}]}
    return server, client
