# XONIX preview: incomplete

This branch contains an experimental local installer, not a release. Do not
use it on a production server. There is no published or verified GitHub
installation command. The former `x-ui-latest.sh` installer remains disabled.

In a disposable Debian 13 amd64 system with systemd and TUN support, with an
independently verified BUILD-ALL-05A candidate already unpacked into a local
directory, the implemented invocation is:

```sh
sudo bash install-preview.sh --domain example.test \
  --components /path/to/unpacked-candidate --awg-subnet 10.88.31.0/30
```

Choose a non-conflicting dedicated private /30; the example domain is for an
isolated test. `--test-mode` uses port 18080 rather than port 80. The installer
verifies the pinned component manifest and binary hashes and checks its
candidate helper files against the local release sources. It can install
missing nginx and iproute2 packages via Debian apt. It refuses existing
unowned web files, ambiguous server names and non-Nginx listeners. It does not
perform binary upgrades. A nonterminal web state requires manual review.

The original offline game is `assets/decoy/xonix/index.html`; the managed web
copy is `/var/www/3xui-pro-fork/decoy/index.html`, and its root-owned Nginx
server block is `/etc/nginx/conf.d/3xui-pro-fork-preview.conf`. Prior owned
versions are saved under `/var/lib/3xui-pro-fork/preview-web-backups`.
Browser high scores use localStorage and are separate for each browser origin.

The default experimental server is HTTP-only. It does not configure public
TLS, ACME issuance, public panel/API, subscriptions, XHTTP, REALITY or fallback routes. It does not
configure firewall or NAT. The panel is bound to loopback; its initial
credentials appear in the root-readable service journal. AWG is a separate
NAMED service; FD_NATIVE is not enabled. The installation procedure, repeat
checks and recovery limitations are described in
`docs/stages/evidence/preview-xonix-03/test-results.md` and
`release/README-CANDIDATE.md`.

Useful diagnostics on a disposable test system:

```sh
systemctl status 3xui-pro-fork.service 3xui-pro-fork-awg.service nginx
journalctl -u 3xui-pro-fork.service -u 3xui-pro-fork-awg.service -u nginx
nginx -t
```

Backups can contain private data. A `RECOVERY_REQUIRED` result is not proof of
successful recovery; preserve the existing files and inspect their state before
any manual action. Full project upgrade and rollback are not implemented.

## Optional isolated HTTPS sandbox

For an isolated VM only, supply both `--sandbox-tls-cert /absolute/cert.pem`
and `--sandbox-tls-key /absolute/key.pem` together with `--test-mode`. The
certificate must be root-owned; its private key must also be root-only. The
installer does not generate or renew certificates. Sandbox HTTP listens on
port 18080 and HTTPS binds only `127.0.0.1:18443`. The site host serves XONIX;
`panel.<domain>` proxies the panel to its loopback listener with WebSocket
headers. The sandbox serves existing HTTP-01 test tokens beneath
`/var/www/3xui-pro-fork/decoy/.well-known/acme-challenge/`; it does not issue
a certificate. A self-signed sandbox certificate was used in the VM test.

Do not mistake this sandbox for the intended public SNI-stream architecture.
TCP 443 and UDP 443 are not managed by this integration; REALITY, P0/P1/P3,
subscription routes and public TLS remain unverified. See
`docs/stages/evidence/preview-xonix-04/test-results.md` for current results.

## Optional sandbox subscription proxy

When sandbox HTTPS is already configured, `--sandbox-subscriptions` adds
explicit Nginx locations for enabled subscription formats using the panel's
existing settings, without updating its SQLite database. The subscription
backend must be enabled, explicitly bound to `127.0.0.1`, use plain HTTP
locally, and already be running in the verified panel process. The panel must be configured with the exact
sandbox subscription base URL `https://<domain>:18443/<configured-path>/`
for each enabled format. The installer refuses missing, ambiguous, conflicting
or differently configured values; configure the panel deliberately before
re-running it with this option. Subscription tokens are bearer secrets and
must not be pasted into logs, reports or public issue trackers. Nginx disables
access logging for the managed subscription locations.

The game includes an embedded favicon to prevent a browser request for the
missing `/favicon.ico`; its gameplay is unchanged. This remains an isolated
sandbox. Public 443 routing, REALITY, XHTTP and production TLS are not
implemented by this option. See
`docs/stages/evidence/preview-xonix-04a/test-results.md` for the actual scope
of the current tests and any outstanding failures.
