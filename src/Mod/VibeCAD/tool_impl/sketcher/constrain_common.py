# SPDX-License-Identifier: LGPL-2.1-or-later

"""Shared helpers for typed Sketcher constraint tools."""

from __future__ import annotations


POINT_POSITIONS = {
    "whole": 0,
    "edge": 0,
    "curve": 0,
    "start": 1,
    "end": 2,
    "center": 3,
    "midpoint": 3,
    "origin": 1,
}


def point_position(value: str) -> int:
    clean = str(value or "").strip().lower()
    if clean not in POINT_POSITIONS:
        raise ValueError(
            "point role must be one of: "
            + ", ".join(sorted(POINT_POSITIONS))
        )
    return POINT_POSITIONS[clean]


def optional_point_position(value: str | None, geometry_handle: str | None = None, default: str = "whole") -> int:
    if value is None:
        clean_handle = str(geometry_handle or "").strip().lower()
        if clean_handle in {"origin", "root", "rootpoint", "root_point"}:
            return POINT_POSITIONS["start"]
        value = default
    return point_position(value)
