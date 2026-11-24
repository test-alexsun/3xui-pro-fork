# Установка Debian 13 preview

Это инструкция для новой выделенной Debian 13 amd64 машины. Production migration требует отдельного разрешения и reviewed plan. Не повторять handoff на существующем READY deployment ради добавления протоколов.

## Подготовка

Нужны root, running systemd, `/dev/net/tun`, CAP_NET_ADMIN, настроенные signed Debian repositories и исходящий HTTPS. Historical fixture примерно 1 GiB RAM проходил приёмку; capacity под пользовательской нагрузкой не измерена. Installer требует минимум 512 MiB свободного диска; планируйте запас для компонентов и private backup. На memory-backed `/tmp` используйте `TMPDIR=/var/tmp`.

Подготовьте два DNS A имени на выбранный IPv4; AAAA не добавляйте для неподтверждённого IPv6 deployment. Проверьте TCP80/443, P0 TCP8443, P3 TCP9443 и AWG UDP29177. Дополнительные WG/HY2 порты не назначены. Установщик не открывает host/provider firewall, не изменяет DNS/SSH и не включает NAT автоматически.

Проверьте `ss -H -ltnp`, `ss -H -lunp`, `ip -4 route`, `free -m`, `df -h / /var/tmp`. Выберите свободную dedicated RFC1918 /30 без overlap с существующими маршрутами/VPN. Не публикуйте диагностические данные с private identities.

## Immutable bootstrap

Из чистой root-only директории на новой машине после независимой проверки commit и bootstrap SHA256:

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
  --awg-subnet '<UNUSED_RFC1918_/30>' \
  --panel-inbounds
```

Placeholders намеренно не задают реальные credentials, private subnet или production hosts. При ошибке SHA256 остановиться. Floating branch и main не заменяют reviewed commit. Bootstrap проверяет fetched commit, installer проверяет pinned upstream archives, binary hashes и manifests. Hash из того же непроверенного источника обеспечивает только проверку повреждения.

Строгий режим использует два домена и изолированный Certbot HTTP-01. Порты P0/P3 можно задать `--p0-port` / `--p3-port` только при новом согласованном layout; существующие не менять. Автоматически генерируется private panel path; credentials остаются root-readable, не вставлять их в reports.

## Первый запуск и клиенты

Проверьте systemd/Nginx/HTTPS по [OPERATIONS](OPERATIONS.md), native journal READY, три действительных VLESS inbound и AWG endpoint. Через защищённый UI создайте клиента, назначьте нужные native inbound; для P3 задайте flow `xtls-rprx-vision`. Используйте сгенерированные native subscription links. AWG starter `.conf` выдаётся отдельно по защищённому каналу и не является panel-created customer.

Текущий installer **не создаёт шесть native inbound**. Не добавляйте вручную фиктивные WG/AWG/HY2 rows. [PROTOCOLS](PROTOCOLS.md) описывает gap и ограничения.

## Повтор и обновление

Повтор разрешён с тем же pin, доменами, bind, ports, subnet, credentials и `--panel-inbounds`; installer проверяет ownership и сохраняет клиентов/ключи. `--migrate-panel-inbounds` предназначен для отдельно разрешённого перехода standalone → native, не нужен повторно после READY. Полный updater проекта не реализован; не заменять компоненты floating upstream update.

Исторические sandbox/Pebble режимы и подробные flags: [PREVIEW_XONIX_INSTALL](PREVIEW_XONIX_INSTALL.md). Их нельзя смешивать с public deployment flags.
