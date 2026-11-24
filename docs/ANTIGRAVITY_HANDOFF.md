# Передача проекта и дальнейшее сопровождение

Проект `test-alexsun/3xui-pro-fork` (ветка `preview/xonix-standalone-debian13`) переведён на унифицированную шестипротокольную архитектуру для Debian 13 amd64 (`3x-ui 3.11.0`, `Xray 26.11.9`, `amneziawg-go 3.1.20260828`, `awg 3.1.20260812`, `Nginx 1.26.3-3+deb13u11`). Перед работой прочитайте [GEMINI.md](../GEMINI.md), [AGENTS.md](../AGENTS.md), [PROJECT_STATUS](PROJECT_STATUS.md) и [DECISIONS](DECISIONS.md).

## Итоги PREVIEW-XONIX-08

- **Все 6 целевых inbound активны и проверены в чистой Debian 13 lab VM**: `VLESS-REALITY-XHTTP-H2` (TCP `8443`), `VLESS-TLS-XHTTP-H2` (TCP `443` → `127.0.0.1:19441`), `VLESS-REALITY-VISION` (TCP `9443`), `WIREGUARD` (UDP `51820`), `AMNEZIAWG-3.1` (UDP `29177`), `HYSTERIA2` (UDP `24443`).
- **Строгая независимость WG и AWG 3.1**: реализованы отдельными модулями ([preview_wireguard.py](../release/preview_wireguard.py) и [preview_amneziawg31.py](../release/preview_amneziawg31.py)), раздельными портами, непересекающимися RFC1918 подсетями, отдельными криптоключевыми парами и независимыми E2E-наборами.
- **Универсальный установщик**: по умолчанию `--panel-inbounds` разворачивает все 6 inbound и проходит идемпотентный повтор без мутации клиентов/ключей; `--vless-only` сохранён как opt-out для 3 VLESS + standalone AWG; `--add-vpn-inbounds` (+ `--handoff-standalone-awg`) позволяет явный переход с 3 VLESS.
- **Отмена legacy client compatibility**: проверялись новые синтетические профили WG и AWG 3.1 (без AWG 1.x/2.x или старых `/30` клиентских адаптеров), при строгой неприкосновенности production `de126`.

## Состояние production и границы безопасности

- Production VPS `de126` (`179.254.154.126`) **не изменялся** и продолжает работать на native 3 VLESS (`READY`) + отдельной службе `3xui-pro-fork-awg.service` (UDP `29177`).
- Ветка `main` (`7e822e3e5dfe6f6e95c57fc83b24d00cd7fde661`) **не изменялась**.
- Любые production-изменения, включая запуск `--panel-inbounds --add-vpn-inbounds --handoff-standalone-awg`, требуют отдельного письменного разрешения оператора, предварительного off-host encrypted backup (SQLite Online Backup API + `/var/lib/3xui-pro-fork/` + `/var/lib/3xui-preview-acme/`), проверки свободных портов `51820`/`24443` и согласованного окна обслуживания.
- При любом `RECOVERY_REQUIRED` автоматический откат запрещён ([RECOVERY](RECOVERY.md)).

## Как развивать дальше

1. Работайте только в preview-ветке с чистыми LF-файлами (`\n`) и правами `100755` на `bootstrap-preview.sh` и `install-preview.sh`.
2. Не меняйте pinned версии компонентов, SHA256 baseline-скрипты (`awg_service.py`, `awg_config_candidate.py`, `*.service`) и `HOOK_SCRIPT` без согласованного релиза.
3. После любых правок в `release/` прогоняйте `tests/release/`, `tests/protocols/`, `tests/integration/`, а поведенческие изменения доказывайте в disposable Debian 13 lab VM ([TESTING](TESTING.md)).
4. Для согласованного production rollout используйте явный план с сохранением текущих UUID/REALITY-ключей, VLESS-клиентов, AWG 3.1 параметров/ключей, двух доменов и SAN-сертификатов.
