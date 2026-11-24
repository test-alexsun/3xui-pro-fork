# PREVIEW-XONIX-04B: PASS

Date: 2026-11-20. Branch: `preview/xonix-standalone-debian13`.
Base: `a57fe69404743d14c36f999bc110145565509ac1`. The initial tree was clean.
Historical unified regression source: `f6c478aae0b522a822b83d373dc0dc32182362cc`.

## Architecture

The 04A base had Nginx HTTP on 80 (18080 in test mode) and optional HTTPS
on loopback 18443. The panel accepted HTTP on loopback 2053. The optional
subscription proxy forwarded to a loopback listener verified as belonging to
the panel process. There was no preview stream ingress, XHTTP backend or
provisioned REALITY listener. Candidate AWG used its own configured UDP port
(29177 by default).

| Socket | 04B sandbox role |
| --- | --- |
| TCP 80 | Nginx HTTP and the ACME HTTP-01 challenge location |
| TCP 443, loopback | Nginx stream reads the TLS ClientHello and dispatches by SNI |
| TCP 18443, loopback | Nginx HTTPS/H2 for the site, P1, the separate panel hostname and the optional subscriptions |
| TCP 19440 and 19443, loopback | P0 and P3 distinct Xray REALITY listeners |
| TCP 19441, loopback | P1 Xray XHTTP backend using cleartext HTTP/2 from Nginx `grpc_pass` |
| TCP 19444, loopback | Separate H2/TLS REALITY destination serving a fixed 404 |
| TCP 2053 / 12996, loopback | Panel HTTP and the subscription backend used in the VM |
| UDP 443 / 29177 | UDP 443 unmanaged. AWG continues to listen on 29177. |

The site and panel SNI go to 18443, where a default TLS server rejects unknown
SNI. The site and panel vhosts also check their respective SNI names. P0 and
P3 have different SNI names; Nginx passes their TLS bytes through. Xray ends
REALITY and points its destination at the distinct 19444 cover listener.
There is no cycle to the ingress. PROXY protocol is off on every leg. No
Unix socket is created. P1 uses a certificate explicitly trusted by the
test client. The panel stays on its own HTTPS hostname.

The sandbox copies the historical renderer's `render_pair` and profile
definitions into the standalone preview release. It applies only the
listener changes for the routed topology. The new laboratory Xray service
is separate from the panel runtime. Root-only JSON stores generated profile
credentials. The installer owns and checks digests for its stream include,
service and Xray files. The pre-existing web transaction owns the site
include and XONIX asset. Repeat installation does not regenerate credentials.

## Final verification

| Gate | Result |
| --- | --- |
| Clean Debian 13 installation, Nginx stream and TCP 443 | PASS. All six TCP listeners were checked, and a foreign TCP 443 listener was refused before candidate state creation. |
| P0 REALITY + XHTTP H2 | PASS. Xray client logged HTTP version 2 and transferred 65,536 bytes in each direction. The Xray journal correlated the accepted origin request to P0 and `preview-P0`. |
| P1 TLS + XHTTP H2 | PASS. The pinned client trusted the supplied certificate, offered H2 and logged HTTP version 2. It transferred 65,536 bytes in each direction through the Nginx H2 backend route, with P1 server correlation. |
| P3 REALITY + Vision | PASS. Both sides used the generated Vision profile. A real TLS origin accepted and returned 65,536 bytes in each direction with P3 server correlation. |
| Restart and reconnect | PASS. All three profiles repeated the transfer after restarting the managed Xray service. |
| Panel HTTPS / authenticated API | PASS. Trusted HTTPS login and the authenticated inbound-list API succeeded on `panel.example.test`, including after enabling the subscription route. |
| Subscriptions | PASS. A real panel-created subscription returned its expected synthetic client. An invalid token matched the direct backend 404. An unknown subscription route returned 404. No negative response contained XONIX. The response sent `Referrer-Policy: no-referrer`, and the synthetic token was absent from the checked service logs. |
| XONIX browser smoke / missing panel API | PASS in Chromium 156 on a child of the same installed Debian VM. HTTPS returned the game, JavaScript movement worked, and there were no page errors, external requests or favicon requests. Missing and hidden files were 404 and the challenge directory was not listed. A strict HTTPS request to an absent panel API route returned HTTP 404 without XONIX. |
| ACME sandbox | PASS. A synthetic HTTP-01 file returned its exact contents over TCP 80. |
| UDP listeners | PASS for the VM scope. UDP 443 did not change. Candidate AWG listened on UDP 29177. |
| Repeat installation | PASS. SQLite sentinel and integrity check passed. The AWG configuration, REALITY keys, client UUIDs, Nginx files and foreign sentinel file retained their hashes. Exactly one stream map remained. |
| Nginx failure recovery | PASS. A disposable copy of the installer injected an unknown directive. The actual installer returned an error, restored the old files and configuration, and all three transfers passed again. |
| Unified regression | PASS: 258/258 (245 historical in 376.759 s, 13 preview in 0.247 s). FAIL 0, ERROR 0, SKIP 0, exit 0 for both phases. |
| Syntax and configuration | PASS: Python AST (15 files), Bash syntax (16 files), Node syntax, `git diff --check`, `nginx -t`, pinned Xray `run -test`, five JSON meta-schemas and three historical positive/negative schema tests. |

The VM used Nginx 1.26.3 with the Debian stream module and Xray 26.11.9.
The final transport container check also passed all three profiles, so the
accepted VM result did not depend on the container-only wiring. Xray emitted
its warning about using internal non-443 ports for the REALITY listeners.
The measured transfers reached the TCP 443 ingress. Xray API counters
were not enabled; the driver verified the byte count and server log records.
The installed VM payload matched the worktree (15 files, tarball SHA-256
`e1ae9d1781fdbc24307f5a3443f51d685dbac577f5e8ad9ebfb4f8666814f33d`).
All runtime Python files and discovered preview tests matched the full
regression snapshot.

Reference behavior: [Nginx stream ssl_preread](https://nginx.org/en/docs/stream/ngx_stream_ssl_preread_module.html)
and [Xray console/file log selection](https://raw.githubusercontent.com/XTLS/Xray-core/main/infra/conf/log.go).

## Scope and limits

- Public Let's Encrypt issuance: **NOT_VERIFIED**. ACME renewal:
  **NOT_VERIFIED**. Production deployment: **NOT_VERIFIED**.
- This uses a disposable Debian 13 VM and a generated four-host test certificate.
  The TCP 443 ingress and private backends are bound to the VM loopback. The
  browser runs directly on the loopback of a child of the accepted VM. The test validates the configured certificate for both hostnames using strict TLS and compares the actual certificate seen by Chromium with that exact certificate. Its per-origin exception only applies to the authority error for the verified test peer. The Windows host attempt received a different certificate and was excluded from acceptance.
  Public reachability, production authentication policy and migration from
  existing 04A state are outside this qualification.
- Hysteria2 was not provisioned in the fresh candidate. The installer does
  not change UDP 443 or the AWG backend. AWG remained NAMED. FD_NATIVE and
  destructive recovery were outside this change.
- P0/P1/P3 use independent synthetic Xray client IDs; the panel subscription
  assertion uses a separate synthetic panel-created client. The test verifies
  authenticated subscription delivery, not transport provisioning by the panel.
- `main` and `origin/main` were checked at
  `7e822e3e5dfe6f6e95c57fc83b24d00cd7fde661`.
