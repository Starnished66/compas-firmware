#!/usr/bin/env python3
"""Fail if an unpacked update image carries a record the player's OTA validator rejects.

Usage: check_ota_entries.py UNPACKED_UPT_DIR

The player (firmware_image.c) accepts only ota_config.in and, in ota_v0, ota_update.in, ota_v0.ok, the
ota_md5_* chain lists and the xImage / rootfs.squashfs chunks. Anything else, such as HiBy 2.0's
ota_v0/ota_compatibility.in, makes every in-app update fail with "unexpected OTA image record", and
players already in the field cannot change. Exit status: 0 clean, 1 unexpected entries, 2 usage error.
"""
from __future__ import annotations

import pathlib
import re
import sys

ALLOWED = re.compile(
    r"(?:ota_config\.in|ota_v0|ota_v0/(?:ota_update\.in|ota_v0\.ok|"
    r"ota_md5_(?:rootfs\.squashfs|xImage)\.[0-9a-f]{32}|"
    r"(?:rootfs\.squashfs|xImage)\.[0-9]{4}\.[0-9a-f]{32}))")


def unexpected(root: pathlib.Path) -> list:
    return sorted(str(p.relative_to(root)) for p in root.rglob("*")
                  if not ALLOWED.fullmatch(str(p.relative_to(root))))


def main() -> int:
    if len(sys.argv) != 2 or not pathlib.Path(sys.argv[1]).is_dir():
        print(__doc__, file=sys.stderr)
        return 2
    bad = unexpected(pathlib.Path(sys.argv[1]))
    for rel in bad:
        print(f"OTA entry check: unexpected record in the image: {rel}", file=sys.stderr)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
