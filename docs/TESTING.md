# Проверки и evidence

**Historical baseline: 318/318 PASS**, PREVIEW-XONIX-07A, отдельно 245 historical +73 preview tests. Это существующая регрессия, не результат нового six-inbound прогона. Источник: [07A report](stages/evidence/preview-xonix-07a/test-results.md) и сохранённый `unified-regression.log` в том же каталоге.

## Что уже подтверждалось

| Evidence | Подтверждённая область | Что не следует из результата |
|---|---|---|
| BUILD-ALL-04/05A | Pinned candidate, AWG real handshake/UDP/systemd, private config | Все шесть native inbound |
| PREVIEW-04/04B/05 | XONIX, sandbox TLS, P0/P1/P3 transport, standalone installer | Полная production приёмка |
| PREVIEW-06A/07-redirect | Strict two-domain layout, immutable bootstrap, redirect | Native customers до 07A |
| PREVIEW-07A | Native panel/API/UI, VLESS raw/JSON/Clash traffic, negative client changes, scoped rollback, PMTU lab, 318 tests | WG/HY2 native integration |
| PREVIEW-07B | Существующий локальный production report: native migration PASS, READY, P0/P1/P3 и AWG traffic | Новый live результат текущего чата или six-inbound preview |

WG/HY2 исторические **core-pair** проверки находятся в основной исторической ветке/других fixtures, а не в принятой шестипротокольной preview панели. Нельзя переименовать их в current acceptance. PREVIEW-07B evidence может оставаться локальным private материалом; перед публикацией требуется отдельная sanitization review.

## Выбор проверок по изменению

- Native integration: `tests/release/preview07a_native_smoke.py`, `preview07a_customer_setup.py`, `preview07a_native_acceptance.py`; проверить prerequisites каждого script.
- Assignments: `preview07a_assignment_updates.py`; UI: `tests/xonix/preview07a-panel.cjs`, затем `preview07a_ui_data.py`.
- Negative lifecycle: `preview07a_negative_live.py` только в disposable lab.
- PMTU: `preview07a_pmtu_vm.py` только при изменении соответствующего runtime/path; не повторять без причины.
- Scoped failure rollback: `preview07a_rollback_vm.py` только в предназначенном minimal fixture, никогда после production READY.
- Installer/public web: existing `preview07a_vm.sh` и `preview07_vm.sh` подготавливают disposable VM, Pebble/test certs, namespaces; это не production deployment scripts.

Минимальные unit checks текущего preview: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests/release -v` в Linux окружении со всеми prerequisites. Полный historical runner `tests/release/run_preview_regression.sh` требует отдельные `/src`, `/preview`, native Docker volumes и network-none root Debian container; не запускать на host/production и не повторять на каждом изменении.

## Единственный финальный прогон PREVIEW-08

После завершённой реализации один lab run должен проверить шесть реальных inbounds, backend ownership, правильные listeners, fresh handshake/auth, bidirectional traffic, client exports, disable/delete и restart persistence. Отдельно общий smoke: HTTPS, XONIX/browser, panel/API, subscriptions, AWG, Nginx, SQLite, systemd, memory/OOM и critical logs. Старые неизменённые checks reuse явно обозначать.

Без реальной интеграции WG/AWG/HY2 такой прогон не может получить PASS. Новый результат фиксируется отдельно в [08 report](stages/evidence/preview-xonix-08/test-results.md), не складывается с 318 и не переименовывает historical tests.

## Production запреты

Без отдельного разрешения не создавать clients/inbounds, не менять SQLite/runtime, не restart panel/Xray/AWG, не выполнять fault injection, rollback, DNS/firewall/certificate mutations. Read-only диагностика может содержать secrets; публиковать только sanitized structural outcomes. Public evidence не содержит реальные client profiles, credentials, backup или subscription URLs.

## Выполненные08 проверки и команды

Точный результат и ограничения: [08 report](stages/evidence/preview-xonix-08/test-results.md). Шесть native records/listeners и scoped traffic/lifecycle проверены в disposable Debian13 overlay. Первый FAIL и targeted corrections сохранены; overall INCOMPLETE из-за installer/старого AWG host-route профиля и непринятых UI/export gates.

Только новые guard tests из checkout:

```sh
python3 -B -m unittest discover -s tests/release -p test_vpn_inbounds.py -v
```

Lab utility требует заранее установленный native READY baseline, RFC1918 bind, private root-owned marker `/var/lib/3xui-preview08-lab` с содержимым `PREVIEW-XONIX-08`, private AWG JSON с теми же server/client keys, server subnet, obfuscation и наблюдаемым MTU. Не создавать marker на production и не обходить guard. Сначала проверить listeners/маршруты; приведённые порты — именно свободные lab choices, не production default.

```sh
python3 release/preview_vpn_inbounds.py --wg-port 29178 --hy2-port 24443
# Только disposable lab, отдельный private AWG fixture:
python3 release/preview_vpn_inbounds.py --wg-port 29178 --hy2-port 24443 \
  --awg-settings-file /root/lab-awg.private.json --lab --lab-handoff-awg --apply
python3 tests/release/preview08_final.py \
  --ca /var/lib/3xui-preview-acme/config/live/3xui-preview/fullchain.pem \
  --output /root/lab-final-results.json
python3 tests/release/preview08_existing_smoke.py
```

Harness использует конкретную namespace topology10.77.5.1/10.77.5.2 и controlled benchmark route, не universal production smoke. При конкретной ошибке `--protocol` и `--restart-only` позволяют адресную проверку. Не выдавать её за независимый повтор всего финального набора.
