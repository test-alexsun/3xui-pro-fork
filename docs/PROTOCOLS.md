# Протоколы и независимая интеграция (6 Inbounds)

Целевой набор состоит ровно из **шести управляемых панелью inbound**: `VLESS-REALITY-XHTTP-H2` (P0), `VLESS-TLS-XHTTP-H2` (P1), `VLESS-REALITY-VISION` (P3), `WIREGUARD`, `AMNEZIAWG-3.1`, `HYSTERIA2`. Каждый inbound имеет реальный backend в закреплённом tuple `3x-ui` **3.11.0** + `Xray-core` **26.11.9** + `amneziawg-go` **3.1.20260828** + `awg` **3.1.20260812**, независимую клиентскую модель, собственный порт и собственный результат acceptance-проверок.

**WireGuard и AmneziaWG 3.1 описаны в отдельных технических разделах** — их смешивание, совмещение портов, подсетей, ключей, клиентов или перенос PASS-статуса между ними запрещены.

## Сводная матрица шести протоколов

| Tag | Протокол / режим | Порт / bind | Runtime owner | Аутентификация и экспорт | Статус (Lab VM & Prod `de126`) |
|---|---|---|---|---|---|
| `VLESS-REALITY-XHTTP-H2` (P0) | `vless`, REALITY + XHTTP H2 | TCP `8443` (`--p0-port`) | `xray-linux-amd64` | UUID + REALITY key/shortId; `/sub`, `/json`, `/clash` | **PASS** (Lab VM & `de126`) |
| `VLESS-TLS-XHTTP-H2` (P1) | `vless`, XHTTP H2 за Nginx TLS | Public TCP `443` → `127.0.0.1:19441` | `nginx` → `xray-linux-amd64` | UUID + SAN TLS (`externalProxy`); `/sub`, `/json`, `/clash` | **PASS** (Lab VM & `de126`) |
| `VLESS-REALITY-VISION` (P3) | `vless`, raw/`tcp` REALITY Vision | TCP `9443` (`--p3-port`) | `xray-linux-amd64` | UUID + `xtls-rprx-vision` + REALITY; `/sub`, `/json`, `/clash` | **PASS** (Lab VM & `de126`) |
| `WIREGUARD` | `wireguard`, `noKernelTun: true`, MTU `1420` | UDP `51820` (`--wg-port`) | `xray-linux-amd64` | RFC 7748 X25519 keys, AllowedIPs; `.conf`, `wireguard://`, `/sub`, `/json`, `/clash` | **PASS** (независимый E2E Lab & `de126`) |
| `AMNEZIAWG-3.1` | `amneziawg`, `kernelMode: false`, MTU `1420` | UDP `29177` (`--awg-port`) | `x-ui` MainPID (`amneziawgnet`) → Xray SOCKS5 | `awg` keys + `HeaderProtectionKey` + obfuscation; `vpn://` → `.conf`/`setconf`, `/clash` | **PASS** (независимый E2E Lab & `de126`) |
| `HYSTERIA2` | `hysteria` v2, QUIC/TLS `h3` | UDP `24443` (`--hy2-port`) | `xray-linux-amd64` | 32-byte `auth` secret, SAN cert; `hysteria2://`, `/sub`, `/json`, `/clash` | **PASS** (независимый E2E Lab & `de126`) |

---

## VLESS (P0 / P1 / P3)

Три VLESS inbound управляются модулем [preview_panel_inbounds.py](../release/preview_panel_inbounds.py) и фиксируются в журнале `preview-panel-inbounds.json`:
- **P0 (`VLESS-REALITY-XHTTP-H2`)**: Xray listening TCP `8443` (`--p0-port`), REALITY + XHTTP HTTP/2.
- **P1 (`VLESS-TLS-XHTTP-H2`)**: Xray listening loopback `127.0.0.1:19441`, терминирование публичного TLS `443` в Nginx на основном домене (`/xhttp/...`), метаданные `externalProxy` (`domain:443`, `tls`, `alpn: ["h2"]`).
- **P3 (`VLESS-REALITY-VISION`)**: Xray listening TCP `9443` (`--p3-port`), raw TCP + REALITY + flow `xtls-rprx-vision`.
- Клиенты используют UUID, не перегенерируются при повторе установщика и проверяются через [preview08_existing_smoke.py](../tests/release/preview08_existing_smoke.py) (P0/P1/P3 > 64 KiB uplink/downlink + `/sub`, `/json`, `/clash`). При добавлении WG/AWG/HY2 исходный журнал и настройки VLESS сохраняются без изменений.

---

## WireGuard (`WIREGUARD`)

Отдельная реализация обычного WireGuard описана и валидируется в модуле [preview_wireguard.py](../release/preview_wireguard.py).

- **Runtime**: нативный inbound `protocol: wireguard` в `3x-ui 3.11.0`, исполняемый внутри дочернего процесса `xray-linux-amd64` (`26.11.9`) в userspace-режиме (`noKernelTun: true`). Модуль не импортирует `awg` / `amneziawg-go` и запрещает процессы `awg`/`amnezia` как владельцев сокета.
- **Порт**: выделенный UDP-порт `51820` по умолчанию (`--wg-port`). Порт `29177` (`AWG_RESERVED_PORT`), системные порты и порты P0/P1/P3/HY2 строго отклоняются.
- **Подсеть**: выделенная RFC1918 IPv4-подсеть `/16../30`, по умолчанию `10.89.8.0/24` (`--wg-subnet`). Пересечение с подсетью `AMNEZIAWG-3.1` или маршрутами хоста отклоняется функцией `validate_subnet()` / `validate_vpn_spec()`. Первый адрес хоста (`.1`) резервируется под сервер, клиенты получают последовательные `/32` начиная с `.2`. Server MTU строго `1420`.
- **Peer**: отдельный peer-объект в `settings.clients` с полями `email`, `id` (UUID), `subId`, `privateKey`, `publicKey`, `allowedIPs: ["<ip>/32"]`, `keepAlive`, `enable`. Ни один клиентский record не привязывается одновременно к WireGuard и AmneziaWG 3.1 (в SQLite 3x-ui поля `clients.wg_*` общие для одной записи клиента).
- **Keys**: серверная пара Curve25519 (`secretKey`) и клиентские пары (`privateKey`/`publicKey`) генерируются и проверяются чистым Python по **RFC 7748 X25519** без вызова внешнего бинарника `awg`. Присутствие любых AWG-полей (`Jc`, `Jmin`, `Jmax`, `S1`–`S4`, `H1`–`H4`, `I1`–`I5`, `HeaderProtectionKey` и т. д.) в settings, `.conf` или ссылках отклоняется.
- **Client configuration**: чистый WireGuard-формат без AWG-параметров:
  - `.conf` (`render_client_conf` / `parse_client_conf`);
  - `wireguard://<priv>@<host>:<port>?address=...&publickey=...&mtu=1420` (`clients/links/:email` и `https://<sub_domain>/sub/<subId>`);
  - `/json/<subId>` outbound `protocol: wireguard` (проверена чистота от AWG-параметров).
- **Управление**: нативный UI (`Inbounds` → `WIREGUARD`, `Clients`) и API (`inbounds/add`, `inbounds/setEnable/:id`, `clients/add`, `clients/update/:email` с сохранением/ротацией ключей и enable/disable, `clients/del/:email`).
- **Проверки**: 26 модульных тестов в [tests/protocols/wireguard/](../tests/protocols/wireguard/test_config.py) (RFC 7748 векторы, отказ порта `29177`, отказ AWG-загрязнения, аллокация подсети, проверка PID-владельца) и независимый live E2E [test_e2e.py](../tests/protocols/wireguard/test_e2e.py) с явным драйвером `linux-kernel-wireguard` (или Xray fallback), проверкой handshake, 65 536 B TCP, 8 × 512 B (и 16 dgrams в integration) UDP, ротацией ключей, disable/enable, restart persistence и удалением клиента.
- **Ограничения**: в `3x-ui 3.11.0` эндпоинты `clients/get/:email` и `clients/list` возвращают `client.allowedIPs` как CSV-строку (`"10.89.8.2/32"`), тогда как `inbounds/list` возвращает JSON-массив `["10.89.8.2/32"]`. Серверный MTU `1420` не понижается; глобальный NAT/full-tunnel маршрутизатор за пределами Xray не настраивается.

---

## AmneziaWG 3.1 (`AMNEZIAWG-3.1`)

Отдельная реализация строго **AmneziaWG версии 3.1** описана и валидируется в модуле [preview_amneziawg31.py](../release/preview_amneziawg31.py).

- **Версия 3.1**: строго `amneziawg-go` **3.1.20260828** (встроен в `3x-ui 3.11.0` как `amneziawg-go/v3 v3.1.20260828` и скопирован в `/opt/3xui-pro-fork/awg/amneziawg-go`) и утилита `awg` **3.1.20260812** (`/opt/3xui-pro-fork/awg/awg`). Профили 1.x/2.x и замена на обычный WireGuard запрещены.
- **Runtime**: в 6-inbound режиме (по умолчанию при fresh install `--panel-inbounds` и после `--add-vpn-inbounds --handoff-standalone-awg`) работает встроенный менеджер `amneziawgnet` внутри процесса `x-ui` MainPID (`kernelMode: false`, gVisor userspace), ретранслирующий расшифрованный трафик через loopback password-auth SOCKS5 inbound (`127.0.0.1:<port>`, tag `AMNEZIAWG-3.1`) в `xray-linux-amd64`. Отдельная служба `3xui-pro-fork-awg.service` остаётся inactive/disabled. Режим `kernelMode: true` (`xui-awg<ID>`) **не используется и отклоняется** валидатором (кроме замечания: Go-сериализатор `json:"kernelMode,omitempty"` опускает поле `"kernelMode": false` при возврате `inbounds/list`, поэтому проверка интерпретирует отсутствие ключа как `False` и отклоняет `True`).
- **Obfuscation settings (AWG 3.1)**: обязателен 32-байтный `HeaderProtectionKey` (`S1`/`S2`/`S3` в диапазоне `12..255`, `S4` в `12..32`, `S1 + 56 != S2`, по умолчанию `S1=S2=S3=S4=12`), `Jc=4`, `Jmin=40`, `Jmax=70`, непересекающиеся `H1="1"`, `H2="2"`, `H3="3"`, `H4="4"`, поддерживаются опциональные CPS-цепочки `I1`–`I5` (`<b ...>`, `<c>`, `<t>`, `<r ...>`, `<rc ...>`, `<rd ...>`) и 3.1 параметры (`randomTrailers`, `disableCookies`, `contentPaddingAddition`, `rekey*`, `rejectAfterTime`, `keepaliveTimeout`, `maxHandshakeAttempts`). Server MTU равен `1420` (client MTU `1368` зафиксирован лишь для единичного измеренного внешнего пути из `07A`, а не как системный default).
- **Порт**: UDP `29177` по умолчанию (`--awg-port`). Не пересекается с `WIREGUARD` и `HYSTERIA2`. На `de126` 2026-11-24 порт `29177` переведён со standalone `3xui-pro-fork-awg.service` на embedded `AMNEZIAWG-3.1` в `x-ui` MainPID.
- **Подсеть**: в 6-inbound режиме выделенная RFC1918 IPv4 `/16../30`, по умолчанию `10.88.32.0/24` (`--awg-subnet`). В opt-out режиме `--vless-only` (и архиве старого standalone `/30`) сохраняется формат `/30` (`awg_config_candidate.py`). Пересечение с `WIREGUARD` запрещено.
- **Peer**: отдельный client record в `settings.clients` (начинающийся со `starter-amneziawg31` или создаваемый оператором/тестом), с собственной парой ключей, `/32` адресом и `subId`. Никогда не объединяется с WireGuard-клиентом.
- **Keys**: серверная пара ключей (`privateKey`/`publicKey`), `HeaderProtectionKey` и клиентские пары генерируются и проверяются бинарником `/opt/3xui-pro-fork/awg/awg` (`awg genkey`, `awg pubkey`).
- **Client configuration**:
  - `clients/links/:email` и `https://<sub_domain>/sub/<subId>` выдают `vpn://<base64url>` (AmneziaVPN container JSON + zlib); поддерживается также `/clash/<subId>` (`/json/<subId>` возвращает `404`, так как клиентский Xray-core не имеет нативного outbound для AWG 3.1);
  - `preview_amneziawg31.decode_vpn_link()` декодирует её в INI `.conf` с секциями `[Interface]` и `[Peer]`, включающими `Jc`/`Jmin`/`Jmax`/`S1`–`S4`/`H1`–`H4`/`HeaderProtectionKey` и `MTU = 1420`;
  - `conf_to_setconf()` преобразует булевы флаги (`RandomTrailers`, `DisableCookies`) в `on`/`off`, совместимые с CLI `awg setconf`.
- **Управление**: панель UI/API (`clients/add`, `clients/update`, `clients/del`, `inbounds/setEnable/:id`). **Важное поведение `3x-ui 3.11.0`**: изменение состава/статуса клиентов `AMNEZIAWG-3.1` изменяет `settings.accounts` loopback SOCKS5-ретранслятора, и background-планировщик панели на ~30-секундном reconcile-тике принудительно перезапускает `xray-linux-amd64` (`hot diff: inbound [ AMNEZIAWG-3.1 ] is a password-auth SOCKS5 inbound ... forcing a full restart`). До завершения перезапуска Xray handshake уже проходит, но пересылка данных через SOCKS5 вернёт сброс соединения.
- **Проверки**: 22 модульных теста в [tests/protocols/amneziawg31/](../tests/protocols/amneziawg31/test_config.py), live E2E [test_e2e.py](../tests/protocols/amneziawg31/test_e2e.py) в lab VM и внешняя production-приёмка на `de126` (`amneziawg-go 3.1.20260828` + `awg v3.1.20260812`: **PASS** — отказ plain WG на `29177`, handshake + HTTP TCP + UDP DNS на `MTU=1420`, PQ TLSv1.3 HTTPS + UDP DNS на `MTU=1280`, полный CRUD с ~30s reconcile).
- **Ограничения**: тестирование старых `/30` standalone-профилей отменено (после переключения `de126` прежние `/30` профили теряют доступ, при сохранении старых конфигов в архиве `/var/lib/3xui-pro-fork/awg/`); `kernelMode: true` не поддерживается; на измеренном локальном Docker/WSL2/ISP WAN-пути до `de126` 1568 B PQ TLSv1.3 `ClientHello` требует клиентский `MTU <= 1280..1368`.

---

## Hysteria2 (`HYSTERIA2`)

Протокол реализован и валидируется в модуле [preview_hysteria2.py](../release/preview_hysteria2.py).

- **Runtime и schema**: нативный inbound `protocol: hysteria`, `settings.version: 2`, `streamSettings.network: hysteria`, `security: tls`, `alpn: ["h3"]`, `udpIdleTimeout: 60` под управлением дочернего `xray-linux-amd64`. Версия v1 или `allowInsecure` отклоняются.
- **Порт и TLS**: выделенный UDP-порт `24443` по умолчанию (`--hy2-port`). Используется существующий SAN-сертификат `/var/lib/3xui-preview-acme/config/live/3xui-preview/fullchain.pem` и ключ `privkey.pem` (без создания третьего домена или отдельной ACME lineage); `tlsSettings.serverName` равен основному домену.
- **Клиенты и экспорт**: 32-байтный URL-safe `auth` secret (`id` равен `auth` в 3x-ui 3.11.0); ссылка `hysteria2://<auth>@<domain>:<port>/?alpn=h3&sni=<domain>` возвращается в `clients/links/:email` и `/sub/<subId>`, поддерживаются `/json/<subId>` и `/clash/<subId>`.
- **Проверки**: 18 модульных тестов в [tests/protocols/hysteria2/](../tests/protocols/hysteria2/test_config.py), live E2E [test_e2e.py](../tests/protocols/hysteria2/test_e2e.py) в lab VM и внешняя production-приёмка на `de126` (**PASS**: доверенный Let's Encrypt CA без `allowInsecure`, egress `179.254.154.126` + UDP DNS `1.1.1.1:53`, отказ неверного `auth`, CRUD, одновременная работа с 5 другими inbound и restart persistence).
