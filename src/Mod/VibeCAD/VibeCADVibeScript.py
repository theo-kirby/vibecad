# SPDX-License-Identifier: LGPL-2.1-or-later

"""Native FreeCAD parametric modeling engine driven by VibeScript source.

VibeScript source is the model authority. Unlike the build123d and OpenSCAD
engines there is no sidecar process: validated source executes directly in
the FreeCAD process through :mod:`vibescript_executor`, wrapped in a single
document transaction so a failed run leaves the document byte-identical to
its prior state. ``execute_prepared`` is therefore synchronous and terminal:
it returns a final success or failure payload with no pending/wait states.
"""

from __future__ import annotations

import ast
import builtins
import hashlib
import json
import re
import shutil
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import vibescript_api
import vibescript_executor
from VibeCADScriptedOwnership import (
    delete_owned_model_objects,
    owned_model_objects,
)
from VibeCADTools import tool_failure

VIBESCRIPT_VERSION = "1"
MODEL_SCHEMA = "vibecad-vibescript-model-v1"
ATTEMPT_SCHEMA = "vibecad-vibescript-attempt-v1"
MAX_SOURCE_BYTES = 512_000
MAX_OUTPUTS = 64
DEFAULT_TIMEOUT_SECONDS = vibescript_executor.DEFAULT_MAX_SECONDS
DEFAULT_MAX_OPERATIONS = vibescript_executor.DEFAULT_MAX_OPERATIONS

PROP_MODEL_ID = "VibeCADVibeScriptModelId"
PROP_SOURCE = "VibeCADVibeScriptSource"
PROP_PARAMETERS = "VibeCADVibeScriptParameters"
PROP_REVISION = "VibeCADVibeScriptRevision"
PROP_RUNTIME_VERSION = "VibeCADVibeScriptRuntimeVersion"
PROP_OUTPUTS = "VibeCADVibeScriptOutputs"
PROP_OUTPUT_KEY = "VibeCADVibeScriptOutputKey"

_NAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_. -]{0,95}$")
_MODEL_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")

ALLOWED_IMPORT_ROOTS = vibescript_executor.ALLOWED_IMPORT_ROOTS
_DISALLOWED_CALLS = frozenset(
    {
        "breakpoint",
        "compile",
        "delattr",
        "eval",
        "exec",
        "getattr",
        "globals",
        "help",
        "input",
        "locals",
        "open",
        "setattr",
        "vars",
        "__import__",
    }
)

#: Builtins reachable inside the sandbox namespace (runtime allowlist).
_SANDBOX_BUILTIN_NAMES = frozenset(vibescript_executor._BUILTIN_ALLOWLIST)

#: Names injected into the script namespace besides builtins.
_NAMESPACE_NAMES = frozenset({"doc", "params", "__name__"}) | frozenset(
    vibescript_api.__all__
)

#: Real Python builtins that would raise NameError inside the sandbox.
#: Reads of these are rejected statically so a script fails at validation
#: time with a line number instead of mid-execution after mutating geometry.
_EXCLUDED_BUILTIN_NAMES = (
    frozenset(vars(builtins)) - _SANDBOX_BUILTIN_NAMES - _NAMESPACE_NAMES
) | vibescript_executor._FRAME_INTERNAL_BUILTINS

_EXECUTION_FAILURE_CODES = {
    "contract_violation": "VIBESCRIPT_CONTRACT_VIOLATION",
    "execution_budget_exceeded": "VIBESCRIPT_BUDGET_EXCEEDED",
    "sketch_validation_failure": "VIBESCRIPT_SKETCH_UNSOLVED",
    "design_assertion_failure": "VIBESCRIPT_DESIGN_ASSERTION_FAILED",
    "syntax_error": "SOURCE_SYNTAX_ERROR",
    "vibescript_api_failure": "VIBESCRIPT_API_FAILED",
}


class VibeScriptFailure(RuntimeError):
    def __init__(self, payload: dict[str, Any]):
        self.payload = dict(payload)
        super().__init__(str(payload.get("error") or "VibeScript operation failed."))


def _failure(
    code: str,
    stage: str,
    error: str,
    *,
    requested: Any = None,
    observed: Any = None,
    retry_same_call: bool = False,
    required_changes: list[Any] | None = None,
    **details: Any,
) -> dict[str, Any]:
    stage_map = {
        "schema": "schema",
        "surface": "surface",
        "precondition": "precondition",
        "document_state": "precondition",
        "source_validation": "schema",
        "source_edit": "schema",
        "execution": "native_call",
        "contract": "postcondition",
        "commit": "postcondition",
    }
    return tool_failure(
        "vibescript",
        code,
        stage_map.get(stage, "native_call"),
        error,
        requested=requested,
        observed=observed,
        retry_same_call=retry_same_call,
        required_changes=required_changes,
        engine_stage=stage,
        **details,
    )


# ---------------------------------------------------------------------------
# Source policy
# ---------------------------------------------------------------------------


def _script_bound_names(tree: ast.AST) -> frozenset[str]:
    """Names bound anywhere in the script, in any scope.

    Deliberately scope-insensitive: a binding anywhere (assignment, loop or
    comprehension target, function/class/lambda argument, import alias,
    ``except ... as``, ``with ... as``, walrus, match capture) suppresses the
    excluded-builtin check for that name everywhere. This can only make the
    static check more permissive (the runtime NameError still applies to
    genuinely unbound reads); it can never produce a false positive on a
    script-defined shadow.
    """
    bound: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            bound.add(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(node.name)
        elif isinstance(node, ast.arg):
            bound.add(node.arg)
        elif isinstance(node, ast.alias):
            bound.add((node.asname or node.name).split(".", 1)[0])
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bound.add(node.name)
        elif isinstance(node, (ast.MatchAs, ast.MatchStar)) and node.name:
            bound.add(node.name)
        elif isinstance(node, ast.MatchMapping) and node.rest:
            bound.add(node.rest)
    return frozenset(bound)


def validate_source(source: str) -> None:
    """Reject VibeScript source that violates the in-process execution policy."""
    encoded = str(source or "").encode("utf-8")
    if not encoded:
        raise VibeScriptFailure(
            _failure("SOURCE_REQUIRED", "source_validation", "source is required.")
        )
    if len(encoded) > MAX_SOURCE_BYTES:
        raise VibeScriptFailure(
            _failure(
                "SOURCE_TOO_LARGE",
                "source_validation",
                f"source exceeds {MAX_SOURCE_BYTES} UTF-8 bytes.",
                observed={"source_bytes": len(encoded)},
            )
        )
    try:
        tree = ast.parse(
            source, filename=vibescript_executor.SCRIPT_FILENAME, mode="exec"
        )
    except SyntaxError as exc:
        raise VibeScriptFailure(
            _failure(
                "SOURCE_SYNTAX_ERROR",
                "source_validation",
                str(exc),
                observed={"line": exc.lineno, "column": exc.offset},
            )
        ) from exc
    violations: list[dict[str, Any]] = []
    bound_names = _script_bound_names(tree)
    # Name nodes already reported as disallowed calls; skipped by the
    # excluded-builtin check so one ``eval(...)`` yields one violation.
    # ``ast.walk`` is breadth-first and always yields a ``Call`` before its
    # ``func`` child, so entries land here before the child is inspected.
    flagged_call_funcs: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            denied = sorted(
                {
                    alias.name.split(".", 1)[0]
                    for alias in node.names
                    if alias.name.split(".", 1)[0] not in ALLOWED_IMPORT_ROOTS
                }
            )
            if denied:
                violations.append(
                    {
                        "line": node.lineno,
                        "reason": (
                            f"imports not allowed: {denied}; VibeScript source may "
                            f"only import {sorted(ALLOWED_IMPORT_ROOTS)}."
                        ),
                    }
                )
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                violations.append(
                    {
                        "line": node.lineno,
                        "reason": "relative imports are not allowed in VibeScript source.",
                    }
                )
                continue
            root = str(node.module or "").split(".")[0]
            if root not in ALLOWED_IMPORT_ROOTS:
                violations.append(
                    {
                        "line": node.lineno,
                        "reason": (
                            f"import not allowed: {root}; VibeScript source may "
                            f"only import {sorted(ALLOWED_IMPORT_ROOTS)}."
                        ),
                    }
                )
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in _DISALLOWED_CALLS:
                flagged_call_funcs.add(id(node.func))
                violations.append(
                    {
                        "line": node.lineno,
                        "reason": (
                            f"call not allowed: {node.func.id}; use the vibescript_api "
                            "helpers instead of dynamic or filesystem builtins."
                        ),
                    }
                )
        elif isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            violations.append(
                {
                    "line": node.lineno,
                    "reason": f"dunder access not allowed: {node.attr}",
                }
            )
        elif isinstance(node, ast.Name):
            if node.id == "__builtins__":
                violations.append(
                    {
                        "line": node.lineno,
                        "reason": (
                            "access to __builtins__ is not allowed in "
                            "VibeScript source."
                        ),
                    }
                )
            elif (
                isinstance(node.ctx, ast.Load)
                and node.id in _EXCLUDED_BUILTIN_NAMES
                and node.id not in bound_names
                and id(node) not in flagged_call_funcs
            ):
                violations.append(
                    {
                        "line": node.lineno,
                        "reason": (
                            f"builtin not available in the VibeScript sandbox: "
                            f"{node.id}; allowed builtins are listed by "
                            "vibescript.describe_api."
                        ),
                    }
                )
    if violations:
        raise VibeScriptFailure(
            _failure(
                "SOURCE_POLICY_VIOLATION",
                "source_validation",
                "VibeScript source violates the in-process execution policy.",
                observed={"violations": violations[:20]},
                required_changes=[{"remove_policy_violations": violations[:20]}],
            )
        )


# ---------------------------------------------------------------------------
# Revisions and JSON helpers
# ---------------------------------------------------------------------------


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def source_revision(
    source: str,
    parameters: dict[str, Any],
    expected_outputs: list[str],
) -> str:
    payload = {
        "schema": MODEL_SCHEMA,
        "runtime_version": VIBESCRIPT_VERSION,
        "source": source,
        "parameters": parameters,
        "expected_outputs": expected_outputs,
    }
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _json_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise VibeScriptFailure(
            _failure(
                f"INVALID_{label.upper()}", "schema", f"{label} must be an object."
            )
        )
    try:
        decoded = json.loads(_canonical_json(value))
    except (TypeError, ValueError) as exc:
        raise VibeScriptFailure(
            _failure(
                f"INVALID_{label.upper()}",
                "schema",
                f"{label} is not JSON-safe: {exc}",
            )
        ) from exc
    return decoded


def _clean_parameters(value: Any) -> dict[str, Any]:
    parameters = _json_object(value, "parameters")
    try:
        vibescript_api.Params(**parameters)
    except vibescript_api.VibeScriptError as exc:
        raise VibeScriptFailure(
            _failure(
                "INVALID_PARAMETERS",
                "schema",
                f"parameters must map identifier names to finite numbers: {exc}",
                observed={"parameters": parameters},
            )
        ) from exc
    return parameters


def _clean_outputs(value: Any) -> list[str]:
    if not isinstance(value, list) or not value:
        raise VibeScriptFailure(
            _failure(
                "OUTPUTS_REQUIRED",
                "schema",
                "expected_outputs must contain at least one output key.",
            )
        )
    if len(value) > MAX_OUTPUTS:
        raise VibeScriptFailure(
            _failure(
                "TOO_MANY_OUTPUTS",
                "schema",
                f"expected_outputs may contain at most {MAX_OUTPUTS} keys.",
            )
        )
    cleaned = [str(item or "").strip() for item in value]
    if any(not _NAME_PATTERN.fullmatch(item) for item in cleaned):
        raise VibeScriptFailure(
            _failure(
                "INVALID_OUTPUT_NAME",
                "schema",
                "Every output key must start with a letter and contain only "
                "letters, numbers, spaces, dots, underscores, or hyphens.",
                observed={"expected_outputs": cleaned},
            )
        )
    if len(set(cleaned)) != len(cleaned):
        raise VibeScriptFailure(
            _failure(
                "DUPLICATE_OUTPUT_NAME",
                "schema",
                "expected_outputs contains duplicate keys.",
                observed={"expected_outputs": cleaned},
            )
        )
    return cleaned


def _apply_source_edits(source: str, edits: Any) -> str:
    if not isinstance(edits, list) or not edits:
        raise VibeScriptFailure(
            _failure(
                "SOURCE_EDITS_REQUIRED",
                "schema",
                "edits must contain at least one replacement.",
            )
        )
    candidate = source
    for index, edit in enumerate(edits):
        if not isinstance(edit, dict):
            raise VibeScriptFailure(
                _failure(
                    "INVALID_SOURCE_EDIT",
                    "schema",
                    f"Source edit {index} must be an object.",
                )
            )
        old_text = str(edit.get("old_text") or "")
        new_text = str(edit.get("new_text") or "")
        if not old_text:
            raise VibeScriptFailure(
                _failure(
                    "INVALID_SOURCE_EDIT",
                    "schema",
                    f"Source edit {index} has empty old_text.",
                )
            )
        occurrences = candidate.count(old_text)
        if occurrences != 1:
            raise VibeScriptFailure(
                _failure(
                    "SOURCE_EDIT_NOT_UNIQUE",
                    "source_edit",
                    f"Source edit {index} old_text matched {occurrences} times; "
                    "expected exactly once.",
                    observed={
                        "edit_index": index,
                        "match_count": occurrences,
                        "old_text": old_text,
                    },
                    required_changes=[{"inspect_model_and_correct_old_text": index}],
                )
            )
        candidate = candidate.replace(old_text, new_text, 1)
    return candidate


def _merge_patch(target: Any, patch: Any) -> Any:
    if not isinstance(patch, dict):
        return json.loads(_canonical_json(patch))
    result = dict(target) if isinstance(target, dict) else {}
    for key, value in patch.items():
        if value is None:
            result.pop(str(key), None)
        else:
            result[str(key)] = _merge_patch(result.get(str(key)), value)
    return result


def _apply_parameter_merge_patch(
    parameters: dict[str, Any], raw_patch: Any, label: str
) -> dict[str, Any]:
    """Apply an RFC 7396 merge patch to flat params with schema-stage failures."""
    patch = _json_object(raw_patch, label)
    if not patch:
        raise VibeScriptFailure(
            _failure("EMPTY_PARAMETER_PATCH", "schema", f"{label} cannot be empty.")
        )
    merged = _merge_patch(parameters, patch)
    if not isinstance(merged, dict):
        raise VibeScriptFailure(
            _failure(
                "INVALID_PARAMETER_RESULT",
                "schema",
                "The parameter merge patch must leave params as an object.",
            )
        )
    return _clean_parameters(merged)


# ---------------------------------------------------------------------------
# Document model objects
# ---------------------------------------------------------------------------


def _add_string_property(obj: Any, name: str, group: str = "VibeScript") -> None:
    if name not in list(getattr(obj, "PropertiesList", []) or []):
        obj.addProperty("App::PropertyString", name, group)


def _safe_internal_name(value: str, prefix: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9_]", "_", str(value or ""))
    clean = re.sub(r"_+", "_", clean).strip("_")
    if not clean or not clean[0].isalpha():
        clean = f"{prefix}_{clean}" if clean else prefix
    return clean[:80]


def _model_objects(doc: Any) -> list[Any]:
    result: list[Any] = []
    for obj in list(getattr(doc, "Objects", []) or []):
        if str(getattr(obj, "TypeId", "") or "") != "App::Part":
            continue
        model_id = str(getattr(obj, PROP_MODEL_ID, "") or "")
        properties = set(getattr(obj, "PropertiesList", []) or [])
        if (
            _MODEL_ID_PATTERN.fullmatch(model_id)
            and PROP_SOURCE in properties
            and PROP_REVISION in properties
        ):
            result.append(obj)
    return result


def _find_model(doc: Any, model_id: str) -> Any | None:
    clean = str(model_id or "").strip().lower()
    if not clean:
        return None
    if not _MODEL_ID_PATTERN.fullmatch(clean):
        raise VibeScriptFailure(
            _failure(
                "INVALID_MODEL_ID",
                "precondition",
                "model_id must be a 32-character lowercase hexadecimal id.",
                requested={"model_id": model_id},
            )
        )
    matches = [
        obj for obj in _model_objects(doc) if getattr(obj, PROP_MODEL_ID) == clean
    ]
    if len(matches) > 1:
        raise VibeScriptFailure(
            _failure(
                "DUPLICATE_MODEL_ID",
                "document_state",
                f"Multiple FreeCAD objects claim VibeScript model id {clean}.",
                observed={"objects": [obj.Name for obj in matches]},
            )
        )
    return matches[0] if matches else None


def _output_objects(container: Any) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for child in list(getattr(container, "Group", []) or []):
        key = str(getattr(child, PROP_OUTPUT_KEY, "") or "")
        if key:
            result[key] = child
    return result


def _model_summary(container: Any, *, include_source: bool) -> dict[str, Any]:
    outputs_raw = str(getattr(container, PROP_OUTPUTS, "{}") or "{}")
    parameters_raw = str(getattr(container, PROP_PARAMETERS, "{}") or "{}")
    try:
        outputs = json.loads(outputs_raw)
    except ValueError:
        outputs = {"invalid_json": outputs_raw}
    try:
        parameters = json.loads(parameters_raw)
    except ValueError:
        parameters = {"invalid_json": parameters_raw}
    summary = {
        "model_id": str(getattr(container, PROP_MODEL_ID, "") or ""),
        "object_name": str(getattr(container, "Name", "") or ""),
        "label": str(getattr(container, "Label", "") or ""),
        "revision": str(getattr(container, PROP_REVISION, "") or ""),
        "runtime_version": str(getattr(container, PROP_RUNTIME_VERSION, "") or ""),
        "parameters": parameters,
        "outputs": outputs,
    }
    if include_source:
        summary["source"] = str(getattr(container, PROP_SOURCE, "") or "")
    return summary


def _model_contract(container: Any) -> dict[str, Any]:
    try:
        parameters = json.loads(str(getattr(container, PROP_PARAMETERS) or "{}"))
        output_map = json.loads(str(getattr(container, PROP_OUTPUTS) or "{}"))
    except (TypeError, ValueError) as exc:
        raise VibeScriptFailure(
            _failure(
                "MODEL_METADATA_INVALID",
                "document_state",
                f"Persisted VibeScript model metadata is invalid: {exc}",
                observed={"model_id": str(getattr(container, PROP_MODEL_ID, "") or "")},
            )
        ) from exc
    if not isinstance(parameters, dict) or not isinstance(output_map, dict):
        raise VibeScriptFailure(
            _failure(
                "MODEL_METADATA_INVALID",
                "document_state",
                "Persisted parameters and outputs must both be JSON objects.",
            )
        )
    source = str(getattr(container, PROP_SOURCE, "") or "")
    validate_source(source)
    return {
        "model_name": str(getattr(container, "Label", "") or ""),
        "source": source,
        "parameters": _json_object(parameters, "parameters"),
        "expected_outputs": _clean_outputs(list(output_map)),
    }


# ---------------------------------------------------------------------------
# Persisted artifacts
# ---------------------------------------------------------------------------


def _project_root(service: Any) -> Path:
    value = str(service.project_context().get("root") or "").strip()
    if not value:
        raise VibeScriptFailure(
            _failure(
                "PROJECT_ROOT_UNAVAILABLE",
                "precondition",
                "Project root is unavailable.",
            )
        )
    return Path(value)


def _model_directory(project_root: str | Path, model_id: str) -> Path:
    return Path(project_root) / "vibescript" / model_id


def _read_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise VibeScriptFailure(
            _failure(
                "MODEL_ARTIFACT_INVALID",
                "document_state",
                f"Persisted VibeScript {label} is invalid: {exc}",
                observed={"path": str(path)},
            )
        ) from exc
    if not isinstance(payload, dict):
        raise VibeScriptFailure(
            _failure(
                "MODEL_ARTIFACT_INVALID",
                "document_state",
                f"Persisted VibeScript {label} must be a JSON object.",
                observed={"path": str(path)},
            )
        )
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )
    temporary.replace(path)


def _write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp")
    temporary.write_text(value, encoding="utf-8")
    temporary.replace(path)


def _artifact_contract(
    project_root: str | Path, model_id: str
) -> dict[str, Any] | None:
    directory = _model_directory(project_root, model_id)
    manifest_path = directory / "manifest.json"
    source_path = directory / "model.py"
    parameters_path = directory / "parameters.json"
    if not directory.is_dir():
        return None
    if (
        not manifest_path.is_file()
        or not source_path.is_file()
        or not parameters_path.is_file()
    ):
        raise VibeScriptFailure(
            _failure(
                "MODEL_ARTIFACT_INCOMPLETE",
                "document_state",
                "The persisted VibeScript model is missing its manifest, source, "
                "or parameters.",
                observed={"artifact_directory": str(directory)},
            )
        )
    manifest = _read_json_object(manifest_path, "manifest")
    if (
        manifest.get("schema") != MODEL_SCHEMA
        or str(manifest.get("model_id") or "") != model_id
    ):
        raise VibeScriptFailure(
            _failure(
                "MODEL_ARTIFACT_INVALID",
                "document_state",
                "The persisted VibeScript manifest identity is invalid.",
                observed={"path": str(manifest_path), "manifest": manifest},
            )
        )
    try:
        source = source_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise VibeScriptFailure(
            _failure(
                "MODEL_ARTIFACT_INVALID",
                "document_state",
                f"Persisted VibeScript source could not be read: {exc}",
                observed={"path": str(source_path)},
            )
        ) from exc
    parameters = _read_json_object(parameters_path, "parameters")
    output_map = manifest.get("outputs") or {}
    if not isinstance(output_map, dict):
        raise VibeScriptFailure(
            _failure(
                "MODEL_ARTIFACT_INVALID",
                "document_state",
                "Persisted VibeScript outputs must be an object.",
                observed={"path": str(manifest_path)},
            )
        )
    output_facts = manifest.get("output_facts") or {}
    if not isinstance(output_facts, dict):
        raise VibeScriptFailure(
            _failure(
                "MODEL_ARTIFACT_INVALID",
                "document_state",
                "Persisted VibeScript output facts must be an object.",
                observed={"path": str(manifest_path)},
            )
        )
    expected_outputs = manifest.get("expected_outputs")
    if expected_outputs is None:
        expected_outputs = list(output_map)
    expected_outputs = _clean_outputs(expected_outputs)
    working_revision = str(
        manifest.get("working_revision") or manifest.get("revision") or ""
    )
    calculated_revision = source_revision(source, parameters, expected_outputs)
    if working_revision != calculated_revision:
        raise VibeScriptFailure(
            _failure(
                "MODEL_ARTIFACT_REVISION_MISMATCH",
                "document_state",
                "Persisted VibeScript source and metadata do not match the "
                "working revision.",
                observed={
                    "manifest_revision": working_revision,
                    "calculated_revision": calculated_revision,
                    "artifact_directory": str(directory),
                },
            )
        )
    state = str(manifest.get("state") or "accepted")
    accepted_revision = str(
        manifest.get("accepted_revision")
        or (working_revision if state == "accepted" else "")
    )
    return {
        "model_id": model_id,
        "model_name": str(manifest.get("label") or ""),
        "source": source,
        "parameters": parameters,
        "expected_outputs": expected_outputs,
        "outputs": output_map,
        "output_facts": output_facts,
        "working_revision": working_revision,
        "accepted_revision": accepted_revision,
        "state": state,
        "latest_attempt": manifest.get("latest_attempt") or {},
        "directory": directory,
        "manifest": manifest,
    }


def _artifact_summary(
    contract: dict[str, Any], *, include_source: bool
) -> dict[str, Any]:
    summary = {
        "model_id": contract["model_id"],
        "object_name": "",
        "label": contract["model_name"],
        "revision": contract["working_revision"],
        "working_revision": contract["working_revision"],
        "accepted_revision": contract["accepted_revision"],
        "state": contract["state"],
        "parameters": contract["parameters"],
        "outputs": contract["outputs"],
    }
    if include_source:
        summary["source"] = contract["source"]
    return summary


def model_summaries(
    doc: Any,
    project_root: str | Path | None = None,
) -> list[dict[str, Any]]:
    summaries = {
        item["model_id"]: item
        for item in (
            _model_summary(obj, include_source=False) for obj in _model_objects(doc)
        )
    }
    root = Path(project_root) if project_root else None
    artifact_root = root / "vibescript" if root else None
    if artifact_root is not None and artifact_root.is_dir():
        for directory in sorted(artifact_root.iterdir()):
            if not directory.is_dir() or not _MODEL_ID_PATTERN.fullmatch(
                directory.name
            ):
                continue
            contract = _artifact_contract(root, directory.name)
            if contract is None:
                continue
            summary = _artifact_summary(contract, include_source=False)
            native = summaries.get(directory.name)
            if native is not None:
                summary["object_name"] = native.get("object_name", "")
                summary["outputs"] = native.get("outputs", summary["outputs"])
            summaries[directory.name] = summary
    return list(summaries.values())


def _persist_working_candidate(prepared: dict[str, Any]) -> dict[str, str]:
    directory = _model_directory(prepared["project_root"], prepared["model_id"])
    attempts = directory / "attempts"
    attempt = attempts / prepared["revision"]
    directory.mkdir(parents=True, exist_ok=True)
    attempt.mkdir(parents=True, exist_ok=True)
    _write_text(directory / "model.py", prepared["source"])
    _write_json(directory / "parameters.json", prepared["parameters"])
    _write_text(attempt / "model.py", prepared["source"])
    _write_json(attempt / "parameters.json", prepared["parameters"])
    attempt_manifest = {
        "schema": ATTEMPT_SCHEMA,
        "model_id": prepared["model_id"],
        "label": prepared["model_name"],
        "operation": prepared["operation"],
        "revision": prepared["revision"],
        "base_revision": prepared["base_revision"],
        "accepted_revision": prepared["accepted_revision_before"],
        "runtime_version": VIBESCRIPT_VERSION,
        "expected_outputs": prepared["expected_outputs"],
        "status": "running",
    }
    _write_json(attempt / "manifest.json", attempt_manifest)
    manifest = {
        "schema": MODEL_SCHEMA,
        "model_id": prepared["model_id"],
        "label": prepared["model_name"],
        "state": "running",
        "revision": prepared["revision"],
        "working_revision": prepared["revision"],
        "accepted_revision": prepared["accepted_revision_before"],
        "runtime_version": VIBESCRIPT_VERSION,
        "expected_outputs": prepared["expected_outputs"],
        "outputs": prepared["accepted_outputs"],
        "output_facts": prepared["accepted_output_facts"],
        "latest_attempt": {
            "revision": prepared["revision"],
            "status": "running",
            "path": str(Path("attempts") / prepared["revision"]),
        },
    }
    _write_json(directory / "manifest.json", manifest)
    return {
        "artifact_directory": str(directory),
        "attempt_directory": str(attempt),
    }


def _mirror_model(
    prepared: dict[str, Any],
    output_map: dict[str, Any],
    output_facts: dict[str, Any],
) -> dict[str, str]:
    directory = _model_directory(prepared["project_root"], prepared["model_id"])
    directory.mkdir(parents=True, exist_ok=True)
    revision = str(prepared["revision"])
    source = str(prepared["source"])
    parameters = prepared["parameters"]
    revisions_directory = directory / "revisions"
    revision_source_path = revisions_directory / f"{revision}.py"
    revision_parameters_path = revisions_directory / f"{revision}.parameters.json"
    revision_manifest_path = revisions_directory / f"{revision}.manifest.json"
    if (
        revision_source_path.exists()
        and revision_source_path.read_text(encoding="utf-8") != source
    ):
        raise VibeScriptFailure(
            _failure(
                "MODEL_ARTIFACT_INVALID",
                "commit",
                f"VibeScript revision {revision} already exists with different source.",
            )
        )
    manifest = {
        "schema": MODEL_SCHEMA,
        "model_id": prepared["model_id"],
        "label": prepared["model_name"],
        "state": "accepted",
        "revision": revision,
        "working_revision": revision,
        "accepted_revision": revision,
        "runtime_version": VIBESCRIPT_VERSION,
        "expected_outputs": prepared["expected_outputs"],
        "outputs": output_map,
        "output_facts": output_facts,
        "latest_attempt": {
            "revision": revision,
            "status": "accepted",
            "path": str(Path("attempts") / revision),
        },
    }
    if not revision_source_path.exists():
        _write_text(revision_source_path, source)
        _write_json(revision_parameters_path, parameters)
        _write_json(revision_manifest_path, manifest)
    _write_text(directory / "model.py", source)
    _write_json(directory / "parameters.json", parameters)
    _write_json(directory / "manifest.json", manifest)
    attempt_manifest_path = directory / "attempts" / revision / "manifest.json"
    if attempt_manifest_path.is_file():
        attempt_manifest = _read_json_object(attempt_manifest_path, "attempt manifest")
        attempt_manifest["status"] = "accepted"
        _write_json(attempt_manifest_path, attempt_manifest)
    return {
        "source": str(directory / "model.py"),
        "parameters": str(directory / "parameters.json"),
        "manifest": str(directory / "manifest.json"),
        "revision_source": str(revision_source_path),
    }


def record_failed_attempt(
    prepared: dict[str, Any],
    failure: dict[str, Any],
) -> dict[str, Any]:
    paths = _persist_working_candidate(prepared)
    directory = Path(paths["artifact_directory"])
    attempt = Path(paths["attempt_directory"])
    stored_failure = dict(failure)
    stored_failure.pop("requested", None)
    _write_json(attempt / "failure.json", stored_failure)
    attempt_manifest = _read_json_object(attempt / "manifest.json", "attempt manifest")
    attempt_manifest.update(
        {
            "status": "failed",
            "failure_code": str(failure.get("failure_code") or "VIBESCRIPT_FAILED"),
            "failure_stage": str(failure.get("failure_stage") or "native_call"),
        }
    )
    _write_json(attempt / "manifest.json", attempt_manifest)
    manifest = _read_json_object(directory / "manifest.json", "manifest")
    state = (
        "candidate_failed"
        if str(prepared.get("accepted_revision_before") or "")
        else "draft_failed"
    )
    manifest.update(
        {
            "state": state,
            "revision": prepared["revision"],
            "working_revision": prepared["revision"],
            "accepted_revision": prepared["accepted_revision_before"],
            "latest_attempt": {
                "revision": prepared["revision"],
                "status": "failed",
                "failure_code": attempt_manifest["failure_code"],
                "failure_stage": attempt_manifest["failure_stage"],
                "path": str(Path("attempts") / prepared["revision"]),
            },
        }
    )
    _write_json(directory / "manifest.json", manifest)
    return {
        "model_id": prepared["model_id"],
        "state": state,
        "working_revision": prepared["revision"],
        "accepted_revision": prepared["accepted_revision_before"],
        "artifact_directory": str(directory),
        "attempt_directory": str(attempt),
    }


def _inspect_latest_attempt(contract: dict[str, Any]) -> dict[str, Any]:
    latest = contract.get("latest_attempt") or {}
    relative = str(latest.get("path") or "").strip()
    if not relative:
        return {}
    directory = (contract["directory"] / relative).resolve()
    if (
        contract["directory"].resolve() not in directory.parents
        or not directory.is_dir()
    ):
        return {
            "status": "invalid_artifact",
            "error": "Latest attempt path is missing or outside the model artifact directory.",
        }
    response = dict(latest)
    response["directory"] = str(directory)
    failure_path = directory / "failure.json"
    if failure_path.is_file():
        response["failure"] = _read_json_object(failure_path, "attempt failure")
    return response


# ---------------------------------------------------------------------------
# Editor integration
# ---------------------------------------------------------------------------


def stage_editor_source(
    service: Any,
    model_id: str,
    expected_revision: str,
    source: str,
) -> dict[str, Any]:
    """Persist a human-edited working source revision without accepting geometry."""
    project_root = _project_root(service)
    directory = _model_directory(project_root, model_id)
    manifest_path = directory / "manifest.json"
    if not manifest_path.is_file():
        raise VibeScriptFailure(
            _failure(
                "MODEL_NOT_FOUND",
                "precondition",
                f"No VibeScript model has id {model_id!r}.",
            )
        )
    manifest = _read_json_object(manifest_path, "model manifest")
    current_revision = str(
        manifest.get("working_revision") or manifest.get("revision") or ""
    )
    if current_revision != str(expected_revision or ""):
        raise VibeScriptFailure(
            _failure(
                "STALE_MODEL_REVISION",
                "precondition",
                "The VibeScript source changed after the editor loaded it.",
                requested={"expected_revision": expected_revision},
                observed={"current_revision": current_revision},
            )
        )
    validate_source(source)
    parameters = _read_json_object(directory / "parameters.json", "parameters")
    expected_outputs = _clean_outputs(
        manifest.get("expected_outputs") or list((manifest.get("outputs") or {}).keys())
    )
    revision = source_revision(source, parameters, expected_outputs)
    if revision == current_revision:
        return {"ok": True, "changed": False, "working_revision": revision}
    _write_text(directory / "model.py", source)
    manifest.update(
        {
            "state": "working",
            "revision": revision,
            "working_revision": revision,
            "latest_attempt": {
                "revision": revision,
                "status": "working",
                "path": str(Path("attempts") / revision),
            },
        }
    )
    _write_json(manifest_path, manifest)
    attempt = directory / "attempts" / revision
    attempt.mkdir(parents=True, exist_ok=True)
    _write_text(attempt / "model.py", source)
    _write_json(attempt / "parameters.json", parameters)
    _write_json(
        attempt / "manifest.json",
        {
            "schema": ATTEMPT_SCHEMA,
            "model_id": model_id,
            "revision": revision,
            "status": "working",
            "created_at": time.time(),
        },
    )
    return {"ok": True, "changed": True, "working_revision": revision}


def revert_working_to_accepted(service: Any, model_id: str) -> dict[str, Any]:
    project_root = _project_root(service)
    contract = _artifact_contract(project_root, model_id)
    if contract is None:
        raise VibeScriptFailure(
            _failure(
                "MODEL_NOT_FOUND",
                "precondition",
                f"No VibeScript model has id {model_id!r}.",
            )
        )
    accepted = contract["accepted_revision"]
    if not accepted:
        raise VibeScriptFailure(
            _failure(
                "NO_ACCEPTED_REVISION",
                "precondition",
                "This VibeScript model has no accepted revision to restore.",
            )
        )
    directory = contract["directory"]
    source_path = directory / "revisions" / f"{accepted}.py"
    parameters_path = directory / "revisions" / f"{accepted}.parameters.json"
    if not source_path.is_file() or not parameters_path.is_file():
        raise VibeScriptFailure(
            _failure(
                "ACCEPTED_REVISION_MISSING",
                "document_state",
                "The accepted VibeScript revision files are missing.",
            )
        )
    source = source_path.read_text(encoding="utf-8")
    parameters = _read_json_object(parameters_path, "accepted parameters")
    _write_text(directory / "model.py", source)
    _write_json(directory / "parameters.json", parameters)
    manifest = dict(contract["manifest"])
    manifest.update(
        {
            "state": "accepted",
            "revision": accepted,
            "working_revision": accepted,
            "latest_attempt": {
                "revision": accepted,
                "status": "accepted",
                "path": str(Path("attempts") / accepted),
            },
        }
    )
    _write_json(directory / "manifest.json", manifest)
    return {
        "ok": True,
        "model_id": model_id,
        "working_revision": accepted,
        "source": source,
    }


def restore_output_display_modes(doc: Any) -> list[str]:
    """VibeScript outputs are native features; FreeCAD default display applies."""
    return []


# ---------------------------------------------------------------------------
# Inspect / delete
# ---------------------------------------------------------------------------


def inspect_model(service: Any, model_id: str) -> dict[str, Any]:
    doc = service._active_document()
    if doc is None:
        return _failure("NO_DOCUMENT", "precondition", "No active FreeCAD document.")
    try:
        project_root = _project_root(service)
        contract = _artifact_contract(project_root, model_id)
        container = _find_model(doc, model_id)
    except VibeScriptFailure as exc:
        return exc.payload
    if container is None and contract is None:
        return _failure(
            "MODEL_NOT_FOUND",
            "precondition",
            f"No VibeScript model has id {model_id!r}.",
            observed={"available_models": model_summaries(doc, project_root)},
        )
    if contract is None:
        model = _model_summary(container, include_source=True)
        model.update(
            {
                "working_revision": model["revision"],
                "accepted_revision": model["revision"],
                "state": "accepted",
            }
        )
    else:
        model = _artifact_summary(contract, include_source=True)
    if container is not None:
        model["object_name"] = container.Name
        output_geometry: list[dict[str, Any]] = []
        for key, obj in _output_objects(container).items():
            item = {
                "key": key,
                "object": str(getattr(obj, "Name", "") or ""),
                "shape": vibescript_executor.shape_facts(getattr(obj, "Shape", None)),
            }
            if contract is not None:
                persisted_facts = contract["output_facts"].get(key)
                if isinstance(persisted_facts, dict):
                    item.update(persisted_facts)
            output_geometry.append(item)
        model["accepted_outputs"] = output_geometry
    model["artifact_directory"] = str(_model_directory(project_root, model_id))
    if contract is not None:
        latest_attempt = _inspect_latest_attempt(contract)
        if latest_attempt:
            model["latest_attempt"] = latest_attempt
        accepted_revision = contract["accepted_revision"]
        if accepted_revision and accepted_revision != contract["working_revision"]:
            accepted_path = (
                contract["directory"] / "revisions" / f"{accepted_revision}.py"
            )
            if accepted_path.is_file():
                model["accepted_source"] = accepted_path.read_text(encoding="utf-8")
    return {
        "ok": True,
        "model": model,
        "cad_revision": service.structural_document_revision(),
    }


def delete_model(
    service: Any,
    model_id: str,
    expected_revision: str,
    reason: str,
) -> dict[str, Any]:
    doc = service._active_document()
    if doc is None:
        return _failure("NO_DOCUMENT", "precondition", "No active FreeCAD document.")
    try:
        project_root = _project_root(service)
        contract = _artifact_contract(project_root, model_id)
        container = _find_model(doc, model_id)
    except VibeScriptFailure as exc:
        return exc.payload
    if container is None and contract is None:
        return _failure(
            "MODEL_NOT_FOUND",
            "precondition",
            f"No VibeScript model has id {model_id!r}.",
            observed={"available_models": model_summaries(doc, project_root)},
        )
    current_revision = (
        contract["working_revision"]
        if contract is not None
        else str(getattr(container, PROP_REVISION, "") or "")
    )
    if str(expected_revision or "").strip() != current_revision:
        return _failure(
            "STALE_MODEL_REVISION",
            "precondition",
            "The VibeScript model changed after it was inspected.",
            requested={"expected_revision": expected_revision},
            observed={"current_revision": current_revision},
            required_changes=[{"inspect_model": model_id}],
        )
    clean_reason = str(reason or "").strip()
    if not clean_reason:
        return _failure("DELETE_REASON_REQUIRED", "schema", "reason cannot be empty.")
    artifact_directory = _model_directory(project_root, model_id)
    if not artifact_directory.is_dir():
        return _failure(
            "MODEL_ARTIFACT_MISSING",
            "precondition",
            "The persisted VibeScript artifact directory is missing; deletion "
            "was not started.",
            observed={"artifact_directory": str(artifact_directory)},
        )
    deleted_objects: list[str] = []
    if container is not None:
        doc.openTransaction("Delete VibeScript model")
        try:
            deleted_objects = delete_owned_model_objects(doc, PROP_MODEL_ID, model_id)
            doc.recompute()
            remaining = sorted(
                {name for name in deleted_objects if doc.getObject(name) is not None}
                | {
                    str(obj.Name)
                    for obj in owned_model_objects(doc, PROP_MODEL_ID, model_id)
                }
            )
            if remaining:
                raise RuntimeError(
                    "FreeCAD retained model-owned objects after deletion: "
                    + ", ".join(remaining)
                )
            doc.commitTransaction()
        except Exception as exc:
            doc.abortTransaction()
            return _failure(
                "DELETE_FAILED",
                "commit",
                f"VibeScript model deletion failed: {exc}",
            )
    shutil.rmtree(artifact_directory)
    return {
        "ok": True,
        "deleted_model_id": model_id,
        "deleted_revision": current_revision,
        "reason": clean_reason,
        "deleted_objects": deleted_objects,
        "artifact_directory": str(artifact_directory),
        "cad_revision": service.structural_document_revision(),
    }


# ---------------------------------------------------------------------------
# Prepare / execute (synchronous lifecycle)
# ---------------------------------------------------------------------------


def prepare_execution(
    service: Any,
    tool_name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    doc = service._active_document()
    if doc is None:
        raise VibeScriptFailure(
            _failure("NO_DOCUMENT", "precondition", "No active FreeCAD document.")
        )
    project_root = _project_root(service)
    operation = str(tool_name or "").strip()
    creating = operation == "vibescript.create_model"
    if creating:
        model_name = str(arguments.get("model_name") or "").strip()
        if not _NAME_PATTERN.fullmatch(model_name):
            raise VibeScriptFailure(
                _failure(
                    "INVALID_MODEL_NAME",
                    "schema",
                    "model_name must start with a letter and contain at most 96 "
                    "letters, numbers, spaces, dots, underscores, or hyphens.",
                )
            )
        source = str(arguments.get("source") or "")
        parameters = _clean_parameters(arguments.get("parameters"))
        expected_outputs = _clean_outputs(arguments.get("expected_outputs"))
        validate_source(source)
        duplicates = [
            item
            for item in model_summaries(doc, project_root)
            if str(item.get("label") or "") == model_name
        ]
        if duplicates:
            raise VibeScriptFailure(
                _failure(
                    "MODEL_NAME_EXISTS",
                    "precondition",
                    "A VibeScript model with this label already exists; inspect "
                    "and update it by model id instead of creating a duplicate.",
                    observed={"matches": duplicates},
                )
            )
        model_id = uuid.uuid4().hex
        base_revision = ""
        accepted_revision_before = ""
        accepted_outputs: dict[str, Any] = {}
        accepted_output_facts: dict[str, Any] = {}
    else:
        model_id = str(arguments.get("model_id") or "").strip().lower()
        target = _find_model(doc, model_id)
        artifact = _artifact_contract(project_root, model_id)
        if target is None and artifact is None:
            raise VibeScriptFailure(
                _failure(
                    "MODEL_NOT_FOUND",
                    "precondition",
                    f"No VibeScript model has id {model_id!r}.",
                    observed={"available_models": model_summaries(doc, project_root)},
                )
            )
        if artifact is not None:
            current = {
                "model_name": artifact["model_name"],
                "source": artifact["source"],
                "parameters": artifact["parameters"],
                "expected_outputs": artifact["expected_outputs"],
            }
            base_revision = artifact["working_revision"]
            accepted_revision_before = artifact["accepted_revision"]
            accepted_outputs = artifact["outputs"]
            accepted_output_facts = artifact["output_facts"]
            if accepted_revision_before and target is None:
                raise VibeScriptFailure(
                    _failure(
                        "ACCEPTED_MODEL_OBJECT_MISSING",
                        "document_state",
                        "The project records accepted VibeScript geometry, but "
                        "its FreeCAD model object is missing.",
                        observed={
                            "model_id": model_id,
                            "accepted_revision": accepted_revision_before,
                            "artifact_directory": str(artifact["directory"]),
                        },
                    )
                )
            if target is not None:
                native_revision = str(getattr(target, PROP_REVISION, "") or "")
                if native_revision != accepted_revision_before:
                    raise VibeScriptFailure(
                        _failure(
                            "ACCEPTED_REVISION_DIVERGED",
                            "document_state",
                            "The accepted FreeCAD object and project artifact "
                            "have different revisions.",
                            observed={
                                "freecad_revision": native_revision,
                                "artifact_accepted_revision": accepted_revision_before,
                            },
                        )
                    )
        else:
            current = _model_contract(target)
            base_revision = str(getattr(target, PROP_REVISION, "") or "")
            accepted_revision_before = base_revision
            accepted_outputs = json.loads(str(getattr(target, PROP_OUTPUTS) or "{}"))
            accepted_output_facts = {}
        expected_revision = str(arguments.get("expected_revision") or "").strip()
        if expected_revision != base_revision:
            raise VibeScriptFailure(
                _failure(
                    "STALE_MODEL_REVISION",
                    "precondition",
                    "The VibeScript model changed after it was inspected.",
                    requested={"expected_revision": expected_revision},
                    observed={"current_revision": base_revision},
                    required_changes=[{"inspect_model": model_id}],
                )
            )
        model_name = current["model_name"]
        source = current["source"]
        parameters = current["parameters"]
        expected_outputs = current["expected_outputs"]
        if operation == "vibescript.edit_source":
            source = _apply_source_edits(source, arguments.get("edits"))
            if arguments.get("parameter_patch") is not None:
                parameters = _apply_parameter_merge_patch(
                    parameters, arguments.get("parameter_patch"), "parameter_patch"
                )
        elif operation == "vibescript.set_parameters":
            parameters = _apply_parameter_merge_patch(
                parameters, arguments.get("patch"), "patch"
            )
        elif operation == "vibescript.reconfigure_model":
            source = str(arguments.get("source") or "")
            parameters = _clean_parameters(arguments.get("parameters"))
            expected_outputs = _clean_outputs(arguments.get("expected_outputs"))
        elif operation == "vibescript.editor_rebuild":
            pass
        else:
            raise VibeScriptFailure(
                _failure(
                    "UNSUPPORTED_VIBESCRIPT_TOOL",
                    "surface",
                    f"Unsupported runner-backed VibeScript tool: {operation}",
                )
            )
        validate_source(source)

    revision = source_revision(source, parameters, expected_outputs)
    if (
        not creating
        and revision == base_revision
        and operation != "vibescript.editor_rebuild"
    ):
        raise VibeScriptFailure(
            _failure(
                "NO_MODEL_CHANGE",
                "precondition",
                "The requested VibeScript edit produces the existing model revision.",
                observed={"revision": revision},
                required_changes=[{"change_source_parameters_or_outputs": True}],
            )
        )

    prepared = {
        "engine": "vibescript",
        "model_id": model_id,
        "creating": creating,
        "operation": operation,
        "model_name": model_name,
        "source": source,
        "parameters": parameters,
        "expected_outputs": expected_outputs,
        "revision": revision,
        "base_revision": base_revision,
        "accepted_revision_before": accepted_revision_before,
        "accepted_outputs": accepted_outputs,
        "accepted_output_facts": accepted_output_facts,
        "project_root": str(project_root),
        "document_name": doc.Name,
        "cad_revision_before": service.structural_document_revision(),
        "service": service,
    }
    prepared["artifacts"] = _persist_working_candidate(prepared)
    return prepared


def _recompute_errors(summary: Any) -> list[dict[str, Any]]:
    if not isinstance(summary, dict):
        raise RuntimeError("FreeCAD returned an invalid recompute diagnostic payload.")
    if not bool(summary.get("captured")):
        raise RuntimeError(
            "FreeCAD recompute diagnostics are unavailable: "
            + str(summary.get("reason") or "no diagnostic reason was supplied")
        )
    diagnostics = summary.get("diagnostics")
    if not isinstance(diagnostics, list):
        raise RuntimeError("FreeCAD recompute diagnostics did not contain a list.")
    return [
        dict(item)
        for item in diagnostics
        if isinstance(item, dict) and str(item.get("severity") or "").lower() == "error"
    ]


def _accept_outputs(
    service: Any,
    doc: Any,
    prepared: dict[str, Any],
    context: dict[str, Any],
) -> None:
    """Tag, group, and mirror accepted outputs inside the open transaction."""
    result: dict[str, Any] = context["result"]
    new_objects: list[Any] = context["new_objects"]
    new_names = {str(getattr(obj, "Name", "")) for obj in new_objects}
    foreign = [
        str(key)
        for key, value in result.items()
        if str(getattr(value, "Name", "")) not in new_names
    ]
    if foreign:
        raise VibeScriptFailure(
            _failure(
                "OUTPUT_NOT_CREATED_BY_SCRIPT",
                "contract",
                "Every result output must be an object the script created in "
                f"this run; pre-existing objects were returned for: {foreign}.",
                observed={"foreign_outputs": foreign},
            )
        )

    container = doc.addObject(
        "App::Part", _safe_internal_name(prepared["model_name"], "VibeScriptModel")
    )
    for prop in (
        PROP_MODEL_ID,
        PROP_SOURCE,
        PROP_PARAMETERS,
        PROP_REVISION,
        PROP_RUNTIME_VERSION,
        PROP_OUTPUTS,
    ):
        _add_string_property(container, prop)

    contained: set[str] = set()
    for obj in new_objects:
        for child in list(getattr(obj, "OutListRecursive", []) or []):
            contained.add(str(getattr(child, "Name", "")))
    for obj in new_objects:
        if str(getattr(obj, "Name", "")) not in contained:
            container.addObject(obj)

    output_map: dict[str, Any] = {}
    for key, value in result.items():
        _add_string_property(value, PROP_MODEL_ID)
        _add_string_property(value, PROP_OUTPUT_KEY)
        setattr(value, PROP_MODEL_ID, prepared["model_id"])
        setattr(value, PROP_OUTPUT_KEY, str(key))
        output_map[str(key)] = {"object": str(getattr(value, "Name", "") or "")}

    container.Label = prepared["model_name"]
    setattr(container, PROP_MODEL_ID, prepared["model_id"])
    setattr(container, PROP_SOURCE, prepared["source"])
    setattr(container, PROP_PARAMETERS, _canonical_json(prepared["parameters"]))
    setattr(container, PROP_REVISION, prepared["revision"])
    setattr(container, PROP_RUNTIME_VERSION, VIBESCRIPT_VERSION)
    setattr(container, PROP_OUTPUTS, _canonical_json(output_map))

    doc.recompute()
    diagnostics = service.recompute_diagnostics()
    errors = _recompute_errors(diagnostics)
    if errors:
        first = errors[0]
        raise VibeScriptFailure(
            _failure(
                "VIBESCRIPT_COMMIT_FAILED",
                "commit",
                "FreeCAD reported errors while accepting VibeScript outputs. "
                f"First: {first.get('code') or 'UNKNOWN'} on "
                f"{first.get('object') or 'unknown object'}: "
                f"{first.get('message') or 'no message'}",
                observed={"recompute_errors": errors},
            )
        )
    output_facts = {
        item["key"]: {"shape": item["shape"]} for item in context["outputs"]
    }
    context["container"] = container
    context["output_map"] = output_map
    context["diagnostics"] = diagnostics
    context["mirror"] = _mirror_model(prepared, output_map, output_facts)


def execute_prepared(
    prepared: dict[str, Any],
    *,
    cancellation_check: Callable[[], bool] | None = None,
    timeout_seconds: float | None = None,
    max_operations: int | None = None,
) -> dict[str, Any]:
    """Run the prepared VibeScript synchronously and return a terminal payload.

    The whole lifecycle — delete prior owned objects, execute the source,
    enforce the output contract, tag and mirror accepted outputs — happens in
    one document transaction. There are no pending or wait states: the return
    value is always the final success or failure payload. In-process execution
    cannot be preempted mid-run; the execution budget bounds the worst case, so
    ``cancellation_check`` is only honored before execution starts.
    """
    service = prepared["service"]
    doc = service._active_document()
    if doc is None or str(getattr(doc, "Name", "")) != prepared["document_name"]:
        return _failure(
            "DOCUMENT_CHANGED",
            "precondition",
            "The active document changed after the VibeScript run was prepared.",
            observed={
                "expected_document": prepared["document_name"],
                "active_document": getattr(doc, "Name", None),
            },
        )
    if cancellation_check is not None and cancellation_check():
        return _failure(
            "RUN_CANCELLED",
            "execution",
            "VibeScript execution was cancelled before it started.",
            cancelled=True,
        )

    removed_objects: list[str] = []
    commit_failure: list[dict[str, Any]] = []

    def before_exec(document: Any) -> None:
        if prepared["accepted_revision_before"]:
            removed_objects.extend(
                delete_owned_model_objects(
                    document, PROP_MODEL_ID, prepared["model_id"]
                )
            )

    def after_contract(context: dict[str, Any]) -> None:
        try:
            _accept_outputs(service, doc, prepared, context)
            accepted_context.update(context)
        except VibeScriptFailure as exc:
            commit_failure.append(exc.payload)
            raise

    accepted_context: dict[str, Any] = {}
    started = time.monotonic()
    report = vibescript_executor.execute_model(
        doc,
        prepared["source"],
        expected_outputs=prepared["expected_outputs"],
        parameters=prepared["parameters"],
        max_operations=max_operations or DEFAULT_MAX_OPERATIONS,
        max_seconds=timeout_seconds or DEFAULT_TIMEOUT_SECONDS,
        before_exec=before_exec,
        after_contract=after_contract,
    )
    elapsed = time.monotonic() - started

    if not report.get("ok"):
        if commit_failure:
            failure = dict(commit_failure[0])
            failure.setdefault("observed", {})
            failure["observed"]["transaction"] = report.get("transaction")
            failure["observed"].setdefault("stdout", report.get("stdout") or "")
            if report.get("feature_report") is not None:
                failure["observed"].setdefault(
                    "feature_report", report["feature_report"]
                )
            return failure
        exception_kind = str(report.get("exception_kind") or "")
        failure_code = _EXECUTION_FAILURE_CODES.get(
            exception_kind, "VIBESCRIPT_EXECUTION_FAILED"
        )
        stage = "contract" if exception_kind == "contract_violation" else "execution"
        return _failure(
            failure_code,
            stage,
            str(report.get("error") or "VibeScript execution failed."),
            observed={
                "exception_type": report.get("exception_type"),
                "exception_kind": exception_kind or None,
                "traceback": report.get("traceback"),
                "script_frames": report.get("script_frames"),
                "failure_location": report.get("failure_location"),
                "policy_hint": report.get("policy_hint"),
                "stdout": report.get("stdout") or "",
                "transaction": report.get("transaction"),
                "budget": report.get("budget"),
                "feature_report": report.get("feature_report"),
                "elapsed_seconds": elapsed,
            },
            required_changes=[
                {"correct_source_or_parameters_from_failure_location": True}
            ],
        )

    container = accepted_context["container"]
    outputs = [
        {
            "key": item["key"],
            "object": (accepted_context["output_map"].get(item["key"]) or {}).get(
                "object"
            ),
            "shape": item["shape"],
        }
        for item in accepted_context["outputs"]
    ]
    return {
        "ok": True,
        "created": not prepared["accepted_revision_before"],
        "updated": bool(prepared["accepted_revision_before"]),
        "model": _model_summary(container, include_source=False),
        "outputs": outputs,
        "removed_objects": removed_objects,
        "created_objects": report.get("created_objects") or [],
        "stdout": report.get("stdout") or "",
        "mirror": accepted_context["mirror"],
        "execution": {
            "elapsed_seconds": elapsed,
            "vibescript_version": VIBESCRIPT_VERSION,
            "budget": report.get("budget"),
        },
        "native_diagnostics": accepted_context["diagnostics"],
        "cad_revision": service.structural_document_revision(),
    }


def cleanup_prepared(prepared: dict[str, Any]) -> None:
    """Release the prepared run's live references; no staging exists to remove."""
    prepared.pop("service", None)
