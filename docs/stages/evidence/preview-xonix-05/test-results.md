# PREVIEW-XONIX-05: INCOMPLETE

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
| GitHub bootstrap | Implemented; syntax checked. Fresh install from a published SHA is pending. |
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

Prepublication acceptance passed on 2026-11-20. An independent clean Debian VM will verify the published GitHub installer. The overall result remains incomplete until that run succeeds.

References: [Certbot webroot and deployment hooks](https://eff-certbot.readthedocs.io/en/stable/using.html),
[Let's Encrypt HTTP-01](https://letsencrypt.org/docs/challenge-types/).
