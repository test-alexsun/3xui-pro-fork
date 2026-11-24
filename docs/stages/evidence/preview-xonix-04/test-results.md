# PREVIEW-XONIX-04: INCOMPLETE

Branch `preview/xonix-standalone-debian13`; stage-03 checkpoint
`67fd36a` was created locally from the existing verified files. No push or
production deployment occurred. The network changes of this stage remain
uncommitted.

## Architecture actually implemented

- The normal preview entrypoint retains its HTTP-only site and refuses
  conflicting/unowned files; it does not install a public TLS or stream
  listener. Existing Xray listeners are not switched or reconfigured.
- The optional `--test-mode --sandbox-tls-cert PATH --sandbox-tls-key PATH`
  enables a test-only HTTPS listener on `127.0.0.1:18443`. The site hostname
  serves XONIX and `panel.<site-domain>` proxies to panel `127.0.0.1:2053`.
  HTTP test mode listens on 18080. The certificate and root-only key are
  supplied externally and are not modified. The sandbox refuses an occupied
  HTTPS port before first enablement and refuses silently disabling an existing
  sandbox. Existing web state, backup, `nginx -t`, reload and recovery code
  remains in use. A sandbox ACME challenge path takes priority over dotfile
  denial; no ACME client or public certificate issuance is implemented.
- SNI stream, public TCP 443, UDP 443, REALITY, XHTTP, panel subscription
  routes and Hysteria2 are not integrated. The isolated panel reverse proxy is
  not a production exposure method. Xray profile configuration is not changed.

## Current checks

- Fresh Debian 13 QEMU VM, isolated test domain and generated self-signed test
  certificate: installer ran, Xray 26.11.9 executable was observed running,
  AWG service/interface started, and both loopback panel API and authenticated
  login and inbounds-list API through sandbox HTTPS passed. XONIX bytes matched
  through sandbox HTTP and HTTPS. No public trust or ACME issuance is implied.
- Same VM repeated installation, checked AWG key hashes, a SQLite sentinel,
  user file and active services, and verified a synthetic HTTP ACME challenge,
  missing and hidden path 404s. It injected an invalid Nginx directive, saw
  `nginx -t` reject it, restored and checked prior HTTP and sandbox HTTPS, and
  observed both services active. Markers: `PREVIEW04_HTTPS_PANEL_API_PASS`,
  `PREVIEW04_ACME_SANDBOX_HTTP_PASS`, `PREVIEW03_REPEAT_PASS`,
  `PREVIEW03_CONFIG_RECOVERY_PASS`, `PREVIEW04_VM_PASS`.
- A real headless Chrome instance accessed the installed VM Nginx over a
  loopback-only QEMU forwarded port. Start, movement, pause, restart, bomb and
  mine placement and deterministic capture checks passed; no page exceptions
  or external requests were observed. Chrome did report one 404 resource error
  in the console; the no-console-errors requirement is not satisfied. The
  error source was not established. The browser check used HTTP, not HTTPS.
- NAMED AWG controller E2E was run afresh in a network-none Debian container:
  handshake, bidirectional UDP, restart/reconnect and unchanged synthetic
  keys passed (`AWG_CONTROLLER_E2E_PASS`). This was a separate test, not proof
  of complete network integration.
- Six targeted Python tests passed in network-none Debian Docker, covering
  previous publication/recovery paths, sandbox listener conflict, sandbox
  persistence and configuration. The VM payload matched current installer,
  script and XONIX bytes.
- Python, Bash and Node syntax checks passed. `git diff --check` passed;
  new files were checked separately with `git diff --no-index --check`.
- The initial VM attempt exited at the `xray version | grep -q` pipe under
  `pipefail`, before the HTTPS API check. The fixture was changed to capture
  full output before matching and rerun on a fresh VM; no cause beyond that
  pipeline failure is asserted.

## Not verified

Real P0/P1/P3 client connections, SNI stream/REALITY, P2/P4 and Hysteria2,
actual subscriptions and subscription error paths, XHTTP routing, public
TLS/Let's Encrypt, DNS and renewal, browser HTTPS, preservation of existing
REALITY keys and UUIDs, end-to-end regression and JSON Schema validation are
NOT_RUN. No existing subscription or transport backend was configured by this
stage. The browser console issue remains open. Publication and GitHub install
are NOT_RUN until the complete acceptance gates are satisfied.
