# Контекст Gemini Antigravity

Прочитайте [AGENTS.md](AGENTS.md): это общие обязательные правила. Здесь актуальная карта проекта, а не transcript прошлых чатов.

## Проект и статус

`test-alexsun/3xui-pro-fork`, preview `preview/xonix-standalone-debian13`, Debian 13 amd64/systemd. Установщик объединяет 3x-ui, Xray, Nginx, Let's Encrypt, XONIX и AWG3.1. PREVIEW-XONIX-08 не объявлять PASS: текущий baseline имеет три native VLESS и отдельный AWG; WG/HY2 panel lifecycle не интегрирован. [PROJECT_STATUS](docs/PROJECT_STATUS.md) и [08 evidence](docs/stages/evidence/preview-xonix-08/test-results.md) — краткая точка входа.

## Закреплённый tuple

Panel3.11.0, Xray26.11.9, amneziawg-go3.1.20260828, tools3.1.20260812; Nginx Debian1.26.3-3+deb13u11. Не обновлять floating upstream командой. Distribution manifests/hashes/licenses: [release/distribution](release/distribution/README.md).

## Шесть целевых inbound

P0 `VLESS-REALITY-XHTTP-H2` TCP8443; P1 `VLESS-TLS-XHTTP-H2` public TLS443 → loopback19441; P3 `VLESS-REALITY-VISION` TCP9443. Они native panel-managed через единственный Xray child. `WIREGUARD` и `HYSTERIA2` не приняты. `AMNEZIAWG-3.1` реально работает UDP29177 отдельной named-TUN службой, но отсутствует supported panel peer lifecycle. Для новых UDP портов нужен actual conflict inventory, не произвольный default. [PROTOCOLS](docs/PROTOCOLS.md).

Upstream3.11.0 поддерживает WG в Xray, embedded AWG с той же go module3.1.20260828 и HY2 Xray version2/network=hysteria/TLS h3. Отсутствовала installer wiring, не protocol implementation upstream. Embedded AWG использует gVisor/per-peer SOCKS, existing separate runtime — host TUN: безопасный handoff должен доказать routing/client compatibility, не только совпадение версии. Current work может содержать lab-only integration; сверяйте actual08 evidence перед утверждением готовности.

## Где читать и менять

| Путь | Назначение |
|---|---|
| `bootstrap-preview.sh`, `install-preview.sh` | Immutable checkout и installer entrypoint |
| `release/preview_install.py` | Проверки/оркестрация deployment |
| `release/preview_two_domain.py`, `preview_transport.py`, `preview_acme.py` | Web/layout, transports и TLS ownership |
| `release/preview_panel_inbounds.py`, `preview_panel_api.py` | Native API import и durable handoff |
| `release/preview_vpn_inbounds.py` | Optional PREVIEW-08 native WG/AWG3.1/HY2 lab utility; production apply закрыт |
| `release/awg_service.py`, `awg_config_candidate.py` | Separate AWG supervisor и private pair generator |
| `release/distribution/` | Pinned AWG distribution, sources, лицензии |
| `assets/decoy/xonix/` | Original game HTML |
| `tests/release/`, `tests/xonix/` | Existing Linux/unit/lab/browser checks |
| `docs/stages/evidence/` | Historical reports; не все local records публичны |

## Архитектурные решения и инварианты

Debian13 выбран и квалифицировался для единообразных systemd/packages; другие ОС не обещаны. Strict layout использует ровно два домена. P1 TLS завершает Nginx; P0/P3 REALITY обслуживает native Xray. Native panel API/SQLite — текущая truth клиентов; старые standalone snapshots после READY recovery-only. AWG сохраняет отдельный проверенный 3.1 runtime, HeaderProtectionKey и server MTU. Не переносить экспериментальные FD_NATIVE harness как production runtime без необходимости.

Migration journal проходит staging disabled → release old listeners → activate native → READY. После READY нет автоматического reverse, потому что появились новые native clients/subscriptions. RECOVERY_REQUIRED не означает успешного восстановления. [ARCHITECTURE](docs/ARCHITECTURE.md), [RECOVERY](docs/RECOVERY.md).

## Разработка и проверки

Читайте owning source перед правкой. Preserve clients/UUID/keys/short IDs/ports/domains/certificates и чужую рабочую копию. Historical318/318PASS не перезапускайте на каждом docs/targeted изменении. Для code changes выбирайте existing targeted tests, один final six-protocol lab run после полной integration. [TESTING](docs/TESTING.md) описывает fixtures и команды.

Read-only Linux diagnostics: `systemctl status 3xui-pro-fork.service 3xui-pro-fork-awg.service nginx`, `ss -H -ltnp`, `ss -H -lunp`, `nginx -t`, `free -m`, `df -h`. Full regression требует специального network-none container, не production. Никогда не выполнять production fault injection или restart по разрешению на аудит.

## GitHub и безопасность

Только preview, обычные commits/push, remote HEAD verification. Main/force push/production-stable release запрещены без отдельного scope. Проверять staged diff на secrets, private DB/backups, персональные Windows paths; не публиковать raw production evidence без review. Docs publication не означает production apply. Точная publication revision фиксируется после push, без выдуманного SHA.

## Известные ограничения

Full updater/rollback отсутствует; WG/HY2 и AWG native panel control не приняты; full-tunnel NAT не создаётся автоматически; interface MTU1368 — только measured client path; generated core config может отставать от live gRPC users. Subscription formats не универсальны для всех VPN. [Handoff](docs/ANTIGRAVITY_HANDOFF.md), [INSTALLATION](docs/INSTALLATION.md), [OPERATIONS](docs/OPERATIONS.md).

Optional VPN utility отделена от default installer и existing native READY; её новый private manifest `preview-vpn-inbounds.json` использует `CONFIGURED_NOT_ACCEPTED`, пока нет traffic acceptance. Never equate successful configuration with PASS. Explicit lab handoff не даёт production authorization; RECOVERY_REQUIRED не запускает automatic rollback.

## Итог текущей lab работы

В08 получены6реальных API records/listeners и scoped traffic/lifecycle PASS всех backend после targeted fixture/readiness fixes. Default installer не изменён, старый AWG host-route профиль не принят, UI/VPN exports не проверены заново. Overall INCOMPLETE. Initial FAIL и точные результаты сохранены в08 evidence; не повторять весь исторический набор без причины.
