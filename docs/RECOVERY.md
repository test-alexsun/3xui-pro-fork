# Восстановление и migration journal

**После native READY автоматический rollback запрещён.** Существующие panel customers и subscriptions могут быть новее pre-migration snapshots. Повторная миграция, restore старой DB или удаление journal могут потерять текущих клиентов.

| Состояние | Значение и действие |
|---|---|
| READY | Handoff выполнен; current truth в panel API/SQLite. Обратный переход требует нового плана и разрешения |
| ROLLED_BACK | Scoped rollback заявлен законченным; отдельно проверить old listeners, identities, unrelated clients и трафик |
| RECOVERY_REQUIRED | Неоднозначный/незавершённый side effect. Остановить mutations, сохранить evidence, диагностировать вручную |
| PREPARING/STAGING/STAGED/STOPPING_STANDALONE/ACTIVATING_NATIVE/ROLLING_BACK | Незавершённый переход; не удалять state и не запускать повтор blindly |

Journal: `/var/lib/3xui-pro-fork/preview-panel-inbounds.json`, backup перед handoff: private `preview-panel-migration-backups/before-*`. Эти файлы могут раскрывать identities и должны оставаться private. Root-only snapshots не публиковать в evidence.

## Диагностика

Сначала сохранить read-only unit/listener/process status, timestamps и sanitized errors. Проверить disk/RAM, permissions, ownership/hash managed files, SQLite integrity на независимой consistent copy. Не запускать второй Xray или AWG для обхода ошибки. [OPERATIONS](OPERATIONS.md) содержит безопасные команды.

### SQLite и backup

Backup restoration — отдельная maintenance операция с остановленными согласованными writers. Проверить private manifest, hashes, версии schema и `PRAGMA integrity_check` на копии. Учитывать DB WAL/SHM и права. Сначала восстановить в lab с теми же binaries; сравнить users/settings/clients/assignments и fresh traffic. Не переносить SQL между версиями наугад и не применять `.recover` к live production DB. Salvage через SQLite tooling допустим только на private копии с ручной сверкой потерянных данных.

### Повреждение конфигурации и портов

Проверить владельца каждого listener через `ss -ltnp/-lunp`. Не убивать неизвестный PID и не удалять интерфейс по имени. После READY native panel — владелец VLESS; старый `preview-xray.json` нельзя восстановить поверх текущей panel truth. Сравнивать owned manifests до любых замен.

### Nginx / TLS

Сначала `nginx -t`, затем inspect managed include, certificate expiry/SAN и renewal timer. Не удалять чужие vhost или ACME lineage. Новый сертификат не исправляет несоответствие SNI/Host или backend port. Reload разрешён только после valid config и production authorization. Сохранять два существующих домена и сертификат при отсутствии необходимости замены.

### Xray

Проверить единственный child panel, версия 26.11.9, native inbounds и live users. Native gRPC updates могут быть новее generated config. Не стартовать standalone на занятых native ports. Restart panel требует maintenance authorization и повторной проверки fresh connections.

### AWG 3.1

Сохранять runtime/tools, private keys, HeaderProtectionKey, S1–S4/H1–H4, UDP29177 и server MTU. Проверить `xproawg0`, control socket, actual process ownership и permission private configs. Supervisor специально отказывает при существующем чужом interface/socket; это safety condition, не повод для безусловного `ip link del`. Не переносить старый AWG backend как workaround. MTU1368 применять лишь к ранее измеренному client path после новой диагностики.

WireGuard/Hysteria2 не имеют принятого production lifecycle в этой сборке. Не создавать service/config ради recovery до реализации и lab acceptance. Power-loss recovery native journal и полный project rollback не квалифицированы.
