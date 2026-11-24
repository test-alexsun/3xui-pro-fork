---
trigger: model_decision
description: "Read when editing VLESS, WireGuard, AmneziaWG3.1, Hysteria2, clients, subscriptions, routing or MTU."
---
# Протоколы

Target exactly six primary tags: `VLESS-REALITY-XHTTP-H2`, `VLESS-TLS-XHTTP-H2`, `VLESS-REALITY-VISION`, `WIREGUARD`, `AMNEZIAWG-3.1`, `HYSTERIA2`. Preserve existing P0/P1/P3 inbound IDs, UUIDs, REALITY keys/short IDs, XHTTP settings, and Vision flow.

WireGuard and AmneziaWG 3.1 are strictly independent protocols with separate modules (`release/preview_wireguard.py` vs `release/preview_amneziawg31.py`), UDP ports (`51820` vs `29177`), disjoint RFC1918 subnets (`10.89.8.0/24` vs `10.88.32.0/24` in 6-inbound mode), key generators (pure-Python RFC 7748 X25519 vs `awg genkey`/`pubkey` + `HeaderProtectionKey`), client records, exports (`.conf`/`wireguard://`/`/sub`/`/json` with zero AWG fields vs `vpn://` decoded to AWG 3.1 `.conf`/`setconf` with `on/off` booleans), and E2E suites. Note `clients/get` & `clients/list` return `allowedIPs` as a comma-separated string while `inbounds/list` stores a JSON list.

AWG must remain 3.1 (`3.1.20260828`/`3.1.20260812`) with `HeaderProtectionKey` and `kernelMode: false` (omitted by Go `omitempty` in serialized JSON); never downgrade to 1.x/2.x, plain WireGuard, or `kernelMode: true` (`xui-awg<ID>`). Hysteria2 must stay `version: 2`, `network: hysteria`, TLS `alpn: ["h3"]` reusing the two-domain ACME cert with strict verification (`allowInsecure` forbidden). Keep server MTU `1420`; client MTU `1368` is scoped solely to the measured 07A external path. See `docs/PROTOCOLS.md`.
