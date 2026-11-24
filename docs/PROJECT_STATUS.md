# Статус проекта

Сводка на 2026-11-24. **PREVIEW-XONIX-08: NOT PASS** до подтверждённых шести управляемых inbound и финальной lab приёмки. Это описание current sources, не обещание завершённой интеграции.

| Область | Подтверждённое состояние |
|---|---|
| Preview branch | `preview/xonix-standalone-debian13` |
| Исходный docs HEAD | `d2d184f9877f3c49fbd2e1987f35ebb5c97e9cb6` |
| Implementation baseline | `a3a6b991eb21dc2b4822c4fae13426d91e19db48` |
| Production implementation | Тот же a3a6b99 по существующему 07B report; новый read-only audit:3VLESS, READY, AWG29177; сохранены PID/config/cert |
| Последняя historical regression | 318/318 PASS, 07A |
| Production journal | READY по 07B report; в PREVIEW-08 mutation не разрешена |
| Native panel | Три VLESS P0/P1/P3 |
| AWG 3.1 | Отдельный реальный runtime, не native Inbounds peer management |
| WG / HY2 | Не создаются installer; optional lab utility PREVIEW-08 отдельно от default lifecycle |
| Новая lab проверка |6real API records/listeners, P0/P1/P3 traffic, WG/AWG/HY2 TCP/UDP+restart+disable/delete/recreate PASS после targeted fixture fixes; initial FAIL сохранены |
| Проверенная preview implementation | `2f275b6be69531eed80cdbcab5015369782afc43`, remote/tree проверены; последующий commit только фиксирует publication evidence |

## Завершено ранее

Strict two-domain Nginx/ACME/XONIX, native handoff P0/P1/P3, сохранение UUID/keys, native customer lifecycle и subscriptions проверялись в 07A; production handoff с READY — в 07B. Закреплён AWG 3.1; измеренный client path MTU1368 не меняет server default.

## Открыто

Полная связь WireGuard/AWG3.1/Hysteria2 UI → API/SQLite → runtime → client export → disable/delete/restart. Upstream backend поддерживает все три типа. Блокер: default installer не включает utility; embedded AWG не подтверждает прежний host-TUN/server-address профиль. Минимальные решения — реальный adapter существующей службы либо отдельно принятый kernel/host-address handoff; детали в08 evidence.

Source audit подтвердил upstream native support всех трёх в3.11.0, включая ту же AWG3.1 module version и Xray HY2 version2. Основная причина отсутствия — installer фиксировал только три VLESS tag. AWG handoff требует отдельной проверки host-TUN → embedded gVisor routing compatibility; одинаковая версия wire runtime её не доказывает. [Подробное заключение](PROTOCOLS.md#почему-трёх-inbound-не-было).

`release/preview_vpn_inbounds.py` — opt-in laboratory integration, не automatic installer hook. Production apply запрещён utility; native READY сохраняется отдельно. Новый VPN manifest `CONFIGURED_NOT_ACCEPTED` означает только завершённую конфигурацию, не acceptance. Actual final checks и published revision проверять в08 evidence.

Full project updater/rollback, автоматический reverse READY, production six-inbound rollout, global client compatibility и full-tunnel NAT не приняты. Нет команды безопасного production применения трёх отсутствующих inbound до завершённой реализации и lab acceptance.

## Следующие допустимые направления

Сначала завершить source-compatible backend/control-plane integration и один final lab run. Затем immutable preview publication, sanitization review и отдельное операторское разрешение на production apply. Развитие UI, exporter и backup automation должно сохранять current clients/keys и разделение evidence. [Antigravity handoff](ANTIGRAVITY_HANDOFF.md).
