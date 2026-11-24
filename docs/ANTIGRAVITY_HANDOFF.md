# Передача проекта и дальнейшее сопровождение

Проект `test-alexsun/3xui-pro-fork` (ветка `preview/xonix-standalone-debian13`) переведён на унифицированную шестипротокольную архитектуру для Debian 13 amd64 (`3x-ui 3.11.0`, `Xray 26.11.9`, `amneziawg-go 3.1.20260828`, `awg 3.1.20260812`, `Nginx 1.26.3-3+deb13u11`) и развёрнут на production VPS `de126`. Перед работой прочитайте [GEMINI.md](../GEMINI.md), [AGENTS.md](../AGENTS.md), [PRODUCTION_ROLLOUT_6_INBOUNDS](PRODUCTION_ROLLOUT_6_INBOUNDS.md), [PROJECT_STATUS](PROJECT_STATUS.md) и [DECISIONS](DECISIONS.md).

## Итоги PREVIEW-XONIX-08 и production rollout `de126`

- **Все 6 целевых inbound активны и проверены на production `de126` (`179.254.154.126`) и в чистой Debian 13 lab VM**: `VLESS-REALITY-XHTTP-H2` (TCP `8443`), `VLESS-TLS-XHTTP-H2` (TCP `443` → `127.0.0.1:19441`), `VLESS-REALITY-VISION` (TCP `9443`), `WIREGUARD` (UDP `51820`), `AMNEZIAWG-3.1` (UDP `29177`), `HYSTERIA2` (UDP `24443`).
- **Строгая независимость WG и AWG 3.1**: реализованы отдельными модулями ([preview_wireguard.py](../release/preview_wireguard.py) и [preview_amneziawg31.py](../release/preview_amneziawg31.py)), раздельными портами, непересекающимися RFC1918 подсетями, отдельными криптоключевыми парами и независимыми E2E-проверками (**WIREGUARD: PASS** и **AMNEZIAWG-3.1: PASS** на lab и на `de126`).
- **Универсальный установщик**: по умолчанию `--panel-inbounds` разворачивает все 6 inbound; `--vless-only` сохранён как opt-out для свежих установок; `--add-vpn-inbounds --handoff-standalone-awg` успешно перевёл `de126` с 3 VLESS + standalone AWG на 6 нативных inbound с ревизии `9e44b525685458f00c34effe6795814b1da24da9` (повтор с `--panel-inbounds` без `--add-vpn-inbounds` идемпотентен).
- **Отмена legacy client compatibility**: старые standalone `/30` AWG-профили (`10.88.31.0/30`) после handoff на `de126` не обслуживаются; старые конфиги/ключи сохранены в `/var/lib/3xui-pro-fork/awg/` и pre-rollout backup `/var/backups/3xui-pro-fork/pre-6inbounds-20261124T084510Z`, а в панели созданы новые профили (`starter-wireguard`, `starter-amneziawg31`, `starter-hysteria2`).

## Состояние production и границы безопасности

- Production VPS `de126` (`179.254.154.126`, `de126.alexsun55.ru` / `de126-sub.alexsun55.ru`) работает на шести нативных inbound (`preview-panel-inbounds.json` `READY`, `preview-vpn-inbounds.json` `version: 2`, `READY`), служба `3xui-pro-fork-awg.service` `inactive`/`disabled`.
- Ветка `main` (`e1240960c49db774fada954340184f625bacc768`) **не изменялась**.
- Автономное разрешение на работу с `de126` действовало только в пределах задачи rollout шести Inbounds. Для новых будущих задач любые production-изменения требуют отдельного явного разрешения владельца, согласованного backup и окна обслуживания.
- При любом `RECOVERY_REQUIRED` автоматический откат запрещён ([RECOVERY](RECOVERY.md)).

## Как развивать дальше

1. Работайте только в preview-ветке с чистыми LF-файлами (`\n`) и правами `100755` на `bootstrap-preview.sh` и `install-preview.sh`.
2. Не меняйте pinned версии компонентов, SHA256 baseline-скрипты (`awg_service.py`, `awg_config_candidate.py`, `*.service`) и `HOOK_SCRIPT` без согласованного релиза.
3. После любых правок в `release/` прогоняйте `tests/release/`, `tests/protocols/`, `tests/integration/`, а поведенческие изменения доказывайте в disposable Debian 13 lab VM ([TESTING](TESTING.md)).
4. Всегда сохраняйте текущих VLESS/WG/AWG3.1/HY2 клиентов на `de126`, оба `READY`-журнала, pre-rollout backup и архив `/var/lib/3xui-pro-fork/awg/`.
