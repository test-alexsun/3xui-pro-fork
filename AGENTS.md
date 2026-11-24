# Инструкции AI coding agents

Сначала прочитайте [GEMINI.md](GEMINI.md), [статус](docs/PROJECT_STATUS.md), [архитектуру](docs/ARCHITECTURE.md), актуальные исходники и Git status. Не начинайте проект заново.

- Работайте в preview-ветках; не изменяйте main автоматически. Не force push и не удаляйте историю.
- Сохраняйте чужие изменения и evidence. Не используйте `git reset --hard` или `git clean -fdx`.
- Не раскрывайте credentials, API tokens, subscription URLs, private keys, private panel path, production SQLite или backup.
- Production read-only по умолчанию. Любые production SQLite/inbound/peer/runtime/firewall/SSH/DNS/certificate/restart mutations требуют отдельного явного разрешения.
- Сохраняйте существующих клиентов, UUID, ключи, short IDs, ports, transports, сертификаты и домены. Не перегенерируйте ключи автоматически.
- Не выполняйте destructive migration. После journal READY запрещён автоматический rollback/reimport. RECOVERY_REQUIRED требует ручной диагностики с сохранением backups.
- AWG строго 3.1 с закреплённым runtime/tools и HeaderProtectionKey. Не заменяйте его WireGuard или прежними AWG версиями. Не запускать две службы UDP29177.
- Не менять server MTU автоматически. Client MTU1368 относится к одному измеренному path, не глобальному default.
- Не удаляйте проверенные протоколы и не добавляйте неиспользуемые legacy-протоколы. Целевой набор ровно P0/P1/P3/WG/AWG3.1/Hysteria2.
- Сначала изучайте существующие реализации и evidence; не дублируйте tests без причины. Изменения проверяйте targeted checks, затем один final acceptance после integration.
- Не создавайте фиктивные inbound для количества. UI изменение клиента должно менять доступ реального клиента, с протокольной моделью peer/keys либо UUID/auth.
- Документируйте архитектурные решения, ограничения и точные checked revisions. Разделяйте historical, lab, production и новый результат.
- Published PASS допустим только по фактически выполненным gates; local commit не равен release или production deployment.

Подробные правила в [.agents/rules](.agents/rules/architecture.md). Они дополняют этот файл и не расширяют production authorization.
