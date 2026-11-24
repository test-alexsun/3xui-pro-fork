# 3xui-pro-fork — Debian 13 preview

Воспроизводимый установщик 3x-ui, Xray, отдельного AmneziaWG 3.1, Nginx, Let's Encrypt и игры XONIX Neon Frontier. Целевая ОС — **Debian 13 amd64 с systemd**.

**PREVIEW-XONIX-08 ещё не принят.** Рабочая реализация управляет тремя VLESS inbound через нативную панель; AWG 3.1 работает отдельной службой. Шесть управляемых inbound — цель интеграции, а не заявленная готовая возможность. [Статус](docs/PROJECT_STATUS.md) отделяет preview от production.

PREVIEW-08 добавляет отдельную opt-in laboratory utility `release/preview_vpn_inbounds.py` для реальных native WG/AWG3.1/Hysteria2. Она не включена автоматически в installer и не разрешает production apply. Состояние `CONFIGURED_NOT_ACCEPTED` само по себе не означает handshake/traffic. Scoped lab проверки шести backend прошли после адресных исправлений fixtures; исходные FAIL сохранены в evidence. Это не полная installer/production приёмка.

## Возможности и протоколы

| Tag / компонент | Реализация в текущем preview |
|---|---|
| VLESS-REALITY-XHTTP-H2 / P0 | Нативная панель → Xray, REALITY + XHTTP H2 |
| VLESS-TLS-XHTTP-H2 / P1 | Нативная панель → Xray; публичный TLS/H2 завершает Nginx |
| VLESS-REALITY-VISION / P3 | Нативная панель → Xray, REALITY + Vision |
| WIREGUARD | Native Xray TCP/UDP/lifecycle PASS в lab; default installer пока не создаёт |
| AMNEZIAWG-3.1 | Default/production: отдельный runtime; lab: native relay/lifecycle PASS, прежний host-route handoff не принят |
| HYSTERIA2 | Native Xray QUIC/TLS/lifecycle PASS в lab; default installer пока не создаёт |

Закреплены 3x-ui **3.11.0**, Xray **26.11.9**, AWG runtime **3.1.20260828**, AWG tools **3.1.20260812**. Nginx закреплён на Debian Security **1.26.3-3+deb13u11**. [Происхождение и лицензии](release/distribution/README.md).

## Архитектура

Nginx публикует два домена: сайт с XONIX и защищённым путём панели; отдельный домен подписок. SQLite и API панели — источник истины для текущих VLESS клиентов. Единственный дочерний Xray панели обслуживает P0/P1/P3. AWG имеет собственные private config и systemd unit. [Архитектура и диаграммы](docs/ARCHITECTURE.md).

## Установка и требования

Нужны Debian 13 amd64, root, systemd, TUN/CAP_NET_ADMIN, два DNS A имени, доступ к закреплённым источникам и свободная выделенная RFC1918 /30. Исторически проверена машина примерно с 1 GiB RAM; это не гарантия ёмкости. Fresh installer требует минимум 512 MiB свободного диска; оставьте дополнительное место для backup, пакетов и журналов.

Используйте только проверенный immutable commit и SHA256 bootstrap: [подготовка и команда установки](docs/INSTALLATION.md). Не запускайте старый `x-ui-latest.sh`: legacy entrypoint отключён. Текущая установка создаёт три нативных VLESS и отдельный AWG, не шесть панельных inbound.

## Управление и подписки

Клиентов VLESS создавайте в **Clients → Add Clients**, назначая нужные inbound. Для P3 задайте `xtls-rprx-vision`. Изменение/отключение/удаление выполняются через штатные UI/API. Прекращение новых соединений подтверждалось; принудительное завершение уже открытых потоков не заявляется.

Raw VLESS links, JSON и Clash проверялись для существующих VLESS маршрутов. AWG выдаётся private `.conf`, не VLESS UUID. WireGuard/Hysteria2 subscription export в этой сборке не принят. [Матрица протоколов](docs/PROTOCOLS.md).

## Обновление, безопасность и восстановление

Полный безопасный updater/rollback проекта не реализован. Не применяйте `x-ui update` как штатное обновление: оно нарушает закреплённый tuple. Повтор installer с одинаковыми параметрами проверяет owned state; это не общий updater. После миграции обязателен `--panel-inbounds`.

Не коммитьте SQLite, backup, API credentials, private keys, subscription tokens и приватный путь панели. Создавайте согласованный root-only backup SQLite и managed state до разрешённых изменений. После journal **READY автоматический rollback запрещён**. [Эксплуатация](docs/OPERATIONS.md), [восстановление](docs/RECOVERY.md).

## Документация и разработка

- [Статус проекта](docs/PROJECT_STATUS.md) и [evidence PREVIEW-08](docs/stages/evidence/preview-xonix-08/test-results.md).
- [Архитектура](docs/ARCHITECTURE.md), [протоколы](docs/PROTOCOLS.md), [установка](docs/INSTALLATION.md).
- [Тестирование](docs/TESTING.md): historical baseline **318/318 PASS** отделён от новой приёмки.
- [GEMINI.md](GEMINI.md), [AGENTS.md](AGENTS.md), [передача Antigravity](docs/ANTIGRAVITY_HANDOFF.md).
- [Подробная история установщика](docs/PREVIEW_XONIX_INSTALL.md): разделы описывают разные исторические режимы, а не одну актуальную production-команду.

Работайте в preview-ветках, сохраняйте клиентов и ключи, не меняйте production без отдельного разрешения. Дополнительные неиспользуемые legacy-протоколы не добавляются.

## Авторство и лицензии

Форк основан на установщике [mozaroc/3x-ui-pro](https://github.com/mozaroc/3x-ui-pro). Панель — [MHSanaei/3x-ui](https://github.com/MHSanaei/3x-ui), ядро — [XTLS/Xray-core](https://github.com/XTLS/Xray-core), AWG — [Amnezia VPN](https://github.com/amnezia-vpn). Сохраняйте атрибуцию и поставляемые лицензии в [release/distribution](release/distribution/README.md); лицензия одного компонента не заменяет лицензии остальных.
