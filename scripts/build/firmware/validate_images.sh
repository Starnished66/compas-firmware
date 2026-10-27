#!/usr/bin/env bash
# Validate the images in a build output directory. For every image: it unpacks,
# ota_update.in satisfies the player's strict parser (firmware_image.c parse_manifest) and the
# kernel/rootfs chunk chains and chain files exist. HiBy boards: branding assets match the tracked
# sources and the shipped player is the one in OUT_DIR. V1: the player carries its board marker,
# USB overlay and boot animation match the tracked assets, v1_md5.txt matches.
# Usage: validate_images.sh OUT_DIR
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

check_manifest() {   # check_manifest IMAGE_ota_v0_DIR: the exact rules of the player's parse_manifest()
    python3 -I - "$1" <<'PY'
import re, sys, pathlib
ota = pathlib.Path(sys.argv[1])
data = (ota / "ota_update.in").read_bytes()
lines = data.split(b"\n")
want = [b"ota_version=0"]
for kind, name in (("kernel", "xImage"), ("rootfs", "rootfs.squashfs")):
    want += [b"img_type=" + kind.encode(), b"img_name=" + name.encode(), None, None]
if not data.endswith(b"\n") or lines[-1] != b"" or len(lines) - 1 != len(want):
    raise SystemExit("ota_update.in: wrong line count, blank line or missing final newline")
lines = lines[:-1]
for i, (got, exp) in enumerate(zip(lines, want)):
    if exp is not None and got != exp:
        raise SystemExit(f"ota_update.in line {i + 1}: unexpected {got!r}")
for base, name in ((3, "xImage"), (7, "rootfs.squashfs")):
    m = re.fullmatch(rb"img_size=([0-9]+)", lines[base])
    n = re.fullmatch(rb"img_md5=([0-9a-f]{32})", lines[base + 1])
    if not m or not n or int(m.group(1)) == 0:
        raise SystemExit(f"ota_update.in: bad size/md5 for {name}")
    if not (ota / f"ota_md5_{name}.{n.group(1).decode()}").is_file():
        raise SystemExit(f"missing chunk hash list for {name}")
PY
}

for board in r1 r3proii r3ii_2025; do
    [[ -f $out/$board.upt ]] || continue
    theme_src=$repo/assets/theme2
    [[ $board == r1 ]] || theme_src=$repo/assets/$board/theme2
    logo_src=$repo/assets/$board/etc/logo1.jpeg
    unpack_root "$out/$board.upt" "$work/$board"
    root=$work/$board/root
    check_manifest "$work/$board/upt/ota_v0"
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
    check_manifest "$work/v1/upt/ota_v0"
    grep -aq 'COMPAS_PLAYER_BOARD:tempotec_v1' "$root/usr/bin/compas_player"
    cmp -- "$repo/assets/v1/theme2/usb/usb.png" "$root/usr/resource/litegui/theme2/usb/usb.png"
    cmp -- "$repo/assets/theme2/boot_animation/en/0.png" "$root/usr/resource/litegui/theme2/boot_animation/en/0.png"
    [[ $(awk '{print $1}' "$out/v1_md5.txt") == "$(md5sum "$out/v1.upt" | awk '{print $1}')" ]]
    echo "v1.upt: player marker, assets and v1_md5.txt verified"
fi
