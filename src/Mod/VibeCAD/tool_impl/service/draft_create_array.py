# SPDX-License-Identifier: LGPL-2.1-or-later

"""Service tool definition for ``draft.create_array``."""

from __future__ import annotations

from numbers import Integral, Real
from typing import Any

from VibeCADTransactions import run_freecad_transaction

from . import domain_runtime


TOOL_SPEC = {'description': 'Create a native Draft ortho or polar array of a whole '
                'object. Use partdesign.pattern to repeat features inside a Body. '
                'Set fuse=true only when touching copies must merge.',
 'name': 'draft.create_array',
 'parameters': {'properties': {'array_type': {'description': 'ortho: rectangular grid; polar: circular arrangement.',
                                              'enum': ['ortho', 'polar'],
                                              'type': 'string'},
                               'center_x': {'description': 'polar only: center X in mm.',
                                            'type': 'number'},
                               'center_y': {'description': 'polar only: center Y in mm.',
                                            'type': 'number'},
                               'center_z': {'description': 'polar only: center Z in mm.',
                                            'type': 'number'},
                               'interval_x': {'description': 'ortho only: explicit X spacing in mm.',
                                              'type': 'number'},
                               'interval_y': {'description': 'ortho only: explicit Y spacing in mm.',
                                              'type': 'number'},
                               'interval_z': {'description': 'ortho only: explicit Z spacing in mm.',
                                              'type': 'number'},
                               'label': {'type': 'string'},
                               'number_x': {'description': 'ortho only: explicit copies along X.',
                                            'type': 'integer'},
                               'number_y': {'description': 'ortho only: explicit copies along Y.',
                                            'type': 'integer'},
                               'number_z': {'description': 'ortho only: explicit copies along Z.',
                                            'type': 'integer'},
                               'object_name': {'description': 'Object name or label to array.',
                                               'type': 'string'},
                               'polar_angle': {'description': 'polar only: explicit total sweep angle in degrees.',
                                               'type': 'number'},
                               'polar_count': {'description': 'polar only: explicit number of copies including the original.',
                                               'type': 'integer'},
                               'use_link': {'description': 'Explicitly choose whether to create a lightweight Link array instead of copies. Link arrays cannot be fused.',
                                            'type': 'boolean'},
                               'fuse': {'description': 'Explicitly choose whether to fuse touching/overlapping copies into one connected solid. Requires use_link=false.',
                                        'type': 'boolean'}},
                'required': ['object_name', 'array_type', 'use_link', 'fuse'],
                'type': 'object'},
 'safety': 'SAFE_WRITE',
 'workbench': 'DraftWorkbench'}


def _validation_error(message: str) -> dict[str, Any]:
    return {"ok": False, "error": message, "retry_same_call": False}


def _number_arg(name: str, value: Any) -> tuple[bool, float | str]:
    if value is None:
        return False, f"{name} is required and must be an explicit number."
    if isinstance(value, bool) or not isinstance(value, Real):
        return False, f"{name} must be a number."
    return True, float(value)


def _integer_arg(name: str, value: Any) -> tuple[bool, int | str]:
    if value is None:
        return False, f"{name} is required and must be an explicit integer."
    if isinstance(value, bool) or not isinstance(value, Integral):
        return False, f"{name} must be an integer."
    return True, int(value)


def _bool_arg(name: str, value: Any) -> tuple[bool, bool | str]:
    if value is None:
        return False, f"{name} is required and must be true or false."
    if not isinstance(value, bool):
        return False, f"{name} must be true or false."
    return True, value


def run(
    service,
    object_name: str,
    label: str = "VibeCAD Array",
    array_type: str | None = None,
    number_x: int | None = None,
    number_y: int | None = None,
    number_z: int | None = None,
    interval_x: float | None = None,
    interval_y: float | None = None,
    interval_z: float | None = None,
    polar_count: int | None = None,
    polar_angle: float | None = None,
    center_x: float | None = None,
    center_y: float | None = None,
    center_z: float | None = None,
    use_link: bool | None = None,
    fuse: bool | None = None,
) -> dict[str, Any]:
    source = service._get_document_object(object_name)
    if source is None:
        return {"ok": False, "error": f"Object not found: {object_name}"}
    kind = str(array_type or "").lower().strip()
    if kind not in {"ortho", "polar"}:
        return _validation_error("array_type must be exactly 'ortho' or 'polar'.")
    ok, parsed_use_link = _bool_arg("use_link", use_link)
    if not ok:
        return _validation_error(str(parsed_use_link))
    ok, parsed_fuse = _bool_arg("fuse", fuse)
    if not ok:
        return _validation_error(str(parsed_fuse))
    if parsed_fuse and parsed_use_link:
        return _validation_error("fuse=true requires a regular array; set use_link=false.")

    ortho_values: dict[str, float | int] = {}
    polar_values: dict[str, float | int] = {}
    if kind == "ortho":
        for name, value in (
            ("number_x", number_x),
            ("number_y", number_y),
            ("number_z", number_z),
        ):
            ok, result = _integer_arg(name, value)
            if not ok:
                return _validation_error(str(result))
            ortho_values[name] = int(result)
        for name, value in (
            ("interval_x", interval_x),
            ("interval_y", interval_y),
            ("interval_z", interval_z),
        ):
            ok, result = _number_arg(name, value)
            if not ok:
                return _validation_error(str(result))
            ortho_values[name] = float(result)
        counts = (
            int(ortho_values["number_x"]),
            int(ortho_values["number_y"]),
            int(ortho_values["number_z"]),
        )
        if any(count < 1 for count in counts) or counts == (1, 1, 1):
            return _validation_error("Ortho arrays need positive counts and at least one repeated axis.")
        for count_name, interval_name in (
            ("number_x", "interval_x"),
            ("number_y", "interval_y"),
            ("number_z", "interval_z"),
        ):
            if int(ortho_values[count_name]) > 1 and float(ortho_values[interval_name]) == 0.0:
                return _validation_error(f"{interval_name} must be non-zero when {count_name} is greater than 1.")
    else:
        ok, result = _integer_arg("polar_count", polar_count)
        if not ok:
            return _validation_error(str(result))
        polar_values["polar_count"] = int(result)
        ok, result = _number_arg("polar_angle", polar_angle)
        if not ok:
            return _validation_error(str(result))
        polar_values["polar_angle"] = float(result)
        for name, value in (
            ("center_x", center_x),
            ("center_y", center_y),
            ("center_z", center_z),
        ):
            ok, result = _number_arg(name, value)
            if not ok:
                return _validation_error(str(result))
            polar_values[name] = float(result)
        if int(polar_values["polar_count"]) < 2:
            return _validation_error("Polar arrays need at least two copies.")
        if float(polar_values["polar_angle"]) == 0.0:
            return _validation_error("polar_angle must be non-zero.")

    def _create() -> dict[str, Any]:
        import FreeCAD as App
        import Draft

        base = service._get_document_object(object_name)
        if base is None:
            raise RuntimeError(f"Object not found: {object_name}")
        if kind == "ortho":
            array_obj = Draft.make_ortho_array(
                base,
                App.Vector(float(ortho_values["interval_x"]), 0, 0),
                App.Vector(0, float(ortho_values["interval_y"]), 0),
                App.Vector(0, 0, float(ortho_values["interval_z"])),
                int(ortho_values["number_x"]),
                int(ortho_values["number_y"]),
                int(ortho_values["number_z"]),
                use_link=bool(parsed_use_link),
            )
            metadata = {
                "array_type": "ortho",
                "counts": [
                    int(ortho_values["number_x"]),
                    int(ortho_values["number_y"]),
                    int(ortho_values["number_z"]),
                ],
                "intervals": [
                    float(ortho_values["interval_x"]),
                    float(ortho_values["interval_y"]),
                    float(ortho_values["interval_z"]),
                ],
            }
        else:
            center = App.Vector(
                float(polar_values["center_x"]),
                float(polar_values["center_y"]),
                float(polar_values["center_z"]),
            )
            array_obj = Draft.make_polar_array(
                base,
                int(polar_values["polar_count"]),
                float(polar_values["polar_angle"]),
                center,
                use_link=bool(parsed_use_link),
            )
            metadata = {
                "array_type": "polar",
                "count": int(polar_values["polar_count"]),
                "angle": float(polar_values["polar_angle"]),
                "center": [
                    float(polar_values["center_x"]),
                    float(polar_values["center_y"]),
                    float(polar_values["center_z"]),
                ],
            }
        array_obj.Label = label
        if bool(parsed_fuse) and hasattr(array_obj, "Fuse"):
            array_obj.Fuse = True
        doc = App.ActiveDocument
        if doc is not None:
            doc.recompute()
        shape = getattr(array_obj, "Shape", None)
        metadata.update(
            {
                "object": array_obj.Name,
                "label": array_obj.Label,
                "type": getattr(array_obj, "TypeId", ""),
                "base": base.Name,
                "use_link": bool(parsed_use_link),
                "fuse": bool(getattr(array_obj, "Fuse", False)),
                "solids": len(getattr(shape, "Solids", []) or []),
            }
        )
        return metadata

    transaction = run_freecad_transaction(
        f"Create Draft {kind} array: {object_name}",
        _create,
    )
    return {"ok": bool(transaction.get("ok")), "transaction": transaction, "draft": domain_runtime.draft_summary(service)}
