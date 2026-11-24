# PREVIEW-XONIX-05: PASS

Date: 2026-11-20. Branch: `preview/xonix-standalone-debian13`.
Base: `88b0f25fcd666914524c7c2d0c915a8d678e1537`. Initial worktree was clean.
Local and GitHub main were checked at `7e822e3e5dfe6f6e95c57fc83b24d00cd7fde661`.
The initial GitHub lookup returned no preview ref. Publication is gated on
the new mandatory acceptance.

## Release work

- Added a bootstrap that fetches and verifies a chosen commit from the
  specified GitHub repository, then invokes the standalone installer.
- Standalone component acquisition validates the upstream archive hashes,
  the pinned AWG payload, the extracted binaries and the ELF architecture.
  The AWG source archives, build recipe and license files accompany the payload.
- The IPv4 mode binds the Nginx stream inlet to the requested address and
  keeps the P0/P1/P3, panel and TLS backends on loopback. It leaves
  the existing UDP 443 configuration alone and keeps the AWG service.
- Certbot uses a separate lineage and a managed renewal timer. Its deploy
  hook runs Nginx configuration validation before reloading the service.
  No live public certificate or production installation was requested.

## Observed checks

| Gate | Result |
| --- | --- |
| Standalone component acquisition | PASS in a Linux container with live HTTPS downloads and no local component staging. All six files matched the verifier. |
| GitHub bootstrap | PASS. A second clean VM downloaded the published bootstrap, validated its checksum and ran the pinned Git revision. |
| Unified regression | PASS on the pinned release inputs. 264 detected, 264 passed, zero failures, zero skips, exit 0. Historical 245/245 and preview 19/19 both exited 0. |
| Legacy installer | PASS. Install and uninstall exit before the disabled legacy body. |
| Syntax and whitespace | PASS. Bash syntax, Python AST (20 files), browser JavaScript syntax and Git diff check. |
| JSON Schema | PASS, 5 meta-schemas and 3 historical schema tests with pinned offline dependencies. |
| Clean systemd install and external ingress | PASS on the pinned snapshot in a disposable Debian 13 amd64 systemd VM. The installer obtained the panel and Xray upstream artifacts and unpacked its verified AWG distribution. The pinned Debian Nginx packages, `nginx -t` and `xray run -test` passed. The client used the separate 10.77.5.2 namespace and connected to 10.77.5.1. |
| External P0/P1/P3 | PASS on the pinned VM, 65,536 bytes each way with tagged Xray journal correlation and reconnect after Xray restart. P0 and P1 used H2. |
| HTTPS panel API, subscriptions and XONIX response | PASS on the pinned VM. The separate namespace completed authenticated API access, retrieved a live synthetic subscription and obtained the exact XONIX HTML over trusted TLS. Invalid token and unknown subscription paths returned 404. Referrer-Policy and token redaction checks passed. |
| ACME HTTP-01 | PASS on the pinned VM. Pebble issued a certificate for the site, panel, P0 and P3 names via HTTP-01. |
| Repeat install and state preservation | PASS. The repeat kept the SQLite sentinel and database integrity, REALITY keys, client UUIDs, AWG keys, Nginx/TLS, all managed units and the unrelated site and Nginx files. One SNI map remained. |
| AWG 3.1 NAMED E2E | PASS. The systemd service recreated its interface. The separate client completed a handshake and exchanged request/reply UDP before and after service restart with fresh client handshake. Both key-bearing files had unchanged SHA-256. |
| Pebble renewal and reload | PASS. The managed timer was active and both unit files passed `systemd-analyze verify`. Forced renewal issued a different certificate. The configured deploy hook validated Nginx before reload, workers changed, and the external HTTPS client received XONIX with the renewed chain. |
| Nginx failure recovery | PASS. An invalid directive in a disposable source copy caused installer failure, restored the owned Nginx configuration byte for byte, and preserved the P0/P1/P3 data path. |
| Chromium XONIX browser smoke | PASS from the isolated client with Chromium and the verified Pebble chain. Canvas and input worked, there were no external calls or browser errors, and the favicon and blocked routes passed. |
| Public Let's Encrypt issuance, real public renewal, production deployment | NOT_VERIFIED. |

The Nginx packages from the working VM were independently downloaded
from Debian Security and checked. The public mode now pins and verifies
the version, archive SHA-256 and DEB metadata of Nginx, nginx-common and
libnginx-mod-stream. Generated Nginx and both Xray configurations passed
`nginx -t` and `xray run -test` in an isolated container before the
package pin was added. The accompanying AWG executables reported the
declared userspace and tools versions.

Earlier VM trials stopped in fixture setup. Pebble needed an explicit
executable mode and a longer bounded startup window to generate its CA
under emulation. The first AWG fixture also retained its pre-restart client session and timed out. The final fixture explicitly reconnects a fresh test client. Automatic recovery of an existing session was not established.

## Published GitHub install

Release commit `d5376fc699f02bee673ecc8927ca9489b453b757` was pushed to
`origin/preview/xonix-standalone-debian13`. The local commit and `git ls-remote`
agreed immediately after publication. The remote and local `main` both
remained `7e822e3e5dfe6f6e95c57fc83b24d00cd7fde661`.

A new disposable VM booted from the pristine Debian 13 generic cloud image.
The read-only fixture supplied only the test client, ACME CA and comparison
data. The VM downloaded `bootstrap-preview.sh` from GitHub Raw, checked
SHA-256 `dd0ef3205a9d9864c7778de2f0b5b41c259866c8c31055855b4bee9cd5295fb3`,
and ran it as root against the published commit. Neither the checkout nor
the component bundle was seeded. Both the initial and repeat installer
invocations fetched the same pinned commit through GitHub.

| Published install gate | Result |
| --- | --- |
| GitHub bootstrap and Debian 13 fresh install | PASS. Exact Git revision, pinned archives, active Nginx, panel, Xray and AWG services. |
| External P0/P1/P3 | PASS. Each transport exchanged 65,536 bytes in both directions, matched its server inbound and reconnected after Xray restart. |
| Panel API, subscriptions and XONIX over HTTPS | PASS from the separate client, including Chromium smoke. |
| Repeat install and AWG restart | PASS. The synthetic SQLite sentinel, UUIDs, AWG and REALITY keys, TLS, units and user site survived. AWG used a fresh client handshake after service restart. |
| Pebble HTTP-01, renewal and Nginx reload | PASS. New certificate verified over external HTTPS after the configured hook. |

The command with public parameters is in the
[installation guide](../../../PREVIEW_XONIX_INSTALL.md). The VM used the
same GitHub path and release SHA with `--public-bind 10.77.5.1`,
`--domain example.test`, `--acme-email rc-test@example.test`,
`--awg-subnet 10.88.31.0/30` and the private Pebble directory and CA.
Public Let's Encrypt issuance, public renewal and production deployment
remain `NOT_VERIFIED`.

References: [Certbot webroot and deployment hooks](https://eff-certbot.readthedocs.io/en/stable/using.html),
[Let's Encrypt HTTP-01](https://letsencrypt.org/docs/challenge-types/).
