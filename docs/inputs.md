# Build inputs

Nothing below is committed: stock firmware and prebuilt binaries are fetched and checked against a
SHA-256 that is tracked in this repository (no secrets are involved).

| Input | Used for | Source | Pin |
| --- | --- | --- | --- |
| `r1.upt`, `r3proii.upt`, `r3ii_2025.upt` | prepared base images (kernel, drivers, base system) | public `compas-player` release `staging-image-base` | `firmware/inputs.sha256` (equal to the release asset digests) |
| `bluealsad` | Samsung SSC Bluetooth (BlueALSA 5.0.0 + `bluealsa-ssc.patch`, libssc linked statically) | release `build-inputs` of this repository, asset `bluealsad` | `firmware/ssc-overlay.sha256` |
| `v1-stock.upt` | official TempoTec V1 1.2 firmware (kernel, recovery, stock rootfs) | release `build-inputs` of this repository, asset `v1-stock.upt` (a byte-identical mirror of the vendor download) | `firmware/inputs.sha256` (`9f929a92...`) |
| `compas-player` `main` | all four players, loaders | public repository | - |

`scripts/build/firmware/fetch_inputs.sh DEST` downloads and verifies all of them.

Exact assets of release `build-inputs` (tag `build-inputs`):

| Asset name | SHA-256 | Size |
| --- | --- | --- |
| `bluealsad` | `d683e3389fbfb3e35351d3b44f9dafbbc4007136c1f2ee510702280415cc11c4` | 1 file, mode 0755 as installed |
| `v1-stock.upt` | `9f929a92319a05a81bbd16cbf0fb8a886a9bb2def192f5a6786b6ea7032fa05d` | 39,907,328 bytes |

The staging bases predate SSC; the SSC daemon is applied at repack time through
`R1_RUNTIME_OVERLAY` / `R3_RUNTIME_OVERLAY` (a directory holding `usr/bin/bluealsad`).
V1 takes its BlueALSA/GLib runtime, themes and fonts from the freshly built `r1.upt`.
The V1 stock image's origin is the TempoTec firmware download page (public Google Drive folder, file id
`1z8es1IXVFt2PhWLzUFVbv_D0rfGzjjes`, vendor MD5 `d3301d3930309b5433331a2aed741652`).

## Rebuilding bluealsad

Needs the Ingenic glibc 2.22 toolchain (see `scripts/base_image/README.md`). Run the build order there with
`SSC_STATIC=ON` for `build_base_bt_codecs.sh`, then `build_base_bluealsa.sh`; the resulting
`stage/usr/bin/bluealsad` is the overlay. The published v1.3.0 daemon was built from BlueALSA
`1935d6dcb8975f2d7a51aaafe61538d157224623` with `scripts/base_image/patches/bluealsa/bluealsa-ssc.patch`.
A rebuild is not guaranteed to be byte-identical; if you replace the daemon, update `firmware/ssc-overlay.sha256`
(the only place the hash lives) and re-upload the `build-inputs` asset.

## How v1.3.0 was assembled

* r1 / r3proii / r3ii_2025: `repack_upt.sh` on the staging base with the SSC overlay.
* V1: `repack_v1_upt.py` on the stock V1 image with the R1 image as resource/runtime source.
* The released players were later exchanged and relabelled with the tools in
  `scripts/firmware/package/history/`. `build_all_upt.sh` produces the same result directly.
