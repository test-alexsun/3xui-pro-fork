---
trigger: model_decision
description: "Read when choosing checks, creating acceptance evidence or interpreting historical protocol test results."
---
# Проверки

Reuse confirmed historical evidence for unchanged components. Historical `318/318 PASS` belongs strictly to PREVIEW-XONIX-07A, and `PASS_CORE_PAIR` belongs to the separate historical core-pair harness — never conflate them with PREVIEW-XONIX-08 results.

Validate WireGuard (`tests/protocols/wireguard/`), AmneziaWG 3.1 (`tests/protocols/amneziawg31/`), and Hysteria2 (`tests/protocols/hysteria2/`) independently, plus shared multi-inbound conflict and non-interference integration via `tests/integration/` and `tests/release/test_vpn_inbounds.py`. Legacy standalone AWG `/30` client compatibility testing is explicitly canceled; test new synthetic WG and AWG 3.1 clients only.

Live E2E (`PREVIEW08_RUN_E2E=1`) and Playwright UI (`tests/xonix/preview08-six-inbounds-panel.cjs`) require a disposable Debian 13 RFC1918 lab VM with `/var/lib/3xui-preview08-lab`; never run them on production. Record failures and skipped/NOT_RUN gates honestly, and separate lab, production, historical, and publication states. See `docs/TESTING.md`.
