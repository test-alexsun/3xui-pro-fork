# Восстановление и fail-closed журналы миграции

После перехода в состояние `READY` в любом из журналов **автоматический rollback, удаление state-файлов и повторное усыновление запрещены**. Последующие клиенты и их ключи/UUID принадлежат native `x-ui.db`; откат к pre-migration snapshots уничтожит действующих клиентов.

## Два fail-closed журнала

| Журнал | Область | Backup перед переходом | Поведение при сбое |
|---|---|---|---|
| `/var/lib/3xui-pro-fork/preview-panel-inbounds.json` | Native P0/P1/P3 + отключение `3xui-preview-xray.service` | `preview-panel-migration-backups/before-*` | Сбой на staging/activation → `RECOVERY_REQUIRED` без автоматического удаления VLESS |
| `/var/lib/3xui-pro-fork/preview-vpn-inbounds.json` (`version: 2`) | `WIREGUARD`, `AMNEZIAWG-3.1`, `HYSTERIA2` (и опциональный handoff standalone AWG) | `preview-vpn-migration-backups/before-*` | Сбой на `STAGING_*`, `STOPPING_STANDALONE_AWG` или `ACTIVATING` → `RECOVERY_REQUIRED`; существующий `preview-panel-inbounds.json` (`READY`) и VLESS не затрагиваются |

Непереходные фазы `PREPARING`, `STAGING_*`, `STAGED_*`, `STOPPING_STANDALONE*`, `ACTIVATING*`, `ROLLING_BACK` или `RECOVERY_REQUIRED` блокируют любые повторные запуски установщика и требуют ручной диагностики.

## Процедура диагностики

1. **Остановите мутации** и снимите read-only диагностику по [OPERATIONS](OPERATIONS.md): `systemctl status`, `ss -H -ltnp`, `ss -H -lunp`, свободный RAM/диск, разрешения и SHA256 owned-файлов.
2. **Проверьте SQLite и backups**: запустите `PRAGMA integrity_check` на consistent read-only копии `x-ui.db`; сверьте контрольные суммы в `preview-panel-inbounds.json` (`ready_sha256`) и сохраните root-only backups `preview-*-migration-backups/`.
3. **Разделите диагностику по протоколам**:
   - **P0/P1/P3 & Nginx/TLS**: `nginx -t`, проверка SAN/срока действия `/var/lib/3xui-preview-acme/config/live/3xui-preview/fullchain.pem`, проверка loopback `19441`/`19444`, TCP `8443`/`9443`.
   - **WIREGUARD**: владелец UDP `51820` (`xray-linux-amd64`), `noKernelTun: true`, pure-Python X25519 keypair, отсутствие AWG-параметров и пересечения подсетей. Не переносите ключи/подсети в AWG.
   - **AMNEZIAWG-3.1**: владелец UDP `29177` (embedded `x-ui` MainPID в 6-inbound режиме или `amneziawg-go` `xproawg0` в standalone `--vless-only`). Проверяйте наличие `AMNEZIAWG-3.1` SOCKS5 inbound в `/opt/3xui-pro-fork/panel/bin/config.json` (учитывайте ~30s reconcile-тик) и валидность `HeaderProtectionKey`. Не запускайте одновременно `3xui-pro-fork-awg.service` и embedded `AMNEZIAWG-3.1` на одном порту.
   - **HYSTERIA2**: владелец UDP `24443` (`xray-linux-amd64`), `version: 2`, `network: hysteria`, `alpn: ["h3"]`, root-readable ACME cert/key.
4. **Power-loss / ручное восстановление и production backup**: power-loss journal recovery и автоматический binary downgrade не реализованы. На `de126` перед rollout 2026-11-24 сохранён верифицированный online backup `/var/backups/3xui-pro-fork/pre-6inbounds-20261124T084510Z` (`manifest.sha256` OK) и installer backup `/var/lib/3xui-pro-fork/preview08-backup-482dd1cdafd75fdd`. Любое восстановление БД выполняется вручную при остановленных writers и сначала проверяется на изолированной lab-копии.
