#!/usr/bin/env bash
# x-ui-rename-remarks.sh — rename inbound (+ optional hosts) remarks to CC-subdomain |
#
# Usage (on EACH node, as root):
#   bash x-ui-rename-remarks.sh
#   bash x-ui-rename-remarks.sh -domain ee3.alexsun55.ru
#   bash x-ui-rename-remarks.sh -label ee3 -cc DE
#   bash x-ui-rename-remarks.sh -prefix 'DE-ee3 |'
#   bash x-ui-rename-remarks.sh -hosts y    # also rewrite hosts.remark
#   bash x-ui-rename-remarks.sh -restart n
#
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "Run as root"; exit 1; }

DOMAIN=""
LABEL=""
CC=""
PREFIX=""
DO_HOSTS=y
RESTART=y

while [[ $# -gt 0 ]]; do
  case "$1" in
    -domain)  DOMAIN="${2:-}"; shift 2 ;;
    -label)   LABEL="${2:-}"; shift 2 ;;
    -cc)      CC="${2:-}"; shift 2 ;;
    -prefix)  PREFIX="${2:-}"; shift 2 ;;
    -hosts)   DO_HOSTS="${2:-y}"; shift 2 ;;
    -restart) RESTART="${2:-y}"; shift 2 ;;
    -h|--help) sed -n '2,18p' "$0"; exit 0 ;;
    *) echo "Unknown: $1"; exit 1 ;;
  esac
done

DB="/etc/x-ui/x-ui.db"
[[ -f "$DB" ]] || { echo "ERROR: $DB not found"; exit 1; }

BKP="/root/x-ui.db.bak-rename-$(date +%Y%m%d-%H%M%S)"
cp -a "$DB" "$BKP"
echo "[*] Backup: $BKP"

export RENAME_DOMAIN="$DOMAIN" RENAME_LABEL="$LABEL" RENAME_CC="$CC"
export RENAME_PREFIX="$PREFIX" RENAME_HOSTS="$DO_HOSTS"

python3 - "$DB" << 'PY'
import json, os, re, sqlite3, sys, urllib.request

DB = sys.argv[1]

def detect_domain(c):
    env = (os.environ.get("RENAME_DOMAIN") or "").strip()
    if env:
        return env
    try:
        r = c.execute("SELECT address FROM hosts WHERE address LIKE '%.%' LIMIT 1").fetchone()
        if r and r[0]:
            return r[0]
    except Exception:
        pass
    try:
        r = c.execute("SELECT value FROM settings WHERE key='webCertFile'").fetchone()
        if r and r[0]:
            parts = r[0].strip("/").split("/")
            if "live" in parts:
                return parts[parts.index("live") + 1]
            if "cert" in parts:
                return parts[parts.index("cert") + 1]
    except Exception:
        pass
    return ""

def country_code():
    env = (os.environ.get("RENAME_CC") or "").strip().upper()
    if env:
        return env
    try:
        with urllib.request.urlopen("https://ipwho.is/", timeout=8) as resp:
            data = json.loads(resp.read().decode())
            cc = (data.get("country_code") or "SRV").upper()
            if cc and cc != "NULL":
                return cc
    except Exception:
        pass
    return "SRV"

def node_label(domain, explicit=""):
    explicit = (explicit or "").strip().lower()
    if explicit:
        return re.sub(r"[^a-z0-9-]", "", explicit) or "node"
    if not domain:
        return "node"
    label = domain.split(".")[0].lower()
    return re.sub(r"[^a-z0-9-]", "", label) or "node"

# Match: "DE |", "DE|", "DE-ee2 |", "RU-h3|"
PREFIX_RE = re.compile(
    r"^(?P<head>(?:[A-Z]{2,3}|SRV)(?:-[a-z0-9-]+)?)\s*\|\s*"
)

def apply_prefix(text, prefix):
    text = text or ""
    m = PREFIX_RE.match(text)
    if m:
        return prefix + text[m.end():]
    return prefix + text.lstrip()

db = sqlite3.connect(DB)
c = db.cursor()
domain = detect_domain(c)
cc = country_code()
label = node_label(domain, os.environ.get("RENAME_LABEL") or "")
prefix = (os.environ.get("RENAME_PREFIX") or "").strip()
if not prefix:
    prefix = f"{cc}-{label} |"
if prefix.endswith("|"):
    prefix = prefix + " "
elif not prefix.endswith(" |"):
    prefix = prefix.rstrip() + " "

print(f"[*] domain={domain or '(unknown)'}  prefix={prefix!r}")

# --- inbounds.remark ---
n_ib = 0
for iid, remark in c.execute("SELECT id, remark FROM inbounds ORDER BY id"):
    new = apply_prefix(remark or "", prefix)
    if new != (remark or ""):
        c.execute("UPDATE inbounds SET remark=? WHERE id=?", (new, iid))
        print(f"  inbound {iid}: {(remark or '')!r}")
        print(f"           → {new!r}")
        n_ib += 1
    else:
        print(f"  inbound {iid}: unchanged")

# --- clients inside settings JSON (comment field) ---
n_cl = 0
for iid, raw in c.execute("SELECT id, settings FROM inbounds"):
    try:
        s = json.loads(raw or "{}")
    except Exception:
        continue
    changed = False
    clients = s.get("clients")
    if isinstance(clients, list):
        for cl in clients:
            if not isinstance(cl, dict):
                continue
            for key in ("comment", "email"):
                val = cl.get(key)
                if isinstance(val, str) and PREFIX_RE.match(val):
                    cl[key] = apply_prefix(val, prefix)
                    changed = True
                    n_cl += 1
    if changed:
        c.execute(
            "UPDATE inbounds SET settings=? WHERE id=?",
            (json.dumps(s, ensure_ascii=False), iid),
        )

# --- hosts.remark (short names → include node label) ---
n_h = 0
if (os.environ.get("RENAME_HOSTS") or "y").lower() in ("y", "yes", "1"):
    cols = {r[1] for r in c.execute("PRAGMA table_info(hosts)")}
    if "remark" in cols:
        for hid, hremark, addr in c.execute(
            "SELECT id, remark, address FROM hosts ORDER BY id"
        ):
            hremark = hremark or ""
            # If already has CC-label prefix, rewrite; else prepend label for clarity
            if PREFIX_RE.match(hremark):
                new_h = apply_prefix(hremark, prefix)
            else:
                # e.g. "awg" → "ee3-awg", "REALITY + Vision" → "ee3-REALITY + Vision"
                if hremark.startswith(f"{label}-"):
                    new_h = hremark
                else:
                    new_h = f"{label}-{hremark}" if hremark else f"{label}-host"
            if new_h != hremark:
                c.execute("UPDATE hosts SET remark=? WHERE id=?", (new_h, hid))
                print(f"  host {hid} ({addr}): {hremark!r} → {new_h!r}")
                n_h += 1

db.commit()
db.close()
print(f"[*] inbounds updated: {n_ib}, client fields: {n_cl}, hosts: {n_h}")
print("done")
PY

# drop panel UI caches if any
rm -f /usr/local/x-ui/bin/config.json.bak 2>/dev/null || true

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

echo
echo "=== Next steps ==="
echo "1) Run this on EVERY node (ee2, ee3, h3, ...)."
echo "2) On MASTER panel: Nodes → open each node → Save (or toggle enable) to re-sync."
echo "3) Hosts page: refresh; if old names remain, edit host remark or delete+re-import hosts."
echo "4) Hard-refresh browser (Ctrl+F5)."
