#!/usr/bin/env python3

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess


SYSTEM_PREFIXES = (
    Path("/System/Library"),
    Path("/usr/lib"),
    Path("/Library/Apple/System/Library"),
)
MACHO_SUFFIXES = {".dylib", ".so", ".bundle"}


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reject non-relocatable Mach-O references in a macOS app bundle."
    )
    parser.add_argument("bundle", type=Path)
    parser.add_argument(
        "--forbid-prefix",
        action="append",
        default=[],
        type=Path,
        help="Reject any load command that references this source prefix.",
    )
    return parser.parse_args()


def _normalized(path: Path) -> Path:
    return Path(os.path.abspath(os.path.expanduser(str(path))))


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _is_system_path(path: Path) -> bool:
    return any(_is_relative_to(path, prefix) for prefix in SYSTEM_PREFIXES)


def _candidate(file_path: Path) -> bool:
    if file_path.suffix in MACHO_SUFFIXES:
        return True
    if "MacOS" in file_path.parts:
        return True
    return os.access(file_path, os.X_OK)


def _otool(file_path: Path, option: str) -> str | None:
    result = subprocess.run(
        ["otool", option, str(file_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        return result.stdout
    diagnostic = f"{result.stdout}\n{result.stderr}"
    if "is not an object file" in diagnostic or "The file was not recognized" in diagnostic:
        return None
    raise RuntimeError(
        f"otool {option} failed for {file_path} with status {result.returncode}:\n"
        f"{diagnostic.strip()}"
    )


def _load_command_paths(output: str) -> list[tuple[str, str]]:
    paths: list[tuple[str, str]] = []
    command = ""
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if line.startswith("cmd "):
            command = line.removeprefix("cmd ")
            continue
        if command == "LC_RPATH" and line.startswith("path "):
            paths.append(
                (command, line.removeprefix("path ").split(" (offset", 1)[0])
            )
            command = ""
        elif command in {"LC_ID_DYLIB", "LC_REEXPORT_DYLIB"} and line.startswith(
            "name "
        ):
            paths.append(
                (command, line.removeprefix("name ").split(" (offset", 1)[0])
            )
            command = ""
    return paths


def _linked_libraries(output: str) -> list[str]:
    libraries: list[str] = []
    for raw_line in output.splitlines()[1:]:
        line = raw_line.strip()
        if not line:
            continue
        libraries.append(line.split(" (compatibility version", 1)[0])
    return libraries


def _validate_path(
    value: str,
    *,
    command: str,
    file_path: Path,
    bundle: Path,
    forbidden_prefixes: tuple[Path, ...],
) -> None:
    for prefix in forbidden_prefixes:
        if str(prefix) in value:
            raise RuntimeError(
                f"{file_path}: {command} still references source prefix "
                f"{prefix}: {value}"
            )
    if not os.path.isabs(value):
        if value.startswith("@"):
            return
        raise RuntimeError(
            f"{file_path}: {command} uses an unresolved relative load path: {value}"
        )

    path = _normalized(Path(value))
    if _is_system_path(path):
        return
    if _is_relative_to(path, bundle):
        raise RuntimeError(
            f"{file_path}: {command} contains an absolute build-time bundle "
            f"path and will break after installation: {value}"
        )
    raise RuntimeError(
        f"{file_path}: {command} references an external non-system path: {value}"
    )


def main() -> int:
    arguments = _parse_arguments()
    bundle = _normalized(arguments.bundle)
    forbidden_prefixes = tuple(_normalized(path) for path in arguments.forbid_prefix)
    if not bundle.is_dir():
        raise SystemExit(f"macOS app bundle does not exist: {bundle}")

    candidates = 0
    mach_o_files = 0
    references = 0
    for file_path in sorted(bundle.rglob("*")):
        if not file_path.is_file() or file_path.is_symlink() or not _candidate(file_path):
            continue
        candidates += 1
        load_output = _otool(file_path, "-l")
        if load_output is None:
            continue
        mach_o_files += 1
        for command, value in _load_command_paths(load_output):
            references += 1
            _validate_path(
                value,
                command=command,
                file_path=file_path,
                bundle=bundle,
                forbidden_prefixes=forbidden_prefixes,
            )

        linked_output = _otool(file_path, "-L")
        if linked_output is None:
            raise RuntimeError(f"otool -L did not recognize known Mach-O file: {file_path}")
        for value in _linked_libraries(linked_output):
            references += 1
            _validate_path(
                value,
                command="linked library",
                file_path=file_path,
                bundle=bundle,
                forbidden_prefixes=forbidden_prefixes,
            )

    print(
        "macOS bundle relocation audit passed: "
        f"{mach_o_files} Mach-O files from {candidates} candidates, "
        f"{references} load references checked.",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
