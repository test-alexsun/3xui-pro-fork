# PREVIEW-XONIX-04A.1: PASS

Date: 2026-11-20. Branch: `preview/xonix-standalone-debian13`.
The initial worktree was clean at `5889cadb622d06ecd25ba37732b6bddb8b3a857a`
(checkpoint `2f64b46e0cbd6f9c212a9a89d5f05170749fbc90`).
Historical regression source: `f6c478aae0b522a822b83d373dc0dc32182362cc`.

## Three original failures

The previous run reported 245 tests, 242 passed and 3 failed. Its historical
test tree and library came from `f6c478a`, but its five `x-ui-*.sh`
entrypoints came from preview. Repeating that shell overlay reproduced all
three failures. Running those same three tests on the intact historical tree
passed 3/3, exit 0.

| Test | Function and historical expectation | Actual result with the preview overlay |
| --- | --- | --- |
| `integration.test_installer.InstallerContracts.test_no_legacy_imperative_body_or_host_mutators` | Reads the historical launcher and helper sources to reject embedded host mutators. Separately checks the historical lab installer modules for direct firewall invocations. | The full-file search finds `fuser -k` in preview `x-ui-latest.sh`. Its retained legacy implementation begins after an unconditional `exit 1`; the assertion does not distinguish executable entry code from the retained body. It fails before checking the historical modules. |
| `modern.test_profiles.ModernProfiles.test_all_historical_shell_entrypoints_block_before_mutators` | Scans each historical shell entrypoint up to the first `exit 2` for `PRODUCTION_APPLY_DISABLED` and absence of host mutator commands. Historical lab wrappers delegate to their guarded Python entrypoints. | In the reproduction the first mismatch was `x-ui-update-routing.sh`: the old helper from preview lacks the marker and still contains its operational body. Preview `x-ui-latest.sh` also does not match because it prints `INSTALL_DISABLED` and exits with 1. The old helper is distinct from the disabled installer and is not called by preview installation. |
| `modern.test_profiles.ModernProfiles.test_legacy_ports_routes_output_and_count_absent` | Checks historical modern profiles and the shell launcher for absence of old WS/Trojan/VMess parameters, legacy route and output markers, and the old fixed profile count. The historical launcher must delegate to `lib.installer.install_cli`. The test also checks lab Nginx routing and the P0–P3 rendered URI formats. | The first failure is `ws_port` in the retained disabled installer body. The active preview launcher `install-preview.sh` uses `release/preview_install.py`; the profile and routing assertions belong to the historical module, and the overlay failure stops before those assertions. |

The first and third failures are source checks against a disabled legacy
installer. The second compares historical wrappers with legacy preview
files, including an auxiliary standalone utility. None exercises the active
`install-preview.sh` installer. No runtime defect in the active installer was
identified in these three cases. The four separate historical management
utilities remain outside the preview installer contract and were not executed.

## Regression contract

- `tests/release/run_preview_regression.sh` runs the original unified suite
  in a separate historical tree, then explicitly discovers the current
  preview release suite in its own tree. Both exit codes are reported and
  either failing phase makes the overall invocation fail. The historical
  tests, shell fixtures and library are kept together.
- `tests/release/test_legacy_installer.py` verifies the preview contract.
  Before starting Bash it checks that the first commands are the stderr
  `INSTALL_DISABLED` message and the unconditional `exit 1`. Running the
  preview launcher without arguments, with `-install y` and with
  `-uninstall y` independently returned 1, wrote only that refusal to stderr
  and left the scratch working directory empty. The installer source and
  guard remain unchanged.
- The preview phase reads the final `release/preview_install.py`
  (SHA-256 `714f4193047e590a1229ed94ed163203a7fffd26919ad443490fd530acb54878`),
  including `proxy_cache off`, `proxy_hide_header Referrer-Policy` and
  `add_header Referrer-Policy no-referrer always`.

## Final results

| Phase | Discovered and run | PASS | FAIL | ERROR | SKIP | Exit |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Historical unified suite (310.587 s) | 245 | 245 | 0 | 0 | 0 | 0 |
| Current preview release suite (0.192 s) | 11 | 11 | 0 | 0 | 0 | 0 |
| Total | 256 | 256 | 0 | 0 | 0 | 0 |

The current preview suite includes 8 existing installer tests, 2 existing
backup tests and 1 legacy protection test. There were no skip reasons because
no tests were skipped. The run used Debian 13 Docker image
`sha256:ece737fcf90805c6cd83db459906acb936374d02beb443a70f0595bb6f141e5b`
with network disabled, read-only root and separate native Docker volumes.
The preview snapshot was the current HEAD plus the two new test files.

- Targeted historical cases: 3/3 PASS. Preview installer protection:
  VERIFIED, including the separate safety test (1/1, three invocations).
- Nginx: PASS. The existing HTTP/HTTPS route fixture passed. Real Nginx
  accepted the config generated by the current preview. With caching enabled
  at the HTTP level, two requests to the subscription reached the synthetic
  upstream separately. The 200 and 404 responses each carried exactly one
  `Referrer-Policy: no-referrer` header, replacing the upstream header.
  The unknown route returned 404. The canary tokens were absent from the
  fixture's Nginx access and error logs.
- Panel/API/subscriptions smoke with the real panel: NOT_RUN. This change
  touches the test harness only. The current Nginx subscription proxy was
  exercised against the synthetic upstream described above.
- Python AST (11 files), Bash syntax (15 files), POSIX shell syntax for the
  new runner and `git diff --check`: PASS. Syntax ran on the committed LF
  export. The only script byte differences between that export and the full
  regression export were CRLF in four unexecuted legacy helpers.

The separate trees are mounted read-only. If exporting from Windows for Linux
syntax checks, use `git -c core.autocrlf=false archive` to keep the committed
line endings of the legacy helpers. With `$HISTORICAL` set to the unpacked
historical archive and `$PREVIEW` set to the current preview tree, run:

```sh
docker run --rm --pull never --network none --read-only \
  --cap-drop ALL --cap-add DAC_OVERRIDE --cap-add CHOWN \
  --cap-add SETUID --cap-add SETGID --security-opt no-new-privileges \
  --tmpfs /tmp:rw,exec,mode=1777 --volume /work --volume /checkpoint \
  --mount "type=bind,source=$HISTORICAL,target=/src,readonly" \
  --mount "type=bind,source=$PREVIEW,target=/preview,readonly" \
  3xuiprofork-stage05:debian13 sh /preview/tests/release/run_preview_regression.sh
```

The historical runner drops to an unprivileged UID for the tests. An initial
bootstrap attempt omitted `DAC_OVERRIDE` and could not open the historical
log after changing ownership of `/work`; it yielded no historical result.

The local `main` and `origin/main` refs remained at
`7e822e3e5dfe6f6e95c57fc83b24d00cd7fde661`. No push or merge was performed.
