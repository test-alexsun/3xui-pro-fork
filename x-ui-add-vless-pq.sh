#!/usr/bin/env bash
# x-ui-add-vless-pq.sh — add VLESS Encryption (ML-KEM-768 PQ) + XHTTP + REALITY
# to an existing 3x-ui / 3x-ui-pro-fork install.
#
# Usage (root on the VPS):
#   bash <(curl -fsSL https://raw.githubusercontent.com/test-alexsun/3xui-pro-fork/main/x-ui-add-vless-pq.sh)
#   bash x-ui-add-vless-pq.sh -restart n
#
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "Run as root"; exit 1; }

RESTART=y
while [[ $# -gt 0 ]]; do
  case "$1" in
    -restart) RESTART="${2:-y}"; shift 2 ;;
    *) echo "Unknown: $1"; exit 1 ;;
  esac
done

DB="/etc/x-ui/x-ui.db"
[[ -f "$DB" ]] || { echo "ERROR: $DB not found — is 3x-ui installed?"; exit 1; }

# xray binary
_arch() {
  case "$(uname -m)" in
    x86_64|amd64) echo amd64 ;;
    aarch64|arm64) echo arm64 ;;
    armv7*|armv6*) echo arm ;;
    *) echo amd64 ;;
  esac
}
XRAY="/usr/local/x-ui/bin/xray-linux-$(_arch)"
[[ -x "$XRAY" ]] || XRAY="/usr/local/x-ui/bin/xray-linux-arm"
[[ -x "$XRAY" ]] || { echo "ERROR: xray binary not found"; exit 1; }

BKP="/root/x-ui.db.bak-vless-pq-$(date +%Y%m%d-%H%M%S)"
cp -a "$DB" "$BKP"
echo "[*] Backup: $BKP"

python3 - "$DB" "$XRAY" << 'PY'
import json, os, random, secrets, sqlite3, string, subprocess, sys, uuid

DB, XRAY = sys.argv[1], sys.argv[2]

def free_port():
    import socket
    for _ in range(40):
        p = secrets.randbelow(40000) + 10000
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("0.0.0.0", p))
                return p
            except OSError:
                continue
    raise SystemExit("no free port")

def rnd(n=16):
    return "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(n))

def gen_group_id():
    return "".join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(16))

# --- vlessenc PQ pair ---
out = subprocess.check_output([XRAY, "vlessenc"], text=True)
decryption = encryption = None
in_pq = False
for line in out.splitlines():
    if "ML-KEM-768" in line:
        in_pq = True
        continue
    if in_pq and "decryption" in line:
        decryption = line.split('"')[3] if line.count('"') >= 4 else None
        # also try regex-ish
        if "mlkem" in line.lower():
            parts = line.split('"')
            for i, p in enumerate(parts):
                if p.strip().endswith("decryption") or p.strip() == "decryption":
                    pass
            import re
            m = re.search(r'"decryption"\s*:\s*"([^"]+)"', line)
            if m:
                decryption = m.group(1)
    if in_pq and "encryption" in line:
        import re
        m = re.search(r'"encryption"\s*:\s*"([^"]+)"', line)
        if m:
            encryption = m.group(1)
            break
if not decryption or not encryption:
    # fallback parse all mlkem lines after ML-KEM header
    import re
    block = out.split("ML-KEM-768", 1)[-1]
    dm = re.search(r'"decryption"\s*:\s*"([^"]+)"', block)
    em = re.search(r'"encryption"\s*:\s*"([^"]+)"', block)
    decryption = dm.group(1) if dm else None
    encryption = em.group(1) if em else None
if not decryption or not encryption:
    print("ERROR: could not parse xray vlessenc ML-KEM-768 keys")
    print(out[:500])
    raise SystemExit(1)

print(f"[*] PQ decryption: {decryption[:48]}...")
print(f"[*] PQ encryption: {encryption[:48]}...")

db = sqlite3.connect(DB)
c = db.cursor()

# skip if already exists
exist = c.execute(
    "SELECT id, port FROM inbounds WHERE remark LIKE '%Encryption (PQ)%' OR remark LIKE '%VLESS Encryption%'"
).fetchone()
if exist:
    print(f"[!] VLESS Encryption PQ already present: id={exist[0]} port={exist[1]}")
    print("    Remove it in the panel first if you want to recreate.")
    db.close()
    raise SystemExit(0)

# REALITY keys from existing reality inbound (port 8443 or security reality)
reality = None
for row in c.execute("SELECT id, stream_settings, settings FROM inbounds WHERE protocol='vless'"):
    try:
        st = json.loads(row[1] or "{}")
    except Exception:
        continue
    if st.get("security") == "reality" and "realitySettings" in st:
        reality = st["realitySettings"]
        break
if not reality:
    print("ERROR: no REALITY inbound found — install 3x-ui-pro-fork first or create REALITY inbound")
    raise SystemExit(1)

priv = reality.get("privateKey") or ""
pub = (reality.get("settings") or {}).get("publicKey") or ""
shorts = reality.get("shortIds") or ["00"]
server_names = reality.get("serverNames") or ["www.example.com"]
target = reality.get("target") or reality.get("dest") or "127.0.0.1:9443"
if not priv or not pub:
    print("ERROR: REALITY privateKey/publicKey missing in existing inbound")
    raise SystemExit(1)

# domain from hosts / settings
domain = "localhost"
try:
    r = c.execute("SELECT address FROM hosts WHERE address LIKE '%.%' LIMIT 1").fetchone()
    if r:
        domain = r[0]
except Exception:
    pass
try:
    r = c.execute("SELECT value FROM settings WHERE key='webCertFile'").fetchone()
    if r and r[0]:
        parts = r[0].strip("/").split("/")
        if "live" in parts:
            domain = parts[parts.index("live") + 1]
        elif "cert" in parts:
            domain = parts[parts.index("cert") + 1]
except Exception:
    pass

port = free_port()
path = rnd(10)
client_uuid = str(uuid.uuid4())
sub_id = rnd(16)
tag = f"inbound-{port}"

settings = {
    "clients": [{
        "id": client_uuid,
        "flow": "xtls-rprx-vision",
        "email": "vless-pq-default",
        "limitIp": 0,
        "totalGB": 0,
        "expiryTime": 0,
        "enable": True,
        "tgId": 0,
        "subId": sub_id,
        "comment": "VLESS Encryption ML-KEM-768",
        "reset": 0,
    }],
    "decryption": decryption,
    "encryption": encryption,
}
stream = {
    "network": "xhttp",
    "security": "reality",
    "realitySettings": {
        "show": False,
        "xver": 0,
        "target": target,
        "serverNames": server_names,
        "privateKey": priv,
        "minClient": "",
        "maxClient": "",
        "maxTimediff": 0,
        "shortIds": shorts,
        "settings": {
            "publicKey": pub,
            "fingerprint": "firefox",
            "serverName": "",
            "spiderX": "/",
        },
    },
    "xhttpSettings": {
        "path": f"/{path}",
        "host": "",
        "headers": {},
        "scMaxBufferedPosts": 30,
        "scMaxEachPostBytes": "1000000",
        "noSSEHeader": False,
        "xPaddingBytes": "100-1000",
        "mode": "auto",
    },
}
sniff = {
    "enabled": True,
    "destOverride": ["http", "tls", "quic", "fakedns"],
    "metadataOnly": False,
    "routeOnly": False,
}

# country prefix for remark
cc = "SRV"
try:
    import urllib.request
    with urllib.request.urlopen("https://ipwho.is/", timeout=6) as resp:
        data = json.loads(resp.read().decode())
        cc = (data.get("country_code") or "SRV").upper()
except Exception:
    pass
remark = f"{cc} | 🔐 VLESS Encryption (PQ)"

c.execute(
    """INSERT INTO inbounds
       (user_id, up, down, total, remark, enable, expiry_time, listen, port, protocol,
        settings, stream_settings, tag, sniffing)
       VALUES (1,0,0,0,?,1,0,'',?,?,?,?,?,?)""",
    (
        remark,
        port,
        "vless",
        json.dumps(settings, ensure_ascii=False),
        json.dumps(stream, ensure_ascii=False),
        tag,
        json.dumps(sniff),
    ),
)
iid = c.execute("SELECT id FROM inbounds WHERE tag=?", (tag,)).fetchone()[0]

# hosts
cols = [r[1] for r in c.execute("PRAGMA table_info(hosts)")]
if "group_id" in cols:
    c.execute(
        """INSERT INTO hosts (inbound_id, group_id, sort_order, remark, address, port, security, fingerprint, alpn)
           VALUES (?,?,0,'VLESS Encryption PQ',?,?,'same','','[]')""",
        (iid, gen_group_id(), domain, port),
    )
else:
    c.execute(
        """INSERT INTO hosts (inbound_id, sort_order, remark, address, port, security, fingerprint, alpn)
           VALUES (?,0,'VLESS Encryption PQ',?,?,'same','','[]')""",
        (iid, domain, port),
    )

db.commit()
db.close()

# firewall (optional — ufw / firewalld / skip)
def open_port(port: int) -> None:
    import shutil
    if shutil.which("ufw"):
        r = subprocess.run(["ufw", "allow", f"{port}/tcp"], capture_output=True, text=True)
        print(f"[*] ufw allow {port}/tcp → {r.returncode}")
        return
    if shutil.which("firewall-cmd"):
        r = subprocess.run(
            ["firewall-cmd", "--permanent", f"--add-port={port}/tcp"],
            capture_output=True, text=True,
        )
        subprocess.run(["firewall-cmd", "--reload"], capture_output=True)
        print(f"[*] firewalld allow {port}/tcp → {r.returncode}")
        return
    print(f"[!] No ufw/firewalld — open TCP {port} manually if a firewall is active")

open_port(port)

print("─── VLESS Encryption (PQ) added ───")
print(f"  inbound id : {iid}")
print(f"  port       : {port}")
print(f"  uuid       : {client_uuid}")
print(f"  path       : /{path}")
print(f"  flow       : xtls-rprx-vision")
print(f"  encryption : ML-KEM-768 (post-quantum)")
print(f"  domain     : {domain}")
print(f"  SNI/REALITY: {server_names}")
print(f"  remark     : {remark}")
print("Done. Restart x-ui and open the client QR/link in the panel.")
PY

if [[ "$RESTART" == "y" ]]; then
  echo "[*] Restarting x-ui..."
  if command -v x-ui >/dev/null 2>&1; then
    x-ui restart 2>/dev/null || systemctl restart x-ui
  else
    systemctl restart x-ui
  fi
  sleep 2
  systemctl is-active x-ui 2>/dev/null || true
fi
