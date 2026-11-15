#!/usr/bin/env python3
"""Rebuild the R1 modules that carry the HiBy v2.0 fixes (cw2015, soc_aic, lcd_lg35583)
and the Compás-only axp2101_wake module from its pinned kit commit.

The reconstructed drivers come from the pinned hiby-custom-kernel commit
(firmware/kernel/upstream.json) with the reviewed module patches applied in name order:
compas-reconstructed-drivers-safety.patch, then compas-reconstructed-drivers-v2-fixes.patch.
axp2101_wake is not in that commit. module_build.added_module_sources names its repo,
upstream, path and commit; the build archives that commit and refuses a working-tree copy.
While the commit is null the added module is skipped, with one message, and cw2015, soc_aic
and lcd_lg35583 are still built. They are built out of tree against the recorded Compás kernel
tree (.config and System.map pinned in firmware/r1_base_v2.json) with the Ingenic GCC 7.2
toolchain of the SDK archive named in upstream.json (mips-gcc720-glibc229). Every pin must
match or the build stops, and the result must reproduce the pinned module hashes.

Usage:
  build_r1_v2_modules.py --kit HIBY_CUSTOM_KERNEL_CHECKOUT --kernel-tree CONFIGURED_KERNEL_TREE \\
      --toolchain SDK/prebuilts/toolchains/mips-gcc720-glibc229 --output DIR
          [--siblings DIR_OF_THE_OTHER_SHIPPED_MODULES]

The kernel tree is only read by Kbuild's out-of-tree mode; build against a copy of a recorded tree
to keep the original untouched. --siblings adds the other shipped modules (for example the
module_driver directory of the assembled base) to the undefined-symbol check.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "scripts/kernel/modules/verification"))
import verify_module_abi as abi  # noqa: E402

TOOL_FILES = {
    "gcc": "bin/mips-linux-gnu-gcc",
    "as": "bin/mips-linux-gnu-as",
    "ld": "bin/mips-linux-gnu-ld",
    "cc1": "libexec/gcc/mips-linux-gnu/7.2.0/cc1",
}
PATCH_GLOB = "compas-reconstructed-drivers-*.patch"


def sha(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def fail(message: str):
    raise SystemExit(f"build_r1_v2_modules: {message}")


def run(*argv, **kw):
    return subprocess.run([str(a) for a in argv], check=True, **kw)


def check_pins(args, pins: dict):
    tree = args.kernel_tree
    for rel, key in ((".config", "kernel_config_sha256"), ("System.map", "system_map_sha256")):
        if not (tree / rel).is_file() or sha(tree / rel) != pins[key]:
            fail(f"kernel tree {rel} does not match the pin in firmware/r1_base_v2.json")
    if not (tree / "Module.symvers").is_file():
        fail("kernel tree has no Module.symvers (it must be a built tree)")
    for name, rel in TOOL_FILES.items():
        path = args.toolchain / rel
        if not path.is_file() or sha(path) != pins["toolchain"][name]:
            fail(f"toolchain {rel} does not match the pin in firmware/r1_base_v2.json")
    patches = sorted(p for p in (REPO / "firmware/kernel/module-patches").glob(PATCH_GLOB))
    if [p.name for p in patches] != list(pins["patches"]):
        fail(f"module patches {[p.name for p in patches]} differ from the pinned list {list(pins['patches'])}")
    for p in patches:
        if sha(p) != pins["patches"][p.name]:
            fail(f"{p.name} does not match its pin")
    return patches


def export_sources(kit: pathlib.Path, commit: str, dest: pathlib.Path):
    try:
        run("git", "-C", kit, "cat-file", "-e", f"{commit}^{{commit}}")
    except subprocess.CalledProcessError:
        fail(f"{kit} is not a git checkout containing commit {commit}")
    archive = subprocess.run(["git", "-C", str(kit), "archive", commit, "modules", "boards/r1/modules"],
                             check=True, capture_output=True).stdout
    run("tar", "-x", "-C", dest, input=archive)


def valid_source_commit(commit) -> bool:
    """The only 40-hex check for an added module commit."""
    return isinstance(commit, str) and len(commit) == 40 and all(c in "0123456789abcdef" for c in commit)


def owner_commit_text(name: str, spec: dict) -> str:
    repo = spec.get("repo") or "the kit repo named in added_module_sources"
    upstream = spec.get("upstream") or ""
    rel = spec.get("path") or ("modules/" + name)
    upstream_note = f" Upstream is {upstream}." if upstream else ""
    return (
        f"In {repo} commit {rel} (source only, no .ko) and set "
        f"module_build.added_module_sources.{name}.commit and the open-modules "
        f"source.commit to that full lowercase SHA. Add {repo} as a remote of the "
        f"local kit checkout and fetch it, so git cat-file can see the commit."
        f"{upstream_note} The build does not copy the working tree."
    )


def added_source_commit(name: str, spec: dict):
    """Pinned commit, or None when it is still null. A bad value fails."""
    if not isinstance(spec, dict):
        fail(f"{name} is in added_modules but has no added_module_sources entry")
    commit = spec.get("commit")
    if commit is None or commit == "":
        return None
    if not valid_source_commit(commit):
        fail(f"{name} source commit is not a full lowercase SHA. {owner_commit_text(name, spec)}")
    return commit


def added_source(kit: pathlib.Path, name: str, spec: dict, dest: pathlib.Path) -> pathlib.Path:
    """Archive one added module from its pinned commit. Never the working tree."""
    commit = added_source_commit(name, spec)
    if commit is None:
        fail(f"{name} has no pinned source commit. {owner_commit_text(name, spec)}")
    rel = spec.get("path") or ""
    if not rel or rel.startswith("/") or ".." in pathlib.PurePosixPath(rel).parts:
        fail(f"{name} source path is not a kit-relative directory")
    try:
        run("git", "-C", kit, "cat-file", "-e", f"{commit}^{{commit}}")
    except subprocess.CalledProcessError:
        fail(f"{kit} does not contain commit {commit} for {name}")
    try:
        archive = subprocess.run(["git", "-C", str(kit), "archive", commit, rel],
                                 check=True, capture_output=True).stdout
    except subprocess.CalledProcessError as exc:
        fail(f"git archive {commit} {rel} failed: {exc.stderr.decode(errors='replace').strip()}")
    if not archive:
        fail(f"commit {commit} has no {rel}")
    dest.mkdir(parents=True, exist_ok=True)
    run("tar", "-x", "-C", dest, input=archive)
    src = dest / rel
    if not (src / "Makefile").is_file():
        fail(f"commit {commit} did not contain {rel}/Makefile")
    return src


def module_dir(kit_tree: pathlib.Path, name: str) -> pathlib.Path:
    for base in ("modules", "boards/r1/modules"):
        if (kit_tree / base / name / "Makefile").is_file():
            return kit_tree / base / name
    fail(f"no source directory for {name}")


def build(args, pins: dict, commit: str):
    added = pins.get("added_modules") or {}
    sources = pins.get("added_module_sources") or {}
    planned = {}
    for name in added:
        planned[name] = added_source_commit(name, sources.get(name))
    patches = check_pins(args, pins)
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    if any(out.glob("*.ko")):
        fail(f"output directory already holds modules: {out}")
    env = dict(os.environ, PATH=f"{args.toolchain / 'bin'}:{os.environ['PATH']}")
    with tempfile.TemporaryDirectory(prefix="r1-v2-modules.") as tmp:
        tmp = pathlib.Path(tmp)
        src = tmp / "kit"
        src.mkdir()
        export_sources(args.kit, commit, src)
        for patch in patches:
            run("patch", "--batch", "--forward", "--fuzz=0", "-s", "-p1", "-d", src, "-i", patch)
        built = {}
        for name in pins["modules"]:
            work = tmp / "ext" / name
            shutil.copytree(module_dir(src, name), work)
            run("make", "-C", args.kernel_tree, "ARCH=mips", "CROSS_COMPILE=mips-linux-gnu-",
                "HOSTCC=gcc -fcommon", f"M={work}", "HIBY_MODEL=r1", "modules", env=env,
                stdout=subprocess.DEVNULL)
            ko = work / f"{name}.ko"
            if not ko.is_file():
                fail(f"{name}.ko was not produced")
            if sha(ko) != pins["modules"][name]:
                fail(f"{name}.ko is {sha(ko)}, expected {pins['modules'][name]}")
            shutil.copy2(ko, out / f"{name}.ko")
            built[name] = sha(ko)
        for name, want in added.items():
            spec = sources[name]
            if planned[name] is None:
                print(f"{name} has no pinned source commit. Skipping it. "
                      f"{owner_commit_text(name, spec)}", file=sys.stderr)
                continue
            src_dir = added_source(args.kit, name, spec, tmp / "added" / name)
            work = tmp / "ext" / name
            shutil.copytree(src_dir, work)
            run("make", "-C", args.kernel_tree, "ARCH=mips", "CROSS_COMPILE=mips-linux-gnu-",
                "HOSTCC=gcc -fcommon", f"M={work}", "HIBY_MODEL=r1", "modules", env=env,
                stdout=subprocess.DEVNULL)
            ko = work / f"{name}.ko"
            if not ko.is_file():
                fail(f"{name}.ko was not produced")
            digest = sha(ko)
            if digest != want:
                fail(f"{name}.ko is {digest}, expected {want}")
            shutil.copy2(ko, out / f"{name}.ko")
            built[name] = digest
    return built


def verify(args, pins: dict, built: dict):
    """Vermagic and undefined symbols of the rebuilt modules against System.map and their siblings."""
    out = args.output.resolve()
    with tempfile.TemporaryDirectory(prefix="r1-v2-abi.") as tmp:
        tmp = pathlib.Path(tmp)
        vendor = tmp / "siblings"
        vendor.mkdir()
        # Drop a sibling only when this run built a replacement. A skipped
        # added module stays in the check.
        replaced = set(pins["modules"]) | (set(built) & set(pins.get("added_modules") or {}))
        if args.siblings:
            for ko in sorted(args.siblings.glob("*.ko")):
                if ko.name[:-3] not in replaced:
                    shutil.copy2(ko, vendor / ko.name)
        for ko in out.glob("*.ko"):
            shutil.copy2(ko, vendor / ko.name)
        empty = tmp / "built"
        empty.mkdir()
        report = abi.verify(args.kernel_tree / "System.map", empty, vendor,
                            shutil.which("nm") or "nm", shutil.which("modinfo") or "modinfo")
    if not report["valid"]:
        fail(f"ABI check failed: {report['vermagic_errors']} {report['missing_imports_by_module']}")
    (out / "abi-report.json").write_text(json.dumps(
        {k: report[k] for k in ("valid", "system_map_sha256", "vermagic_values",
                                "missing_imports_by_module", "selected_module_count")},
        indent=2, sort_keys=True) + "\n")
    return report["vermagic_values"]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--kit", required=True, type=pathlib.Path)
    ap.add_argument("--kernel-tree", required=True, type=pathlib.Path)
    ap.add_argument("--toolchain", required=True, type=pathlib.Path)
    ap.add_argument("--output", required=True, type=pathlib.Path)
    ap.add_argument("--siblings", type=pathlib.Path)
    args = ap.parse_args()
    args.kit, args.kernel_tree, args.toolchain = (p.resolve() for p in (args.kit, args.kernel_tree, args.toolchain))
    for tool in ("git", "make", "patch", "tar", "nm", "modinfo"):
        if not shutil.which(tool):
            fail(f"required command is unavailable: {tool}")
    pins = json.loads((REPO / "firmware/r1_base_v2.json").read_text())["module_build"]
    commit = json.loads((REPO / "firmware/kernel/upstream.json").read_text())["commit"]
    built = build(args, pins, commit)
    vermagic = verify(args, pins, built)
    for name, digest in sorted(built.items()):
        print(f"{digest}  {name}.ko")
    print(f"vermagic: {', '.join(vermagic)}")


if __name__ == "__main__":
    main()
