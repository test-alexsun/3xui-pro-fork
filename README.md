# 3x-ui-pro Extended Installer

Расширенный установщик панели **[3x-ui](https://github.com/MHSanaei/3x-ui)** на базе [mozaroc/3x-ui-pro](https://github.com/mozaroc/3x-ui-pro).

Одна команда ставит панель, nginx, SSL, подписку Clash и сразу создаёт inbound’ы по основным протоколам — включая антиблок-варианты (REALITY + Vision, XHTTP + REALITY, Hysteria2 на UDP 443).

---

## Возможности

| Компонент | Описание |
|-----------|----------|
| **3x-ui** | VPN-панель с веб-интерфейсом |
| **nginx** | Обратный прокси, SNI-роутинг на порт 443 |
| **certbot** | Let's Encrypt SSL (автообновление) |
| **Clash-подписка** | Выдача `clash.yaml` по User-Agent |
| **Диагностика** | MTR + LibreSpeed в браузере |
| **Fake-site** | Случайный HTML-сайт-прикрытие |
| **Firewall (UFW)** | Автооткрытие нужных портов |

### Протоколы (создаются при установке)

| Протокол | Порт / путь | Примечание |
|----------|-------------|------------|
| **VLESS + REALITY + Vision** | 8443 → nginx **:443** | flow `xtls-rprx-vision`, клиент с UUID, `tgId: 0` |
| **VLESS + WebSocket + TLS** | path → nginx **:443** | |
| **VLESS + XHTTP + TLS** | path → nginx **:443** (Unix-сокет) | через nginx |
| **VLESS + XHTTP + REALITY** | отдельный TCP | прямой REALITY, клиент с UUID |
| **VLESS Encryption (PQ)** | отдельный TCP | ML-KEM-768 + XHTTP + REALITY + Vision |
| **Trojan + gRPC + TLS** | path → nginx **:443** | |
| **VMess + WebSocket + TLS** | path → nginx **:443** | |
| **Shadowsocks 2022** | свой TCP+UDP | method `2022-blake3-aes-128-gcm` |
| **Hysteria2** | **UDP 443** | тот же порт, что HTTPS (TCP) |
| **TUIC v5** | отдельный UDP + TLS | |
| **AmneziaWG** | отдельный UDP | схема 3x-ui `server` + obfuscation |
| **AmneziaWG 3.1** | отдельный UDP | отдельная подсеть и параметры |
| **WireGuard** | отдельный UDP | |
| **MTProto** | отдельный TCP | для Telegram |
| **Mixed (SOCKS5 + HTTP)** | отдельный TCP | **user/pass создаётся автоматически** |
| **MASQUE** | TCP+UDP + TLS | CONNECT-IP HTTP/3+HTTP/2, user/pass |

### Антиблок

- **REALITY + Vision** — основной канал против DPI  
- **XHTTP + REALITY** — запасной «веб-подобный» транспорт  
- **VLESS Encryption (ML-KEM-768)** — post-quantum + XHTTP + REALITY  
- **Hysteria2 на UDP 443** — рядом с HTTPS, меньше «лишних» портов  
- **AmneziaWG / 3.1** — WireGuard с обфускацией (panel-native)

### Названия inbound’ов

Формат: `код_страны | emoji название`, например:

`AL | 🔒 VLESS REALITY + Vision` · `AL | ⚡ Hysteria2 (UDP 443)` · `AL | 🔧 Mixed SOCKS5 + HTTP`

Код страны берётся по IP сервера (без emoji-флагов — они часто отображаются как «кубик»).

---

## Nginx: расположение и роль в связке

Скрипт ставит **nginx-full** как фронт на **:443**. TLS для «обычных» протоколов терминируется на nginx, REALITY идёт мимо TLS nginx (SNI → Xray).

### Схема трафика

```
Клиент
  │
  ▼
:443 TCP  ── nginx stream (ssl_preread / SNI)
  │
  ├─ SNI = reality_domain  →  127.0.0.1:8443  (Xray VLESS REALITY)
  │
  └─ SNI = subdomain       →  127.0.0.1:7443  (nginx HTTP vhost + TLS)
                                │
                                ├─ /ws|vmess|trojan paths  → Xray (WS/gRPC)
                                ├─ /xhttp_path             → Unix-сокет XHTTP
                                ├─ /sub_path               → подписка 3x-ui
                                └─ /                       → fake-site
```

UDP **443** (Hysteria2) nginx **не** трогает — слушает Xray напрямую.

### Файлы на сервере

| Путь | Назначение |
|------|------------|
| `/etc/nginx/nginx.conf` | Основной конфиг; подключены `stream` и `ngx_stream_module` |
| `/etc/nginx/stream-enabled/stream.conf` | SNI-роутинг :443 → 8443 (REALITY) / 7443 (сайт) |
| `/etc/nginx/sites-available/<subdomain>` | TLS-vhost панели (listen **7443** ssl proxy_protocol) |
| `/etc/nginx/sites-available/<reality_domain>` | Отдельный vhost для reality-домена |
| `/etc/nginx/sites-available/80.conf` | HTTP :80 → ACME / redirect |
| `/etc/nginx/sites-available/00-maps.conf` | map’ы (User-Agent → Clash и т.п.) |
| `/etc/nginx/snippets/includes.conf` | Общие `location`: подписка, XHTTP, WS-прокси |
| `/etc/nginx/sites-enabled/` | Симлинки на активные vhost’ы |

Сертификаты: `/etc/letsencrypt/live/<domain>/` (копии в `/root/cert/` для Hysteria2/TUIC).

### Порты

| Порт | Кто слушает | Зачем |
|------|-------------|--------|
| **443/TCP** | nginx stream | Единая точка входа, SNI-split |
| **443/UDP** | Xray (Hysteria2) | QUIC рядом с HTTPS |
| **7443** | nginx vhost | TLS-сайт + прокси к Xray |
| **8443** | Xray REALITY | После SNI-роутинга с :443 |

### Cloudflare

Только для location’ов за TLS nginx (WS, XHTTP+TLS, gRPC, подписка).  
REALITY, Hysteria2, AmneziaWG, TUIC — **напрямую на IP**, не через CF Proxied.

---

## Установка

**Требования:** Debian 12/13 или Ubuntu 24.04/26.04, root, **два домена** с A-записью на IP сервера.

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/test-alexsun/3xui-pro-fork/main/x-ui-latest.sh) \
  -install y \
  -subdomain panel.example.com \
  -reality_domain reality.example.com
```

| Флаг | Описание |
|------|----------|
| `-install y` | Установка без лишних вопросов |
| `-subdomain` | Основной домен панели / TLS / подписки |
| `-reality_domain` | Домен для REALITY (SNI) |
| `-ONLY_CF_IP_ALLOW y` | Доступ только с IP Cloudflare |
| `-version X.Y.Z` | Закрепить версию 3x-ui |
| `-uninstall y` | Удаление |

После установки в выводе: URL панели, логин/пароль, UUID Vision и XHTTP+REALITY, user/pass Mixed, порты.

### Опционально: AdGuard Home (DoH)

Совместим с этой сборкой (тот же nginx layout). Конфликта с inbound’ами нет:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/mozaroc/3x-ui-pro/main/x-ui-adguard.sh)
```

После полной переустановки панели — запустите скрипт AdGuard ещё раз (восстановит include в nginx).

---

## Обновление панели

Обычный update **не сбрасывает** inbound’ы:

```bash
x-ui update
```

Бэкап БД:

```bash
cp /etc/x-ui/x-ui.db /root/x-ui.db.bak-$(date +%F)
```

---


## Правка БД на уже установленном сервере

Если клиенты не сохраняются (`tgId of type int64`) или TUIC / AmneziaWG с ошибками — запустите:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/test-alexsun/3xui-pro-fork/main/x-ui-db-fix.sh)
```

Скрипт:

1. Делает бэкап `/etc/x-ui/x-ui.db` → `/root/x-ui.db.bak-fix-...`
2. Исправляет `tgId` / числовые поля клиентов (строка → число)
3. Пересобирает **TUIC** в формат `server` + `clients` + сертификаты
4. Пересобирает **AmneziaWG** в формат `server` + obfuscation (если старая схема)
5. Перезапускает `x-ui`

Без перезапуска: `bash x-ui-db-fix.sh -restart n`

### Добавить VLESS Encryption (PQ) на уже установленный сервер

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/test-alexsun/3xui-pro-fork/main/x-ui-add-vless-pq.sh)
```

Берёт ключи REALITY из существующего inbound, генерирует ML-KEM-768 через `xray vlessenc`, открывает порт в UFW и перезапускает панель.







### Переименовать remark на уже установленных узлах

Формат `CC-subdomain |` (например `DE-ee3 |`):

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/test-alexsun/3xui-pro-fork/main/x-ui-rename-remarks.sh)
```

Параметры:

```bash
bash x-ui-rename-remarks.sh -domain ee3.alexsun55.ru
bash x-ui-rename-remarks.sh -label ee3 -cc DE
bash x-ui-rename-remarks.sh -prefix 'DE-ee3 |'
```

Запускать **на каждом узле**. На мастере после этого обновите/переимпортируйте hosts при необходимости.


## RoscomVPN routing (Happ + INCY)

При установке подключается [hydraponique/roscomvpn-routing](https://github.com/hydraponique/roscomvpn-routing):

| Клиент | Настройка 3x-ui |
|--------|-----------------|
| **Happ** | `subEnableRouting` + `subRoutingRules` (DEFAULT deeplink) |
| **INCY** | `subIncyEnableRouting` + `subIncyRoutingRules` |
| **JSON sub** | `subJsonRoutingRules` → URL `HAPP/DEFAULT.JSON` |

Автообновление: **ежедневно в 04:00** (`/usr/local/lib/3x-ui-pro/update-roscomvpn-routing.sh`).

На уже установленном сервере:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/test-alexsun/3xui-pro-fork/main/x-ui-update-routing.sh)
```

## Устранение неполадок

### Ошибка при сохранении клиента: `tgId of type int64`

В 3x-ui поле `tgId` должно быть **числом** (`0`), не строкой `""`.  
В актуальном скрипте клиенты создаются с `"tgId": 0`.

Если установка была со старой версии скрипта:

```bash
python3 << 'PY'
import sqlite3, json
db = sqlite3.connect("/etc/x-ui/x-ui.db")
c = db.cursor()
for iid, raw in c.execute("SELECT id, settings FROM inbounds"):
    try:
        s = json.loads(raw or "{}")
    except Exception:
        continue
    changed = False
    for cl in s.get("clients") or []:
        if not isinstance(cl, dict):
            continue
        for key in ("tgId", "limitIp", "totalGB", "expiryTime", "reset"):
            v = cl.get(key)
            if isinstance(v, str):
                s2 = v.strip().replace(" ", "")
                cl[key] = int(s2) if s2.lstrip("-").isdigit() else 0
                changed = True
    if changed:
        c.execute("UPDATE inbounds SET settings=? WHERE id=?", (json.dumps(s, ensure_ascii=False), iid))
        print("fixed", iid)
db.commit()
db.close()
print("done")
PY
x-ui restart
```

---

## Удаление

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/test-alexsun/3xui-pro-fork/main/x-ui-latest.sh) -uninstall y
```

---

## Важно

- REALITY, Hysteria2, TUIC, AmneziaWG, WireGuard **не** работают через Cloudflare CDN.  
- Через CDN: WebSocket, XHTTP+TLS, Trojan gRPC.  
- Для протоколов без авто-клиента добавьте клиентов в панели.  
- Vision, XHTTP+REALITY и Mixed уже имеют готового клиента.

---

## Changelog (кратко)

- REALITY + Vision, XHTTP + REALITY, Hysteria2 на UDP 443  
- AmneziaWG / 3.1 — корректная схема `server` + obfuscation  
- Mixed — авто user/pass  
- Remarks: CC-subdomain (DE-ee3) + emoji протокола  
- Клиенты: `"tgId": 0` (int64), без пустых строк
- VLESS Encryption PQ (ML-KEM-768 + XHTTP + REALITY)
- TUIC v5: схема `server`+`clients` (не Xray stream), сертификаты, клиент с uuid/pass  
- Совместимость с `x-ui-adguard.sh` из mozaroc/3x-ui-pro  

---

## Благодарности

- **[MHSanaei](https://github.com/MHSanaei)** — автор и основной разработчик панели [3x-ui](https://github.com/MHSanaei/3x-ui)
- **[mozaroc](https://github.com/mozaroc)** — автор установщика [3x-ui-pro](https://github.com/mozaroc/3x-ui-pro), на базе которого сделан этот форк

Спасибо за открытый код и поддержку сообщества.

## Ссылки

- [3x-ui](https://github.com/MHSanaei/3x-ui)  
- [3x-ui-pro (оригинал)](https://github.com/mozaroc/3x-ui-pro)  
- Скрипт: [`x-ui-latest.sh`](https://raw.githubusercontent.com/test-alexsun/3xui-pro-fork/main/x-ui-latest.sh)
