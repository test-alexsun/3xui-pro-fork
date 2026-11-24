---
trigger: model_decision
description: "Read before any production access, migration, restart, peer management, database or deployment operation."
---
# Production

Default authorization is read-only diagnosis. Production (`de126`, `179.254.154.126`) database/inbound/peer/config/firewall/SSH/DNS/certificate mutations and service restarts require separate explicit authorization. A clean-VM lab PASS or preview push never authorizes production deployment.

`de126` remains unmutated on `a3a6b991eb21dc2b4822c4fae13426d91e19db48` (three native VLESS P0/P1/P3 with `READY` journal + active standalone `3xui-pro-fork-awg.service` on UDP `29177`). Preserve current identities, domains, certificates, ports, and `READY` journals; never delete journals, repeat migration, or run automatic rollback. `RECOVERY_REQUIRED` requires manual diagnosis with retained backups.

Upgrading an existing 3-VLESS `READY` host to 6 inbounds requires explicit maintenance authorization, consistent pre-change backups, and `--panel-inbounds --add-vpn-inbounds --handoff-standalone-awg`; note that standalone AWG `/30` host-TUN routing is replaced by embedded AWG 3.1 without legacy `/30` profile compatibility claims. Never run two AWG runtimes on UDP `29177`, never alter server MTU (`1420`), and never run lab/fault-injection scripts on production. See `docs/RECOVERY.md`.
