# Production Rollout & Verification Log (`de126`, 6 Inbounds)

**SIX-INBOUNDS-PRODUCTION: PASS** — 2026-11-24 на живом production VPS `de126` (`179.254.154.126`, `de126.alexsun55.ru`, `de126-sub.alexsun55.ru`, Debian 13 amd64, kernel `6.12.117+deb13-amd64`).

> [!NOTE]
> Данный каталог содержит только санитайзнутый отчёт реального production-развёртывания `de126` с ревизии `9e44b525685458f00c34effe6795814b1da24da9`. Лабораторный прогон PREVIEW-XONIX-08 ([preview-xonix-08](../preview-xonix-08/test-results.md)) и historical baseline ([preview-xonix-07a](../preview-xonix-07a/test-results.md)) сохранены отдельно без изменений. Секреты, API tokens, private keys, `HeaderProtectionKey`, `subId`, подписочные URL, приватный `panel_path`, SQLite DB и backup-архивы не включены.

---

## Сводка приёмки (17 контрольных точек + изоляция + ресурсы)

| Контрольная точка | Статус | Подтверждённое доказательство |
|---|---|---|
| Pre-rollout backup + SQLite WAL online backup | **PASS** | `/var/backups/3xui-pro-fork/pre-6inbounds-20261124T084510Z` (`23` файла, `manifest.sha256` PASS, `PRAGMA integrity_check == ok`) ([preflight-and-backup.json](preflight-and-backup.json)) |
| Installer handoff + safe repeat check | **PASS** | `bootstrap-preview.sh` @ `9e44b525685458f00c34effe6795814b1da24da9`, `VPN_INBOUNDS_READY`, repeat exit `0`, VLESS SHA256 идентичны ([rollout-and-repeat.json](rollout-and-repeat.json)) |
| P0 `VLESS-REALITY-XHTTP-H2` (TCP `8443`) | **PASS** | Сохранены UUID/ключи/клиент `preview-P0`, реальный egress IP `179.254.154.126` + decoy HTTPS `200` ([vless-smoke.json](vless-smoke.json)) |
| P1 `VLESS-TLS-XHTTP-H2` (TCP `443` → `127.0.0.1:19441`) | **PASS** | Сохранены UUID/клиент `preview-P1`, `externalProxy` Let's Encrypt TLS, egress IP `179.254.154.126` + decoy `200` ([vless-smoke.json](vless-smoke.json)) |
| P3 `VLESS-REALITY-VISION` (TCP `9443`) | **PASS** | Сохранены UUID/flow/ключи/клиент `preview-P3`, egress IP `179.254.154.126` + decoy `200` ([vless-smoke.json](vless-smoke.json)) |
| `WIREGUARD` (независимый, UDP `51820`, `10.89.8.0/24`) | **PASS** | `xray-linux-amd64` `noKernelTun: true`, pure X25519 без AWG, kernel `wg` handshake + TCP/UDP + CRUD ([wireguard-smoke.json](wireguard-smoke.json)) |
| `AMNEZIAWG-3.1` (независимый, UDP `29177`, `10.88.32.0/24`) | **PASS** | Embedded `amneziawgnet 3.1.20260828` (`x-ui` MainPID) + `awg v3.1.20260812` + HPK, plain WG отклонён, handshake + TCP/UDP + CRUD + 30s reconcile ([amneziawg31-smoke.json](amneziawg31-smoke.json)) |
| `HYSTERIA2` (UDP `24443`, TLS ALPN `h3`) | **PASS** | `xray-linux-amd64` v2, доверенный Let's Encrypt CA без `insecure`, egress IP `179.254.154.126` + UDP DNS, wrong auth отклонён, CRUD ([hysteria2-smoke.json](hysteria2-smoke.json)) |
| Одновременная работа и изоляция всех 6 + planned restart | **PASS** | Все 6 активны одновременно; плановый `systemctl restart 3xui-pro-fork.service`; трафик по всем 6 после restart; отзыв удалённых smoke-клиентов ([six-inbounds-independence-and-restart.json](six-inbounds-independence-and-restart.json)) |
| Six Inbounds UI & Clients UI (Playwright Chromium) | **PASS** | Реальный Let's Encrypt SAN без CDP override; 6 Inbounds visible/enabled; 6 Clients (`preview-P0/P1/P3`, `starter-*`); `HttpOnly`/`Secure`/`SameSite=Lax`; `pageerror=0` ([ui-and-web-smoke.json](ui-and-web-smoke.json)) |
| Client API & Client CRUD | **PASS** | `inbounds/list`, `clients/add`, `clients/get`, `clients/links`, `clients/update` (ротация ключей/auth, disable/enable), `clients/del` + отказ на сети |
| Subscriptions (`/sub`, `/json`, `/clash`) | **PASS** | `https://de126-sub.alexsun55.ru`: `200`, `Referrer-Policy: no-referrer`, `Cache-Control: no-store`; VLESS `sub/json/clash`, WG `sub/json/clash`, AWG31 `sub/clash`, HY2 `sub/json/clash` |
| XONIX (`https://de126.alexsun55.ru/`) | **PASS** | HTTP `200`, `XONIX` title, canvas `1024x683`, `consoleErrors=0`, `pageErrors=0` |
| Nginx & HTTPS | **PASS** | `nginx -t` OK; HTTP `308` → HTTPS на оба домена; `https://de126-sub.alexsun55.ru/` корень `404`; доверенный Let's Encrypt SAN |
| SQLite integrity | **PASS** | `PRAGMA integrity_check == ok` до/после rollout; installer backup SQLite `ok` |
| Systemd & sockets | **PASS** | `3xui-pro-fork.service`, `nginx.service`, `3xui-preview-renew.timer` `active/enabled`; `3xui-pro-fork-awg.service` и `3xui-preview-xray.service` `inactive/disabled`; `xproawg0` удалён ([post-rollout-health.json](post-rollout-health.json)) |
| RAM, CPU/Disk & OOM | **PASS** | `MemTotal=967 MiB`, `MemAvailable=622 MiB` (после rollout свободнее за счёт снятия отдельного процесса `amneziawg-go`), `Swap=0`, load `0.15`, `/` free `7.78 GiB`, **`oom_count: 0`** |

---

## Отдельные результаты: WireGuard (`WIREGUARD`) vs AmneziaWG 3.1 (`AMNEZIAWG-3.1`)

| Критерий | `WIREGUARD` | `AMNEZIAWG-3.1` |
|---|---|---|
| Итоговый статус | **WIREGUARD: PASS** | **AMNEZIAWG-3.1: PASS** |
| Порт / подсеть / MTU сервера | UDP `51820` / `10.89.8.0/24` / `1420` | UDP `29177` / `10.88.32.0/24` / `1420` |
| Runtime owner | `xray-linux-amd64` (`noKernelTun: true`) | `x-ui` MainPID (`amneziawgnet 3.1.20260828`, `kernelMode: false`) → Xray SOCKS5 |
| Криптография и параметры | Pure-Python X25519, **без AWG-полей** | `awg v3.1.20260812` + `HeaderProtectionKey` + `Jc=4,Jmin=40,Jmax=70,S1..S4=12,H1..H4=1..4` |
| Проверка изоляции | Отдельный inbound `id=4`, отдельный клиент `prod-smoke-wg-f0b87064` | Отдельный inbound `id=5`, клиент `prod-smoke-awg31-69201dc1`, **plain WG отклонён на UDP `29177`** |
| Handshake & UDP DNS (`MTU=1420`) | Epoch `1795510541`, HTTP IP `179.254.154.126`, DNS `1.1.1.1:53` **PASS** | Epoch `1795510647`, HTTP IP `179.254.154.126`, DNS `1.1.1.1:53` **PASS** |
| Полный PQ TLSv1.3 HTTPS (`MTU=1280` клиента*) | Epoch `1795510543`, HTTPS IP `179.254.154.126`, `rx=6860`, `tx=4116`, DNS **PASS** | Epoch `1795510648`, HTTPS IP `179.254.154.126`, `rx=6684`, `tx=4599`, DNS **PASS** |
| CRUD (ротация / disable / re-enable / del) | **PASS** (старый ключ/disabled/deleted отклонены) | **PASS** (с ожиданием ~30s Xray SOCKS5 reconcile) |

> [!IMPORTANT]
> \*Локальный измеренный клиентский путь (Windows Docker Desktop / WSL2 / локальный ISP → `179.254.154.126`) пропускает HTTP TCP и UDP DNS при клиентском `MTU=1420`, но фрагментирует/теряет return-пакеты для 1568-байтного постквантового `TLSv1.3 ClientHello` (`X25519MLKEM768`) при `MTU=1420`; при клиентском `MTU=1280` полный HTTPS PQ TLSv1.3 проходит чисто без изменения серверного `MTU=1420`.

---

## Первоначальные сбои инструментов проверки и честная фиксация

1. **`smoke_1_vless.py` (первый прогон анализа `/json/<subId>`)**: ожидалась устаревшая структура `outbounds[0].settings.vnext[0]`, тогда как `3x-ui 3.11.0` / `Xray 26.11.9` генерирует плоскую схему (`address`/`port`/`id`). Скрипт адаптирован; live Xray P0/P1/P3 отработал **PASS**.
2. **`smoke_2_wireguard.py` (первый прогон, эфемерный `prod-smoke-wg-50f36719`)**: `udp_ok: true`, handshake получен (`1795510439`), однако `https://api.ipify.org` (1568 B PQ TLSv1.3 `ClientHello`) не завершился на `MTU=1420` по описанной причине внешнего пути; диагностика подтвердила `HTTP=179.254.154.126` на `MTU=1420` и полный `HTTPS=179.254.154.126` на клиентском `MTU=1280` без изменения серверного `MTU=1420`. Старый тестовый клиент `prod-smoke-wg-50f36719` удалён.
3. **`smoke_6_ui_web_health.py` (первые два прогона `Clients` UI)**: SPA-переход Vue Router не дожидался размонтирования таблицы `Inbounds` до выборки `table thead`; после явного ожидания маршрута `/clients` и таблицы не-`Protocol` Playwright подтвердил `6` клиентских строк (`preview-P0/P1/P3`, `starter-*`) с `0` ошибок.
