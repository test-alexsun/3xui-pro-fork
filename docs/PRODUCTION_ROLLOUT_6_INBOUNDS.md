# Production Rollout: Six Independent Inbounds on `de126`

**SIX-INBOUNDS-PRODUCTION: PASS** (выполнено 2026-11-24 на production VPS `de126` с подтверждённой ревизии `9e44b525685458f00c34effe6795814b1da24da9`). Санитайзнутые JSON-результаты и лог приёмки: [production-de126-6inbounds](stages/evidence/production-de126-6inbounds/test-results.md).

---

## 1. Фактическая production-архитектура `de126`

- **Хост и ОС**: `de126` (`179.254.154.126`, SSH alias `de126`), `Debian GNU/Linux 13 (trixie)` amd64, kernel `6.12.117+deb13-amd64`, systemd PID 1, 1 vCPU, `967 MiB` RAM (`Swap: 0`).
- **Два фиксированных домена**: `de126.alexsun55.ru` (основной домен: `XONIX`, приватный путь панели, P1 `/xhttp/`, P0/P3/WG/AWG3.1/HY2) и `de126-sub.alexsun55.ru` (подписки `/sub/`, `/json/`, `/clash/`, корень `404`). Оба DNS A-имени указывают исключительно на `179.254.154.126`, TLS обеспечен доверенным Let's Encrypt SAN-сертификатом (`/var/lib/3xui-preview-acme/config/live/3xui-preview/`).
- **Закреплённые версии (без изменений tuple)**: `3x-ui` `3.11.0`, `Xray-core` `26.11.9`, `amneziawg-go` `3.1.20260828`, `awg` tools `3.1.20260812`, Nginx `1.26.3-3+deb13u11`, Certbot `4.0.0-2+deb13u1`.

## 2. Шесть активных production Inbound и runtime ownership

| ID | Inbound Tag | Протокол / режим | Порт / bind | Подсеть / транспорт / MTU | Владелец сокета | Статус |
|---|---|---|---|---|---|---|
| `1` | `VLESS-REALITY-XHTTP-H2` (P0) | `vless`, REALITY + XHTTP H2 | TCP `8443` (`179.254.154.126`) | REALITY + XHTTP `stream-up` | `xray-linux-amd64` | **PASS** (SHA256 строки БД неизменен) |
| `2` | `VLESS-TLS-XHTTP-H2` (P1) | `vless`, XHTTP H2 за Nginx TLS | Public TCP `443` → `127.0.0.1:19441` | Let's Encrypt TLS `externalProxy` H2 | `nginx` → `xray-linux-amd64` | **PASS** (SHA256 строки БД неизменен) |
| `3` | `VLESS-REALITY-VISION` (P3) | `vless`, raw/`tcp` REALITY Vision | TCP `9443` (`179.254.154.126`) | `xtls-rprx-vision` + REALITY | `xray-linux-amd64` | **PASS** (SHA256 строки БД неизменен) |
| `4` | `WIREGUARD` | `wireguard` (`noKernelTun: true`) | UDP `51820` (`179.254.154.126`) | `10.89.8.0/24`, MTU `1420`, без AWG-полей | `xray-linux-amd64` | **PASS** |
| `5` | `AMNEZIAWG-3.1` | `amneziawg` (`kernelMode: false`) | UDP `29177` (`179.254.154.126`) | `10.88.32.0/24`, MTU `1420`, HPK + `Jc`/`Jmin`/`Jmax`/`S1`–`S4`/`H1`–`H4` | `x-ui` MainPID → Xray SOCKS5 loopback | **PASS** |
| `6` | `HYSTERIA2` | `hysteria` v2, QUIC/TLS ALPN `h3` | UDP `24443` (`179.254.154.126`) | Two-domain ACME SAN cert, 32-byte `auth` | `xray-linux-amd64` | **PASS** |

## 3. Независимость WireGuard и AmneziaWG 3.1

- Оба протокола развёрнуты как полностью отдельные inbounds с непересекающимися UDP-портами (`51820` vs `29177`), непересекающимися RFC1918 подсетями (`10.89.8.0/24` vs `10.88.32.0/24`), разными серверными ключами (`distinct_wg_awg_pubkeys: true` и `distinct_wg_awg_server_keys: true`) и разными клиентскими записями.
- Отрицательный изоляционный тест на production подтвердил, что стандартный клиент WireGuard отклоняется на UDP `29177` (`AMNEZIAWG-3.1`).
- Каждый протокол прошёл отдельный полный цикл приёмки: **WIREGUARD: PASS** и **AMNEZIAWG-3.1: PASS**.

## 4. Backup, handoff standalone AWG, migration, safe repeat и recovery

1. **Независимый pre-rollout backup** (через Python `sqlite3` Online Backup API из-за режима WAL):
   - Каталог на сервере (`0700`): `/var/backups/3xui-pro-fork/pre-6inbounds-20261124T084510Z` (`23` файла).
   - Содержит `x-ui.db` (`PRAGMA integrity_check == ok`), state JSON (`preview-web.json`, `preview-panel.json`, `preview-panel-inbounds.json`, `preview-xray.json`, `preview-xray-clients.json`), архив `/var/lib/3xui-pro-fork/awg/` (`client.conf`, `metadata.json`, `server.setconf`), конфиги Nginx/systemd, `acme-lineage.tar.gz`, дампы `iptables-save`/`ip -4 route`/`ss` и `manifest.sha256`, подтверждённый `sha256sum -c`.
2. **Installer backup перед переключением**:
   - `/var/lib/3xui-pro-fork/preview08-backup-482dd1cdafd75fdd` (SQLite `PRAGMA integrity_check == ok`).
3. **Controlled Rollout & Handoff**:
   - Запущен проверенный `bootstrap-preview.sh` (`SHA256 dd0ef3205a9d9864c7778de2f0b5b41c259866c8c31055855b4bee9cd5295fb3`) с `TMPDIR=/var/tmp`, ревизией `9e44b525685458f00c34effe6795814b1da24da9` и явными флагами `--panel-inbounds --add-vpn-inbounds --handoff-standalone-awg`.
   - Служба `3xui-pro-fork-awg.service` остановлена и отключена (`inactive`/`disabled`), host TUN интерфейс `xproawg0` удалён (`xproawg0_present: false`), UDP `29177` перешёл во владение `x-ui` MainPID (`87577` до restart, `101179` после планового restart).
   - Старая конфигурация standalone AWG (`/var/lib/3xui-pro-fork/awg/{server.setconf,client.conf,metadata.json}`) сохранена без удаления на диске и в backup.
   - **Важное следствие для legacy клиентов**: старые standalone `/30` AWG-профили (`10.88.31.0/30`), выпущенные прежней службой `3xui-pro-fork-awg.service`, после переключения теряют доступ к серверу (ожидаемое следствие отмены legacy-совместимости); для подключения используются новые нативные AWG 3.1 профили панели (`10.88.32.0/24`).
4. **Safe repeat**:
   - Повторный запуск с ревизией `9e44b525685458f00c34effe6795814b1da24da9` и `--panel-inbounds` (без `--add-vpn-inbounds`) завершился с кодом `0`, не изменил журналы, VLESS rows, ключи и клиентов.
5. **Состояние журналов и recovery**:
   - `preview-panel-inbounds.json`: `phase: READY`, `version: 1`, `profiles: {"P0": 1, "P1": 2, "P3": 3}`, SHA256 `7ff0149a3ee5b74ec96b45668668bef0ecd8b1be76fef7d7b5ccba7765252ec0` **не изменился**.
   - `preview-vpn-inbounds.json`: `phase: READY`, `version: 2`, `profiles: {"WIREGUARD": 4, "AMNEZIAWG-3.1": 5, "HYSTERIA2": 6}`.
   - Оба журнала остаются fail-closed: автоматический откат после `READY` запрещён; при любых инцидентах используется процедура ручной диагностики и backups по [RECOVERY.md](RECOVERY.md).

## 5. Production-приёмка, ресурсы и известные ограничения

- **Внешние реальные тесты (с локального Docker Debian 13 клиента через WAN на `179.254.154.126`)**:
  - `VLESS` P0/P1/P3: сохранены `preview-P0`, `preview-P1`, `preview-P3`; `/sub`, `/json`, `/clash` HTTP `200`; реальный HTTPS egress `179.254.154.126` + XONIX `200`.
  - `WIREGUARD`: kernel `wg` handshake + HTTP TCP + UDP DNS (`MTU=1420`) и полный PQ TLSv1.3 HTTPS + UDP DNS (client `MTU=1280`, server `MTU=1420`), `/sub`/`/json`/`/clash`/`.conf`, полная ротация/disable/re-enable/del + wire revocation.
  - `AMNEZIAWG-3.1`: `amneziawg-go 3.1.20260828` + `awg v3.1.20260812` + HPK, отказ plain WG, handshake + HTTP TCP + UDP DNS (`MTU=1420`) и PQ TLSv1.3 HTTPS + UDP DNS (client `MTU=1280`), `/sub`/`/clash`/`vpn://`, CRUD с ~30s reconcile.
  - `HYSTERIA2`: Xray v2 QUIC/TLS `h3` с доверенным Let's Encrypt CA, egress `179.254.154.126` + UDP DNS, отказ wrong `auth`, `/sub`/`/json`/`/clash`, CRUD + revocation.
  - **Одновременная работа и restart**: одновременный трафик через все 6 протоколов, плановый `systemctl restart 3xui-pro-fork.service`, повторный трафик по всем 6 протоколам, удаление 3 эфемерных smoke-клиентов (оставлены `preview-P0/P1/P3` и `starter-wireguard`, `starter-amneziawg31`, `starter-hysteria2`).
  - **UI & Web**: Playwright Chromium с реальным Let's Encrypt CA (без CDP TLS override): XONIX `200` (`1024x683`), HTTP `308` на оба домена, subscription root `404`, auth cookies `HttpOnly`/`Secure`/`SameSite=Lax`, 6 видимых включённых Inbounds, 6 строк Clients, `pageerror=0`.
- **Ресурсы и состояние `de126` после rollout**:
  - `MemTotal`: `990564 kB` (`967 MiB`), **`MemAvailable`: `637124 kB` (`622 MiB`)**, `SwapTotal`: `0 kB` (использование памяти снизилось относительно `610896 kB` до rollout за счёт отказа от второго процесса `amneziawg-go`), `x-ui` RSS `133340 kB`, `xray` RSS `49156 kB`, loadavg `0.15 0.06 0.01`, `/` free `7.78 GiB` (`609760` inodes), **`oom_count: 0`**, `/var/tmp` без временных staging-хвостов.
- **Известные ограничения**:
  - Серверный MTU зафиксирован на `1420`; на измеренном внешнем пути (Windows/WSL2/локальный ISP → `179.254.154.126`) 1568-байтный PQ `TLSv1.3 ClientHello` требует клиентский `MTU <= 1280..1368`, тогда как HTTP и UDP DNS проходят и при `1420`.
  - Embedded `AMNEZIAWG-3.1` перезапускает Xray на ~30-секундном reconcile-тике при изменениях клиентов; idle серверный WireGuard peer с `keepAlive=25` пишет в журнал Xray периодическое `no known endpoint for peer` до подключения пира; на экране `Inbounds` Chromium фиксирует стандартный `404` на `/favicon.ico` (`pageerror=0`).
  - Автоматический binary updater и power-loss recovery журналов отсутствуют.
