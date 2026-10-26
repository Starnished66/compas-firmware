# Compás Firmware (private)

Firmware image packaging and runtime resources, separated from the public `compas-player` executable source tree. This repository contains production repacking helpers, board resources, fonts, overlays, driver pins and base-system build inputs. It does not contain accounts, player settings, personal media or base firmware dumps.

## Build an image

Keep a matching `compas-player` checkout beside this repository, or set `COMPAS_PLAYER_DIR` to its absolute path. Use Linux with Bash, Python 3, Git, Make, a MIPS musl cross-toolchain, `7z`, `unsquashfs`, `mksquashfs`, `genisoimage`, `file`, and standard GNU utilities.

```sh
export COMPAS_PLAYER_DIR="$(realpath ../compas-player)"
export TMPDIR="$HOME/.cache/compas-firmware-tmp"
mkdir -p "$TMPDIR" inputs outputs
make -C "$COMPAS_PLAYER_DIR" -j6 target BOARD=r1
make -C "$COMPAS_PLAYER_DIR" bootloader BOARD=r1
make early-splash BOARD=r1
scripts/firmware/package/repack_upt.sh --board r1   --early-splash "$PWD/build/compas_early_splash"   "$PWD/inputs/r1-base.upt"   "$COMPAS_PLAYER_DIR/compas_player_target"   "$COMPAS_PLAYER_DIR/compas_loader"   "$PWD/outputs/r1.upt"
```

Supply an approved base image under `inputs/`; it is intentionally not committed. Run from a Git clone: the repacker deliberately copies only Git-tracked assets. The repacker retains its existing validation, board identity, driver and font checks. Do not replace those checks to force an unsupported image through. Packaging creates a file; it does not flash a device.

| Board | Player suffix | Early-splash output |
| --- | --- | --- |
| `r1` | none | `build/compas_early_splash` |
| `r3proii` | `_r3proii` | `build/compas_early_splash_r3proii` |
| `r3ii_2025` | `_r3ii_2025` | `build/compas_early_splash_r3ii_2025` |

Use the same board for every input. `--vendor-drivers` and the optional runtime-overlay environment variables retain their existing validation. `scripts/build/firmware/build_both_upt.sh` is the convenience command for the existing two-board R1/R3 Pro II workflow.

The font verifier compares these packaged resources with the manifest in `COMPAS_PLAYER_DIR`; incompatible font and player revisions fail rather than silently producing a mismatched image. Regeneration tools use that same source checkout for LVGL font inputs and compiled manifests.

Base-system and kernel production helpers remain under `scripts/build/`, `scripts/base_image/`, `scripts/kernel/` and `firmware/kernel/`. They require their documented stock-root and board-toolchain inputs; the main repacker consumes a prepared base image.

## Provenance

Moved from `compas-player` commit `bbca9a5b80` and its pending executable-only cleanup. Resource contents, license notices and pinned driver records are preserved. Retain the accompanying licenses when distributing generated images.
