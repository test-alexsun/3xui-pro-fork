# 3xui-pro-fork — Debian 13 preview

Воспроизводимый установщик `3x-ui`, `Xray`, `AmneziaWG 3.1`, `WireGuard`, `Hysteria2`, `Nginx`, `Let's Encrypt` и игры `XONIX Neon Frontier`. Целевая ОС — **Debian 13 amd64 с systemd**.

**PREVIEW-XONIX-08: PASS на чистой лабораторной Debian 13 VM** для всех шести управляемых панелью inbound (`P0`, `P1`, `P3`, `WIREGUARD`, `AMNEZIAWG-3.1`, `HYSTERIA2`). **Production `de126` (`179.254.154.126`) и ветка `main` (`7e822e3e5dfe6f6e95c57fc83b24d00cd7fde661`) не изменялись**: production продолжает работать на `a3a6b991eb21dc2b4822c4fae13426d91e19db48` (три VLESS + отдельный AWG `29177`). См. [статус проекта](docs/PROJECT_STATUS.md) и [отчёт PREVIEW-XONIX-08](docs/stages/evidence/preview-xonix-08/test-results.md).

## Возможности и шесть протоколов

| Tag / компонент | Runtime и транспорт | Порт / сеть по умолчанию | Аутентификация, export и статус |
|---|---|---|---|
| `VLESS-REALITY-XHTTP-H2` (P0) | Native `3x-ui` → `xray-linux-amd64` `26.11.9`, REALITY + XHTTP H2 | TCP `8443` (`--p0-port`) | UUID, REALITY keys/shortId; `/sub`, `/json`, `/clash`; **PASS** |
| `VLESS-TLS-XHTTP-H2` (P1) | Nginx TLS/H2 → loopback `127.0.0.1:19441` (`xray-linux-amd64`) | Public TCP `443` | UUID + TLS (`externalProxy` SAN); `/sub`, `/json`, `/clash`; **PASS** |
| `VLESS-REALITY-VISION` (P3) | Native `3x-ui` → `xray-linux-amd64`, REALITY + Vision | TCP `9443` (`--p3-port`) | UUID + `xtls-rprx-vision`; `/sub`, `/json`, `/clash`; **PASS** |
| `WIREGUARD` | Native `3x-ui` → `xray-linux-amd64` userspace (`noKernelTun: true`) | UDP `51820` (`--wg-port`), `10.89.8.0/24` (`--wg-subnet`) | Pure-Python X25519 (`clients.wg_*`), zero AWG; `.conf`, `wireguard://`, `/sub`, `/json`; **PASS** |
| `AMNEZIAWG-3.1` | Embedded `amneziawgnet` в `x-ui` MainPID (`kernelMode: false`) → Xray SOCKS5 loopback | UDP `29177` (`--awg-port`), `10.88.32.0/24` (`--awg-subnet`) | `awg` keys + `HeaderProtectionKey` + obfuscation; `vpn://` → `.conf`/`setconf`; **PASS** |
| `HYSTERIA2` | Native `3x-ui` → `xray-linux-amd64` v2, `network: hysteria`, TLS `h3` | UDP `24443` (`--hy2-port`), two-domain ACME cert | 32-byte `auth` secret; `hysteria2://`, `/sub`; **PASS** |

WireGuard и AmneziaWG 3.1 реализованы и проверяются **строго независимо** (отдельные модули, порты, подсети, ключи, клиенты и E2E-тесты). Подробности в [PROTOCOLS](docs/PROTOCOLS.md).

Закреплённые версии: `3x-ui` **3.11.0**, `Xray-core` **26.11.9**, `amneziawg-go` **3.1.20260828**, `awg` tools **3.1.20260812**, Nginx Debian Security **1.26.3-3+deb13u11**. [Происхождение и лицензии](release/distribution/README.md).

## Архитектура

`Nginx` публикует два домена: основной домен с XONIX (`/`), защищённым путём панели и `/xhttp/` для P1, а также отдельный домен подписок (`access_log off`, корень `404`). SQLite (`/var/lib/3xui-pro-fork/x-ui.db`) и API панели — источник истины для всех шести inbound, клиентов и подписок. Единственный дочерний процесс `xray-linux-amd64` обслуживает P0, P1, P3, `WIREGUARD`, `HYSTERIA2` и loopback SOCKS5-ретранслятор для `AMNEZIAWG-3.1`; процесс `x-ui` обслуживает UI/API, подписки и embedded `AMNEZIAWG-3.1`. Отдельная служба `3xui-pro-fork-awg.service` остаётся inactive/disabled в 6-inbound режиме и активна только при `--vless-only` или на неизменённом production. [Архитектура](docs/ARCHITECTURE.md), [решения](docs/DECISIONS.md).

## Установка и режимы

Нужны Debian 13 amd64, root, systemd, `/dev/net/tun`, `CAP_NET_ADMIN`, два DNS A-имени, доступ к закреплённым источникам и непересекающиеся RFC1918 подсети. Fresh installer требует минимум 512 MiB свободного диска (используйте `TMPDIR=/var/tmp` при memory-backed `/tmp`).

- **Fresh 6-inbound по умолчанию**: `bootstrap-preview.sh` с `--panel-inbounds` и `--awg-subnet <UNUSED_RFC1918_/16../30>` (и опциональными `--wg-subnet`, `--wg-port`, `--awg-port`, `--hy2-port`) создаёт все 6 управляемых inbound.
- **Opt-out legacy схема**: `--panel-inbounds --vless-only --awg-subnet <UNUSED_RFC1918_/30>` сохраняет схему 3 VLESS + отдельный `3xui-pro-fork-awg.service`.
- **Opt-in апгрейд существующего 3-VLESS READY**: `--panel-inbounds --add-vpn-inbounds` (и `--handoff-standalone-awg`, если активен `3xui-pro-fork-awg.service`). На production запускается только по отдельному разрешению.

Используйте только проверенный immutable commit и SHA256 bootstrap: [установка](docs/INSTALLATION.md). Старый `x-ui-latest.sh` отключён.

## Управление, экспорт и подписки

Клиенты создаются и управляются через защищённый UI (`Inbounds` / `Clients`) или authenticated API панели. Для P3 задаётся `xtls-rprx-vision`. WireGuard экспортируется в стандартный `.conf`, `wireguard://`, `/sub/<subId>` и `/json/<subId>` без AWG-параметров; AmneziaWG 3.1 — в `vpn://<base64url>` (`clients/links` и `/sub/<subId>`) с декодированием в AWG 3.1 `.conf`; Hysteria2 — в `hysteria2://` (TLS/h3, SNI = main domain) через `clients/links` и `/sub/<subId>`. VLESS поддерживает `/sub`, `/json` и `/clash`. Для `AMNEZIAWG-3.1` обновление клиентов запускает ~30-секундный цикл пересборки Xray SOCKS5-ретранслятора. [Матрица протоколов](docs/PROTOCOLS.md).

## Безопасность, повторы и восстановление

Повтор установщика с идентичными параметрами и `--panel-inbounds` проверяет ownership, целостность SQLite и криптографическую идентичность без перезаписи клиентов (`preserved_exact_identity: true`). Полный бинарный updater/rollback не реализован; не запускайте `x-ui update`.

Никогда не коммитьте SQLite, backups, API tokens, private keys, subscription tokens и приватный путь панели. Оба журнала (`preview-panel-inbounds.json` и `preview-vpn-inbounds.json`) после `READY` запрещают автоматический rollback; при `RECOVERY_REQUIRED` требуется ручная диагностика. [Эксплуатация](docs/OPERATIONS.md), [восстановление](docs/RECOVERY.md).

## Документация и разработка

- [Статус проекта](docs/PROJECT_STATUS.md) и [отчёт PREVIEW-XONIX-08](docs/stages/evidence/preview-xonix-08/test-results.md).
- [Архитектура](docs/ARCHITECTURE.md), [архитектурные решения](docs/DECISIONS.md), [протоколы](docs/PROTOCOLS.md), [установка](docs/INSTALLATION.md).
- [Тестирование](docs/TESTING.md): historical baseline **318/318 PASS** (07A) отделён от новой 6-inbound приёмки PREVIEW-08.
- [GEMINI.md](GEMINI.md), [AGENTS.md](AGENTS.md), [передача Antigravity](docs/ANTIGRAVITY_HANDOFF.md).
- [Историческая справка установщика](docs/PREVIEW_XONIX_INSTALL.md): архивные режимы до 6-inbound интеграции.

## Авторство и лицензии

Форк основан на установщике [mozaroc/3x-ui-pro](https://github.com/mozaroc/3x-ui-pro). Панель — [MHSanaei/3x-ui](https://github.com/MHSanaei/3x-ui), ядро — [XTLS/Xray-core](https://github.com/XTLS/Xray-core), AWG — [Amnezia VPN](https://github.com/amnezia-vpn). Сохраняйте атрибуцию и поставляемые лицензии в [release/distribution](release/distribution/README.md); лицензия одного компонента не заменяет лицензии остальных.
