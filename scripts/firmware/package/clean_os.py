#!/usr/bin/env python3
"""Apply the small, audited Compas cleanup to an extracted firmware root."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any


INACTIVE_SUFFIXES = (".oem", ".bak", ".orig")
RESOURCE_DIRS = ("coordinate", "hl_json", "layout", "str", "unicode")
THEME_NAMESPACES = (
    "boot_animation", "breeze_rows", "bt", "category", "keyboard", "launcher",
    "navigation", "player_layouts", "playing_plane", "playlist_actions",
    "power_action", "pull_down", "settings", "stream_media", "sub_back",
    "submenu", "themes", "titlebar", "topbar", "touch_list", "volume", "wireless",
)
OLD_HOST_ALIASES = {"ingenic", "hiby", "buildroot"}
BT_ALIAS_FOOTER = '''# Set the branded BlueZ alias from the configured Bluetooth name.
if [ -f /usr/resource/bt_name ]; then
    bt_name=$(cat /usr/resource/bt_name)
    bt-adapter --set "Alias" "$bt_name" >/dev/null 2>&1 || true
fi
'''
RESOURCE_REF_RE = re.compile(
    r"(?:/usr/resource/|/resource/)(?P<absolute>coordinate|hl_json|layout|str|unicode)(?:/|\b)"
    r"|(?<![A-Za-z0-9_])(?P<relative>coordinate|hl_json|layout|str|unicode)/"
)


UNUSED_ASSETS_MANIFEST = "firmware/unused_assets.txt"


def unused_asset_paths(repo: Path) -> list[str]:
    """Expand firmware/unused_assets.txt into litegui-relative paths (theme1/..., theme2/...)."""
    paths: list[str] = []
    for number, raw in enumerate((repo / UNUSED_ASSETS_MANIFEST).read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = Path(line).parts
        if ".." in parts or line.startswith("/") or len(parts) < 3 or parts[0] not in ("*", "theme1", "theme2"):
            raise ValueError(f"{UNUSED_ASSETS_MANIFEST}:{number}: bad path {line!r}")
        for theme in (("theme1", "theme2") if parts[0] == "*" else (parts[0],)):
            paths.append("/".join((theme,) + parts[1:]))
    return paths


def _inside(root: Path, rel: str) -> Path:
    """Return a root-relative path while rejecting symlinked ancestors."""
    path = root / rel
    current = root
    for part in Path(rel).parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"unsafe symlink in firmware path: /{current.relative_to(root)}")
    return path


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="surrogateescape")


def _active_helper_blockers(root: Path, repo: Path) -> dict[str, list[str]]:
    """Find active shell/helper references before removing legacy resources."""
    candidates: set[Path] = set()
    for base in (root / "etc", root / "usr/bin", repo / "scripts", repo / "firmware"):
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if path.is_file() and not path.is_symlink() and (
                path.suffix in {".sh", ".conf"} or path.name.startswith(("S", "T"))
            ):
                candidates.add(path)
    blockers: dict[str, set[str]] = {name: set() for name in RESOURCE_DIRS}
    for path in candidates:
        try:
            lines = _read_text(path).splitlines()
        except (OSError, UnicodeError):
            continue
        for number, line in enumerate(lines, 1):
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue
            for match in RESOURCE_REF_RE.finditer(line):
                name = match.group("absolute") or match.group("relative")
                blockers[name].add(f"{path}:{number}")
    return {name: sorted(refs) for name, refs in blockers.items() if refs}


def _binary_resource_blockers(root: Path) -> dict[str, list[str]]:
    """Inspect retained executable/library strings for legacy resource names."""
    terms = (b"coordinate", b"hl_json", b"layout", b"str", b"unicode")
    patterns = {
        term: (
            re.compile(rb"(?:/usr/resource/|/resource/)" + re.escape(term) + rb"(?:/|\x00|$)"),
            re.compile(rb"(?<![A-Za-z0-9_])" + re.escape(term) + rb"/"),
        )
        for term in terms
    }
    # hl_json can be assembled as a bare NUL-terminated directory string;
    # other basenames are only meaningful when followed by a path separator.
    patterns[b"hl_json"] += (re.compile(rb"(?<![A-Za-z0-9_])hl_json\x00"),)
    hits: dict[str, set[str]] = {term.decode("ascii"): set() for term in terms}
    for rel in ("usr/bin", "usr/sbin", "usr/libexec", "usr/lib"):
        base = root / rel
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or path.is_symlink():
                continue
            try:
                data = path.read_bytes()
            except OSError:
                continue
            for term, term_patterns in patterns.items():
                if any(pattern.search(data) for pattern in term_patterns):
                    # Keep the report to paths and resource directory names only.
                    hits[term.decode("ascii")].add(str(path))
    return {name: sorted(refs) for name, refs in hits.items() if refs}


def _remove(path: Path, rel: str, removed: list[dict[str, Any]]) -> None:
    if path.is_symlink():
        path.unlink()
        removed.append({"path": "/" + rel.lstrip("/"), "bytes": 0})
        return
    if not path.is_file():
        return
    size = path.stat().st_size
    path.unlink()
    removed.append({"path": "/" + rel.lstrip("/"), "bytes": size})


def _remove_tree(path: Path, root: Path, removed: list[dict[str, Any]]) -> None:
    """Remove a directory and account for each removed entry."""
    entries = sorted(path.rglob("*"), key=lambda p: len(p.parts), reverse=True)
    for entry in entries:
        rel = "/" + entry.relative_to(root).as_posix()
        if entry.is_symlink():
            entry.unlink()
            removed.append({"path": rel, "bytes": 0})
        elif entry.is_file():
            _remove(entry, rel, removed)
        elif entry.is_dir():
            entry.rmdir()
            removed.append({"path": rel, "bytes": 0})
    path.rmdir()
    removed.append({"path": "/" + path.relative_to(root).as_posix(), "bytes": 0})


def _prune_tree(root: Path, rel: str, keep_names: set[str], canonical: set[str],
                removed: list[dict[str, Any]]) -> None:
    base = _inside(root, rel)
    if not base.exists():
        return
    for child in sorted(base.iterdir(), key=lambda p: p.name):
        child_rel = child.relative_to(root).as_posix()
        if (child.name in keep_names or child_rel in canonical or
                any(item.startswith(child_rel + "/") for item in canonical)):
            continue
        if child.is_dir() and not child.is_symlink():
            _remove_tree(child, root, removed)
        else:
            _remove(child, child_rel, removed)


def prepare(root: str | os.PathLike[str], repo: str | os.PathLike[str]) -> dict[str, Any]:
    """Clean an extracted firmware root and return a machine-readable report."""
    root_path = Path(root).resolve()
    repo_path = Path(repo).resolve()
    if not root_path.is_dir() or not repo_path.is_dir():
        raise ValueError("root and repo must be existing directories")
    if (root_path == Path("/") or not _inside(root_path, "usr/resource/config.json").is_file()
            or not _inside(root_path, "module_driver").is_dir()):
        raise ValueError("root must be an extracted supported firmware tree")

    report: dict[str, Any] = {"root": str(root_path), "removed": [], "naming_updates": [],
                              "protected": [], "blocked_resource_dirs": []}
    removed: list[dict[str, Any]] = report["removed"]

    naming_files = {
        "etc/hostname": "compas\n",
        "usr/resource/hostname": "compas\n",
        "usr/resource/bt_name": "compás\n",
    }
    for rel, value in naming_files.items():
        path = _inside(root_path, rel)
        old = path.read_bytes() if path.is_file() and not path.is_symlink() else None
        data = value.encode("utf-8")
        if old != data:
            _write(path, data)
            report["naming_updates"].append({"path": "/" + rel, "value": value.rstrip("\n")})

    # Set the kernel hostname too; stock init does not read /etc/hostname.
    init_rel = "etc/init.d/S00compas-hostname"
    init_path = _inside(root_path, init_rel)
    init_data = b"#!/bin/sh\n[ \"$1\" = stop ] && exit 0\n/bin/hostname compas\n"
    if not init_path.is_file() or init_path.read_bytes() != init_data:
        _write(init_path, init_data)
        report["naming_updates"].append({"path": "/" + init_rel, "hostname": "compas"})
    init_path.chmod(0o755)

    hosts = _inside(root_path, "etc/hosts")
    if hosts.is_file() and not hosts.is_symlink():
        lines = _read_text(hosts).splitlines(keepends=True)
        changed = False
        for index, line in enumerate(lines):
            if line.lstrip().startswith("#"):
                continue
            match = re.match(r"^(\s*\S+\s+)(.*?)(\s*(?:#.*)?(?:\r?\n)?)$", line)
            if not match:
                continue
            aliases = match.group(2).split()
            replacement = ["compas" if alias.lower() in OLD_HOST_ALIASES else alias for alias in aliases]
            if replacement != aliases:
                lines[index] = match.group(1) + " ".join(replacement) + match.group(3)
                changed = True
        if changed:
            _write(hosts, "".join(lines).encode("utf-8", "surrogateescape"))
            report["naming_updates"].append({"path": "/etc/hosts", "aliases": "ingenic/hiby/buildroot -> compas"})

    bluez = _inside(root_path, "etc/bluetooth/main.conf")
    if bluez.is_file() and not bluez.is_symlink():
        lines = _read_text(bluez).splitlines(keepends=True)
        section = None
        changed = False
        found = False
        for index, line in enumerate(lines):
            section_match = re.match(r"\s*\[([^]]+)\]", line)
            if section_match:
                section = section_match.group(1).strip().lower()
            if section == "general" and re.match(r"\s*#?\s*Name\s*=", line, re.I):
                if not line.lstrip().startswith("#"):
                    newline = "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
                    if line.strip() != "Name = compás":
                        lines[index] = "Name = compás" + newline
                        changed = True
                    found = True
        if not found:
            # BlueZ's General section is present in supported images. Fail closed
            # if its structure changed instead of adding a duplicate section.
            if not any(re.match(r"\s*\[General\]\s*$", line, re.I) for line in lines):
                raise ValueError(f"BlueZ config has no [General] section: {bluez}")
            section = None
            insert_at = None
            for index, line in enumerate(lines):
                if re.match(r"\s*\[General\]", line, re.I):
                    section = "general"
                    insert_at = index + 1
                    continue
                if section == "general" and re.match(r"\s*\[", line):
                    break
            lines.insert(insert_at or 1, "Name = compás\n")
            changed = True
        # Ask Broadcom/Cypress controllers for a high priority A2DP link (our bluetoothd option;
        # a no-op on other controllers). Idempotent: set it right in [General] after Name.
        section = None
        option = None
        name_at = None
        for index, line in enumerate(lines):
            section_match = re.match(r"\s*\[([^]]+)\]", line)
            if section_match:
                section = section_match.group(1).strip().lower()
            if section != "general" or line.lstrip().startswith("#"):
                continue
            if re.match(r"\s*BroadcomHighPriority\s*=", line, re.I):
                option = index
            elif re.match(r"\s*Name\s*=", line, re.I):
                name_at = index
        wanted = "BroadcomHighPriority = true"
        if option is not None:
            if lines[option].strip() != wanted:
                newline = "\r\n" if lines[option].endswith("\r\n") else "\n"
                lines[option] = wanted + newline
                changed = True
        elif name_at is not None:
            newline = "\r\n" if lines[name_at].endswith("\r\n") else "\n"
            lines.insert(name_at + 1, wanted + newline)
            changed = True
        else:
            raise ValueError(f"BlueZ config has no Name to place BroadcomHighPriority after: {bluez}")
        if changed:
            _write(bluez, "".join(lines).encode("utf-8", "surrogateescape"))
            report["naming_updates"].append({"path": "/etc/bluetooth/main.conf", "general_name": "compás",
                                             "bluetooth_options": {"BroadcomHighPriority": True}})

    for name in ("bt_init", "bt_resume"):
        path = _inside(root_path, f"usr/bin/{name}")
        if not path.is_file() or path.is_symlink():
            report["protected"].append({"path": f"/usr/bin/{name}", "reason": "active Bluetooth helper absent or unsafe; unchanged"})
            continue
        text = _read_text(path)
        active_alias = any(
            not line.lstrip().startswith("#") and "bt-adapter" in line and "--set" in line
            and "Alias" in line and "bt_name" in line
            for line in text.splitlines()
        )
        reads_bt_name = any(
            not line.lstrip().startswith("#") and "/usr/resource/bt_name" in line
            for line in text.splitlines()
        )
        if not (active_alias and reads_bt_name):
            footer = BT_ALIAS_FOOTER
            lines = text.splitlines(keepends=True)
            ready = next((i for i, line in enumerate(lines)
                          if "/tmp/bt_init_ok" in line and not line.lstrip().startswith("#")), None)
            if ready is not None:
                lines.insert(ready, footer)
                text = "".join(lines)
            else:
                text = text.rstrip() + "\n" + footer
            _write(path, text.encode("utf-8", "surrogateescape"))
            report["naming_updates"].append({"path": f"/usr/bin/{name}", "alias_footer": "added"})

    for rel in ("usr/bin",):
        base = _inside(root_path, rel)
        if not base.exists():
            continue
        for path in sorted(base.rglob("*")):
            if path.is_file() and not path.is_symlink() and path.name.endswith(INACTIVE_SUFFIXES):
                _remove(path, path.relative_to(root_path).as_posix(), removed)

    stock_v1_rel = "usr/lib/alsa-lib/stock-v1"
    stock_v1 = _inside(root_path, stock_v1_rel)
    alsa = _inside(root_path, "usr/lib/alsa-lib")
    alias_refs = []
    if alsa.is_dir():
        for alias in alsa.iterdir():
            if not alias.is_symlink():
                continue
            link = Path(os.readlink(alias))
            target = ((root_path / str(link).lstrip("/")) if link.is_absolute()
                      else alias.parent / link).resolve()
            if target == stock_v1.resolve() or stock_v1.resolve() in target.parents:
                alias_refs.append("/" + alias.relative_to(root_path).as_posix())
    if stock_v1.is_dir() and not alias_refs:
        _remove_tree(stock_v1, root_path, removed)
    elif alias_refs:
        report["protected"].append({"path": "/" + stock_v1_rel, "reason": "active ALSA aliases point into backup directory",
                                    "aliases": sorted(alias_refs)})

    blockers = _active_helper_blockers(root_path, repo_path)
    binary_blockers = _binary_resource_blockers(root_path)
    for name, refs in binary_blockers.items():
        blockers.setdefault(name, []).extend(refs)
    blockers = {name: sorted(set(refs)) for name, refs in blockers.items()}
    report["blocked_resource_dirs"] = blockers
    for name in RESOURCE_DIRS:
        rel = f"usr/resource/{name}"
        path = _inside(root_path, rel)
        if blockers.get(name):
            report["protected"].append({"path": "/" + rel,
                                        "reason": "active platform helper or binary reference found",
                                        "references": blockers[name]})
        elif path.is_dir() and not path.is_symlink():
            _remove_tree(path, root_path, removed)

    tracked = subprocess.check_output(
        ["git", "-C", str(repo_path), "ls-files", "assets"], text=True).splitlines()
    canonical: set[str] = set()
    kept_fonts: set[str] = {"Korean.ttf", "Thai.ttf"}
    for rel in tracked:
        parts = Path(rel).parts
        if len(parts) >= 3 and parts[1] == "fonts":
            kept_fonts.add(parts[2])
        for theme in ("theme1", "theme2"):
            if theme in parts:
                index = parts.index(theme)
                canonical.add(f"usr/resource/litegui/{theme}/" + "/".join(parts[index + 1:]))
    for theme in ("theme1", "theme2"):
        _prune_tree(root_path, f"usr/resource/litegui/{theme}", set(THEME_NAMESPACES), canonical, removed)
    _prune_tree(root_path, "usr/resource/fonts", kept_fonts, set(), removed)

    # Stock images nothing loads (see firmware/unused_assets.txt for the evidence).
    for rel in unused_asset_paths(repo_path):
        full = f"usr/resource/litegui/{rel}"
        if full in canonical:
            raise ValueError(f"{UNUSED_ASSETS_MANIFEST} lists a tracked asset: assets/{rel}")
        _remove(_inside(root_path, full), full, removed)
    # Directories the deletions emptied (only inside litegui), deepest first.
    litegui = _inside(root_path, "usr/resource/litegui")
    for directory in sorted((d for d in litegui.rglob("*") if d.is_dir() and not d.is_symlink()),
                            key=lambda d: len(d.parts), reverse=True):
        if not any(directory.iterdir()):
            directory.rmdir()
            removed.append({"path": "/" + directory.relative_to(root_path).as_posix(), "bytes": 0})

    report["removed_bytes"] = sum(item["bytes"] for item in removed)
    report["removed_count"] = len(removed)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", help="extracted firmware root directory")
    parser.add_argument("repo", nargs="?", default=str(Path(__file__).resolve().parents[3]),
                        help="compas-firmware repository (defaults to this script's repository)")
    parser.add_argument("--report", help="write JSON report to this path (stdout by default)")
    args = parser.parse_args(argv)
    report = prepare(args.root, args.repo)
    output = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.report:
        Path(args.report).write_text(output, encoding="utf-8")
    else:
        sys.stdout.write(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
