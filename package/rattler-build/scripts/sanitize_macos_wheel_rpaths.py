#!/usr/bin/env python3
"""Remove unused external build-host RPATHs from installed Python wheels."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess

from macos_macho import linked_libraries, load_command_paths, otool


SYSTEM_PREFIXES = (
    Path("/System/Library"),
    Path("/usr/lib"),
    Path("/Library/Apple/System/Library"),
)
MACHO_SUFFIXES = {".dylib", ".so", ".bundle"}


def _normalized(path: Path) -> Path:
    return Path(os.path.abspath(os.path.expanduser(str(path))))


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _is_external_absolute(path: str, bundle_prefix: Path) -> bool:
    if not os.path.isabs(path):
        return False
    normalized = _normalized(Path(path))
    if _is_relative_to(normalized, bundle_prefix):
        return False
    return not any(_is_relative_to(normalized, prefix) for prefix in SYSTEM_PREFIXES)


def _run(arguments: list[str], file_path: Path) -> None:
    subprocess.run([*arguments, str(file_path)], check=True, text=True)


def _sanitize_file(file_path: Path, *, bundle_prefix: Path, scan_only: bool) -> int:
    load_output = otool(file_path, "-l")
    if load_output is None:
        return 0
    rpaths = sorted(
        {
            value
            for command, value in load_command_paths(load_output)
            if command == "LC_RPATH" and _is_external_absolute(value, bundle_prefix)
        }
    )
    if not rpaths:
        return 0

    linked_output = otool(file_path, "-L")
    if linked_output is None:
        raise RuntimeError(f"otool -L did not recognize Mach-O file: {file_path}")
    rpath_dependencies = sorted(
        value for value in linked_libraries(linked_output) if value.startswith("@rpath/")
    )
    if rpath_dependencies:
        raise RuntimeError(
            f"Refusing to remove external RPATHs from {file_path}; it has "
            f"@rpath dependencies that may require them: {rpath_dependencies}. "
            f"External RPATHs: {rpaths}"
        )

    for rpath in rpaths:
        print(f"{file_path}: install_name_tool -delete_rpath {rpath}", flush=True)
        if not scan_only:
            _run(["install_name_tool", "-delete_rpath", rpath], file_path)
    if not scan_only:
        _run(["codesign", "--force", "--sign", "-"], file_path)
        remaining_output = otool(file_path, "-l")
        if remaining_output is None:
            raise RuntimeError(f"Modified file is no longer recognized as Mach-O: {file_path}")
        remaining = {
            value
            for command, value in load_command_paths(remaining_output)
            if command == "LC_RPATH"
        }
        not_removed = sorted(set(rpaths) & remaining)
        if not_removed:
            raise RuntimeError(
                f"External RPATH removal did not persist for {file_path}: {not_removed}"
            )
    return len(rpaths)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("site_packages", type=Path)
    parser.add_argument("--bundle-prefix", required=True, type=Path)
    parser.add_argument("--scan-only", action="store_true")
    arguments = parser.parse_args()

    site_packages = _normalized(arguments.site_packages)
    bundle_prefix = _normalized(arguments.bundle_prefix)
    if not site_packages.is_dir():
        parser.error(f"site-packages directory does not exist: {site_packages}")
    if not bundle_prefix.is_dir():
        parser.error(f"bundle prefix does not exist: {bundle_prefix}")
    if not _is_relative_to(site_packages, bundle_prefix):
        parser.error(f"site-packages is outside bundle prefix: {site_packages}")

    scanned = 0
    changes = 0
    for file_path in sorted(site_packages.rglob("*")):
        if (
            not file_path.is_file()
            or file_path.is_symlink()
            or file_path.suffix not in MACHO_SUFFIXES
        ):
            continue
        scanned += 1
        changes += _sanitize_file(
            file_path,
            bundle_prefix=bundle_prefix,
            scan_only=arguments.scan_only,
        )

    action = "required" if arguments.scan_only else "applied"
    print(
        f"macOS Python-wheel RPATH sanitization complete: scanned {scanned} files; "
        f"{changes} removals {action}.",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
