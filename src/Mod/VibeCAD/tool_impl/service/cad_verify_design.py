# SPDX-License-Identifier: LGPL-2.1-or-later

"""AI-native design verification tool."""

from __future__ import annotations

from typing import Any

from . import domain_runtime
from .cad_common import call_backend


CHECKS = (
    "errors",
    "design_memory",
    "obligations",
    "object_existence",
    "body_shapes",
    "sketch_profiles",
    "screenshot",
)


TOOL_SPEC = {
    "name": "cad.verify_design",
    "description": (
        "Verify current CAD against design obligations: report errors, design "
        "memory, object existence, body shape validity, sketch profile health, "
        "and optional viewport screenshot."
    ),
    "safety": "VIEW",
    "parameters": {
        "type": "object",
        "properties": {
            "checks": {
                "type": "array",
                "items": {"type": "string", "enum": list(CHECKS)},
            },
            "object_names": {"type": "array", "items": {"type": "string"}},
            "sketch_names": {"type": "array", "items": {"type": "string"}},
            "body_names": {"type": "array", "items": {"type": "string"}},
        },
    },
}


def _document_objects(service: Any) -> list[Any]:
    doc = service._active_document()
    if doc is None:
        return []
    return list(getattr(doc, "Objects", []) or [])


def run(
    service: Any,
    checks: list[str] | None = None,
    object_names: list[str] | None = None,
    sketch_names: list[str] | None = None,
    body_names: list[str] | None = None,
) -> dict[str, Any]:
    selected = [str(item) for item in (checks or ["errors", "design_memory", "obligations", "body_shapes", "sketch_profiles"])]
    unknown = sorted(set(selected) - set(CHECKS))
    if unknown:
        return {"ok": False, "error": f"Unknown verification checks: {unknown}."}

    issues: list[str] = []
    result: dict[str, Any] = {"ok": True, "checks": selected}

    if "errors" in selected:
        errors = call_backend(service, "core.get_report_view_errors", include_stale=True)
        result["report_view_errors"] = errors
        if isinstance(errors, dict) and errors.get("errors"):
            issues.append("Report view contains FreeCAD errors.")

    if "design_memory" in selected:
        project = service.project_context()
        memory = project.get("design_memory", {})
        result["design_memory"] = memory
        if not isinstance(memory, dict) or not any(memory.values()):
            issues.append("No accepted design memory is present.")

    if "obligations" in selected:
        project = service.project_context()
        memory = project.get("design_memory", {})
        if not isinstance(memory, dict):
            memory = {}
        obligation_keys = (
            "components",
            "interfaces",
            "envelopes",
            "mechanisms",
            "critical_geometry",
            "verification_checks",
            "forbidden_shortcuts",
            "known_failures",
        )
        obligations: dict[str, list[str]] = {}
        for key in obligation_keys:
            values = memory.get(key)
            if isinstance(values, list) and values:
                obligations[key] = [str(item) for item in values]
        unverified = []
        for key, values in obligations.items():
            for value in values:
                unverified.append({"kind": key, "obligation": value})
        result["design_obligations"] = {
            "obligations": obligations,
            "unverified_by_this_tool": unverified,
            "note": (
                "This check exposes standing semantic obligations. It does not "
                "prove motion, clearance, fit, load, or manufacturing behavior "
                "unless the requested object/body/sketch checks directly cover them."
            ),
        }

    if "object_existence" in selected:
        objects = []
        for raw_name in object_names or []:
            name = str(raw_name or "").strip()
            if not name:
                continue
            obj = service._get_document_object(name)
            found = obj is not None
            if not found:
                issues.append(f"Required object not found: {name}")
            objects.append(
                {
                    "requested": name,
                    "found": found,
                    "name": getattr(obj, "Name", None) if obj is not None else None,
                    "label": getattr(obj, "Label", None) if obj is not None else None,
                    "type": getattr(obj, "TypeId", None) if obj is not None else None,
                }
            )
        result["objects"] = objects

    if "body_shapes" in selected:
        requested = [str(item).strip() for item in (body_names or []) if str(item).strip()]
        bodies = []
        if requested:
            for name in requested:
                body = service._get_partdesign_body(name)
                if body is not None:
                    bodies.append(body)
                else:
                    issues.append(f"Required Body not found: {name}")
        else:
            bodies = [
                obj
                for obj in _document_objects(service)
                if getattr(obj, "TypeId", "") == "PartDesign::Body"
            ]
        body_reports = []
        for body in bodies:
            shape = domain_runtime.shape_summary(body)
            if int(shape.get("solids", 0) or 0) <= 0:
                issues.append(f"Body has no solid shape: {getattr(body, 'Label', body.Name)}")
            body_reports.append(
                {
                    "name": body.Name,
                    "label": getattr(body, "Label", body.Name),
                    "shape": shape,
                    "feature_count": len(getattr(body, "Group", []) or []),
                    "tip": getattr(getattr(body, "Tip", None), "Name", None),
                }
            )
        result["body_shapes"] = body_reports

    if "sketch_profiles" in selected:
        requested_sketches = [
            str(item).strip() for item in (sketch_names or []) if str(item).strip()
        ]
        sketches = []
        if requested_sketches:
            for name in requested_sketches:
                sketch = service._get_sketch(name)
                if sketch is not None:
                    sketches.append(sketch)
                else:
                    issues.append(f"Required Sketch not found: {name}")
        else:
            sketches = [
                obj
                for obj in _document_objects(service)
                if getattr(obj, "TypeId", "") == "Sketcher::SketchObject"
            ]
        sketch_reports = []
        for sketch in sketches:
            inspection = call_backend(
                service,
                "sketcher.inspect_sketch",
                sketch_name=sketch.Name,
                include=["geometry", "solver", "profile"],
            )
            profile = inspection.get("profile_validation") if isinstance(inspection, dict) else {}
            if isinstance(profile, dict) and profile.get("closed") is False:
                issues.append(f"Sketch profile is not closed: {getattr(sketch, 'Label', sketch.Name)}")
            sketch_reports.append(inspection)
        result["sketch_profiles"] = sketch_reports

    if "screenshot" in selected:
        result["screenshot"] = call_backend(service, "core.capture_view_screenshot")

    result["issues"] = issues
    result["ok"] = not issues
    return result
