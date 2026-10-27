#!/usr/bin/env bash
# Download and verify the build inputs (nothing is committed or republished).
#   fetch_inputs.sh DEST   -> DEST/base/{r1,r3proii,r3ii_2025}.upt, DEST/base/v1-stock.upt,
#                             DEST/ssc/usr/bin/bluealsad
# Hashes: firmware/inputs.sha256 (base images, V1 stock) and firmware/ssc-overlay.sha256 (daemon).
# Sources: compas-player release staging-image-base (public); compas-firmware release build-inputs
# (assets bluealsad and v1-stock.upt). Needs the gh CLI (GH_TOKEN in CI).
set -euo pipefail
repo=$(cd "$(dirname "$0")/../../.." && pwd)
dest=$(realpath -m "${1:?usage: $0 DEST}")
player_repo=${PLAYER_REPO:-Starnished66/compas-player}
firmware_repo=${FIRMWARE_REPO:-Starnished66/compas-firmware}
mkdir -p "$dest/base" "$dest/ssc/usr/bin"
gh release download staging-image-base -R "$player_repo" --dir "$dest/base" --clobber \
    --pattern r1.upt --pattern r3proii.upt --pattern r3ii_2025.upt
gh release download build-inputs -R "$firmware_repo" --dir "$dest/base" --clobber --pattern v1-stock.upt
gh release download build-inputs -R "$firmware_repo" --dir "$dest/ssc/usr/bin" --clobber --pattern bluealsad
chmod 0755 "$dest/ssc/usr/bin/bluealsad"
(cd "$dest/base" && sha256sum --check "$repo/firmware/inputs.sha256")
(cd "$dest/ssc/usr/bin" && sha256sum --check "$repo/firmware/ssc-overlay.sha256")
