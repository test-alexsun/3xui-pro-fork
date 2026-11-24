# Инструкции AI coding agents

Сначала прочитайте [GEMINI.md](GEMINI.md), [статус](docs/PROJECT_STATUS.md), [архитектуру](docs/ARCHITECTURE.md), [решения](docs/DECISIONS.md), актуальные исходники и Git status. Не начинайте проект заново.

- Работайте в preview-ветках; не изменяйте `main` автоматически. Не используйте `force push` и не удаляйте историю.
- Сохраняйте чужие изменения и evidence. Не используйте `git reset --hard` или `git clean -fdx`.
- Не раскрывайте credentials, API tokens, subscription URLs, private keys, private panel path, production SQLite или backups.
- Production (`de126`) read-only по умолчанию. Любые production SQLite/inbound/peer/runtime/firewall/SSH/DNS/certificate/restart mutations требуют отдельного явного разрешения.
- Сохраняйте существующих клиентов, UUID, ключи, short IDs, порты, транспорты, сертификаты и домены. Не перегенерируйте ключи автоматически.
- Не выполняйте destructive migration. После journal `READY` (`preview-panel-inbounds.json` и `preview-vpn-inbounds.json`) запрещён автоматический rollback/reimport. `RECOVERY_REQUIRED` требует ручной диагностики с сохранением backups.
- Не смешивать WireGuard и AWG 3.1. Разработка и тестирование выполняются независимо. Общие integration tests допускаются только для проверки совместной работы и отсутствия конфликтов.
- AWG строго версии **3.1** (`amneziawg-go` `3.1.20260828`, `awg` tools `3.1.20260812`) с `HeaderProtectionKey`. Не заменяйте его plain WireGuard, профилями 1.x/2.x или `kernelMode: true` (`xui-awg<ID>`). Не запускайте две службы на UDP `29177` и не останавливайте production `3xui-pro-fork-awg.service` без явных `--add-vpn-inbounds --handoff-standalone-awg`.
- Не менять server MTU (`1420`) автоматически. Client MTU `1368` относится только к одному измеренному 07A path, а не к глобальному default.
- Не удаляйте проверенные протоколы и не добавляйте неиспользуемые legacy-протоколы. Целевой набор ровно: `VLESS-REALITY-XHTTP-H2` (P0), `VLESS-TLS-XHTTP-H2` (P1), `VLESS-REALITY-VISION` (P3), `WIREGUARD`, `AMNEZIAWG-3.1`, `HYSTERIA2`.
- Сначала изучайте существующие реализации и evidence; не дублируйте tests без причины. Изменения проверяйте targeted checks, затем единой приёмкой после интеграции.
- Не создавайте фиктивные inbound для количества. UI/API изменение клиента должно менять доступ реального клиента, с протокольной моделью peer/keys, auth либо UUID/flow.
- Документируйте архитектурные решения, ограничения и точные checked revisions. Разделяйте historical, lab, production и новый результат.
- Published PASS допустим только по фактически выполненным gates; local commit не равен release или production deployment.

Подробные правила находятся в [.agents/rules](.agents/rules/architecture.md). Они дополняют этот файл и не расширяют production authorization.
