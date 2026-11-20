# PREVIEW-XONIX-04A: INCOMPLETE

Date: 2026-11-20. Branch `preview/xonix-standalone-debian13`.
PREVIEW-XONIX-04 checkpoint: `2f64b46e0cbd6f9c212a9a89d5f05170749fbc90`.
No push, merge, or production deployment was performed.

## Implementation and scope

- The optional `--sandbox-subscriptions` uses existing panel settings read
  through a read-only SQLite connection. It refuses disabled/ambiguous
  settings, non-loopback backends, unverified listener ownership, backend TLS,
  invalid or overlapping paths, and a subscription base URL that differs from
  the sandbox HTTPS route. It does not change panel SQLite or credentials.
- Enabled paths are proxied through the existing loopback-only HTTPS vhost;
  Nginx access/error request logging and proxy caching are disabled for these
  locations; responses set `Referrer-Policy: no-referrer`. The subscription
  ID remains a bearer secret. This is not a public TLS/443 or
  Xray transport integration.
- The game received one inline data favicon and no gameplay changes. The old
  and new HTML were compared after removing that link: all other bytes match.
  New SHA-256: `cd8cbef1d1d80ad2eacb441467cef9d93aec216b378775b39409b84bffffa325`.
- New owned web directories are explicitly mode 0755 even with umask 077;
  inaccessible existing directories are refused without changing their modes.

## Results

- **PASS, scoped VM:** fresh disposable Debian 13 with self-signed synthetic
  certificate, installed panel/Nginx/AWG and synthetic client created via
  panel API. Authenticated HTTPS panel API was checked after the subscription
  route was enabled. The test read the configured base URL back from the panel,
  fetched the real subscription through HTTPS, decoded its format and matched
  the synthetic client identity. A fake token gave the same 404 and body as
  the direct panel subscription backend. An unknown route returned 404 and
  neither negative response was XONIX. The VM checked ACME challenge priority,
  a hidden path, a missing file, and `nginx -t`. Markers in the private VM log:
  `PREVIEW04A_PANEL_API_AFTER_ROUTE_PASS`, `PREVIEW04A_LOCATION_PRIORITY_PASS`,
  `PREVIEW04A_SUBSCRIPTION_PASS`, `PREVIEW04A_SUB_NEGATIVE_PASS status=404`.
  Final VM run also reported `PREVIEW04A_TOKEN_LOG_AND_REFERRER_PASS`:
  its synthetic token was absent from the panel journal and Nginx access/error
  logs, and its response carried `Referrer-Policy: no-referrer`. This is
  limited to the tested deployment and logs. Final VM ISO payload and current
  installer/HTML bytes were compared separately.
- **PASS, browser after fix:** headless Chrome against the installed VM's
  Nginx over a loopback-only forwarded HTTP port exercised loading, movement,
  pause, restart, bomb and mine placement, with no page exceptions, console
  errors, unexpected HTTP errors or external requests. HTTPS browser testing
  was not performed; HTTPS itself was tested by the VM fixture.
- **404 diagnosed and resolved:** on a child overlay of the previously
  installed VM, Chrome CDP captured `GET /favicon.ico`, HTTP 404, resource
  type `Other`, initiator `other` (browser). The game otherwise ran. A data
  icon removed the request and its console error; the equivalent Nginx test
  and the installed-VM browser smoke passed after the change.
- **PASS, targeted:** eight Python tests passed in a Debian container with no
  network. These cover ownership/URL/path refusals, no SQLite write, directory
  modes, Nginx transaction and sandbox settings. A separate network-none test
  using the real pinned panel confirmed that the subscription listener PID
  matches the panel, rejected a foreign PID, and did not find a synthetic
  invalid subscription token in that panel's captured log. It does not prove
  absence of logging in every deployment or external intermediary.
- **PASS, JSON Schema:** meta-schema validation and three historical schema
  tests (including valid and invalid examples) passed in a network-none
  container using pinned, hash-checked offline dependencies. These concern
  the existing AWG journal schema, not a new subscription schema.
- Python, Bash and Node syntax checks passed; tracked and new files were
  checked for whitespace errors.
- **FAIL, unified regression:** 245 tests ran, 242 passed, 3 failed, 0 errors,
  0 skipped. The three failures are
  `integration.test_installer.InstallerContracts.test_no_legacy_imperative_body_or_host_mutators`,
  `modern.test_profiles.ModernProfiles.test_all_historical_shell_entrypoints_block_before_mutators`,
  and `modern.test_profiles.ModernProfiles.test_legacy_ports_routes_output_and_count_absent`.
  They inspect the retained legacy `x-ui-latest.sh` body and expect the
  historical sandbox's short `PRODUCTION_APPLY_DISABLED` stubs; the preview
  file instead retains that body behind an `INSTALL_DISABLED` exit guard.
  The other legacy entrypoints have not been qualified for safe use. The suite
  ran against an archive of historical commit `f6c478a` with the preview
  release code, release tests and all five current preview shell scripts
  overlaid. It is a hybrid test harness, not a complete preview checkout.
  This run preceded the final cache/referrer directives; the current installer
  was subsequently covered by targeted tests and the final VM run. Its 3
  failures prevent an overall PASS. An earlier tmpfs attempt also hit
  `READONLY_ROOT_NATIVE_TEST_VOLUME_REQUIRED`; the recorded result above used
  the native Docker volumes required by the harness.

## Remaining boundaries

Panel HTTPS and subscriptions are verified only in the isolated sandbox with
test credentials and certificate. Public TLS/ACME issuance, public 443 SNI,
REALITY, XHTTP and real P0/P1/P3 connections remain PREVIEW-XONIX-04B work.
The GitHub installer is not published. FD_NATIVE was not modified or retested.
