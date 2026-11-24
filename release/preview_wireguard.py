"""Standalone WireGuard protocol helpers and validators for 3x-ui 3.11.0 / Xray 26.11.9.

Strictly independent from AmneziaWG 3.1: never invokes external AWG binaries,
never touches the reserved AWG port, and actively rejects obfuscation keys.
"""
import base64
import ipaddress
from pathlib import Path
import re
import secrets
import subprocess
import urllib.parse

WG_PROTOCOL = 'wireguard'
WG_TAG = 'WIREGUARD'
WG_REMARK = 'WIREGUARD'
WG_DEFAULT_PORT = 51820
WG_DEFAULT_MTU = 1420
WG_DEFAULT_KEEPALIVE = 25
AWG_RESERVED_PORT = 29177
XRAY_BIN = '/opt/3xui-pro-fork/panel/bin/xray-linux-amd64'

RFC1918_NETWORKS = (
    ipaddress.IPv4Network('10.0.0.0/8'),
    ipaddress.IPv4Network('172.16.0.0/12'),
    ipaddress.IPv4Network('192.168.0.0/16'),
)

_P = (1 << 255) - 19
_A24 = 121665
_BASEPOINT = b'\x09' + (b'\x00' * 31)

_CANONICAL_AWG_KEYS = (
    'Jc', 'Jmin', 'Jmax',
    'S1', 'S2', 'S3', 'S4',
    'H1', 'H2', 'H3', 'H4',
    'I1', 'I2', 'I3', 'I4', 'I5',
    'HeaderProtectionKey',
    'ContentPaddingAddition',
    'RandomTrailers',
    'DisableCookies',
)


class _CaseInsensitiveKeySet(frozenset):
    """Frozenset supporting case-insensitive string membership checks."""

    def __contains__(self, item):
        if isinstance(item, str):
            return super().__contains__(item.casefold())
        return False


AWG_CONTAMINATION_KEYS = _CaseInsensitiveKeySet(k.casefold() for k in _CANONICAL_AWG_KEYS)

_CONF_INTERFACE_KEYS = {
    'privatekey': 'private_key',
    'address': 'address',
    'mtu': 'mtu',
    'dns': 'dns',
    'listenport': 'listen_port',
}
_CONF_PEER_KEYS = {
    'publickey': 'public_key',
    'presharedkey': 'preshared_key',
    'allowedips': 'allowed_ips',
    'endpoint': 'endpoint',
    'persistentkeepalive': 'persistent_keepalive',
}
_LINK_ALLOWED_QUERY_KEYS = frozenset({
    'publickey',
    'address',
    'mtu',
    'keepalive',
    'presharedkey',
    'allowedips',
    'dns',
    'reserved',
})

_DOMAIN_RE = re.compile(
    r'^(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}$'
)
_EMAIL_RE = re.compile(r'^[A-Za-z0-9._@+-]{1,128}$')
_SUB_ID_RE = re.compile(r'^[A-Za-z0-9_-]{4,128}$')


def _reject_awg_key(key):
    if isinstance(key, str) and key in AWG_CONTAMINATION_KEYS:
        raise ValueError(f'AWG contamination parameter rejected in WireGuard config: {key}')


def _reject_awg_mapping(mapping, context='WireGuard settings'):
    if not isinstance(mapping, dict):
        return
    for key in mapping:
        if isinstance(key, str) and key in AWG_CONTAMINATION_KEYS:
            raise ValueError(f'AWG contamination key rejected in {context}: {key}')


def clamp_scalar(scalar):
    """Apply RFC 7748 Section 5 scalar clamping to a 32-byte key."""
    if not isinstance(scalar, (bytes, bytearray)) or len(scalar) != 32:
        raise ValueError('X25519 scalar must be exactly 32 bytes')
    buf = bytearray(scalar)
    buf[0] &= 248
    buf[31] &= 127
    buf[31] |= 64
    return bytes(buf)


def x25519_scalarmult(scalar, u_point):
    """Compute RFC 7748 X25519(scalar, u_point) in pure Python over GF(2^255 - 19)."""
    if not isinstance(u_point, (bytes, bytearray)) or len(u_point) != 32:
        raise ValueError('X25519 u-coordinate must be exactly 32 bytes')
    k = int.from_bytes(clamp_scalar(scalar), 'little')
    u_buf = bytearray(u_point)
    u_buf[31] &= 127
    x_1 = int.from_bytes(u_buf, 'little') % _P

    x_2 = 1
    z_2 = 0
    x_3 = x_1
    z_3 = 1
    swap = 0

    for bit in range(254, -1, -1):
        k_t = (k >> bit) & 1
        swap ^= k_t
        if swap:
            x_2, x_3 = x_3, x_2
            z_2, z_3 = z_3, z_2
        swap = k_t

        a_sum = (x_2 + z_2) % _P
        aa = (a_sum * a_sum) % _P
        b_diff = (x_2 - z_2) % _P
        bb = (b_diff * b_diff) % _P
        e_diff = (aa - bb) % _P
        c_sum = (x_3 + z_3) % _P
        d_diff = (x_3 - z_3) % _P
        da = (d_diff * a_sum) % _P
        cb = (c_sum * b_diff) % _P
        x_3 = pow((da + cb) % _P, 2, _P)
        z_3 = (x_1 * pow((da - cb) % _P, 2, _P)) % _P
        x_2 = (aa * bb) % _P
        z_2 = (e_diff * (aa + _A24 * e_diff)) % _P

    if swap:
        x_2, x_3 = x_3, x_2
        z_2, z_3 = z_3, z_2

    result = (x_2 * pow(z_2, _P - 2, _P)) % _P
    return result.to_bytes(32, 'little')


def validate_key(value):
    """Validate a WireGuard standard-base64 32-byte non-zero key."""
    if not isinstance(value, str) or not value.isascii() or any(c.isspace() for c in value):
        raise ValueError('invalid WireGuard key format')
    if len(value) != 44:
        raise ValueError('invalid WireGuard key length')
    try:
        raw = base64.b64decode(value, validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError('invalid WireGuard base64 key') from exc
    if len(raw) != 32 or base64.b64encode(raw).decode('ascii') != value:
        raise ValueError('non-canonical WireGuard key')
    if raw == b'\x00' * 32:
        raise ValueError('all-zero WireGuard key rejected')
    return value


def public_key_from_private(priv_b64):
    """Derive the WireGuard X25519 public key from a base64 private key."""
    validate_key(priv_b64)
    priv_raw = base64.b64decode(priv_b64, validate=True)
    pub_raw = x25519_scalarmult(priv_raw, _BASEPOINT)
    if pub_raw == b'\x00' * 32:
        raise ValueError('derived public key is zero')
    return base64.b64encode(pub_raw).decode('ascii')


def generate_keypair():
    """Generate a clamped RFC 7748 X25519 (private_b64, public_b64) pair."""
    priv_raw = clamp_scalar(secrets.token_bytes(32))
    priv_b64 = base64.b64encode(priv_raw).decode('ascii')
    pub_b64 = public_key_from_private(priv_b64)
    return priv_b64, pub_b64


def validate_subnet(subnet_str):
    """Validate an RFC1918 IPv4 /16../30 WireGuard tunnel subnet.

    Returns (network, server_ip_str, list_of_client_ips).
    """
    if not isinstance(subnet_str, str) or '/' not in subnet_str:
        raise ValueError('WireGuard subnet must be an IPv4 CIDR string')
    try:
        network = ipaddress.ip_network(subnet_str, strict=True)
    except ValueError as exc:
        raise ValueError('invalid WireGuard subnet CIDR') from exc
    if network.version != 4:
        raise ValueError('WireGuard tunnel subnet must be IPv4')
    if not 16 <= network.prefixlen <= 30:
        raise ValueError('WireGuard tunnel subnet prefix must be between /16 and /30')
    if not any(network.subnet_of(rfc) for rfc in RFC1918_NETWORKS):
        raise ValueError('WireGuard tunnel subnet must lie strictly inside RFC1918 space')
    hosts = [str(host) for host in network.hosts()]
    if len(hosts) < 2:
        raise ValueError('WireGuard tunnel subnet lacks server and client hosts')
    return network, hosts[0], hosts[1:]


def validate_subnet_disjoint(subnet_str, other_subnets):
    """Refuse WireGuard subnet overlap against reserved or existing subnets."""
    network, _, _ = validate_subnet(subnet_str)
    if not other_subnets:
        return network
    for other in other_subnets:
        try:
            other_net = ipaddress.ip_network(other, strict=False)
        except ValueError as exc:
            raise ValueError(f'invalid comparison subnet: {other}') from exc
        if other_net.version == 4 and network.overlaps(other_net):
            raise ValueError(f'WireGuard subnet {network} overlaps existing subnet {other_net}')
    return network


def allocate_client_ip(subnet_str, used_cidrs=(), reserved_subnets=()):
    """Allocate the next unused host IP inside subnet_str, skipping .0, .1, and broadcast."""
    network, server_ip_str, client_ips = validate_subnet(subnet_str)
    if reserved_subnets:
        validate_subnet_disjoint(subnet_str, reserved_subnets)

    used_nets = []
    for entry in used_cidrs or ():
        if not isinstance(entry, str) or not entry.strip():
            raise ValueError('invalid used CIDR entry')
        try:
            used_net = ipaddress.ip_network(entry.strip(), strict=False)
        except ValueError as exc:
            raise ValueError(f'invalid used CIDR: {entry}') from exc
        if used_net.version != 4:
            raise ValueError('used WireGuard CIDR must be IPv4')
        used_nets.append(used_net)

    server_addr = ipaddress.IPv4Address(server_ip_str)
    for candidate in client_ips:
        addr = ipaddress.IPv4Address(candidate)
        if addr == server_addr:
            continue
        if any(addr in net for net in used_nets):
            continue
        return candidate
    raise ValueError(f'WireGuard subnet {network} is exhausted')


def _validate_port(port):
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError('invalid WireGuard UDP port')
    if port == AWG_RESERVED_PORT:
        raise ValueError(f'port {AWG_RESERVED_PORT} is reserved and forbidden for WireGuard')
    return port


def _validate_mtu(mtu):
    if type(mtu) is not int or not 1280 <= mtu <= 65535:
        raise ValueError('WireGuard MTU must be an integer between 1280 and 65535')
    return mtu


def _validate_host(host, label='host'):
    if not isinstance(host, str) or not host or any(c.isspace() for c in host):
        raise ValueError(f'invalid WireGuard {label}')
    try:
        ipaddress.ip_address(host)
        return host
    except ValueError:
        if _DOMAIN_RE.fullmatch(host):
            return host
    raise ValueError(f'invalid WireGuard {label}: {host}')


def _normalize_client_cidr(client_ip):
    if not isinstance(client_ip, str) or not client_ip.strip():
        raise ValueError('client IP is required')
    try:
        iface = ipaddress.ip_interface(client_ip.strip())
    except ValueError as exc:
        raise ValueError('invalid WireGuard client IP') from exc
    if iface.version != 4 or iface.network.prefixlen != 32:
        raise ValueError('WireGuard client address must be an IPv4 /32 host')
    if iface.ip.is_unspecified or iface.ip.is_multicast:
        raise ValueError('invalid WireGuard client host address')
    return f'{iface.ip}/32'


def build_inbound_payload(listen_ip, port, domain, subnet_str, server_private_key,
                          mtu=WG_DEFAULT_MTU, enable=True):
    """Build the 3x-ui 3.11.0 native WireGuard inbound payload."""
    if not isinstance(listen_ip, str):
        raise ValueError('listen_ip must be an IP address string')
    try:
        listen_addr = str(ipaddress.ip_address(listen_ip))
    except ValueError as exc:
        raise ValueError('invalid WireGuard listen_ip') from exc
    _validate_port(port)
    _validate_host(domain, label='domain')
    network, _, _ = validate_subnet(subnet_str)
    validate_key(server_private_key)
    _validate_mtu(mtu)
    if type(enable) is not bool:
        raise ValueError('enable must be a bool')

    return {
        'tag': WG_TAG,
        'remark': WG_REMARK,
        'enable': enable,
        'listen': listen_addr,
        'port': port,
        'protocol': WG_PROTOCOL,
        'settings': {
            'secretKey': server_private_key,
            'peers': [],
            'clients': [],
            'mtu': mtu,
            'noKernelTun': True,
            'subnetIp': str(network.network_address),
            'subnetCidr': network.prefixlen,
        },
        'streamSettings': {},
        'sniffing': {'enabled': False},
        'shareAddrStrategy': 'custom',
        'shareAddr': domain,
    }


def verify_inbound_settings(settings, stream_settings=None):
    """Enforce native Xray WireGuard runtime invariants (including noKernelTun: True)."""
    if not isinstance(settings, dict):
        raise ValueError('WireGuard inbound settings must be a dict')
    _reject_awg_mapping(settings, context='inbound settings')
    if settings.get('kernelMode'):
        raise ValueError('kernelMode is not permitted for native Xray WireGuard')
    if settings.get('noKernelTun') is not True:
        raise ValueError('WireGuard inbound settings must enforce noKernelTun=True')
    validate_key(settings.get('secretKey'))
    _validate_mtu(settings.get('mtu'))
    subnet_ip = settings.get('subnetIp')
    subnet_cidr = settings.get('subnetCidr')
    if not isinstance(subnet_ip, str) or type(subnet_cidr) is not int:
        raise ValueError('WireGuard inbound settings require valid subnetIp and subnetCidr')
    validate_subnet(f'{subnet_ip}/{subnet_cidr}')
    if stream_settings is not None:
        if not isinstance(stream_settings, dict):
            raise ValueError('WireGuard streamSettings must be a dict')
        _reject_awg_mapping(stream_settings, context='streamSettings')
    return True


def build_client_payload(email, client_ip, private_key=None, public_key=None,
                         pre_shared_key='', keep_alive=WG_DEFAULT_KEEPALIVE,
                         enable=True, sub_id=None):
    """Build a 3x-ui 3.11.0 WireGuard client payload with a verified X25519 keypair."""
    if not isinstance(email, str) or not _EMAIL_RE.fullmatch(email) or '..' in email:
        raise ValueError('invalid WireGuard client email')
    cidr = _normalize_client_cidr(client_ip)
    if type(enable) is not bool:
        raise ValueError('enable must be a bool')
    if type(keep_alive) is not int or not 0 <= keep_alive <= 65535:
        raise ValueError('keep_alive must be an integer between 0 and 65535')

    if private_key is None and public_key is None:
        priv_b64, pub_b64 = generate_keypair()
    elif private_key is not None and public_key is None:
        priv_b64 = validate_key(private_key)
        pub_b64 = public_key_from_private(priv_b64)
    elif private_key is not None and public_key is not None:
        priv_b64 = validate_key(private_key)
        pub_b64 = validate_key(public_key)
        if public_key_from_private(priv_b64) != pub_b64:
            raise ValueError('WireGuard client publicKey does not match privateKey')
    else:
        raise ValueError('private_key is required when public_key is specified')

    if pre_shared_key in ('', None):
        psk = ''
    else:
        psk = validate_key(pre_shared_key)

    if sub_id is None:
        resolved_sub_id = secrets.token_urlsafe(24)
    else:
        if not isinstance(sub_id, str) or not _SUB_ID_RE.fullmatch(sub_id):
            raise ValueError('invalid WireGuard subId')
        resolved_sub_id = sub_id

    return {
        'email': email,
        'enable': enable,
        'privateKey': priv_b64,
        'publicKey': pub_b64,
        'allowedIPs': [cidr],
        'preSharedKey': psk,
        'keepAlive': keep_alive,
        'subId': resolved_sub_id,
    }


def rotate_client_keys(client, private_key=None, public_key=None):
    """Return an updated copy of client with rotated matching WireGuard keys."""
    if not isinstance(client, dict):
        raise ValueError('client must be a dict')
    _reject_awg_mapping(client, context='client')
    old_priv = client.get('privateKey')
    old_pub = client.get('publicKey')
    allowed = client.get('allowedIPs') or []
    if len(allowed) != 1:
        raise ValueError('client must have exactly one allowedIPs host CIDR')

    if private_key is None and public_key is None:
        new_priv, new_pub = generate_keypair()
        while new_priv == old_priv:
            new_priv, new_pub = generate_keypair()
    else:
        new_priv = private_key
        new_pub = public_key

    updated = build_client_payload(
        email=client['email'],
        client_ip=allowed[0],
        private_key=new_priv,
        public_key=new_pub,
        pre_shared_key=client.get('preSharedKey', ''),
        keep_alive=client.get('keepAlive', WG_DEFAULT_KEEPALIVE),
        enable=client.get('enable', True),
        sub_id=client.get('subId'),
    )
    if updated['privateKey'] == old_priv or updated['publicKey'] == old_pub:
        raise ValueError('rotated keys must differ from previous client keys')
    return updated


def _format_endpoint(host, port):
    host = _validate_host(host, label='endpoint host')
    _validate_port(port)
    try:
        addr = ipaddress.ip_address(host)
        if addr.version == 6:
            return f'[{host}]:{port}'
    except ValueError:
        pass
    return f'{host}:{port}'


def _split_endpoint(value):
    if not isinstance(value, str) or not value or any(c.isspace() for c in value):
        raise ValueError('invalid WireGuard Endpoint')
    if value.startswith('['):
        if ']:' not in value:
            raise ValueError('invalid bracketed IPv6 WireGuard Endpoint')
        host_part, port_part = value[1:].split(']:', 1)
        try:
            addr = ipaddress.ip_address(host_part)
        except ValueError as exc:
            raise ValueError('invalid IPv6 host in Endpoint') from exc
        if addr.version != 6:
            raise ValueError('bracketed host in Endpoint must be IPv6')
        host = str(addr)
    else:
        if value.count(':') != 1:
            raise ValueError('invalid WireGuard Endpoint host:port')
        host, port_part = value.split(':', 1)
        host = _validate_host(host, label='Endpoint host')
    try:
        port = int(port_part)
    except ValueError as exc:
        raise ValueError('invalid WireGuard Endpoint port') from exc
    _validate_port(port)
    return host, port


def render_client_conf(endpoint_host, port, server_public_key, client,
                       allowed_ips=('198.18.0.10/32',), dns='', mtu=WG_DEFAULT_MTU):
    """Render a clean standard WireGuard .conf client profile (zero AWG params)."""
    if not isinstance(client, dict):
        raise ValueError('client must be a dict')
    _reject_awg_mapping(client, context='client')
    endpoint = _format_endpoint(endpoint_host, port)
    server_pub = validate_key(server_public_key)
    client_priv = validate_key(client.get('privateKey'))
    if client.get('publicKey'):
        if public_key_from_private(client_priv) != validate_key(client['publicKey']):
            raise ValueError('client publicKey does not match privateKey')

    raw_addresses = client.get('allowedIPs') or ()
    if not raw_addresses:
        raise ValueError('client allowedIPs is required for Address')
    addresses = [_normalize_client_cidr(item) for item in raw_addresses]

    if isinstance(allowed_ips, str):
        peer_cidrs = [x.strip() for x in allowed_ips.split(',') if x.strip()]
    else:
        peer_cidrs = [str(x).strip() for x in allowed_ips if str(x).strip()]
    if not peer_cidrs:
        raise ValueError('peer allowed_ips must be non-empty')
    validated_allowed = [str(ipaddress.ip_network(item, strict=False)) for item in peer_cidrs]

    dns_items = []
    if dns:
        raw_dns = dns.split(',') if isinstance(dns, str) else dns
        for item in raw_dns:
            item_str = str(item).strip()
            if item_str:
                dns_items.append(str(ipaddress.ip_address(item_str)))

    lines = [
        '[Interface]',
        f'PrivateKey = {client_priv}',
        'Address = ' + ', '.join(addresses),
    ]
    if dns_items:
        lines.append('DNS = ' + ', '.join(dns_items))
    if mtu is not None:
        lines.append(f'MTU = {_validate_mtu(mtu)}')

    lines.extend([
        '',
        '[Peer]',
        f'PublicKey = {server_pub}',
        'AllowedIPs = ' + ', '.join(validated_allowed),
        f'Endpoint = {endpoint}',
    ])
    psk = client.get('preSharedKey', '')
    if psk:
        lines.append(f'PresharedKey = {validate_key(psk)}')
    keep_alive = client.get('keepAlive', WG_DEFAULT_KEEPALIVE)
    if type(keep_alive) is not int or not 0 <= keep_alive <= 65535:
        raise ValueError('invalid WireGuard keepAlive')
    if keep_alive > 0:
        lines.append(f'PersistentKeepalive = {keep_alive}')
    return '\n'.join(lines) + '\n'


def parse_client_conf(text):
    """Parse and validate a standard WireGuard .conf file, rejecting any AWG parameter."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError('WireGuard .conf text must be non-empty')

    sections = {}
    current = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#') or line.startswith(';'):
            continue
        if line.startswith('[') and line.endswith(']'):
            section_name = line[1:-1].strip()
            if section_name not in ('Interface', 'Peer'):
                raise ValueError(f'unsupported WireGuard section: [{section_name}]')
            if section_name in sections:
                raise ValueError(f'duplicate WireGuard section: [{section_name}]')
            sections[section_name] = {}
            current = section_name
            continue
        if current is None:
            raise ValueError('WireGuard configuration line outside section')
        if '=' not in line:
            raise ValueError('malformed WireGuard configuration line')
        key_raw, val_raw = line.split('=', 1)
        key = key_raw.strip()
        val = val_raw.strip()
        _reject_awg_key(key)

        key_cf = key.casefold()
        allowed_map = _CONF_INTERFACE_KEYS if current == 'Interface' else _CONF_PEER_KEYS
        if key_cf not in allowed_map:
            raise ValueError(f'unsupported WireGuard [{current}] key: {key}')
        norm_key = allowed_map[key_cf]
        if norm_key in sections[current]:
            raise ValueError(f'duplicate WireGuard [{current}] key: {key}')
        sections[current][norm_key] = val

    if set(sections) != {'Interface', 'Peer'}:
        raise ValueError('WireGuard .conf must contain exactly [Interface] and [Peer]')

    iface = sections['Interface']
    peer = sections['Peer']

    priv_key = validate_key(iface.get('private_key'))
    if 'address' not in iface or not iface['address']:
        raise ValueError('WireGuard [Interface] missing Address')
    addresses = [
        str(ipaddress.ip_interface(item.strip()))
        for item in iface['address'].split(',') if item.strip()
    ]
    if not addresses:
        raise ValueError('WireGuard [Interface] Address cannot be empty')

    mtu = None
    if 'mtu' in iface:
        try:
            mtu = _validate_mtu(int(iface['mtu']))
        except ValueError as exc:
            raise ValueError('invalid WireGuard [Interface] MTU') from exc

    listen_port = None
    if 'listen_port' in iface:
        try:
            listen_port = _validate_port(int(iface['listen_port']))
        except ValueError as exc:
            raise ValueError('invalid WireGuard [Interface] ListenPort') from exc

    dns_list = []
    if 'dns' in iface and iface['dns']:
        dns_list = [str(ipaddress.ip_address(item.strip()))
                    for item in iface['dns'].split(',') if item.strip()]

    pub_key = validate_key(peer.get('public_key'))
    psk = validate_key(peer['preshared_key']) if peer.get('preshared_key') else ''
    if 'allowed_ips' not in peer or not peer['allowed_ips']:
        raise ValueError('WireGuard [Peer] missing AllowedIPs')
    allowed_ips = [
        str(ipaddress.ip_network(item.strip(), strict=False))
        for item in peer['allowed_ips'].split(',') if item.strip()
    ]
    if not allowed_ips:
        raise ValueError('WireGuard [Peer] AllowedIPs cannot be empty')
    if 'endpoint' not in peer:
        raise ValueError('WireGuard [Peer] missing Endpoint')
    endpoint_host, endpoint_port = _split_endpoint(peer['endpoint'])

    keepalive = None
    if 'persistent_keepalive' in peer:
        try:
            keepalive = int(peer['persistent_keepalive'])
        except ValueError as exc:
            raise ValueError('invalid WireGuard PersistentKeepalive') from exc
        if not 0 <= keepalive <= 65535:
            raise ValueError('WireGuard PersistentKeepalive out of range')

    return {
        'interface': {
            'private_key': priv_key,
            'addresses': addresses,
            'mtu': mtu,
            'dns': dns_list,
            'listen_port': listen_port,
        },
        'peer': {
            'public_key': pub_key,
            'preshared_key': psk,
            'allowed_ips': allowed_ips,
            'endpoint_host': endpoint_host,
            'endpoint_port': endpoint_port,
            'persistent_keepalive': keepalive,
        },
    }


def parse_wireguard_link(uri):
    """Parse and validate a standard wireguard:// URI, rejecting AWG query params."""
    if not isinstance(uri, str) or not uri or any(ord(c) < 32 for c in uri):
        raise ValueError('invalid wireguard:// URI')
    if '://' not in uri:
        raise ValueError('missing URI scheme')
    scheme, rest = uri.split('://', 1)
    if scheme.casefold() != 'wireguard':
        raise ValueError(f'unexpected URI scheme for WireGuard: {scheme}')

    if '#' in rest:
        before_frag, frag_raw = rest.split('#', 1)
        remark = urllib.parse.unquote(frag_raw)
    else:
        before_frag = rest
        remark = ''

    if '?' in before_frag:
        authority, query_raw = before_frag.split('?', 1)
    else:
        authority = before_frag
        query_raw = ''

    if any(c.isspace() for c in authority) or any(c.isspace() for c in query_raw):
        raise ValueError('whitespace not allowed in wireguard:// URI authority or query')
    if '@' not in authority:
        raise ValueError('wireguard:// URI missing private key userinfo')
    priv_raw, host_port = authority.rsplit('@', 1)
    if not priv_raw or not host_port:
        raise ValueError('wireguard:// URI missing credentials or endpoint')

    client_priv = validate_key(urllib.parse.unquote(priv_raw))
    host, port = _split_endpoint(host_port)

    params = {}
    if query_raw:
        for pair in query_raw.split('&'):
            if not pair:
                continue
            if '=' not in pair:
                raise ValueError('malformed wireguard:// query parameter')
            raw_k, raw_v = pair.split('=', 1)
            k = urllib.parse.unquote(raw_k).strip()
            v = urllib.parse.unquote(raw_v).strip()
            _reject_awg_key(k)
            k_cf = k.casefold()
            if k_cf not in _LINK_ALLOWED_QUERY_KEYS:
                raise ValueError(f'unsupported wireguard:// query parameter: {k}')
            if k_cf in params:
                raise ValueError(f'duplicate wireguard:// query parameter: {k}')
            params[k_cf] = v

    if 'publickey' not in params:
        raise ValueError('wireguard:// URI missing publickey parameter')
    server_pub = validate_key(params['publickey'])

    addresses = []
    if 'address' in params and params['address']:
        addresses = [
            str(ipaddress.ip_interface(item.strip()))
            for item in params['address'].split(',') if item.strip()
        ]
    if not addresses:
        raise ValueError('wireguard:// URI missing address parameter')

    mtu = None
    if 'mtu' in params and params['mtu']:
        try:
            mtu = _validate_mtu(int(params['mtu']))
        except ValueError as exc:
            raise ValueError('invalid wireguard:// mtu parameter') from exc

    keepalive = None
    if 'keepalive' in params and params['keepalive']:
        try:
            keepalive = int(params['keepalive'])
        except ValueError as exc:
            raise ValueError('invalid wireguard:// keepalive parameter') from exc
        if not 0 <= keepalive <= 65535:
            raise ValueError('wireguard:// keepalive out of range')

    psk = validate_key(params['presharedkey']) if params.get('presharedkey') else ''

    allowed_ips = []
    if 'allowedips' in params and params['allowedips']:
        allowed_ips = [
            str(ipaddress.ip_network(item.strip(), strict=False))
            for item in params['allowedips'].split(',') if item.strip()
        ]

    dns_list = []
    if 'dns' in params and params['dns']:
        dns_list = [
            str(ipaddress.ip_address(item.strip()))
            for item in params['dns'].split(',') if item.strip()
        ]

    if 'reserved' in params and params['reserved']:
        parts = [p.strip() for p in params['reserved'].split(',')]
        if len(parts) != 3 or not all(p.isdigit() and 0 <= int(p) <= 255 for p in parts):
            raise ValueError('invalid wireguard:// reserved parameter')

    return {
        'scheme': 'wireguard',
        'client_private_key': client_priv,
        'host': host,
        'port': port,
        'public_key': server_pub,
        'addresses': addresses,
        'mtu': mtu,
        'keepalive': keepalive,
        'preshared_key': psk,
        'allowed_ips': allowed_ips,
        'dns': dns_list,
        'remark': remark,
        'params': params,
    }


def validate_wireguard_link(uri, expected_host, expected_port,
                            expected_server_pub, expected_client_priv,
                            expected_address=None):
    """Validate a wireguard:// link against expected server and client identity."""
    parsed = parse_wireguard_link(uri)
    expected_host_norm = _validate_host(expected_host, label='expected host')
    _validate_port(expected_port)
    expected_server_pub_norm = validate_key(expected_server_pub)
    expected_client_priv_norm = validate_key(expected_client_priv)

    if parsed['host'].casefold() != expected_host_norm.casefold():
        raise ValueError(f"wireguard:// host mismatch: {parsed['host']} != {expected_host_norm}")
    if parsed['port'] != expected_port:
        raise ValueError(f"wireguard:// port mismatch: {parsed['port']} != {expected_port}")
    if parsed['public_key'] != expected_server_pub_norm:
        raise ValueError('wireguard:// server publickey mismatch')
    if parsed['client_private_key'] != expected_client_priv_norm:
        raise ValueError('wireguard:// client privateKey mismatch')

    if expected_address is not None:
        if isinstance(expected_address, str):
            expected_cidrs = [_normalize_client_cidr(expected_address)]
        else:
            expected_cidrs = [_normalize_client_cidr(item) for item in expected_address]
        if not set(expected_cidrs).issubset(set(parsed['addresses'])):
            raise ValueError('wireguard:// client address mismatch')

    return parsed


def verify_live_listener(port, expected_xray_pid):
    """Verify via ss -H -lunp and /proc/<pid>/comm that exact Xray PID owns UDP port."""
    if type(port) is not int or not 1 <= port <= 65535:
        raise RuntimeError('invalid WireGuard UDP port')
    if port == AWG_RESERVED_PORT:
        raise RuntimeError(f'port {AWG_RESERVED_PORT} is reserved for AWG; WireGuard forbidden')
    if type(expected_xray_pid) is not int or expected_xray_pid <= 0:
        raise RuntimeError('expected Xray PID must be a positive integer')

    try:
        output = subprocess.check_output(
            ['ss', '-H', '-lunp', f'sport = :{port}'],
            text=True,
            stderr=subprocess.PIPE,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f'failed to inspect UDP listener on port {port}') from exc

    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError(f'no live WireGuard UDP listener on port {port}')

    all_pids = []
    for line in lines:
        line_pids = [int(match) for match in re.findall(r'pid=(\d+)', line)]
        if not line_pids:
            raise RuntimeError(f'unidentified UDP listener on port {port}')
        all_pids.extend(line_pids)

    if len(all_pids) != 1 or len(lines) != 1:
        raise RuntimeError(f'duplicate or multiple UDP listener PIDs on port {port}: {all_pids}')

    owner_pid = all_pids[0]
    if owner_pid != expected_xray_pid:
        raise RuntimeError(
            f'WireGuard UDP port {port} owned by PID {owner_pid}, expected Xray PID {expected_xray_pid}'
        )

    comm_path = Path(f'/proc/{owner_pid}/comm')
    try:
        comm = comm_path.read_text(encoding='utf-8').strip()
    except OSError as exc:
        raise RuntimeError(f'cannot read {comm_path} for WireGuard listener verification') from exc

    if 'awg' in comm.casefold() or 'amnezia' in comm.casefold():
        raise RuntimeError(f'forbidden AWG process {comm!r} found on WireGuard port {port}')
    if comm not in ('xray', 'xray-linux-amd6', 'xray-linux-amd64'):
        raise RuntimeError(f'unexpected process {comm!r} owning WireGuard UDP port {port}')

    return owner_pid
