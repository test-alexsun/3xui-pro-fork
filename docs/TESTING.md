# Проверки и evidence

**Historical baseline: 318/318 PASS** ([07A report](stages/evidence/preview-xonix-07a/test-results.md), 245 historical + 73 preview tests) сохранён без повторного запуска. Отдельно **PREVIEW-XONIX-08: PASS** для всех шести управляемых inbound (`P0`, `P1`, `P3`, `WIREGUARD`, `AMNEZIAWG-3.1`, `HYSTERIA2`) в чистой Debian 13 lab VM ([08 report](stages/evidence/preview-xonix-08/test-results.md)).

## Разделение контуров тестирования

- **Unit & contract suites (Debian 13 Docker `--network none`)**:
  - `python3 -m unittest discover -s tests/release -v` — **79/79 OK** (guards installer, strict two-domain layout, native P0/P1/P3, VPN ports/conflicts, backup/PMTU/redirect contracts);
  - `python3 -m unittest discover -s tests/protocols -v` — **69 tests (66 OK, 3 live E2E skipped без `PREVIEW08_RUN_E2E=1`)**:
    - [tests/protocols/wireguard/](../tests/protocols/wireguard/test_config.py) — **26 unit OK** (pure-Python RFC 7748 X25519, отказ AWG-полей и порта `29177`, `.conf` / `wireguard://`, PID ownership);
    - [tests/protocols/amneziawg31/](../tests/protocols/amneziawg31/test_config.py) — **22 unit OK** (AWG 3.1 `HeaderProtectionKey`, `Jc`/`Jmin`/`Jmax`/`S1`–`S4`/`H1`–`H4`, отказ plain WG и `kernelMode: true`, `vpn://` / `setconf`, PID ownership);
    - [tests/protocols/hysteria2/](../tests/protocols/hysteria2/test_config.py) — **18 unit OK** (v2 schema, ALPN `h3`, `hysteria2://`, Xray outbound verification);
  - `python3 -m unittest discover -s tests/integration -v` — **15 tests (14 OK, 1 live E2E skipped без `PREVIEW08_RUN_E2E=1`)** ([test_port_isolation.py](../tests/integration/test_port_isolation.py), [test_subnet_isolation.py](../tests/integration/test_subnet_isolation.py), [test_panel_api.py](../tests/integration/test_panel_api.py), [test_install_repeat.py](../tests/integration/test_install_repeat.py)).

- **Независимые live E2E suites (только disposable Debian 13 lab VM с маркером `/var/lib/3xui-preview08-lab = PREVIEW-XONIX-08`)**:
  - `tests/release/preview08_existing_smoke.py` — P0/P1/P3 handshake & >64 KiB counters, HTTPS XONIX (`200`) и subscription root (`404`), `/sub`/`/json`/`/clash` VLESS, Nginx, SQLite, systemd, `oom=0`;
  - `tests/protocols/wireguard/test_e2e.py` — независимый клиент `linux-kernel-wireguard` против UDP `51820` (10 проверок: backend, inbound, client_config, handshake, 65 536 B TCP, 8 192 B UDP, key rotation, disable/enable, restart persistence, delete, export `/sub`/`/json`);
  - `tests/protocols/amneziawg31/test_e2e.py` — независимый клиент `amneziawg-go` `3.1.20260828` + `awg` `3.1.20260812` против UDP `29177` (10 проверок + негативный отказ plain WireGuard, `vpn://` & `/sub`, 65 536 B TCP, 16 × 512 B UDP, CRUD с ожиданием ~30s Xray SOCKS5 reconcile, restart persistence, delete);
  - `tests/protocols/hysteria2/test_e2e.py` — независимый клиент Xray `hysteria` v2 против UDP `24443` (10 проверок: listener, TLS/h3 SNI, 65 536 B TCP, 16 × 512 B UDP, `auth` rotation, CRUD, restart persistence, delete);
  - `tests/integration/test_six_inbounds.py` — одновременная работа всех 6 inbound (7 проверок: disjoint ports/subnets/keys, общий трафик через все 6, отключение `WIREGUARD` не нарушает `AMNEZIAWG-3.1`/`HYSTERIA2`/`P0`, отключение `AMNEZIAWG-3.1` не нарушает `WIREGUARD`/`HYSTERIA2`/`P3`, restart восстанавливает все 6);
  - `tests/xonix/preview08-six-inbounds-panel.cjs` — Playwright Chromium в `preview-client` netns (`XONIX`, panel login cookies `HttpOnly`/`Secure`/`SameSite`, 6 enabled Inbounds rows, 6 Client rows).

## Отмена legacy client compatibility

Проверка старых standalone `/30` WG/AWG клиентских профилей и профилей AWG 1.x/2.x **официально отменена**. Финальная лабораторная приёмка использует новых синтетических клиентов `WIREGUARD` и `AMNEZIAWG-3.1`, при этом существующие клиенты и ключи на production `de126` не изменяются.

## Безопасность проверок

Live E2E и Playwright UI тесты запускаются **исключительно** в изолированной QEMU/Docker лаборатории (RFC1918 bind, `preview-client` netns, тестовый Pebble ACME CA). Запуск E2E-скриптов, создание маркера `/var/lib/3xui-preview08-lab`, мутация SQLite или restart служб на production `de126` запрещены без отдельного разрешения.
