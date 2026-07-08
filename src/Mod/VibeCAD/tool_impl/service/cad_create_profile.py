# SPDX-License-Identifier: LGPL-2.1-or-later

"""AI-native profile authoring tool."""

from __future__ import annotations

from typing import Any

from .cad_common import append_design_memory, backend_ok, call_backend, find_body_name


CURVE_KINDS = {"arc", "circle", "ellipse", "bspline"}
ENTITY_KINDS = ("line", "polyline", "arc", "circle", "ellipse", "bspline", "point")


TOOL_SPEC = {
    "name": "cad.create_profile",
    "description": (
        "Create a named Sketcher profile for a component using explicit entity "
        "types. Lines are straight; arcs/ellipses/bsplines are real curves. "
        "Use this instead of low-level sketcher tools for normal profile work."
    ),
    "safety": "SAFE_WRITE",
    "parameters": {
        "type": "object",
        "properties": {
            "component_name": {"type": "string"},
            "body_name": {"type": "string"},
            "profile_name": {"type": "string"},
            "purpose": {"type": "string"},
            "support": {
                "type": "object",
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": ["origin_plane", "datum_plane", "face"],
                    },
                    "plane": {
                        "type": "string",
                        "enum": ["XY_Plane", "XZ_Plane", "YZ_Plane"],
                    },
                    "object": {"type": "string"},
                    "subelement": {"type": "string"},
                    "normal": {
                        "type": "object",
                        "properties": {
                            "x": {"type": "number"},
                            "y": {"type": "number"},
                            "z": {"type": "number"},
                        },
                    },
                },
            },
            "entities": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "kind": {"type": "string", "enum": list(ENTITY_KINDS)},
                        "points": {
                            "type": "array",
                            "items": {
                                "type": "array",
                                "items": {"type": "number"},
                                "minItems": 2,
                                "maxItems": 2,
                            },
                        },
                        "center": {
                            "type": "array",
                            "items": {"type": "number"},
                            "minItems": 2,
                            "maxItems": 2,
                        },
                        "radius": {"type": "number"},
                        "start_angle_degrees": {"type": "number"},
                        "end_angle_degrees": {"type": "number"},
                        "major_radius": {"type": "number"},
                        "minor_radius": {"type": "number"},
                        "angle_degrees": {"type": "number"},
                        "closed": {"type": "boolean"},
                        "periodic": {"type": "boolean"},
                        "interpolate": {"type": "boolean"},
                        "construction": {"type": "boolean"},
                    },
                    "required": ["kind"],
                },
            },
            "constraints": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {
                            "type": "string",
                            "description": "Native Sketcher constraint type, e.g. Coincident, Tangent, Radius, DistanceX, DistanceY, Lock, Block.",
                        },
                        "entity": {
                            "type": "string",
                            "description": "First entity name from entities[].name.",
                        },
                        "point": {
                            "type": "string",
                            "description": "Point role on entity: start, end, center, midpoint, whole.",
                        },
                        "second_entity": {"type": "string"},
                        "second_point": {"type": "string"},
                        "third_entity": {"type": "string"},
                        "third_point": {"type": "string"},
                        "value": {"type": "number"},
                        "x": {"type": "number"},
                        "y": {"type": "number"},
                    },
                    "required": ["type", "entity"],
                },
            },
            "requires_curves": {"type": "boolean"},
            "close_after": {"type": "boolean"},
        },
        "required": ["component_name", "profile_name", "purpose", "entities"],
    },
}


def _geometry_index_from_add_result(result: dict[str, Any]) -> int | None:
    transaction = result.get("transaction")
    if not isinstance(transaction, dict):
        return None
    payload = transaction.get("result")
    if not isinstance(payload, dict):
        return None
    if "geometry_index" not in payload:
        return None
    try:
        return int(payload["geometry_index"])
    except (TypeError, ValueError):
        return None


def _body_for_profile(service: Any, component_name: str, body_name: str | None) -> tuple[str | None, dict[str, Any] | None]:
    requested_body = find_body_name(service, body_name) if body_name else None
    if requested_body:
        return requested_body, None
    component_body = find_body_name(service, component_name)
    if component_body:
        return component_body, None
    created = call_backend(service, "partdesign.create_body", label=component_name)
    body = created.get("active_body") if isinstance(created, dict) else None
    return (str(body) if body else None), created


def _add_entity(service: Any, sketch_name: str, entity: dict[str, Any]) -> dict[str, Any]:
    kind = str(entity.get("kind") or "").strip().lower()
    if kind not in ENTITY_KINDS:
        return {"ok": False, "error": f"Unknown profile entity kind: {kind!r}."}
    args: dict[str, Any] = {
        "sketch_name": sketch_name,
        "kind": kind,
        "construction": bool(entity.get("construction", False)),
    }
    for key in (
        "points",
        "center",
        "radius",
        "start_angle_degrees",
        "end_angle_degrees",
        "major_radius",
        "minor_radius",
        "angle_degrees",
        "closed",
        "periodic",
        "interpolate",
    ):
        if key in entity:
            args[key] = entity[key]
    result = call_backend(service, "sketcher.add_geometry", **args)
    name = str(entity.get("name") or "").strip()
    geometry_index = _geometry_index_from_add_result(result)
    if name and geometry_index is not None and backend_ok(result):
        result["name_result"] = call_backend(
            service,
            "sketcher.set_geometry_name",
            sketch_name=sketch_name,
            geometry_index=geometry_index,
            geometry_name=name,
        )
    return result


def _constraint_args(sketch_name: str, item: dict[str, Any]) -> dict[str, Any]:
    clean_type = str(item.get("type") or "").strip()
    entity = str(item.get("entity") or "").strip()
    if not clean_type:
        raise ValueError("Constraint type is required.")
    if not entity:
        raise ValueError("Constraint entity is required.")
    args: dict[str, Any] = {
        "sketch_name": sketch_name,
        "constraint_type": clean_type,
        "first_geometry_handle": f"name:{entity}",
    }
    if str(item.get("point") or "").strip():
        args["first_point"] = str(item["point"]).strip()
    second = str(item.get("second_entity") or "").strip()
    if second:
        args["second_geometry_handle"] = f"name:{second}"
        if str(item.get("second_point") or "").strip():
            args["second_point"] = str(item["second_point"]).strip()
    third = str(item.get("third_entity") or "").strip()
    if third:
        args["third_geometry_handle"] = f"name:{third}"
        if str(item.get("third_point") or "").strip():
            args["third_point"] = str(item["third_point"]).strip()
    for key in ("value", "x", "y"):
        if key in item:
            args[key] = item[key]
    return args


def _add_constraint(service: Any, sketch_name: str, item: dict[str, Any]) -> dict[str, Any]:
    try:
        args = _constraint_args(sketch_name, item)
    except ValueError as exc:
        return {"ok": False, "error": str(exc), "constraint": item}
    return call_backend(service, "sketcher.add_constraint", **args)


def run(
    service: Any,
    component_name: str,
    profile_name: str,
    purpose: str,
    entities: list[dict[str, Any]],
    body_name: str | None = None,
    support: dict[str, Any] | None = None,
    constraints: list[dict[str, Any]] | None = None,
    requires_curves: bool = False,
    close_after: bool = False,
) -> dict[str, Any]:
    clean_component = str(component_name or "").strip()
    clean_profile = str(profile_name or "").strip()
    clean_purpose = str(purpose or "").strip()
    if not clean_component:
        return {"ok": False, "error": "component_name is required."}
    if not clean_profile:
        return {"ok": False, "error": "profile_name is required."}
    if not clean_purpose:
        return {"ok": False, "error": "purpose is required."}
    if not isinstance(entities, list) or not entities:
        return {"ok": False, "error": "entities must be a non-empty list."}

    body, body_result = _body_for_profile(service, clean_component, body_name)
    if not body:
        return {
            "ok": False,
            "error": f"No PartDesign Body available for component {clean_component!r}.",
            "body_result": body_result,
        }

    support = support or {}
    support_type = str(support.get("type") or "origin_plane")
    sketch_result = call_backend(
        service,
        "partdesign.create_sketch",
        body_name=body,
        label=clean_profile,
        support_type=support_type,
        plane=str(support.get("plane") or "XY_Plane"),
        support_object=support.get("object"),
        subelement=support.get("subelement"),
        normal=support.get("normal"),
    )
    sketch_name = sketch_result.get("active_sketch") or sketch_result.get("sketch")
    if not sketch_name:
        transaction = sketch_result.get("transaction")
        if isinstance(transaction, dict) and isinstance(transaction.get("result"), dict):
            sketch_name = transaction["result"].get("sketch")
    if not backend_ok(sketch_result) or not sketch_name:
        return {
            "ok": False,
            "error": "Could not create profile sketch.",
            "sketch_result": sketch_result,
            "body_result": body_result,
        }

    entity_results = []
    kind_counts: dict[str, int] = {}
    for raw_entity in entities:
        if not isinstance(raw_entity, dict):
            entity_results.append({"ok": False, "error": "Profile entity must be an object."})
            continue
        kind = str(raw_entity.get("kind") or "").strip().lower()
        kind_counts[kind] = kind_counts.get(kind, 0) + 1
        entity_results.append(_add_entity(service, str(sketch_name), raw_entity))
        if not backend_ok(entity_results[-1]):
            break

    constraint_results = []
    if all(backend_ok(item) for item in entity_results):
        for raw_constraint in constraints or []:
            if not isinstance(raw_constraint, dict):
                constraint_results.append(
                    {"ok": False, "error": "Profile constraint must be an object."}
                )
                continue
            constraint_results.append(
                _add_constraint(service, str(sketch_name), raw_constraint)
            )
            if not backend_ok(constraint_results[-1]):
                break

    inspect = call_backend(
        service,
        "sketcher.inspect_sketch",
        sketch_name=str(sketch_name),
        include=["geometry", "solver", "profile", "profile_deep"],
    )
    close_result = None
    if bool(close_after):
        close_result = call_backend(service, "sketcher.close_sketch", sketch_name=str(sketch_name))

    curve_count = sum(kind_counts.get(kind, 0) for kind in CURVE_KINDS)
    warnings = []
    if bool(requires_curves) and curve_count == 0:
        warnings.append(
            "requires_curves=true but the profile contains no arc/circle/ellipse/bspline entities."
        )
    memory = append_design_memory(
        service,
        sketches_features=[
            f"{clean_component}.{clean_profile}: {clean_purpose}; entities={kind_counts}"
        ],
    )
    ok = (
        all(backend_ok(item) for item in entity_results)
        and all(backend_ok(item) for item in constraint_results)
        and backend_ok(inspect)
        and (close_result is None or backend_ok(close_result))
        and not warnings
    )
    repair_actions = []
    if not all(backend_ok(item) for item in entity_results):
        repair_actions.append(
            {
                "tool": "cad.create_profile",
                "why": (
                    "Recreate the profile with corrected entity definitions. "
                    "Use explicit entity kinds and sketch-local [x,y] points."
                ),
            }
        )
    if not all(backend_ok(item) for item in constraint_results):
        repair_actions.append(
            {
                "tool": "cad.create_profile",
                "why": (
                    "Recreate or extend the profile with corrected named constraints. "
                    "Use entity names from entities[].name and point roles such as start, end, center, whole."
                ),
            }
        )
    if warnings:
        repair_actions.append(
            {
                "tool": "cad.create_profile",
                "why": (
                    "The profile contradicted its stated surface character. "
                    "Author real arc, ellipse, circle, bspline, loft, or sweep geometry instead of straight stand-ins."
                ),
            }
        )
    if not backend_ok(inspect):
        repair_actions.append(
            {
                "tool": "cad.inspect_state",
                "why": "Inspect current document, active sketch, and errors before another profile write.",
            }
        )
    return {
        "ok": ok,
        "component": clean_component,
        "body": body,
        "profile": str(sketch_name),
        "profile_label": clean_profile,
        "purpose": clean_purpose,
        "body_result": body_result,
        "sketch_result": sketch_result,
        "entity_kind_counts": kind_counts,
        "authored_curve_entity_count": curve_count,
        "entity_results": entity_results,
        "constraint_results": constraint_results,
        "inspect_result": inspect,
        "close_result": close_result,
        "warnings": warnings,
        "repair_actions": repair_actions,
        "design_memory_result": memory,
    }
