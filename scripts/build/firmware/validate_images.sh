#!/usr/bin/env bash
# Validate the images in a build output directory. For every image: it unpacks,
# ota_update.in satisfies the player's strict parser (firmware_image.c parse_manifest) and the
# kernel/rootfs chunk chains and chain files exist and the image holds no record the player's OTA validator rejects
# (such as ota_compatibility.in). HiBy boards: branding assets match the tracked
# sources, the shipped player is the one in OUT_DIR and no file carries the build machine's paths or forbidden
# words (the path rule is report-only except for r1, see check_no_build_paths below). R1: the Compas Bluetooth stack,
# not HiBy's stock one. V1: the player carries its board marker,
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
            etc/logo.jpeg|etc/logo2.jpeg) [[ $dir == v1 ]] || { echo "assets/$dir/$f is only valid for v1" >&2; exit 1; } ;;
            *) echo "assets/$dir/$f is not board-specific; move it to assets/theme1 or assets/theme2" >&2; exit 1 ;;
        esac
    done < <(cd "$repo/assets/$dir" && find . -type f | sed 's#^\./##' | LC_ALL=C sort)
done

# check_icons ROOT: no image ships a stock icon that nothing loads, and no theme2 icon ships
# next to the Breeze art the player draws instead.
check_icons() {
    python3 -I - "$repo" "$1" <<'PY'
import os, sys
sys.path.insert(0, os.path.join(sys.argv[1], "scripts/firmware/package"))
import pathlib, clean_os
repo, root = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]) / "usr/resource/litegui"
shipped = [p for p in clean_os.unused_asset_paths(repo) if (root / p).exists()]
if shipped:
    raise SystemExit("unused stock images ship in the image: " + ", ".join(shipped[:8]))
# The packaged player must not name a removed image, except these: it names them but always
# draws Breeze art instead (a missing stock file is never opened).
REDIRECTED = {
    "settings/library.png",          # decorate_category_row() -> breeze_rows/settings_library.png
    "settings/playback.png",         # titlebar_breeze_icon() -> titlebar/breeze_playback.png; rows -> breeze_rows/settings_playback.png
    "settings/sound.png",            # titlebar_breeze_icon() -> titlebar/breeze_sound.png; rows -> breeze_rows/settings_sound.png
    "submenu/genres.png",            # decorate_category_row() -> breeze_rows/submenu_genres.png
    "submenu/layouts.png",           # decorate_category_row() -> breeze_rows/submenu_layouts.png
    "submenu/plugins.png",           # decorate_category_row() -> breeze_rows/submenu_plugins.png
    "submenu/themes.png",            # decorate_category_row() -> breeze_rows/submenu_themes.png
    "submenu/emulators.png",         # decorate_category_row() -> breeze_rows/submenu_emulators.png
    "submenu/refresh_covers.png",    # decorate_category_row() -> breeze_rows/submenu_refresh_covers.png
    "submenu/refresh_metadata.png",  # decorate_category_row() -> breeze_rows/submenu_refresh_metadata.png
    "submenu/update_database.png",   # decorate_category_row() -> breeze_rows/submenu_update_database.png
    "submenu/music_database.png",    # titlebar_breeze_icon() -> titlebar/breeze_database.png
    "power_action/screen_off.png",   # power_hub_card() -> breeze_rows/power_action_screen_off.png
    "power_action/sleep_timer.png",  # power_hub_card() -> breeze_rows/power_action_sleep_timer.png
    "navigation/reorder.png",        # set_reorder_handle_icon() -> titlebar/breeze_handle.png
    "navigation/back.png",           # build_header_back_button() -> titlebar/breeze_back.png
    "navigation/more.png",           # titlebar_breeze_icon() -> titlebar/breeze_menu.png (headers, compact_list trailing)
    "navigation/search.png",         # titlebar_breeze_icon() -> titlebar/breeze_search.png
    "power_action/power.png",        # power_hub_card() -> breeze_rows/power_action_power.png
    "power_action/reboot.png",       # power_hub_card() -> breeze_rows/power_action_reboot.png
    "submenu/bluetooth.png",         # decorate_category_row() -> breeze_rows/submenu_bluetooth.png
    "submenu/usb.png",               # decorate_category_row() -> breeze_rows/submenu_usb.png
    "settings/about.png",            # legacy inventory only; Settings rows use breeze_rows/settings_about.png
    "settings/display.png",          # decorate_category_row() -> breeze_rows/settings_display.png
    "settings/music.png",            # legacy inventory only; breeze_rows/settings_music.png
    "settings/power.png",            # decorate_category_row() -> breeze_rows/settings_power.png
    "settings/system.png",           # decorate_category_row() -> breeze_rows/settings_system.png
    "stream_media/podcasts_row.png", # Stream Media row (Podcasts plugin) -> breeze_rows/stream_media_podcasts_row.png
    "stream_media/podcasts_row_s.png",   # gui_themes.c inventory / plugin_manager "_s" derivation; category rows never draw it
    "stream_media/radio_row.png",    # Stream Media row (NetRadio, RadioBrowser) -> breeze_rows/stream_media_radio_row.png
    "stream_media/radio_row_s.png",  # same: pressed copy, not drawn
    "stream_media/subsonic_row.png", # build_stream_media_screen() -> breeze_rows/stream_media_subsonic_row.png
    "stream_media/subsonic_row_s.png",   # same: pressed copy, not drawn
    "sub_back/btn_playlist.png",     # resolve_file_row_icon() -> breeze_rows/sub_back_btn_playlist.png
    "sub_back/btn_playlist_s.png",   # pressed copy, not drawn
    "touch_list/list_folder.png",    # resolve_file_row_icon() -> breeze_rows/touch_list_list_folder.png
    "submenu/album_artist.png",      # build_music_screen() rows -> breeze_rows/submenu_album_artist.png
    "submenu/albums.png",            # build_music_screen() rows -> breeze_rows/submenu_albums.png
    "submenu/all_songs.png",         # build_music_screen() rows -> breeze_rows/submenu_all_songs.png
    "submenu/artists.png",           # build_music_screen() rows -> breeze_rows/submenu_artists.png
    "submenu/books.png",             # gui_books.c decorate_category_row() -> breeze_rows/submenu_books.png
    "submenu/favorites.png",         # gui_books.c decorate_category_row() -> breeze_rows/submenu_favorites.png
    "submenu/files.png",             # Music and More rows -> breeze_rows/submenu_files.png
    "submenu/playlists.png",         # build_music_screen() rows -> breeze_rows/submenu_playlists.png
    "wireless/list_airplay.png",     # build_wireless_screen() -> breeze_rows/wireless_list_airplay.png
    "wireless/list_bt.png",          # build_wireless_screen() -> breeze_rows/wireless_list_bt.png
    "wireless/list_dlna.png",        # build_wireless_screen() -> breeze_rows/wireless_list_dlna.png
    "wireless/list_remote.png",      # build_wireless_screen() -> breeze_rows/wireless_list_remote.png
    "wireless/list_wifi.png",        # build_wireless_screen() -> breeze_rows/wireless_list_wifi.png
}
import re
player = (pathlib.Path(sys.argv[2]) / "usr/bin/compas_player").read_bytes()
named = set()
for p in clean_os.unused_asset_paths(repo):
    rel = p.split("/", 1)[1]
    if rel not in REDIRECTED and re.search(rb"(?<![A-Za-z0-9_/.-])" + re.escape(rel.encode()) + rb"\0", player):
        named.add(rel)
if named:
    raise SystemExit("compas_player names images the manifest removes: " + ", ".join(sorted(named)))
theme2 = root / "theme2"
folders = sorted((d.name for d in theme2.iterdir() if d.is_dir()), key=len, reverse=True)
stale = []
for art in sorted((theme2 / "breeze_rows").glob("*.png")):
    folder = next((f for f in folders if art.name.startswith(f + "_")), None)
    if folder is None:
        continue
    stock = f"{folder}/{art.name[len(folder) + 1:]}"
    if (theme2 / stock).exists():
        stale.append(stock)
if stale:
    raise SystemExit("superseded stock icons ship next to their Breeze art: " + ", ".join(stale))
PY
}

# check_bluetooth_overlay ROOT LABEL: the BlueALSA SSC daemon and the patched BlueZ daemons (bluetoothd,
# cover-art obexd) are the pinned overlay binaries, and the cover-art responder is installed.
check_bluetooth_overlay() {
    local root=$1 label=$2 want path
    while read -r want path; do
        [[ $(sha256sum "$root/$path" | awk '{print $1}') == "$want" ]] || {
            echo "$label: /$path is not the pinned overlay binary" >&2; exit 1; }
    done < "$repo/firmware/ssc-overlay.sha256"
    [[ -x $root/etc/init.d/S81compas_obex && -f $root/etc/dbus-1/system.d/org.bluez.obex.conf &&
       -f $root/etc/dbus-1/system.d/org.mpris.MediaPlayer2.compas.conf ]] || {
        echo "$label: the OBEX cover-art responder is not installed" >&2; exit 1; }
    grep -qx 'BroadcomHighPriority = true' "$root/etc/bluetooth/main.conf" || {
        echo "$label: main.conf lacks BroadcomHighPriority = true" >&2; exit 1; }
    [[ $(readlink "$root/usr/lib/libbluetooth.so.3") == libbluetooth.so.3.19.16 ]] || {
        echo "$label: libbluetooth.so.3 does not point at the BlueZ 5.87 library" >&2; exit 1; }
}

# check_ota_entries UPT_DIR LABEL: the unpacked image holds only records the player's OTA validator accepts.
check_ota_entries() {
    python3 -I "$repo/scripts/build/firmware/check_ota_entries.py" "$1" || {
        echo "$2: the image carries a record the player's OTA validator rejects" >&2; exit 1; }
}

# check_bluetooth_stack ROOT LABEL: R1 keeps the Compas Bluetooth stack (BlueZ 5.87, GLib 2.84, D-Bus 1.16,
# SSC BlueALSA, codec libraries), never HiBy's stock one, and both bt_init branches and bt_resume launch
# bluealsad with the Compas flags.
check_bluetooth_stack() {
    local root=$1 label=$2 flags='-p a2dp-source --a2dp-force-audio-cd --all-codecs' want link f
    for want in 'usr/lib/libbluetooth.so.3 libbluetooth.so.3.19.16' 'usr/lib/libglib-2.0.so.0 libglib-2.0.so.0.8400.4' \
                'usr/lib/libdbus-1.so.3 libdbus-1.so.3.38.3'; do
        link=${want% *}
        [[ $(readlink "$root/$link") == "${want#* }" && -f $root/usr/lib/${want#* } ]] || {
            echo "$label: /$link does not point at ${want#* }" >&2; exit 1; }
    done
    for f in libfdk-aac.so.2.0.3 libldacBT_enc.so.2 libldacBT_abr.so.2 libldacdec.so.1 libopenaptx.so.0 libsbc.so.1.3.2 \
             libspeexdsp.so.1; do
        [[ -e $root/usr/lib/$f ]] || { echo "$label: codec library $f is missing" >&2; exit 1; }
    done
    [[ $(readlink "$root/usr/lib/libfdk-aac.so.2") == libfdk-aac.so.2.0.3 &&
       $(readlink "$root/usr/lib/libsbc.so.1") == libsbc.so.1.3.2 ]] || {
        echo "$label: libfdk-aac.so.2 or libsbc.so.1 does not point at the Compas build" >&2; exit 1; }
    grep -aq 'ssc_native_' "$root/usr/bin/bluealsad" && grep -aq -- '--ssc-auto-profile' "$root/usr/bin/bluealsad" || {
        echo "$label: bluealsad lacks the SSC support (ssc_native_*, --ssc-auto-profile)" >&2; exit 1; }
    [[ $(grep -c "^[[:space:]]*/usr/bin/bluealsad $flags &\$" "$root/usr/bin/bt_init") -ge 2 ]] || {
        echo "$label: bt_init does not start bluealsad with the Compas flags in both branches" >&2; exit 1; }
    grep -q "^[[:space:]]*/usr/bin/bluealsad $flags &\$" "$root/usr/bin/bt_resume" || {
        echo "$label: bt_resume does not start bluealsad with the Compas flags" >&2; exit 1; }
    ! grep -Eq '/usr/bin/bluealsa( |$)' "$root/usr/bin/bt_init" "$root/usr/bin/bt_resume" || {
        echo "$label: bt_init or bt_resume still start HiBy's stock bluealsa" >&2; exit 1; }
    grep -qx 'AutoEnable=false' "$root/etc/bluetooth/main.conf" || {
        echo "$label: main.conf lacks AutoEnable=false" >&2; exit 1; }
    # AIC units get the device name from bt_enable_aic.sh (which the player runs to power Bluetooth), reading
    # /usr/resource/bt_name, the file the user's device name is bind-mounted over.
    grep -q 'bt-adapter --set "Alias" "\$bt_name"' "$root/usr/bin/bt_enable_aic.sh" || {
        echo "$label: bt_enable_aic.sh does not set the Bluetooth alias from bt_name" >&2; exit 1; }
}

# check_no_build_paths ROOT LABEL [ENFORCE]: no file, file name or symlink target of the rootfs carries the
# build machine's home path, user or host name (see check_no_build_paths.py; unmodified HiBy vendor files are
# pinned by hash; extra forbidden words come from an untracked local list). The forbidden words always fail.
# TODO: the /home/ rule is enforced for r1 only. r3proii, r3ii_2025 and V1 still carry HiBy vendor files with
# /home/ paths that vendor_home_paths.txt does not list yet (scripts/build/firmware/vendor_home_paths_pending.txt);
# they are reported as warnings until those bases are rebuilt or their vendor files are pinned. Then drop ENFORCE.
check_no_build_paths() {
    local mode=--warn-only
    [[ ${3:-} != enforce ]] || mode=
    python3 -I "$repo/scripts/build/firmware/check_no_build_paths.py" ${mode:+"$mode"} "$1" || {
        echo "$2: the image carries build machine paths or names" >&2; exit 1; }
}

for board in r1 r3proii r3ii_2025; do
    [[ -f $out/$board.upt ]] || continue
    theme_src=$repo/assets/theme2
    [[ $board == r1 ]] || theme_src=$repo/assets/$board/theme2
    logo_src=$repo/assets/$board/etc/logo1.jpeg
    unpack_root "$out/$board.upt" "$work/$board"
    root=$work/$board/root
    check_manifest "$work/$board/upt/ota_v0"
    check_ota_entries "$work/$board/upt" "$board.upt"
    cmp -- "$logo_src" "$root/etc/logo1.jpeg"
    cmp -- "$theme_src/boot_animation/en/0.jpg" "$root/usr/resource/litegui/theme2/boot_animation/en/0.jpg"
    cmp -- "$theme_src/boot_animation/en/0.png" "$root/usr/resource/litegui/theme2/boot_animation/en/0.png"
    suffix=_$board; [[ $board != r1 ]] || suffix=
    cmp -- "$out/compas_player$suffix" "$root/usr/bin/compas_player"
    check_icons "$root"
    check_bluetooth_overlay "$root" "$board.upt"
    enforce=; [[ $board != r1 ]] || { enforce=enforce; check_bluetooth_stack "$root" "$board.upt"; }
    check_no_build_paths "$root" "$board.upt" $enforce
    echo "$board.upt: branding assets, icon set, player, overlay daemons and build paths verified"
done

if [[ -f $out/v1.upt ]]; then
    unpack_root "$out/v1.upt" "$work/v1"
    root=$work/v1/root
    check_manifest "$work/v1/upt/ota_v0"
    check_ota_entries "$work/v1/upt" v1.upt
    grep -aq 'COMPAS_PLAYER_BOARD:tempotec_v1' "$root/usr/bin/compas_player"
    cmp -- "$repo/assets/v1/theme2/usb/usb.png" "$root/usr/resource/litegui/theme2/usb/usb.png"
    # Panel-sized (240x320) artwork, not the shared 480x800 one.
    for logo in logo.jpeg logo1.jpeg logo2.jpeg; do
        cmp -- "$repo/assets/v1/etc/$logo" "$root/etc/$logo"
        [[ $(file -b "$repo/assets/v1/etc/$logo") == *"JPEG image data"*240x320* ]] || {
            echo "v1.upt: assets/v1/etc/$logo is not a 240x320 JPEG" >&2; exit 1; }
    done
    cmp -- "$repo/assets/v1/theme2/boot_animation/en/0.jpg" "$root/usr/resource/litegui/theme2/boot_animation/en/0.jpg"
    cmp -- "$repo/assets/v1/theme2/boot_animation/en/0.png" "$root/usr/resource/litegui/theme2/boot_animation/en/0.png"
    [[ $(file -b "$repo/assets/v1/theme2/boot_animation/en/0.jpg") == *"JPEG image data"*240x320* ]] &&
        [[ $(file -b "$repo/assets/v1/theme2/boot_animation/en/0.png") == *"PNG image data, 240 x 320"* ]] || {
        echo "v1.upt: boot animation is not 240x320" >&2; exit 1; }
    check_icons "$root"
    check_bluetooth_overlay "$root" v1.upt
    check_no_build_paths "$root" v1.upt
    grep -qx 'DiscoverableTimeout = 0' "$root/etc/bluetooth/main.conf" &&
        grep -qx 'AutoEnable=false' "$root/etc/bluetooth/main.conf" || {
        echo "v1.upt: main.conf lacks the V1 Bluetooth options" >&2; exit 1; }
    [[ $(awk '{print $1}' "$out/v1_md5.txt") == "$(md5sum "$out/v1.upt" | awk '{print $1}')" ]]
    echo "v1.upt: player marker, assets, BlueZ stack and v1_md5.txt verified"
fi
