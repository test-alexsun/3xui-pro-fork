---
trigger: model_decision
description: "Read when changing installer orchestration, runtime ownership, panel schema, transports or component versions."
---
# Архитектура

Read `docs/ARCHITECTURE.md`, `docs/DECISIONS.md`, and owning source before changing the existing implementation. Preserve the pinned tuple (`3x-ui 3.11.0`, `Xray 26.11.9`, `amneziawg-go 3.1.20260828`, `awg 3.1.20260812`, Nginx `1.26.3-3+deb13u11`) until a reviewed compatibility change.

Native API/SQLite (`/var/lib/3xui-pro-fork/x-ui.db`) owns all six managed inbounds (`P0`, `P1`, `P3`, `WIREGUARD`, `AMNEZIAWG-3.1`, `HYSTERIA2`), clients, and subscriptions after `READY`. Pre-migration snapshots are recovery evidence only. Keep one native `xray-linux-amd64` child owning P0/P1/P3, `WIREGUARD`, `HYSTERIA2`, and the loopback `AMNEZIAWG-3.1` SOCKS5 relay; in embedded 6-inbound mode `x-ui` MainPID owns UDP `29177` (`kernelMode: false`, omitted by Go `omitempty` in serialized JSON), while `3xui-pro-fork-awg.service` stays inactive/disabled.

Fresh `--panel-inbounds` defaults to 6 inbounds (`--vless-only` keeps 3 VLESS + standalone AWG); upgrading existing 3-VLESS `READY` requires `--panel-inbounds --add-vpn-inbounds` (and `--handoff-standalone-awg` when `3xui-pro-fork-awg.service` is active). Separate journals (`preview-panel-inbounds.json` v1 and `preview-vpn-inbounds.json` v2) must both remain fail-closed with no auto-rollback after `READY`. Display-only inbounds are forbidden; note 3x-ui `3.11.0` forces an async ~30s Xray restart reconcile tick on `AMNEZIAWG-3.1` client updates.
