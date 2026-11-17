# XONIX preview: incomplete

This local preview branch is not an installer or a release. There is currently
no verified GitHub installation command and no supported domain argument. Do
not use the legacy installer: it previously removed existing Nginx site
configuration and is now disabled at entry in this preview branch.

The original offline XONIX page is at `assets/decoy/xonix/index.html`.
Browser high scores use localStorage and are separate for each browser origin.
The Nginx fragment next to it is a test candidate only; it is not wired into an
installer and is not qualified against actual panel, subscription or transport
routes. It must not be applied to a running server as-is.

The intended destination is `/var/www/3xui-pro-fork/decoy/index.html`; only an
isolated fixture has exercised root ownership, directory mode 0755 and file
mode 0644. Safe site updates, backups, rollback after a failed Nginx reload,
DNS, public TLS/ACME, Xray fallback and domain configuration remain to be
implemented and verified. Panel, Xray and AWG service setup, operation and
logs are not qualified on this branch. See the stage test results for exact
evidence and remaining gates.

The imported BUILD-ALL-04/05A code is a scoped test candidate only. It is not
integrated into a standalone installer; see `release/README-CANDIDATE.md` and
`docs/stages/evidence/preview-xonix-02/test-results.md` for limitations.
