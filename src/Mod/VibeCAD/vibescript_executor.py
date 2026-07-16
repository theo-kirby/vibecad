# SPDX-License-Identifier: LGPL-2.1-or-later

"""In-process VibeScript executor.

Runs VibeScript model source against the live FreeCAD document, wrapped in a
document transaction so any failure rolls the document back to its exact
prior state::

    openTransaction -> exec source -> enforce contract -> commitTransaction
                                   \\-> any failure     -> abortTransaction

This module never imports FreeCAD. The caller passes the live document (or a
stub in tests), so every path is testable under plain pytest.

The execution budget is a trace-based guard: a runaway Python loop in model
source raises ``ExecutionBudgetExceeded`` instead of hanging the UI thread.
``ExecutionBudgetExceeded`` derives from ``BaseException`` so model-source
``except Exception`` blocks cannot swallow it, and the tracer's tripped flag
is re-checked after exec as a second line of defense against bare handlers.

Import policy is enforced statically (``VibeCADVibeScript.validate_source``
rejects disallowed imports before source ever reaches this module). The
execution namespace deliberately exposes the *real* ``__import__``: FreeCAD's
own machinery resolves ``__import__`` from the executing frame's builtins,
and a restricted runtime hook breaks ViewProvider attachment.

Script ``print()`` output is captured into a bounded per-execution buffer and
returned as ``stdout`` on both success and failure payloads, so model source
can report intermediate values without exception-driven probing.
"""

from __future__ import annotations

import sys
import time
import traceback
from collections.abc import Callable, Mapping, Sequence
from numbers import Real
from typing import Any

import VibeCADGeometry
import vibescript_api

__all__ = [
    "ALLOWED_IMPORT_ROOTS",
    "ContractViolation",
    "DEFAULT_MAX_OPERATIONS",
    "DEFAULT_MAX_SECONDS",
    "ExecutionBudgetExceeded",
    "MAX_STDOUT_CHARS",
    "SCRIPT_FILENAME",
    "TRANSACTION_NAME",
    "bop_check",
    "execute_model",
    "shape_facts",
]

SCRIPT_FILENAME = "<vibecad-vibescript>"
TRANSACTION_NAME = "VibeScript model"

DEFAULT_MAX_OPERATIONS = 5_000_000
# Wall-clock budget covers the whole transaction, including native FreeCAD
# recompute time (pads, booleans, patterns), which dominates on real parts.
# 30s proved too tight for multi-boolean models; 120s keeps runaway scripts
# bounded while leaving room for legitimate heavy recomputes.
DEFAULT_MAX_SECONDS = 120.0

MAX_STDOUT_CHARS = 65_536

ALLOWED_IMPORT_ROOTS = frozenset(
    {
        "FreeCAD",
        "Part",
        "PartDesign",
        "Sketcher",
        "vibescript_api",
        "collections",
        "dataclasses",
        "decimal",
        "enum",
        "fractions",
        "functools",
        "itertools",
        "math",
        "operator",
        "statistics",
        "typing",
    }
)


class ExecutionBudgetExceeded(BaseException):
    """The model source exceeded its execution budget.

    Derives from ``BaseException`` on purpose: model-source ``except
    Exception`` handlers must not be able to swallow a budget trip.
    """


class ContractViolation(vibescript_api.VibeScriptError):
    """The executed source did not satisfy the VibeScript output contract."""


# --------------------------------------------------------------------------
# Restricted execution namespace
# --------------------------------------------------------------------------


_BUILTIN_ALLOWLIST = (
    "ArithmeticError",
    "AssertionError",
    "AttributeError",
    "ImportError",
    "Exception",
    "IndexError",
    "KeyError",
    "NameError",
    "RuntimeError",
    "StopIteration",
    "TypeError",
    "ValueError",
    "ZeroDivisionError",
    "__build_class__",
    "abs",
    "all",
    "any",
    "bool",
    "classmethod",
    "dict",
    "dir",
    "enumerate",
    "filter",
    "float",
    "format",
    "frozenset",
    "hasattr",
    "int",
    "isinstance",
    "issubclass",
    "len",
    "list",
    "map",
    "max",
    "min",
    "object",
    "pow",
    "print",
    "property",
    "range",
    "repr",
    "reversed",
    "round",
    "set",
    "slice",
    "sorted",
    "str",
    "staticmethod",
    "sum",
    "super",
    "tuple",
    "type",
    "zip",
)

# Private frame-builtin entries required by native Python bindings. These are
# runtime protocol details, not names VibeScript source is allowed to use.
_FRAME_INTERNAL_BUILTINS = frozenset({"__orig_import__"})

#: Names resolvable inside VibeScript source without a policy hint on NameError.
_ALLOWED_BUILTIN_NAMES = frozenset(_BUILTIN_ALLOWLIST) | {"__import__"}


class _StdoutBuffer:
    """Bounded sink for script ``print()`` output.

    Stops accepting text after ``limit`` characters and reports the
    truncation in :meth:`getvalue` so payloads stay JSON-safe and small.
    """

    __slots__ = ("chunks", "length", "limit", "truncated")

    def __init__(self, limit: int = MAX_STDOUT_CHARS) -> None:
        self.chunks: list[str] = []
        self.length = 0
        self.limit = limit
        self.truncated = False

    def write(self, text: str) -> None:
        if self.truncated:
            return
        space = self.limit - self.length
        if len(text) > space:
            text = text[:space]
            self.truncated = True
        if text:
            self.chunks.append(text)
            self.length += len(text)

    def getvalue(self) -> str:
        value = "".join(self.chunks)
        if self.truncated:
            value += f"\n[stdout truncated at {self.limit} characters]"
        return value


def _sandbox_print(buffer: _StdoutBuffer) -> Callable[..., None]:
    """Return a ``print`` replacement that writes to ``buffer``.

    ``file`` and ``flush`` keywords are accepted for signature compatibility
    but ignored: script output always goes to the captured buffer.
    """

    def sandbox_print(
        *values: Any,
        sep: str | None = " ",
        end: str | None = "\n",
        file: Any = None,
        flush: bool = False,
    ) -> None:
        del file, flush
        joiner = " " if sep is None else str(sep)
        terminator = "\n" if end is None else str(end)
        buffer.write(joiner.join(str(value) for value in values) + terminator)

    return sandbox_print


def _restricted_builtins(stdout: _StdoutBuffer) -> dict[str, Any]:
    import builtins

    allowed = {name: getattr(builtins, name) for name in _BUILTIN_ALLOWLIST}
    allowed["print"] = _sandbox_print(stdout)
    # Import policy is enforced *statically* (AST validation before execution).
    # The runtime ``__import__`` must be the real one: FreeCAD's own machinery
    # (e.g. ViewProvider attachment during ``doc.addObject``) resolves
    # ``__import__`` from the executing frame's builtins, and a restricted
    # hook here vetoes FreeCAD importing its own Gui modules, leaving objects
    # without ViewProviders. Static validation already rejects imports the
    # script author writes; runtime imports triggered by FreeCAD internals
    # must succeed unconditionally.
    allowed["__import__"] = builtins.__import__
    # PySide/Shiboken's feature-aware importer fetches ``__orig_import__``
    # from the *executing frame's* builtins. Omitting it makes libshiboken
    # call Py_FatalError during an otherwise ordinary import, terminating the
    # whole FreeCAD process. Preserve the interpreter-installed callable in
    # this private frame dictionary; source validation prevents model code
    # from resolving the private name directly.
    orig_import = getattr(builtins, "__orig_import__", None)
    if callable(orig_import):
        allowed["__orig_import__"] = orig_import
    return allowed


def _build_namespace(
    document: Any,
    parameters: Mapping[str, Any] | vibescript_api.Params | None,
    environment: Mapping[str, Any] | None,
    stdout: _StdoutBuffer,
) -> dict[str, Any]:
    if isinstance(parameters, vibescript_api.Params):
        params = parameters
    else:
        params = vibescript_api.Params(**dict(parameters or {}))
    namespace: dict[str, Any] = {
        "__builtins__": _restricted_builtins(stdout),
        "__name__": "__vibecad_vibescript__",
        "doc": document,
        "params": params,
    }
    for name in vibescript_api.__all__:
        namespace[name] = getattr(vibescript_api, name)
    if environment:
        namespace.update(environment)
    return namespace


# --------------------------------------------------------------------------
# Execution budget
# --------------------------------------------------------------------------


class _BudgetTracer:
    """Trace function that bounds line-event count and wall-clock time."""

    __slots__ = ("deadline", "executed", "max_operations", "max_seconds", "tripped")

    def __init__(self, max_operations: int, max_seconds: float) -> None:
        self.max_operations = max_operations
        self.max_seconds = max_seconds
        self.deadline = time.monotonic() + max_seconds
        self.executed = 0
        self.tripped: str | None = None

    def _trip(self, reason: str) -> None:
        self.tripped = reason
        raise ExecutionBudgetExceeded(reason)

    def __call__(self, frame: Any, event: str, arg: Any) -> "_BudgetTracer":
        if self.tripped is not None:
            raise ExecutionBudgetExceeded(self.tripped)
        self.executed += 1
        if self.executed > self.max_operations:
            self._trip(
                "execution budget exceeded: more than "
                f"{self.max_operations} traced operations; remove unbounded "
                "loops from the model source."
            )
        if not (self.executed & 0x03FF) and time.monotonic() > self.deadline:
            self._trip(
                f"execution budget exceeded: ran longer than {self.max_seconds:g} "
                "seconds (wall clock, including native FreeCAD recompute time); "
                "simplify the model source or reduce recompute-heavy features."
            )
        return self


# --------------------------------------------------------------------------
# Shape facts (duck-typed over FreeCAD Part shapes)
# --------------------------------------------------------------------------


def shape_facts(shape: Any) -> dict[str, Any]:
    """Extract JSON-safe geometric facts from a FreeCAD-like shape."""
    facts: dict[str, Any] = {}
    is_valid = getattr(shape, "isValid", None)
    if callable(is_valid):
        facts["valid"] = bool(is_valid())
    for key, attribute in (
        ("solid_count", "Solids"),
        ("face_count", "Faces"),
        ("edge_count", "Edges"),
        ("vertex_count", "Vertexes"),
    ):
        items = getattr(shape, attribute, None)
        if items is not None:
            facts[key] = len(items)
    for key, attribute in (("volume_mm3", "Volume"), ("surface_area_mm2", "Area")):
        value = getattr(shape, attribute, None)
        if isinstance(value, Real) and not isinstance(value, bool):
            facts[key] = float(value)
    # Prefer the optimal (tight) bounding box: the default BoundBox is
    # computed from control points, so B-spline surfaces overshoot it and
    # scripts asserting on bounds see phantom oversize.
    bounds = None
    optimal = getattr(shape, "optimalBoundingBox", None)
    if callable(optimal):
        try:
            bounds = optimal()
        except (RuntimeError, TypeError, ValueError):
            # FreeCAD raises Base.FreeCADError (a RuntimeError) when the
            # tight box cannot be computed; fall back to the loose box.
            bounds = None
    if bounds is None:
        bounds = getattr(shape, "BoundBox", None)
    if bounds is not None:
        try:
            facts["bounds_mm"] = {
                "min": [
                    float(bounds.XMin),
                    float(bounds.YMin),
                    float(bounds.ZMin),
                ],
                "max": [
                    float(bounds.XMax),
                    float(bounds.YMax),
                    float(bounds.ZMax),
                ],
                "size": [
                    float(bounds.XLength),
                    float(bounds.YLength),
                    float(bounds.ZLength),
                ],
            }
        except (AttributeError, TypeError, ValueError):
            pass
    return facts


def _validation_defect_detail(result: Mapping[str, Any]) -> str | None:
    """Summarize structured worker diagnostics for contract error messages."""
    details: list[str] = []
    for stage in ("brep", "bop"):
        report = result.get(stage)
        if not isinstance(report, Mapping):
            continue
        defects = report.get("defects")
        if not isinstance(defects, Sequence) or isinstance(defects, (str, bytes)):
            continue
        for defect in defects:
            if not isinstance(defect, Mapping):
                details.append(f"{stage.upper()}: {defect!s}")
                continue
            status = str(defect.get("status") or "unknown defect")
            shape_type = str(defect.get("shape_type") or "shape")
            shape_index = defect.get("shape_index")
            location = (
                f"{shape_type} {shape_index}" if shape_index is not None else shape_type
            )
            details.append(f"{stage.upper()}: {status} ({location})")
    if details:
        return "; ".join(details)
    error = result.get("error")
    return str(error) if error else None


def bop_check(shape: Any) -> tuple[bool | None, str | None]:
    """Run deep BREP/BOP validation in the isolated geometry worker.

    Returns ``(True, None)`` for a valid shape and ``(False, detail)`` for
    reported defects or a native worker crash. Validation is unknown when the
    shape cannot be exported (including duck-typed test doubles), the worker
    is unavailable, or another infrastructure failure prevents a result.
    """
    result = VibeCADGeometry.validate_shape(shape)
    valid = result.get("valid")
    if valid is True:
        return True, None
    detail = _validation_defect_detail(result)
    if valid is False:
        return False, detail or "unspecified defect"
    if result.get("failure_code") == "GEOMETRY_WORKER_CRASHED":
        return False, detail or "the isolated geometry validator crashed"
    if result.get("failure_code") == "BREP_EXPORT_UNAVAILABLE":
        return None, None
    return None, detail


# --------------------------------------------------------------------------
# Contract enforcement
# --------------------------------------------------------------------------


def _object_names(document: Any) -> set[str]:
    objects = getattr(document, "Objects", None) or []
    return {str(getattr(item, "Name", "")) for item in objects}


def _new_objects(document: Any, before_names: set[str]) -> list[Any]:
    objects = getattr(document, "Objects", None) or []
    return [
        item for item in objects if str(getattr(item, "Name", "")) not in before_names
    ]


def _check_new_sketches(new_objects: list[Any]) -> None:
    for item in new_objects:
        type_id = str(getattr(item, "TypeId", ""))
        if not type_id.startswith("Sketcher::"):
            continue
        try:
            vibescript_api.assert_fully_constrained(item)
        except vibescript_api.SketchValidationError as error:
            raise ContractViolation(str(error)) from error


def _enforce_contract(
    document: Any,
    namespace: dict[str, Any],
    expected_outputs: list[str],
    new_objects: list[Any],
) -> list[dict[str, Any]]:
    result = namespace.get("result")
    if not isinstance(result, dict) or not result:
        raise ContractViolation(
            "The VibeScript source must assign a non-empty dict mapping output "
            "names to document objects to `result`."
        )
    actual_outputs = [str(key) for key in result]
    if expected_outputs and actual_outputs != expected_outputs:
        raise ContractViolation(
            "result keys must exactly match expected_outputs in the same "
            f"order; expected {expected_outputs!r}, received {actual_outputs!r}."
        )

    recompute = getattr(document, "recompute", None)
    if callable(recompute):
        recompute()

    _check_new_sketches(new_objects)

    outputs: list[dict[str, Any]] = []
    for key, value in result.items():
        shape = getattr(value, "Shape", None)
        if value is None or shape is None:
            raise ContractViolation(
                f"result[{key!r}] is missing an output body: expected a "
                "document object exposing Shape, received "
                f"{type(value).__name__}."
            )
        is_valid = getattr(value, "isValid", None)
        if callable(is_valid) and not is_valid():
            raise ContractViolation(
                f"result[{key!r}] ({getattr(value, 'Name', key)!s}) failed to "
                "recompute cleanly."
            )
        facts = shape_facts(shape)
        if not facts.get("valid", True):
            raise ContractViolation(f"result[{key!r}] has an invalid shape.")
        solid_count = int(facts.get("solid_count", 0))
        if solid_count != 1:
            raise ContractViolation(
                f"result[{key!r}] must contain exactly one solid; received "
                f"{solid_count}. Return physical components as separate named "
                "outputs."
            )
        bop_ok, bop_detail = bop_check(shape)
        if bop_ok is False:
            raise ContractViolation(
                f"result[{key!r}] ({getattr(value, 'Name', key)!s}) passed "
                "recompute but OCCT's deep validity check (BOPCheck) reports "
                f"defects: {bop_detail or 'unspecified defect'}. Defective "
                "booleans usually come from tangent face contact or plane "
                "faces piercing spline/loft surfaces; overlap fused geometry "
                "by >=0.5mm or attach at a loft's own end-cap section."
            )
        outputs.append(
            {
                "key": key,
                "object_name": str(getattr(value, "Name", "")) or None,
                "label": str(getattr(value, "Label", "")) or None,
                "shape": facts,
            }
        )
    return outputs


# --------------------------------------------------------------------------
# Failure evidence
# --------------------------------------------------------------------------


def _feature_entry(item: Any) -> dict[str, Any]:
    """JSON-safe shape health facts for one document object."""
    entry: dict[str, Any] = {
        "object_name": str(getattr(item, "Name", "")) or None,
        "label": str(getattr(item, "Label", "")) or None,
        "type_id": str(getattr(item, "TypeId", "")) or None,
    }
    try:
        shape = getattr(item, "Shape", None)
    except (AttributeError, RuntimeError, TypeError):
        shape = None
    if shape is None:
        entry["has_shape"] = False
        entry["defective"] = False
        return entry
    entry["has_shape"] = True
    try:
        facts = shape_facts(shape)
    except (AttributeError, RuntimeError, TypeError, ValueError):
        facts = {}
    entry["is_valid"] = facts.get("valid")
    for key in ("solid_count", "volume_mm3", "bounds_mm"):
        if key in facts:
            entry[key] = facts[key]
    bop_ok, bop_detail = bop_check(shape)
    entry["bop_ok"] = bop_ok
    if bop_detail:
        entry["bop_errors"] = bop_detail
    entry["defective"] = entry["is_valid"] is False or bop_ok is False
    return entry


def _collect_feature_report(
    document: Any, before_names: set[str]
) -> dict[str, Any] | None:
    """Shape health facts for every object this run created, in tree order.

    Runs on the failure path *before* the transaction is aborted, while the
    created objects still exist. Defective OCCT booleans compute
    "successfully" and only break the *next* feature, so the report flags
    the first defective feature — the true culprit — instead of leaving the
    agent chasing the downstream failure. Best-effort by design: it must
    never raise, because it runs while the original failure is being
    reported.
    """
    try:
        entries: list[dict[str, Any]] = []
        first_defective: str | None = None
        for item in _new_objects(document, before_names):
            entry = _feature_entry(item)
            if entry.get("defective") and first_defective is None:
                first_defective = entry.get("object_name") or entry.get("label")
            entries.append(entry)
        if not entries:
            return None
        return {"features": entries, "first_defective": first_defective}
    except Exception:  # noqa: BLE001 - must never mask the original failure
        return None


def _script_frames(exc: BaseException, source: str) -> list[dict[str, Any]]:
    lines = source.splitlines()
    frames: list[dict[str, Any]] = []
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        tb = current.__traceback__
        while tb is not None:
            frame = tb.tb_frame
            if frame.f_code.co_filename == SCRIPT_FILENAME:
                item: dict[str, Any] = {
                    "line": int(tb.tb_lineno),
                    "function": str(frame.f_code.co_name),
                }
                if 0 < tb.tb_lineno <= len(lines):
                    item["source"] = lines[tb.tb_lineno - 1].strip()
                frames.append(item)
            tb = tb.tb_next
        if frames:
            break
        current = current.__cause__ or current.__context__
    return frames[-16:]


def _policy_hint_for(exc: BaseException) -> str | None:
    """Explain a NameError caused by a policy-excluded builtin.

    Returns a hint only when the missing name is a real Python builtin that
    the sandbox deliberately does not expose; ordinary typos get no hint.
    """
    if not isinstance(exc, NameError):
        return None
    name = getattr(exc, "name", None)
    if not isinstance(name, str) or not name or name in _ALLOWED_BUILTIN_NAMES:
        return None
    import builtins

    if not hasattr(builtins, name):
        return None
    return (
        f"{name!r} is a Python builtin that the VibeScript sandbox excludes "
        "by policy. Use the vibescript_api helpers and the allowed builtin "
        "subset (math, containers, iteration, introspection, print) instead."
    )


def _exception_kind(exc: BaseException) -> str:
    if isinstance(exc, ExecutionBudgetExceeded):
        return "execution_budget_exceeded"
    if isinstance(exc, ContractViolation):
        return "contract_violation"
    if isinstance(exc, vibescript_api.SketchValidationError):
        return "sketch_validation_failure"
    if isinstance(exc, vibescript_api.VibeScriptError):
        return "vibescript_api_failure"
    if isinstance(exc, SyntaxError):
        return "syntax_error"
    if isinstance(exc, AssertionError):
        return "design_assertion_failure"
    return "python_execution_failure"


def _failure_payload(
    exc: BaseException,
    source: str,
    *,
    opened: bool,
    aborted: bool,
    budget: dict[str, Any] | None = None,
    stdout: str = "",
    feature_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    frames = _script_frames(exc, source)
    location: dict[str, Any] | None = frames[-1] if frames else None
    if isinstance(exc, SyntaxError) and exc.lineno is not None:
        location = {"line": int(exc.lineno), "source": (exc.text or "").strip()}
    hint = _policy_hint_for(exc)
    error = str(exc) if hint is None else f"{exc}. {hint}"
    payload: dict[str, Any] = {
        "ok": False,
        "error": error,
        "exception_type": type(exc).__name__,
        "exception_kind": _exception_kind(exc),
        "traceback": "".join(traceback.format_exception(exc, limit=16)),
        "script_frames": frames,
        "stdout": stdout,
        "transaction": {"opened": opened, "committed": False, "aborted": aborted},
    }
    if hint is not None:
        payload["policy_hint"] = hint
    if location is not None:
        payload["failure_location"] = location
    if budget is not None:
        payload["budget"] = budget
    if feature_report is not None:
        payload["feature_report"] = feature_report
    return payload


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def execute_model(
    document: Any,
    source: str,
    *,
    expected_outputs: Sequence[str],
    parameters: Mapping[str, Any] | vibescript_api.Params | None = None,
    environment: Mapping[str, Any] | None = None,
    max_operations: int = DEFAULT_MAX_OPERATIONS,
    max_seconds: float = DEFAULT_MAX_SECONDS,
    transaction_name: str = TRANSACTION_NAME,
    before_exec: Callable[[Any], None] | None = None,
    after_contract: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Execute VibeScript ``source`` against ``document`` atomically.

    Returns a JSON-safe report: ``{"ok": True, "outputs": [...], ...}`` on
    success, ``{"ok": False, "error": ..., "failure_location": ...}`` on any
    failure. Failure payloads additionally carry ``feature_report``: per-
    feature shape health facts (validity, solid count, volume, bounds,
    BOPCheck) for every object the run created, collected before the abort,
    with the first defective feature flagged. On failure the document
    transaction is aborted, leaving the document in its exact prior state. ``KeyboardInterrupt``/``SystemExit``
    still abort the transaction but propagate to the caller.

    ``before_exec(document)`` runs inside the transaction before the source
    executes (engines use it to delete objects owned by a prior revision).
    ``after_contract(context)`` runs inside the transaction after contract
    enforcement and immediately before commit; ``context`` carries ``result``
    (the output-name -> document-object mapping), ``new_objects``, and
    ``outputs`` (JSON-safe facts). Either hook may raise to abort atomically.
    """
    if max_operations <= 0:
        raise ValueError(f"max_operations must be positive, got {max_operations}.")
    if max_seconds <= 0:
        raise ValueError(f"max_seconds must be positive, got {max_seconds:g}.")

    expected = [str(item) for item in expected_outputs]
    stdout = _StdoutBuffer()
    try:
        compiled = compile(source, SCRIPT_FILENAME, "exec")
        namespace = _build_namespace(document, parameters, environment, stdout)
    except (SyntaxError, ValueError, TypeError, vibescript_api.VibeScriptError) as exc:
        return _failure_payload(
            exc, source, opened=False, aborted=False, stdout=stdout.getvalue()
        )

    tracer = _BudgetTracer(max_operations, max_seconds)

    def _budget() -> dict[str, Any]:
        return {
            "max_operations": max_operations,
            "max_seconds": max_seconds,
            "operations_used": tracer.executed,
        }

    before_names: set[str] | None = None
    document.openTransaction(transaction_name)
    try:
        if before_exec is not None:
            before_exec(document)
        before_names = _object_names(document)
        previous_trace = sys.gettrace()
        sys.settrace(tracer)
        try:
            exec(compiled, namespace)  # noqa: S102 - policy-validated source
        finally:
            sys.settrace(previous_trace)
        if tracer.tripped is not None:
            raise ExecutionBudgetExceeded(tracer.tripped)
        new_objects = _new_objects(document, before_names)
        outputs = _enforce_contract(document, namespace, expected, new_objects)
        if after_contract is not None:
            after_contract(
                {
                    "result": dict(namespace["result"]),
                    "new_objects": list(new_objects),
                    "outputs": outputs,
                }
            )
        document.commitTransaction()
        return {
            "ok": True,
            "outputs": outputs,
            "created_objects": [str(getattr(item, "Name", "")) for item in new_objects],
            "stdout": stdout.getvalue(),
            "transaction": {"opened": True, "committed": True, "aborted": False},
            "budget": _budget(),
        }
    except (Exception, ExecutionBudgetExceeded) as exc:
        # Collect per-feature evidence while the created objects still
        # exist: abortTransaction destroys them.
        feature_report = (
            _collect_feature_report(document, before_names)
            if before_names is not None
            else None
        )
        document.abortTransaction()
        return _failure_payload(
            exc,
            source,
            opened=True,
            aborted=True,
            budget=_budget(),
            stdout=stdout.getvalue(),
            feature_report=feature_report,
        )
    except BaseException:
        document.abortTransaction()
        raise
