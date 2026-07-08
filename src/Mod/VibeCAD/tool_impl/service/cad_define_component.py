# SPDX-License-Identifier: LGPL-2.1-or-later

"""AI-native component definition tool."""

from __future__ import annotations

from typing import Any

from .cad_common import append_design_memory, call_backend, find_body_name


TOOL_SPEC = {
    "name": "cad.define_component",
    "description": (
        "Define a functional CAD component or subassembly and optionally create "
        "its native PartDesign Body. Use this before geometry so intent, "
        "material, process, interfaces, and non-negotiable behavior survive "
        "later tool turns."
    ),
    "safety": "SAFE_WRITE",
    "parameters": {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "purpose": {"type": "string"},
            "component_type": {
                "type": "string",
                "enum": ["solid_part", "surface_part", "assembly", "reference"],
            },
            "material": {"type": "string"},
            "manufacturing_process": {"type": "string"},
            "critical_geometry": {"type": "array", "items": {"type": "string"}},
            "interfaces": {"type": "array", "items": {"type": "string"}},
            "verification_checks": {"type": "array", "items": {"type": "string"}},
            "create_body": {"type": "boolean"},
        },
        "required": ["name", "purpose"],
    },
}


def _component_line(
    name: str,
    purpose: str,
    component_type: str,
    material: str,
    manufacturing_process: str,
) -> str:
    details = [f"{name}: {purpose}"]
    if component_type:
        details.append(f"type={component_type}")
    if material:
        details.append(f"material={material}")
    if manufacturing_process:
        details.append(f"process={manufacturing_process}")
    return " | ".join(details)


def run(
    service: Any,
    name: str,
    purpose: str,
    component_type: str = "solid_part",
    material: str = "",
    manufacturing_process: str = "",
    critical_geometry: list[str] | None = None,
    interfaces: list[str] | None = None,
    verification_checks: list[str] | None = None,
    create_body: bool = True,
) -> dict[str, Any]:
    clean_name = str(name or "").strip()
    clean_purpose = str(purpose or "").strip()
    if not clean_name:
        return {"ok": False, "error": "Component name is required."}
    if not clean_purpose:
        return {"ok": False, "error": "Component purpose is required."}
    clean_type = str(component_type or "solid_part").strip()
    if clean_type not in {"solid_part", "surface_part", "assembly", "reference"}:
        return {
            "ok": False,
            "error": "component_type must be solid_part, surface_part, assembly, or reference.",
        }

    backend_body = None
    if bool(create_body) and clean_type == "solid_part":
        existing = find_body_name(service, clean_name)
        if existing:
            backend_body = {
                "ok": True,
                "active_body": existing,
                "already_existed": True,
            }
        else:
            backend_body = call_backend(
                service,
                "partdesign.create_body",
                label=clean_name,
            )

    memory = append_design_memory(
        service,
        components=[
            _component_line(
                clean_name,
                clean_purpose,
                clean_type,
                str(material or "").strip(),
                str(manufacturing_process or "").strip(),
            )
        ],
        interfaces=list(interfaces or []),
        critical_geometry=list(critical_geometry or []),
        verification_checks=list(verification_checks or []),
    )
    ok = bool(memory.get("ok", True)) and not (
        isinstance(backend_body, dict) and backend_body.get("ok") is False
    )
    return {
        "ok": ok,
        "component": clean_name,
        "component_type": clean_type,
        "purpose": clean_purpose,
        "body_result": backend_body,
        "design_memory_result": memory,
        "next_actions": [
            {
                "tool": "cad.create_profile",
                "why": "Create the first named profile for this component.",
            },
            {
                "tool": "cad.define_interface",
                "why": "Define how this component mates, moves, fastens, seals, or clears another component.",
            },
            {
                "tool": "cad.define_envelope",
                "why": "Define any keepout, clearance, swept-motion, fit, flow, or load envelope this component must honor.",
            },
            {
                "tool": "cad.define_mechanism",
                "why": "Define any moving, locking, load-path, bearing, actuation, or compliant behavior before detailing geometry.",
            },
        ],
    }
