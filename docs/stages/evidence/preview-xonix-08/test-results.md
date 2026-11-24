# PREVIEW-XONIX-08 — финальная лабораторная приёмка шести управляемых Inbounds

**Статус: PASS на чистой лабораторной Debian 13 amd64 VM** (fresh install, safe repeat install, все 6 управляемых inbound `P0`, `P1`, `P3`, `WIREGUARD`, `AMNEZIAWG-3.1`, `HYSTERIA2`, одновременная работа и взаимная изоляция, UI/XONIX Playwright, экспорт, подписки, системное здоровье). **Production `de126` (`179.254.154.126`) и ветка `main` (`7e822e3e5dfe6f6e95c57fc83b24d00cd7fde661`) не изменялись.**

> [!NOTE]
> Исторические результаты раннего 08 lab-этапа ([preview08-existing-initial-results.json](preview08-existing-initial-results.json), [preview08-final-results.json](preview08-final-results.json), [preview08-targeted-results.json](preview08-targeted-results.json), [preview08-restart-recheck.json](preview08-restart-recheck.json), [production-readonly-summary.json](production-readonly-summary.json), [targeted-tests.log](targeted-tests.log)) сохранены без удаления как часть истории ветки. Ниже приведён полный отчёт по завершённой интеграции по всем 23 обязательным пунктам.

---

## Обязательные 23 пункта отчёта

1. **Исходный commit**: `4c5ebd98f434723c1f424dbb4e50de3709ef1463` (на ветке `preview/xonix-standalone-debian13`; implementation baseline `a3a6b991eb21dc2b4822c4fae13426d91e19db48`; предыдущая 08 lab-база `2f275b6be69531eed80cdbcab5015369782afc43`).
2. **Финальный commit**: проверенный implementation/evidence commit `2191f391de54c43a7702380a4afc5ee2943b4486` (хеши исходников — [source-sha256.json](source-sha256.json); следующий docs-only metadata commit фиксирует данный опубликованный hash).
3. **Remote HEAD**: обычный fast-forward push в `origin/preview/xonix-standalone-debian13` проверен через `git ls-remote origin` (`2191f391de54c43a7702380a4afc5ee2943b4486` для implementation commit, далее docs-only commit поверх него; `origin/main` неизменен на `7e822e3e5dfe6f6e95c57fc83b24d00cd7fde661`).
4. **Результаты оркестрации**: соблюдена схема parallel → sequential → unified Debian 13 VM acceptance → docs & security review. Работа продолжена без создания новых серий этапов (`08A`, `09`).
5. **Работа каждого субагента**:
   - *VLESS & UI Engineer*: проверил совместимость `preview_panel_inbounds.py` с 6-inbound строками и реализовал Playwright-набор [preview08-six-inbounds-panel.cjs](../../../../tests/xonix/preview08-six-inbounds-panel.cjs).
   - *WireGuard Protocol Engineer*: реализовал независимый [preview_wireguard.py](../../../../release/preview_wireguard.py) (RFC 7748 X25519 без `awg`), 26 unit-тестов и независимый [wireguard/test_e2e.py](../../../../tests/protocols/wireguard/test_e2e.py).
   - *AmneziaWG 3.1 Engineer*: реализовал независимый [preview_amneziawg31.py](../../../../release/preview_amneziawg31.py) (`kernelMode: false`, `HeaderProtectionKey`, AWG 3.1 `3.1.20260828`/`3.1.20260812`), 22 unit-теста и [amneziawg31/test_e2e.py](../../../../tests/protocols/amneziawg31/test_e2e.py).
   - *Hysteria2 Engineer*: реализовал [preview_hysteria2.py](../../../../release/preview_hysteria2.py) (v2, TLS `h3`, existing SAN cert), 18 unit-тестов и [hysteria2/test_e2e.py](../../../../tests/protocols/hysteria2/test_e2e.py).
   - *Integration / Installer*: доработал [install_candidate.py](../../../../release/install_candidate.py) (`--no-standalone-awg`), [upgrade_candidate.py](../../../../release/upgrade_candidate.py), [preview_panel_inbounds.py](../../../../release/preview_panel_inbounds.py), [preview_vpn_inbounds.py](../../../../release/preview_vpn_inbounds.py), [preview_install.py](../../../../release/preview_install.py) и [tests/integration/](../../../../tests/integration/test_six_inbounds.py).
   - *Security & QA Reviewer*: провёл аудит секретов/путей/прав/SHA256 инвариантов/разделения WG и AWG 3.1 + финальную read-only проверку `de126`.
6. **Архитектурные решения**: зафиксированы в [DECISIONS.md](../../../DECISIONS.md) и [ARCHITECTURE.md](../../../ARCHITECTURE.md) (строго 6 target inbound, 2 домена, Xray userspace WG vs embedded `amneziawgnet` AWG 3.1, Hysteria2 с переиспользованием ACME SAN, серверный MTU `1420`, отмена проверки legacy `/30` и 1.x/2.x профилей, fail-closed журналы).
7. **Шесть Inbounds**: по данным чистой VM ([preview08-fresh-summary.json](preview08-fresh-summary.json), [preview08-ui-results.json](preview08-ui-results.json)) все 6 созданы, включены и видны в UI (`Inbounds`: 6 строк, `Clients`: 6 строк):
   - `id=1` `VLESS-REALITY-XHTTP-H2` (`vless`, TCP `8443`, `xray-linux-amd64`)
   - `id=2` `VLESS-TLS-XHTTP-H2` (`vless`, TCP `443` Nginx → `127.0.0.1:19441` `xray-linux-amd64`)
   - `id=3` `VLESS-REALITY-VISION` (`vless`, TCP `9443`, `xray-linux-amd64`)
   - `id=4` `WIREGUARD` (`wireguard`, UDP `51820`, `xray-linux-amd64`)
   - `id=5` `AMNEZIAWG-3.1` (`amneziawg`, UDP `29177`, `x-ui` MainPID → Xray SOCKS5 loopback)
   - `id=6` `HYSTERIA2` (`hysteria`, UDP `24443`, `xray-linux-amd64`)
8. **Отдельный WireGuard PASS/FAIL**: **PASS** ([preview08-wireguard-results.json](preview08-wireguard-results.json)) — 10/10 проверок PASS (`backend`, `inbound`, `client_config`, `handshake`, `tcp_traffic`, `udp_traffic`, `crud`, `restart`, `persistence`, `ui_api`); `client_driver: linux-kernel-wireguard`, порт UDP `51820`, `tcp_payload_bytes: 65536`, `udp_payload_bytes: 8192`, PID Xray до/после restart `6628 -> 7610`, удаление клиента подтверждено.
9. **Отдельный AWG 3.1 PASS/FAIL**: **PASS** ([preview08-amneziawg31-results.json](preview08-amneziawg31-results.json)) — 10/10 проверок PASS; `amneziawg-go v3.1.20260828`, `amneziawg-tools v3.1.20260812`, порт UDP `29177`, `mtu: 1420`, `negative_plain_wg_rejected: PASS`, `tcp_payload_bytes: 65536`, `udp_datagrams: 16` × `512` B, ротация ключей, disable/enable, restart persistence и удаление подтверждены.
10. **Отдельный Hysteria2 PASS/FAIL**: **PASS** ([preview08-hysteria2-results.json](preview08-hysteria2-results.json)) — 10/10 проверок PASS (`inbound_and_listener_ownership`, `client_create_and_export`, `initial_transfer`, `rotate_auth_old_denied`, `rotate_auth_new_transfer`, `disabled_denied`, `reenabled_transfer`, `restart_persistence_listener`, `restart_persistence_transfer`, `deleted_denied`), UDP `24443`, `65536` B TCP, `16` × `512` B UDP, `alpn: ["h3"]`, строгий CA check.
11. **Результаты P0/P1/P3**: **PASS** ([preview08-existing-results.json](preview08-existing-results.json)) — реальный трафик P0 (uplink `67388`, downlink `68715`), P1 (`67388`/`68715`), P3 (`69726`/`69750`), HTTPS `de126.alexsun55.ru` `200` XONIX + `de126-sub.alexsun55.ru` `404` root. Historical `318/318 PASS` (07A) сохранён без повторного полного прогона.
12. **Проверка независимости WG/AWG**: **PASS** ([preview08-six-inbounds-results.json](preview08-six-inbounds-results.json)) — 7/7 проверок PASS: `six_inbounds_active`, `port_and_ownership_isolation` (`51820` xray vs `29177` `x-ui` vs `24443` xray; `3xui-pro-fork-awg.service` inactive), `subnet_and_key_isolation` (`10.89.8.0/24` vs `10.88.32.0/24`, раздельные ключи), `simultaneous_all_six_traffic`, `disable_wg_keeps_awg_and_others_alive`, `disable_awg_keeps_wg_and_others_alive`, `restart_preserves_all_six`. Плюс 15 тестов в `tests/integration` (14 OK, 1 E2E skipped без live VM).
13. **Client CRUD**: проверен отдельно на реальных клиентах в каждом протокольном E2E (создание `clients/add`, проверка `clients/get`, ротация ключей/auth через `clients/update`, отказ старых ключей/auth, `enable=false`/`true`, `clients/del` с отказом доступа удалённого клиента).
14. **Export**:
    - `WIREGUARD`: стандартный `.conf`, `wireguard://`, `/sub/<subId>`, `/json/<subId>` — подтверждено отсутствие AWG-полей.
    - `AMNEZIAWG-3.1`: `vpn://<base64url>` через `clients/links` и `/sub/<subId>`, декодирование и проверка `HeaderProtectionKey` / `Jc` / `Jmin` / `Jmax` / `S1`–`S4` / `H1`–`H4` / `MTU = 1420`.
    - `HYSTERIA2`: `hysteria2://` через `clients/links` и `/sub/<subId>` с `alpn=h3` и SNI основного домена.
15. **Subscriptions**: `vless_subscriptions` (`sub`, `json`, `clash`) `PASS` в `preview08-existing-results.json`; VPN подписки `/sub/<subId>` (`WIREGUARD`, `AMNEZIAWG-3.1`, `HYSTERIA2`) и `/json/<subId>` (`WIREGUARD`) подтверждены по HTTPS с проверкой SAN/CA на подписочном домене.
16. **Fresh installation**: **PASS** на чистой Debian 13 VM ([preview08-fresh-summary.json](preview08-fresh-summary.json)) через `install-preview.sh --public-bind 10.77.5.1 ... --awg-subnet 10.88.32.0/24 --wg-subnet 10.89.8.0/24 --wg-port 51820 --awg-port 29177 --hy2-port 24443 --panel-inbounds` (`native_journal: READY`, `vpn_journal: READY`, `sqlite_integrity: ok`).
17. **Safe repeat**: **PASS** ([preview08-repeat-summary.json](preview08-repeat-summary.json)) — повтор с идентичными аргументами завершился кодом `0`, сохранил все 6 `id`, клиентов, ключи и SHA256 `settings`/`streamSettings` (`preserved_exact_identity: true`).
18. **Recovery**: `preview-panel-inbounds.json` и `preview-vpn-inbounds.json` fail-closed; переход в `RECOVERY_REQUIRED` без удаления VLESS подтверждён модульным тестом в [test_panel_api.py](../../../../tests/integration/test_panel_api.py) и зафиксирован в реальной VM при первом диагностированном сбое. Автоматический rollback после `READY` отсутствует по дизайну ([RECOVERY.md](../../../RECOVERY.md)).
19. **Security**: независимый аудит `Security & QA Reviewer` подтвердил 0 секретов/приватных ключей/токенов/паролей/куки/SQLite/Windows-путей в diff и 9 JSON-отчётах, `0` CRLF, сохранение `100755` на `bootstrap-preview.sh` и `install-preview.sh`, неизменность SHA256 pinned-файлов (`awg_service.py`, `awg_config_candidate.py`, `3xui-pro-fork.service`, `3xui-pro-fork-awg.service`, `HOOK_SCRIPT`), корректные `HttpOnly`/`Secure`/`SameSite=Lax` cookie панели и DNS/HTTP-`308`/TLS CA проверки в [preview08-common-health.json](preview08-common-health.json) (`oom_events: 0`).
20. **Documentation**: обновлены `README.md`, `GEMINI.md`, `AGENTS.md`, `.agents/rules/*.md`, `docs/ARCHITECTURE.md`, `docs/PROTOCOLS.md` (раздельные секции WG и AWG 3.1), `docs/INSTALLATION.md`, `docs/OPERATIONS.md`, `docs/RECOVERY.md`, `docs/TESTING.md`, `docs/PROJECT_STATUS.md`, `docs/ANTIGRAVITY_HANDOFF.md`, `docs/DECISIONS.md` и этот отчёт.
21. **Production unchanged**: read-only SSH аудит `de126` (`179.254.154.126`) до и после работы подтвердил неизменность: `3xui-pro-fork.service`, `3xui-pro-fork-awg.service`, `nginx`, `3xui-preview-renew.timer` активны; `3xui-preview-xray.service` inactive; `preview-panel-inbounds.json` `READY` с 3 VLESS; `preview-vpn-inbounds.json` отсутствует; на UDP слушается только `29177` (`amneziawg-go` `pid=85900`), порты `51820` и `24443` отсутствуют.
22. **Main unchanged**: `origin/main` и локальный `main` не изменялись — `7e822e3e5dfe6f6e95c57fc83b24d00cd7fde661`.
23. **Оставшиеся ограничения**: отмена проверки legacy `/30` и AWG 1.x/2.x клиентских профилей (синтетические профили проверены, production ключи не тронуты); отсутствует full binary updater и power-loss recovery журналов; `kernelMode: true` AWG не используется; серверный MTU `1420` не меняется; embedded AWG 3.1 перезапускает Xray на ~30s reconcile-тике при изменении клиентов; выкатка на production требует отдельного разрешения.

---

## Отдельная сравнительная таблица: WireGuard vs AWG 3.1

| Параметр | WireGuard (`WIREGUARD`) | AWG 3.1 (`AMNEZIAWG-3.1`) |
|---|---|---|
| Runtime | Native `xray-linux-amd64` `26.11.9` userspace (`noKernelTun: true`) | Embedded `amneziawgnet` (`amneziawg-go v3.1.20260828`, `kernelMode: false`) в `x-ui` MainPID → loopback SOCKS5 `xray-linux-amd64` |
| UDP port | `51820` (`--wg-port`, без `29177`) | `29177` (`--awg-port`) |
| Subnet | `10.89.8.0/24` (`--wg-subnet`) | `10.88.32.0/24` (`--awg-subnet`; `/30` в `--vless-only`) |
| Server keys | Separate (`xray` pure-Python X25519 `secretKey`) | Separate (`awg` tools X25519 + `HeaderProtectionKey` + `Jc`/`Jmin`/`Jmax`/`S1`-`S4`/`H1`-`H4`) |
| Client keys | Separate (RFC 7748 X25519, отдельные клиенты `clients.wg_*`) | Separate (`awg genkey`/`pubkey`, отдельные клиенты `clients.wg_*`) |
| Inbound | ID `4`, tag `WIREGUARD`, protocol `wireguard` | ID `5`, tag `AMNEZIAWG-3.1`, protocol `amneziawg` |
| UI/API | Нативный UI (`Inbounds`/`Clients`) + API + `preview_wireguard.py` | Нативный UI (`Inbounds`/`Clients`) + API + `preview_amneziawg31.py` |
| Client creation | `clients/add` (`starter-wireguard` + E2E клиенты), экспорт `.conf`/`wireguard://`/`/sub`/`/json` | `clients/add` (`starter-amneziawg31` + E2E клиенты), экспорт `vpn://` → `.conf`/`setconf`, негативный отказ plain WG |
| Handshake | **PASS** (`linux-kernel-wireguard`, `initial_handshake_epoch: 1795494779`) | **PASS** (`amneziawg-go v3.1.20260828` + `awg v3.1.20260812` positive handshake) |
| Bidirectional traffic | **PASS** (`tcp_payload_bytes: 65536`, `udp_payload_bytes: 8192`) | **PASS** (`tcp_payload_bytes: 65536`, `udp_datagrams: 16` × `512` B) |
| Restart | **PASS** (`xray_pid 6628 -> 7610`, repeat install & `systemctl restart`) | **PASS** (`systemctl restart 3xui-pro-fork.service` + 30s SOCKS5 reconcile) |
| Persistence | **PASS** (состояние ротированных ключей и `enable` в SQLite сохранено) | **PASS** (состояние ротированных ключей и `enable` в SQLite сохранено) |
| E2E result | **PASS** (10/10 в `preview08-wireguard-results.json` + изоляция в `preview08-six-inbounds-results.json`) | **PASS** (10/10 в `preview08-amneziawg31-results.json` + изоляция в `preview08-six-inbounds-results.json`) |

---

## Первоначальные ошибки и точные исправления до финального PASS

В соответствии с правилом не скрывать первоначальные ошибки зафиксированы все четыре проблемы, выявленные до чистого итогового PASS:
1. **Fresh install `RECOVERY_REQUIRED` в VM**: на первом VM-прогоне `_validate_awg_row()` в [release/preview_vpn_inbounds.py](../../../../release/preview_vpn_inbounds.py) проверял `server.get('kernelMode') is not False`, тогда как Go-тег `json:"kernelMode,omitempty"` в `3x-ui 3.11.0` опускает `"kernelMode": false` при возврате JSON через `inbounds/list`. Исправлено на `bool(server.get('kernelMode', False))`, покрыто unit-тестом и подтверждено с чистого `disk.qcow2` (`READY`).
2. **WireGuard `clients/get` mismatch в `wireguard/test_e2e.py`**: первый прогон остановился на сравнении `allowedIPs`, поскольку `clients/get` и `clients/list` в `3x-ui 3.11.0` возвращают CSV-строку (`"10.89.8.2/32"`), а не JSON-массив. Добавлена нормализация `_split_allowed_ips()` без изменения контракта API.
3. **AmneziaWG 3.1 TCP reset после CRUD в `amneziawg31/test_e2e.py` и `test_six_inbounds.py`**: добавление/изменение/удаление клиента ставит `SetToNeedRestart()`, а ~30-секундный reconcile-тик `3x-ui 3.11.0` принудительно перезапускает Xray из-за password-auth SOCKS5 inbound; старая 0.5s пауза приводила к TCP `ConnectionResetError(104)` после успешного UDP handshake. Добавлено детерминированное ожидание конвергенции аккаунтов SOCKS5 в `config.json` и `lsi`.
4. **Транзиентный 30s timeout Chromium в Playwright (`networkidle`)**: после рестарта `test_six_inbounds` первичный переход к `https://de126.alexsun55.ru/` превысил 30s (`nameserver 127.0.0.53` недоступен внутри `preview-client` netns при высокой нагрузке QEMU); повторный запуск того же чистого UI-сценария [preview08-six-inbounds-panel.cjs](../../../../tests/xonix/preview08-six-inbounds-panel.cjs) и common health check [preview08-common-health.json](preview08-common-health.json) завершились `PASS`.

## Файлы доказательств

- [preview08-fresh-summary.json](preview08-fresh-summary.json) — свежая установка 6 inbound (`READY`/`READY`)
- [preview08-repeat-summary.json](preview08-repeat-summary.json) — безопасный идемпотентный повтор
- [preview08-existing-results.json](preview08-existing-results.json) — P0/P1/P3, XONIX HTTPS, VLESS subscriptions
- [preview08-wireguard-results.json](preview08-wireguard-results.json) — независимый WireGuard E2E (`PASS`)
- [preview08-amneziawg31-results.json](preview08-amneziawg31-results.json) — независимый AmneziaWG 3.1 E2E (`PASS`)
- [preview08-hysteria2-results.json](preview08-hysteria2-results.json) — независимый Hysteria2 E2E (`PASS`)
- [preview08-six-inbounds-results.json](preview08-six-inbounds-results.json) — одновременная работа и изоляция всех 6 inbound (`PASS`)
- [preview08-ui-results.json](preview08-ui-results.json) — Playwright Chromium UI (`Inbounds`, `Clients`, `XONIX`) (`PASS`)
- [preview08-common-health.json](preview08-common-health.json) — HTTP `308`, `nginx -t`, SQLite `ok`, systemd, `oom_events: 0`
- [source-sha256.json](source-sha256.json) — контрольные суммы исходников и тестов
