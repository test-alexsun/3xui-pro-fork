"""Hysteria2 v2 native panel contract, URI validation, outbound builder, and listener checks."""
import base64
import ipaddress
from pathlib import Path, PurePath
import re
import secrets
import subprocess
import urllib.parse

TAG = 'HYSTERIA2'
PROTOCOL = 'hysteria'
DEFAULT_PORT = 24443
DEFAULT_UDP_IDLE_TIMEOUT = 60
AWG_RESERVED_PORT = 29177
DEFAULT_CERT = Path('/var/lib/3xui-preview-acme/config/live/3xui-preview/fullchain.pem')
DEFAULT_KEY = Path('/var/lib/3xui-preview-acme/config/live/3xui-preview/privkey.pem')

_DOMAIN_RE = re.compile(r'(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}')
_TOKEN_INVALID_RE = re.compile(r'[\s\x00-\x1f\x7f]')
_CONTROL_RE = re.compile(r'[\r\n\x00]')
_TRUTHY = {'1', 'true', 'yes', 'on'}


def _posix_path(value, label):
    if isinstance(value, PurePath):
        text = value.as_posix()
    elif isinstance(value, str):
        text = value
    else:
        raise ValueError(f'{label} must be a path or string')
    if not text or not text.strip() or _CONTROL_RE.search(text):
        raise ValueError(f'invalid {label}')
    return text


def _validate_domain(domain, label='domain'):
    if not isinstance(domain, str) or len(domain) > 253 or not _DOMAIN_RE.fullmatch(domain):
        raise ValueError(f'invalid {label}')
    return domain


def _validate_port(port):
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError('invalid Hysteria2 port')
    if port == AWG_RESERVED_PORT:
        raise ValueError('port 29177 is reserved for AmneziaWG 3.1')
    return port


def _validate_token(value, label):
    if not isinstance(value, str) or not value or _TOKEN_INVALID_RE.search(value):
        raise ValueError(f'invalid {label}')
    return value


def _parse_alpn(params):
    raw = params.get('alpn', '')
    return [item.strip().lower() for item in raw.split(',') if item.strip()]


def _has_insecure_flag(params):
    for key in ('insecure', 'allowInsecure', 'allowinsecure'):
        if str(params.get(key, '')).strip().lower() in _TRUTHY:
            return True
    return False


def generate_auth():
    """Generate a 32-byte URL-safe secret for Hysteria2 client authentication."""
    return secrets.token_urlsafe(32)


def validate_inbound_payload(payload):
    """Validate that an inbound payload matches the 3x-ui 3.11.0 Hysteria2 v2 contract."""
    if not isinstance(payload, dict):
        raise ValueError('inbound payload must be a dict')
    if payload.get('protocol') != PROTOCOL:
        raise ValueError('inbound protocol must be hysteria')
    if payload.get('tag') != TAG or payload.get('remark') != TAG:
        raise ValueError('inbound tag and remark must be HYSTERIA2')
    _validate_port(payload.get('port'))
    try:
        ipaddress.ip_address(str(payload.get('listen', '')))
    except ValueError as exc:
        raise ValueError('invalid listen IP address') from exc

    settings = payload.get('settings')
    if not isinstance(settings, dict) or settings.get('version') != 2 or not isinstance(settings.get('clients'), list):
        raise ValueError('Hysteria2 settings must specify version 2 and clients list')

    stream = payload.get('streamSettings')
    if not isinstance(stream, dict):
        raise ValueError('streamSettings must be a dict')
    if stream.get('network') != 'hysteria':
        raise ValueError('streamSettings.network must be hysteria')
    if stream.get('security') != 'tls':
        raise ValueError('streamSettings.security must be tls')

    hy_settings = stream.get('hysteriaSettings')
    if (not isinstance(hy_settings, dict) or hy_settings.get('version') != 2 or
            type(hy_settings.get('udpIdleTimeout')) is not int or hy_settings['udpIdleTimeout'] <= 0):
        raise ValueError('hysteriaSettings must specify version 2 and positive udpIdleTimeout')

    tls = stream.get('tlsSettings')
    if not isinstance(tls, dict):
        raise ValueError('tlsSettings must be a dict')
    if tls.get('allowInsecure'):
        raise ValueError('TLS verification must never be disabled')
    if tls.get('alpn') != ['h3']:
        raise ValueError('tlsSettings.alpn must be ["h3"]')
    _validate_domain(tls.get('serverName', ''), 'tlsSettings.serverName')

    certs = tls.get('certificates')
    if not isinstance(certs, list) or not certs:
        raise ValueError('tlsSettings.certificates must be non-empty')
    for cert in certs:
        if not isinstance(cert, dict):
            raise ValueError('certificate entry must be a dict')
        _posix_path(cert.get('certificateFile', ''), 'certificateFile')
        _posix_path(cert.get('keyFile', ''), 'keyFile')
    return payload


def build_inbound_payload(
    listen_ip,
    port=DEFAULT_PORT,
    domain='',
    cert_path=DEFAULT_CERT,
    key_path=DEFAULT_KEY,
    udp_idle_timeout=DEFAULT_UDP_IDLE_TIMEOUT,
    enable=False,
):
    """Build and validate a 3x-ui 3.11.0 Hysteria2 v2 inbound payload."""
    try:
        listen_addr = str(ipaddress.ip_address(str(listen_ip)))
    except ValueError as exc:
        raise ValueError('invalid listen_ip') from exc
    _validate_port(port)
    _validate_domain(domain)
    cert_str = _posix_path(cert_path, 'cert_path')
    key_str = _posix_path(key_path, 'key_path')
    if type(udp_idle_timeout) is not int or udp_idle_timeout <= 0:
        raise ValueError('udp_idle_timeout must be a positive integer')

    payload = {
        'tag': TAG,
        'remark': TAG,
        'enable': bool(enable),
        'listen': listen_addr,
        'port': port,
        'protocol': PROTOCOL,
        'settings': {
            'version': 2,
            'clients': [],
        },
        'streamSettings': {
            'network': 'hysteria',
            'security': 'tls',
            'hysteriaSettings': {
                'version': 2,
                'udpIdleTimeout': udp_idle_timeout,
            },
            'tlsSettings': {
                'serverName': domain,
                'alpn': ['h3'],
                'certificates': [
                    {
                        'certificateFile': cert_str,
                        'keyFile': key_str,
                    }
                ],
            },
        },
        'sniffing': {
            'enabled': False,
        },
        'shareAddrStrategy': 'custom',
        'shareAddr': domain,
    }
    return validate_inbound_payload(payload)


def build_client_payload(email, auth=None, enable=True, sub_id=None):
    """Build a Hysteria2 client record dictionary for 3x-ui client endpoints."""
    _validate_token(email, 'email')
    resolved_auth = generate_auth() if auth is None else _validate_token(auth, 'auth')
    resolved_sub_id = secrets.token_urlsafe(24) if sub_id is None else _validate_token(sub_id, 'subId')
    return {
        'email': email,
        'enable': bool(enable),
        'auth': resolved_auth,
        'subId': resolved_sub_id,
    }


def build_client_add_payload(inbound_ids, email, auth=None, enable=True, sub_id=None):
    """Build a complete payload for POST /panel/api/clients/add."""
    if type(inbound_ids) is int:
        ids = [inbound_ids]
    elif isinstance(inbound_ids, (list, tuple)) and inbound_ids:
        ids = list(inbound_ids)
    else:
        raise ValueError('inbound_ids must be a positive int or non-empty sequence')
    if any(type(item) is not int or item < 1 for item in ids):
        raise ValueError('inbound_ids must contain positive integers')
    return {
        'client': build_client_payload(email, auth=auth, enable=enable, sub_id=sub_id),
        'inboundIds': ids,
    }


def build_client_update_payload(email, *, enable=None, auth=None, sub_id=None):
    """Build a payload for POST /panel/api/clients/update/:email.

    Omit auth to preserve existing credentials in client_crud.go; pass a
    non-empty auth string to rotate the client secret.
    """
    _validate_token(email, 'email')
    payload = {'email': email}
    if enable is not None:
        payload['enable'] = bool(enable)
    if auth is not None:
        payload['auth'] = _validate_token(auth, 'auth')
    if sub_id is not None:
        payload['subId'] = _validate_token(sub_id, 'subId')
    if len(payload) == 1:
        raise ValueError('at least one update field (enable, auth, or sub_id) is required')
    return payload


def parse_hysteria2_link(uri):
    """Parse a hysteria2:// URI and extract URL-unquoted auth, host, port, params, and remark."""
    if not isinstance(uri, str) or not uri.strip() or _CONTROL_RE.search(uri):
        raise ValueError('invalid hysteria2 URI')
    parsed = urllib.parse.urlsplit(uri.strip())
    scheme = parsed.scheme.lower()
    if scheme != 'hysteria2':
        raise ValueError('URI scheme must be hysteria2')
    if parsed.path not in ('', '/'):
        raise ValueError('unexpected path in hysteria2 URI')

    userinfo, sep, hostport = parsed.netloc.rpartition('@')
    if not sep or not userinfo or not hostport:
        raise ValueError('hysteria2 URI must include auth and host:port')
    auth = urllib.parse.unquote(userinfo)
    if not auth:
        raise ValueError('empty auth in hysteria2 URI')

    authority = urllib.parse.urlsplit('//' + hostport)
    host = authority.hostname
    try:
        port = authority.port
    except ValueError as exc:
        raise ValueError('invalid port in hysteria2 URI') from exc
    if not host or port is None or not 1 <= port <= 65535:
        raise ValueError('hysteria2 URI must include valid host and port')

    params = {}
    for key, value in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True):
        if key in params:
            params[key] = params[key] + ',' + value
        else:
            params[key] = value
    remark = urllib.parse.unquote(parsed.fragment)
    return {
        'scheme': scheme,
        'auth': auth,
        'host': host,
        'port': port,
        'params': params,
        'remark': remark,
    }


def validate_hysteria2_link(uri, expected_host, expected_port, expected_auth, expected_sni):
    """Validate a hysteria2:// URI against expected host, port, auth, TLS/h3, and SNI."""
    parsed = parse_hysteria2_link(uri)
    if parsed['scheme'] != 'hysteria2':
        raise ValueError('unexpected scheme in hysteria2 link')
    if not isinstance(expected_host, str) or parsed['host'].casefold() != expected_host.casefold():
        raise ValueError('hysteria2 link host mismatch')
    if type(expected_port) is not int or parsed['port'] != expected_port:
        raise ValueError('hysteria2 link port mismatch')
    if not isinstance(expected_auth, str) or not secrets.compare_digest(
        parsed['auth'].encode('utf-8'), expected_auth.encode('utf-8')
    ):
        raise ValueError('hysteria2 link auth mismatch')

    params = parsed['params']
    if params.get('security', '').strip().lower() != 'tls':
        raise ValueError('hysteria2 link must require security=tls')
    if _has_insecure_flag(params):
        raise ValueError('hysteria2 link must not disable TLS verification')
    if 'h3' not in _parse_alpn(params):
        raise ValueError('hysteria2 link must require alpn=h3')
    sni = params.get('sni', '')
    if not isinstance(expected_sni, str) or not sni or sni.casefold() != expected_sni.casefold():
        raise ValueError('hysteria2 link sni mismatch')
    return parsed


def client_outbound_from_link(uri, connect_address, ca_file):
    """Construct an Xray Hysteria2 v2 client outbound strictly verifying TLS via ca_file."""
    parsed = parse_hysteria2_link(uri)
    params = parsed['params']
    if params.get('security', '').strip().lower() != 'tls':
        raise ValueError('hysteria2 link must require security=tls')
    if _has_insecure_flag(params):
        raise ValueError('refusing to construct outbound with insecure TLS setting')
    if 'h3' not in _parse_alpn(params):
        raise ValueError('hysteria2 link must require alpn=h3')

    sni = params.get('sni') or ''
    if not sni:
        try:
            ipaddress.ip_address(parsed['host'])
        except ValueError:
            sni = _validate_domain(parsed['host'], 'host')
        else:
            raise ValueError('hysteria2 link missing TLS SNI')
    else:
        _validate_domain(sni, 'sni')

    _validate_token(connect_address, 'connect_address')
    ca_str = _posix_path(ca_file, 'ca_file')
    return {
        'protocol': 'hysteria',
        'settings': {
            'version': 2,
            'address': connect_address,
            'port': parsed['port'],
        },
        'streamSettings': {
            'network': 'hysteria',
            'security': 'tls',
            'hysteriaSettings': {
                'version': 2,
                'auth': parsed['auth'],
            },
            'tlsSettings': {
                'serverName': sni,
                'alpn': ['h3'],
                'certificates': [
                    {
                        'certificateFile': ca_str,
                        'usage': 'verify',
                    }
                ],
            },
        },
    }


def _decode_possible_subscription(text):
    stripped = text.strip()
    if not stripped:
        return []
    if '://' in stripped:
        return [line.strip() for line in stripped.splitlines() if line.strip().lower().startswith('hysteria2://')]
    compact = ''.join(stripped.split())
    if not re.fullmatch(r'[A-Za-z0-9+/=_-]+', compact):
        return []
    padded = compact + '=' * (-len(compact) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded) if ('-' in compact or '_' in compact) else base64.b64decode(padded, validate=True)
        decoded = raw.decode('utf-8')
    except (ValueError, UnicodeDecodeError):
        return []
    return [line.strip() for line in decoded.splitlines() if line.strip().lower().startswith('hysteria2://')]


def extract_hysteria2_links(data):
    """Extract unique hysteria2:// URIs from panel API link payloads or subscription responses."""
    if isinstance(data, bytes):
        data = data.decode('utf-8')
    found = []
    seen = set()

    def add_uri(candidate):
        if candidate not in seen:
            seen.add(candidate)
            found.append(candidate)

    def walk(node, top_level=False):
        if isinstance(node, str):
            if top_level:
                for uri in _decode_possible_subscription(node):
                    add_uri(uri)
            elif 'hysteria2://' in node.lower():
                for line in node.splitlines():
                    item = line.strip()
                    if item.lower().startswith('hysteria2://'):
                        add_uri(item)
        elif isinstance(node, (list, tuple)):
            for item in node:
                walk(item, top_level=False)
        elif isinstance(node, dict):
            for key in ('link', 'uri', 'url', 'links', 'obj', 'hysteria2'):
                if key in node:
                    walk(node[key], top_level=False)
            for key, value in node.items():
                if key not in ('link', 'uri', 'url', 'links', 'obj', 'hysteria2'):
                    walk(value, top_level=False)

    walk(data, top_level=True)
    return found


def verify_live_listener(port, expected_xray_pid):
    """Verify the UDP listener on port is active and owned solely by expected_xray_pid."""
    _validate_port(port)
    if type(expected_xray_pid) is not int or expected_xray_pid <= 0:
        raise ValueError('expected_xray_pid must be a positive integer')
    try:
        output = subprocess.check_output(
            ['ss', '-H', '-lunp', f'sport = :{port}'],
            text=True,
            stderr=subprocess.PIPE,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError('failed to inspect live Hysteria2 UDP listener') from exc

    if not output.strip():
        raise RuntimeError(f'missing UDP listener on port {port}')
    pids = {int(pid) for pid in re.findall(r'pid=(\d+)', output)}
    if not pids:
        raise RuntimeError(f'unidentified UDP listener on port {port}')
    if pids != {expected_xray_pid}:
        raise RuntimeError(f'UDP listener on port {port} owned by unexpected PID')
    return True
