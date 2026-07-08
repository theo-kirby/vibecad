# SPDX-License-Identifier: LGPL-2.1-or-later

"""Service tool definition for ``core.list_workbench_objects``.

Single workbench-aware read tool that replaces the retired per-workbench
``*.get_objects`` / ``fem.get_analyses`` / ``cam.get_jobs`` clones. It routes
to the specialized domain summaries when the workbench has one, and falls
back to tool-pack object matching (with shape summaries) otherwise.
"""

from __future__ import annotations

from typing import Any

from VibeCADWorkbenchTools import get_tool_pack

from . import domain_runtime


TOOL_SPEC = {'contextual': True,
 'description': 'List active-document objects for a workbench with '
                'workbench-specific summaries (shape counts, bounds, dimensions, '
                'roles). Replaces the per-workbench get_objects tools; also covers '
                'FEM analyses and CAM jobs.',
 'name': 'core.list_workbench_objects',
 'parameters': {'properties': {'workbench': {'description': 'Optional workbench name '
                                                            '(e.g. PartWorkbench, '
                                                            'MeshWorkbench, '
                                                            'FemWorkbench). Defaults '
                                                            'to the active workbench.',
                                             'type': 'string'},
                               'object_name': {'description': 'Optional object name or '
                                                              'label to select (FEM '
                                                              'analysis or CAM job).',
                                               'type': 'string'},
                               'limit': {'description': 'Maximum objects per list '
                                                        '(default 40).',
                                         'type': 'integer'}},
                'type': 'object'},
 'safety': 'READ'}


_DEFAULT_LIMIT = 40

# Workbenches with specialized domain summaries. Values are callables of
# (service, object_name) -> dict.
_SPECIALIZED_SUMMARIES = {
    "PartWorkbench": lambda service, name: domain_runtime.part_summary(service),
    "DraftWorkbench": lambda service, name: domain_runtime.draft_summary(service),
    "MeshWorkbench": lambda service, name: domain_runtime.mesh_summary(service),
    "PointsWorkbench": lambda service, name: domain_runtime.points_summary(service),
    "MaterialWorkbench": lambda service, name: domain_runtime.material_summary(service),
    "BIMWorkbench": lambda service, name: domain_runtime.bim_summary(service),
    "InspectionWorkbench": lambda service, name: domain_runtime.inspection_summary(service),
    "OpenSCADWorkbench": lambda service, name: domain_runtime.openscad_summary(service),
    "SurfaceWorkbench": lambda service, name: domain_runtime.surface_summary(service),
    "ReverseEngineeringWorkbench": lambda service, name: domain_runtime.reverseengineering_summary(service),
    "RobotWorkbench": lambda service, name: domain_runtime.robot_summary(service),
    "MeshPartWorkbench": lambda service, name: domain_runtime.meshpart_summary(service),
    "FemWorkbench": lambda service, name: domain_runtime.fem_summary(service, name),
    "CAMWorkbench": lambda service, name: domain_runtime.cam_summary(service, name),
    "PartDesignWorkbench": lambda service, name: domain_runtime.partdesign_summary(service, name),
    "TechDrawWorkbench": lambda service, name: domain_runtime.techdraw_summary(service, name),
    "AssemblyWorkbench": lambda service, name: domain_runtime.assembly_summary(service),
}

_LIST_KEYS = (
    "objects",
    "candidates",
    "outputs",
    "features",
    "analyses",
    "jobs",
    "bodies",
    "pages",
    "assemblies",
    "part_candidates",
    "meshes",
)


def run(service, **kwargs):
    active = kwargs.get("workbench") or _active_workbench_name()
    object_name = kwargs.get("object_name")
    try:
        limit = max(1, int(kwargs.get("limit") or _DEFAULT_LIMIT))
    except (TypeError, ValueError):
        limit = _DEFAULT_LIMIT

    workbench = _normalize_workbench(active)
    result: dict[str, Any] = {
        "active_workbench": active,
        "workbench": workbench,
    }

    summarize = _SPECIALIZED_SUMMARIES.get(workbench or "")
    if summarize is not None:
        summary = summarize(service, object_name)
        if isinstance(summary, dict):
            result.update(_bound_summary_lists(summary, limit))
        result["summary_kind"] = "workbench_specific"
        return result

    # Generic workbench summary: match objects against the tool-pack metadata.
    pack = get_tool_pack(workbench or active)
    doc = service._active_document()
    objects = []
    if doc is not None and pack is not None:
        objects = [
            service._document_object_summary(obj)
            for obj in doc.Objects
            if service._object_matches_pack(obj, pack)
        ]
    visible, bounds = _bounded_items(objects, limit)
    result.update(
        {
            "tool_pack": pack.workbench if pack else None,
            "object_count": len(objects),
            "object_limit": bounds["limit"],
            "objects_truncated": bounds["truncated"],
            "objects_omitted": bounds["omitted"],
            "objects": visible,
            "summary_kind": "tool_pack_match",
        }
    )
    return result


def _normalize_workbench(name: Any) -> str | None:
    if not name:
        return None
    text = str(name).strip()
    if not text:
        return None
    lowered = text.lower()
    for canonical in _SPECIALIZED_SUMMARIES:
        if lowered == canonical.lower():
            return canonical
        if lowered == canonical.lower().removesuffix("workbench"):
            return canonical
    if lowered.endswith("workbench"):
        return text
    return text + "Workbench" if text[:1].isupper() else text


def _bound_summary_lists(summary: dict[str, Any], limit: int) -> dict[str, Any]:
    bounded: dict[str, Any] = {}
    for key, value in summary.items():
        if key in _LIST_KEYS and isinstance(value, list) and len(value) > limit:
            bounded[key] = value[:limit]
            bounded[f"{key}_omitted"] = len(value) - limit
            bounded[f"{key}_truncated"] = True
        else:
            bounded[key] = value
    return bounded


def _active_workbench_name():
    try:
        import FreeCADGui as Gui

        workbench = Gui.activeWorkbench()
        if workbench:
            return workbench.name()
    except Exception:
        pass
    return None


def _bounded_items(items, limit):
    safe_limit = max(0, int(limit))
    visible = list(items[:safe_limit])
    omitted = max(0, len(items) - len(visible))
    return visible, {
        "limit": safe_limit,
        "truncated": omitted > 0,
        "omitted": omitted,
    }
