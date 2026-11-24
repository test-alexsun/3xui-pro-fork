---
trigger: model_decision
description: "Read before any production access, migration, restart, peer management, database or deployment operation."
---
# Production

Default authorization is read-only diagnosis. Production database/inbound/peer/config/firewall/SSH/DNS/certificate mutations and service restarts require separate explicit authorization. A successful preview push does not authorize deployment.

Preserve current P0/P1/P3 identities, domains, certificates, ports and READY journal. Never repeat migration, delete journal or automatically reverse READY. RECOVERY_REQUIRED requires manual diagnosis with retained evidence/backups.

Do not start another AWG runtime on UDP29177. Preserve server MTU. Prepare concrete reviewed lab-qualified apply/backup/recovery steps before asking to deploy. Do not run fault injection or laboratory scripts on production. See `docs/RECOVERY.md`.
