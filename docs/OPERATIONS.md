# Эксплуатация

Ниже read-only диагностика. Start/stop/restart, изменения SQLite, peer и конфигураций production требуют отдельного разрешения. Перед публикацией выводов удалять credentials, tokens, private paths и ключи.

```sh
systemctl status 3xui-pro-fork.service 3xui-pro-fork-awg.service nginx --no-pager
systemctl status 3xui-preview-renew.timer --no-pager
systemctl is-active 3xui-preview-xray.service
ss -H -ltnp
ss -H -lunp
nginx -t
journalctl -u 3xui-pro-fork.service -u 3xui-pro-fork-awg.service -u nginx --since '1 hour ago' --no-pager
free -m
df -h / /var/tmp
journalctl -k --since '1 hour ago' --no-pager
```

После native READY standalone `3xui-preview-xray.service` должен быть inactive/disabled. Native Xray — child panel, не отдельный unit. `nginx -t` проверяет синтаксис, но не доказывает HTTPS/подписки/трафик. Inspect process/listener ownership, а не только unit active.

## Runtime checks

Панельный binary/core лежит в `/opt/3xui-pro-fork/panel`. Версия Xray:

```sh
/opt/3xui-pro-fork/panel/bin/xray-linux-amd64 version
/opt/3xui-pro-fork/awg/amneziawg-go --version
ip -details link show dev xproawg0
/opt/3xui-pro-fork/awg/awg show xproawg0 latest-handshakes
/opt/3xui-pro-fork/awg/awg show xproawg0 transfer
```

Public keys/traffic timestamps тоже относятся к private operational data. Не использовать `awg showconf` для публичной диагностики. WireGuard и Hysteria2 service names не существуют в текущей интеграции; отсутствие службы ожидаемо, нельзя документировать `systemctl restart` выдуманного unit.

Для TLS проверяйте hostname verification и SAN существующего сертификата, expiry и renewal timer. Certbot использует `/var/lib/3xui-preview-acme`, а не стандартный `/etc/letsencrypt` lineage. Не выполнять forced renewal для smoke. Проверка XONIX требует HTTPS page/canvas без JS errors; panel/API — authenticated проверку с приватными реквизитами локально.

## Backup

Сохраняйте consistent SQLite Online Backup, owned state, AWG configs, certificates, Nginx files/units и manifests в root-only directory; файлы 0600, каталоги 0700. При активных writers простой `cp x-ui.db` может не включить WAL и не даёт coordinated snapshot.

`release/backup_candidate.py` предоставляет `create_backup` / `verify_backup`; это library, не готовая universal backup CLI. Его caller обязан координировать writers. Candidate `--mode prepare-upgrade` поддерживает ограниченный loopback layout и останавливает службы: не применять его как безопасную read-only production команду после strict native READY.

Для отдельно согласованного backup plan используйте SQLite Online Backup API, проверяйте `PRAGMA integrity_check` на независимой копии, private manifest/checksums и восстановление в disposable lab. Off-host backup шифруйте и проверяйте. Никогда не коммитить backup или реальную DB в GitHub.

## Изменения

На разрешённой lab машине существующие службы управляются `systemctl start|stop|restart UNIT`. Restart панели затрагивает native Xray и соединения. После любого разрешённого изменения проверяйте fresh connections, bidirectional traffic, persistence и OOM delta. Production permission на диагностику не разрешает restart.

Нет автоматического полного project upgrade. Сначала reviewed pin, backup, targeted lab validation и maintenance authorization; затем только конкретное согласованное действие. [RECOVERY](RECOVERY.md).
