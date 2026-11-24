---
trigger: model_decision
description: "Read when changing installer orchestration, runtime ownership, panel schema, transports or component versions."
---
# Архитектура

Read `docs/ARCHITECTURE.md` and owning source before changing the existing implementation. Preserve pinned panel3.11.0/Xray26.11.9/AWG3.1 tuple until a reviewed compatibility change.

Native API/SQLite owns current VLESS customers and subscriptions after READY. Pre-migration snapshots are recovery evidence, not current truth. Keep one native Xray child and avoid competing standalone listeners. P1 TLS terminates at Nginx; its external proxy metadata must describe the public endpoint.

An external protocol integration must connect UI/API/SQLite, real runtime, client lifecycle and export. A display-only inbound is forbidden. Document ownership decisions and limitations in architecture/protocol/status docs. Follow AGENTS.md production constraints.
