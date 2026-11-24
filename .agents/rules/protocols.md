---
trigger: model_decision
description: "Read when editing VLESS, WireGuard, AmneziaWG3.1, Hysteria2, clients, subscriptions, routing or MTU."
---
# Протоколы

Target exactly six primary tags: VLESS-REALITY-XHTTP-H2, VLESS-TLS-XHTTP-H2, VLESS-REALITY-VISION, WIREGUARD, AMNEZIAWG-3.1, HYSTERIA2. Preserve the existing three VLESS inbound IDs and settings.

WG/AWG use peer keys and AllowedIPs; do not substitute UUID lifecycle. Require protocol schema compatibility and real runtime effect of panel client changes. Native support alone does not prove existing standalone routing compatibility or safe handoff.

AWG must remain3.1 with pinned runtime/tools and supported HeaderProtectionKey/obfuscation parameters. Never downgrade or replace it with WG. No competing listener on UDP29177. Choose new UDP ports only after actual inventory and conflict checks. Keep server MTU;1368 is scoped to a measured external client path.

Hysteria2 requires actual version2 QUIC/TLS/auth schema and correct export; do not infer format from its name. Do not claim every subscription format supports every protocol. See `docs/PROTOCOLS.md`.
