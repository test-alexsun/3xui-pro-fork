# Установка Debian 13 preview

Документ описывает универсальный установщик Debian 13 amd64/systemd с шестью управляемыми inbound (`VLESS-REALITY-XHTTP-H2`, `VLESS-TLS-XHTTP-H2`, `VLESS-REALITY-VISION`, `WIREGUARD`, `AMNEZIAWG-3.1`, `HYSTERIA2`). Применение на существующем production `de126` требует отдельного разрешения и окна обслуживания.

## Предварительные требования

- Свежая Debian 13 (trixie) amd64 машина с `systemd` PID 1, root, `/dev/net/tun`, `CAP_NET_ADMIN`, подписанными репозиториями Debian (`apt`) и исходящим HTTPS к закреплённым источникам (`3x-ui` `3.11.0`, `Xray-core` `26.11.9`, Nginx Debian Security `1.26.3-3+deb13u11`).
- Минимум 512 MiB свободного места на `/` и достаточный RAM (при memory-backed `/tmp` обязательно передавайте `TMPDIR=/var/tmp`).
- Ровно два DNS A-имени (`--domain` и `--subscription-domain`), указывающих на `--public-bind`. AAAA не настраиваются для IPv4-only режима.
- Свободные непересекающиеся порты по умолчанию:
  - TCP `80`, `443` (Nginx + P1 TLS/H2);
  - TCP `8443` (`--p0-port`), TCP `9443` (`--p3-port`), loopback TCP `2096` (`--subscription-port`);
  - UDP `51820` (`--wg-port`, `WIREGUARD`);
  - UDP `29177` (`--awg-port`, `AMNEZIAWG-3.1`);
  - UDP `24443` (`--hy2-port`, `HYSTERIA2`).
- Свободные непересекающиеся RFC1918 IPv4 подсети `/16../30` без конфликтов с маршрутами хоста и Docker/VPN сетями (`ip -4 route show table all`):
  - `--wg-subnet` (по умолчанию `10.89.8.0/24`);
  - `--awg-subnet` (обязателен; рекомендуемое значение для 6-inbound режима `10.88.32.0/24`).

Установщик не изменяет host/provider firewall, SSH, DNS и не включает глобальный NAT; доступность TCP/UDP портов проверяется оператором заранее.

## Режим 1: свежая установка с 6 управляемыми inbound (по умолчанию)

Из root-only каталога после независимой сверки 40-hex commit SHA и SHA256 `bootstrap-preview.sh`:

```sh
umask 077
REV='<REVIEWED_40_HEX_COMMIT>'
BOOTSTRAP_SHA256='<INDEPENDENTLY_VERIFIED_SHA256>'
curl -fsSL "https://raw.githubusercontent.com/test-alexsun/3xui-pro-fork/$REV/bootstrap-preview.sh" -o bootstrap-preview.sh
printf '%s  %s\n' "$BOOTSTRAP_SHA256" bootstrap-preview.sh | sha256sum -c -
TMPDIR=/var/tmp sh ./bootstrap-preview.sh "$REV" \
  --public-bind '<SERVER_IPV4>' \
  --domain 'vpn.example.com' \
  --subscription-domain 'sub.example.com' \
  --acme-email 'operator@example.com' \
  --wg-subnet '10.89.8.0/24' \
  --awg-subnet '10.88.32.0/24' \
  --wg-port 51820 \
  --awg-port 29177 \
  --hy2-port 24443 \
  --panel-inbounds
```

Что делает этот запуск:
1. `install_candidate.py --no-standalone-awg` устанавливает `3x-ui 3.11.0`, `xray-linux-amd64 26.11.9` и AWG 3.1 бинарники в `/opt/3xui-pro-fork`, настраивает Nginx + SAN ACME TLS и стартует `3xui-pro-fork.service` (при этом `3xui-pro-fork-awg.service` остаётся disabled/inactive).
2. `preview_panel_inbounds.py` импортирует и верифицирует P0/P1/P3 (`preview-panel-inbounds.json` → `READY`).
3. `preview_vpn_inbounds.py` валидирует разделение портов и подсетей, разворачивает независимые `WIREGUARD`, `AMNEZIAWG-3.1` и `HYSTERIA2` со стартовыми клиентами (`starter-wireguard`, `starter-amneziawg31`, `starter-hysteria2`) и фиксирует `preview-vpn-inbounds.json` → `READY`.

## Режим 2: Opt-out `--vless-only` (совместимость со старой схемой)

Для сохранения старой раскладки (3 native VLESS + отдельная systemd-служба `3xui-pro-fork-awg.service` на `/30`) на свежей машине:

```sh
TMPDIR=/var/tmp sh ./bootstrap-preview.sh "$REV" \
  --public-bind '<SERVER_IPV4>' \
  --domain 'vpn.example.com' \
  --subscription-domain 'sub.example.com' \
  --acme-email 'operator@example.com' \
  --awg-subnet '<UNUSED_RFC1918_/30>' \
  --panel-inbounds \
  --vless-only
```

Если на узле уже существует `preview-vpn-inbounds.json`, флаг `--vless-only` отклонён (fail-closed).

## Режим 3: Opt-in добавление VPN на существующий 3-VLESS `READY` узел

Не запускается автоматически и на production требует согласованного backup, проверки свободных UDP-портов и окна обслуживания (успешно применено на `de126` 2026-11-24 с ревизии `9e44b525685458f00c34effe6795814b1da24da9` — [PRODUCTION_ROLLOUT_6_INBOUNDS](PRODUCTION_ROLLOUT_6_INBOUNDS.md)):

```sh
TMPDIR=/var/tmp sh ./bootstrap-preview.sh "$REV" \
  --public-bind '<SERVER_IPV4>' \
  --domain 'vpn.example.com' \
  --subscription-domain 'sub.example.com' \
  --acme-email 'operator@example.com' \
  --wg-subnet '10.89.8.0/24' \
  --awg-subnet '10.88.32.0/24' \
  --wg-port 51820 \
  --awg-port 29177 \
  --hy2-port 24443 \
  --panel-inbounds \
  --add-vpn-inbounds \
  --handoff-standalone-awg
```

Без `--add-vpn-inbounds` повторный запуск против существующего 3-VLESS `READY` оставляет узел нетронутым; без `--handoff-standalone-awg` активная `3xui-pro-fork-awg.service` никогда не останавливается. Оба флага `--add-vpn-inbounds` и `--handoff-standalone-awg` требуют `--panel-inbounds`, а `--vless-only` несовместим с `--add-vpn-inbounds`. После завершения `--add-vpn-inbounds` повторный запуск выполняется уже **без** `--add-vpn-inbounds` (только `--panel-inbounds` с теми же портами/подсетями).

## Безопасный повтор

Повторный вызов с теми же `--domain`, `--subscription-domain`, `--public-bind`, портами, подсетями и `--panel-inbounds` завершается кодом `0` (подтверждено и в VM, и на `de126`), проверяет `upgrade_candidate.inspect_installed(..., require_standalone_awg=False)`, `native.verify_ready()` и `vpn.verify_ready()`, не меняя inbound IDs, UUIDs, ключи, `subId` и операторских клиентов. При расхождении параметров или состоянии `RECOVERY_REQUIRED` повтор аварийно останавливается без изменений.

Исторические flags sandbox/Pebble: [PREVIEW_XONIX_INSTALL](PREVIEW_XONIX_INSTALL.md).
