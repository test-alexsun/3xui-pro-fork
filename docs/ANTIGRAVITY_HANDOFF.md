# Передача проекта в Gemini Antigravity

Проект — Debian13 amd64 installer/control integration для 3x-ui, Xray, AWG3.1, Nginx, Let's Encrypt, subscriptions и XONIX. Откройте корень preview checkout; сначала [GEMINI.md](../GEMINI.md), [AGENTS.md](../AGENTS.md), [PROJECT_STATUS](PROJECT_STATUS.md), затем owning source. Результат PREVIEW-08 не считать PASS без его actual evidence.

## Что уже реализовано

Strict two-domain layout и HTTPS, XONIX с localStorage, private panel path, native raw/JSON/Clash VLESS subscriptions, три real native inbound P0/P1/P3, durable standalone→native handoff и separate AWG3.1. Historical regression318/318PASS относится к 07A; существующий 07B report фиксирует production READY и scoped traffic acceptance. Не путать эти результаты с новым шестипротокольным lab run.

Целевой набор: `VLESS-REALITY-XHTTP-H2`, `VLESS-TLS-XHTTP-H2`, `VLESS-REALITY-VISION`, `WIREGUARD`, `AMNEZIAWG-3.1`, `HYSTERIA2`. Последние три пока не имеют принятой общей panel lifecycle integration. UI rows без настоящего backend и управления доступом запрещены.

Upstream audit подтвердил WG native Xray, AWG embedded3.1.20260828 и Hysteria2 version2/network=hysteria/TLS h3 в закреплённых версиях. Installer был ограничен `TAGS` P0/P1/P3. Собственный новый protocol runtime обычно не нужен. Однако embedded AWG имеет gVisor/SOCKS egress вместо existing host-TUN /30: совместимость старого клиента и маршрутов должна быть отдельно доказана до handoff.

Optional `release/preview_vpn_inbounds.py` PREVIEW-08 добавляет отдельный laboratory path: read-only plan и строго lab-only native configuration с explicit AWG handoff. Default installer остаётся3 VLESS + separate AWG. VPN manifest отделён от existing native READY; `CONFIGURED_NOT_ACCEPTED` не подтверждает реального подключения, а `RECOVERY_REQUIRED` требует ручного разбора. Production apply закрыт до acceptance и отдельного разрешения. Читайте08 evidence для actual final outcome.

## Почему так устроено

Debian13/systemd — квалифицированный target installer, package pins и system services. Panel3.11.0/Xray26.11.9 закреплены по проверенной tuple; смена версии означает новую совместимость API/schema/transport. AWG runtime3.1.20260828/tools3.1.20260812 используют проверенные параметры включая HeaderProtectionKey; совпадение слова AWG в другом backend не даёт совместимость3.1.

Панель хранит current VLESS clients/assignments в SQLite, а API применяет изменения к native Xray. P1 external proxy metadata описывает реальный public TLS ingress, хотя backend cleartext H2. Подписки — bearer secrets на отдельном домене, без access logging. AWG `.conf` — отдельный peer/key формат, не VLESS subscription.

READY journal сохраняет ownership и состояние завершённого handoff. Staged native records disabled до освобождения старых ports. После READY новые клиенты принадлежат native panel; rollback старой DB может уничтожить их. Поэтому automatic reverse запрещён; RECOVERY_REQUIRED требует ручного разбора, а не удаления journal.

## Installer и production-critical пути

Bootstrap получает exact40hex commit; `install-preview.sh` запускает Python orchestrator. Пinned upstream archives и bundled AWG проверяются hash/ELF/manifests, source helpers сверяются. Distribution source/build scripts и лицензии лежат в `release/distribution/`. Не собирать новый package из непроверенной latest версии.

Production-critical: SQLite и native assignments, private setup state/journal, Xray keys/UUID, AWG keys/config/port29177, Nginx routing, TLS lineage/renewal timer и unit ownership. Read-only audit не разрешает mutation. Существующие P0/P1/P3 нельзя пересоздавать ради нужного количества строк.

## Как продолжать

Безопасно начинать с read-only source audit, сопоставления schema/runtime, docs и isolated fixture. Реальная integration WG/AWG/HY2 требует backend ownership, peer/auth lifecycle, export и persistence; возможный scoped panel fork должен сохранять API/data compatibility. Не добавляйте лишние VMess/Trojan/SS/WS/gRPC режимы.

Изменение installer/runtime/client management требует targeted checks и одного final disposable lab run; fault injection и namespaces только lab. Не повторяйте всю историю автоматически. [TESTING](TESTING.md) содержит проверенные scenario locations. [PROTOCOLS](PROTOCOLS.md) не обещает универсальную поддержку subscription formats.

Перед GitHub publication проверить staged paths/secrets/links/licenses/executable scripts, работать только preview, обычный push, сравнить remoteHEAD и main. Публикация docs или local commit не является release. Production apply допускается только после завершённой lab acceptance и отдельного разрешения; до этого не выдавать фиктивную команду добавления трёх inbound.

## Оставшиеся задачи

Связать три отсутствующих protocol lifecycle с реальными backend; не мигрировать AWG в несовместимый implementation. Проверить шесть UI entries с реальным runtime и bidirectional traffic, fresh disable/delete, restart persistence, exports и общий smoke. Затем опубликовать exact verified commit и отдельный production apply plan с preserving identities. Полный updater/rollback и power-loss recovery остаются ограничениями.

Evidence находится в `docs/stages/evidence/`; owning code и sanitized actual results важнее исторических утверждений. Local private07B material не публиковать автоматически. [08 report](stages/evidence/preview-xonix-08/test-results.md) фиксирует текущие blockers/publication.

## Workspace rules

`.agents/rules/` разделяет architecture/security/production/testing/protocols/git-workflow. Формат проверен по [официальным правилам Antigravity](https://antigravity.google/docs/rules/): Markdown начинается с YAML `trigger`; используется `model_decision` с `description`. `GEMINI.md`/`AGENTS.md` — plain Markdown без frontmatter. Правила не расширяют production authorization.

## Стартовый prompt

«Изучи GEMINI.md, AGENTS.md, документацию проекта и текущую Git-ветку. Сначала проведи read-only аудит архитектуры и состояния исходников. Не изменяй production без моего разрешения. Продолжай развитие существующей реализации, сохраняя совместимость и накопленные результаты».
