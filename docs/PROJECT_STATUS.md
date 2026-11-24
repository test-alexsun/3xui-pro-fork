# Статус проекта

Сводка на 2026-11-24. **PREVIEW-XONIX-08: PASS на чистой лабораторной Debian 13 VM** для всех шести управляемых панелью inbound (`VLESS-REALITY-XHTTP-H2`, `VLESS-TLS-XHTTP-H2`, `VLESS-REALITY-VISION`, `WIREGUARD`, `AMNEZIAWG-3.1`, `HYSTERIA2`) и универсального Debian 13 установщика.

| Область | Подтверждённое состояние |
|---|---|
| Рабочая ветка | `preview/xonix-standalone-debian13` |
| Базовый preview HEAD до финальной интеграции | `4c5ebd98f434723c1f424dbb4e50de3709ef1463` |
| Native VLESS implementation baseline | `a3a6b991eb21dc2b4822c4fae13426d91e19db48` |
| GitHub `main` | `7e822e3e5dfe6f6e95c57fc83b24d00cd7fde661` (**не изменялся**) |
| Production VPS `de126` (`179.254.154.126`) | **Не изменялся** (read-only audit: `3xui-pro-fork.service` + `3xui-pro-fork-awg.service` UDP `29177` + `nginx` + `3xui-preview-renew.timer` active, `3xui-preview-xray.service` inactive, 3 VLESS `READY`, `preview-vpn-inbounds.json` отсутствует, порты `51820` и `24443` не слушаются) |
| Историческая регрессия (07A) | `318/318 PASS` (сохранена без пересборки) |
| Unit & contract suites (Debian 13 Docker) | `tests/release` **79/79 OK**, `tests/protocols` **69 (66 OK, 3 E2E skipped)**, `tests/integration` **15 (14 OK, 1 E2E skipped)** |
| Чистая Debian 13 VM приёмка (PREVIEW-XONIX-08) | **PASS**: fresh install (`READY`/`READY`), safe repeat (`preserved_exact_identity: true`), P0/P1/P3 + XONIX + VLESS subs, независимые E2E `WIREGUARD`, `AMNEZIAWG-3.1`, `HYSTERIA2`, одновременная работа и изоляция всех 6, Playwright Chromium UI (6 Inbounds + 6 Clients), HTTP `308`, SQLite `ok`, OOM `0` |

## Что реализовано и подтверждено

1. Универсальный Debian 13 installer (`install-preview.sh` / `release/preview_install.py`) с режимами:
   - по умолчанию (`--panel-inbounds`): устанавливает все 6 управляемых inbound (`install_candidate.py --no-standalone-awg` → `preview_panel_inbounds.py` → `preview_vpn_inbounds.py`);
   - `--vless-only`: сохраняет старую схему 3 VLESS + `3xui-pro-fork-awg.service`;
   - `--panel-inbounds --add-vpn-inbounds` (+ `--handoff-standalone-awg`): opt-in добавление WG/AWG 3.1/HY2 на существующий 3-VLESS `READY` узел.
2. Независимые протокольные модули и E2E:
   - `release/preview_wireguard.py` (`WIREGUARD`, UDP `51820`, `10.89.8.0/24`, `xray-linux-amd64` `noKernelTun: true`, pure-Python X25519);
   - `release/preview_amneziawg31.py` (`AMNEZIAWG-3.1`, UDP `29177`, `10.88.32.0/24`, embedded `amneziawgnet` `3.1.20260828` + `awg` `3.1.20260812` с `HeaderProtectionKey`);
   - `release/preview_hysteria2.py` (`HYSTERIA2`, UDP `24443`, `xray-linux-amd64` v2 TLS/h3 с переиспользованием SAN-сертификата двух доменов).
3. Подробный журнал отчёта и санитайзнутые JSON-результаты: [08 test-results](stages/evidence/preview-xonix-08/test-results.md).

## Известные ограничения

- Тестирование обратной совместимости со старыми standalone `/30` WG/AWG профилями **официально отменено**; проверялись новые синтетические профили, при сохранении production клиентов и ключей без изменений.
- Автоматический full binary updater/rollback и power-loss recovery migration-журналов не реализованы; `kernelMode: true` (`xui-awg<ID>`) не используется; серверный MTU зафиксирован на `1420`.
- Встроенный `AMNEZIAWG-3.1` при изменении клиента (`add`/`update`/`del`) перезапускает Xray на ~30-секундном reconcile-тике для обновления SOCKS5-ретранслятора; `clients/get` и `clients/list` возвращают `allowedIPs` как CSV-строку.
- Выкатка 6-inbound конфигурации на production `de126` не выполнялась и требует отдельного операторского разрешения и maintenance window. См. [ANTIGRAVITY_HANDOFF](ANTIGRAVITY_HANDOFF.md).
