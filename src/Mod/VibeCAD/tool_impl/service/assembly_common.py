# SPDX-License-Identifier: LGPL-2.1-or-later

"""Shared helpers for native Assembly service tools."""

from __future__ import annotations

from typing import Any


_ASSEMBLY_INTERNAL_TYPES = {
    "Assembly::JointGroup",
    "Assembly::BomGroup",
    "Assembly::ViewGroup",
    "Assembly::SimulationGroup",
}


def object_ref(obj: Any) -> dict[str, Any]:
    return {
        "name": getattr(obj, "Name", None),
        "label": getattr(obj, "Label", getattr(obj, "Name", None)),
        "type": getattr(obj, "TypeId", None),
    }


def _active_document(service: Any) -> Any | None:
    return service._active_document()


def _document_objects(service: Any) -> list[Any]:
    doc = _active_document(service)
    if doc is None:
        return []
    return list(getattr(doc, "Objects", []) or [])


def _shape_available(obj: Any) -> bool:
    try:
        shape = getattr(obj, "Shape", None)
        return bool(shape is not None and not shape.isNull())
    except Exception:
        return False


def partdesign_owner_body(service: Any, obj: Any) -> Any | None:
    for body in service._partdesign_bodies():
        try:
            if obj in list(getattr(body, "Group", []) or []):
                return body
            if getattr(body, "Tip", None) is obj:
                return body
        except Exception:
            continue
    return None


def component_root_status(service: Any, obj: Any) -> dict[str, Any]:
    type_id = str(getattr(obj, "TypeId", ""))
    if type_id == "PartDesign::Body":
        return {
            "ok": True,
            "role": "partdesign_body",
            "reason": "PartDesign Body is a valid assembly component root.",
        }
    if type_id.startswith("PartDesign::"):
        owner = partdesign_owner_body(service, obj)
        result = {
            "ok": False,
            "role": "partdesign_feature",
            "reason": (
                "PartDesign features are Body internals, not assembly component roots; "
                "add the owning Body instead."
            ),
        }
        if owner is not None:
            result["owning_body"] = object_ref(owner)
        return result
    if type_id == "Assembly::AssemblyObject" or type_id in _ASSEMBLY_INTERNAL_TYPES:
        return {
            "ok": False,
            "role": "assembly_internal",
            "reason": "Assembly containers and internal assembly groups are not components.",
        }
    if type_id.startswith("App::Origin"):
        return {
            "ok": False,
            "role": "origin_internal",
            "reason": "Origin objects are internal references, not assembly components.",
        }
    if type_id == "App::Part":
        return {
            "ok": True,
            "role": "app_part",
            "reason": "App Part is a valid assembly component root.",
        }
    if _shape_available(obj):
        return {
            "ok": True,
            "role": "shaped_object",
            "reason": "Object has shape geometry and can be an assembly component.",
        }
    if hasattr(obj, "Placement"):
        return {
            "ok": True,
            "role": "placeable_object",
            "reason": "Object has Placement and can be positioned as an assembly component.",
        }
    return {
        "ok": False,
        "role": "unsupported_object",
        "reason": "Object has no shape or Placement property usable by Assembly.",
    }


def container_memberships(service: Any, obj: Any) -> list[dict[str, Any]]:
    memberships: list[dict[str, Any]] = []
    for owner in _document_objects(service):
        if owner is obj:
            continue
        try:
            group = list(getattr(owner, "Group", []) or [])
        except Exception:
            group = []
        if obj in group:
            memberships.append(
                {
                    "relationship": "Group",
                    "owner": object_ref(owner),
                    "group_index": group.index(obj),
                }
            )
        try:
            if getattr(owner, "Tip", None) is obj:
                memberships.append(
                    {
                        "relationship": "Tip",
                        "owner": object_ref(owner),
                    }
                )
        except Exception:
            pass
        try:
            if getattr(owner, "BaseFeature", None) is obj:
                memberships.append(
                    {
                        "relationship": "BaseFeature",
                        "owner": object_ref(owner),
                    }
                )
        except Exception:
            pass
    return memberships


def membership_delta(
    before: list[dict[str, Any]],
    after: list[dict[str, Any]],
) -> dict[str, Any]:
    def key(item: dict[str, Any]) -> tuple[str, str, str]:
        owner = item.get("owner") if isinstance(item.get("owner"), dict) else {}
        return (
            str(item.get("relationship") or ""),
            str(owner.get("name") or ""),
            str(item.get("group_index") if "group_index" in item else ""),
        )

    before_by_key = {key(item): item for item in before}
    after_by_key = {key(item): item for item in after}
    return {
        "added": [
            after_by_key[item_key]
            for item_key in sorted(set(after_by_key) - set(before_by_key))
        ],
        "removed": [
            before_by_key[item_key]
            for item_key in sorted(set(before_by_key) - set(after_by_key))
        ],
    }


def group_refs(obj: Any) -> list[dict[str, Any]]:
    return [object_ref(child) for child in list(getattr(obj, "Group", []) or [])]


def body_state(service: Any, body: Any | None) -> dict[str, Any] | None:
    if body is None:
        return None
    return {
        "body": object_ref(body),
        "group": group_refs(body),
        "tip": object_ref(getattr(body, "Tip", None)) if getattr(body, "Tip", None) else None,
    }


def capture_body_membership(body: Any | None) -> dict[str, Any] | None:
    if body is None:
        return None
    return {
        "body": body,
        "group": list(getattr(body, "Group", []) or []),
        "tip": getattr(body, "Tip", None),
    }


def restore_body_membership_if_changed(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    if not snapshot:
        return {"checked": False, "changed": False, "restored": False}
    body = snapshot.get("body")
    if body is None:
        return {"checked": False, "changed": False, "restored": False}
    expected_group = list(snapshot.get("group", []) or [])
    expected_tip = snapshot.get("tip")
    try:
        current_group = list(getattr(body, "Group", []) or [])
        current_tip = getattr(body, "Tip", None)
    except Exception as exc:
        return {
            "checked": True,
            "changed": False,
            "restored": False,
            "error": str(exc),
        }
    changed = current_group != expected_group or current_tip is not expected_tip
    if not changed:
        return {"checked": True, "changed": False, "restored": False}
    errors: list[str] = []
    try:
        body.Group = expected_group
    except Exception as exc:
        errors.append(f"Group: {exc}")
    try:
        body.Tip = expected_tip
    except Exception as exc:
        errors.append(f"Tip: {exc}")
    return {
        "checked": True,
        "changed": True,
        "restored": not errors,
        "errors": errors,
    }


def _candidate_summary(service: Any, obj: Any, matched_by: str) -> dict[str, Any]:
    return {
        **object_ref(obj),
        "matched_by": matched_by,
        "component_root_status": component_root_status(service, obj),
        "container_memberships": container_memberships(service, obj),
    }


def _find_document_candidates(service: Any, query: str) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for obj in _document_objects(service):
        name = str(getattr(obj, "Name", ""))
        label = str(getattr(obj, "Label", ""))
        if name == query:
            candidates.append({"object": obj, "matched_by": "exact_name"})
        elif label == query:
            candidates.append({"object": obj, "matched_by": "exact_label"})
    return candidates


def _select_unique(
    service: Any,
    query: str,
    candidates: list[dict[str, Any]],
    *,
    prefer_component_roots: bool,
) -> dict[str, Any]:
    exact_name = [item for item in candidates if item["matched_by"] == "exact_name"]
    if exact_name:
        selected = exact_name[0]
        status = component_root_status(service, selected["object"])
        return _resolution_result(service, query, candidates, selected, status)

    if prefer_component_roots:
        valid = [
            item
            for item in candidates
            if component_root_status(service, item["object"]).get("ok")
        ]
        if len(valid) == 1:
            selected = valid[0]
            return _resolution_result(
                service,
                query,
                candidates,
                selected,
                component_root_status(service, selected["object"]),
            )
        if len(valid) > 1:
            return {
                "ok": False,
                "error": f"Component reference is ambiguous: {query}",
                "resolution": {
                    "query": query,
                    "candidates": [
                        _candidate_summary(service, item["object"], item["matched_by"])
                        for item in candidates
                    ],
                    "valid_component_root_count": len(valid),
                },
            }

    if len(candidates) == 1:
        selected = candidates[0]
        return _resolution_result(
            service,
            query,
            candidates,
            selected,
            component_root_status(service, selected["object"]),
        )
    return {
        "ok": False,
        "error": f"Object reference is ambiguous: {query}",
        "resolution": {
            "query": query,
            "candidates": [
                _candidate_summary(service, item["object"], item["matched_by"])
                for item in candidates
            ],
        },
    }


def _resolution_result(
    service: Any,
    query: str,
    candidates: list[dict[str, Any]],
    selected: dict[str, Any],
    status: dict[str, Any],
) -> dict[str, Any]:
    obj = selected["object"]
    resolution = {
        "query": query,
        "selected": _candidate_summary(service, obj, selected["matched_by"]),
        "candidate_count": len(candidates),
        "candidates": [
            _candidate_summary(service, item["object"], item["matched_by"])
            for item in candidates
        ],
    }
    if not status.get("ok"):
        return {
            "ok": False,
            "object": obj,
            "error": status.get("reason") or f"Object is not a valid component: {query}",
            "resolution": resolution,
            "suggested_component": status.get("owning_body"),
        }
    return {
        "ok": True,
        "object": obj,
        "resolution": resolution,
    }


def resolve_component_to_add(service: Any, component_name: str) -> dict[str, Any]:
    query = str(component_name or "").strip()
    if not query:
        return {"ok": False, "error": "Component name is required.", "resolution": {"query": query}}
    if _active_document(service) is None:
        return {"ok": False, "error": "No active document.", "resolution": {"query": query}}
    candidates = _find_document_candidates(service, query)
    if not candidates:
        return {
            "ok": False,
            "error": f"Component not found: {component_name}",
            "resolution": {"query": query, "candidates": []},
        }
    return _select_unique(service, query, candidates, prefer_component_roots=True)


def assembly_component_children(service: Any, assembly: Any) -> list[Any]:
    joint_names = {
        getattr(joint, "Name", None)
        for joint in service._assembly_joint_objects(assembly)
    }
    components = []
    for child in list(getattr(assembly, "Group", []) or []):
        type_id = getattr(child, "TypeId", "")
        if type_id in _ASSEMBLY_INTERNAL_TYPES:
            continue
        if getattr(child, "Name", None) in joint_names:
            continue
        components.append(child)
    return components


def resolve_existing_component(
    service: Any,
    assembly: Any,
    component_name: str,
) -> dict[str, Any]:
    query = str(component_name or "").strip()
    if not query:
        return {"ok": False, "error": "Component name is required.", "resolution": {"query": query}}
    candidates = []
    for child in assembly_component_children(service, assembly):
        name = str(getattr(child, "Name", ""))
        label = str(getattr(child, "Label", ""))
        if name == query:
            candidates.append({"object": child, "matched_by": "assembly_child_exact_name"})
        elif label == query:
            candidates.append({"object": child, "matched_by": "assembly_child_exact_label"})
    if not candidates:
        return {
            "ok": False,
            "error": (
                f"Component is not a child of assembly "
                f"{getattr(assembly, 'Label', getattr(assembly, 'Name', ''))}: {component_name}"
            ),
            "resolution": {
                "query": query,
                "assembly": object_ref(assembly),
                "assembly_components": [
                    object_ref(child) for child in assembly_component_children(service, assembly)
                ],
            },
        }
    result = _select_unique(service, query, candidates, prefer_component_roots=False)
    if result.get("ok"):
        result["resolution"]["assembly"] = object_ref(assembly)
    return result
