# Протоколы и фактическая интеграция

Целевой список ровно из шести основных inbound. В текущем installer три native VLESS; AWG отдельный. WG/Hysteria2 не считать готовыми на основании старого README. Поддержка конкретных upstream backend должна подтверждаться исходниками закреплённой версии и живым lifecycle.

## Почему трёх inbound не было

Причина в preview integration, а не в полном отсутствии upstream поддержки: `release/preview_panel_inbounds.py` фиксирует `TAGS` только P0/P1/P3, а `preview_profiles.py` строит VLESS. Separate AWG candidate не создаёт native запись. Старый legacy README смешивал возможности разных режимов.

3x-ui3.11.0 нативно поддерживает все три дополнительных protocol types:

- **WireGuard**: [upstream wireguard schema](https://github.com/MHSanaei/3x-ui/blob/v3.11.0/frontend/src/schemas/protocols/inbound/wireguard.ts), server `secretKey`, peer keys/AllowedIPs; enabled clients преобразуются в real Xray peers. Собственный дублирующий WG service не нужен, если этот backend удовлетворяет выбранной модели маршрутизации.
- **AWG3.1**: [go.mod](https://github.com/MHSanaei/3x-ui/blob/v3.11.0/go.mod) закрепляет `amneziawg-go/v3 v3.1.20260828`; [ServerSettings](https://github.com/MHSanaei/3x-ui/blob/v3.11.0/internal/amneziawg/types.go) включает HeaderProtectionKey и прочие3.1 параметры. [device.go](https://github.com/MHSanaei/3x-ui/blob/v3.11.0/internal/amneziawgnet/device.go) применяет peers через `IpcSet`, [instance.go](https://github.com/MHSanaei/3x-ui/blob/v3.11.0/internal/amneziawg/instance.go) исключает disabled peers. Это реальный embedded gVisor backend с per-peer SOCKS egress в Xray, не decorative record.
- **Hysteria2**: [upstream hysteria schema](https://github.com/MHSanaei/3x-ui/blob/v3.11.0/frontend/src/schemas/protocols/inbound/hysteria.ts), `version:2`, clients/auth, stream `network:hysteria`, TLS/h3. [Xray26.11.9 conf](https://github.com/XTLS/Xray-core/blob/v26.11.9/infra/conf/hysteria.go) требует version2; [server](https://github.com/XTLS/Xray-core/blob/v26.11.9/proxy/hysteria/server.go) требует правильный transport.

Версию панели менять для базовой поддержки не требуется. Критический gap — безопасный AWG handoff: existing host TUN `xproawg0` с /30 и embedded userspace proxy имеют разные routing semantics при одинаковом wire runtime. Сохранить keys недостаточно: надо проверить старый client profile, server tunnel address/маршруты, traffic и MTU, освободить29177 до активации нового владельца. Нельзя автоматически принять этот переход как совместимый.

Минимально затрагиваемые preview пути: `preview_panel_inbounds.py`/новый отдельный integration module, `preview_install.py`, `preview_panel_api.py` при недостающих operations, AWG ownership/journal wrapper и соответствующие existing tests/docs. Не расширять старый native READY journal задним числом и не пересоздавать VLESS.

PREVIEW-08 реализует отдельную opt-in `release/preview_vpn_inbounds.py`, без изменения default installer lifecycle. Она использует существующие native backend; production apply отказывает. Для lab AWG handoff переносит existing parameters/keys/MTU и peer, но acceptance требует реального старого profile traffic после смены backend. `CONFIGURED_NOT_ACCEPTED` в новом private VPN manifest не даёт права объявлять PASS.

Upstream [subscription service](https://github.com/MHSanaei/3x-ui/blob/v3.11.0/internal/sub/service.go) умеет WG `wireguard://`, AWG `vpn://` (encoded config) и HY2 `hysteria2://`. Это source-confirmed capabilities, а не current preview export acceptance. Совместимость каждого raw/JSON/Clash формата проверяется отдельно.

| Tag | Runtime / transport | Endpoint по strict defaults | Клиент и authentication | Export / текущий статус |
|---|---|---|---|---|
| VLESS-REALITY-XHTTP-H2 | Xray 26.11.9 / REALITY XHTTP H2 | TCP 8443 | UUID, REALITY public key, short ID, SNI, XHTTP path | Native VLESS links/JSON/Clash; historical PASS |
| VLESS-TLS-XHTTP-H2 | Xray 26.11.9 / XHTTP H2 за Nginx TLS | Public TCP 443 → loopback 19441 | UUID + TLS hostname verification | Native VLESS links/JSON/Clash; historical PASS |
| VLESS-REALITY-VISION | Xray 26.11.9 / raw TCP REALITY Vision | TCP 9443 | UUID, `xtls-rprx-vision`, REALITY credentials | Native VLESS links/JSON/Clash; historical PASS |
| WIREGUARD | Backend текущей сборки не интегрирован | Не назначен; проверить UDP inventory | Peer public/private keys и AllowedIPs; не UUID | `.conf` нужен; панельный lifecycle не принят |
| AMNEZIAWG-3.1 | amneziawg-go 3.1.20260828 + tools 3.1.20260812 | UDP 29177 | Peer keys + AWG3.1 parameters | Private `.conf`; реальная служба historical PASS, Inbounds integration отсутствует |
| HYSTERIA2 | Runtime текущей сборки не интегрирован | Не назначен; проверить UDP inventory | QUIC/TLS + protocol authentication | `hysteria2://` требует реализации; не принят |

## VLESS

Три существующих native inbound сохраняются по ID. Не пересоздавать UUID, REALITY keys/short IDs, XHTTP settings, Vision flow, certificates или порты. Native клиент может быть attached к одному или нескольким inbound. Для P3 явно задаётся Vision flow. Изменение клиента выполняется native API/UI; fresh reconnect нужен для доказательства disable/delete. Already-established streams не являются отрицательным тестом новых подключений.

Подтверждённая матрица — Xray client 26.11.9 и браузерная панель в 07A/07B evidence. Исторические INCY/Happ результаты относятся к отдельным сценариям; не переносить их автоматически на новую сборку и все subscription formats. Совместимость стороннего клиента зависит от XHTTP/H2/REALITY и его собственной версии.

## AWG 3.1

`release/awg_config_candidate.py` генерирует ровно одну server/client pair на выделенной private /30. Private files 0600, directory 0700; server AllowedIPs — client /32, client AllowedIPs — адрес server tunnel /32. Это не готовая full-tunnel NAT/forwarding конфигурация и не масштабируемый панельный peer manager.

Генератор задаёт S1–S4=12, H1–H4=1/2/3/4 и **HeaderProtectionKey**. Одного совпадения слова AmneziaWG недостаточно: нативный backend должен поддержать именно этот формат 3.1 и сохранять cryptographic identity. Не запускать второй AWG на UDP 29177.

Серверный MTU не менять автоматически. Client-only MTU **1368** был проверен на одном внешнем IPv4 маршруте с PMTU1440 и S4=12; это не глобальный default. Конфигурационный импорт и interface MTU — разные операции.

## WireGuard и Hysteria2

Существующие upstream возможности и исторические core-pair tests не заменяют preview acceptance. Для WG требуется доказать native server peer lifecycle, сохранение private keys, disable/delete, client export и runtime ownership. Для Hysteria2 требуется проверить конкретную schema закреплённого Xray или отдельного runtime, QUIC/TLS, auth и user lifecycle. Не запускать конкурирующие реализации.

Для новых UDP endpoints сначала собрать `ss -H -lunp`, routing/subnet inventory и фактическую доступность. Не занимать AWG 29177. TCP443 и UDP443 различны, но свободный локальный UDP443 ещё не доказывает provider reachability. Не менять provider firewall без разрешения.

Существующий сертификат можно использовать только после проверки SAN, validity, ownership и доступа runtime к key; не выдавать private key веб-процессу без необходимости. Не создавать новые DNS records или ACME lineage ради предполагаемой поддержки.

## Evidence

[07A](stages/evidence/preview-xonix-07a/test-results.md) содержит native panel, subscriptions и AWG PMTU laboratory evidence. BUILD-ALL-04/05A относится к отдельной candidate qualification. Historical WG/HY2 core-pair results из основной исторической ветки не являются доказательством текущего preview. В08 six-record lab получила scoped traffic/lifecycle PASS после targeted fixture/readiness исправлений; исходные FAIL сохранены. Это не приёмка default installer, VPN subscription export или прежнего AWG host-route профиля: [08](stages/evidence/preview-xonix-08/test-results.md).
