# Compás Firmware

Everything needed to turn a `compas-player` build into flashable firmware images (`.upt`) for the
HiBy R1, HiBy R3 Pro II, HiBy R3II 2025 and TempoTec V1: packaging scripts, board resources, fonts,
themes, init overlays, driver pins, the Bluetooth/SSC sources, kernel work and translation catalogs.
It contains no accounts, settings, media or stock firmware dumps. Packaging creates files; it never flashes.

## Layout

| Path | Contents |
| --- | --- |
| `scripts/build/firmware/` | `build_all_upt.sh` (all four images), `validate_images.sh` |
| `scripts/firmware/package/` | `repack_upt.sh` (HiBy boards), `repack_v1_upt.py` (V1), `clean_os.py`, player swap tools |
| `scripts/build/base`, `scripts/base_image`, `scripts/overlays` | Bluetooth / audio / Wi-Fi base-system builds and overlays |
| `scripts/kernel`, `firmware/kernel` | kernel, driver, display, radio work and repackers |
| `firmware/overlay`, `firmware/vendor_drivers.json`, `firmware/ssc-overlay.sha256`, `firmware/v1` | init overlay, pins |
| `assets/` | themes, fonts, bootloader selector, brand and per-board assets (`r3proii`, `r3ii_2025`, `v1`) |
| `src/bootloader/startup` + `Makefile` | early splash (built against the player checkout) |
| `third_party/libssc` | native Samsung SSC encoder |
| `i18n/` | `.po` catalogs and `po2c.py` |
| `docs/inputs.md` | base images, overlay, V1 stock: sources and checks |

## Build all images

Needs Linux, Bash, Python 3, Git, Make, CMake, `7z`, `unsquashfs`, `mksquashfs`, `genisoimage`, `file`,
and the MIPS musl toolchain (`compas-player/scripts/tools/toolchain/install_mips_toolchain.sh DIR`, add `DIR/mipsel-linux-musl-cross/bin` to PATH).
Work from a Git clone: the repacker copies only tracked files.

```sh
git clone https://github.com/Starnished66/compas-player ../compas-player
git clone -b tempotec-v1 https://github.com/Starnished66/compas-player ../compas-player-v1   # V1 only
COMPAS_PLAYER_DIR=../compas-player COMPAS_PLAYER_V1_DIR=../compas-player-v1 \
BASE_DIR=inputs/base SSC_OVERLAY_DIR=inputs/ssc V1_STOCK_UPT=inputs/base/v1-stock.upt \
OUT_DIR=outputs RELEASE_LABEL="Weekly Beta 2026-11-02" \
scripts/build/firmware/build_all_upt.sh
```

`BOARDS="r1"` (etc.) limits the build. Per board by hand: `make release BOARD=<b> RELEASE_LABEL=v1.3.1` and
`make bootloader BOARD=<b>` in the player, `make early-splash BOARD=<b>` here, then
`scripts/firmware/package/repack_upt.sh --board <b> --early-splash build/compas_early_splash[_<b>] BASE PLAYER LOADER OUT`
(set `R1_RUNTIME_OVERLAY` / `R3_RUNTIME_OVERLAY` to the SSC overlay). V1: `scripts/firmware/package/repack_v1_upt.py --help`.
Labels must be `vX.Y.Z` or `Weekly Beta YYYY-MM-DD`. See `docs/inputs.md` for the inputs.

## Continuous integration

`.github/workflows/weekly.yml` runs Mondays 19:00 UTC (and on demand): it builds the four images, validates them
and publishes a pre-release `weekly-YYYY-MM-DD`. Secrets: `STAGING_IMAGE_SHA256`, `R3PROII_STAGING_IMAGE_SHA256`,
`R3II_2025_STAGING_IMAGE_SHA256`, `V1_STAGING_IMAGE_SHA256`, `V1_STOCK_UPT_URL`. The build fails if one is missing.

## Licences and provenance

The repository is GPL-3.0 (`LICENSE`) unless a file or folder says otherwise. Third-party material, its
licences and what is still unresolved are listed in `THIRD_PARTY_NOTICES.md`; retain the accompanying licences
when distributing images. Moved out of `compas-player` (commit `bbca9a5b80` and later).
