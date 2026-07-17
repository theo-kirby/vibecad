#!/usr/bin/env python3

"""Calculate a conservative HFS+ image capacity for a staged macOS app."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys


ALLOCATION_BLOCK_BYTES = 4 * 1024
CATALOG_RESERVE_BYTES_PER_ENTRY = 2 * ALLOCATION_BLOCK_BYTES
FILESYSTEM_RESERVE_BYTES = 256 * 1024 * 1024
IMAGE_SIZE_QUANTUM_BYTES = 64 * 1024 * 1024


def _round_up(value: int, quantum: int) -> int:
    return ((value + quantum - 1) // quantum) * quantum


def _walk_without_following_symlinks(root: Path):
    pending = [root]
    while pending:
        path = pending.pop()
        yield path
        if path.is_symlink() or not path.is_dir():
            continue
        with os.scandir(path) as entries:
            pending.extend(Path(entry.path) for entry in entries)


def calculate_image_size(root: Path) -> dict[str, int]:
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError(f"macOS bundle path is not a directory: {root}")

    entry_count = 0
    data_bytes = 0
    extended_attribute_bytes = 0
    for path in _walk_without_following_symlinks(root):
        entry_count += 1
        stat_result = path.lstat()
        data_bytes += _round_up(stat_result.st_size, ALLOCATION_BLOCK_BYTES)
        for attribute_name in os.listxattr(path, follow_symlinks=False):
            attribute_value = os.getxattr(
                path, attribute_name, follow_symlinks=False
            )
            attribute_record_bytes = (
                len(os.fsencode(attribute_name)) + len(attribute_value) + 64
            )
            extended_attribute_bytes += _round_up(
                attribute_record_bytes, ALLOCATION_BLOCK_BYTES
            )

    catalog_reserve_bytes = entry_count * CATALOG_RESERVE_BYTES_PER_ENTRY
    required_bytes = (
        data_bytes
        + extended_attribute_bytes
        + catalog_reserve_bytes
        + FILESYSTEM_RESERVE_BYTES
    )
    image_bytes = _round_up(required_bytes, IMAGE_SIZE_QUANTUM_BYTES)
    return {
        "entries": entry_count,
        "data_bytes": data_bytes,
        "extended_attribute_bytes": extended_attribute_bytes,
        "catalog_reserve_bytes": catalog_reserve_bytes,
        "filesystem_reserve_bytes": FILESYSTEM_RESERVE_BYTES,
        "image_bytes": image_bytes,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("app_bundle", type=Path)
    args = parser.parse_args()

    estimate = calculate_image_size(args.app_bundle)
    print(
        "macOS DMG capacity audit: "
        + " ".join(f"{key}={value}" for key, value in estimate.items()),
        file=sys.stderr,
    )
    print(f"{estimate['image_bytes']}b")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
