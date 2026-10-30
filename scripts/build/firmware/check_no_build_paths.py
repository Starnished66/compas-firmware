#!/usr/bin/env python3
"""Fail if a firmware root filesystem carries the build machine's paths or names.

Usage: check_no_build_paths.py ROOT [--vendor-list FILE] [--forbidden-words FILE] [--warn-only]
                               [--print-vendor-entries]

Scanned: the bytes of every regular file (binaries included), every file and directory name, and the
target of every symbolic link.
  * A `/home/<name>/` path is a build path and is not allowed, except in a vendor file that ships exactly
    as HiBy built it: FILE (default vendor_home_paths.txt next to this script) lists those as
    `SHA-256  rootfs/path`, one per line. The hash has to match, so a rebuilt or replaced file is
    checked again. An absolute symlink target or entry name under /home/<name>/ is never excused.
  * Forbidden words (the builder's user name, host name and the like) are never allowed anywhere and
    the vendor list never excuses them. They are not tracked in this repository; they are read, one per
    line (`#` starts a comment), from the first of these that exist, all of which are merged:
      - the file given with --forbidden-words,
      - the COMPAS_FORBIDDEN_WORDS environment variable (words separated by commas or whitespace),
      - <git dir>/info/forbidden-words (not tracked),
      - ~/.config/compas/forbidden-words.
    The matched word is masked in the report so the log does not repeat it.
--warn-only reports the `/home/` findings but exits 0 (TODO: used for the r3proii, r3ii_2025 and V1
images until their bases are rebuilt without HiBy's /home/ vendor files; remove it then). Forbidden
words always fail.
--print-vendor-entries prints list lines for the files that only fail on the `/home/` rule, for a
reviewer to confirm are unmodified vendor files before adding them.
Exit status: 0 clean, 1 offending files, 2 usage error.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import pathlib
import re
import subprocess
import sys

HOME = re.compile(rb"/home/[A-Za-z_][A-Za-z0-9_.-]*/")
DEFAULT_LIST = pathlib.Path(__file__).with_name("vendor_home_paths.txt")


def parse_words(text: str) -> list:
    words = []
    for line in text.splitlines():
        line = line.split("#", 1)[0]
        words += [w for w in re.split(r"[\s,]+", line) if w]
    return words


def load_forbidden(extra: pathlib.Path | None = None) -> list:
    """Return the forbidden words as bytes, from the untracked local sources."""
    texts = []
    if extra is not None:
        texts.append(extra.read_text())
    texts.append(os.environ.get("COMPAS_FORBIDDEN_WORDS", ""))
    candidates = [pathlib.Path.home() / ".config/compas/forbidden-words"]
    try:
        git_dir = subprocess.run(["git", "-C", str(pathlib.Path(__file__).parent), "rev-parse",
                                  "--path-format=absolute", "--git-common-dir"],
                                 capture_output=True, text=True, check=True).stdout.strip()
        candidates.append(pathlib.Path(git_dir) / "info/forbidden-words")
    except (OSError, subprocess.CalledProcessError):
        pass
    for path in candidates:
        if path.is_file():
            texts.append(path.read_text())
    seen, out = set(), []
    for text in texts:
        for word in parse_words(text):
            if word.lower() not in seen:
                seen.add(word.lower())
                out.append(word.encode())
    return out


def load_vendor(path: pathlib.Path) -> dict:
    out = {}
    if not path.is_file():
        return out
    for number, line in enumerate(path.read_text().splitlines(), 1):
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        fields = line.split(None, 1)
        if len(fields) != 2 or not re.fullmatch(r"[0-9a-f]{64}", fields[0]):
            raise SystemExit(f"{path}:{number}: expected 'SHA-256  rootfs/path'")
        out.setdefault(fields[1].strip().lstrip("/"), set()).add(fields[0])
    return out


def mask(snippet: bytes, words: re.Pattern | None) -> bytes:
    return words.sub(b"***", snippet) if words else snippet


def scan(root: pathlib.Path, vendor: dict, forbidden: list = ()):
    """Return (offenders, vendor_only): offenders are (rel, kind, why, snippet), kind 'word' or 'home';
    vendor_only are (rel, sha) of regular files that fail only on the /home/ rule."""
    words = re.compile(b"|".join(re.escape(w) for w in forbidden), re.I) if forbidden else None
    offenders, vendor_only = [], []

    def check_text(rel: str, text: bytes, what: str) -> bool:
        """Check a name or link target; True if it was an offender."""
        if words and (m := words.search(text)):
            offenders.append((rel, "word", f"forbidden word in {what}", mask(text, words)))
            return True
        if what == "symlink target" and (m := HOME.search(text)):
            offenders.append((rel, "home", "/home/ symlink target", text))
            return True
        return False

    for parent, dirs, names in os.walk(root):
        dirs.sort()
        for name in sorted(dirs + names):
            p = pathlib.Path(parent) / name
            rel = str(p.relative_to(root))
            if check_text(rel, os.fsencode(rel), "entry name"):
                continue
            if p.is_symlink():
                check_text(rel, os.fsencode(os.readlink(p)), "symlink target")
                continue
            if name in names and p.is_file():
                data = p.read_bytes()
                if words and (m := words.search(data)):
                    lo = max(0, m.start() - 40)
                    offenders.append((rel, "word", "forbidden word", mask(data[lo:m.end() + 60], words)))
                    continue
                m = HOME.search(data)
                if not m:
                    continue
                digest = hashlib.sha256(data).hexdigest()
                if digest in vendor.get(rel, ()):
                    continue
                vendor_only.append((rel, digest))
                offenders.append((rel, "home", "/home/ build path", data[m.start():m.end() + 80]))
    return offenders, vendor_only


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("root", type=pathlib.Path)
    ap.add_argument("--vendor-list", type=pathlib.Path, default=DEFAULT_LIST)
    ap.add_argument("--forbidden-words", type=pathlib.Path)
    ap.add_argument("--warn-only", action="store_true")
    ap.add_argument("--print-vendor-entries", action="store_true")
    args = ap.parse_args()
    if not args.root.is_dir():
        print(f"check_no_build_paths: not a directory: {args.root}", file=sys.stderr)
        return 2
    if args.forbidden_words and not args.forbidden_words.is_file():
        print(f"check_no_build_paths: not a file: {args.forbidden_words}", file=sys.stderr)
        return 2
    offenders, vendor_only = scan(args.root, load_vendor(args.vendor_list), load_forbidden(args.forbidden_words))
    if args.print_vendor_entries:
        for rel, digest in vendor_only:
            print(f"{digest}  {rel}")
        return 0
    failing = 0
    for rel, kind, why, snippet in offenders:
        text = re.sub(rb"[^\x20-\x7e]", b"?", snippet).decode()
        soft = args.warn_only and kind == "home"
        failing += not soft
        print(f"build path check: {'warning: ' if soft else ''}/{rel}: {why}: ...{text}", file=sys.stderr)
    if failing:
        print(f"build path check: {failing} entr(ies) carry the build machine's paths or names", file=sys.stderr)
        return 1
    if offenders:
        print(f"build path check: {len(offenders)} /home/ finding(s) reported only (--warn-only)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
