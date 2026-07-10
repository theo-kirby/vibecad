# SPDX-License-Identifier: LGPL-2.1-or-later

"""Exact native geometric measurements for PartDesign decisions."""

from __future__ import annotations

import math
from typing import Any

from . import domain_runtime, partdesign_find_subelements


REFERENCE_SCHEMA = {
    "type": "object",
    "properties": {
        "object_name": {"type": "string"},
        "subelement": {"type": "string"},
    },
    "required": ["object_name", "subelement"],
    "additionalProperties": False,
}

TOOL_SPEC = {
    "name": "partdesign.measure",
    "description": (
        "Measure exact native object/subelement geometry, minimum distance, or direction angle. "
        "Returns CAD facts only; it does not infer requirement satisfaction or choose geometry."
    ),
    "contextual": True,
    "safety": "READ",
    "workbench": "PartDesignWorkbench",
    "edit_modes": ["none"],
    "parameters": {
        "type": "object",
        "properties": {
            "measurement": {
                "oneOf": [
                    {
                        "type": "object",
                        "properties": {
                            "type": {"const": "geometry"},
                            "object_name": {"type": "string"},
                            "subelements": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                        },
                        "required": ["type", "object_name", "subelements"],
                        "additionalProperties": False,
                    },
                    {
                        "type": "object",
                        "properties": {
                            "type": {"const": "distance"},
                            "first": REFERENCE_SCHEMA,
                            "second": REFERENCE_SCHEMA,
                        },
                        "required": ["type", "first", "second"],
                        "additionalProperties": False,
                    },
                    {
                        "type": "object",
                        "properties": {
                            "type": {"const": "angle"},
                            "first": REFERENCE_SCHEMA,
                            "second": REFERENCE_SCHEMA,
                        },
                        "required": ["type", "first", "second"],
                        "additionalProperties": False,
                    },
                ]
            }
        },
        "required": ["measurement"],
        "additionalProperties": False,
    },
}


def run(service: Any, measurement: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(measurement, dict):
        return _invalid("measurement must be an object.")
    kind = str(measurement.get("type") or "")
    if kind == "geometry":
        return _measure_geometry(
            service,
            measurement.get("object_name"),
            measurement.get("subelements"),
        )
    if kind == "distance":
        return _measure_distance(service, measurement.get("first"), measurement.get("second"))
    if kind == "angle":
        return _measure_angle(service, measurement.get("first"), measurement.get("second"))
    return _invalid("measurement.type must be geometry, distance, or angle.")


def _measure_geometry(service: Any, object_name: Any, subelements: Any) -> dict[str, Any]:
    resolved = _resolve_object(service, object_name)
    if not resolved.get("ok"):
        return resolved
    obj = resolved["object"]
    if not isinstance(subelements, list):
        return _invalid("measurement.subelements must be an array.")
    names = [str(value or "").strip() for value in subelements]
    if len(set(names)) != len(names):
        return _invalid("measurement.subelements cannot contain duplicates.")
    shape = getattr(obj, "Shape", None)
    if shape is None or shape.isNull():
        return _invalid(f"Object {obj.Name} has no measurable shape.")
    details = []
    for name in names:
        detail = _subelement_measurement(shape, name)
        if not detail.get("ok"):
            return _invalid(
                f"Cannot measure {obj.Name}.{name}: {detail.get('error')}",
                available={
                    "faces": len(shape.Faces),
                    "edges": len(shape.Edges),
                    "vertices": len(shape.Vertexes),
                },
            )
        details.append(detail["measurement"])
    center = shape.CenterOfMass
    result = {
        "ok": True,
        "measurement_type": "geometry",
        "object": service._document_object_summary(obj),
        "shape": domain_runtime.shape_summary(obj),
        "surface_area": float(getattr(shape, "Area", 0.0) or 0.0),
        "center_of_mass": _vector(center),
        "subelements": details,
    }
    return result


def _measure_distance(service: Any, first: Any, second: Any) -> dict[str, Any]:
    first_state = _resolve_shape_reference(service, first)
    if not first_state.get("ok"):
        return first_state
    second_state = _resolve_shape_reference(service, second)
    if not second_state.get("ok"):
        return second_state
    try:
        distance, point_pairs, support = first_state["shape"].distToShape(second_state["shape"])
    except Exception as exc:
        return _invalid(f"FreeCAD could not measure the requested distance: {exc}")
    return {
        "ok": True,
        "measurement_type": "distance",
        "first": first_state["summary"],
        "second": second_state["summary"],
        "distance": float(distance),
        "closest_point_pairs": [
            {"first": _vector(pair[0]), "second": _vector(pair[1])}
            for pair in list(point_pairs or [])
        ],
        "native_support": _plain_support(support),
    }


def _measure_angle(service: Any, first: Any, second: Any) -> dict[str, Any]:
    first_state = _resolve_direction_reference(service, first)
    if not first_state.get("ok"):
        return first_state
    second_state = _resolve_direction_reference(service, second)
    if not second_state.get("ok"):
        return second_state
    dot = max(-1.0, min(1.0, float(first_state["direction"].dot(second_state["direction"]))))
    degrees = math.degrees(math.acos(dot))
    return {
        "ok": True,
        "measurement_type": "angle",
        "first": first_state["summary"],
        "second": second_state["summary"],
        "angle_degrees": degrees,
        "acute_angle_degrees": min(degrees, 180.0 - degrees),
    }


def _resolve_object(service: Any, object_name: Any) -> dict[str, Any]:
    doc = service._active_document()
    clean = str(object_name or "").strip()
    obj = doc.getObject(clean) if doc is not None and clean else None
    if obj is None:
        return _invalid(f"Object not found by exact internal name: {clean}")
    return {"ok": True, "object": obj}


def _resolve_shape_reference(service: Any, reference: Any) -> dict[str, Any]:
    if not isinstance(reference, dict):
        return _invalid("A measurement reference must be an object.")
    resolved = _resolve_object(service, reference.get("object_name"))
    if not resolved.get("ok"):
        return resolved
    obj = resolved["object"]
    shape = getattr(obj, "Shape", None)
    if shape is None or shape.isNull():
        return _invalid(f"Object {obj.Name} has no measurable shape.")
    subelement = str(reference.get("subelement") or "").strip()
    if subelement:
        try:
            shape = shape.getElement(subelement)
        except Exception:
            return _invalid(f"Subelement does not exist: {obj.Name}.{subelement}")
    return {
        "ok": True,
        "shape": shape,
        "summary": {"object_name": obj.Name, "subelement": subelement},
    }


def _resolve_direction_reference(service: Any, reference: Any) -> dict[str, Any]:
    if not isinstance(reference, dict):
        return _invalid("An angle reference must be an object.")
    resolved = _resolve_object(service, reference.get("object_name"))
    if not resolved.get("ok"):
        return resolved
    obj = resolved["object"]
    subelement = str(reference.get("subelement") or "").strip()
    direction = None
    reference_type = None
    if getattr(obj, "TypeId", "") == "PartDesign::Line" and not subelement:
        direction = obj.getDirection()
        reference_type = "datum_axis"
    elif getattr(obj, "TypeId", "") == "PartDesign::Plane" and not subelement:
        direction = obj.getNormal()
        reference_type = "datum_plane_normal"
    elif subelement.startswith("Edge"):
        try:
            edge = obj.Shape.getElement(subelement)
            canonical = partdesign_find_subelements._canonical_geometry_type(
                type(edge.Curve).__name__
            )
            if canonical != "line":
                return _invalid(f"Angle edge must be linear: {obj.Name}.{subelement}")
            direction = edge.tangentAt(edge.FirstParameter)
            reference_type = "linear_edge"
        except Exception as exc:
            return _invalid(f"Cannot resolve angle edge {obj.Name}.{subelement}: {exc}")
    elif subelement.startswith("Face"):
        try:
            face = obj.Shape.getElement(subelement)
            canonical = partdesign_find_subelements._canonical_geometry_type(
                type(face.Surface).__name__
            )
            if canonical != "plane":
                return _invalid(f"Angle face must be planar: {obj.Name}.{subelement}")
            direction = partdesign_find_subelements._outward_normal(obj.Shape, face)
            reference_type = "planar_face_normal"
        except Exception as exc:
            return _invalid(f"Cannot resolve angle face {obj.Name}.{subelement}: {exc}")
    else:
        return _invalid(
            "Angle references must be datum axes, datum planes, linear edges, or planar faces."
        )
    if direction is None or float(direction.Length) <= 1e-9:
        return _invalid("The requested angle reference has no non-zero direction.")
    direction.normalize()
    return {
        "ok": True,
        "direction": direction,
        "summary": {
            "object_name": obj.Name,
            "subelement": subelement,
            "reference_type": reference_type,
            "direction": _vector(direction),
        },
    }


def _subelement_measurement(shape: Any, name: str) -> dict[str, Any]:
    try:
        element = shape.getElement(name)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    result: dict[str, Any] = {"name": name}
    if name.startswith("Vertex"):
        result.update({"element_type": "vertex", "point": _vector(element.Point)})
    elif name.startswith("Edge"):
        curve = getattr(element, "Curve", None)
        canonical = partdesign_find_subelements._canonical_geometry_type(
            type(curve).__name__ if curve is not None else ""
        )
        result.update(
            {
                "element_type": "edge",
                "geometry_type": canonical,
                "length": float(element.Length),
                "center_of_mass": _vector(element.CenterOfMass),
                "bounding_box": partdesign_find_subelements._bounding_box_dict(
                    element.BoundBox
                ),
                "endpoints": [_vector(vertex.Point) for vertex in list(element.Vertexes)],
            }
        )
        radius = partdesign_find_subelements._element_radius(curve)
        if radius is not None:
            result["radius"] = radius
        if canonical == "line":
            direction = element.tangentAt(element.FirstParameter)
            direction.normalize()
            result["direction"] = _vector(direction)
    elif name.startswith("Face"):
        surface = getattr(element, "Surface", None)
        canonical = partdesign_find_subelements._canonical_geometry_type(
            type(surface).__name__ if surface is not None else ""
        )
        result.update(
            {
                "element_type": "face",
                "geometry_type": canonical,
                "area": float(element.Area),
                "center_of_mass": _vector(element.CenterOfMass),
                "bounding_box": partdesign_find_subelements._bounding_box_dict(
                    element.BoundBox
                ),
            }
        )
        radius = partdesign_find_subelements._element_radius(surface)
        if radius is not None:
            result["radius"] = radius
        if canonical == "plane":
            normal = partdesign_find_subelements._outward_normal(shape, element)
            if normal is not None:
                result["outward_normal"] = _vector(normal)
    else:
        return {"ok": False, "error": "Only Vertex, Edge, and Face subelements are supported."}
    return {"ok": True, "measurement": result}


def _plain_support(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        return [_plain_support(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _plain_support(item) for key, item in value.items()}
    return str(value)


def _vector(value: Any) -> dict[str, float]:
    return {"x": float(value.x), "y": float(value.y), "z": float(value.z)}


def _invalid(message: str, **details: Any) -> dict[str, Any]:
    return {"ok": False, "error": message, "retry_same_call": False, **details}
