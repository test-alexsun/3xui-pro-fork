#!/usr/bin/env bash
# x-ui-db-fix.sh — repair 3x-ui-pro-fork inbound settings in SQLite
#
# Fixes:
#   1. clients[].tgId / limitIp / totalGB / expiryTime / reset as strings → numbers
#   2. TUIC flat/Xray-style settings → server + clients (3x-ui shape)
#   3. AmneziaWG secretKey/peers style → server + clients + obfuscation
#   4. Optional: restart x-ui
#
# Usage (on the VPS as root):
#   bash x-ui-db-fix.sh
#   bash x-ui-db-fix.sh -restart n
#   bash <(curl -fsSL https://raw.githubusercontent.com/test-alexsun/3xui-pro-fork/main/x-ui-db-fix.sh)
#
set -euo pipefail

[[ $EUID -eq 0 ]] || { echo "Run as root"; exit 1; }

RESTART=y
while [[ $# -gt 0 ]]; do
  case "$1" in
    -restart) RESTART="${2:-y}"; shift 2 ;;
    *) echo "Unknown arg: $1"; exit 1 ;;
  esac
done

DB="/etc/x-ui/x-ui.db"
[[ -f "$DB" ]] || { echo "ERROR: $DB not found"; exit 1; }

# Backup
BKP="/root/x-ui.db.bak-fix-$(date +%Y%m%d-%H%M%S)"
cp -a "$DB" "$BKP"
echo "[*] Backup: $BKP"

python3 - "$DB" << 'PY'
import json, sqlite3, sys, secrets, string, subprocess, base64, os

DB = sys.argv[1]
XRAY_CANDIDATES = [
    "/usr/local/x-ui/bin/xray-linux-amd64",
    "/usr/local/x-ui/bin/xray-linux-arm64",
    "/usr/local/x-ui/bin/xray-linux-arm",
]

def xray_bin():
    for p in XRAY_CANDIDATES:
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    return None

def wg_keypair():
    xb = xray_bin()
    if not xb:
        # fallback random base64-ish keys (panel may regenerate publicKey)
        priv = base64.b64encode(secrets.token_bytes(32)).decode()
        return priv, priv
    out = subprocess.check_output([xb, "wg"], text=True)
    priv = pub = None
    for line in out.splitlines():
        if line.startswith("PrivateKey:"):
            priv = line.split(":", 1)[1].strip()
        elif "PublicKey" in line or line.startswith("Password"):
            pub = line.split()[-1]
    return priv, pub

def rnd(n=16):
    return "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(n))

def gen_hpk():
    return base64.b64encode(secrets.token_bytes(32)).decode()

def rand_int(a, b):
    return secrets.randbelow(b - a + 1) + a

def gen_obfuscation():
    jmin = rand_int(40, 89)
    s1 = rand_int(15, 150)
    s2 = rand_int(15, 150)
    while s1 + 56 == s2:
        s2 = rand_int(15, 150)
    h_max = 2147483647
    lo = 5
    band = (h_max - lo + 1) // 4
    hvals = [str(rand_int(lo + i * band, lo + (i + 1) * band - 1)) for i in range(4)]
    cp_lo = rand_int(8, 24)
    rekey_lo = rand_int(100, 120)
    rekey_hi = rekey_lo + rand_int(10, 40)
    reject_lo = rekey_hi + rand_int(30, 60)
    rekey_to_lo = rand_int(3, 6)
    ka_lo = rand_int(8, 12)
    att_lo = rand_int(15, 25)
    return {
        "jc": rand_int(3, 6),
        "jmin": jmin,
        "jmax": jmin + rand_int(50, 250),
        "s1": s1, "s2": s2,
        "s3": rand_int(12, 55),
        "s4": rand_int(12, 27),
        "h1": hvals[0], "h2": hvals[1], "h3": hvals[2], "h4": hvals[3],
        "i1": f"<r {rand_int(32, 256)}>",
        "i2": "", "i3": "", "i4": "", "i5": "",
        "headerProtectionKey": gen_hpk(),
        "contentPaddingAddition": f"{cp_lo}-{cp_lo + rand_int(8, 40)}",
        "rekeyAfterTime": f"{rekey_lo}-{rekey_hi}",
        "rekeyTimeout": f"{rekey_to_lo}-{rekey_to_lo + rand_int(1, 4)}",
        "rejectAfterTime": f"{reject_lo}-{reject_lo + rand_int(30, 90)}",
        "keepaliveTimeout": f"{ka_lo}-{ka_lo + rand_int(2, 8)}",
        "maxHandshakeAttempts": f"{att_lo}-{att_lo + rand_int(5, 25)}",
        "randomTrailers": True,
        "disableCookies": True,
    }

def fix_int_fields(obj):
    changed = False
    if not isinstance(obj, dict):
        return False
    for key in ("tgId", "limitIp", "totalGB", "expiryTime", "reset", "created_at", "updated_at"):
        if key not in obj:
            continue
        v = obj[key]
        if isinstance(v, str):
            s = v.strip().replace(" ", "")
            if s == "" or not s.lstrip("-").isdigit():
                obj[key] = 0
            else:
                obj[key] = int(s)
            changed = True
        elif v is None:
            obj[key] = 0
            changed = True
    return changed

def detect_domain(c):
    # webCertFile in settings, or hosts address
    try:
        row = c.execute("SELECT value FROM settings WHERE key='webCertFile'").fetchone()
        if row and row[0]:
            # /root/cert/domain/fullchain.pem or /etc/letsencrypt/live/domain/fullchain.pem
            path = row[0]
            parts = path.strip("/").split("/")
            if "live" in parts:
                i = parts.index("live")
                if i + 1 < len(parts):
                    return parts[i + 1]
            if "cert" in parts:
                i = parts.index("cert")
                if i + 1 < len(parts):
                    return parts[i + 1]
    except Exception:
        pass
    try:
        row = c.execute("SELECT address FROM hosts WHERE address LIKE '%.%' LIMIT 1").fetchone()
        if row:
            return row[0]
    except Exception:
        pass
    return "localhost"

def cert_paths(domain):
    for base in (f"/root/cert/{domain}", f"/etc/letsencrypt/live/{domain}"):
        full = f"{base}/fullchain.pem"
        key = f"{base}/privkey.pem"
        if os.path.isfile(full) and os.path.isfile(key):
            return full, key
    return f"/root/cert/{domain}/fullchain.pem", f"/root/cert/{domain}/privkey.pem"

db = sqlite3.connect(DB)
c = db.cursor()
domain = detect_domain(c)
cert, key = cert_paths(domain)
print(f"[*] domain={domain}")
print(f"[*] cert={cert}")

stats = {"tgId": 0, "tuic": 0, "amneziawg": 0, "inbounds": 0}

rows = c.execute(
    "SELECT id, protocol, port, settings, stream_settings, remark FROM inbounds ORDER BY id"
).fetchall()

for iid, protocol, port, raw, stream_raw, remark in rows:
    try:
        s = json.loads(raw or "{}")
    except Exception as e:
        print(f"[!] inbound {iid}: bad JSON settings: {e}")
        continue
    changed = False
    protocol = (protocol or "").lower()

    # --- 1) fix clients int fields ---
    clients = s.get("clients")
    if isinstance(clients, list):
        for cl in clients:
            if fix_int_fields(cl):
                changed = True
                stats["tgId"] += 1

    # --- 2) TUIC ---
    if protocol == "tuic":
        needs = "server" not in s or not isinstance(s.get("server"), dict)
        # also fix if still has auth_timeout string / heartbeat
        if needs or "auth_timeout" in s or "heartbeat" in s or "tlsSettings" in (json.loads(stream_raw or "{}") if stream_raw else {}):
            old_clients = s.get("clients") if isinstance(s.get("clients"), list) else []
            # preserve clients, normalize ints
            for cl in old_clients:
                fix_int_fields(cl)
            if not old_clients:
                import uuid as uuidlib
                u = str(uuidlib.uuid4())
                old_clients = [{
                    "uuid": u, "id": u, "password": rnd(16),
                    "email": "tuic-default", "limitIp": 0, "totalGB": 0,
                    "expiryTime": 0, "enable": True, "tgId": 0,
                    "subId": rnd(16), "comment": "TUIC v5 (fixed)", "reset": 0,
                }]
            s = {
                "server": {
                    "certificate": cert,
                    "private_key": key,
                    "congestion_control": "bbr",
                    "alpn": ["h3", "spdy/3.1"],
                    "udp_relay_mode": "native",
                    "zero_rtt_handshake": True,
                    "log_level": "info",
                    "max_idle_time": 15,
                    "authentication_timeout": 3,
                    "max_udp_relay_packet_size": 1500,
                    "sni": domain,
                },
                "clients": old_clients,
            }
            c.execute(
                "UPDATE inbounds SET settings=?, stream_settings=? WHERE id=?",
                (json.dumps(s, ensure_ascii=False), "{}", iid),
            )
            print(f"[+] TUIC id={iid} port={port} → server+clients")
            stats["tuic"] += 1
            changed = False  # already written
            stats["inbounds"] += 1
            continue

    # --- 3) AmneziaWG ---
    if protocol == "amneziawg":
        if "server" not in s or not isinstance(s.get("server"), dict):
            # old secretKey / peers shape
            idx = stats["amneziawg"]
            subnet = f"10.8.{idx + 1}.0"
            priv, pub = wg_keypair()
            old_clients = s.get("clients") if isinstance(s.get("clients"), list) else []
            for cl in old_clients:
                fix_int_fields(cl)
            s = {
                "server": {
                    "privateKey": priv,
                    "publicKey": pub,
                    "subnetIp": subnet,
                    "subnetCidr": 24,
                    "mtu": 1420,
                    "primaryDns": "8.8.8.8",
                    "secondaryDns": "8.8.4.4",
                    "externalInterface": "",
                    "ipv6Enabled": False,
                    "ipv6Subnet": "",
                    "ipv6ExternalInterface": "",
                    **gen_obfuscation(),
                },
                "clients": old_clients,
            }
            c.execute(
                "UPDATE inbounds SET settings=?, stream_settings=? WHERE id=?",
                (json.dumps(s, ensure_ascii=False), "{}", iid),
            )
            print(f"[+] AmneziaWG id={iid} port={port} subnet={subnet}/24")
            stats["amneziawg"] += 1
            stats["inbounds"] += 1
            continue

    if changed:
        c.execute(
            "UPDATE inbounds SET settings=? WHERE id=?",
            (json.dumps(s, ensure_ascii=False), iid),
        )
        print(f"[+] clients ints fixed id={iid} ({protocol})")
        stats["inbounds"] += 1

# clients table (newer 3x-ui)
try:
    cols = {r[1] for r in c.execute("PRAGMA table_info(clients)")}
    if cols:
        col = "tg_id" if "tg_id" in cols else ("tgId" if "tgId" in cols else None)
        if col:
            c.execute(f"UPDATE clients SET {col}=0 WHERE typeof({col})='text' OR {col} IS NULL OR {col}=''")
            print(f"[+] clients.{col} normalized")
except Exception as e:
    print(f"[*] clients table skip: {e}")

db.commit()
db.close()

print("─── summary ───")
print(f"  tgId/int fields fixed : {stats['tgId']}")
print(f"  TUIC rebuilt          : {stats['tuic']}")
print(f"  AmneziaWG rebuilt     : {stats['amneziawg']}")
print(f"  inbounds updated      : {stats['inbounds']}")
print("done")
PY

if [[ "$RESTART" == "y" ]]; then
  echo "[*] Restarting x-ui..."
  if command -v x-ui >/dev/null 2>&1; then
    x-ui restart || systemctl restart x-ui
  else
    systemctl restart x-ui
  fi
  sleep 2
  systemctl is-active x-ui 2>/dev/null || true
  echo "[*] Done. Refresh the panel and try saving clients again."
else
  echo "[*] Skipped restart (-restart n). Run: x-ui restart"
fi
