#!/usr/bin/env bash
# Build every Compás firmware image from source plus the prepared inputs.
#
#   COMPAS_PLAYER_DIR=...  compas-player checkout (r1, r3proii, r3ii_2025)
#   BASE_DIR=...           holds r1.upt, r3proii.upt, r3ii_2025.upt (prepared base images)
#   SSC_OVERLAY_DIR=...    directory with usr/bin/bluealsad (see docs/inputs.md)
#   OUT_DIR=...            receives the .upt files, standalone players and SHA256SUMS
#   RELEASE_LABEL=...      vX.Y.Z or "Weekly Beta YYYY-MM-DD"
# Optional TempoTec V1 (skipped when V1_STOCK_UPT is unset):
#   V1_STOCK_UPT=...       official TempoTec V1 1.2 firmware (not committed)
#   COMPAS_PLAYER_V1_DIR=... compas-player checkout of the tempotec-v1 branch
# BOARDS="r1 r3proii r3ii_2025 tempotec_v1" limits the build (tempotec_v1 needs r1).
set -euo pipefail

repo=$(cd "$(dirname "$0")/../../.." && pwd)
player_dir=$(realpath "${COMPAS_PLAYER_DIR:?set COMPAS_PLAYER_DIR}")
base_dir=${BASE_DIR:-}
overlay_dir=$(realpath "${SSC_OVERLAY_DIR:?set SSC_OVERLAY_DIR}")
out_dir=$(realpath -m "${OUT_DIR:?set OUT_DIR}")
label=${RELEASE_LABEL:?set RELEASE_LABEL}
jobs=${JOBS:-$(nproc)}
boards=${BOARDS:-"r1 r3proii r3ii_2025 tempotec_v1"}
export COMPAS_PLAYER_DIR="$player_dir"

[[ $label =~ ^((Compas )?v[0-9]+\.[0-9]+\.[0-9]+|Weekly\ Beta\ [0-9]{4}-[0-9]{2}-[0-9]{2})$ ]] || {
    echo "RELEASE_LABEL must be vX.Y.Z or 'Weekly Beta YYYY-MM-DD': $label" >&2; exit 1; }
[[ -f $overlay_dir/usr/bin/bluealsad ]] || { echo "Missing $overlay_dir/usr/bin/bluealsad" >&2; exit 1; }
(cd "$overlay_dir/usr/bin" && sha256sum --check --status "$repo/firmware/ssc-overlay.sha256") || {
    echo "bluealsad does not match firmware/ssc-overlay.sha256" >&2; exit 1; }
for tool in make 7z unsquashfs mksquashfs genisoimage file python3 mipsel-linux-musl-gcc \
    mipsel-linux-musl-readelf sha256sum; do
    command -v "$tool" >/dev/null || { echo "Required command is unavailable: $tool" >&2; exit 1; }
done
mkdir -p "$out_dir"

suffix() { [[ $1 == r1 ]] && echo "" || echo "_$1"; }

check_player() {   # check_player BINARY: MIPS ELF without diagnostic builds
    mipsel-linux-musl-readelf -h "$1" | grep -q 'Machine:.*MIPS'
    if strings "$1" | grep -Eq 'TEST BUILD|TEST_BUILD_TAG|UI_PERF_TRACE|UI_GESTURE_TRACE|UI_HITBOX_DEBUG'; then
        echo "Diagnostic flags were found in $1." >&2; exit 1
    fi
}

build_player() {   # build_player DIR BOARD
    local dir=$1 board=$2
    if grep -q '^release:' "$dir/Makefile"; then
        make -C "$dir" -j"$jobs" release BOARD="$board" RELEASE_LABEL="$label"
    else    # older branches (the tempotec-v1 port) predate the release target
        make -C "$dir" -j"$jobs" target BOARD="$board" RELEASE_LABEL="$label"
    fi
}

for board in $boards; do
    [[ $board == tempotec_v1 ]] && continue
    sfx=$(suffix "$board")
    [[ -s $base_dir/$board.upt ]] || { echo "Missing base image $base_dir/$board.upt" >&2; exit 1; }
    build_player "$player_dir" "$board"
    make -C "$player_dir" bootloader BOARD="$board"
    make -C "$repo" early-splash BOARD="$board"
    for f in "$player_dir/compas_player_target$sfx" "$player_dir/compas_loader$sfx" \
        "$repo/build/compas_early_splash$sfx"; do check_player "$f"; done
    if [[ $board == r1 ]]; then
        export R1_RUNTIME_OVERLAY="$overlay_dir"; unset R3_RUNTIME_OVERLAY
    else
        export R3_RUNTIME_OVERLAY="$overlay_dir"; unset R1_RUNTIME_OVERLAY
    fi
    "$repo/scripts/firmware/package/repack_upt.sh" --board "$board" \
        --early-splash "$repo/build/compas_early_splash$sfx" \
        "$base_dir/$board.upt" "$player_dir/compas_player_target$sfx" \
        "$player_dir/compas_loader$sfx" "$out_dir/$board.upt"
    cp "$player_dir/compas_player_target$sfx" "$out_dir/compas_player$sfx"
done
unset R1_RUNTIME_OVERLAY R3_RUNTIME_OVERLAY

if [[ " $boards " == *" tempotec_v1 "* && -n ${V1_STOCK_UPT:-} ]]; then
    v1_dir=$(realpath "${COMPAS_PLAYER_V1_DIR:-$player_dir}")
    [[ -s $out_dir/r1.upt ]] || { echo "tempotec_v1 needs the freshly built r1.upt in OUT_DIR" >&2; exit 1; }
    build_player "$v1_dir" tempotec_v1
    check_player "$v1_dir/compas_player_target_tempotec_v1"
    tmp=$(mktemp -d "${TMPDIR:-/tmp}/v1-repack.XXXXXX")
    trap 'rm -rf "$tmp"' EXIT
    rm -f "$out_dir/v1.upt" "$out_dir/v1_md5.txt" "$out_dir/v1-manifest.json"
    python3 -I "$repo/scripts/firmware/package/repack_v1_upt.py" \
        --base "$V1_STOCK_UPT" --player "$v1_dir/compas_player_target_tempotec_v1" \
        --r1-candidate "$out_dir/r1.upt" --output "$out_dir/v1.upt" \
        --md5-output "$out_dir/v1_md5.txt" --manifest "$out_dir/v1-manifest.json" \
        --tmp "$tmp" --md5-template "$repo/firmware/v1/v1_md5.template.txt"
fi

(cd "$out_dir" && sha256sum *.upt compas_player* $( [[ -f v1_md5.txt ]] && echo v1_md5.txt ) > SHA256SUMS && sha256sum --check SHA256SUMS)
"$repo/scripts/build/firmware/validate_images.sh" "$out_dir"
