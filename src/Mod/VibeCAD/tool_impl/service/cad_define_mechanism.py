# SPDX-License-Identifier: LGPL-2.1-or-later

"""AI-native mechanism definition tool."""

from __future__ import annotations

from typing import Any

from .cad_common import append_design_memory


MECHANISM_TYPES = (
    "rotating",
    "sliding",
    "hinge",
    "cam",
    "gear_train",
    "linkage",
    "spring",
    "latch",
    "lock",
    "bearing_support",
    "actuator",
    "fluid_path",
    "load_path",
    "compliant",
)


TOOL_SPEC = {
    "name": "cad.define_mechanism",
    "description": (
        "Define a mechanism, motion, lock, load path, bearing support, "
        "actuation, fluid path, or compliant behavior that the CAD must make "
        "physically plausible before details are modeled."
    ),
    "safety": "SAFE_WRITE",
    "parameters": {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "components": {"type": "array", "items": {"type": "string"}},
            "mechanism_type": {"type": "string", "enum": list(MECHANISM_TYPES)},
            "description": {"type": "string"},
            "degrees_of_freedom": {"type": "string"},
            "axes": {"type": "array", "items": {"type": "string"}},
            "range": {"type": "string"},
            "contacts": {"type": "array", "items": {"type": "string"}},
            "load_path": {"type": "string"},
            "failure_modes": {"type": "array", "items": {"type": "string"}},
            "verification_checks": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["name", "components", "mechanism_type", "description"],
    },
}


def _clean_list(values: list[str] | None) -> list[str]:
    return [str(item).strip() for item in (values or []) if str(item).strip()]


def run(
    service: Any,
    name: str,
    components: list[str],
    mechanism_type: str,
    description: str,
    degrees_of_freedom: str = "",
    axes: list[str] | None = None,
    range: str = "",
    contacts: list[str] | None = None,
    load_path: str = "",
    failure_modes: list[str] | None = None,
    verification_checks: list[str] | None = None,
) -> dict[str, Any]:
    clean_name = str(name or "").strip()
    clean_components = _clean_list(components)
    clean_type = str(mechanism_type or "").strip()
    clean_description = str(description or "").strip()
    clean_axes = _clean_list(axes)
    clean_contacts = _clean_list(contacts)
    clean_failures = _clean_list(failure_modes)
    checks = _clean_list(verification_checks)
    if not clean_name:
        return {"ok": False, "error": "Mechanism name is required."}
    if len(clean_components) < 1:
        return {"ok": False, "error": "At least one component is required."}
    if clean_type not in MECHANISM_TYPES:
        return {
            "ok": False,
            "error": f"mechanism_type must be one of: {', '.join(MECHANISM_TYPES)}.",
        }
    if not clean_description:
        return {"ok": False, "error": "Mechanism description is required."}

    parts = [
        f"{clean_name}: {clean_type}",
        f"components={', '.join(clean_components)}",
        clean_description,
    ]
    dof = str(degrees_of_freedom or "").strip()
    if dof:
        parts.append(f"dof={dof}")
    if clean_axes:
        parts.append(f"axes={', '.join(clean_axes)}")
    clean_range = str(range or "").strip()
    if clean_range:
        parts.append(f"range={clean_range}")
    if clean_contacts:
        parts.append(f"contacts={', '.join(clean_contacts)}")
    clean_load_path = str(load_path or "").strip()
    if clean_load_path:
        parts.append(f"load_path={clean_load_path}")
    if clean_failures:
        parts.append(f"failure_modes={', '.join(clean_failures)}")
    if checks:
        parts.append(f"verify={', '.join(checks)}")
    line = " | ".join(parts)

    memory = append_design_memory(
        service,
        mechanisms=[line],
        interfaces=[line] if len(clean_components) > 1 else [],
        verification_checks=checks,
        known_failures=clean_failures,
    )
    return {
        "ok": bool(memory.get("ok", True)),
        "mechanism": clean_name,
        "mechanism_type": clean_type,
        "components": clean_components,
        "design_memory_result": memory,
        "next_actions": [
            {
                "tool": "cad.define_envelope",
                "why": "Capture the swept, clearance, fit, or keepout envelope this mechanism requires.",
            },
            {
                "tool": "cad.verify_design",
                "why": "Check built geometry against mechanism interfaces before declaring progress.",
            },
        ],
    }
