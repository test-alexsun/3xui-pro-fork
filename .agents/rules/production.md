---
trigger: model_decision
description: "Read before any production access, migration, restart, peer management, database or deployment operation."
---
# Production

Default authorization for future tasks is read-only diagnosis. Within the six-inbound rollout task, the owner authorized autonomous work on `preview/xonix-standalone-debian13` and `de126`; that authorization was scoped strictly to that assignment, is not perpetual, and does not override security boundaries. Any new production (`de126`, `179.254.154.126`) database/inbound/peer/config/firewall/SSH/DNS/certificate mutations and service restarts require separate explicit authorization.

`de126` runs the six managed native inbounds installed from reviewed preview revision `9e44b525685458f00c34effe6795814b1da24da9` (`P0`, `P1`, `P3` in `preview-panel-inbounds.json` `READY`; `WIREGUARD`, `AMNEZIAWG-3.1`, `HYSTERIA2` in `preview-vpn-inbounds.json` `version: 2`, `READY`; standalone `3xui-pro-fork-awg.service` `inactive`/`disabled` after `--handoff-standalone-awg`, while `/var/lib/3xui-pro-fork/awg/` and pre-rollout backup `/var/backups/3xui-pro-fork/pre-6inbounds-20261124T084510Z` remain preserved). Note that legacy `/30` standalone AWG clients lose access after the handoff without legacy profile compatibility claims.

Preserve current identities, domains, certificates, ports, and `READY` journals; never delete journals, repeat `--add-vpn-inbounds`, or run automatic rollback. `RECOVERY_REQUIRED` requires manual diagnosis with retained backups. Never run two AWG runtimes on UDP `29177`, never alter server MTU (`1420`), and never run lab/fault-injection scripts on production. See `docs/RECOVERY.md` and `docs/PRODUCTION_ROLLOUT_6_INBOUNDS.md`.
