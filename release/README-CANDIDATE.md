# Candidate only — not a release

This candidate contains the pinned panel, Xray and AWG executables. It does not
implement a safe upgrade or rollback or the required ordinary WireGuard inbound.
The separate AWG service and fresh installer passed a scoped disposable Debian
13 systemd VM test; this is not production qualification. Do not deploy it to a
production host.

The candidate installer is fresh-install only and refuses known existing panel
paths. It requires `--awg-endpoint` and `--awg-subnet` (an unused RFC1918 /30),
with optional `--awg-port` (default 29177). It binds the panel to loopback and
creates the separately managed AWG endpoint; it does not add an AWG inbound to
the panel UI. It is not restartable after a failed
partial installation and does not delete files on failure. It does not
configure TLS, firewall or a reverse proxy. The upstream panel prints the first
login to the service journal: access to that journal must be restricted.
`--mode inspect-upgrade` performs read-only checks against the exact known
BUILD-ALL-04 tuple and systemd service state. It does not authorize or perform
an upgrade. `--mode prepare-upgrade --health-credentials /root/health.json`
coordinates a private snapshot and restores both initially active services;
the file must be root-owned, mode 0600, and contain JSON keys `username` and
`password`. This mode supports only the pinned tuple, exact known units with no
drop-ins, and the loopback HTTP panel. Other states are refused. Xray is stopped
as part of the panel service, not as a separate unit.

Preparation uses a cooperative operation lock, checks for observable writable
file descriptors, and holds a SQLite reserved write lock during Online Backup.
It records source ownership and modes in the private manifest. A privileged
external actor can still race process/file checks; no global filesystem freeze
is claimed. On interruption, an unfinished durable phase requires operator
review; it is never interpreted as permission to apply an update. Because the
services restart after the snapshot, the snapshot may immediately become stale:
an eventual updater must re-establish a coordinated cut. This mode does not
replace binaries, migrate data, authorize upgrade, or implement rollback.

The generated server and client configuration files are private and contain
secret keys; the client file is under `/var/lib/3xui-pro-fork/awg`. The AWG
controller uses an exclusively created named TUN descriptor, refuses an
existing interface and does not delete interfaces by name. It is separate from
the experimental FD_NATIVE namespace harness. It does not configure host NAT,
forwarding or a public firewall; the included client routes only the tunnel
server address. Use it only in an isolated test environment until qualified.

For a disposable test host, after independently verifying and extracting the
candidate archive, run the installer from its directory, for example:

```sh
sudo python3 install_candidate.py --awg-endpoint 192.0.2.1 --awg-subnet 10.88.31.0/30
sudo systemctl status 3xui-pro-fork-awg.service
```

Choose a client-reachable endpoint and a non-conflicting subnet for the test.
Manage the separate service with `systemctl start`, `stop` and `restart`. The
panel listens only on `127.0.0.1:2053`; its initial credentials are in the
service journal. Do not expose that HTTP listener without an independently
configured, secure access method.

`components-manifest.json` checks component integrity against values inside the
archive. A checksum distributed with an archive detects corruption but is not
authentication if obtained from the same untrusted source.
