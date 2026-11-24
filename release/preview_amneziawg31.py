"""AmneziaWG 3.1 embedded panel integration helpers for 3x-ui 3.11.0.

Strictly targets embedded AWG 3.1 (amneziawg-go/v3 v3.1.20260828, tools 3.1.20260812)
with HeaderProtectionKey and obfuscation parameters; never touches plain WireGuard,
never alters server MTU away from explicit 1420 default, and never enables kernelMode.
"""
import base64
import ipaddress
import json
import re
import secrets
import subprocess

AWG_BIN = '/opt/3xui-pro-fork/awg/awg'
AWG_GO_BIN = '/opt/3xui-pro-fork/awg/amneziawg-go'
STANDALONE_UNIT = '3xui-pro-fork-awg.service'
PANEL_UNIT = '3xui-pro-fork.service'
DEFAULT_PORT = 29177
DEFAULT_MTU = 1420

AWG31_OBFUSCATION_DEFAULTS = {
    'jc': 4,
    'jmin': 40,
    'jmax': 70,
    's1': 12,
    's2': 12,
    's3': 12,
    's4': 12,
    'h1': '1',
    'h2': '2',
    'h3': '3',
    'h4': '4',
}

RFC1918_NETWORKS = (
    ipaddress.IPv4Network('10.0.0.0/8'),
    ipaddress.IPv4Network('172.16.0.0/12'),
    ipaddress.IPv4Network('192.168.0.0/16'),
)

_KEY_RE = re.compile(r'^[A-Za-z0-9+/]{43}=$')
_B64URL_RE = re.compile(r'^[A-Za-z0-9_-]+={0,2}$')
_CONTROL_RE = re.compile(r'[\x00-\x1f\x7f]')
_OBF_CHAIN_TAGS = frozenset({'b', 't', 'r', 'rc', 'rd', 'd', 'ds', 'dz'})
_UINT32_MAX = 4294967295
_MAX_SERVER_S1 = 1700 - 148
_MAX_SERVER_S2 = 1700 - 92
_MAX_SERVER_S3 = 1700 - 64

_OPTIONAL_RANGE_FIELDS = (
    'contentPaddingAddition',
    'rekeyAfterTime',
    'rekeyTimeout',
    'rejectAfterTime',
    'keepaliveTimeout',
    'maxHandshakeAttempts',
)
_OPTIONAL_CPS_FIELDS = ('i1', 'i2', 'i3', 'i4', 'i5')
_CONF_REQUIRED_AWG31_KEYS = (
    'MTU',
    'Jc',
    'Jmin',
    'Jmax',
    'S1',
    'S2',
    'S3',
    'S4',
    'H1',
    'H2',
    'H3',
    'H4',
    'HeaderProtectionKey',
)
_SETCONF_STRIP_KEYS = frozenset({'Address', 'DNS', 'MTU'})
_FORBIDDEN_HOOK_KEYS = frozenset({'PreUp', 'PostUp', 'PreDown', 'PostDown', 'Table', 'SaveConfig'})
_BOOL_SETCONF_KEYS = frozenset({'RandomTrailers', 'DisableCookies'})


def _reject_control_chars(value, label):
    if not isinstance(value, str) or _CONTROL_RE.search(value):
        raise ValueError(f'{label} must be a string without control characters')
    return value


def _run_awg(awg_bin, *args, data=None):
    try:
        result = subprocess.run(
            [str(awg_bin), *args],
            input=data,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f'AWG command failed: {type(exc).__name__}') from None
    return result.stdout.strip()


def validate_key(value):
    """Validate a canonical 32-byte standard base64 WireGuard/AWG 3.1 key."""
    if not isinstance(value, str) or not _KEY_RE.fullmatch(value):
        raise ValueError('invalid 32-byte base64 AWG key')
    try:
        raw = base64.b64decode(value, validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError('invalid base64 encoding in AWG key') from exc
    if len(raw) != 32 or raw == b'\x00' * 32 or base64.b64encode(raw).decode('ascii') != value:
        raise ValueError('invalid 32-byte AWG key material')
    return value


def _x25519_pubkey_from_priv_b64(priv_b64):
    """Compute standard base64 Curve25519 public key from base64 private key."""
    validate_key(priv_b64)
    p = (1 << 255) - 19
    k = bytearray(base64.b64decode(priv_b64))
    k[0] &= 248
    k[31] &= 127
    k[31] |= 64
    k_int = int.from_bytes(k, 'little')
    x_1 = 9
    x_2, z_2, x_3, z_3 = 1, 0, 9, 1
    swap = 0
    for bit in range(254, -1, -1):
        k_t = (k_int >> bit) & 1
        swap ^= k_t
        if swap:
            x_2, x_3 = x_3, x_2
            z_2, z_3 = z_3, z_2
        swap = k_t
        a = (x_2 + z_2) % p
        aa = (a * a) % p
        b = (x_2 - z_2) % p
        bb = (b * b) % p
        e = (aa - bb) % p
        c = (x_3 + z_3) % p
        d = (x_3 - z_3) % p
        da = (d * a) % p
        cb = (c * b) % p
        x_3 = pow(da + cb, 2, p)
        z_3 = (x_1 * pow(da - cb, 2, p)) % p
        x_2 = (aa * bb) % p
        z_2 = (e * (aa + 121665 * e)) % p
    if swap:
        x_2, x_3 = x_3, x_2
        z_2, z_3 = z_3, z_2
    pub_raw = ((x_2 * pow(z_2, p - 2, p)) % p).to_bytes(32, 'little')
    return base64.b64encode(pub_raw).decode('ascii')


def generate_keypair(awg_bin=AWG_BIN):
    """Generate a Curve25519 (private, public) keypair via the pinned awg binary."""
    priv = validate_key(_run_awg(awg_bin, 'genkey'))
    pub = validate_key(_run_awg(awg_bin, 'pubkey', data=priv + '\n'))
    return priv, pub


def public_key(priv_b64, awg_bin=AWG_BIN):
    """Derive Curve25519 public key from a private key via the pinned awg binary."""
    priv_b64 = validate_key(priv_b64)
    return validate_key(_run_awg(awg_bin, 'pubkey', data=priv_b64 + '\n'))


def generate_header_protection_key(awg_bin=AWG_BIN):
    """Generate a 32-byte base64 HeaderProtectionKey for AWG 3.1."""
    return validate_key(_run_awg(awg_bin, 'genkey'))


def validate_subnet(subnet_str, existing_subnets=None):
    """Require strict RFC1918 IPv4 /16../30 subnet and optional non-overlap."""
    if not isinstance(subnet_str, str) or '/' not in subnet_str:
        raise ValueError('AWG subnet must be an IPv4 CIDR string (/16../30)')
    try:
        network = ipaddress.ip_network(subnet_str, strict=True)
    except ValueError as exc:
        raise ValueError(f'invalid AWG subnet {subnet_str!r}') from exc
    if network.version != 4 or not 16 <= network.prefixlen <= 30:
        raise ValueError('AWG subnet must be IPv4 with prefix length /16../30')
    if not any(network.subnet_of(block) for block in RFC1918_NETWORKS):
        raise ValueError(f'AWG subnet {network} must be inside RFC1918 private space')
    if existing_subnets:
        for other in existing_subnets:
            other_net = ipaddress.ip_network(other, strict=False)
            if other_net.version == 4 and network.overlaps(other_net):
                raise ValueError(f'AWG subnet {network} overlaps existing subnet {other_net}')
    return network


def allocate_client_ip(subnet_str, used_cidrs=()):
    """Allocate the next free host /32 CIDR in subnet_str, reserving the first host for server."""
    network = validate_subnet(subnet_str)
    used_ips = set()
    for entry in used_cidrs or ():
        if not isinstance(entry, str) or not entry.strip():
            raise ValueError('used_cidrs entries must be non-empty CIDR strings')
        try:
            iface = ipaddress.ip_interface(entry.strip())
        except ValueError as exc:
            raise ValueError(f'invalid CIDR in used_cidrs: {entry!r}') from exc
        if iface.version != 4:
            raise ValueError(f'IPv4 CIDR expected in used_cidrs, got {entry!r}')
        if '/' in entry and iface.network.prefixlen < 32 and iface.network.overlaps(network):
            raise ValueError(f'used CIDR {entry!r} overlaps subnet {network}; /32 host expected')
        used_ips.add(iface.ip)

    first_client_int = int(network.network_address) + 2
    last_client_int = int(network.broadcast_address) - 1
    for addr_int in range(first_client_int, last_client_int + 1):
        candidate = ipaddress.IPv4Address(addr_int)
        if candidate not in used_ips:
            return f'{candidate}/32'
    raise ValueError(f'AWG subnet exhausted: no free client IP in {network}')


def _parse_uint_range(value, min_val=0, max_val=_UINT32_MAX, label='range'):
    if type(value) is int:
        value = str(value)
    _reject_control_chars(value, label)
    stripped = value.strip()
    if not stripped:
        raise ValueError(f'{label} must not be empty')
    if '-' in stripped:
        lo_s, hi_s = stripped.split('-', 1)
        lo_s, hi_s = lo_s.strip(), hi_s.strip()
        if not lo_s.isdigit() or not hi_s.isdigit():
            raise ValueError(f'invalid {label} range: {value!r}')
        lo, hi = int(lo_s), int(hi_s)
        normalized = f'{lo}-{hi}'
    else:
        if not stripped.isdigit():
            raise ValueError(f'invalid {label} integer: {value!r}')
        lo = hi = int(stripped)
        normalized = str(lo)
    if lo < min_val or hi > max_val or lo > hi:
        raise ValueError(f'{label} {value!r} out of range {min_val}..{max_val}')
    return lo, hi, normalized


def _validate_cps_chain(spec, label):
    _reject_control_chars(spec, label)
    if not spec:
        return ''
    pos = 0
    while pos < len(spec):
        if spec[pos] != '<':
            raise ValueError(f'{label} has invalid CPS syntax outside <...> tags')
        end = spec.find('>', pos)
        if end < 0:
            raise ValueError(f'{label} has unclosed CPS tag')
        body = spec[pos + 1:end].strip()
        parts = body.split()
        if not parts or parts[0] not in _OBF_CHAIN_TAGS:
            raise ValueError(f'{label} has unsupported CPS tag: {body!r}')
        pos = end + 1
    return spec


def _validate_dns(value, label):
    _reject_control_chars(value, label)
    stripped = value.strip()
    if stripped:
        try:
            ipaddress.ip_address(stripped)
        except ValueError as exc:
            raise ValueError(f'invalid {label} IP address: {value!r}') from exc
    return stripped


def build_server_settings(subnet_str, private_key, public_key, header_protection_key, mtu=DEFAULT_MTU, **obfs):
    """Build and validate 3x-ui 3.11.0 embedded AmneziaWG 3.1 ServerSettings JSON dict."""
    network = validate_subnet(subnet_str)
    private_key = validate_key(private_key)
    public_key = validate_key(public_key)
    if not header_protection_key:
        raise ValueError('headerProtectionKey is required for AWG 3.1')
    header_protection_key = validate_key(header_protection_key)

    opts = dict(obfs)
    kernel_mode = opts.pop('kernelMode', False)
    if kernel_mode is not False:
        raise ValueError('kernelMode must be False for embedded AWG 3.1')
    if type(mtu) is not int or not 1280 <= mtu <= 65535:
        raise ValueError('mtu must be an int in 1280..65535')

    primary_dns = _validate_dns(opts.pop('primaryDns', '1.1.1.1'), 'primaryDns')
    secondary_dns = _validate_dns(opts.pop('secondaryDns', '8.8.8.8'), 'secondaryDns')

    random_trailers = opts.pop('randomTrailers', False)
    disable_cookies = opts.pop('disableCookies', False)
    if type(random_trailers) is not bool or type(disable_cookies) is not bool:
        raise ValueError('randomTrailers and disableCookies must be booleans')

    int_params = {}
    for key in ('jc', 'jmin', 'jmax', 's1', 's2', 's3', 's4'):
        val = opts.pop(key, AWG31_OBFUSCATION_DEFAULTS[key])
        if type(val) is not int:
            raise ValueError(f'{key} must be an integer')
        int_params[key] = val

    if not 0 <= int_params['jc'] <= _UINT32_MAX:
        raise ValueError('jc out of uint32 range')
    if not 0 <= int_params['jmin'] <= int_params['jmax'] <= _UINT32_MAX:
        raise ValueError('jmin/jmax must satisfy 0 <= jmin <= jmax <= uint32_max')
    if not 12 <= int_params['s1'] <= _MAX_SERVER_S1:
        raise ValueError(f's1 must be in 12..{_MAX_SERVER_S1} when HeaderProtectionKey is active')
    if not 12 <= int_params['s2'] <= _MAX_SERVER_S2:
        raise ValueError(f's2 must be in 12..{_MAX_SERVER_S2} when HeaderProtectionKey is active')
    if not 12 <= int_params['s3'] <= _MAX_SERVER_S3:
        raise ValueError(f's3 must be in 12..{_MAX_SERVER_S3} when HeaderProtectionKey is active')
    if not 12 <= int_params['s4'] <= 32:
        raise ValueError('s4 must be in 12..32 when HeaderProtectionKey is active')
    if int_params['s1'] + 56 == int_params['s2']:
        raise ValueError('invalid s1/s2: s1 + 56 must not equal s2')

    h_intervals = []
    h_values = {}
    for key in ('h1', 'h2', 'h3', 'h4'):
        raw_h = opts.pop(key, AWG31_OBFUSCATION_DEFAULTS[key])
        lo, hi, norm = _parse_uint_range(raw_h, min_val=0, label=key)
        h_intervals.append((key, lo, hi))
        h_values[key] = norm
    for i in range(len(h_intervals)):
        k_i, lo_i, hi_i = h_intervals[i]
        for j in range(i + 1, len(h_intervals)):
            k_j, lo_j, hi_j = h_intervals[j]
            if lo_i <= hi_j and lo_j <= hi_i:
                raise ValueError(f'magic headers {k_i} and {k_j} overlap')

    optional_fields = {}
    for key in _OPTIONAL_CPS_FIELDS:
        if key in opts:
            val = opts.pop(key)
            if val is not None and val != '':
                optional_fields[key] = _validate_cps_chain(val, key)
    for key in _OPTIONAL_RANGE_FIELDS:
        if key in opts:
            val = opts.pop(key)
            if val is not None and str(val).strip() != '':
                min_bound = 0 if key == 'contentPaddingAddition' else 1
                _, _, norm = _parse_uint_range(val, min_val=min_bound, label=key)
                optional_fields[key] = norm

    if opts:
        raise ValueError(f'unsupported AWG 3.1 server settings keys: {sorted(opts)}')

    settings = {
        'privateKey': private_key,
        'publicKey': public_key,
        'subnetIp': str(network.network_address),
        'subnetCidr': network.prefixlen,
        'mtu': mtu,
        'primaryDns': primary_dns,
        'secondaryDns': secondary_dns,
        'kernelMode': False,
        **int_params,
        **h_values,
        'headerProtectionKey': header_protection_key,
        'randomTrailers': random_trailers,
        'disableCookies': disable_cookies,
    }
    settings.update(optional_fields)
    return settings


def build_inbound_payload(listen_ip, port, domain, server_settings, enable=False):
    """Build 3x-ui 3.11.0 inbounds/add JSON payload for embedded AMNEZIAWG-3.1."""
    if not isinstance(listen_ip, str):
        raise ValueError('listen_ip must be a string')
    try:
        ipaddress.ip_address(listen_ip)
    except ValueError as exc:
        raise ValueError(f'invalid listen IP: {listen_ip!r}') from exc
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError('port must be an int in 1..65535')
    _reject_control_chars(domain, 'domain')
    if not domain.strip() or any(ch.isspace() for ch in domain):
        raise ValueError('domain must be a non-empty hostname without whitespace')
    if type(enable) is not bool:
        raise ValueError('enable must be a bool')
    if not isinstance(server_settings, dict):
        raise ValueError('server_settings must be a dict')

    revalidated_keys = (
        'jc', 'jmin', 'jmax', 's1', 's2', 's3', 's4', 'h1', 'h2', 'h3', 'h4',
        'primaryDns', 'secondaryDns', 'kernelMode', 'randomTrailers', 'disableCookies',
        *_OPTIONAL_CPS_FIELDS, *_OPTIONAL_RANGE_FIELDS,
    )
    obfs_subset = {k: server_settings[k] for k in revalidated_keys if k in server_settings}
    build_server_settings(
        f"{server_settings.get('subnetIp')}/{server_settings.get('subnetCidr')}",
        server_settings.get('privateKey'),
        server_settings.get('publicKey'),
        server_settings.get('headerProtectionKey'),
        mtu=server_settings.get('mtu'),
        **obfs_subset,
    )

    return {
        'tag': 'AMNEZIAWG-3.1',
        'remark': 'AMNEZIAWG-3.1',
        'enable': enable,
        'listen': listen_ip,
        'port': port,
        'protocol': 'amneziawg',
        'settings': json.dumps({'server': server_settings, 'clients': []}),
        'streamSettings': json.dumps({}),
        'sniffing': json.dumps({'enabled': False}),
        'shareAddrStrategy': 'custom',
        'shareAddr': domain,
    }


def _normalize_client_ip(client_ip):
    if not isinstance(client_ip, str) or not client_ip.strip():
        raise ValueError('client_ip must be a non-empty IPv4 address or /32 CIDR')
    text = client_ip.strip()
    if '/' in text:
        try:
            net = ipaddress.ip_network(text, strict=True)
        except ValueError as exc:
            raise ValueError(f'invalid client_ip CIDR: {client_ip!r}') from exc
        if net.version != 4 or net.prefixlen != 32:
            raise ValueError('client_ip CIDR must be an IPv4 /32 host address')
        return str(net)
    try:
        addr = ipaddress.IPv4Address(text)
    except ValueError as exc:
        raise ValueError(f'invalid IPv4 client_ip: {client_ip!r}') from exc
    return f'{addr}/32'


def build_client_payload(
    email,
    client_ip,
    private_key,
    public_key,
    pre_shared_key='',
    keep_alive=25,
    enable=True,
    sub_id=None,
):
    """Build 3x-ui 3.11.0 client payload for AWG 3.1 clients/add and clients/update."""
    _reject_control_chars(email, 'email')
    if not email.strip() or any(ch.isspace() for ch in email):
        raise ValueError('email must be a non-empty identifier without whitespace')
    normalized_cidr = _normalize_client_ip(client_ip)
    private_key = validate_key(private_key)
    public_key = validate_key(public_key)
    if pre_shared_key:
        pre_shared_key = validate_key(pre_shared_key)
    elif pre_shared_key is None:
        pre_shared_key = ''
    elif not isinstance(pre_shared_key, str):
        raise ValueError('pre_shared_key must be a string')
    if type(keep_alive) is not int or not 0 <= keep_alive <= 65535:
        raise ValueError('keep_alive must be an int in 0..65535')
    if type(enable) is not bool:
        raise ValueError('enable must be a bool')
    if sub_id is None:
        sub_id = secrets.token_urlsafe(24)
    else:
        _reject_control_chars(sub_id, 'sub_id')
        if not sub_id.strip() or any(ch.isspace() for ch in sub_id):
            raise ValueError('sub_id must be a non-empty token without whitespace')

    return {
        'email': email,
        'enable': enable,
        'privateKey': private_key,
        'publicKey': public_key,
        'allowedIPs': [normalized_cidr],
        'preSharedKey': pre_shared_key,
        'keepAlive': keep_alive,
        'subId': sub_id,
    }


def decode_vpn_link(vpn_uri):
    """Decode an AmneziaVPN vpn://<base64url> link into raw .conf text."""
    if not isinstance(vpn_uri, str):
        raise ValueError('vpn_uri must be a string')
    uri = vpn_uri.strip()
    if not uri.startswith('vpn://'):
        raise ValueError('expected vpn:// scheme')
    encoded = uri[6:]
    if not encoded or not _B64URL_RE.fullmatch(encoded):
        raise ValueError('invalid base64url payload in vpn:// URI')
    padded = encoded + '=' * (-len(encoded) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode('ascii'))
        text = raw.decode('utf-8')
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError('unable to decode vpn:// URI payload') from exc
    if '\x00' in text or not text.strip():
        raise ValueError('decoded vpn:// payload is empty or contains null bytes')
    return text


def parse_awg31_conf(text):
    """Strictly parse an AmneziaWG .conf into {'Interface': {...}, 'Peer': {...}}."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError('AWG configuration text is empty')
    sections = {}
    current = None
    for raw_line in text.splitlines():
        if re.search(r'[\x00-\x08\x0b-\x1f\x7f]', raw_line):
            raise ValueError('control character in AWG configuration')
        line = raw_line.strip()
        if not line or line.startswith('#') or line.startswith(';'):
            continue
        if line.startswith('[') and line.endswith(']'):
            name = line[1:-1].strip()
            if name not in ('Interface', 'Peer'):
                raise ValueError(f'unsupported section [{name}] in AWG configuration')
            if name in sections:
                raise ValueError(f'duplicate section [{name}] in AWG configuration')
            sections[name] = {}
            current = sections[name]
            continue
        if current is None or '=' not in line:
            raise ValueError(f'invalid configuration line: {line!r}')
        key, value = line.split('=', 1)
        key, value = key.strip(), value.strip()
        if not key:
            raise ValueError('empty key in AWG configuration')
        if key in current:
            raise ValueError(f'duplicate key {key!r} in AWG configuration')
        current[key] = value
    if set(sections) != {'Interface', 'Peer'}:
        raise ValueError('AWG configuration must contain [Interface] and [Peer] sections')
    return sections


def _normalize_endpoint(host, port):
    host_str = str(host).strip()
    if ':' in host_str and not (host_str.startswith('[') and host_str.endswith(']')):
        return f'[{host_str}]:{port}'
    return f'{host_str}:{port}'


def _parse_bool_flag(raw):
    low = raw.strip().lower()
    if low in ('on', 'true', '1', 'yes'):
        return True
    if low in ('off', 'false', '0', 'no'):
        return False
    raise ValueError(f'invalid boolean AWG value: {raw!r}')


def validate_awg31_conf(text, expected_server, expected_client_pub_or_priv, expected_host, expected_port):
    """Validate decoded .conf strictly has all AWG 3.1 parameters and matches expectations."""
    if not isinstance(expected_server, dict):
        raise ValueError('expected_server must be a dict')
    parsed = parse_awg31_conf(text)
    iface = parsed['Interface']
    peer = parsed['Peer']

    for req_key in ('PrivateKey', 'Address', *_CONF_REQUIRED_AWG31_KEYS):
        if not iface.get(req_key):
            raise ValueError(f'missing required AWG 3.1 [Interface] field: {req_key}')
    for hook_key in _FORBIDDEN_HOOK_KEYS:
        if hook_key in iface:
            raise ValueError(f'forbidden wg-quick hook directive {hook_key} in AWG config')

    client_priv = validate_key(iface['PrivateKey'])
    if isinstance(expected_client_pub_or_priv, dict):
        if expected_client_pub_or_priv.get('privateKey') and client_priv != expected_client_pub_or_priv['privateKey']:
            raise ValueError('exported client PrivateKey mismatch')
        if expected_client_pub_or_priv.get('publicKey'):
            if _x25519_pubkey_from_priv_b64(client_priv) != expected_client_pub_or_priv['publicKey']:
                raise ValueError('exported client PrivateKey does not match expected publicKey')
        if expected_client_pub_or_priv.get('allowedIPs'):
            exported_addrs = {x.strip() for x in iface['Address'].split(',') if x.strip()}
            if not set(expected_client_pub_or_priv['allowedIPs']).issubset(exported_addrs):
                raise ValueError('exported client Address mismatch')
    elif isinstance(expected_client_pub_or_priv, str):
        validate_key(expected_client_pub_or_priv)
        if client_priv != expected_client_pub_or_priv:
            if _x25519_pubkey_from_priv_b64(client_priv) != expected_client_pub_or_priv:
                raise ValueError('exported client key does not match expected private or public key')
    elif expected_client_pub_or_priv is not None:
        raise ValueError('expected_client_pub_or_priv must be a key string, dict, or None')

    for addr_entry in iface['Address'].split(','):
        ipaddress.ip_interface(addr_entry.strip())

    try:
        conf_mtu = int(iface['MTU'])
    except ValueError as exc:
        raise ValueError('invalid MTU in AWG config') from exc
    expected_mtu = expected_server.get('mtu', DEFAULT_MTU)
    if not 1280 <= conf_mtu <= 65535 or conf_mtu != expected_mtu:
        raise ValueError(f'exported MTU {conf_mtu} != expected {expected_mtu}')

    expected_hpk = validate_key(expected_server.get('headerProtectionKey'))
    conf_hpk = validate_key(iface['HeaderProtectionKey'])
    if conf_hpk != expected_hpk:
        raise ValueError('exported HeaderProtectionKey mismatch')

    obfs_map = (
        ('Jc', 'jc'),
        ('Jmin', 'jmin'),
        ('Jmax', 'jmax'),
        ('S1', 's1'),
        ('S2', 's2'),
        ('S3', 's3'),
        ('S4', 's4'),
        ('H1', 'h1'),
        ('H2', 'h2'),
        ('H3', 'h3'),
        ('H4', 'h4'),
    )
    for conf_key, srv_key in obfs_map:
        if srv_key not in expected_server:
            raise ValueError(f'expected_server missing {srv_key}')
        if iface[conf_key] != str(expected_server[srv_key]):
            raise ValueError(f'exported {conf_key}={iface[conf_key]!r} != expected {expected_server[srv_key]!r}')

    for s_key in ('S1', 'S2', 'S3', 'S4'):
        if int(iface[s_key]) < 12:
            raise ValueError(f'AWG 3.1 HeaderProtectionKey requires {s_key} >= 12')

    optional_pairs = (
        ('I1', 'i1'), ('I2', 'i2'), ('I3', 'i3'), ('I4', 'i4'), ('I5', 'i5'),
        ('ContentPaddingAddition', 'contentPaddingAddition'),
        ('RekeyAfterTime', 'rekeyAfterTime'),
        ('RekeyTimeout', 'rekeyTimeout'),
        ('RejectAfterTime', 'rejectAfterTime'),
        ('KeepaliveTimeout', 'keepaliveTimeout'),
        ('MaxHandshakeAttempts', 'maxHandshakeAttempts'),
    )
    for conf_key, srv_key in optional_pairs:
        expected_val = expected_server.get(srv_key)
        if expected_val:
            if iface.get(conf_key) != str(expected_val):
                raise ValueError(f'exported {conf_key} mismatch')

    for conf_key, srv_key in (('RandomTrailers', 'randomTrailers'), ('DisableCookies', 'disableCookies')):
        expected_flag = bool(expected_server.get(srv_key, False))
        if expected_flag:
            if conf_key not in iface or not _parse_bool_flag(iface[conf_key]):
                raise ValueError(f'exported {conf_key} must be enabled')
        elif conf_key in iface and _parse_bool_flag(iface[conf_key]):
            raise ValueError(f'exported {conf_key} unexpectedly enabled')

    expected_srv_pub = validate_key(expected_server.get('publicKey'))
    if validate_key(peer.get('PublicKey')) != expected_srv_pub:
        raise ValueError('exported [Peer] PublicKey mismatch')
    if not peer.get('AllowedIPs'):
        raise ValueError('missing [Peer] AllowedIPs')
    expected_endpoint = _normalize_endpoint(expected_host, expected_port)
    if peer.get('Endpoint') != expected_endpoint:
        raise ValueError(f'exported Endpoint {peer.get("Endpoint")!r} != expected {expected_endpoint!r}')

    return parsed


def conf_to_setconf(conf_text, endpoint_override=None, allowed_ips_override=None):
    """Convert .conf to awg setconf text, stripping Address/DNS/MTU and fixing booleans.

    Returns (setconf_text, address_cidr, mtu).
    """
    parsed = parse_awg31_conf(conf_text)
    iface = parsed['Interface']
    peer = parsed['Peer']

    for hook_key in _FORBIDDEN_HOOK_KEYS:
        if hook_key in iface or hook_key in peer:
            raise ValueError(f'forbidden wg-quick directive {hook_key} in AWG config')

    raw_addr = iface.get('Address', '')
    if not raw_addr:
        raise ValueError('Address missing from [Interface] in AWG config')
    addr_parts = [part.strip() for part in raw_addr.split(',') if part.strip()]
    ipv4_cidrs = []
    for entry in addr_parts:
        addr_obj = ipaddress.ip_interface(entry)
        if addr_obj.version == 4:
            ipv4_cidrs.append(entry)
    address_cidr = ipv4_cidrs[0] if ipv4_cidrs else addr_parts[0]
    ipaddress.ip_interface(address_cidr)

    if 'MTU' in iface:
        try:
            mtu = int(iface['MTU'])
        except ValueError as exc:
            raise ValueError(f'invalid MTU value: {iface["MTU"]!r}') from exc
        if not 1280 <= mtu <= 65535:
            raise ValueError(f'MTU {mtu} out of valid range 1280..65535')
    else:
        mtu = DEFAULT_MTU

    iface_lines = ['[Interface]']
    for key, val in iface.items():
        if key in _SETCONF_STRIP_KEYS:
            continue
        if key in _BOOL_SETCONF_KEYS:
            val = 'on' if _parse_bool_flag(val) else 'off'
        elif val.strip().lower() == 'true':
            val = 'on'
        elif val.strip().lower() == 'false':
            val = 'off'
        iface_lines.append(f'{key} = {val}')

    peer_lines = ['[Peer]']
    for key, val in peer.items():
        norm_key = 'PresharedKey' if key == 'PreSharedKey' else key
        if norm_key == 'Endpoint' and endpoint_override is not None:
            val = str(endpoint_override)
        elif norm_key == 'AllowedIPs' and allowed_ips_override is not None:
            if isinstance(allowed_ips_override, (list, tuple)):
                val = ', '.join(str(x).strip() for x in allowed_ips_override if str(x).strip())
            else:
                val = str(allowed_ips_override).strip()
        peer_lines.append(f'{norm_key} = {val}')

    if endpoint_override is not None and 'Endpoint' not in peer:
        peer_lines.append(f'Endpoint = {endpoint_override}')
    if allowed_ips_override is not None and 'AllowedIPs' not in peer:
        joined = (
            ', '.join(str(x).strip() for x in allowed_ips_override if str(x).strip())
            if isinstance(allowed_ips_override, (list, tuple))
            else str(allowed_ips_override).strip()
        )
        peer_lines.append(f'AllowedIPs = {joined}')

    setconf_text = '\n'.join([*iface_lines, *peer_lines]) + '\n'
    return setconf_text, address_cidr, mtu


def verify_live_listener(port, expected_panel_pid):
    """Verify standalone AWG unit is inactive and expected_panel_pid exclusively owns UDP port."""
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError('port must be an int in 1..65535')
    if type(expected_panel_pid) is not int or expected_panel_pid <= 0:
        raise ValueError('expected_panel_pid must be a positive int')

    try:
        unit_out = subprocess.check_output(
            ['systemctl', 'show', STANDALONE_UNIT, '--property=ActiveState'],
            text=True,
            stderr=subprocess.PIPE,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f'failed to query {STANDALONE_UNIT}: {type(exc).__name__}') from None

    props = dict(line.split('=', 1) for line in unit_out.splitlines() if '=' in line)
    if props.get('ActiveState') != 'inactive':
        raise RuntimeError(
            f'standalone AWG unit {STANDALONE_UNIT} must be inactive, got {props.get("ActiveState")!r}'
        )

    try:
        ss_out = subprocess.check_output(
            ['ss', '-H', '-lunp', f'sport = :{port}'],
            text=True,
            stderr=subprocess.PIPE,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f'failed to inspect UDP listener on port {port}: {type(exc).__name__}') from None

    if not ss_out.strip():
        raise RuntimeError(f'no UDP listener bound on port {port}')
    pids = {int(pid) for pid in re.findall(r'pid=(\d+)', ss_out)}
    if not pids:
        raise RuntimeError(f'unidentified UDP listener on port {port}')
    if pids != {expected_panel_pid}:
        raise RuntimeError(
            f'UDP port {port} owned by unexpected PID(s) {sorted(pids)}; expected [{expected_panel_pid}]'
        )
    return True
