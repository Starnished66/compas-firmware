#!/usr/bin/env bash
# Replace /usr/bin/compas_player inside a published .upt and repack it the same way
# the canonical repack_upt.sh does. Everything else in the image is kept byte for byte.
#   swap_player.sh BASE.upt NEW_PLAYER BOARD_MARKER LABEL OUT.upt
set -euo pipefail
base=$1 player=$2 board=$3 label=$4 out=$5
work=$(mktemp -d "${TMPDIR:-/tmp}/swap.XXXXXX")
trap 'rm -rf -- "$work"' EXIT

# The new player must carry exactly one vX.Y.Z (what Compás Tools reads) and its board.
versions=$(grep -a -o 'v[0-9][0-9]*\.[0-9][0-9]*\.[0-9][0-9]*' "$player" | sort -u)
[[ "$versions" == "$label" ]] || { echo "player versions: '$versions', want '$label'" >&2; exit 1; }
boards=$(grep -a -o 'COMPAS_PLAYER_BOARD:[a-z0-9_]*' "$player" | sort -u | grep -v ':$')
[[ "$boards" == "COMPAS_PLAYER_BOARD:$board" ]] || { echo "player board: '$boards'" >&2; exit 1; }
! grep -a -q 'Development Build' "$player" || { echo "player still says Development Build" >&2; exit 1; }

7z x -y -o"$work/iso" "$base" >/dev/null
ota="$work/iso/ota_v0"
cat $(ls "$ota"/rootfs.squashfs.[0-9]* | sort) > "$work/rootfs.squashfs"
cat $(ls "$ota"/xImage.[0-9]* | sort) > "$work/xImage"
[[ $(md5sum < "$work/rootfs.squashfs" | cut -d' ' -f1) == $(sed -n 's/^img_md5=//p' "$ota/ota_update.in" | sed -n 2p) ]] \
    || { echo "base rootfs md5 mismatch" >&2; exit 1; }
unsquashfs -q -no-xattrs -d "$work/root" "$work/rootfs.squashfs" >/dev/null
install -m 0755 "$player" "$work/root/usr/bin/compas_player"
mksquashfs "$work/root" "$work/new-rootfs.squashfs" -comp lzo -all-root -noappend -no-xattrs >/dev/null

# Same file list, modes and contents as before, except the player.
list() { unsquashfs -lls "$1" | awk '{print $1, $6}' | sort; }
diff <(list "$work/rootfs.squashfs") <(list "$work/new-rootfs.squashfs") >/dev/null \
    || { echo "file list or modes changed" >&2; exit 1; }

mkdir -p "$work/new-iso/ota_v0"
package_image() {
    local image=$1 name=$2 dest=$3 initial_md5 size chain previous part part_md5
    initial_md5=$(md5sum "$image" | awk '{print $1}')
    size=$(stat -c%s "$image")
    chain="$dest/ota_md5_${name}.${initial_md5}"
    : > "$chain"
    split -b 512k --numeric-suffixes=0 -a 4 "$image" "$dest/${name}."
    previous=$initial_md5
    for part in "$dest/${name}."[0-9]*; do
        part_md5=$(md5sum "$part" | awk '{print $1}')
        echo "$part_md5" >> "$chain"
        mv "$part" "$part.$previous"
        previous=$part_md5
    done
    printf '%s %s %s\n' "$name" "$size" "$initial_md5"
}
read -r root_name root_size root_md5 < <(package_image "$work/new-rootfs.squashfs" rootfs.squashfs "$work/new-iso/ota_v0")
read -r kernel_name kernel_size kernel_md5 < <(package_image "$work/xImage" xImage "$work/new-iso/ota_v0")
cat > "$work/new-iso/ota_v0/ota_update.in" <<EOF
ota_version=0
img_type=kernel
img_name=$kernel_name
img_size=$kernel_size
img_md5=$kernel_md5
img_type=rootfs
img_name=$root_name
img_size=$root_size
img_md5=$root_md5
EOF
: > "$work/new-iso/ota_v0/ota_v0.ok"
cp "$work/iso/ota_config.in" "$work/new-iso/ota_config.in"
genisoimage -quiet -f -U -J -joliet-long -r -allow-lowercase -allow-multidot -o "$out" "$work/new-iso"
(( $(stat -c%s "$out") <= 45 * 1024 * 1024 )) || { echo "image over 45 MiB" >&2; exit 1; }
cmp -s "$work/xImage" <(cat $(ls "$work/new-iso/ota_v0"/xImage.[0-9]* | sort)) || { echo "kernel changed" >&2; exit 1; }
echo "OK $out $(stat -c%s "$out") $(sha256sum "$out" | cut -d' ' -f1)"
