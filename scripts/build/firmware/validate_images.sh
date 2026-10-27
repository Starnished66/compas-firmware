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

# Per-board folders hold only what differs per board: the boot animation at the board's
# resolution, etc/logo1.jpeg and a board-specific USB DAC overlay. Shared icons live in
# assets/theme1 and assets/theme2 and are never duplicated per board.
for dir in r1 r3proii r3ii_2025 v1; do
    while IFS= read -r f; do
        case $f in
            theme2/boot_animation/en/0.jpg|theme2/boot_animation/en/0.png|theme2/boot_animation/en/config.ini) ;;
            etc/logo1.jpeg|theme2/usb/usb.png) ;;
            *) echo "assets/$dir/$f is not board-specific; move it to assets/theme1 or assets/theme2" >&2; exit 1 ;;
        esac
    done < <(cd "$repo/assets/$dir" && find . -type f | sed 's#^\./##' | LC_ALL=C sort)
done

# check_icons ROOT: no image ships a stock icon that nothing loads, and no icon ships whose
# Breeze replacement is what the player draws (the legacy-inventory names are the only ones
# kept; gui_themes.c compares leftover legacy theme copies with the stock file of that name).
check_icons() {
    python3 -I - "$repo" "$1" <<'PY'
import os, sys
sys.path.insert(0, os.path.join(sys.argv[1], "scripts/firmware/package"))
import pathlib, clean_os
repo, root = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]) / "usr/resource/litegui"
shipped = [p for p in clean_os.unused_asset_paths(repo) if (root / p).exists()]
if shipped:
    raise SystemExit("unused stock images ship in the image: " + ", ".join(shipped[:8]))
LEGACY_KEPT = {
    "navigation/back.png", "navigation/more.png", "navigation/search.png",
    "power_action/power.png", "power_action/reboot.png",
    "settings/about.png", "settings/display.png", "settings/music.png", "settings/power.png", "settings/system.png",
    "stream_media/podcasts_row.png", "stream_media/radio_row.png", "stream_media/subsonic_row.png",
    "sub_back/btn_playlist.png", "touch_list/list_folder.png",
    "submenu/album_artist.png", "submenu/albums.png", "submenu/all_songs.png", "submenu/artists.png",
    "submenu/bluetooth.png", "submenu/books.png", "submenu/favorites.png", "submenu/files.png",
    "submenu/playlists.png", "submenu/usb.png",
    "wireless/list_airplay.png", "wireless/list_bt.png", "wireless/list_dlna.png",
    "wireless/list_remote.png", "wireless/list_wifi.png",
}
theme2 = root / "theme2"
folders = sorted((d.name for d in theme2.iterdir() if d.is_dir()), key=len, reverse=True)
stale = []
for art in sorted((theme2 / "breeze_rows").glob("*.png")):
    folder = next((f for f in folders if art.name.startswith(f + "_")), None)
    if folder is None:
        continue
    stock = f"{folder}/{art.name[len(folder) + 1:]}"
    if (theme2 / stock).exists() and stock not in LEGACY_KEPT:
        stale.append(stock)
if stale:
    raise SystemExit("superseded stock icons ship next to their Breeze art: " + ", ".join(stale))
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
    check_icons "$root"
    echo "$board.upt: branding assets, icon set and player verified"
done

if [[ -f $out/v1.upt ]]; then
    unpack_root "$out/v1.upt" "$work/v1"
    root=$work/v1/root
    check_manifest "$work/v1/upt/ota_v0"
    grep -aq 'COMPAS_PLAYER_BOARD:tempotec_v1' "$root/usr/bin/compas_player"
    cmp -- "$repo/assets/v1/theme2/usb/usb.png" "$root/usr/resource/litegui/theme2/usb/usb.png"
    cmp -- "$repo/assets/theme2/boot_animation/en/0.png" "$root/usr/resource/litegui/theme2/boot_animation/en/0.png"
    check_icons "$root"
    [[ $(awk '{print $1}' "$out/v1_md5.txt") == "$(md5sum "$out/v1.upt" | awk '{print $1}')" ]]
    echo "v1.upt: player marker, assets and v1_md5.txt verified"
fi
