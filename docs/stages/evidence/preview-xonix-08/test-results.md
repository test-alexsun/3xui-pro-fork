# PREVIEW-XONIX-08 — integration and handoff

Date: 2026-11-24. **Overall: INCOMPLETE, not PASS.** This preview adds an explicit laboratory integration and source-backed handoff documentation. The default installer still provisions three native VLESS inbounds plus standalone AWG. Production six-inbound migration is not qualified or executed.

## A. Why three inbounds were absent

| Protocol | Native panel support at 3.11.0 | Existing project implementation | Cause / selected runtime |
|---|---|---|---|
| WireGuard | Yes | Historical Xray userspace core-pair tests | Preview provisioning only imported P0/P1/P3; now uses native Xray, no duplicate service |
| AmneziaWG 3.1 | Yes; embedded dependency `amneziawg-go/v3 v3.1.20260828` | Separate pinned AWG3.1 service, private single-peer /30 configuration | Existing `awg_service.py` owns host TUN/UDP29177 and never creates a panel record; laboratory utility imports identities into embedded panel manager after releasing the old port |
| Hysteria2 | Yes, panel protocol `hysteria`, version2 | Historical Xray26.11.9 core-pair tests | No current preview provisioning; now native Xray protocol/transport hysteria with TLS/h3 |

Evidence: [fixed native registry](../../../../release/preview_panel_inbounds.py), [AWG supervisor](../../../../release/awg_service.py), [new opt-in integration](../../../../release/preview_vpn_inbounds.py), [upstream native schemas](https://github.com/MHSanaei/3x-ui/tree/v3.11.0/frontend/src/schemas/protocols/inbound), [AWG pinned module](https://github.com/MHSanaei/3x-ui/blob/v3.11.0/go.mod), [AWG settings](https://github.com/MHSanaei/3x-ui/blob/v3.11.0/internal/amneziawg/types.go), [Xray HY2 schema](https://github.com/XTLS/Xray-core/blob/v26.11.9/infra/conf/hysteria.go).

No panel version change is required for basic native backend support. Embedded AWG uses gVisor and per-peer authenticated SOCKS to Xray; existing standalone AWG uses a host TUN and server tunnel address. Matching wire-library versions does not qualify routing equivalence or preserve an old full client profile by itself.

Changed runtime integration files are a new `release/preview_vpn_inbounds.py` only; existing P0/P1/P3 renderer, API client, migration code and READY schema remain unchanged. Added targeted guards and laboratory acceptance helpers. Installer orchestration is intentionally unchanged until complete installation/repeat/recovery and existing AWG profile compatibility are qualified.

### Management and storage

Uses supported `inbounds/add`, `inbounds/setEnable/:id`, `clients/add`, `clients/update/:email`, `clients/del/:email`; SQLite remains owned by panel. WG/AWG use actual peer keys/AllowedIPs; HY2 uses auth, not a VLESS UUID. Panel settings persist protocol-specific keys. Private utility manifest and SQLite/AWG backups stay root-only, never GitHub. Existing native READY bytes and VLESS settings/identities are compared before/after apply.

An unknown row, existing manifest, reserved port, foreign socket, changed AWG identity/parameter or server MTU fails closed. Only explicit lab mode, private lab marker, RFC1918 bind and explicit handoff permit mutation. Production `--apply` is refused. No automatic rollback or replay of ambiguous side effects.

## B. Six inbounds

Initial laboratory apply created six real native API records, with active UDP29178 WG, UDP29177 AWG3.1, UDP24443 HY2. Ports were selected after observed local TCP/UDP inventory; these are lab choices, not production defaults. Existing VLESS records IDs1/2/3 and native READY were preserved. An inherited unrelated laboratory VLESS fixture was removed only from a new overlay before apply; original VM disk and checkout work remained intact.

| Inbound | Panel UI | Backend | Client management | Final check |
|---|---|---|---|---|
| P0 | Native API record; historical UI accepted | Panel Xray, existing listener | Existing native clients preserved | 65536bytes each direction PASS, counter correlation PASS |
| P1 | Native API record; historical UI accepted | Panel Xray behind Nginx TLS/H2 | Existing native clients preserved | 65536bytes each direction PASS, counter correlation PASS |
| P3 | Native API record; historical UI accepted | Panel Xray REALITY/Vision | Existing native clients preserved | 65536bytes each direction PASS, targeted counter correlation PASS |
| WireGuard | Native record; new visual UI test not run | Native Xray UDP29178 | TCP/UDP, restart, disable/enable, delete/recreate PASS | PASS in first final run |
| AmneziaWG3.1 | Native record; new visual UI test not run | Embedded panel manager UDP29177 | TCP/UDP, restart, disable/enable, delete/recreate PASS | Scoped relay PASS after targeted fixes; old profile routing NOT ACCEPTED |
| Hysteria2 | Native record; new visual UI test not run | Native Xray QUIC/TLS UDP24443 | TCP/UDP, restart, disable/enable, delete/recreate PASS | PASS after targeted fixture/readiness fixes |

## C. Final validation and limits

Historical **318/318 PASS** is reused from [07A](../preview-xonix-07a/test-results.md), not rerun and not counted as new results. Existing 07B local evidence records production READY/native VLESS/AWG acceptance. Older WG/HY2 `PASS_CORE_PAIR` belongs to the historical main worktree branch, `tools/linux_stage06/retained_core.py`, `docs/tests/RETAINED_PROFILES_E2E.md` and `docs/stages/evidence/stage06/retained-core.json`. It tests Xray userspace pairs in controlled fixtures, not this six-inbound panel; no ordinary separate WG/HY2 daemon was adopted.

The one final new-VPN harness initially returned FAIL: WG passed all traffic/lifecycle checks; AWG CLI rejected boolean `false` (requires `on/off` or `0/1`), and HY2 client referenced an ephemeral CA path removed at reboot. These are recorded fixture failures, not hidden successful checks. Targeted correction serializes AWG booleans correctly and uses the persisted managed certificate as explicit trust without disabling verification. Only AWG/HY2 are rechecked; WG history is retained.

TCP payload is 65536 bytes each direction; UDP is sixteen512-byte responses each direction. Laboratory benchmark destination is explicitly redirected through protocol-constrained Xray routing to a controlled namespace origin. This proves the tested proxy/relay path; it does not qualify arbitrary internet egress, provider firewall, ICMP, old standalone AWG server-address routing, all OS clients, or full-tunnel NAT. Production MTU and certificates were not changed. Client MTU1368 remains specific to the earlier measured external path.

### Actual results

- [First final harness](preview08-final-results.json): FAIL retained; WG lifecycle PASS, AWG/HY2 fixture failures as above.
- [Targeted fixture recheck](preview08-targeted-results.json): lifecycle PASS for AWG/HY2; initial/restart still FAIL because harness sampled before runtime/origin readiness and AWG process startup exceeded its10s budget in TCG.
- [Targeted startup/restart recheck](preview08-restart-recheck.json): PASS. Replaced fixed sleeps with observed native state, exact UDP owner PIDs and stable listeners; origin readiness observed; client startup bound30s. Payload/authorization assertions unchanged. Only the failed startup/restart cases were repeated.
- Original P0/P1/P3 smoke: all3 client transfers passed65536bytes each direction; P0/P1 counters passed. Immediate P3 counter sample lagged and subscription-root incorrectly expected XONIX instead of404. Both failures retained in [initial smoke](preview08-existing-initial-results.json).
- [Targeted P3/web smoke](preview08-existing-results.json): P3 counters69437uplink/69917downlink; verified HTTPS main/XONIX, TLS subscription-domain root404, raw/JSON/Clash VLESS subscription responses, Nginx syntax, SQLite integrity`ok`, panel/Nginx/renew timer active, native READY, six API records, OOM0. Subscription smoke verifies fetch/nonempty formats; full cryptographic content validation is reused from07A/07B, not newly claimed for VPN exports.
- [Targeted guards](targeted-tests.log):6/6PASS. AST, relative documentation links, six rule frontmatters and known-production-secret/private-PEM/personal-path scan PASS. [New source hashes](source-sha256.json).

No full historical regression or load test was repeated. New browser UI/canvas interaction, VPN subscription/profile exports and edit/key-rotation lifecycle are NOT_RUN; previous XONIX browser acceptance is reused. All six had actual working backends in this lab, but installer packaging and existing AWG profile preservation remain unaccepted, so the overall stage is INCOMPLETE.

### Production safety

Read-only SSH observed Debian13, native journal READY, exactly three existing VLESS records, AWG UDP29177, active panel/AWG/Nginx. No production mutation command was issued. No production SQLite/inbound/peer, service restart, DNS, SSH, firewall, certificate or READY rollback was performed. Source implementation remains `a3a6b991eb21dc2b4822c4fae13426d91e19db48` per 07B evidence; audit of live state is separate from source provenance.

### Concrete remaining work

1. Qualify existing standalone AWG client profile and server tunnel-address semantics against embedded routing. The old profile routes only the server tunnel address; stopping `xproawg0` removes that address from the host, while embedded gVisor owns it only inside the panel. Benchmark relay traffic does not prove old host-service access. Native `kernelMode:true` instead creates `xui-awg<ID>`, requires a different pinned kernel module3.1.20260906, headers/DKMS and nft/NAT qualification; it cannot simply adopt the old userspace interface. Minimum compatible route: a genuine panel backend adapter preserving the existing userspace TUN/service and implementing peer CRUD, or a separately qualified kernel/host-address migration. Do not bypass lab guards on production. Sources: [kernel manager](https://github.com/MHSanaei/3x-ui/blob/v3.11.0/internal/amneziawgkern/manager.go), [embedded manager](https://github.com/MHSanaei/3x-ui/blob/v3.11.0/internal/amneziawgnet/manager.go), [relay](https://github.com/MHSanaei/3x-ui/blob/v3.11.0/internal/amneziawgnet/relay.go).
2. Integrate the qualified backend into installer provisioning, safe repeat and recovery with separate VPN ownership state, preserving native READY unchanged.
3. Qualify native profile/subscription export, client edit/key changes, visual UI and required common smoke against final installed layout. Current harness verifies fixture profiles and disable/delete/restart, not every subscription format.
4. Produce a pinned backup/preflight/apply command only after these gates. There is no safe production apply command in this revision; inventing one would violate the handoff requirements.

## D. GitHub and repository

Branch `preview/xonix-standalone-debian13`; base `d2d184f9877f3c49fbd2e1987f35ebb5c97e9cb6`; implementation baseline `a3a6b991eb21dc2b4822c4fae13426d91e19db48`. Main before work: `7e822e3e5dfe6f6e95c57fc83b24d00cd7fde661`.

Publication is a laboratory preview/documentation handoff, not a production-stable release. Exact commit/remote verification will be appended after publication. No force push, merge or main mutation is permitted. Existing unrelated untracked evidence was preserved and excluded from this commit.

Structure: root bootstrap/install entrypoints and agent context; `release/` pinned runtime orchestration; `assets/` XONIX; `tests/release/` targeted guards/acceptance; `docs/` architecture/protocols/install/operations/recovery/testing/status/handoff; `.agents/rules/` six scoped rules; `docs/stages/evidence/` preserved history and this report. Dependency attribution/licenses remain in [distribution](../../../../release/distribution/README.md).

## E. Gemini Antigravity

[GEMINI.md](../../../../GEMINI.md), [AGENTS.md](../../../../AGENTS.md), six [.agents/rules](../../../../.agents/rules/architecture.md) and [handoff](../../../ANTIGRAVITY_HANDOFF.md) are prepared. [README](../../../../README.md) links the documentation. Each rule declares supported YAML `trigger: model_decision` and description per [official rules documentation](https://antigravity.google/docs/rules/).

The repository can be studied without the previous chat. Documents explicitly distinguish supported upstream protocols, laboratory integration, default installer and production. They do not claim PREVIEW-XONIX-08 PASS or authorize production changes.
