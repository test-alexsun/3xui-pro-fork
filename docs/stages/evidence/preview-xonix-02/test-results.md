# PREVIEW-XONIX-02: INCOMPLETE

Date: 2026-11-17. Base main `7e822e3e5dfe6f6e95c57fc83b24d00cd7fde661`;
initial preview HEAD `45af6056a2b30c83114cfe9ba77d4efb66d99d21`.

## Changes and checks

- Selected BUILD-ALL-04 and BUILD-ALL-05A candidate source files, builder,
  relevant test fixtures and their historical evidence were copied from commit
  `f6c478aae0b522a822b83d373dc0dc32182362cc`. Nine operational source files, units and the builder were checked
  byte-for-byte against that commit.
  They remain an isolated candidate, not integration into a standalone
  preview installer. Their historical VM results describe earlier artifacts,
  not a new acceptance run on this preview branch.
- The legacy `x-ui-latest.sh` is disabled at entry on this branch: it exits with
  `INSTALL_DISABLED` before reaching its destructive code. Debian 13 container
  test: `bash -n` and a no-network, read-only, capability-dropped invocation
  passed, confirming exit status 1 and the diagnostic. This guard is not a
  safe replacement installer. Other legacy scripts have not been qualified.
- Debian 13 container, network disabled, read-only tree: both targeted backup
  unit tests passed (live SQLite WAL snapshot, restore rehearsal, tampering and
  unexpected file refusal, external writable descriptor refusal). Python AST
  parsing of eight files, including release modules, builder and test, succeeded, as did
  `bash -n` for the three imported release shell fixtures. These are not a VM
  test of service coordination or interruption on the new branch.
- Previous XONIX local browser and isolated Nginx results are documented in
  `../preview-xonix-01/test-results.md`; they were not rerun for this stage.

## Missing gates

Standalone installer, reproducible dependency distribution, safe repeat
installation and managed atomic Nginx/XONIX configuration with failure
recovery are not implemented. Panel/API, Xray, AWG handshake and service
lifecycle, SQLite and key preservation across repeat install, public TLS,
ACME, fallback, P0/P1/P3 connectivity and browser access through installed
Nginx have not been validated on this branch. Unified regression and JSON
Schema validation were not run. FD_NATIVE was not changed or requalified.

GitHub push and remote verification are NOT_RUN because mandatory acceptance
is incomplete. No GitHub installation command exists or has been tested.
