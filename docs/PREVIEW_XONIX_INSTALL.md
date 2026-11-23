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
DEB SHA-256 and package metadata and refuses a different installed
version. Certbot and other system dependencies come from configured
signed Debian APT repositories. XONIX and the units
come from the selected Git revision.

The repository includes `bootstrap-preview.sh` for a verified GitHub
revision. It verifies Debian 13, amd64 and root, obtains Git and Python
from Debian if missing, fetches the exact Git object, checks its commit
SHA, and forwards options to `install-preview.sh`.

## Strict two-domain public deployment

The new public deployment mode uses exactly two user-provided hostnames. For
the de126 deployment these are `de126.alexsun55.ru` and
`de126-sub.alexsun55.ru`, both with a single A record `179.254.154.126` and
no AAAA answer. Additional panel/P0/P3 DNS records and SANs are not required.
The earlier four-host sandbox remains available for historical qualification;
its derived hostnames are not requirements of strict mode.

| Purpose | Address |
| --- | --- |
| VPS | 179.254.154.126 |
| XONIX | https://de126.alexsun55.ru/ |
| Panel | https://de126.alexsun55.ru/<private-base-path>/ |
| Subscriptions | https://de126-sub.alexsun55.ru/{sub,json,clash}/<token> |
| HTTPS / P1 VLESS TLS XHTTP H2 | TCP 443 |
| P0 VLESS REALITY XHTTP H2 | TCP 8443 |
| P3 VLESS REALITY Vision | TCP 9443 |
| AWG 3.1 NAMED | UDP 29177 |

`--subscription-domain DOMAIN` enables strict mode and automatic subscription
backend setup. It requires `--public-bind IPV4 --domain DOMAIN --acme-email EMAIL
--awg-subnet CIDR`; do not combine it with the older `--public-subscriptions`
flag. `--p0-port` and `--p3-port` default to 8443/9443. The optional
`--subscription-port` is a loopback-only backend, default 2096. Ports must be
unique, unprivileged and outside reserved project/system ports. Conflict checks
run before fresh component installation.

`--panel-path /PRIVATE_SEGMENT/` is optional: one safe segment of 16–80
characters. By default the installer generates a random private base path and
retains it in root-only `/var/lib/3xui-pro-fork/preview-panel.json`. Read only its
`layout.panel_path` field locally as root when finding the panel URL. The file
also holds a privileged setup credential; do not publish it. The panel uses its
supported webBasePath mechanism, native login/CSRF/cookie path and WebSocket route.
Nginx preserves the full path, forwards only the intended prefix, sets secure
cookie flags and forwards HTTPS headers. Administrative paths at the site root
or the subscription hostname return hard errors. A private path complements
normal authentication; it does not replace it. Initial account credentials
remain in the root-readable panel service journal, as in the earlier preview.

Only the two specified names enter ACME HTTP-01 and the certificate SAN list.
Nginx stream listens at the chosen IPv4:443 and sends both HTTPS names to
127.0.0.1:18443. Unknown SNI is rejected by the default TLS vhost, and Host/SNI
mismatches are rejected. P1 `/xhttp/` uses Nginx TLS/H2 followed by cleartext H2
to Xray at 127.0.0.1:19441. P0/P3 listen directly at the chosen IPv4:8443/9443;
both REALITY serverNames/client SNI use the main domain. The separate local
REALITY TLS1.3/H2 destination is 127.0.0.1:19444, covers the main domain and
returns 404 without exposing panel or subscription routes. No third domain or
unproved SNI multiplexing is used. There are no PROXY protocol headers.

The installer configures its freshly owned panel through the pinned panel CLI
and authenticated API. It sets the panel base path and domain, enables the
loopback HTTP subscription backend and the three existing formats with explicit
HTTPS base URLs on the subscription domain. It does not write panel SQLite
settings directly, reset account credentials or import/delete existing users.
The subscription vhost has no game or administrative proxy. Unknown paths and
invalid tokens return backend/404 responses. Access logging is disabled for the
entire managed HTTP/HTTPS vhosts, including invalid paths/queries, with error
request logging suppressed. Referrer-Policy is no-referrer and subscription
responses are not cached.

The fresh panel has no customer clients. Add clients through the authenticated
panel API/UI; the backend generates their subscriptions. The standalone
P0/P1/P3 starter profiles remain root-only in `preview-xray-clients.json` and
are managed separately from panel-created inbounds. This preview does not
silently import these standalone inbounds into the panel's Xray process or
claim automatic user/configuration synchronization between the two processes.

On repeat use identical domains, bind, ports and panel path. UUIDs, REALITY/AWG
keys, account credentials, TLS lineage and managed files are preserved. Changing
identity, externally editing managed files/settings or adopting an old-mode
installation is refused. A nonterminal setup state requires manual inspection;
there is no automatic binary upgrade or complete project rollback. Existing
unowned Nginx configurations and foreign transport listeners are not adopted.
BUILD-ALL-05B remains deferred.

Certbot uses isolated config/work/log directories under
`/var/lib/3xui-preview-acme`, cert-name `3xui-preview`, and
`3xui-preview-renew.timer`. The deploy hook runs `nginx -t` before reload.
Existing `/etc/letsencrypt` lineages are not modified. Failure can retain the
HTTP-only preview and private recovery state; RECOVERY_REQUIRED is not proof of
successful rollback. Public Let's Encrypt issuance/renewal and production
acceptance are separate from Pebble laboratory qualification.

The installer does not change SSH, DNS, host/provider firewall, forwarding or
NAT. Before a future authorized deployment verify TCP 80/443/8443/9443 and UDP
29177 with the provider, repeat the /30 overlap check, supply the operator's
ACME email, and assess memory under the intended load. The previous de126
preflight found about 1 GiB RAM, no swap and a memory-backed /tmp; use
`TMPDIR=/var/tmp` for bootstrap/component scratch space. AWG's starter client
routes only the server tunnel address, not a full-tunnel internet gateway.

Installation command and measured acceptance results are recorded in
[PREVIEW-XONIX-06A evidence](stages/evidence/preview-xonix-06a/test-results.md).
Use its exact immutable commit and bootstrap checksum after qualification;
never substitute a floating branch or main. No production deployment is
performed by the documentation or by the laboratory test.
