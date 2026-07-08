# SPDX-License-Identifier: LGPL-2.1-or-later

"""AI-native interface definition tool."""

from __future__ import annotations

from typing import Any

from .cad_common import append_design_memory


INTERFACE_TYPES = (
    "fixed",
    "rotating",
    "sliding",
    "clearance",
    "seal",
    "fastener",
    "bearing",
    "load_path",
    "motion_envelope",
    "contact",
)


TOOL_SPEC = {
    "name": "cad.define_interface",
    "description": (
        "Define how components relate: fit, clearance, fastening, motion, "
        "contact, bearing support, sealing, or load path. This is product "
        "architecture, not sketch geometry."
    ),
    "safety": "SAFE_WRITE",
    "parameters": {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "components": {"type": "array", "items": {"type": "string"}},
            "interface_type": {"type": "string", "enum": list(INTERFACE_TYPES)},
            "description": {"type": "string"},
            "clearance_mm": {"type": "number"},
            "fit": {"type": "string"},
            "motion": {"type": "string"},
            "verification_checks": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["name", "components", "interface_type", "description"],
    },
}


def run(
    service: Any,
    name: str,
    components: list[str],
    interface_type: str,
    description: str,
    clearance_mm: float | None = None,
    fit: str = "",
    motion: str = "",
    verification_checks: list[str] | None = None,
) -> dict[str, Any]:
    clean_name = str(name or "").strip()
    clean_components = [str(item).strip() for item in (components or []) if str(item).strip()]
    clean_type = str(interface_type or "").strip()
    clean_description = str(description or "").strip()
    if not clean_name:
        return {"ok": False, "error": "Interface name is required."}
    if len(clean_components) < 2:
        return {"ok": False, "error": "At least two components are required."}
    if clean_type not in INTERFACE_TYPES:
        return {
            "ok": False,
            "error": f"interface_type must be one of: {', '.join(INTERFACE_TYPES)}.",
        }
    if not clean_description:
        return {"ok": False, "error": "Interface description is required."}

    parts = [
        f"{clean_name}: {clean_type}",
        f"components={', '.join(clean_components)}",
        clean_description,
    ]
    if clearance_mm is not None:
        parts.append(f"clearance={float(clearance_mm):g} mm")
    if str(fit or "").strip():
        parts.append(f"fit={str(fit).strip()}")
    if str(motion or "").strip():
        parts.append(f"motion={str(motion).strip()}")
    line = " | ".join(parts)

    mechanisms = [line] if clean_type in {"rotating", "sliding", "motion_envelope"} else []
    memory = append_design_memory(
        service,
        interfaces=[line],
        mechanisms=mechanisms,
        verification_checks=list(verification_checks or []),
    )
    next_actions = []
    if clean_type in {"rotating", "sliding", "motion_envelope", "clearance"}:
        next_actions.append(
            {
                "tool": "cad.define_envelope",
                "why": "Capture the swept, clearance, fit, or keepout volume this interface requires.",
            }
        )
    return {
        "ok": bool(memory.get("ok", True)),
        "interface": clean_name,
        "interface_type": clean_type,
        "components": clean_components,
        "design_memory_result": memory,
        "next_actions": next_actions,
    }
