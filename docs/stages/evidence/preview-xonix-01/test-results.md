# PREVIEW-XONIX-01: INCOMPLETE

Base: `7e822e3e5dfe6f6e95c57fc83b24d00cd7fde661` (local main).
Branch: `preview/xonix-standalone-debian13`. Date: 2026-11-17.

## Verified in isolation

- The copied page has the same SHA-256 as the original local `index.html`:
  `5f133c4641749c351903b4bff5fd48e645fa8579972d7a87712e160553c7ccd7`.
- Headless installed Chrome and Playwright exercised the local file. The
  browser script passed movement keydown/keyup, pause and restart, live touch
  start/end, localStorage persistence and denied storage, timer via a real
  Space key and elapsed time, and the M key. It checks game states and game
  methods for captures, surviving ball regions, next level, loss and Game Over,
  collisions, corner movement, bombs, mines and stock preservation. Several
  edge cases are created programmatically; this is not a full human playthrough.
  No page exceptions or external requests were observed in the main browser
  context. No assertion is made for untested gestures or every game state.
- Isolated Docker image `3xuiprofork-stage05:debian13`, with no network and
  read-only root filesystem: `nginx -t` passed; HTTP and self-signed HTTPS
  served byte-identical original HTML; nonexistent and hidden paths returned
  404; root-owned test site directory 0755 and page 0644 were checked. Fixture
  API and subscription locations returned their synthetic 418/419 responses,
  and a synthetic ACME challenge was returned. These do not test real routes,
  public certificates, browser execution over HTTPS or an installed system.
- `bash -n tests/xonix/nginx-fixture.sh` passed in the Debian 13 image.

## Not run or not implemented

- Standalone installer, clean/repeat Debian installation, safe XONIX update,
  file backup/restore, failure handling, real ACME and reload recovery.
- Panel/API, real subscription paths, Xray, REALITY, Vision, XHTTP H2/H3,
  Hysteria2, fallback, NAMED AWG E2E and systemd lifecycle. No actual
  transport connection or preservation of SQLite/AWG keys is established.
- Targeted installer tests, unified regression and JSON Schema validation;
  the preview branch contains no corresponding integrated implementation.
- Publication and remote SHA verification are NOT_RUN because mandatory
  acceptance gates are unmet. No GitHub installation command is verified.

The legacy `x-ui-latest.sh` includes removal of existing Nginx site and stream
configuration and downloads moving upstream references. It does not meet this
stage's preservation and reproducibility requirements. The XONIX Nginx snippet
is an isolated candidate, not a tested production integration.
