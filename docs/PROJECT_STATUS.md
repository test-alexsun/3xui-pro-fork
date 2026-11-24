# Статус проекта

Сводка на 2026-11-24. **SIX-INBOUNDS-PRODUCTION: PASS на VPS `de126` (`179.254.154.126`)** и **PREVIEW-XONIX-08: PASS на чистой лабораторной Debian 13 VM** для всех шести управляемых панелью inbound (`VLESS-REALITY-XHTTP-H2`, `VLESS-TLS-XHTTP-H2`, `VLESS-REALITY-VISION`, `WIREGUARD`, `AMNEZIAWG-3.1`, `HYSTERIA2`) и универсального Debian 13 установщика.

| Область | Подтверждённое состояние |
|---|---|
| Рабочая ветка | `preview/xonix-standalone-debian13` |
| Implementation commit 6 Inbounds | `2191f391de54c43a7702380a4afc5ee2943b4486` |
| Checked rollout revision (`de126` installed SHA) | `9e44b525685458f00c34effe6795814b1da24da9` |
| GitHub `main` | `e1240960c49db774fada954340184f625bacc768` (**не изменялся**; ранее фиксировался `7e822e3e5dfe6f6e95c57fc83b24d00cd7fde661`) |
| Production VPS `de126` (`179.254.154.126`) | **PASS (6 управляемых Inbounds)**: `3xui-pro-fork.service` + `nginx` + `3xui-preview-renew.timer` `active/enabled`; `3xui-pro-fork-awg.service` и `3xui-preview-xray.service` `inactive/disabled`; `preview-panel-inbounds.json` `READY` (`P0`, `P1`, `P3` SHA256 неизменены) и `preview-vpn-inbounds.json` `READY` (`WIREGUARD`, `AMNEZIAWG-3.1`, `HYSTERIA2`); SQLite `ok`; `MemAvailable=622 MiB`; `oom_count=0` |
| Production backups (`de126`) | `/var/backups/3xui-pro-fork/pre-6inbounds-20261124T084510Z` (`23` файла, `manifest.sha256` PASS, SQLite online backup `ok` + архив `/var/lib/3xui-pro-fork/awg/`) и `/var/lib/3xui-pro-fork/preview08-backup-482dd1cdafd75fdd` (SQLite `ok`) |
| Историческая регрессия (07A) | `318/318 PASS` (сохранена без пересборки) |
| Unit & contract suites (Debian 13 Docker) | `tests/release` **79/79 OK**, `tests/protocols` **69 (66 OK, 3 E2E skipped)**, `tests/integration` **15 (14 OK, 1 E2E skipped)** |
| Чистая Debian 13 VM приёмка (PREVIEW-XONIX-08) | **PASS**: fresh install (`READY`/`READY`), safe repeat, P0/P1/P3 + XONIX + VLESS subs, независимые E2E `WIREGUARD`, `AMNEZIAWG-3.1`, `HYSTERIA2`, одновременная работа всех 6, Playwright Chromium UI, HTTP `308`, SQLite `ok`, OOM `0` |
| Production E2E & UI приёмка (`de126`) | **PASS**: safe repeat (`rc=0`), внешние E2E smoke P0/P1/P3, независимые `WIREGUARD: PASS` (UDP `51820`), `AMNEZIAWG-3.1: PASS` (UDP `29177`, отказ plain WG), `HYSTERIA2: PASS` (UDP `24443`, trusted Let's Encrypt CA), одновременная работа всех 6 + planned restart + отзыв smoke-клиентов, Playwright Chromium UI (6 Inbounds + 6 Clients + XONIX), `nginx -t`, `PRAGMA integrity_check == ok` |

## Что реализовано и подтверждено

1. Универсальный Debian 13 installer (`install-preview.sh` / `release/preview_install.py`) с режимами:
   - по умолчанию (`--panel-inbounds`): устанавливает все 6 управляемых inbound (`install_candidate.py --no-standalone-awg` → `preview_panel_inbounds.py` → `preview_vpn_inbounds.py`);
   - `--vless-only`: сохраняет старую схему 3 VLESS + `3xui-pro-fork-awg.service`;
   - `--panel-inbounds --add-vpn-inbounds --handoff-standalone-awg`: успешно применён на production `de126` 2026-11-24 для перехода с 3-VLESS `READY` + standalone AWG на 6 нативных inbound с сохранением P0/P1/P3 и архива `/var/lib/3xui-pro-fork/awg/`.
2. Независимые протокольные модули и подтверждённая работа на lab VM и production `de126`:
   - `release/preview_wireguard.py` (`WIREGUARD`, UDP `51820`, `10.89.8.0/24`, `xray-linux-amd64` `noKernelTun: true`, pure-Python X25519);
   - `release/preview_amneziawg31.py` (`AMNEZIAWG-3.1`, UDP `29177`, `10.88.32.0/24`, embedded `amneziawgnet` `3.1.20260828` + `awg` `3.1.20260812` с `HeaderProtectionKey`);
   - `release/preview_hysteria2.py` (`HYSTERIA2`, UDP `24443`, `xray-linux-amd64` v2 TLS/h3 с переиспользованием SAN-сертификата двух доменов).
3. Подробные журналы отчётов: [PRODUCTION_ROLLOUT_6_INBOUNDS](PRODUCTION_ROLLOUT_6_INBOUNDS.md), [production `de126` evidence](stages/evidence/production-de126-6inbounds/test-results.md) и [08 lab test-results](stages/evidence/preview-xonix-08/test-results.md).

## Известные ограничения

- Тестирование обратной совместимости со старыми standalone `/30` WG/AWG профилями **официально отменено**: на `de126` старые standalone `/30` AWG-профили (`10.88.31.0/30`) после handoff не обслуживаются (при сохранении старых конфигов/ключей в `/var/lib/3xui-pro-fork/awg/` и pre-rollout backup); активны новые нативные клиенты панели (`10.88.32.0/24`).
- Серверный MTU зафиксирован на `1420`; на внешнем WAN-пути (Docker/WSL2/ISP → `179.254.154.126`) 1568 B PQ TLSv1.3 `ClientHello` требует клиентский `MTU <= 1280..1368` (HTTP и UDP DNS работают и на `MTU=1420`).
- Автоматический full binary updater/rollback и power-loss recovery migration-журналов не реализованы; `kernelMode: true` (`xui-awg<ID>`) не используется.
- Встроенный `AMNEZIAWG-3.1` при изменении клиента (`add`/`update`/`del`) перезапускает Xray на ~30-секундном reconcile-тике для обновления SOCKS5-ретранслятора; `clients/get` и `clients/list` возвращают `allowedIPs` как CSV-строку.
