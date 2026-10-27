#!/usr/bin/env bash
# Validate the images in a build output directory: branding assets match the
# tracked sources, the shipped players carry their board marker, and every
# image unpacks. Usage: validate_images.sh OUT_DIR
set -euo pipefail
repo=$(cd "$(dirname "$0")/../../.." && pwd)
out=$(realpath "${1:?usage: $0 OUT_DIR}")
work=$(mktemp -d "${TMPDIR:-/tmp}/validate-images.XXXXXX")
trap 'rm -rf "$work"' EXIT

unpack_root() {   # unpack_root UPT DIR -> DIR/root
    7z x -y "-o$2/upt" "$1" >/dev/null
    mapfile -t chunks < <(find "$2/upt/ota_v0" -maxdepth 1 -type f -name 'rootfs.squashfs.[0-9]*' | LC_ALL=C sort)
    (( ${#chunks[@]} > 0 ))
    cat "${chunks[@]}" > "$2/rootfs.squashfs"
    unsquashfs -no-xattrs -d "$2/root" "$2/rootfs.squashfs" >/dev/null
}

for board in r1 r3proii r3ii_2025; do
    [[ -f $out/$board.upt ]] || continue
    theme_src=$repo/assets/theme2
    [[ $board == r1 ]] || theme_src=$repo/assets/$board/theme2
    logo_src=$repo/assets/$board/etc/logo1.jpeg
    unpack_root "$out/$board.upt" "$work/$board"
    root=$work/$board/root
    cmp -- "$logo_src" "$root/etc/logo1.jpeg"
    cmp -- "$theme_src/boot_animation/en/0.jpg" "$root/usr/resource/litegui/theme2/boot_animation/en/0.jpg"
    cmp -- "$theme_src/boot_animation/en/0.png" "$root/usr/resource/litegui/theme2/boot_animation/en/0.png"
    suffix=_$board; [[ $board != r1 ]] || suffix=
    cmp -- "$out/compas_player$suffix" "$root/usr/bin/compas_player"
    echo "$board.upt: branding assets and player verified"
done

if [[ -f $out/v1.upt ]]; then
    unpack_root "$out/v1.upt" "$work/v1"
    root=$work/v1/root
    grep -aq 'COMPAS_PLAYER_BOARD:tempotec_v1' "$root/usr/bin/compas_player"
    cmp -- "$repo/assets/v1/theme2/usb/usb.png" "$root/usr/resource/litegui/theme2/usb/usb.png"
    cmp -- "$repo/assets/theme2/boot_animation/en/0.png" "$root/usr/resource/litegui/theme2/boot_animation/en/0.png"
    [[ $(awk '{print $1}' "$out/v1_md5.txt") == "$(md5sum "$out/v1.upt" | awk '{print $1}')" ]]
    echo "v1.upt: player marker, assets and v1_md5.txt verified"
fi
