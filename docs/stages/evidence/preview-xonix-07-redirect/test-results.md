# PREVIEW-XONIX-07 â€” off-host HTTP redirect qualification

Status: PASS — off-host redirect qualification only. Production deployment remains on hold.

Base: 8410dc9b01ef19e49844839ae4cd7b09749e48ea. The originally requested
installer d0cbd985ff10c2faf4376c7d411c50d47d1b9ee6 served HTTP XONIX 200
and subscription-root 404 without Location headers. The user chose to hold
deployment until a corrected revision is checked, rather than waive redirect.
No production installation, public ACME order or VPS configuration change is
included in this correction. The original pin is not replaced without approval.

## Change

- Preserve HTTP bootstrap readiness before TLS exists.
- After a verified certificate is configured, return 308 to each fixed validated
  hostname, preserving URI/query, for both main and subscription HTTP vhosts.
- Keep HTTP-01 challenge locations direct on port 80; unknown Host is not used
  as a redirect destination. Managed access/error logging remains suppressed.
- Validate redirects without following them or disabling TLS checks. HTTPS is
  still verified separately using normal trust or an explicit private lab CA.
- Persist the redirect contract in private owned state and validate the previous
  contract during rollback, including older HTTP-content states.
- Preserve protocols, public ports, two-name SAN, UUIDs, keys, credentials and
  isolated renewal. No binary upgrade or new hostname is introduced.

## Validation

All original 30 preview tests plus 6 new redirect/readiness/rollback contracts
passed: 36/36. Original tests were not edited. Unified regression passed
281/281 (245 historical in 304.819s, 36 preview in 0.467s), both exit 0,
in a network-isolated read-only Debian container. Fresh Debian 13/Pebble VM
acceptance passed, including Chromium HTTPS game smoke and owned Nginx rollback.
The VM powered off normally; no production host was used. The extended stage07 web fixture
checks real HTTP responses for both domains and multiple URI/query values,
HTTP-01, trusted HTTPS, panel/API/CSRF/cookies/WebSocket, subscription isolation
and log secrecy, alongside P0/P1/P3, repeat, AWG, renewal and owned Nginx rollback.

Qualified proposed installation SHA: `8c17a4078e1e9d925b8ece9b15dbf951228767aa`.
Provider/public-TLS/production acceptance is separate; pin replacement and
production execution still require explicit operator approval.

## Local VM evidence

Fresh Debian 13 genericcloud amd64, 3072 MiB RAM, two vCPUs, no production
configuration. Real peer network namespace, normal trust with an explicit Pebble
lab CA (not public Let's Encrypt), pinned payloads. Full acceptance markers:

- PREVIEW07_HTTP_HTTPS_REDIRECT_BOTH_DOMAINS_URI_QUERY_PASS (initial, repeat, rollback)
- P0/P1/P3_HANDSHAKE_DATA_PASS: each uploaded/downloaded 65536 bytes, reconnect,
  matching server inbound correlation
- PREVIEW06A_PANEL_LOGIN_COOKIE_CSRF_API_WEBSOCKET_PASS
- PREVIEW06A_SUBSCRIPTIONS_ALL_FORMATS_INVALID_UNKNOWN_EXPOSURE_SNI_PASS
- PREVIEW06A_TOKEN_LOG_REDACTION_PASS
- PREVIEW06A_REPEAT_INSTALL_PASS
- PREVIEW06A_AWG_UDP_BEFORE_RESTART_PASS and AWG_UDP_RECONNECT_PASS
- PREVIEW06A_ACME_RENEWAL_RELOAD_PASS (private Pebble)
- PREVIEW06A_NGINX_RECOVERY_PASS (fault injection only in this disposable VM)
- PREVIEW06A_XONIX_BROWSER_HTTPS_PASS and PREVIEW06A_BROWSER_PASS
- PREVIEW07_REDIRECT_INTEGRATION_PASS

Browser smoke is scoped to the existing lab fixture, not the full public game
acceptance requested for production. Public CA issuance and external production
connectivity remain NOT_RUN. Standalone identities remain separate from panel
customers; AWG remains server-address-only, with destructive recovery disabled.

## Exact published bootstrap and 1 GiB capacity

The immutable commit above was installed from GitHub in a second fresh Debian
13 VM: 1024 MiB configured RAM, one vCPU, no swap, TMPDIR=/var/tmp, 96 MiB
additional anonymous memory reserved. The bootstrap hash was checked before
execution and remains:
`dd0ef3205a9d9864c7778de2f0b5b41c259866c8c31055855b4bee9cd5295fb3`.
The bootstrap fetched and checked the exact commit; no floating branch was used.

Initial install, repeat with preserved state, both redirects/URI/query,
HTTP-01, exact two-name SAN/private-CA HTTPS, panel/API/WebSocket/subscriptions,
P0/P1/P3 65536-byte transfers each way and reconnect/server correlation,
AWG traffic/restart and isolated Pebble renewal/reload all passed. VM shutdown
was normal, QEMU exit 0. Browser and fault injection were covered in the first
local-source VM; they were not repeated in this capacity VM.

Memory sampling (requested 20 Hz; shorter peaks may be missed): MemTotal
991164 KiB, initial MemAvailable 747880 KiB, minimum 313432 KiB (306.1 MiB),
4430 samples, OOM-kill delta 0. See memory-install-check.json. This supports the
initial installation envelope, not long-term production concurrency capacity.
No swap or production changes were made by this qualification.
