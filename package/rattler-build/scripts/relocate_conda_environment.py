#!/usr/bin/env python3

from __future__ import annotations

import argparse
from pathlib import Path

from conda_pack.core import CondaEnv


REQUIRED_FILES = {
    "bin/freecad",
    "bin/freecadcmd",
    "bin/python",
    "Mod/VibeCAD/Init.py",
}


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Relocate only package-managed files from a conda/Pixi environment "
            "into a deterministic application prefix."
        )
    )
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    return parser.parse_args()


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def main() -> int:
    arguments = _parse_arguments()
    source = arguments.source.resolve()
    destination = arguments.destination.resolve()
    if not source.is_dir():
        raise SystemExit(f"Source conda environment does not exist: {source}")
    if source == destination or _is_relative_to(destination, source):
        raise SystemExit(
            f"Destination must be outside the source conda environment: {destination}"
        )
    if destination.exists():
        raise SystemExit(f"Destination already exists and will not be overwritten: {destination}")

    environment = CondaEnv.from_prefix(str(source))
    managed_files = [file for file in environment.files if file.is_conda]
    unmanaged_count = len(environment.files) - len(managed_files)
    managed_targets = {file.target for file in managed_files}
    missing = sorted(REQUIRED_FILES - managed_targets)
    if missing:
        raise RuntimeError(
            "The package-managed environment is incomplete; required files are missing: "
            + ", ".join(missing)
        )

    print(
        f"Relocating {len(managed_files)} package-managed files from {source} to "
        f"{destination}; excluding {unmanaged_count} unmanaged files.",
        flush=True,
    )
    clean_environment = CondaEnv(str(source), managed_files)
    clean_environment.pack(
        output=str(destination),
        format="no-archive",
        dest_prefix=str(destination),
        force=True,
    )
    print(f"Relocated conda environment is ready: {destination}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
