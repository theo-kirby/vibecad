# SPDX-License-Identifier: LGPL-2.1-or-later

"""Service tool definition for ``part.dressup``.

Consolidates the retired ``part.apply_fillet``, ``part.apply_chamfer``, and
``part.apply_thickness`` tools behind a single ``operation`` discriminator.
"""

from __future__ import annotations

from numbers import Integral, Real
from typing import Any

from VibeCADTransactions import run_freecad_transaction
from . import domain_runtime


TOOL_SPEC = {'description': 'Apply a Part fillet, chamfer, or thickness feature. '
                'Use after the base shape is correct, not as a substitute for it.',
 'name': 'part.dressup',
 'parameters': {'properties': {'operation': {'description': "One of 'fillet', 'chamfer', "
                                                            "or 'thickness'.",
                                             'enum': ['fillet', 'chamfer', 'thickness'],
                                             'type': 'string'},
                               'object_name': {'description': 'Existing document object '
                                                              'to dress up.',
                                               'type': 'string'},
                               'label': {'description': 'Label for the created feature.',
                                         'type': 'string'},
                               'radius': {'description': 'Fillet radius in mm '
                                                         '(required for fillet).',
                                          'type': 'number'},
                               'distance': {'description': 'Chamfer distance in mm '
                                                           '(required for chamfer).',
                                            'type': 'number'},
                               'edge_indices': {'description': '1-based edge indices to '
                                                               'dress up (required for '
                                                               'fillet/chamfer).',
                                                'items': {'type': 'integer'},
                                                'type': 'array'},
                               'wall_thickness': {'description': 'Shell wall thickness in '
                                                                 'mm (required for '
                                                                 'thickness).',
                                                  'type': 'number'},
                               'face_names': {'description': 'Faces to remove for the '
                                                             'shell opening, e.g. '
                                                             "['Face6'] (required for "
                                                             'thickness).',
                                              'items': {'type': 'string'},
                                              'type': 'array'},
                               'inward': {'description': 'Thicken inward (required for '
                                                         'thickness).',
                                          'type': 'boolean'},
                               'mode': {'description': 'Part Thickness mode (0=Skin, '
                                                       '1=Pipe, 2=RectoVerso; required '
                                                       'for thickness).',
                                        'type': 'integer'},
                               'join': {'description': 'Part Thickness join type (0=Arc, '
                                                       '1=Tangent, 2=Intersection; required '
                                                       'for thickness).',
                                        'type': 'integer'}},
                'required': ['operation', 'object_name'],
                'type': 'object'},
 'safety': 'SAFE_WRITE',
 'workbench': 'PartWorkbench'}


_OPERATIONS = ("fillet", "chamfer", "thickness")


def _validation_error(message: str) -> dict[str, Any]:
    return {"ok": False, "error": message, "retry_same_call": False}


def _positive_number(name: str, value: Any) -> tuple[bool, float | str]:
    if value is None:
        return False, f"{name} is required and must be an explicit positive number."
    if isinstance(value, bool) or not isinstance(value, Real):
        return False, f"{name} must be a number."
    number = float(value)
    if number <= 0:
        return False, f"{name} must be positive."
    return True, number


def _explicit_bool(name: str, value: Any) -> tuple[bool, bool | str]:
    if value is None:
        return False, f"{name} is required and must be true or false."
    if not isinstance(value, bool):
        return False, f"{name} must be true or false."
    return True, value


def _explicit_enum_int(name: str, value: Any, allowed: set[int]) -> tuple[bool, int | str]:
    if value is None:
        return False, f"{name} is required and must be one of {sorted(allowed)}."
    if isinstance(value, bool) or not isinstance(value, Integral):
        return False, f"{name} must be an integer."
    number = int(value)
    if number not in allowed:
        return False, f"{name} must be one of {sorted(allowed)}."
    return True, number


def run(
    service,
    operation: str,
    object_name: str,
    label: str | None = None,
    radius: float | None = None,
    distance: float | None = None,
    edge_indices: list[int] | None = None,
    wall_thickness: float | None = None,
    face_names: list[str] | None = None,
    inward: bool | None = None,
    mode: int | None = None,
    join: int | None = None,
) -> dict[str, Any]:
    op = str(operation).strip().lower()
    if op not in _OPERATIONS:
        return {
            "ok": False,
            "error": f"Unknown operation: {operation!r}. Valid operations: {list(_OPERATIONS)}",
        }
    source = service._get_document_object(object_name)
    if source is None:
        return {"ok": False, "error": f"Object not found: {object_name}"}

    if op == "fillet":
        ok, parsed_radius = _positive_number("radius", radius)
        if not ok:
            return _validation_error(str(parsed_radius))
        edges_result = _validate_edge_indices(source, object_name, edge_indices, "filletable")
        if isinstance(edges_result, dict):
            return edges_result
        return _run_fillet(service, object_name, label or "VibeCAD Fillet", float(parsed_radius), edges_result)
    if op == "chamfer":
        ok, parsed_distance = _positive_number("distance", distance)
        if not ok:
            return _validation_error(str(parsed_distance))
        edges_result = _validate_edge_indices(source, object_name, edge_indices, "chamferable")
        if isinstance(edges_result, dict):
            return edges_result
        return _run_chamfer(service, object_name, label or "VibeCAD Chamfer", float(parsed_distance), edges_result)
    ok, parsed_thickness = _positive_number("wall_thickness", wall_thickness)
    if not ok:
        return _validation_error(str(parsed_thickness))
    faces_result = _validate_face_names(source, object_name, face_names)
    if isinstance(faces_result, dict):
        return faces_result
    ok, parsed_inward = _explicit_bool("inward", inward)
    if not ok:
        return _validation_error(str(parsed_inward))
    ok, parsed_mode = _explicit_enum_int("mode", mode, {0, 1, 2})
    if not ok:
        return _validation_error(str(parsed_mode))
    ok, parsed_join = _explicit_enum_int("join", join, {0, 1, 2})
    if not ok:
        return _validation_error(str(parsed_join))
    return _run_thickness(
        service,
        object_name,
        label or "VibeCAD Thickness",
        float(parsed_thickness),
        faces_result,
        bool(parsed_inward),
        int(parsed_mode),
        int(parsed_join),
    )


def _validate_edge_indices(
    source: Any,
    object_name: str,
    edge_indices: list[int] | None,
    verb: str,
) -> list[int] | dict[str, Any]:
    if edge_indices is None:
        return _validation_error(f"edge_indices is required for {verb} edges.")
    if not isinstance(edge_indices, list) or not edge_indices:
        return _validation_error(f"edge_indices must be a non-empty list for {verb} edges.")
    shape = getattr(source, "Shape", None)
    edges = list(getattr(shape, "Edges", []) or [])
    if not edges:
        return _validation_error(f"Object has no {verb} edges: {object_name}")
    selected: list[int] = []
    for item in edge_indices:
        if isinstance(item, bool) or not isinstance(item, Integral):
            return _validation_error("edge_indices must contain 1-based integer edge indices.")
        index = int(item)
        if index < 1 or index > len(edges):
            return _validation_error(f"Edge index out of range for {object_name}: {index}")
        if index in selected:
            return _validation_error(f"Duplicate edge index for {object_name}: {index}")
        selected.append(index)
    return selected


def _select_edges(shape: Any, object_name: str, edge_indices: list[int], verb: str) -> list[Any]:
    edges = list(getattr(shape, "Edges", []) or [])
    if not edges:
        raise RuntimeError(f"Object has no {verb} edges: {object_name}")
    selected_edges = []
    for edge_index in edge_indices:
        if 1 <= edge_index <= len(edges):
            selected_edges.append(edges[edge_index - 1])
    if not selected_edges:
        raise RuntimeError(f"No valid edge indices selected for {verb}.")
    return selected_edges


def _validate_face_names(
    source: Any,
    object_name: str,
    face_names: list[str] | None,
) -> list[str] | dict[str, Any]:
    if face_names is None:
        return _validation_error("face_names is required for thickness.")
    if not isinstance(face_names, list) or not face_names:
        return _validation_error("face_names must be a non-empty list for thickness.")
    shape = getattr(source, "Shape", None)
    faces = list(getattr(shape, "Faces", []) or [])
    if not faces:
        return _validation_error(f"Object has no faces for thickness: {object_name}")
    selected: list[str] = []
    for item in face_names:
        if not isinstance(item, str) or not item.startswith("Face"):
            return _validation_error(f"Invalid face name for thickness: {item!r}")
        try:
            face_index = int(item[4:])
        except ValueError:
            return _validation_error(f"Invalid face name for thickness: {item!r}")
        if face_index < 1 or face_index > len(faces):
            return _validation_error(f"Face name out of range for {object_name}: {item}")
        if item in selected:
            return _validation_error(f"Duplicate face name for {object_name}: {item}")
        selected.append(item)
    return selected


def _finalize(service, transaction: dict[str, Any], op: str) -> dict[str, Any]:
    return domain_runtime.build_mutation_result(
        transaction,
        extra={
            "operation": op,
            "part": domain_runtime.part_summary(service),
        },
    )


def _run_fillet(
    service,
    object_name: str,
    label: str,
    radius: float,
    edge_indices: list[int],
) -> dict[str, Any]:
    if float(radius) <= 0:
        return {"ok": False, "error": "radius must be positive"}

    def _fillet() -> dict[str, Any]:
        import FreeCAD as App

        doc = App.ActiveDocument
        if doc is None:
            raise RuntimeError("No active document.")
        target = service._get_document_object(object_name)
        if target is None:
            raise RuntimeError(f"Object not found: {object_name}")
        shape = getattr(target, "Shape", None)
        selected_edges = _select_edges(shape, object_name, edge_indices, "filletable")
        feature = doc.addObject("Part::Feature", "VibeCAD_Fillet")
        feature.Label = label
        feature.Shape = shape.makeFillet(float(radius), selected_edges)
        doc.recompute()
        return {
            "object": feature.Name,
            "label": feature.Label,
            "type": feature.TypeId,
            "source": target.Name,
            "radius": float(radius),
            "edge_count": len(selected_edges),
        }

    transaction = run_freecad_transaction(
        f"Apply Part fillet to {object_name}",
        _fillet,
    )
    return _finalize(service, transaction, "fillet")


def _run_chamfer(
    service,
    object_name: str,
    label: str,
    distance: float,
    edge_indices: list[int],
) -> dict[str, Any]:
    if float(distance) <= 0:
        return {"ok": False, "error": "distance must be positive"}

    def _chamfer() -> dict[str, Any]:
        import FreeCAD as App

        doc = App.ActiveDocument
        if doc is None:
            raise RuntimeError("No active document.")
        target = service._get_document_object(object_name)
        if target is None:
            raise RuntimeError(f"Object not found: {object_name}")
        shape = getattr(target, "Shape", None)
        selected_edges = _select_edges(shape, object_name, edge_indices, "chamferable")
        feature = doc.addObject("Part::Feature", "VibeCAD_Chamfer")
        feature.Label = label
        feature.Shape = shape.makeChamfer(float(distance), selected_edges)
        doc.recompute()
        return {
            "object": feature.Name,
            "label": feature.Label,
            "type": feature.TypeId,
            "source": target.Name,
            "distance": float(distance),
            "edge_count": len(selected_edges),
        }

    transaction = run_freecad_transaction(
        f"Apply Part chamfer to {object_name}",
        _chamfer,
    )
    return _finalize(service, transaction, "chamfer")


def _run_thickness(
    service,
    object_name: str,
    label: str,
    wall_thickness: float,
    face_names: list[str],
    inward: bool,
    mode: int,
    join: int,
) -> dict[str, Any]:
    selected_faces = list(face_names)

    def _thickness() -> dict[str, Any]:
        import FreeCAD as App

        doc = App.ActiveDocument
        if doc is None:
            raise RuntimeError("No active document.")
        target = service._get_document_object(object_name)
        if target is None:
            raise RuntimeError(f"Object not found: {object_name}")
        shape = getattr(target, "Shape", None)
        faces = list(getattr(shape, "Faces", []) or [])
        if not faces:
            raise RuntimeError(f"Object has no faces for thickness: {object_name}")
        for face_name in selected_faces:
            if not face_name.startswith("Face"):
                raise RuntimeError(f"Invalid face name: {face_name}")
            try:
                face_index = int(face_name[4:])
            except ValueError as exc:
                raise RuntimeError(f"Invalid face name: {face_name}") from exc
            if face_index < 1 or face_index > len(faces):
                raise RuntimeError(f"Face name out of range for {object_name}: {face_name}")
        feature = doc.addObject("Part::Thickness", "VibeCAD_Thickness")
        feature.Label = label
        feature.Faces = (target, selected_faces)
        feature.Value = -float(wall_thickness) if inward else float(wall_thickness)
        feature.Mode = int(mode)
        feature.Join = int(join)
        doc.recompute()
        return {
            "object": feature.Name,
            "label": feature.Label,
            "type": feature.TypeId,
            "source": target.Name,
            "face_names": selected_faces,
            "wall_thickness": float(wall_thickness),
            "inward": bool(inward),
            "mode": int(mode),
            "join": int(join),
            "mode_label": str(getattr(feature, "Mode", "")),
            "join_label": str(getattr(feature, "Join", "")),
            "face_count": len(getattr(getattr(feature, "Shape", None), "Faces", []) or []),
            "solid_count": len(getattr(getattr(feature, "Shape", None), "Solids", []) or []),
            "volume": float(getattr(getattr(feature, "Shape", None), "Volume", 0.0) or 0.0),
        }

    transaction = run_freecad_transaction(
        f"Apply Part thickness to {object_name}",
        _thickness,
    )
    return _finalize(service, transaction, "thickness")
