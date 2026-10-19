#!/usr/bin/env bash
# x-ui-update-routing.sh — apply RoscomVPN routing (Happ + INCY) into 3x-ui settings
# Source: https://github.com/hydraponique/roscomvpn-routing
#
# Usage:
#   bash x-ui-update-routing.sh
#   bash x-ui-update-routing.sh -restart n
#   bash x-ui-update-routing.sh -cron y
#
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "Run as root"; exit 1; }

RESTART=y
INSTALL_CRON=n
while [[ $# -gt 0 ]]; do
  case "$1" in
    -restart) RESTART="${2:-y}"; shift 2 ;;
    -cron)    INSTALL_CRON="${2:-y}"; shift 2 ;;
    -h|--help) echo "Usage: $0 [-restart y|n] [-cron y|n]"; exit 0 ;;
    *) echo "Unknown: $1"; exit 1 ;;
  esac
done

DB="/etc/x-ui/x-ui.db"
[[ -f "$DB" ]] || { echo "ERROR: $DB not found"; exit 1; }

LIB="/usr/local/lib/3x-ui-pro"
DIR="$LIB/roscomvpn-routing"
UPDATER="$LIB/update-roscomvpn-routing.sh"
mkdir -p "$DIR" "$LIB"

HAPP_JSON_URL="https://raw.githubusercontent.com/hydraponique/roscomvpn-routing/main/HAPP/DEFAULT.JSON"
INCY_JSON_URL="https://raw.githubusercontent.com/hydraponique/roscomvpn-routing/main/INCY/DEFAULT.JSON"
HAPP_DL_URL="https://raw.githubusercontent.com/hydraponique/roscomvpn-routing/main/HAPP/DEFAULT.DEEPLINK"
INCY_DL_URL="https://raw.githubusercontent.com/hydraponique/roscomvpn-routing/main/INCY/DEFAULT.DEEPLINK"

echo "[*] Downloading RoscomVPN routing profiles..."
ok=0
for pair in \
  "happ.json|$HAPP_JSON_URL" \
  "incy.json|$INCY_JSON_URL" \
  "happ.deeplink|$HAPP_DL_URL" \
  "incy.deeplink|$INCY_DL_URL"
do
  name="${pair%%|*}"
  url="${pair#*|}"
  if curl -fsSL --max-time 30 "$url" -o "$DIR/$name"; then
    echo "  + $name"
    ok=$((ok+1))
  else
    echo "  ! failed: $name"
  fi
done
[[ "$ok" -ge 2 ]] || { echo "ERROR: could not download routing files"; exit 1; }

HAPP_RULES=""
INCY_RULES=""
[[ -s "$DIR/happ.deeplink" ]] && HAPP_RULES=$(tr -d '\r\n' < "$DIR/happ.deeplink")
[[ -s "$DIR/incy.deeplink" ]] && INCY_RULES=$(tr -d '\r\n' < "$DIR/incy.deeplink")
[[ -z "$HAPP_RULES" && -s "$DIR/happ.json" ]] && HAPP_RULES=$(cat "$DIR/happ.json")
[[ -z "$INCY_RULES" && -s "$DIR/incy.json" ]] && INCY_RULES=$(cat "$DIR/incy.json")
JSON_RULES="$HAPP_JSON_URL"

export HAPP_RULES INCY_RULES JSON_RULES
python3 - "$DB" << 'PY'
import os, sqlite3, sys

DB = sys.argv[1]
happ = os.environ.get("HAPP_RULES") or ""
incy = os.environ.get("INCY_RULES") or ""
js = os.environ.get("JSON_RULES") or ""

db = sqlite3.connect(DB)
c = db.cursor()

def upsert(key, value):
    row = c.execute("SELECT id FROM settings WHERE key=?", (key,)).fetchone()
    if row:
        c.execute("UPDATE settings SET value=? WHERE key=?", (value, key))
    else:
        c.execute("INSERT INTO settings (key, value) VALUES (?, ?)", (key, value))

upsert("subEnableRouting", "true")
if happ:
    upsert("subRoutingRules", happ)
upsert("subIncyEnableRouting", "true")
if incy:
    upsert("subIncyRoutingRules", incy)
if js:
    upsert("subJsonRoutingRules", js)

db.commit()
db.close()
print("[*] 3x-ui settings updated (Happ + INCY + JSON routing)")
PY

echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) updated" > "$DIR/last-update.txt"

# Stable cron target (works even when this script was run via process substitution)
cat > "$UPDATER" << 'UPD'
#!/usr/bin/env bash
set -euo pipefail
[[ $EUID -eq 0 ]] || exit 1
DB="/etc/x-ui/x-ui.db"
[[ -f "$DB" ]] || exit 1
DIR="/usr/local/lib/3x-ui-pro/roscomvpn-routing"
mkdir -p "$DIR"
HAPP_JSON_URL="https://raw.githubusercontent.com/hydraponique/roscomvpn-routing/main/HAPP/DEFAULT.JSON"
INCY_JSON_URL="https://raw.githubusercontent.com/hydraponique/roscomvpn-routing/main/INCY/DEFAULT.JSON"
HAPP_DL_URL="https://raw.githubusercontent.com/hydraponique/roscomvpn-routing/main/HAPP/DEFAULT.DEEPLINK"
INCY_DL_URL="https://raw.githubusercontent.com/hydraponique/roscomvpn-routing/main/INCY/DEFAULT.DEEPLINK"
for pair in "happ.json|$HAPP_JSON_URL" "incy.json|$INCY_JSON_URL" "happ.deeplink|$HAPP_DL_URL" "incy.deeplink|$INCY_DL_URL"; do
  name="${pair%%|*}"; url="${pair#*|}"
  curl -fsSL --max-time 30 "$url" -o "$DIR/$name" 2>/dev/null || true
done
HAPP_RULES=""; INCY_RULES=""
[[ -s "$DIR/happ.deeplink" ]] && HAPP_RULES=$(tr -d '\r\n' < "$DIR/happ.deeplink")
[[ -s "$DIR/incy.deeplink" ]] && INCY_RULES=$(tr -d '\r\n' < "$DIR/incy.deeplink")
[[ -z "$HAPP_RULES" && -s "$DIR/happ.json" ]] && HAPP_RULES=$(cat "$DIR/happ.json")
[[ -z "$INCY_RULES" && -s "$DIR/incy.json" ]] && INCY_RULES=$(cat "$DIR/incy.json")
JSON_RULES="$HAPP_JSON_URL"
export HAPP_RULES INCY_RULES JSON_RULES
python3 - "$DB" << 'PY'
import os, sqlite3, sys
DB = sys.argv[1]
db = sqlite3.connect(DB); c = db.cursor()
def upsert(k, v):
    if c.execute("SELECT id FROM settings WHERE key=?", (k,)).fetchone():
        c.execute("UPDATE settings SET value=? WHERE key=?", (v, k))
    else:
        c.execute("INSERT INTO settings (key, value) VALUES (?, ?)", (k, v))
upsert("subEnableRouting", "true")
upsert("subIncyEnableRouting", "true")
if os.environ.get("HAPP_RULES"): upsert("subRoutingRules", os.environ["HAPP_RULES"])
if os.environ.get("INCY_RULES"): upsert("subIncyRoutingRules", os.environ["INCY_RULES"])
if os.environ.get("JSON_RULES"): upsert("subJsonRoutingRules", os.environ["JSON_RULES"])
db.commit(); db.close()
PY
echo "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$DIR/last-update.txt"
UPD
chmod +x "$UPDATER"
echo "[*] Installed updater: $UPDATER"

if [[ "$INSTALL_CRON" == "y" ]]; then
  crontab -l 2>/dev/null | grep -v "update-roscomvpn\|roscomvpn-routing" | crontab - 2>/dev/null || true
  (crontab -l 2>/dev/null; echo '0 4 * * * /usr/local/lib/3x-ui-pro/update-roscomvpn-routing.sh >> /var/log/roscomvpn-routing.log 2>&1') | crontab -
  echo "[*] Cron installed: daily 04:00"
fi

if [[ "$RESTART" == "y" ]]; then
  if command -v x-ui >/dev/null 2>&1; then
    x-ui restart 2>/dev/null || systemctl restart x-ui 2>/dev/null || true
  else
    systemctl restart x-ui 2>/dev/null || true
  fi
  echo "[*] x-ui restarted"
fi
echo "[*] Done. Happ/INCY will pick up routing on next subscription refresh."
