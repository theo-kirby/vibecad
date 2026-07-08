# SPDX-License-Identifier: LGPL-2.1-or-later

"""Shared helpers for AI-native CAD tools."""

from __future__ import annotations

from typing import Any


def call_backend(service: Any, tool_name: str, **kwargs: Any) -> dict[str, Any]:
    result = service.registry.call(tool_name, **kwargs)
    if isinstance(result, dict):
        return result
    return {"ok": True, "result": result}


def append_design_memory(service: Any, **fields: Any) -> dict[str, Any]:
    payload = {key: value for key, value in fields.items() if value not in (None, "", [], {})}
    if not payload:
        return {"ok": True, "design_memory": {}}
    return call_backend(service, "core.update_design_memory", **payload)


def find_body_name(service: Any, name_or_label: str | None) -> str | None:
    clean = str(name_or_label or "").strip()
    if not clean:
        return None
    body = service._get_partdesign_body(clean)
    if body is not None:
        return str(getattr(body, "Name", clean))
    return None


def backend_ok(result: dict[str, Any]) -> bool:
    if not isinstance(result, dict):
        return True
    if result.get("ok") is False:
        return False
    transaction = result.get("transaction")
    if isinstance(transaction, dict) and transaction.get("ok") is False:
        return False
    feature_effect = result.get("feature_effect")
    if isinstance(feature_effect, dict) and feature_effect.get("ok") is False:
        return False
    return True
