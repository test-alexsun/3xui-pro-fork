# Эксплуатация

Read-only диагностика допустима для проверки состояния узла. Любые изменения на production `de126` (SQLite, клиенты, inbounds, restart служб, firewall, DNS, сертификаты, откат) запрещены без отдельного явного разрешения. Перед публикацией выводов всегда удаляйте API tokens, private keys, password, cookies, subscription URLs и приватный `panel_path`.

## Базовая диагностика

```sh
systemctl status 3xui-pro-fork.service nginx --no-pager
systemctl status 3xui-preview-renew.timer --no-pager
systemctl is-active 3xui-pro-fork-awg.service 3xui-preview-xray.service
ss -H -ltnp
ss -H -lunp
nginx -t
free -m
df -h / /var/tmp
journalctl -k --since '1 hour ago' --no-pager
```

Ожидаемое владение сокетами в **6-inbound preview режиме** (`READY`):
- `3xui-pro-fork.service` (`x-ui` MainPID): loopback панели `127.0.0.1:2053`, подписок `127.0.0.1:2096` и UDP `--awg-port` (`29177` для `AMNEZIAWG-3.1`); `3xui-pro-fork-awg.service` и `3xui-preview-xray.service` должны быть `inactive`/`disabled`.
- Дочерний `xray-linux-amd64`: TCP `--p0-port` (`8443`), loopback P1 (`127.0.0.1:19441`), TCP `--p3-port` (`9443`), loopback Xray gRPC API (`62789`), UDP `--wg-port` (`51820` для `WIREGUARD`), UDP `--hy2-port` (`24443` для `HYSTERIA2`) и loopback SOCKS5 relay `127.0.0.1:<port>` для `AMNEZIAWG-3.1`.
- `nginx`: TCP `80` (308 redirect + HTTP-01 challenge), `443` (XONIX decoy, private panel path, `/xhttp/`, subscription vhost).

На **неизменённом production `de126`** `3xui-pro-fork-awg.service` активен (`amneziawg-go` на UDP `29177`, интерфейс `xproawg0`), а порты `51820` и `24443` не слушаются.

## Управление клиентами и нюансы протоколов

- **VLESS (P0/P1/P3)**: клиенты создаются и редактируются через UI/API панели, могут шарить идентификатор (`uuid`) между P0/P1/P3 (для P3 обязательно `xtls-rprx-vision`).
- **WireGuard (`WIREGUARD`) vs AmneziaWG 3.1 (`AMNEZIAWG-3.1`)**: в SQLite 3x-ui обе записи используют колонки `clients.wg_*`. Запрещено привязывать одну и ту же клиентскую запись одновременно к `WIREGUARD` и `AMNEZIAWG-3.1` — создавайте отдельных клиентов со своими ключами, `/32` IP из соответствующей подсети и собственными `subId`.
- **~30-секундный цикл примирения AWG 3.1**: при добавлении, удалении, включении или отключении клиента на `AMNEZIAWG-3.1` 3x-ui обновляет список `settings.accounts` loopback SOCKS5-ретранслятора и ставит флаг `SetToNeedRestart`. Фоновый reconcile-таймер панели (~30s) принудительно перезапускает `xray-linux-amd64` (для password-auth SOCKS5 горячий gRPC swap не применяется). В течение окна пересборки новые сессии AWG могут получать сброс до стабилизации Xray.
- **Проверка формата `allowedIPs`**: эндпоинты `clients/get/:email` и `clients/list` возвращают `allowedIPs` как CSV-строку, а `inbounds/list` — как список.
- **Сертификаты HYSTERIA2 и TLS**: `/var/lib/3xui-preview-acme` обновляется `3xui-preview-renew.timer`. Не выполняйте forced renewal ради smoke-проверок. `HYSTERIA2` использует тот же root-readable SAN-сертификат без дополнительной ACME-инфраструктуры.

## Бинарные проверки и OOM/SQLite

```sh
/opt/3xui-pro-fork/panel/bin/xray-linux-amd64 version
/opt/3xui-pro-fork/awg/amneziawg-go --version
/opt/3xui-pro-fork/awg/awg --version
sqlite3 "file:/var/lib/3xui-pro-fork/x-ui.db?mode=ro" "PRAGMA integrity_check;"
```

При активном `--vless-only` или standalone production также доступны `/opt/3xui-pro-fork/awg/awg show xproawg0 latest-handshakes` и `transfer` (значения ключей и handshakes не подлежат публикации).

## Backup и запрет несогласованного апгрейда

- Используйте SQLite Online Backup API (а не сырое `cp x-ui.db` под нагрузкой WAL), сохраняйте `/var/lib/3xui-pro-fork/`, Nginx include, `/var/lib/3xui-preview-acme/` и manifests в root-only каталоге (`0700`/`0600`). Никогда не коммитьте backups и БД.
- Библиотека [backup_candidate.py](../release/backup_candidate.py) требует координации writers от вызывающего кода. Полный автоматический updater не реализован; не запускайте `x-ui update`. См. [RECOVERY](RECOVERY.md).
