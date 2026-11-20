# XONIX preview installer

This preview targets Debian 13 amd64 with systemd. See
[standalone installation and IPv4 mode](#standalone-components-and-ipv4-mode)
for the release-candidate installation, or use the isolated sandbox options
below for local qualification. The former `x-ui-latest.sh` installer
remains disabled. Production deployment requires separate qualification.

## Local HTTP preview

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

The 18443 sandbox does not use SNI stream routing or manage TCP/UDP 443.
Use the separate loopback TCP 443 mode below for P0/P1/P3. See
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

## Optional loopback TCP 443 transport sandbox

Use a **fresh disposable Debian 13 VM**. This mode needs the existing sandbox
TLS flags and an explicitly trusted test certificate. Its SANs must cover the
site, `panel.<domain>`, `p0.<domain>` and `p3.<domain>`. Use a root-owned
certificate and a root-only key.

```sh
sudo bash install-preview.sh --domain example.test --test-mode \
  --sandbox-transports --sandbox-tls-cert /path/to/test-cert.pem \
  --sandbox-tls-key /path/to/test-key.pem \
  --components /path/to/unpacked-candidate --awg-subnet 10.88.31.0/30
```

| Route | Listener and backend |
| --- | --- |
| HTTP and HTTP-01 fixture | TCP 80, Nginx site with separate ACME location |
| Shared TLS ingress | `127.0.0.1:443`, Nginx stream reads SNI |
| P0 | `p0.<domain>` passes through to Xray at `127.0.0.1:19440` (REALITY + XHTTP H2) |
| P1 | Site SNI terminates TLS/H2 in Nginx at `127.0.0.1:18443`. `/xhttp/` uses HTTP/2 cleartext to Xray at `127.0.0.1:19441`. |
| P3 | `p3.<domain>` passes through to Xray at `127.0.0.1:19443` (REALITY + Vision) |
| XONIX / panel | Site and `panel.<domain>` have distinct HTTPS vhosts. The panel proxy goes to `127.0.0.1:2053`. |
| REALITY destination | Separate Nginx H2/TLS endpoint at `127.0.0.1:19444`, with a fixed 404 response |
| UDP | The transport sandbox does not use UDP 443. Candidate AWG retains its own UDP listener, normally 29177. |

The HTTPS router rejects unknown SNI in a default TLS vhost. The website and
panel vhosts also check SNI against their respective names. No leg of this
sandbox adds a PROXY protocol header. P1 uses loopback TCP throughout and
does not create a Unix socket.

The installer installs the Debian stream module as needed and owns one stream
include under `/etc/nginx/modules-enabled/`, one HTTP include under
`/etc/nginx/conf.d/`, and `3xui-preview-xray.service`. It refuses an occupied
transport TCP listener on initial installation, and it does not adopt an
existing stream context. Debian's normal `nginx -t` includes both managed
files. Routing is tested over loopback; the installer does not configure a
public IPv4/IPv6 listener, firewall, Hysteria2 or ACME renewal.

The dedicated Xray service stores its generated configuration and client
profiles in root-only JSON under `/var/lib/3xui-pro-fork/`. These laboratory
identities are separate from the panel database. Repeating the same
invocation checks ownership and keeps the generated keys and client UUIDs.
Client profiles connect to loopback TCP 443 and P1 verifies the supplied
certificate. Keep these files private. Existing 04A state on HTTP 18080
requires a separate migration and is outside this fresh-install mode.

The optional subscription routes still require explicit existing panel
settings and a verified loopback backend. Configure the base URL for each
enabled format as `https://<domain>/<configured-path>/` and repeat the command
with `--sandbox-subscriptions`. The older 18443 sandbox mode continues to
require its original explicit port in configured subscription URLs.

For a browser smoke inside the installed disposable VM, run
`tests/xonix/preview04b-browser.cjs` with the HTTPS URL and test certificate
path. It strictly validates the certificate for the site and panel hostnames
and compares it with the certificate Chromium received. The script requires
Node.js and `playwright-core` and uses the installed Linux Chromium unless
`CHROME_PATH` points to another executable.

See [the 04B test report](stages/evidence/preview-xonix-04b/test-results.md)
for the transport, web and repeat-install evidence and its limits.

## Standalone components and IPv4 mode

The installer supports Debian 13 amd64 with running systemd. With no
`--components` argument it obtains the official upstream panel 3x-ui
v3.11.0 and Xray v26.11.9 archives over HTTPS, checks the pinned archive
hashes, and validates Linux amd64 ELF headers and the pinned hashes of
the executables and geodata. It extracts amneziawg-go v3.1.20260828 and
AWG tools v3.1.20260812 from the checked-in AWG distribution and checks
both the package SHA-256 and each binary SHA-256. See
[distribution provenance and licenses](../release/distribution/README.md).
The public Nginx, Nginx common and stream packages are pinned to Debian
Security version `1.26.3-3+deb13u11`. The installer checks each downloaded
DEB�s SHA-256 and package metadata and refuses a different installed
version. Certbot and other system dependencies come from configured
signed Debian APT repositories. XONIX and the units
come from the selected Git revision.

The repository includes `bootstrap-preview.sh` for a verified GitHub
revision. It verifies Debian 13, amd64 and root, obtains Git and Python
from Debian if missing, fetches the exact Git object, checks its commit
SHA, and forwards options to `install-preview.sh`. A candidate stays
unpublished until its required isolated acceptance passes. Use the
GitHub command from the release evidence once that evidence includes a
verified remote SHA.

For an initial IPv4 installation, use a directly assigned public address and
create A records for the site, `panel.<domain>`, `p0.<domain>` and
`p3.<domain>`, all pointing exclusively to that address. This mode supports
a single direct IPv4 and refuses conflicting or AAAA answers. Ensure TCP 80
and 443 and the selected AWG UDP port (default 29177) can reach the VPS.
The installer does not edit host firewall rules, NAT or existing UDP 443
configuration. Foreign transport listeners and a foreign Nginx stream
context are refused.

`--public-bind IPV4 --domain DOMAIN --acme-email EMAIL --awg-subnet CIDR`
selects this mode. The installer brings up HTTP-01 first, checks that
each requested name serves a challenge through Nginx, and runs Certbot
webroot issuance for all four names with an isolated configuration at
`/var/lib/3xui-preview-acme`. Failure leaves the HTTP-only preview and
withholds the HTTPS transport configuration. Normal public mode uses
Let's Encrypt. The custom private ACME flags require a private directory,
non-public address and an explicit root-owned test CA. They are for
disposable testing only. This mode allows Xray to reach only its
controlled test origin at the private ACME peer on TCP 18099 in addition
to the normal public egress. Normal mode retains Xray�s default private
destination protection.

The public ingress binds only the specified IPv4. Internal TLS (18443),
the separate REALITY P0/P3 targets (19440 and 19443), XHTTP cleartext H2
(19441), the REALITY destination (19444) and the panel (2053) stay on
loopback. The site remains separate from the panel vhost. P0/P1/P3 client
JSON is root-only and keeps its UUIDs and REALITY keys on repeat installs.
P1 uses the client's normal certificate trust. UDP 443, P2 H3, P4 PQ and
Hysteria2 are not provisioned by this standalone command. AWG keeps its
existing separate NAMED service. FD_NATIVE and destructive recovery are
outside this mode.

Enable subscription proxying by first configuring the panel's verified
loopback subscription backend and base URLs as in the TCP 443 sandbox,
then rerunning with `--public-subscriptions`. The installer only reads
panel subscription settings. Repeat with the same bind, domain and mode.
Unsupported binaries and upgrades are refused. Ownership checks protect
the existing site, state and transport files, and the web transaction
keeps private backups under `/var/lib/3xui-pro-fork/preview-web-backups`.

`3xui-preview-renew.timer` runs the isolated Certbot renewal service. Its
deploy hook runs `nginx -t` before reloading Nginx. It does not manage
existing Certbot lineages under `/etc/letsencrypt`. If the installer
reports that an earlier configuration was restored, inspect the Nginx
journal and the private backup. Do not remove unfamiliar files or treat
`RECOVERY_REQUIRED` as proof of a successful rollback.

```sh
systemctl status nginx 3xui-preview-xray 3xui-pro-fork 3xui-pro-fork-awg
systemctl list-timers 3xui-preview-renew.timer
journalctl -u nginx -u 3xui-preview-xray -u 3xui-preview-renew
nginx -t
```

[Release-candidate evidence](stages/evidence/preview-xonix-05/test-results.md)
records the lab results. Public Let's Encrypt issuance, public renewal
and production deployment require separate verification.
