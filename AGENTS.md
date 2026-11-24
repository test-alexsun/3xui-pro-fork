# Инструкции AI coding agents

Сначала прочитайте [GEMINI.md](GEMINI.md), [статус](docs/PROJECT_STATUS.md), [архитектуру](docs/ARCHITECTURE.md), [решения](docs/DECISIONS.md), актуальные исходники и Git status. Не начинайте проект заново.

> [!NOTE]
> **В рамках проекта владелец разрешил автономную работу с GitHub preview-веткой и VPS de126, включая необходимые изменения production.** Это разрешение действует исключительно в пределах того задания (выкатка шести Inbounds на `de126`, приёмка и публикация результата), **не является бессрочным правом на любые будущие действия и не отменяет ограничений безопасности**. Для новых будущих задач production (`de126`) по умолчанию остаётся read-only без отдельного явного поручения владельца.

- Работайте в preview-ветках; не изменяйте `main` автоматически. Не используйте `force push` и не удаляйте историю.
- Сохраняйте чужие изменения и evidence. Не используйте `git reset --hard` или `git clean -fdx`.
- Не раскрывайте credentials, API tokens, subscription URLs, private keys, private panel path, production SQLite или backups.
- Production (`de126`, `179.254.154.126` — переведён на 6 управляемых inbound `READY`/`READY` с `9e44b525685458f00c34effe6795814b1da24da9`) read-only по умолчанию для новых задач. Любые новые production SQLite/inbound/peer/runtime/firewall/SSH/DNS/certificate/restart mutations требуют отдельного явного разрешения.
- Сохраняйте существующих клиентов, UUID, ключи, short IDs, порты, транспорты, сертификаты и домены. Не перегенерируйте ключи автоматически.
- Не выполняйте destructive migration. После journal `READY` (`preview-panel-inbounds.json` и `preview-vpn-inbounds.json`) запрещён автоматический rollback/reimport. `RECOVERY_REQUIRED` требует ручной диагностики с сохранением backups.
- Не смешивать WireGuard и AWG 3.1. Разработка и тестирование выполняются независимо. Общие integration tests допускаются только для проверки совместной работы и отсутствия конфликтов.
- AWG строго версии **3.1** (`amneziawg-go` `3.1.20260828`, `awg` tools `3.1.20260812`) с `HeaderProtectionKey`. Не заменяйте его plain WireGuard, профилями 1.x/2.x или `kernelMode: true` (`xui-awg<ID>`). Не запускайте две службы на UDP `29177` и не запускайте несогласованные изменения `3xui-pro-fork-awg.service` (на `de126` остановлена/отключена штатным `--add-vpn-inbounds --handoff-standalone-awg` с сохранением `/var/lib/3xui-pro-fork/awg/` и pre-rollout backup).
- Не менять server MTU (`1420`) автоматически. Client MTU `1368` (07A) или `1280` (PQ TLSv1.3 ClientHello через измеренный WAN-путь) относится только к клиентскому пути, а не к глобальному server default.
- Не удаляйте проверенные протоколы и не добавляйте неиспользуемые legacy-протоколы. Целевой набор ровно: `VLESS-REALITY-XHTTP-H2` (P0), `VLESS-TLS-XHTTP-H2` (P1), `VLESS-REALITY-VISION` (P3), `WIREGUARD`, `AMNEZIAWG-3.1`, `HYSTERIA2`.
- Сначала изучайте существующие реализации и evidence; не дублируйте tests без причины. Изменения проверяйте targeted checks, затем единой приёмкой после интеграции.
- Не создавайте фиктивные inbound для количества. UI/API изменение клиента должно менять доступ реального клиента, с протокольной моделью peer/keys, auth либо UUID/flow.
- Документируйте архитектурные решения, ограничения и точные checked revisions. Разделяйте historical, lab, production и новый результат.
- Published PASS допустим только по фактически выполненным gates; local commit не равен release или production deployment.

Подробные правила находятся в [.agents/rules](.agents/rules/architecture.md). Они дополняют этот файл и не расширяют будущую production authorization.
