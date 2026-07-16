# SPDX-License-Identifier: LGPL-2.1-or-later

"""Contract tests for the VibeScript engine module (no FreeCAD required).

VibeCADVibeScript exposes the same runner API surface as the build123d and
OpenSCAD engines (prepare_execution, execute_prepared, record_failed_attempt,
cleanup_prepared, inspect_model, delete_model, model_summaries, editor
staging) but with a synchronous lifecycle: ``execute_prepared`` runs the
source in-process inside one document transaction and always returns a
terminal payload.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import VibeCADVibeScript as vibescript

MODEL_ID = "b" * 32

SOURCE_OK = (
    'body = doc.addObject("PartDesign::Body", "Body")\nresult = {"Body": body}\n'
)


# ---------------------------------------------------------------------------
# Stub document objects
# ---------------------------------------------------------------------------


class _StubBoundBox:
    XMin = 0.0
    YMin = 0.0
    ZMin = 0.0
    XMax = 10.0
    YMax = 20.0
    ZMax = 30.0
    XLength = 10.0
    YLength = 20.0
    ZLength = 30.0


class _StubShape:
    def __init__(self, *, solids: int = 1, valid: bool = True) -> None:
        self.Solids = [object() for _ in range(solids)]
        self.Faces = [object() for _ in range(6)]
        self.Edges = [object() for _ in range(12)]
        self.Vertexes = [object() for _ in range(8)]
        self.Volume = 6000.0
        self.Area = 2200.0
        self.BoundBox = _StubBoundBox()
        self._valid = valid

    def isValid(self) -> bool:
        return self._valid


class _StubObject:
    def __init__(self, name: str, type_id: str) -> None:
        self.Name = name
        self.Label = name
        self.TypeId = type_id
        self.PropertiesList: list[str] = []
        self.Group: list[Any] = []
        self.OutListRecursive: list[Any] = []
        if type_id != "App::Part":
            self.Shape = _StubShape()

    def addProperty(self, _type: str, name: str, _group: str = "") -> None:
        if name not in self.PropertiesList:
            self.PropertiesList.append(name)
            setattr(self, name, "")

    def addObject(self, obj: Any) -> None:
        self.Group.append(obj)
        self.OutListRecursive.append(obj)

    def isValid(self) -> bool:
        return True


class _StubDocument:
    """Document stub with FreeCAD transaction semantics and abort rollback."""

    def __init__(self, name: str = "Doc") -> None:
        self.Name = name
        self.Objects: list[Any] = []
        self.transaction_log: list[str] = []
        self._snapshot: list[Any] | None = None
        self._sequence = 0

    def openTransaction(self, label: str) -> None:
        self.transaction_log.append(f"open:{label}")
        self._snapshot = list(self.Objects)

    def commitTransaction(self) -> None:
        self.transaction_log.append("commit")
        self._snapshot = None

    def abortTransaction(self) -> None:
        self.transaction_log.append("abort")
        if self._snapshot is not None:
            self.Objects = list(self._snapshot)
            self._snapshot = None

    def addObject(self, type_id: str, name: str) -> _StubObject:
        self._sequence += 1
        obj = _StubObject(f"{name}{self._sequence:03d}", type_id)
        self.Objects.append(obj)
        return obj

    def getObject(self, name: str) -> Any | None:
        return next((obj for obj in self.Objects if obj.Name == name), None)

    def removeObject(self, name: str) -> None:
        obj = self.getObject(name)
        if obj is not None:
            self.Objects.remove(obj)

    def recompute(self) -> None:
        pass


def _stub_service(
    doc: _StubDocument,
    project_root: Path,
    diagnostics: list[dict[str, Any]] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        _active_document=lambda: doc,
        project_context=lambda: {"root": str(project_root)},
        recompute_diagnostics=lambda: {
            "captured": True,
            "diagnostics": list(diagnostics or []),
        },
        structural_document_revision=lambda: "cad-revision-1",
    )


def _create_arguments(**overrides: Any) -> dict[str, Any]:
    arguments: dict[str, Any] = {
        "model_name": "Test Model",
        "source": SOURCE_OK,
        "parameters": {"width": 10.0},
        "expected_outputs": ["Body"],
    }
    arguments.update(overrides)
    return arguments


def _prepare_create(
    tmp_path: Path, doc: _StubDocument | None = None, **overrides: Any
) -> dict[str, Any]:
    doc = doc if doc is not None else _StubDocument()
    service = _stub_service(doc, tmp_path)
    return vibescript.prepare_execution(
        service, "vibescript.create_model", _create_arguments(**overrides)
    )


# ---------------------------------------------------------------------------
# Source policy
# ---------------------------------------------------------------------------


class TestVibeScriptSourcePolicy:
    def test_valid_source_passes(self) -> None:
        vibescript.validate_source(
            "import math\n"
            "from vibescript_api import SketchBuilder\n"
            "result = {'Body': doc.addObject('PartDesign::Body', 'Body')}\n"
        )

    def test_freecad_imports_allowed(self) -> None:
        vibescript.validate_source(
            "import FreeCAD\nimport Part\nimport Sketcher\nimport PartDesign\n"
            "result = {'Body': None}\n"
        )

    def test_empty_source_rejected(self) -> None:
        with pytest.raises(vibescript.VibeScriptFailure) as excinfo:
            vibescript.validate_source("")
        assert excinfo.value.payload["failure_code"] == "SOURCE_REQUIRED"

    def test_oversized_source_rejected(self) -> None:
        big = "# pad\n" * (vibescript.MAX_SOURCE_BYTES // 6 + 2)
        with pytest.raises(vibescript.VibeScriptFailure) as excinfo:
            vibescript.validate_source(big)
        payload = excinfo.value.payload
        assert payload["failure_code"] == "SOURCE_TOO_LARGE"
        assert payload["observed"]["source_bytes"] > vibescript.MAX_SOURCE_BYTES

    def test_syntax_error_reports_location(self) -> None:
        with pytest.raises(vibescript.VibeScriptFailure) as excinfo:
            vibescript.validate_source("def broken(:\n")
        payload = excinfo.value.payload
        assert payload["failure_code"] == "SOURCE_SYNTAX_ERROR"
        assert payload["observed"]["line"] == 1

    def test_disallowed_import_rejected_with_allowed_list(self) -> None:
        with pytest.raises(vibescript.VibeScriptFailure) as excinfo:
            vibescript.validate_source("import os\n")
        payload = excinfo.value.payload
        assert payload["failure_code"] == "SOURCE_POLICY_VIOLATION"
        violations = payload["observed"]["violations"]
        assert violations and "os" in violations[0]["reason"]
        # Actionable: the message names what *is* allowed.
        assert "vibescript_api" in violations[0]["reason"]
        assert payload["retry"]["required_changes"]

    def test_disallowed_import_from_rejected(self) -> None:
        with pytest.raises(vibescript.VibeScriptFailure) as excinfo:
            vibescript.validate_source("from subprocess import run\n")
        payload = excinfo.value.payload
        assert payload["failure_code"] == "SOURCE_POLICY_VIOLATION"
        assert any(
            "subprocess" in item["reason"] for item in payload["observed"]["violations"]
        )

    def test_relative_import_rejected(self) -> None:
        with pytest.raises(vibescript.VibeScriptFailure) as excinfo:
            vibescript.validate_source("from . import secrets\n")
        assert excinfo.value.payload["failure_code"] == "SOURCE_POLICY_VIOLATION"

    def test_disallowed_call_rejected(self) -> None:
        with pytest.raises(vibescript.VibeScriptFailure) as excinfo:
            vibescript.validate_source("data = open('/etc/passwd').read()\n")
        payload = excinfo.value.payload
        assert payload["failure_code"] == "SOURCE_POLICY_VIOLATION"
        assert any(
            "open" in item["reason"] for item in payload["observed"]["violations"]
        )

    def test_dunder_access_rejected(self) -> None:
        with pytest.raises(vibescript.VibeScriptFailure) as excinfo:
            vibescript.validate_source("x = (1).__class__\n")
        payload = excinfo.value.payload
        assert payload["failure_code"] == "SOURCE_POLICY_VIOLATION"
        assert any(
            "__class__" in item["reason"] for item in payload["observed"]["violations"]
        )

    def test_builtins_name_read_rejected(self) -> None:
        with pytest.raises(vibescript.VibeScriptFailure) as excinfo:
            vibescript.validate_source("x = __builtins__\n")
        payload = excinfo.value.payload
        assert payload["failure_code"] == "SOURCE_POLICY_VIOLATION"
        assert any(
            "__builtins__" in item["reason"]
            for item in payload["observed"]["violations"]
        )

    def test_shiboken_private_import_name_rejected(self) -> None:
        with pytest.raises(vibescript.VibeScriptFailure) as excinfo:
            vibescript.validate_source("module = __orig_import__('os')\n")
        payload = excinfo.value.payload
        assert payload["failure_code"] == "SOURCE_POLICY_VIOLATION"
        assert any(
            "__orig_import__" in item["reason"]
            for item in payload["observed"]["violations"]
        )

    def test_violation_line_numbers_reported(self) -> None:
        with pytest.raises(vibescript.VibeScriptFailure) as excinfo:
            vibescript.validate_source("import math\nimport socket\n")
        assert excinfo.value.payload["observed"]["violations"][0]["line"] == 2


# ---------------------------------------------------------------------------
# Failure payload parity with the other engines
# ---------------------------------------------------------------------------


class TestFailurePayloadContract:
    REQUIRED_KEYS = (
        "ok",
        "tool",
        "failure_code",
        "failure_stage",
        "error",
        "requested",
        "normalized",
        "observed",
        "candidates",
        "allowed_values",
        "state_change",
        "native_diagnostics",
        "retry",
    )

    def test_failure_payloads_carry_shared_contract_keys(self) -> None:
        with pytest.raises(vibescript.VibeScriptFailure) as excinfo:
            vibescript.validate_source("import os\n")
        payload = excinfo.value.payload
        for key in self.REQUIRED_KEYS:
            assert key in payload, key
        assert payload["tool"] == "vibescript"
        assert payload["ok"] is False
        assert payload["engine_stage"] == "source_validation"


# ---------------------------------------------------------------------------
# Revisions
# ---------------------------------------------------------------------------


class TestSourceRevision:
    def test_revision_is_deterministic(self) -> None:
        first = vibescript.source_revision(SOURCE_OK, {"a": 1.0}, ["Body"])
        second = vibescript.source_revision(SOURCE_OK, {"a": 1.0}, ["Body"])
        assert first == second
        assert len(first) == 64

    def test_revision_changes_with_any_component(self) -> None:
        base = vibescript.source_revision(SOURCE_OK, {"a": 1.0}, ["Body"])
        assert vibescript.source_revision(SOURCE_OK + "#", {"a": 1.0}, ["Body"]) != base
        assert vibescript.source_revision(SOURCE_OK, {"a": 2.0}, ["Body"]) != base
        assert vibescript.source_revision(SOURCE_OK, {"a": 1.0}, ["Other"]) != base


# ---------------------------------------------------------------------------
# prepare_execution
# ---------------------------------------------------------------------------


class TestPrepareExecution:
    def test_create_prepares_and_persists_working_candidate(
        self, tmp_path: Path
    ) -> None:
        prepared = _prepare_create(tmp_path)
        assert prepared["engine"] == "vibescript"
        assert prepared["creating"] is True
        assert prepared["expected_outputs"] == ["Body"]
        directory = Path(prepared["artifacts"]["artifact_directory"])
        assert (directory / "model.py").read_text(encoding="utf-8") == SOURCE_OK
        assert (directory / "manifest.json").is_file()
        assert (directory / "parameters.json").is_file()

    def test_invalid_model_name_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(vibescript.VibeScriptFailure) as excinfo:
            _prepare_create(tmp_path, model_name="9bad")
        assert excinfo.value.payload["failure_code"] == "INVALID_MODEL_NAME"

    def test_invalid_parameters_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(vibescript.VibeScriptFailure) as excinfo:
            _prepare_create(tmp_path, parameters={"width": "wide"})
        assert excinfo.value.payload["failure_code"] == "INVALID_PARAMETERS"

    def test_missing_outputs_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(vibescript.VibeScriptFailure) as excinfo:
            _prepare_create(tmp_path, expected_outputs=[])
        assert excinfo.value.payload["failure_code"] == "OUTPUTS_REQUIRED"

    def test_policy_violating_source_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(vibescript.VibeScriptFailure) as excinfo:
            _prepare_create(tmp_path, source="import os\nresult = {}\n")
        assert excinfo.value.payload["failure_code"] == "SOURCE_POLICY_VIOLATION"

    def test_duplicate_model_label_rejected(self, tmp_path: Path) -> None:
        doc = _StubDocument()
        first = _prepare_create(tmp_path, doc=doc)
        assert first["model_id"]
        with pytest.raises(vibescript.VibeScriptFailure) as excinfo:
            _prepare_create(tmp_path, doc=doc)
        assert excinfo.value.payload["failure_code"] == "MODEL_NAME_EXISTS"

    def test_edit_unknown_model_rejected(self, tmp_path: Path) -> None:
        doc = _StubDocument()
        service = _stub_service(doc, tmp_path)
        with pytest.raises(vibescript.VibeScriptFailure) as excinfo:
            vibescript.prepare_execution(
                service,
                "vibescript.edit_source",
                {"model_id": MODEL_ID, "expected_revision": "x", "edits": []},
            )
        assert excinfo.value.payload["failure_code"] == "MODEL_NOT_FOUND"

    def test_edit_stale_revision_rejected(self, tmp_path: Path) -> None:
        doc = _StubDocument()
        prepared = _prepare_create(tmp_path, doc=doc)
        service = _stub_service(doc, tmp_path)
        with pytest.raises(vibescript.VibeScriptFailure) as excinfo:
            vibescript.prepare_execution(
                service,
                "vibescript.edit_source",
                {
                    "model_id": prepared["model_id"],
                    "expected_revision": "stale",
                    "edits": [{"old_text": "Body", "new_text": "Plate"}],
                },
            )
        assert excinfo.value.payload["failure_code"] == "STALE_MODEL_REVISION"

    def test_edit_source_applies_unique_replacement(self, tmp_path: Path) -> None:
        doc = _StubDocument()
        created = _prepare_create(tmp_path, doc=doc)
        service = _stub_service(doc, tmp_path)
        prepared = vibescript.prepare_execution(
            service,
            "vibescript.edit_source",
            {
                "model_id": created["model_id"],
                "expected_revision": created["revision"],
                "edits": [
                    {
                        "old_text": 'doc.addObject("PartDesign::Body", "Body")',
                        "new_text": 'doc.addObject("PartDesign::Body", "Plate")',
                    }
                ],
            },
        )
        assert '"Plate"' in prepared["source"]
        assert prepared["revision"] != created["revision"]

    def test_edit_source_ambiguous_replacement_rejected(self, tmp_path: Path) -> None:
        doc = _StubDocument()
        created = _prepare_create(tmp_path, doc=doc)
        service = _stub_service(doc, tmp_path)
        with pytest.raises(vibescript.VibeScriptFailure) as excinfo:
            vibescript.prepare_execution(
                service,
                "vibescript.edit_source",
                {
                    "model_id": created["model_id"],
                    "expected_revision": created["revision"],
                    "edits": [{"old_text": "Body", "new_text": "Plate"}],
                },
            )
        assert excinfo.value.payload["failure_code"] == "SOURCE_EDIT_NOT_UNIQUE"

    def test_noop_edit_rejected(self, tmp_path: Path) -> None:
        doc = _StubDocument()
        created = _prepare_create(tmp_path, doc=doc)
        service = _stub_service(doc, tmp_path)
        with pytest.raises(vibescript.VibeScriptFailure) as excinfo:
            vibescript.prepare_execution(
                service,
                "vibescript.set_parameters",
                {
                    "model_id": created["model_id"],
                    "expected_revision": created["revision"],
                    "patch": {"width": 10.0},
                },
            )
        assert excinfo.value.payload["failure_code"] == "NO_MODEL_CHANGE"

    def test_set_parameters_merges_patch(self, tmp_path: Path) -> None:
        doc = _StubDocument()
        created = _prepare_create(tmp_path, doc=doc)
        service = _stub_service(doc, tmp_path)
        prepared = vibescript.prepare_execution(
            service,
            "vibescript.set_parameters",
            {
                "model_id": created["model_id"],
                "expected_revision": created["revision"],
                "patch": {"width": 12.5, "height": 3.0},
            },
        )
        assert prepared["parameters"] == {"width": 12.5, "height": 3.0}

    def test_edit_source_parameter_patch_adds_and_removes_in_one_call(
        self, tmp_path: Path
    ) -> None:
        """Schema+source evolution lands atomically in one prepared candidate.

        The source edit switches which parameter the program reads while the
        patch supplies the new value and null-removes the obsolete key, so no
        intermediate revision ever reads a missing parameter.
        """
        doc = _StubDocument()
        created = _prepare_create(
            tmp_path,
            doc=doc,
            source=(
                'angle = params["old_angle"]\n'
                'body = doc.addObject("PartDesign::Body", "Body")\n'
                'result = {"Body": body}\n'
            ),
            parameters={"width": 10.0, "old_angle": 15.0},
        )
        service = _stub_service(doc, tmp_path)
        prepared = vibescript.prepare_execution(
            service,
            "vibescript.edit_source",
            {
                "model_id": created["model_id"],
                "expected_revision": created["revision"],
                "edits": [
                    {
                        "old_text": 'params["old_angle"]',
                        "new_text": 'params["splitter_count"]',
                    }
                ],
                "parameter_patch": {"splitter_count": 4.0, "old_angle": None},
            },
        )
        assert prepared["parameters"] == {"width": 10.0, "splitter_count": 4.0}
        assert 'params["splitter_count"]' in prepared["source"]
        assert "old_angle" not in prepared["source"]
        assert prepared["revision"] != created["revision"]

    def test_edit_source_without_patch_leaves_parameters_untouched(
        self, tmp_path: Path
    ) -> None:
        doc = _StubDocument()
        created = _prepare_create(tmp_path, doc=doc)
        service = _stub_service(doc, tmp_path)
        prepared = vibescript.prepare_execution(
            service,
            "vibescript.edit_source",
            {
                "model_id": created["model_id"],
                "expected_revision": created["revision"],
                "edits": [
                    {
                        "old_text": '"PartDesign::Body", "Body"',
                        "new_text": '"PartDesign::Body", "Plate"',
                    }
                ],
            },
        )
        assert prepared["parameters"] == {"width": 10.0}

    def test_edit_source_empty_parameter_patch_rejected(self, tmp_path: Path) -> None:
        doc = _StubDocument()
        created = _prepare_create(tmp_path, doc=doc)
        service = _stub_service(doc, tmp_path)
        with pytest.raises(vibescript.VibeScriptFailure) as excinfo:
            vibescript.prepare_execution(
                service,
                "vibescript.edit_source",
                {
                    "model_id": created["model_id"],
                    "expected_revision": created["revision"],
                    "edits": [
                        {
                            "old_text": '"PartDesign::Body", "Body"',
                            "new_text": '"PartDesign::Body", "Plate"',
                        }
                    ],
                    "parameter_patch": {},
                },
            )
        assert excinfo.value.payload["failure_code"] == "EMPTY_PARAMETER_PATCH"
        assert "parameter_patch" in excinfo.value.payload["error"]

    def test_edit_source_non_numeric_patch_value_rejected(self, tmp_path: Path) -> None:
        doc = _StubDocument()
        created = _prepare_create(tmp_path, doc=doc)
        service = _stub_service(doc, tmp_path)
        with pytest.raises(vibescript.VibeScriptFailure) as excinfo:
            vibescript.prepare_execution(
                service,
                "vibescript.edit_source",
                {
                    "model_id": created["model_id"],
                    "expected_revision": created["revision"],
                    "edits": [
                        {
                            "old_text": '"PartDesign::Body", "Body"',
                            "new_text": '"PartDesign::Body", "Plate"',
                        }
                    ],
                    "parameter_patch": {"material": "steel"},
                },
            )
        assert excinfo.value.payload["failure_code"] == "INVALID_PARAMETERS"

    def test_unsupported_tool_rejected(self, tmp_path: Path) -> None:
        doc = _StubDocument()
        created = _prepare_create(tmp_path, doc=doc)
        service = _stub_service(doc, tmp_path)
        with pytest.raises(vibescript.VibeScriptFailure) as excinfo:
            vibescript.prepare_execution(
                service,
                "vibescript.transmogrify",
                {
                    "model_id": created["model_id"],
                    "expected_revision": created["revision"],
                },
            )
        assert excinfo.value.payload["failure_code"] == "UNSUPPORTED_VIBESCRIPT_TOOL"


# ---------------------------------------------------------------------------
# execute_prepared: synchronous lifecycle
# ---------------------------------------------------------------------------


class TestExecutePrepared:
    def test_success_is_terminal_and_commits_one_transaction(
        self, tmp_path: Path
    ) -> None:
        doc = _StubDocument()
        prepared = _prepare_create(tmp_path, doc=doc)
        payload = vibescript.execute_prepared(prepared)
        assert payload["ok"] is True
        # Terminal payload: no pending/wait markers of any kind.
        assert "status" not in payload
        assert "pending" not in payload
        assert doc.transaction_log == ["open:VibeScript model", "commit"]
        assert payload["created"] is True
        assert payload["model"]["model_id"] == prepared["model_id"]
        assert payload["outputs"][0]["key"] == "Body"
        assert payload["outputs"][0]["shape"]["solid_count"] == 1
        assert payload["execution"]["vibescript_version"]
        assert payload["cad_revision"] == "cad-revision-1"
        assert payload["stdout"] == ""

    def test_print_output_surfaces_in_success_payload(self, tmp_path: Path) -> None:
        doc = _StubDocument()
        source = (
            'print("blade count", 12)\n'
            'body = doc.addObject("PartDesign::Body", "Body")\n'
            'result = {"Body": body}\n'
        )
        prepared = _prepare_create(tmp_path, doc=doc, source=source)
        payload = vibescript.execute_prepared(prepared)
        assert payload["ok"] is True
        assert payload["stdout"] == "blade count 12\n"

    def test_print_output_surfaces_in_failure_payload(self, tmp_path: Path) -> None:
        doc = _StubDocument()
        source = 'print("progress marker")\nraise RuntimeError("boom")\n'
        prepared = _prepare_create(tmp_path, doc=doc, source=source)
        payload = vibescript.execute_prepared(prepared)
        assert payload["ok"] is False
        assert payload["observed"]["stdout"] == "progress marker\n"

    def test_banned_builtin_failure_carries_policy_hint(self, tmp_path: Path) -> None:
        doc = _StubDocument()
        # A conditionally-bound shadow must pass the static excluded-builtin
        # gate (scope-insensitive suppression), but the branch never runs so
        # the read still raises NameError at runtime — exercising the
        # runtime policy-hint path that backstops static validation.
        source = 'if False:\n    memoryview = None\nvalues = memoryview(b"x")\n'
        prepared = _prepare_create(tmp_path, doc=doc, source=source)
        payload = vibescript.execute_prepared(prepared)
        assert payload["ok"] is False
        assert payload["failure_code"] == "VIBESCRIPT_EXECUTION_FAILED"
        assert "excludes" in payload["error"]
        assert "excludes" in payload["observed"]["policy_hint"]

    def test_success_creates_tagged_container_and_mirror(self, tmp_path: Path) -> None:
        doc = _StubDocument()
        prepared = _prepare_create(tmp_path, doc=doc)
        payload = vibescript.execute_prepared(prepared)
        containers = [
            obj for obj in doc.Objects if getattr(obj, "TypeId", "") == "App::Part"
        ]
        assert len(containers) == 1
        container = containers[0]
        assert getattr(container, vibescript.PROP_MODEL_ID) == prepared["model_id"]
        assert getattr(container, vibescript.PROP_REVISION) == prepared["revision"]
        assert getattr(container, vibescript.PROP_SOURCE) == SOURCE_OK
        mirror = payload["mirror"]
        assert Path(mirror["source"]).read_text(encoding="utf-8") == SOURCE_OK
        assert Path(mirror["revision_source"]).is_file()
        manifest = Path(mirror["manifest"]).read_text(encoding="utf-8")
        assert '"state": "accepted"' in manifest

    def test_script_failure_aborts_and_rolls_back(self, tmp_path: Path) -> None:
        doc = _StubDocument()
        source = (
            'body = doc.addObject("PartDesign::Body", "Body")\n'
            'raise RuntimeError("boom")\n'
        )
        prepared = _prepare_create(tmp_path, doc=doc, source=source)
        payload = vibescript.execute_prepared(prepared)
        assert payload["ok"] is False
        assert payload["failure_code"] == "VIBESCRIPT_EXECUTION_FAILED"
        assert payload["failure_stage"] == "native_call"
        assert doc.transaction_log == ["open:VibeScript model", "abort"]
        assert doc.Objects == []
        location = payload["observed"]["failure_location"]
        assert location["line"] == 2
        assert "boom" in payload["error"]

    def test_runtime_import_error_is_execution_failure(self, tmp_path: Path) -> None:
        """A runtime ImportError (e.g. FreeCAD internals or an allowlisted
        module missing at runtime) is an execution failure, never a source
        policy violation: import policy is enforced statically.
        """
        doc = _StubDocument()
        source = (
            'import functools\nraise ImportError("runtime import machinery failed")\n'
        )
        prepared = _prepare_create(tmp_path, doc=doc, source=source)
        payload = vibescript.execute_prepared(prepared)
        assert payload["ok"] is False
        assert payload["failure_code"] == "VIBESCRIPT_EXECUTION_FAILED"
        assert payload["failure_stage"] == "native_call"
        assert payload["observed"]["exception_kind"] == "python_execution_failure"
        assert doc.transaction_log == ["open:VibeScript model", "abort"]

    def test_contract_violation_maps_to_postcondition(self, tmp_path: Path) -> None:
        doc = _StubDocument()
        source = 'body = doc.addObject("PartDesign::Body", "Body")\nresult = {}\n'
        prepared = _prepare_create(tmp_path, doc=doc, source=source)
        payload = vibescript.execute_prepared(prepared)
        assert payload["ok"] is False
        assert payload["failure_code"] == "VIBESCRIPT_CONTRACT_VIOLATION"
        assert payload["failure_stage"] == "postcondition"
        assert doc.transaction_log == ["open:VibeScript model", "abort"]

    def test_budget_trip_maps_to_budget_failure(self, tmp_path: Path) -> None:
        doc = _StubDocument()
        source = (
            "total = 0\n"
            "for index in range(1000000):\n"
            "    total = total + index\n"
            'result = {"Body": doc.addObject("PartDesign::Body", "Body")}\n'
        )
        prepared = _prepare_create(tmp_path, doc=doc, source=source)
        payload = vibescript.execute_prepared(prepared, max_operations=500)
        assert payload["ok"] is False
        assert payload["failure_code"] == "VIBESCRIPT_BUDGET_EXCEEDED"
        assert doc.transaction_log == ["open:VibeScript model", "abort"]
        assert doc.Objects == []

    def test_preexisting_object_as_output_rejected(self, tmp_path: Path) -> None:
        doc = _StubDocument()
        existing = doc.addObject("PartDesign::Body", "Existing")
        source = f'result = {{"Body": doc.getObject("{existing.Name}")}}\n'
        prepared = _prepare_create(tmp_path, doc=doc, source=source)
        payload = vibescript.execute_prepared(prepared)
        assert payload["ok"] is False
        assert payload["failure_code"] == "OUTPUT_NOT_CREATED_BY_SCRIPT"
        assert doc.transaction_log == ["open:VibeScript model", "abort"]
        assert doc.Objects == [existing]

    def test_recompute_errors_abort_commit(self, tmp_path: Path) -> None:
        doc = _StubDocument()
        errors = [
            {
                "severity": "error",
                "code": "RECOMPUTE_FAILED",
                "object": "Body",
                "message": "failed to rebuild",
            }
        ]
        prepared = _prepare_create(tmp_path, doc=doc)
        prepared["service"] = _stub_service(doc, tmp_path, diagnostics=errors)
        payload = vibescript.execute_prepared(prepared)
        assert payload["ok"] is False
        assert payload["failure_code"] == "VIBESCRIPT_COMMIT_FAILED"
        assert payload["failure_stage"] == "postcondition"
        assert doc.transaction_log == ["open:VibeScript model", "abort"]
        assert doc.Objects == []

    def test_document_change_fails_before_transaction(self, tmp_path: Path) -> None:
        doc = _StubDocument()
        prepared = _prepare_create(tmp_path, doc=doc)
        other = _StubDocument(name="Other")
        prepared["service"] = _stub_service(other, tmp_path)
        payload = vibescript.execute_prepared(prepared)
        assert payload["ok"] is False
        assert payload["failure_code"] == "DOCUMENT_CHANGED"
        assert other.transaction_log == []

    def test_cancellation_honored_before_execution(self, tmp_path: Path) -> None:
        doc = _StubDocument()
        prepared = _prepare_create(tmp_path, doc=doc)
        payload = vibescript.execute_prepared(prepared, cancellation_check=lambda: True)
        assert payload["ok"] is False
        assert payload["failure_code"] == "RUN_CANCELLED"
        assert doc.transaction_log == []

    def test_update_deletes_prior_owned_objects(self, tmp_path: Path) -> None:
        doc = _StubDocument()
        created = _prepare_create(tmp_path, doc=doc)
        first = vibescript.execute_prepared(created)
        assert first["ok"] is True
        service = _stub_service(doc, tmp_path)
        prepared = vibescript.prepare_execution(
            service,
            "vibescript.edit_source",
            {
                "model_id": created["model_id"],
                "expected_revision": created["revision"],
                "edits": [
                    {
                        "old_text": '"PartDesign::Body", "Body"',
                        "new_text": '"PartDesign::Body", "Plate"',
                    }
                ],
            },
        )
        payload = vibescript.execute_prepared(prepared)
        assert payload["ok"] is True
        assert payload["updated"] is True
        assert payload["removed_objects"]
        containers = [
            obj for obj in doc.Objects if getattr(obj, "TypeId", "") == "App::Part"
        ]
        assert len(containers) == 1
        assert getattr(containers[0], vibescript.PROP_REVISION) == prepared["revision"]

    def test_edit_source_with_parameter_patch_executes_atomically(
        self, tmp_path: Path
    ) -> None:
        """One call edits source, adds a param, retires another — one commit."""
        doc = _StubDocument()
        created = _prepare_create(
            tmp_path,
            doc=doc,
            source=(
                'angle = params["old_angle"]\n'
                'body = doc.addObject("PartDesign::Body", "Body")\n'
                'result = {"Body": body}\n'
            ),
            parameters={"width": 10.0, "old_angle": 15.0},
        )
        first = vibescript.execute_prepared(created)
        assert first["ok"] is True
        service = _stub_service(doc, tmp_path)
        prepared = vibescript.prepare_execution(
            service,
            "vibescript.edit_source",
            {
                "model_id": created["model_id"],
                "expected_revision": created["revision"],
                "edits": [
                    {
                        "old_text": 'params["old_angle"]',
                        "new_text": 'params["splitter_count"]',
                    }
                ],
                "parameter_patch": {"splitter_count": 4.0, "old_angle": None},
            },
        )
        payload = vibescript.execute_prepared(prepared)
        assert payload["ok"] is True
        assert payload["updated"] is True
        # The edited source reads the new parameter, so success proves the
        # patched params reached the executor in the same run.
        containers = [
            obj for obj in doc.Objects if getattr(obj, "TypeId", "") == "App::Part"
        ]
        assert len(containers) == 1
        persisted = json.loads(getattr(containers[0], vibescript.PROP_PARAMETERS))
        assert persisted == {"splitter_count": 4.0, "width": 10.0}
        # Exactly one transaction per run: create commit, then edit commit.
        assert doc.transaction_log == [
            "open:VibeScript model",
            "commit",
            "open:VibeScript model",
            "commit",
        ]


# ---------------------------------------------------------------------------
# record_failed_attempt / cleanup
# ---------------------------------------------------------------------------


class TestFailedAttempts:
    def test_failed_attempt_persists_failure_artifacts(self, tmp_path: Path) -> None:
        doc = _StubDocument()
        prepared = _prepare_create(
            tmp_path, doc=doc, source='raise RuntimeError("boom")\n'
        )
        payload = vibescript.execute_prepared(prepared)
        assert payload["ok"] is False
        candidate = vibescript.record_failed_attempt(prepared, payload)
        assert candidate["state"] == "draft_failed"
        attempt = Path(candidate["attempt_directory"])
        assert (attempt / "failure.json").is_file()
        assert (attempt / "model.py").is_file()
        manifest = (attempt / "manifest.json").read_text(encoding="utf-8")
        assert '"status": "failed"' in manifest

    def test_cleanup_prepared_is_safe_and_idempotent(self, tmp_path: Path) -> None:
        prepared = _prepare_create(tmp_path)
        vibescript.cleanup_prepared(prepared)
        vibescript.cleanup_prepared(prepared)
        assert "service" not in prepared


# ---------------------------------------------------------------------------
# inspect / delete / summaries
# ---------------------------------------------------------------------------


class TestInspectDelete:
    def test_inspect_after_accept_returns_model_and_outputs(
        self, tmp_path: Path
    ) -> None:
        doc = _StubDocument()
        prepared = _prepare_create(tmp_path, doc=doc)
        assert vibescript.execute_prepared(prepared)["ok"] is True
        service = _stub_service(doc, tmp_path)
        result = vibescript.inspect_model(service, prepared["model_id"])
        assert result["ok"] is True
        model = result["model"]
        assert model["model_id"] == prepared["model_id"]
        assert model["source"] == SOURCE_OK
        assert model["state"] == "accepted"
        assert model["accepted_outputs"][0]["key"] == "Body"

    def test_inspect_unknown_model_lists_available(self, tmp_path: Path) -> None:
        doc = _StubDocument()
        service = _stub_service(doc, tmp_path)
        payload = vibescript.inspect_model(service, MODEL_ID)
        assert payload["ok"] is False
        assert payload["failure_code"] == "MODEL_NOT_FOUND"
        assert payload["observed"]["available_models"] == []

    def test_delete_requires_current_revision(self, tmp_path: Path) -> None:
        doc = _StubDocument()
        prepared = _prepare_create(tmp_path, doc=doc)
        assert vibescript.execute_prepared(prepared)["ok"] is True
        service = _stub_service(doc, tmp_path)
        payload = vibescript.delete_model(
            service, prepared["model_id"], "stale", "obsolete"
        )
        assert payload["ok"] is False
        assert payload["failure_code"] == "STALE_MODEL_REVISION"

    def test_delete_removes_objects_and_artifacts(self, tmp_path: Path) -> None:
        doc = _StubDocument()
        prepared = _prepare_create(tmp_path, doc=doc)
        assert vibescript.execute_prepared(prepared)["ok"] is True
        service = _stub_service(doc, tmp_path)
        payload = vibescript.delete_model(
            service, prepared["model_id"], prepared["revision"], "obsolete"
        )
        assert payload["ok"] is True
        assert payload["deleted_objects"]
        assert doc.Objects == []
        assert not Path(payload["artifact_directory"]).exists()

    def test_model_summaries_merge_document_and_artifacts(self, tmp_path: Path) -> None:
        doc = _StubDocument()
        prepared = _prepare_create(tmp_path, doc=doc)
        assert vibescript.execute_prepared(prepared)["ok"] is True
        summaries = vibescript.model_summaries(doc, tmp_path)
        assert len(summaries) == 1
        summary = summaries[0]
        assert summary["model_id"] == prepared["model_id"]
        assert summary["state"] == "accepted"
        assert summary["object_name"]


# ---------------------------------------------------------------------------
# Editor staging
# ---------------------------------------------------------------------------


class TestEditorStaging:
    def test_stage_editor_source_creates_working_revision(self, tmp_path: Path) -> None:
        doc = _StubDocument()
        prepared = _prepare_create(tmp_path, doc=doc)
        assert vibescript.execute_prepared(prepared)["ok"] is True
        service = _stub_service(doc, tmp_path)
        new_source = SOURCE_OK + "# tweaked\n"
        staged = vibescript.stage_editor_source(
            service, prepared["model_id"], prepared["revision"], new_source
        )
        assert staged["ok"] is True and staged["changed"] is True
        directory = vibescript._model_directory(tmp_path, prepared["model_id"])
        assert (directory / "model.py").read_text(encoding="utf-8") == new_source

    def test_revert_working_to_accepted_restores_source(self, tmp_path: Path) -> None:
        doc = _StubDocument()
        prepared = _prepare_create(tmp_path, doc=doc)
        assert vibescript.execute_prepared(prepared)["ok"] is True
        service = _stub_service(doc, tmp_path)
        vibescript.stage_editor_source(
            service, prepared["model_id"], prepared["revision"], SOURCE_OK + "# x\n"
        )
        reverted = vibescript.revert_working_to_accepted(service, prepared["model_id"])
        assert reverted["ok"] is True
        assert reverted["source"] == SOURCE_OK
        assert reverted["working_revision"] == prepared["revision"]

    def test_stage_editor_source_rejects_stale_revision(self, tmp_path: Path) -> None:
        doc = _StubDocument()
        prepared = _prepare_create(tmp_path, doc=doc)
        assert vibescript.execute_prepared(prepared)["ok"] is True
        service = _stub_service(doc, tmp_path)
        with pytest.raises(vibescript.VibeScriptFailure) as excinfo:
            vibescript.stage_editor_source(
                service, prepared["model_id"], "stale", SOURCE_OK + "# x\n"
            )
        assert excinfo.value.payload["failure_code"] == "STALE_MODEL_REVISION"


# ---------------------------------------------------------------------------
# Runner API surface parity
# ---------------------------------------------------------------------------


class TestRunnerApiSurface:
    def test_engine_exposes_full_runner_api(self) -> None:
        for name in (
            "prepare_execution",
            "execute_prepared",
            "record_failed_attempt",
            "cleanup_prepared",
            "inspect_model",
            "delete_model",
            "model_summaries",
            "stage_editor_source",
            "revert_working_to_accepted",
            "restore_output_display_modes",
            "validate_source",
            "source_revision",
        ):
            assert callable(getattr(vibescript, name)), name

    def test_no_freecad_import_at_module_scope(self) -> None:
        import ast as ast_module
        import inspect

        source = inspect.getsource(vibescript)
        tree = ast_module.parse(source)
        top_level_imports: set[str] = set()
        for node in tree.body:
            if isinstance(node, ast_module.Import):
                top_level_imports.update(
                    alias.name.split(".")[0] for alias in node.names
                )
            elif isinstance(node, ast_module.ImportFrom):
                top_level_imports.add(str(node.module or "").split(".")[0])
        assert not top_level_imports & {"FreeCAD", "FreeCADGui", "Part", "Sketcher"}
