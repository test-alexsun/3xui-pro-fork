# PREVIEW-XONIX-06A — strict two-domain deployment

Date: 2026-11-23. Branch: `preview/xonix-standalone-debian13`.
Base published HEAD: `c6285d13aa82b37995bf7ba3deda1f183f224e74`.

**PREVIEW-XONIX-06A: PASS.**
Final clean laboratory trial04 and clean GitHub installation published02 both PASS.
Acceptance completed on 2026-11-23 at approximately 05:27 UTC (11:27 Asia/Omsk).
No production installation or public Let's Encrypt request was performed.

## Implemented architecture

| Purpose | Address |
| --- | --- |
| Intended VPS | 179.254.154.126, SSH alias de126 |
| Main domain | de126.alexsun55.ru |
| Subscription domain | de126-sub.alexsun55.ru |
| XONIX | Main domain `/`, exact original offline HTML |
| Panel | Main domain, persistent private base path; native panel authentication |
| HTTPS / P1 VLESS TLS XHTTP H2 | IPv4 TCP 443, Nginx stream -> loopback TLS 18443 -> H2 19441 |
| P0 VLESS REALITY XHTTP H2 | IPv4 TCP 8443, direct Xray listener, main-domain SNI |
| P3 VLESS REALITY Vision | IPv4 TCP 9443, direct Xray listener, main-domain SNI |
| REALITY destination | 127.0.0.1:19444, main-domain TLS1.3/H2, fixed 404 |
| Panel backend | 127.0.0.1:2053 |
| Subscription backend | 127.0.0.1:2096, panel process |
| AWG 3.1 NAMED | UDP 29177, separate owned service |
| HTTP-01 | TCP 80, explicit locations on both names |

Only the two supplied domains are generated as public names in strict mode.
No additional user DNS records or SANs are required. The historical four-name
sandbox remains supported for its old tests and is not a requirement of the new mode.

`--subscription-domain` selects strict mode. New options `--p0-port`,
`--p3-port`, `--subscription-port` and optional `--panel-path` are implemented
and documented. Domain/path/port injection and collisions are rejected.
The initial subscription port is checked before installation; final validation
requires the exact loopback listener to belong to the verified panel PID.

The pinned panel CLI creates a named setup API credential without printing it;
root-only setup state retains it. Supported authenticated API settings configure
the panel base path, loopback subscription backend and explicit URLs for raw,
JSON and Clash formats. SQLite is read-only in the new installer integration;
the panel's own API performs its changes. Account credentials are not reset.

Strict state records both names, bind, ports and panel path. Changed identity,
foreign installation adoption and externally changed managed files/settings are
refused. Existing UUIDs, REALITY/AWG keys, TLS, user data and credentials survive
repeat installation. Binary upgrades and BUILD-ALL-05B remain deferred.

## Laboratory setup

Disposable Debian 13 amd64 systemd VMs use fresh qcow2 overlays of the local
Debian generic cloud image; the base image is not modified. Its SHA256 is
`edd2b3fb9de8bc51b29ff8425716180c8f631f23f6b07f9e288a57bd18701116`.
QEMU WHPX, 2 vCPU and 3072 MiB RAM are used. This is not a capacity test for
production de126's approximately 1 GiB RAM.

An independent client namespace has 10.77.5.2 and the VM ingress 10.77.5.1.
The real intended domain names are mapped only inside the disposable lab.
Isolated dnsmasq defines only the two explicit user-domain records, with no
wildcard substitution or extra panel/P0/P3 aliases. No production DNS is changed.
Pebble runs in the separate client namespace and validates real HTTP-01 over
TCP 80. Test certificates use an explicit private CA; no insecure public TLS
fallback is added to production profiles.

Pebble v2.10.3 official linux-amd64 archive SHA256:
`7e33cf3e426b67e9e647c44e8cc91683caa8ab331f7a99e5e27fcee291c4c7e2`.
Pinned panel 3.11.0, Xray 26.11.9, AWG runtime 3.1.20260828/tools 3.1.20260812
and Debian Nginx 1.26.3-3+deb13u11 are unchanged. Components are fetched through
HTTPS and verified by existing manifest/archive/ELF checks; no binary upgrade is added.

Local diagnostics and private disposable VM data stay under the original worktree's
ignored `.stage06b/preview06a/`. They are not release artefacts and must not be
published wholesale. Only nonsecret gate markers are retained with this evidence.

## Measured acceptance

| Check | Result |
| --- | --- |
| Historical regression | PASS, 245/245, 348.120 s; unchanged f6c478a Git archive, read-only-root Debian Docker, network none, native work/checkpoint volumes |
| Preview regression | PASS, 30/30, including all original 19 and 11 new contracts; historical tests unchanged |
| Unified runner | PASS, `tests/release/run_preview_regression.sh`, both phases exit 0; 275/275 combined |
| Initial two-domain install | PASS on final trial04, including public redirect without internal backend port |
| Exact TLS SAN | PASS: only the two supplied DNS names |
| P0 | PASS: REALITY/XHTTP H2, 65,536 bytes uploaded and downloaded, server inbound correlation |
| P1 | PASS: trusted TLS/XHTTP H2, 65,536 bytes each direction, server inbound correlation |
| P3 | PASS: REALITY Vision, 65,536 bytes each direction, server inbound correlation |
| Xray reconnect | PASS: all three profiles repeat after server restart |
| Panel/API | PASS: protected-path login and authenticated API, secure path-scoped cookies, missing-CSRF rejection, WebSocket 101 |
| Subscriptions | PASS: separate HTTPS hostname, raw/JSON/Clash responses, invalid-token parity, unknown/admin paths 404, no XONIX substitution |
| Token logs | PASS: valid/invalid/unknown-path/query requests do not put the synthetic token in Nginx or panel logs |
| Repeat | PASS: SQLite sentinel/integrity, unchanged managed-key/client/TLS/unit/config hashes, original credentials still authenticate |
| AWG | PASS: handshake and bidirectional UDP, repeat after service restart with fresh client handshake; keys unchanged |
| Pebble renewal/reload | PASS: new certificate, changed Nginx workers, validated deploy hook, exact XONIX over renewed trusted TLS |
| Nginx recovery | PASS: deliberate invalid directive, installer failure, previous owned config restored byte-for-byte; transports and web checks still pass |
| Browser smoke | PASS on both final local and GitHub-installed VMs: Chromium HTTPS, exact trusted lab leaf, canvas/input, offline assets, no external requests/errors, hard 404 paths |
| Public Let's Encrypt / public renewal | NOT_VERIFIED; not requested on this stage |
| Production de126 deployment | NOT_PERFORMED |
| Published commit install | PASS: new pristine Debian 13 VM fetched bootstrap and exact d0cbd985 commit from GitHub; no local source/component seed; all published-install gates completed |

The initial trial exposed a reload-readiness race; the installer now waits a
bounded interval for the correct XONIX response before deciding rollback.
A second trial caught an overly broad conflict check that included the installer's
own newly configured subscription listener; initial and final checks are separated.
Final fixture checks also cover a public panel redirect without internal port
18443, SameSite cookies and actual UUID content in JSON/Clash output.

The first regression invocation omitted the historical guard's required read-only
root and had 1/245 error. The corrected isolated invocation passed all 245; no
historical test or guard was weakened. Existing SQLite ResourceWarning output
is not treated as a failed test. An ordinary Certbot randomized renewal delay
was observed; the final disposable fixture disables only that random sleep.

## Separate security verification

Static compact diff review and independent runtime review found no concrete new
security vulnerability in the scoped changes. The sealed scan is
`67d88cf0-206f-424d-b69c-28e6f8c7a351`; it applies to snapshot
`codex-security-snapshot/v1:sha256:b26ba43068e3d43a1c30116d8f5e4bd6632e22d528d509d1569d88a9952e0aeb`.
A supplemental read-only review covered the later redirect control and strengthened
fixture assertions, with no new security candidate. The sealed scan was not edited.
This is not a new full audit of upstream panel/Xray internals or production.

Live negative gates cover: subscription host cannot serve panel/API or XONIX;
main-root admin paths and sensitive file/key/database paths return 404; wrong
Host/SNI yields 421; unknown SNI fails TLS; unauthenticated REALITY fallback
reaches only cover404; P0/P1 remain H2; tokens are absent from managed request
logs; repeated setup does not rotate account credentials or keys.

## Publication and installation command

Publication is authorized only to `preview/xonix-standalone-debian13`, without
force push or merge. Initial local and remote main:
`7e822e3e5dfe6f6e95c57fc83b24d00cd7fde661`.
Implementation commit: `d0cbd985ff10c2faf4376c7d411c50d47d1b9ee6`. The authorized non-force preview push
was confirmed by `git ls-remote` at that exact SHA. Main remained
`7e822e3e5dfe6f6e95c57fc83b24d00cd7fde661`.
[Published implementation commit](https://github.com/test-alexsun/3xui-pro-fork/commit/d0cbd985ff10c2faf4376c7d411c50d47d1b9ee6).

The initial push used a different saved account and was rejected with 403.
The existing authorized test-alexsun credential was then used only for the push
process; active account/global credential configuration was not changed.
The separate clean published02 VM passed installation, two SANs, all three
transports and reconnect, panel/API/WebSocket/CSRF/cookies/redirect, all three
subscription formats and negative cases, token-log checks, repeat preservation,
AWG restart, Pebble renewal/reload and Chromium smoke. The installer Git
revision and bootstrap hash were checked; mounted client fixtures were compared
byte-for-byte with that same immutable commit. The first published01 attempt
stopped before bootstrap execution because the host ISO generator wrote CRLF
metadata. Correcting only the ignored local generator to LF and using a new
pristine overlay resolved it; published installer code did not change.
The bootstrap file is unchanged; SHA256 remains
`dd0ef3205a9d9864c7778de2f0b5b41c259866c8c31055855b4bee9cd5295fb3`.
No installation command has run on de126.

## Remaining boundaries

- Public Let's Encrypt, provider ACLs TCP 80/443/8443/9443 and UDP 29177, and
  production memory/throughput still need separate deployment acceptance.
- Supply an explicitly authorized ACME email; no address is invented. Repeat
  the `10.88.31.0/30` route/client-overlap check immediately before future installation.
- Fresh panel subscriptions serve panel-created customers. Standalone starter
  P0/P1/P3 client JSON is separate from panel-created inbounds; automatic user
  synchronization between the two Xray processes is not implemented or claimed.
  The subscription fixture creates a synthetic panel client through supported API.
- AWG routes only the server tunnel address; forwarding/NAT/full-tunnel internet
  are outside this installer and were not changed.
- Partial setup requires review of private state; no automatic binary upgrade,
  global rollback, old-mode migration or destructive recovery is implemented.
- Existing unrelated files and the pre-existing untracked PREVIEW-06 report are
  preserved; production services, DNS, SSH and firewall remain untouched.

## Final local snapshot

Final lab trial04 bundle SHA256: `684f264c6ed9839632bfe2a7f4ec0f9bfc3971d81d76ae7af2483665a1f2d0d9`.
All four changed runtime source files were compared byte-for-byte with the installed lab input.
Final redirect delta preview regression: 30/30 PASS in 7.638 s. The separate historical
245-test source is unchanged by that delta; the unified runner had both phases exit 0.
The obsolete trial03 was stopped after its non-browser gates, to release RAM on
the approximately 8 GiB host; it is not used to claim final browser acceptance.

## Prepared immutable GitHub installation command

The bootstrap is unchanged. Production execution still requires separate authorization,
provider-port verification, a fresh subnet-overlap check and an operator email.
This command uses only the two supplied domains.

```sh
# Future authorized installation on de126, as root, in a clean directory.
# Replace the email placeholder; this command has NOT run on production.
umask 077
curl -fsSL 'https://raw.githubusercontent.com/test-alexsun/3xui-pro-fork/d0cbd985ff10c2faf4376c7d411c50d47d1b9ee6/bootstrap-preview.sh' \
  -o bootstrap-preview.sh && \
printf '%s  %s\n' 'dd0ef3205a9d9864c7778de2f0b5b41c259866c8c31055855b4bee9cd5295fb3' bootstrap-preview.sh | sha256sum -c - && \
TMPDIR=/var/tmp sh ./bootstrap-preview.sh d0cbd985ff10c2faf4376c7d411c50d47d1b9ee6 \
  --public-bind '179.254.154.126' \
  --domain 'de126.alexsun55.ru' \
  --subscription-domain 'de126-sub.alexsun55.ru' \
  --p0-port 8443 --p3-port 9443 \
  --acme-email '<USER_LE_EMAIL>' \
  --awg-subnet '10.88.31.0/30'
```

## Header and production boundaries

Host/SNI isolation, generated HTTPS forwarding headers, secure cookies,
CSRF and authenticated WebSocket behavior passed the scoped checks. As in the
prior stream architecture, the stream-to-loopback-TLS leg does not carry PROXY
protocol: the HTTP backend sees the loopback peer address. Original public-client
IP audit/allowlist semantics are not qualified here and must not be assumed.
This does not replace the panel's tested authentication/CSRF controls.

Only evidence/guide text is updated after the tested implementation commit.
The pre-existing untracked PREVIEW-06 report remains local and is not included
in publication. Main stays unchanged. Production remains untouched.
