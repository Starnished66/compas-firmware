# Build inputs

Nothing below is committed: stock firmware and prebuilt binaries are fetched or supplied
and checked against a SHA-256.

| Input | Used for | Where it comes from | Check |
| --- | --- | --- | --- |
| `r1.upt`, `r3proii.upt`, `r3ii_2025.upt` | prepared base images | public `compas-player` release `staging-image-base` | repository secrets `STAGING_IMAGE_SHA256`, `R3PROII_STAGING_IMAGE_SHA256`, `R3II_2025_STAGING_IMAGE_SHA256` |
| `usr/bin/bluealsad` | Samsung SSC Bluetooth (BlueALSA 5.0.0 + `bluealsa-ssc.patch`, libssc linked statically) | release `build-inputs` of this repository, asset `bluealsad` | `firmware/ssc-overlay.sha256` (tracked) |
| official TempoTec V1 1.2 `.upt` | V1 base (kernel, recovery, stock rootfs) | TempoTec firmware download page (public Google Drive folder, file id `1z8es1IXVFt2PhWLzUFVbv_D0rfGzjjes`); CI fetches it from the `V1_STOCK_UPT_URL` secret | secret `V1_STAGING_IMAGE_SHA256` (value `9f929a92...`, also pinned in `repack_v1_upt.py`) |
| `compas-player` `main` | r1, r3proii, r3ii_2025 players and loaders | public repository | - |
| `compas-player` branch `tempotec-v1` | V1 player | public repository | - |

The staging bases predate SSC; the SSC daemon is applied at repack time through
`R1_RUNTIME_OVERLAY` / `R3_RUNTIME_OVERLAY` (a directory holding `usr/bin/bluealsad`).
V1 takes its BlueALSA/GLib runtime, themes and fonts from the freshly built `r1.upt`.

## Rebuilding bluealsad

Needs the Ingenic glibc 2.22 toolchain (see `scripts/base_image/README.md`). Run the
build order there with `SSC_STATIC=ON` for `build_base_bt_codecs.sh`, then
`build_base_bluealsa.sh`; the resulting `stage/usr/bin/bluealsad` is the overlay. The
published v1.3.0 daemon (`d683e338...`) was built from BlueALSA
`1935d6dcb8975f2d7a51aaafe61538d157224623` with `scripts/base_image/patches/bluealsa/bluealsa-ssc.patch`.
A rebuild is not guaranteed to be byte-identical; update `firmware/ssc-overlay.sha256` with it.

## How v1.3.0 was assembled

* r1 / r3proii / r3ii_2025: `repack_upt.sh` on the staging base with the SSC overlay.
* V1: `repack_v1_upt.py` on the stock V1 image with the R1 image as resource/runtime source
  (first image `compas-tempotec_v1-clean.upt`); then `swap_v1_player.py` replaced only the
  player (SSC fix), and `swap_player.sh` relabelled the final players of all four images.
  `build_all_upt.sh` produces the same result directly with the final player.
