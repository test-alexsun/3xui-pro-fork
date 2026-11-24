# Контекст Gemini Antigravity

Прочитайте [AGENTS.md](AGENTS.md): это общие обязательные правила. Здесь актуальная карта проекта, а не transcript прошлых чатов.

## Проект и статус

`test-alexsun/3xui-pro-fork`, preview `preview/xonix-standalone-debian13`, Debian 13 amd64/systemd. Установщик объединяет `3x-ui`, `Xray`, `Nginx`, `Let's Encrypt`, `XONIX` и шесть нативных панельных inbound: `P0`, `P1`, `P3`, `WIREGUARD`, `AMNEZIAWG-3.1`, `HYSTERIA2`.

**PREVIEW-XONIX-08: PASS на чистой Debian 13 lab VM** (все шесть управляемых inbound, fresh install, safe repeat, UI, subscriptions, common health и отдельные protocol/integration suites). **Production `de126` (`179.254.154.126`) и ветка `main` (`7e822e3e5dfe6f6e95c57fc83b24d00cd7fde661`) не изменялись**: production остаётся на `a3a6b991eb21dc2b4822c4fae13426d91e19db48` (3 VLESS + отдельный `3xui-pro-fork-awg.service` на UDP `29177`). См. [PROJECT_STATUS](docs/PROJECT_STATUS.md) и [08 evidence](docs/stages/evidence/preview-xonix-08/test-results.md).

## Закреплённый tuple

Panel `3.11.0`, Xray `26.11.9`, `amneziawg-go` `3.1.20260828`, `awg` tools `3.1.20260812`; Nginx Debian Security `1.26.3-3+deb13u11`. Не обновлять floating upstream командой. Distribution manifests, hashes и licenses: [release/distribution](release/distribution/README.md).

## Шесть управляемых inbound и изоляция WG / AWG 3.1

WireGuard и AmneziaWG 3.1 — независимые обязательные протоколы. Они имеют отдельные конфигурации, runtime ownership, порты, подсети, клиентов и acceptance tests. Результат проверки одного протокола не подтверждает работоспособность другого.

| Tag | Протокол / режим | Порт / bind | Runtime owner | Подсеть / TLS / Auth |
|---|---|---|---|---|
| `VLESS-REALITY-XHTTP-H2` (P0) | `vless`, REALITY + XHTTP H2 | TCP `8443` (`--p0-port`) | Xray child `xray-linux-amd64` | UUID + REALITY keys/shortIds |
| `VLESS-TLS-XHTTP-H2` (P1) | `vless`, XHTTP H2 за Nginx TLS | Public TCP `443` → `127.0.0.1:19441` | Nginx TLS + Xray child | UUID + Let's Encrypt SAN (`externalProxy`) |
| `VLESS-REALITY-VISION` (P3) | `vless`, raw/`tcp` REALITY Vision | TCP `9443` (`--p3-port`) | Xray child `xray-linux-amd64` | UUID + `xtls-rprx-vision` |
| `WIREGUARD` | `wireguard`, `noKernelTun: true`, MTU `1420` | UDP `51820` (`--wg-port`, без `29177`) | Xray child `xray-linux-amd64` | RFC1918 `10.89.8.0/24` (`--wg-subnet`), pure-Python X25519, без AWG-полей |
| `AMNEZIAWG-3.1` | `amneziawg`, `kernelMode: false`, MTU `1420` | UDP `29177` (`--awg-port`) | Embedded `amneziawgnet` в `x-ui` MainPID → Xray SOCKS5 loopback | RFC1918 `/16../30` (`10.88.32.0/24` в 6-inbound, `/30` в `--vless-only`), `awg` keys + `HeaderProtectionKey` |
| `HYSTERIA2` | `hysteria` v2, QUIC/TLS `h3` | UDP `24443` (`--hy2-port`) | Xray child `xray-linux-amd64` | `auth` token + two-domain ACME cert (`/var/lib/3xui-preview-acme`) |

Подробности по каждому протоколу: [PROTOCOLS](docs/PROTOCOLS.md). Встроенный `AMNEZIAWG-3.1` при добавлении/изменении/удалении клиента вызывает асинхронный полный перезапуск Xray на ~30-секундном reconcile-тике `3x-ui` из-за password-auth SOCKS5 inbound; при сериализации Go `omitempty` опускает `"kernelMode": false`.

## Флаги установщика и режимы

- Fresh `--panel-inbounds` (по умолчанию): устанавливает все 6 управляемых inbound через `install_candidate.py --no-standalone-awg`, `preview_panel_inbounds.py` и `preview_vpn_inbounds.py`. Бинарники AWG сохраняются в `/opt/3xui-pro-fork/awg/`, unit `3xui-pro-fork-awg.service` остаётся inactive/disabled.
- `--vless-only`: opt-out при fresh install для сохранения прежней схемы (3 VLESS + отдельный `3xui-pro-fork-awg.service` на `/30`).
- `--panel-inbounds --add-vpn-inbounds` (плюс `--handoff-standalone-awg`, если активен `3xui-pro-fork-awg.service`): opt-in добавление WG/AWG3.1/HY2 на существующий 3-VLESS `READY` узел.

## Где читать и менять

| Путь | Назначение |
|---|---|
| `bootstrap-preview.sh`, `install-preview.sh` | Immutable checkout и installer entrypoint |
| `release/preview_install.py`, `install_candidate.py`, `upgrade_candidate.py` | Проверки ownership, orchestration и install/upgrade flags |
| `release/preview_two_domain.py`, `preview_transport.py`, `preview_acme.py` | Two-domain Nginx layout, VLESS transports и ACME TLS ownership |
| `release/preview_panel_inbounds.py`, `preview_panel_api.py` | Native P0/P1/P3 API import, verify и durable handoff (`preview-panel-inbounds.json`) |
| `release/preview_wireguard.py` | Независимый WireGuard модуль: X25519, `.conf`, `wireguard://`, listener/API checks |
| `release/preview_amneziawg31.py` | Независимый AWG 3.1 модуль: `awg` keys/HPK, `vpn://`, `.conf`/`setconf`, listener checks |
| `release/preview_hysteria2.py` | Hysteria2 v2 контракт, `hysteria2://`, TLS/h3 проверка, outbound/listener checks |
| `release/preview_vpn_inbounds.py` | Six-inbound VPN orchestration (`provision_vpn_inbounds`, `verify_ready`, `preview-vpn-inbounds.json`) |
| `release/awg_service.py`, `awg_config_candidate.py` | Standalone AWG supervisor и `/30` generator (режим `--vless-only` и unmutated production) |
| `release/distribution/` | Pinned AWG distribution, sources, лицензии |
| `assets/decoy/xonix/` | Original game HTML |
| `tests/protocols/`, `tests/integration/`, `tests/release/`, `tests/xonix/` | Protocol/integration unit & E2E suites, UI Playwright и historical checks |
| `docs/DECISIONS.md` | Зафиксированные архитектурные решения (ADR) |
| `docs/stages/evidence/` | Historical reports и PREVIEW-XONIX-08 acceptance JSONs |

## Архитектурные решения и инварианты

Debian 13 amd64/systemd закреплён для единообразных пакетов и unit ownership. Strict layout использует ровно два домена. Native panel API/SQLite (`/var/lib/3xui-pro-fork/x-ui.db`) — текущий источник истины для всех 6 inbound, клиентов и подписок; pre-migration snapshots после `READY` используются только для recovery.

Оба migration journal (`preview-panel-inbounds.json` и `preview-vpn-inbounds.json`) fail-closed: после `READY` автоматический reverse/rollback запрещён; `RECOVERY_REQUIRED` требует ручной диагностики с сохранением backups. См. [ARCHITECTURE](docs/ARCHITECTURE.md), [DECISIONS](docs/DECISIONS.md), [RECOVERY](docs/RECOVERY.md).

## Разработка и проверки

Читайте owning source перед правкой. Сохраняйте существующих клиентов, UUID, ключи, short IDs, порты, домены и сертификаты. Historical `318/318 PASS` (07A) не перезапускайте на каждом docs/targeted изменении. Для code changes запускайте `tests/protocols/`, `tests/integration/`, targeted `tests/release/`, а полный live E2E — только в disposable Debian 13 lab с `PREVIEW08_RUN_E2E=1` и `/var/lib/3xui-preview08-lab`. Подробности в [TESTING](docs/TESTING.md).

Read-only Linux diagnostics: `systemctl status 3xui-pro-fork.service nginx --no-pager`, `systemctl is-active 3xui-pro-fork-awg.service 3xui-preview-xray.service`, `ss -H -ltnp`, `ss -H -lunp`, `nginx -t`, `free -m`, `df -h`. Никогда не выполнять production fault injection или restart по разрешению на аудит.

## GitHub и безопасность

Работайте только в `preview/xonix-standalone-debian13`, обычные commits/push, remote HEAD verification. `main` (`7e822e3e5dfe6f6e95c57fc83b24d00cd7fde661`) и force push запрещены. Проверять staged diff на secrets, private DB/backups, персональные Windows paths и CRLF; не публиковать raw private evidence. Точная publication revision фиксируется только после push.

## Известные ограничения

- Тестирование совместимости со старым standalone AWG `/30` клиентским профилем **официально отменено**: проверяются новые синтетические клиенты WG и AWG 3.1, при сохранении production клиентов/ключей без изменений.
- Full binary updater/rollback и power-loss recovery журналов не реализованы; `kernelMode: true` AWG не принят; server MTU `1420` не меняется (client MTU `1368` — только для измеренного 07A path); `clients/get` и `clients/list` возвращают `allowedIPs` как CSV-строку, а `inbounds/list` — как список.
- Production six-inbound rollout не выполнялся и требует отдельного операторского разрешения и maintenance window. См. [ANTIGRAVITY_HANDOFF](docs/ANTIGRAVITY_HANDOFF.md), [INSTALLATION](docs/INSTALLATION.md), [OPERATIONS](docs/OPERATIONS.md).
