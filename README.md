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
| **VLESS + REALITY + Vision** | 8443 → nginx **:443** | flow `xtls-rprx-vision`, клиент создаётся автоматически |
| **VLESS + WebSocket + TLS** | path → nginx **:443** | |
| **VLESS + XHTTP + TLS** | path → nginx **:443** (Unix-сокет) | через nginx |
| **VLESS + XHTTP + REALITY** | отдельный TCP | прямой REALITY, клиент с UUID |
| **Trojan + gRPC + TLS** | path → nginx **:443** | |
| **VMess + WebSocket + TLS** | path → nginx **:443** | |
| **Shadowsocks 2022** | свой TCP+UDP | method `2022-blake3-aes-128-gcm` |
| **Hysteria2** | **UDP 443** | тот же порт, что HTTPS (TCP) |
| **TUIC v5** | отдельный UDP + TLS | |
| **AmneziaWG** | отдельный UDP | корректная схема 3x-ui + obfuscation |
| **AmneziaWG 3.1** | отдельный UDP | отдельная подсеть и параметры |
| **WireGuard** | отдельный UDP | |
| **MTProto** | отдельный TCP | для Telegram |
| **Mixed (SOCKS5 + HTTP)** | отдельный TCP | **user/pass создаётся автоматически** |

### Антиблок

- **REALITY + Vision** — основной канал против DPI  
- **XHTTP + REALITY** — запасной «веб-подобный» транспорт  
- **Hysteria2 на UDP 443** — рядом с HTTPS, меньше «лишних» портов  
- **AmneziaWG / 3.1** — WireGuard с обфускацией (панель-native)

### Читаемые названия inbound’ов

В панели сразу видны понятные remark’и с кодом страны (без эмодзи — стабильно во всех браузерах), например:

``AL | 🔒 VLESS REALITY + Vision``, ``AL | ⚡ Hysteria2 (UDP 443)``, ``AL | 🔧 Mixed SOCKS5 + HTTP``

---

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
| `/etc/nginx/sites-available/<reality_domain>` | Отдельный vhost для reality-домена (сертификат LE) |
| `/etc/nginx/sites-available/80.conf` | HTTP :80 → ACME / redirect |
| `/etc/nginx/sites-available/00-maps.conf` | map’ы (User-Agent → Clash и т.п.) |
| `/etc/nginx/snippets/includes.conf` | Общие `location`: подписка, XHTTP, WS-прокси |
| `/etc/nginx/sites-enabled/` | Симлинки на активные vhost’ы |

Сертификаты: `/etc/letsencrypt/live/<domain>/` (и копии под `/root/cert/` для Hysteria2/TUIC).

### Важные location’ы (`snippets/includes.conf`)

| Location | Куда |
|----------|------|
| `/{sub_path}/` | Подписка 3x-ui (Clash / base64) |
| `/{json_path}/` | JSON-конфиг подписки |
| `/{xhttp_path}` | `grpc_pass` → `unix:/dev/shm/uds2023.sock` (VLESS XHTTP) |
| `~ ^/(port)/(path)` | Универсальный прокси на Xray inbound по порту/пути (WS, gRPC) |
| `/` | Fake-site (маскировка) |

### Порты (логика)

| Порт | Кто слушает | Зачем |
|------|-------------|--------|
| **443/TCP** | nginx stream | Единая точка входа, SNI-split |
| **443/UDP** | Xray (Hysteria2) | QUIC рядом с HTTPS |
| **7443** | nginx vhost | TLS-сайт + прокси к Xray (только localhost / proxy_protocol) |
| **8443** | Xray REALITY | После SNI-роутинга с :443 |
| остальные | Xray / x-ui | SS, TUIC, AmneziaWG, Mixed… напрямую |

### Настройка после установки

1. **Не открывайте 7443/8443 наружу** — снаружи достаточно 80/443 (и нужных UDP).  
2. Правки WS/XHTTP путей — в панели inbound + при необходимости в  
   `/etc/nginx/snippets/includes.conf`, затем:
   ```bash
   nginx -t && systemctl reload nginx
   ```
3. Новый домен за nginx — новый файл в `sites-available`, симлинк в `sites-enabled`, `nginx -t && reload`.  
4. REALITY SNI задаётся доменом `-reality_domain` и блоком `map` в `stream-enabled/stream.conf`.

### Cloudflare

Имеет смысл только для location’ов за TLS nginx (WS, XHTTP+TLS, gRPC, подписка).  
REALITY, Hysteria2, AmneziaWG, TUIC — **напрямую на IP**, не через CF Proxied.


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
| `-reality_domain` | Домен для REALITY (SNI, отдельный от subdomain) |
| `-ONLY_CF_IP_ALLOW y` | Ограничить доступ только IP Cloudflare |
| `-version X.Y.Z` | Закрепить версию 3x-ui |
| `-uninstall y` | Удаление |

После установки в выводе будут:

- URL панели, логин/пароль  
- UUID Vision и XHTTP+REALITY  
- user/pass для Mixed  
- порты Hysteria2, AmneziaWG, TUIC и др.

---

## Обновление панели

Обычный update **не сбрасывает** inbound’ы и настройки:

```bash
x-ui update
# или через меню: x-ui → Update
```

Бэкап БД перед крупным апдейтом:

```bash
cp /etc/x-ui/x-ui.db /root/x-ui.db.bak-$(date +%F)
```

Скрипт нужен только для **первой** установки. Дальше — штатный `x-ui`.

---

## Удаление

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/test-alexsun/3xui-pro-fork/main/x-ui-latest.sh) -uninstall y
```

---

## Важно

- REALITY, Hysteria2, TUIC, AmneziaWG, WireGuard **не** работают через Cloudflare CDN (нужен прямой IP).  
- Через CDN (Cloudflare Proxied) подходят: WebSocket, XHTTP+TLS, Trojan gRPC.  
- После установки добавьте клиентов в панели для протоколов без авто-клиента (WS, Trojan, SS и т.д.).  
- Vision и Mixed / XHTTP+REALITY уже имеют готового клиента.

---

---

## Благодарности

- **[MHSanaei](https://github.com/MHSanaei)** — автор и основной разработчик панели [3x-ui](https://github.com/MHSanaei/3x-ui)
- **[mozaroc](https://github.com/mozaroc)** — автор установщика [3x-ui-pro](https://github.com/mozaroc/3x-ui-pro), на базе которого сделан этот форк

Спасибо за открытый код и поддержку сообщества.

## Ссылки

- [3x-ui](https://github.com/MHSanaei/3x-ui)  
- [3x-ui-pro (оригинал)](https://github.com/mozaroc/3x-ui-pro)  
- Скрипт: [`x-ui-latest.sh`](https://raw.githubusercontent.com/test-alexsun/3xui-pro-fork/main/x-ui-latest.sh)
