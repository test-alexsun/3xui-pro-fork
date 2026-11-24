# Pinned AWG distribution

`awg-linux-amd64.tar.gz` contains exactly the two Linux amd64 executables
already qualified in the candidate. Its SHA-256 is
`1273dc4a82b2eff7624db91b77a18f0f603365606e938d052a3a0dc17323d50b`.
The installer independently compares each extracted binary with its original
pinned hash and rejects an unexpected archive member.

| Binary | Version | Source archive | Source commit |
| --- | --- | --- | --- |
| amneziawg-go | 3.1.20260828 | `amneziawg-runtime-source.tar.gz` | `b5928efb6ca19f0153958460c3d141f04abc5c2e` |
| awg | 3.1.20260812 | `amneziawg-tools-source.tar.gz` | `ee0f0a9aa34ff0a0da4b3433b9512781cfe02843` |

The two archives are the corresponding, unmodified upstream source used to
build these binaries, including their license and build files. The runtime
build used Go 1.27.3 with `CGO_ENABLED=0 go build -mod=readonly -trimpath
-buildvcs=false`. The tools build used `make -C src V=1 wg` on Debian 13.
The original build scripts and pinned toolchain image references are in
`build/`. In the Debian build container, name the accompanying upstream
archives `runtime.tar.gz` and `tools.tar.gz` in the source cache and invoke
`bash build/build_pinned.sh BUILD_DIR SOURCE_CACHE`. The recipe verifies
the source hashes and emits the compiler/package versions and binary hashes.
The runtime module versions and hashes are recorded in upstream `go.sum`.

The panel and Xray archives are acquired from official upstream GitHub
releases at install time. No custom panel build is included. License copies
are retained here. See the source releases for their complete upstream
notices: [3x-ui](https://github.com/MHSanaei/3x-ui/tree/v3.11.0) and
[Xray-core](https://github.com/XTLS/Xray-core/tree/v26.11.9).
