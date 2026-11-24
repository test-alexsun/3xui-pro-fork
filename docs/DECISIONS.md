# Архитектурные решения (ADR)

Зафиксированные решения проекта `3xui-pro-fork` для Debian 13 preview (`preview/xonix-standalone-debian13`).

## ADR-01: Ровно шесть управляемых inbound и два фиксированных домена

- **Решение**: целевой набор включает ровно `VLESS-REALITY-XHTTP-H2` (P0), `VLESS-TLS-XHTTP-H2` (P1), `VLESS-REALITY-VISION` (P3), `WIREGUARD`, `AMNEZIAWG-3.1`, `HYSTERIA2` без legacy-протоколов (`VMess`/`Trojan`/`SS`) и при сохранении строго двух доменов (main + subscription).
- **Причина**: исключает фиктивные записи UI и дублирование ACME/Nginx-инфраструктуры; каждый inbound соответствует реальному серверному обработчику.

## ADR-02: Полная независимость WireGuard и AmneziaWG 3.1

- **Решение**: обычный WireGuard (`WIREGUARD`) и AmneziaWG строго версии 3.1 (`AMNEZIAWG-3.1`) разделены на уровне кода (`release/preview_wireguard.py` vs `release/preview_amneziawg31.py`), UDP-портов (`51820` vs `29177`), RFC1918 подсетей (`10.89.8.0/24` vs `10.88.32.0/24`), серверных и клиентских ключей, записей клиентов в SQLite, форматов экспорта, модульных и E2E-тестов.
- **Причина**: оба протокола обязательны для практического применения; в 3x-ui `clients.wg_*` являются общими колонками записи клиента, а смешивание конфигураций или перенос PASS-результата между протоколами ломает требования независимости и изоляции.

## ADR-03: Runtime backends для WG, AWG 3.1 и Hysteria2

- **Решение**:
  - `WIREGUARD` работает через нативный userspace Xray inbound (`noKernelTun: true`) с pure-Python RFC 7748 X25519 криптографией, без зависимости от `awg`.
  - `AMNEZIAWG-3.1` в 6-inbound режиме работает через встроенный менеджер `amneziawgnet` (`3.1.20260828`, `kernelMode: false`) в процессе `x-ui` MainPID с ретрансляцией через loopback password-auth SOCKS5 inbound в Xray; `3xui-pro-fork-awg.service` остаётся inactive/disabled (кроме opt-out режима `--vless-only` и неизменённого production). `kernelMode: true` (`xui-awg<ID>`) не принят.
  - `HYSTERIA2` работает на нативном Xray `hysteria` v2 (`network: hysteria`, TLS ALPN `h3`) с переиспользованием существующего SAN-сертификата `/var/lib/3xui-preview-acme`.
- **Причина**: опирается на подтверждённый pinned tuple (`3x-ui 3.11.0`, `Xray 26.11.9`, `amneziawg-go 3.1.20260828`, `awg 3.1.20260812`) без установки DKMS/ядерных модулей или дублирующих процессов.

## ADR-04: Учёт сериализации и reconcile-таймингов `3x-ui 3.11.0`

- **Решение**:
  - Валидатор `_validate_awg_row` трактует отсутствие ключа `kernelMode` в JSON как `False` (учитывая Go-тег `json:"kernelMode,omitempty"`), отклоняя только `True`.
  - Потребители API (`clients/get`, `clients/list`) нормализуют `allowedIPs` из CSV-строки, сохраняя JSON-список в `inbounds/list` и запросах на запись.
  - Автоматические проверки жизненного цикла `AMNEZIAWG-3.1` ожидают конвергенции `settings.accounts` loopback SOCKS5 inbound после ~30-секундного reconcile-тика Xray.

## ADR-05: Серверный MTU `1420` по умолчанию и отмена legacy client compatibility

- **Решение**: server default MTU остаётся `1420` для `WIREGUARD` и `AMNEZIAWG-3.1`; измеренные клиентские MTU `1368` (путь 07A) и `1280` (1568 B PQ `TLSv1.3 ClientHello` через локальный Docker/WSL2/ISP WAN-путь к `de126`) относятся только к клиентским профилям на конкретных WAN-путях, не меняя server MTU. Проверка старых standalone `/30` WG/AWG клиентских профилей и профилей 1.x/2.x отменена; после production handoff `de126` 2026-11-24 старые `/30` профили теряют доступ, при этом прежний архив `/var/lib/3xui-pro-fork/awg/` и pre-rollout backup полностью сохранены.

## ADR-06: Двухжурнальный fail-closed lifecycle и управление production `de126`

- **Решение**: переход P0/P1/P3 (`preview-panel-inbounds.json`) и добавление WG/AWG 3.1/HY2 (`preview-vpn-inbounds.json`) ведутся в отдельных fail-closed журналах. После `READY` автоматический rollback запрещён; ошибки переводят журнал в `RECOVERY_REQUIRED`. Остановка `3xui-pro-fork-awg.service` не выполняется автоматически без явных `--add-vpn-inbounds --handoff-standalone-awg` и разрешения владельца (реализовано и подтверждено на `de126` 2026-11-24 с созданием согласованного online SQLite backup). Для будущих задач production остаётся read-only по умолчанию.
