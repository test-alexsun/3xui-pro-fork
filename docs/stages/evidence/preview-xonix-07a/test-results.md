# PREVIEW-XONIX-07A — AWG PMTU and native panel integration

**PREVIEW-XONIX-07A: PASS** — laboratory implementation and acceptance.

Date: 2026-11-23. Part A: **PASS**. Part B: **PASS**. Production migration is
not performed or authorized by this stage. Production remains on its original
standalone installation; the client-only PMTU override was applied only to a
disposable test client. Private paths, UUIDs, keys and subscription tokens are
withheld from this report and public evidence.

## Part A — AWG PMTU

The measured client-to-server IPv4 PMTU is 1440 bytes: IP 1440 succeeds, IP 1441
requires fragmentation; Windows destination cache confirms 1440. Server TUN is
1420, physical ens3 is 1500. The external client is behind an existing VPN/NAT
path. Its path limitation is not evidence of provider firewall port blocking.

The baseline independent bidirectional matrix used five trials per direction
for UDP payloads 64, 256, 512, 1000, 1200, 1280, 1350, 1400, 1440, 1460, 2048.
Server-to-client: 5/5 at every size. Client-to-server: 5/5 through 1280; 0/5 at
1350 and above. UDP payload, inner IPv4 size, encrypted outer IPv4 size and inner
fragmentation are reported separately in awg-pmtu-results.json, with loss/RTT/
EMSGSIZE and counter deltas. Captures contain header metadata only, with a
4000-packet cap and bounded duration; raw production headers remain private.

For S4=12, pinned AWG data framing is outer IPv4 20 + UDP 8 + AWG transport
header 16 + AEAD tag 16 + S4 prefix 12 = 72 bytes, plus inner packet and bounded
16-byte padding. UDP 1350 fits inside the 1420 TUN without inner fragmentation,
but produces a 1464-byte outer packet. Captured client outer packets of
1464/1492 bytes never arrive at the server; smaller trailing packets do arrive.
UDP 2048 is internally fragmented into encrypted outer packets 1492 and 760;
loss of the first prevents inner IP reassembly. Outer fragments were not seen:
client outer packets had DF set. No ICMP fragmentation-needed feedback reached
the container in the matrix capture; the Windows host does learn PMTU 1440.
The exact intermediate device losing data/feedback is not identified.

The minimal remedy is client-side TUN MTU 1440 - 72 = **1368**, specific to this
measured IPv4 path and S4. No server default or code change is needed/proposed.
With only the disposable external client's MTU set to 1368, every payload passed
5/5 both directions; largest captured outgoing outer IP packet was 1440 bytes.
Server AWG, keys, routes, sysctl and firewall were unchanged.

A disposable Debian 13 lab reproduced the same asymmetry using client/router/
server namespaces, route PMTU 1440 in one direction, 1500 in reverse, and lost
ICMP feedback (a lab-only rule). Baseline losses matched production. Client MTU
1368 passed every size, including after restarting both lab AWG processes;
keys were unchanged. See awg-pmtu-lab.json. Named namespace fixtures do not modify
FD_NATIVE; destructive recovery remains disabled.

For a compatible client, configure its Interface MTU to 1368 (e.g. an MTU entry
in a wg-quick-compatible client, or ip link set on an already created test TUN).
Do not paste MTU into awg setconf, which does not manage interface MTU. Measure
again for another path, outer IPv6 or different S4/padding options. Rollback is
to restore that client's previous MTU/profile; no production rollback is needed.
Larger UDP still uses inner fragmentation, not application-level splitting.
A permanent operator/client profile change is not applied by this stage.

## Part B — native panel integration: PASS

The production cause is proven by process, unit, listener, SQLite and
authenticated API inspection. The two processes use the same pinned Xray
binary but have independent configuration authorities.

| Production profile | PID / owner | Configuration | Real listener | Native UI/API |
|---|---|---|---|---|
| P0 | 85585, 3xui-preview-xray.service | /var/lib/3xui-pro-fork/preview-xray.json | 179.254.154.126:8443 | absent |
| P1 | 85585, same standalone unit | same | 127.0.0.1:19441 behind Nginx public 443 | absent |
| P3 | 85585, same standalone unit | same | 179.254.154.126:9443 | absent |
| Native API only | 85478, child of panel PID 85468, 3xui-pro-fork.service | /opt/3xui-pro-fork/panel/bin/config.json | 127.0.0.1:62789 | no user inbounds |

Standalone UUIDs/REALITY private keys are in root-owned mode-0600
`preview-xray.json`; starter exports are root-owned mode-0600
`preview-xray-clients.json`. Native panel SQLite is `x-ui.db` (root, 0600).
`inbounds` stores settings/stream_settings JSON plus tag/listen/port/enable;
`clients.uuid` is canonical UUID while `clients.id` is a numeric row ID;
`client_inbounds` stores assignments/flow overrides. Production had one admin,
zero clients, zero inbounds and SQLite integrity `ok`; authenticated API list
also returned zero. No discovery bridge exists between independent processes.

**Why working profiles were invisible:** standalone owns the sockets and users;
the panel lists its own database. **Can 3.11.0 manage them directly?** Yes, using
real native inbounds and supported client/subscription APIs, proved below.
**Can the processes be combined safely?** A staged, explicit handoff is tested;
only the panel's Xray child remains active for these listeners after acceptance.
**What happens to identity?** Existing UUIDs, REALITY keys/short IDs, XHTTP
host/path/mode, listener layout and Vision are retained. Standalone starters
receive new private native subscription IDs because none existed for them in
the panel. Unrelated panel customers and their subscriptions remain intact.
**Does 3x-ui need a patch?** No panel/frontend/Xray binary patch was needed;
the installer integration uses the pinned supported API.

### Implemented authority and handoff

Model A is implemented as explicit `--panel-inbounds`. Existing standalone
requires the additional `--migrate-panel-inbounds`; a fresh installation needs
only the first flag. The compatibility default remains standalone. After
native READY, omitting the native flag or changing the fixed ingress identity
is refused instead of silently reverting/reimporting old clients.

Three real native tags are `VLESS-REALITY-XHTTP-H2`, `VLESS-TLS-XHTTP-H2` and
`VLESS-REALITY-VISION`. P1 stays loopback cleartext H2 on 19441; supported
external Host/Proxy metadata emits public TLS/SNI/ALPN h2 on main-domain 443.
P3 uses equivalent native TCP alias for raw, retaining `xtls-rprx-vision`.
The default private-IP egress guard remains in production; the private Pebble
lab adds only a narrow test-origin exception. No P2/P4/Hysteria2 or FD_NATIVE
change is included. Only the original two domain names are used.

The installer verifies component/unit/file ownership, original PID generation,
listener owners and source hashes. Conflicting native tag/port/email/UUID
adoption is refused. It backs up SQLite consistently, checks integrity and
preserves the old web state in a root-only migration directory. Disabled real
inbounds and imported clients are staged through API, then the old service is
stopped and all three ports must be free. Native activation compiles SQLite
with one panel restart, checks actual gRPC listeners/users/transport crypto,
then disables the old unit and records READY. Archived standalone files remain
private snapshots; they are not resynchronized into current native customers.

Native hot user updates may leave generated config.json stale. Validation uses
live `lsi`, `inbounduser` and real process/socket owners, with REALITY binary
key/short-ID/target/SNI and XHTTP host/path/mode comparisons. Fresh-connection
traffic and server inbound counter deltas independently prove application.

### Debian 13 installation, UI, subscriptions and data

The existing standalone Debian 13 lab was migrated with preserved starter
identities. A separate clean Debian 13 overlay then installed with the native
flag from its first application install, reaching `PANEL_INBOUNDS_READY` and
`PREVIEW07A_FRESH_NATIVE_READY`. Fresh acceptance used 2 vCPU / 2 GiB RAM,
private Pebble ACME and independent 10.77.5.2 client namespace. It does not
claim public Let's Encrypt issuance from the lab. The production public
certificate was separately verified read-only, below.

| Gate | Result and evidence |
|---|---|
| Native live ownership | PASS, one panel Xray child owns all three target listeners; old standalone inactive/disabled; no duplicate socket owners |
| Original starters | PASS, old UUIDs/keys still transfer 65,536 bytes each direction/profile; server counters correlate |
| Chromium native UI | PASS, authenticated Inbounds shows all three exact tags; client created through form and attached only to these three targets |
| UI-created customer P0 | PASS, real subscription, REALITY, XHTTP H2, 65,536 bytes uploaded and verified downloaded |
| UI-created customer P1 | PASS, real subscription, verified lab TLS/ALPN h2, XHTTP H2, 65,536 bytes each direction |
| UI-created customer P3 | PASS, real subscription, REALITY + Vision, 65,536 bytes each direction |
| Native subscription formats | PASS, raw/JSON/Clash identity, invalid-token 404, unknown-path/domain isolation, no XONIX fallthrough |
| Authenticated panel | PASS, HTTPS login, Secure/HttpOnly/SameSite=Lax cookies, CSRF enforcement, authenticated API and WebSocket 101 |
| Customer UUID edit | PASS, new UUID works on all three; old UUID denied without manual Xray file synchronization |
| One/multiple assignment | PASS, one P0 then all three; after P3 detach subscription contains two and old P3 fresh connections are denied; reattach + selected Vision works |
| Actual inbound update | PASS, API XHTTP path update reaches live Xray and transfers data; old path denied; original path restored |
| Panel restart | PASS, customer's identities/subscription and real data survive cold panel/core restart |
| Installer repeat | PASS, edited customer and native IDs preserved, native PID not restarted, old archived snapshots/AWG keys/certificate unchanged, integrity ok, data rechecked |
| Chromium XONIX | PASS, HTTPS canvas/game checks after certificate renewal |

For a new or newly attached P3 customer, select **Credentials → Flow →
xtls-rprx-vision** after attaching a flow-capable inbound. The normal form
defaults to no flow and hides that field while only XHTTP is selected. A
P0-only customer's flow is normalized accordingly; adding P3 does not silently
choose Vision for the operator. The UI gate actually selects Vision through
the visible form. P0/P1 subscriptions retain empty flow, while P3 has Vision.
No API patch was used to substitute for this UI-created customer's credentials.

For the final UI-created customer's independent 64 KiB tests, native server
uplink/downlink byte deltas were P0 67,385 / 68,737, P1 67,385 / 68,737 and
P3 74,444 / 69,976. These include protocol overhead, independently exceeding
the verified application payload. H2 is asserted from actual client logs for
P0/P1, rather than inferred from the profile name.

See `native-api-results.json`, `native-assignment-results.json`,
`native-browser-results.txt` and `native-smoke-results.json`.

### Negative tests and scoped rollback

| Case | Result |
|---|---|
| Wrong UUID | PASS, fresh access denied on all three |
| Expired customer | PASS, fresh access denied on all three |
| Disabled / deleted customer | PASS, fresh access denied on all three for each case |
| Missing runtime inbound | PASS, real Xray API handler removal detected despite unchanged panel DB; panel restart restores authoritative state |
| DB/live users differ | PASS, real Xray API user removal detected; no automatic overwrite/adoption; restart restores state |
| Duplicate/conflicting port | PASS, disabled foreign panel record claiming target port refused before original service stop, no migration journal created |
| Invalid Xray apply | PASS, a lab-only invalid REALITY key triggers real native activation failure; scoped rollback ends ROLLED_BACK |
| Foreign user preservation | PASS, unrelated native inbound/client UUID/subscription preserved through failed handoff |
| Original data after rollback | PASS, source/web/AWG/certificate hashes unchanged, SQLite integrity ok, old standalone starters pass 64 KiB in both directions on all three |
| Template compensation | PASS, lab-only Xray template exception restored to its prior value on failed handoff |
| Nonterminal journal / changed ownership | PASS in targeted contracts, fail closed; RECOVERY_REQUIRED is not treated as ready or successful rollback |

The real failure sequence reached STAGED → STOPPING_STANDALONE →
ACTIVATING_NATIVE → ROLLING_BACK → ROLLED_BACK. Only recorded staged records
were removed; the database was not replaced wholesale. The final guarded
rollback implementation was tested again after adding template compensation.
No fault injection, service restart or migration ran on production.
See `native-rollback-results.txt` and `native-live-negative-results.txt`.

### Preservation and common gates

| Check | Result |
|---|---|
| Nginx and native Xray config validation | PASS |
| Actual READY journal, JSON Schema 2020-12 with format checks | PASS |
| XONIX/main HTTPS and two-domain isolation | PASS |
| AWG after native integration | PASS, handshake and all 11 payload sizes, three trials each direction, before/after AWG restart |
| AWG keys/config/metadata | PASS, unchanged; no server MTU change |
| ACME renewal | PASS in private Pebble lab: new certificate, Nginx worker change/deploy hook, verified HTTPS after renewal |
| Lab RAM / OOM | 2,021,556 kB total, 1,615,396 kB available at smoke sample, no swap, no kernel OOM |
| Bash/Python/JSON/JS syntax | PASS; all new helpers and existing preview scripts included |
| git diff --check | PASS |
| Unified regression | **318/318 PASS**: all 245 historical + 73 preview tests, exit 0/0 |
| New targeted contracts | **37 added**, original 36 preview contracts retained; PMTU math/capture guards plus native blueprint/API/selection/journal/live users/crypto/publication guards |

Two fresh-fixture harness mistakes were found and fixed before final acceptance:
the first generated fixture omitted the native flag; the next treated
`systemctl is-active`'s expected nonzero inactive result as a shell failure.
The final clean fixture reaches native READY with correct inactive/disabled
assertions. The assignment harness was also corrected to select Vision after
adding P3, matching supported UI semantics. These earlier attempts are not
counted as successful complete fresh acceptance. Final independent smoke,
API/CRUD, assignment, browser and data gates all passed on the clean fixture.

## Production preservation and public checks

The stage used only SSH read-only inspection plus bounded synthetic network
diagnostics. It did not change production SQLite/users/inbounds, Xray/Nginx/AWG
configuration, MTU, routes, sysctl, SSH, DNS or firewall, and did not restart any
production service. Both original Xray PIDs remain 85478 and 85585.

32 static managed files match the verified post-07 off-host backup. Logical
contents of **users, clients, client_inbounds, inbounds and settings** separately
match that consistent SQLite backup; only equality booleans are published.
This verifies administrator/customer/settings preservation without publishing
credentials or UUIDs. Production is still on the 8c17a407 installed revision
and retains its two-process standalone architecture and empty native inbounds.

Public read-only recheck: both names validate against the public trust store,
issuer Let's Encrypt YE1, exactly the two specified SANs, expiry
2027-02-21 08:12:20 UTC. Main-domain XONIX HTTPS returns 200. External TCP
80/443/8443/9443 connect successfully. UDP 29177 reachability, handshake and
bidirectional traffic are proved by Part A; no generic UDP-connect probe is
misrepresented as a handshake. No provider-firewall change or blocking
conclusion is made. Production RAM sample: 990,564 kB total, 599,516 kB
available, no swap, zero kernel OOM events.

See `production-readonly-final.json` and `production-table-preservation.json`.

## Source, publication and remaining boundaries

Branch: `preview/xonix-standalone-debian13`. Baseline HEAD was
`6f990e251149fc9b73bcee279def93b307a413d6`. Reviewed implementation commit and
publication confirmation are recorded below after commit/push. No main merge,
force push or production deployment is part of this stage. Pre-existing
untracked 06/07 evidence and unrelated main-workspace changes are preserved.

Pinned binaries remain panel 3.11.0, Xray 26.11.9, AWG runtime 3.1.20260828
and tools 3.1.20260812; AWG/FD_NATIVE runtime files are unchanged. No invented
AWG runtime fix commit was made: the measured problem requires a path-specific
client interface setting, not a server code change.

Primary compatibility references examined at the pinned upstream version:
[3x-ui model](https://github.com/MHSanaei/3x-ui/blob/v3.11.0/internal/database/model/model.go),
[native clients API](https://github.com/MHSanaei/3x-ui/blob/v3.11.0/internal/web/controller/client.go),
[inbound flow handling](https://github.com/MHSanaei/3x-ui/blob/v3.11.0/internal/web/service/inbound_flow_restore.go),
[native client form](https://github.com/MHSanaei/3x-ui/blob/v3.11.0/frontend/src/pages/clients/ClientFormModal.tsx).

The exact intermediate PMTU loss hop remains unidentified. MTU 1368 applies to
the measured external IPv4/S4 path, not every client or IPv6. Forced termination
of already established customer streams was not tested; deny gates use new
connections. Power-loss recovery and automatic reverse migration after READY
are not qualified. Fixed ingress layout changes require separate planning;
repeat refuses drift instead of erasing native customer edits. Production's
approximately 1 GiB RAM load qualification and production migration remain
separate from this 2 GiB laboratory acceptance. Public production certificate
renewal was not forced; private ACME renewal/deploy hook and public current
certificate trust were tested separately.

The separate production handoff/recovery plan is in
[the installer guide](../../../PREVIEW_XONIX_INSTALL.md#separate-production-migration-plan).
It requires separate authorization and a maintenance window. No production
migration is performed automatically by this result.

### Immutable publication

Implementation and reproducible tests: [`a3a6b991eb21dc2b4822c4fae13426d91e19db48`](https://github.com/test-alexsun/3xui-pro-fork/commit/a3a6b991eb21dc2b4822c4fae13426d91e19db48).
The ordinary preview-only Git push succeeded after laboratory acceptance;
`ls-remote` confirmed that exact implementation SHA. Main before/after remains
`7e822e3e5dfe6f6e95c57fc83b24d00cd7fde661`. No force push or merge was used.
The bootstrap file remains SHA-256
`dd0ef3205a9d9864c7778de2f0b5b41c259866c8c31055855b4bee9cd5295fb3`.
All 78 source/test/asset files in the staged laboratory archive matched the
working source byte-for-byte before commit; hashes are published in
`tested-source-sha256.json`. This evidence is a documentation-only follow-up
to the implementation commit. See `provenance.json` for machine-readable pins.


The **published exact revision** was then fetched from GitHub and installed
again through its SHA-256-verified bootstrap on the disposable native VM:
**PASS**. The native Xray PID, registry, customers and subscription identities
were preserved. Original starters transferred 65,536 verified bytes each
direction/profile again, with independent native server counter deltas.
Nginx/Xray config checks, active native/panel/AWG/renewal units and inactive
standalone were rechecked. No kernel OOM occurred after Chromium; final lab
MemAvailable was 1,550,076 kB. See `published-bootstrap-results.json` and
`post-publication-health.json`. This is a laboratory repeat of the published
pin, not production deployment or public-CA issuance from the lab.
