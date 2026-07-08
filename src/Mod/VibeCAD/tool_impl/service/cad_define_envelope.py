# SPDX-License-Identifier: LGPL-2.1-or-later

"""AI-native envelope definition tool."""

from __future__ import annotations

from typing import Any

from .cad_common import append_design_memory


ENVELOPE_TYPES = (
    "swept_motion",
    "clearance",
    "keepout",
    "fit_inside",
    "assembly_volume",
    "manufacturing",
    "fluid_flow",
    "structural_load",
    "ergonomic",
    "thermal",
)


TOOL_SPEC = {
    "name": "cad.define_envelope",
    "description": (
        "Define a clearance, keepout, swept-motion, fit, flow, load, thermal, "
        "manufacturing, or ergonomic envelope the CAD geometry must honor. Use "
        "this before creating geometry that has to move, fit, clear, route, or "
        "carry load inside another component."
    ),
    "safety": "SAFE_WRITE",
    "parameters": {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "components": {"type": "array", "items": {"type": "string"}},
            "envelope_type": {"type": "string", "enum": list(ENVELOPE_TYPES)},
            "description": {"type": "string"},
            "clearance_mm": {"type": "number"},
            "bounds_mm": {
                "type": "object",
                "properties": {
                    "xmin": {"type": "number"},
                    "ymin": {"type": "number"},
                    "zmin": {"type": "number"},
                    "xmax": {"type": "number"},
                    "ymax": {"type": "number"},
                    "zmax": {"type": "number"},
                },
            },
            "path": {"type": "string"},
            "must_contain": {"type": "array", "items": {"type": "string"}},
            "must_exclude": {"type": "array", "items": {"type": "string"}},
            "verification_checks": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["name", "components", "envelope_type", "description"],
    },
}


def _clean_list(values: list[str] | None) -> list[str]:
    return [str(item).strip() for item in (values or []) if str(item).strip()]


def _bounds_text(bounds_mm: dict[str, Any] | None) -> str:
    if not isinstance(bounds_mm, dict):
        return ""
    keys = ("xmin", "ymin", "zmin", "xmax", "ymax", "zmax")
    if not any(key in bounds_mm for key in keys):
        return ""
    parts = []
    for key in keys:
        if key in bounds_mm:
            try:
                parts.append(f"{key}={float(bounds_mm[key]):g}")
            except (TypeError, ValueError):
                parts.append(f"{key}={bounds_mm[key]}")
    return "bounds_mm={" + ", ".join(parts) + "}"


def run(
    service: Any,
    name: str,
    components: list[str],
    envelope_type: str,
    description: str,
    clearance_mm: float | None = None,
    bounds_mm: dict[str, Any] | None = None,
    path: str = "",
    must_contain: list[str] | None = None,
    must_exclude: list[str] | None = None,
    verification_checks: list[str] | None = None,
) -> dict[str, Any]:
    clean_name = str(name or "").strip()
    clean_components = _clean_list(components)
    clean_type = str(envelope_type or "").strip()
    clean_description = str(description or "").strip()
    contains = _clean_list(must_contain)
    excludes = _clean_list(must_exclude)
    checks = _clean_list(verification_checks)
    if not clean_name:
        return {"ok": False, "error": "Envelope name is required."}
    if not clean_components:
        return {"ok": False, "error": "At least one component is required."}
    if clean_type not in ENVELOPE_TYPES:
        return {
            "ok": False,
            "error": f"envelope_type must be one of: {', '.join(ENVELOPE_TYPES)}.",
        }
    if not clean_description:
        return {"ok": False, "error": "Envelope description is required."}

    parts = [
        f"{clean_name}: {clean_type}",
        f"components={', '.join(clean_components)}",
        clean_description,
    ]
    if clearance_mm is not None:
        parts.append(f"clearance={float(clearance_mm):g} mm")
    bounds = _bounds_text(bounds_mm)
    if bounds:
        parts.append(bounds)
    clean_path = str(path or "").strip()
    if clean_path:
        parts.append(f"path={clean_path}")
    if contains:
        parts.append(f"must_contain={', '.join(contains)}")
    if excludes:
        parts.append(f"must_exclude={', '.join(excludes)}")
    if checks:
        parts.append(f"verify={', '.join(checks)}")
    line = " | ".join(parts)

    memory = append_design_memory(
        service,
        envelopes=[line],
        critical_geometry=[line],
        verification_checks=checks,
    )
    return {
        "ok": bool(memory.get("ok", True)),
        "envelope": clean_name,
        "envelope_type": clean_type,
        "components": clean_components,
        "design_memory_result": memory,
        "next_actions": [
            {
                "tool": "cad.create_profile",
                "why": "Author profiles that stay inside, outside, or along this envelope.",
            },
            {
                "tool": "cad.verify_design",
                "why": "Check built geometry against the envelope before declaring progress.",
            },
        ],
    }
