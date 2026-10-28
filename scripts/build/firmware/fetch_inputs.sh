#!/usr/bin/env bash
# Download and verify the build inputs (nothing is committed or republished).
#   fetch_inputs.sh DEST   -> DEST/base/{r1,r3proii,r3ii_2025}.upt, DEST/base/v1-stock.upt,
#                             DEST/ssc/usr/bin/bluealsad,
#                             DEST/ssc/usr/libexec/bluetooth/{bluetoothd,obexd}
# Hashes: firmware/inputs.sha256 (base images, V1 stock) and firmware/ssc-overlay.sha256 (runtime
# overlay daemons, paths relative to DEST/ssc).
# Sources: compas-player release staging-image-base (public); compas-firmware release build-inputs
# (assets bluealsad, bluetoothd, obexd and v1-stock.upt). Needs the gh CLI (GH_TOKEN in CI).
# BUILD_INPUTS_DIR=DIR takes any of those four assets from DIR instead of the release (to try a new
# asset before it is uploaded); the hash checks below still apply.
set -euo pipefail
repo=$(cd "$(dirname "$0")/../../.." && pwd)
dest=$(realpath -m "${1:?usage: $0 DEST}")
player_repo=${PLAYER_REPO:-Starnished66/compas-player}
firmware_repo=${FIRMWARE_REPO:-Starnished66/compas-firmware}
mkdir -p "$dest/base" "$dest/ssc/usr/bin" "$dest/ssc/usr/libexec/bluetooth"

check_pin() {   # check_pin PINFILE DIR NAME: verify one downloaded file against its tracked hash
    local line
    line=$(cd "$2" && grep -E "  $3\$" "$1") || { echo "No pin for $3 in $1" >&2; exit 1; }
    (cd "$2" && printf '%s\n' "$line" | sha256sum --check)
}
base_input() {   # base_input NAME: staging base image from the public player release
    gh release download staging-image-base -R "$player_repo" --dir "$dest/base" --clobber --pattern "$1"
    check_pin "$repo/firmware/inputs.sha256" "$dest/base" "$1"
}
build_input() {   # build_input ASSET DIR PINFILE PIN_ROOT PINNED_NAME
    if [[ -n ${BUILD_INPUTS_DIR:-} && -f $BUILD_INPUTS_DIR/$1 ]]; then
        cp -- "$BUILD_INPUTS_DIR/$1" "$2/$1"
    else
        gh release download build-inputs -R "$firmware_repo" --dir "$2" --clobber --pattern "$1"
    fi
    check_pin "$3" "$4" "$5"
}
for image in r1.upt r3proii.upt r3ii_2025.upt; do base_input "$image"; done
build_input v1-stock.upt "$dest/base" "$repo/firmware/inputs.sha256" "$dest/base" v1-stock.upt
overlay_pins="$repo/firmware/ssc-overlay.sha256"
build_input bluealsad "$dest/ssc/usr/bin" "$overlay_pins" "$dest/ssc" usr/bin/bluealsad
build_input bluetoothd "$dest/ssc/usr/libexec/bluetooth" "$overlay_pins" "$dest/ssc" usr/libexec/bluetooth/bluetoothd
build_input obexd "$dest/ssc/usr/libexec/bluetooth" "$overlay_pins" "$dest/ssc" usr/libexec/bluetooth/obexd
chmod 0755 "$dest/ssc/usr/bin/bluealsad" "$dest/ssc/usr/libexec/bluetooth/bluetoothd" \
    "$dest/ssc/usr/libexec/bluetooth/obexd"
