# PREVIEW-XONIX-03: INCOMPLETE

Date: 2026-11-17. Branch: `preview/xonix-standalone-debian13`.
Starting HEAD: `4d39991d5345e9bf6c748515a8b8b5c4c89e5561`.

## Implementation

An experimental `install-preview.sh` delegates to `release/preview_install.py`.
It accepts `--domain`, `--components` (an already unpacked pinned candidate),
`--awg-subnet`, and optional `--test-mode`. It verifies component hashes,
versions, executable ELF architecture, and candidate helpers against local
source, and uses the existing fresh installer or read-only installed-tuple
inspection. It installs nginx and iproute2 if absent. It manages a dedicated
HTTP server block and XONIX file, backs up owned previous files privately, uses
atomic file replacement and file/directory fsync, validates and reloads nginx,
and checks the resulting HTTP page. Its state refuses ambiguous or modified
managed files. It has no automatic binary update and no production rollback.

## Current tests

- Debian 13 QEMU disposable VM with fresh overlay, user-mode networking for
  Debian packages, pinned prebuilt candidate unpacked from local fixture:
  the installer installed nginx itself; panel and AWG systemd units became
  active; the `xproawg0` interface had the expected address; the Xray version
  was 26.11.9 and its executable was observed as a live process. Panel login
  and authenticated inbounds-list API passed on loopback. XONIX bytes were
  served on HTTP port 80 for the test domain and the file was root:root 0644.
- Same VM: a second invocation passed, the AWG server and client file hashes
  matched, a SQLite sentinel row and a user file remained intact, both services
  were active and exactly one managed nginx config was present. This does not
  demonstrate preservation of arbitrary databases, inbounds or external sites.
- Same VM: injected invalid nginx configuration caused `nginx -t` to fail;
  the previous config was restored and checked, nginx reloaded, the prior XONIX
  HTTP response was checked, and both candidate services remained active.
  Markers: `PREVIEW03_PANEL_API_PASS`, `PREVIEW03_XRAY_PROCESS_PASS`,
  `PREVIEW03_REPEAT_PASS`, `PREVIEW03_CONFIG_RECOVERY_PASS`, `PREVIEW03_VM_PASS`.
  Private local serial log: `.stage06b/xonix-browser/preview03v2-serial.log`
  in the original worktree; it is not a release artifact.
- An earlier independent VM also passed using `--test-mode` on port 18080.
- After the port-80 VM run, the only executable change was an added explicit
  `RECOVERY_REQUIRED` error message for failure on the first web publication;
  that specific change was covered by the targeted tests below, not by a new VM.
- Debian 13 Docker, no network, read-only tree and dropped capabilities:
  four targeted unittest cases passed, covering repeated owned publication,
  refusal of unowned paths and conflicting server names/listeners, simulated
  invalid configuration and simulated reload failure, and the first-install
  recovery-required state. Reload failure was mocked, not induced in the VM.
- Python AST and Bash syntax checks: PASS. `git diff --check`: PASS for tracked changes; new files were checked separately with `git diff --no-index --check`.

## Remaining acceptance gaps

The public Nginx server currently serves only XONIX and 404s; panel/API,
subscription, ACME, XHTTP and REALITY/fallback routes are not integrated for
this virtual host. Existing same-domain or ambiguous server names are refused.
No TLS is configured, and TLS, transport compatibility and production readiness
are NOT_VERIFIED. The VM exercised an empty newly installed panel: preservation
of existing UUIDs/REALITY keys and arbitrary existing service configurations,
real update of changed XONIX bytes and end-to-end live AWG traffic were not
retested. Domain DNS, dual-stack listener conflicts, process interruption at
each web transaction boundary and hostile concurrent changes remain unqualified.
The locally supplied component candidate is not a published GitHub artifact.
No GitHub entrypoint or one-command installation from GitHub is available.
No push, merge, or production deployment was performed. FD_NATIVE unchanged.
