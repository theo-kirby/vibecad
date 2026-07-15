# SPDX-License-Identifier: LGPL-2.1-or-later

"""Tests for the in-process VibeScript executor (no FreeCAD required)."""

from __future__ import annotations

import importlib
import sys
import time
import types
from typing import Any

import pytest

import vibescript_executor as vse

# --------------------------------------------------------------------------
# Stub document objects
# --------------------------------------------------------------------------


class StubBoundBox:
    XMin = 0.0
    YMin = 0.0
    ZMin = 0.0
    XMax = 10.0
    YMax = 20.0
    ZMax = 30.0
    XLength = 10.0
    YLength = 20.0
    ZLength = 30.0


class StubShape:
    def __init__(self, *, solids: int = 1, valid: bool = True) -> None:
        self.Solids = [object() for _ in range(solids)]
        self.Faces = [object() for _ in range(6)]
        self.Edges = [object() for _ in range(12)]
        self.Vertexes = [object() for _ in range(8)]
        self.Volume = 6000.0
        self.Area = 2200.0
        self.BoundBox = StubBoundBox()
        self._valid = valid

    def isValid(self) -> bool:
        return self._valid


class StubObject:
    def __init__(
        self,
        name: str,
        *,
        type_id: str = "Part::Feature",
        shape: StubShape | None = None,
        valid: bool = True,
    ) -> None:
        self.Name = name
        self.Label = name
        self.TypeId = type_id
        self.Shape = shape if shape is not None else StubShape()
        self._valid = valid

    def isValid(self) -> bool:
        return self._valid


class StubSketch:
    TypeId = "Sketcher::SketchObject"

    def __init__(
        self, name: str, *, fully_constrained: bool, solve_status: int = 0
    ) -> None:
        self.Name = name
        self.Label = name
        self.FullyConstrained = fully_constrained
        self._solve_status = solve_status

    def solve(self) -> int:
        return self._solve_status


class StubDocument:
    """Document stub with FreeCAD's transaction hooks and abort rollback."""

    def __init__(self) -> None:
        self.Objects: list[Any] = []
        self.transactions: list[tuple[str, ...]] = []
        self.recomputes = 0
        self.sketches_fully_constrained = True
        self._snapshot: list[Any] | None = None

    def openTransaction(self, name: str) -> None:
        self.transactions.append(("open", name))
        self._snapshot = list(self.Objects)

    def commitTransaction(self) -> None:
        self.transactions.append(("commit",))
        self._snapshot = None

    def abortTransaction(self) -> None:
        self.transactions.append(("abort",))
        if self._snapshot is not None:
            self.Objects = list(self._snapshot)
            self._snapshot = None

    def recompute(self) -> None:
        self.recomputes += 1

    def addObject(self, type_id: str, name: str) -> Any:
        obj: Any
        if type_id.startswith("Sketcher::"):
            obj = StubSketch(name, fully_constrained=self.sketches_fully_constrained)
        else:
            obj = StubObject(name, type_id=type_id)
        self.Objects.append(obj)
        return obj


SOURCE_OK = (
    'body = doc.addObject("PartDesign::Body", "Body")\nresult = {"Body": body}\n'
)


def run(doc: StubDocument, source: str, **kwargs: Any) -> dict[str, Any]:
    kwargs.setdefault("expected_outputs", ["Body"])
    return vse.execute_model(doc, source, **kwargs)


# --------------------------------------------------------------------------
# Import safety
# --------------------------------------------------------------------------


def test_imports_without_freecad() -> None:
    blocked = {"FreeCAD", "FreeCADGui", "Part", "Sketcher", "PartDesign"}
    names = [
        name
        for name in list(sys.modules)
        if name in blocked or name.startswith("vibescript")
    ]
    saved = {name: sys.modules.pop(name) for name in names}
    try:
        module = importlib.import_module("vibescript_executor")
        assert callable(module.execute_model)
        assert not blocked & set(sys.modules)
    finally:
        for name in list(sys.modules):
            if name.startswith("vibescript"):
                del sys.modules[name]
        sys.modules.update(saved)


# --------------------------------------------------------------------------
# Success path
# --------------------------------------------------------------------------


def test_success_returns_ok_with_shape_facts() -> None:
    doc = StubDocument()
    payload = run(doc, SOURCE_OK)
    assert payload["ok"] is True
    (output,) = payload["outputs"]
    assert output["key"] == "Body"
    assert output["object_name"] == "Body"
    facts = output["shape"]
    assert facts["valid"] is True
    assert facts["solid_count"] == 1
    assert facts["volume_mm3"] == pytest.approx(6000.0)
    assert facts["bounds_mm"]["size"] == [10.0, 20.0, 30.0]
    assert doc.recomputes == 1


def test_success_commits_transaction_and_lists_created_objects() -> None:
    doc = StubDocument()
    payload = run(doc, SOURCE_OK)
    assert payload["ok"] is True
    assert payload["created_objects"] == ["Body"]
    assert payload["transaction"] == {
        "opened": True,
        "committed": True,
        "aborted": False,
    }
    assert doc.transactions == [("open", vse.TRANSACTION_NAME), ("commit",)]
    assert payload["budget"]["operations_used"] > 0


def test_environment_injection() -> None:
    doc = StubDocument()
    extra = StubObject("Extra")
    payload = run(
        doc,
        'result = {"Body": extra}\n',
        environment={"extra": extra},
    )
    assert payload["ok"] is True
    assert payload["outputs"][0]["object_name"] == "Extra"


def test_params_available_in_source() -> None:
    doc = StubDocument()
    source = (
        'body = doc.addObject("PartDesign::Body", "Body")\n'
        "assert params.width == 42.0\n"
        'result = {"Body": body}\n'
    )
    payload = run(doc, source, parameters={"width": 42})
    assert payload["ok"] is True


def test_allowed_stdlib_import_works() -> None:
    doc = StubDocument()
    source = (
        "import math\n"
        'body = doc.addObject("PartDesign::Body", "Body")\n'
        "assert math.pi > 3\n"
        'result = {"Body": body}\n'
    )
    payload = run(doc, source)
    assert payload["ok"] is True


# --------------------------------------------------------------------------
# Failure path: aborted transaction, failure location
# --------------------------------------------------------------------------


def test_failing_source_reports_location_and_aborts() -> None:
    doc = StubDocument()
    payload = run(doc, 'x = 1\nraise ValueError("boom")\n')
    assert payload["ok"] is False
    assert payload["exception_type"] == "ValueError"
    assert payload["error"] == "boom"
    assert payload["failure_location"]["line"] == 2
    assert payload["failure_location"]["source"] == 'raise ValueError("boom")'
    assert payload["transaction"] == {
        "opened": True,
        "committed": False,
        "aborted": True,
    }
    assert ("abort",) in doc.transactions
    assert ("commit",) not in doc.transactions


def test_failing_source_rolls_back_document_objects() -> None:
    doc = StubDocument()
    source = (
        'body = doc.addObject("PartDesign::Body", "Body")\n'
        'raise RuntimeError("late failure")\n'
    )
    payload = run(doc, source)
    assert payload["ok"] is False
    assert doc.Objects == []


def test_syntax_error_reported_without_transaction() -> None:
    doc = StubDocument()
    payload = run(doc, "def broken(:\n")
    assert payload["ok"] is False
    assert payload["exception_kind"] == "syntax_error"
    assert payload["failure_location"]["line"] == 1
    assert payload["transaction"]["opened"] is False
    assert doc.transactions == []


def test_freecad_internal_import_during_addobject_succeeds() -> None:
    """Regression: FreeCAD internals resolve ``__import__`` from the script
    frame's builtins (e.g. ViewProvider attachment importing ``PartDesignGui``
    during ``doc.addObject``). The namespace must expose the real import so
    those internal imports succeed even for non-allowlisted Gui modules.
    """
    fake_gui = types.ModuleType("FakePartDesignGui")
    sys.modules["FakePartDesignGui"] = fake_gui

    class GuiImportingDocument(StubDocument):
        def addObject(self, type_id: str, name: str) -> Any:
            importer = sys._getframe(1).f_builtins["__import__"]
            module = importer("FakePartDesignGui")
            assert module is fake_gui
            return super().addObject(type_id, name)

    try:
        doc = GuiImportingDocument()
        payload = run(doc, SOURCE_OK)
        assert payload["ok"] is True
    finally:
        del sys.modules["FakePartDesignGui"]


def test_runtime_import_error_is_python_execution_failure() -> None:
    """Import policy is static; a runtime ImportError is an ordinary
    execution failure, not a policy violation.
    """
    doc = StubDocument()
    payload = run(doc, "import vibecad_module_that_does_not_exist\n")
    assert payload["ok"] is False
    assert payload["exception_kind"] == "python_execution_failure"
    assert "vibecad_module_that_does_not_exist" in payload["error"]
    assert ("abort",) in doc.transactions


def test_invalid_parameter_fails_before_transaction() -> None:
    doc = StubDocument()
    payload = run(doc, SOURCE_OK, parameters={"class": 1})
    assert payload["ok"] is False
    assert payload["exception_type"] == "ParameterError"
    assert doc.transactions == []


def test_keyboard_interrupt_aborts_and_propagates() -> None:
    doc = StubDocument()

    def boom() -> None:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run(doc, "boom()\n", environment={"boom": boom})
    assert ("abort",) in doc.transactions


# --------------------------------------------------------------------------
# Contract violations
# --------------------------------------------------------------------------


def test_missing_result_is_contract_violation() -> None:
    doc = StubDocument()
    payload = run(doc, "x = 1\n")
    assert payload["ok"] is False
    assert payload["exception_kind"] == "contract_violation"
    assert "must assign a non-empty dict" in payload["error"]
    assert ("abort",) in doc.transactions


def test_missing_output_body_is_contract_violation() -> None:
    doc = StubDocument()
    payload = run(doc, 'result = {"Body": 42}\n')
    assert payload["ok"] is False
    assert payload["exception_kind"] == "contract_violation"
    assert "missing an output body" in payload["error"]
    assert "int" in payload["error"]


def test_output_key_mismatch_is_contract_violation() -> None:
    doc = StubDocument()
    source = (
        'body = doc.addObject("PartDesign::Body", "Body")\nresult = {"Other": body}\n'
    )
    payload = run(doc, source)
    assert payload["ok"] is False
    assert payload["exception_kind"] == "contract_violation"
    assert "must exactly match expected_outputs" in payload["error"]


def test_unsolved_sketch_is_contract_violation() -> None:
    doc = StubDocument()
    doc.sketches_fully_constrained = False
    source = (
        'sketch = doc.addObject("Sketcher::SketchObject", "Profile")\n'
        'body = doc.addObject("PartDesign::Body", "Body")\n'
        'result = {"Body": body}\n'
    )
    payload = run(doc, source)
    assert payload["ok"] is False
    assert payload["exception_kind"] == "contract_violation"
    assert "not fully constrained" in payload["error"]
    assert "Profile" in payload["error"]
    assert doc.Objects == []


def test_multi_solid_output_is_contract_violation() -> None:
    doc = StubDocument()
    weird = StubObject("Weird", shape=StubShape(solids=2))
    payload = run(doc, 'result = {"Body": weird}\n', environment={"weird": weird})
    assert payload["ok"] is False
    assert payload["exception_kind"] == "contract_violation"
    assert "exactly one solid" in payload["error"]


def test_invalid_shape_is_contract_violation() -> None:
    doc = StubDocument()
    broken = StubObject("Broken", shape=StubShape(valid=False))
    payload = run(doc, 'result = {"Body": broken}\n', environment={"broken": broken})
    assert payload["ok"] is False
    assert payload["exception_kind"] == "contract_violation"
    assert "invalid shape" in payload["error"]


# --------------------------------------------------------------------------
# Execution budget
# --------------------------------------------------------------------------


def test_runaway_loop_trips_operation_budget() -> None:
    doc = StubDocument()
    started = time.monotonic()
    payload = run(doc, "while True:\n    pass\n", max_operations=5000)
    elapsed = time.monotonic() - started
    assert payload["ok"] is False
    assert payload["exception_kind"] == "execution_budget_exceeded"
    assert "traced operations" in payload["error"]
    assert elapsed < 5.0
    assert ("abort",) in doc.transactions


def test_default_budget_constants() -> None:
    # 120s wall clock: the budget covers native FreeCAD recompute time, and
    # multi-boolean models legitimately exceed the old 30s ceiling.
    assert vse.DEFAULT_MAX_SECONDS == 120.0
    assert vse.DEFAULT_MAX_OPERATIONS == 5_000_000


def test_wall_clock_budget_trips() -> None:
    doc = StubDocument()
    started = time.monotonic()
    payload = run(
        doc,
        "while True:\n    x = 1\n",
        max_operations=10**9,
        max_seconds=0.1,
    )
    elapsed = time.monotonic() - started
    assert payload["ok"] is False
    assert payload["exception_kind"] == "execution_budget_exceeded"
    assert "seconds" in payload["error"]
    assert "recompute" in payload["error"]
    assert elapsed < 5.0


def test_budget_survives_bare_except_swallow() -> None:
    doc = StubDocument()
    source = (
        'try:\n    while True:\n        pass\nexcept:\n    pass\nresult = {"Body": 1}\n'
    )
    payload = run(doc, source, max_operations=5000)
    assert payload["ok"] is False
    assert payload["exception_kind"] == "execution_budget_exceeded"
    assert ("abort",) in doc.transactions


def test_budget_reported_on_success() -> None:
    doc = StubDocument()
    payload = run(doc, SOURCE_OK, max_operations=5000, max_seconds=5.0)
    assert payload["ok"] is True
    assert payload["budget"]["max_operations"] == 5000
    assert 0 < payload["budget"]["operations_used"] <= 5000


def test_invalid_budget_arguments_raise() -> None:
    doc = StubDocument()
    with pytest.raises(ValueError):
        run(doc, SOURCE_OK, max_operations=0)
    with pytest.raises(ValueError):
        run(doc, SOURCE_OK, max_seconds=0.0)


# --------------------------------------------------------------------------
# stdout capture and sandbox self-explanation
# --------------------------------------------------------------------------


def test_print_output_captured_on_success() -> None:
    doc = StubDocument()
    source = (
        'print("hub radius", 12.5)\n'
        'print("blades:", 12, sep="=")\n'
        'body = doc.addObject("PartDesign::Body", "Body")\n'
        'result = {"Body": body}\n'
    )
    payload = run(doc, source)
    assert payload["ok"] is True
    assert payload["stdout"] == "hub radius 12.5\nblades:=12\n"


def test_print_output_captured_on_failure() -> None:
    doc = StubDocument()
    source = 'print("about to fail")\nraise RuntimeError("boom")\n'
    payload = run(doc, source)
    assert payload["ok"] is False
    assert payload["stdout"] == "about to fail\n"


def test_stdout_empty_string_when_nothing_printed() -> None:
    doc = StubDocument()
    payload = run(doc, SOURCE_OK)
    assert payload["ok"] is True
    assert payload["stdout"] == ""


def test_stdout_is_bounded() -> None:
    doc = StubDocument()
    source = (
        "for index in range(5000):\n"
        '    print("x" * 100)\n'
        'result = {"Body": doc.addObject("PartDesign::Body", "Body")}\n'
    )
    payload = run(doc, source)
    assert payload["ok"] is True
    assert len(payload["stdout"]) <= vse.MAX_STDOUT_CHARS + 100
    assert "[stdout truncated at" in payload["stdout"]


def test_print_does_not_write_to_real_stdout(
    capsys: pytest.CaptureFixture[str],
) -> None:
    doc = StubDocument()
    source = (
        'print("sandboxed")\n'
        'result = {"Body": doc.addObject("PartDesign::Body", "Body")}\n'
    )
    payload = run(doc, source)
    assert payload["ok"] is True
    captured = capsys.readouterr()
    assert "sandboxed" not in captured.out


def test_introspection_builtins_usable() -> None:
    doc = StubDocument()
    source = (
        'body = doc.addObject("PartDesign::Body", "Body")\n'
        "print(type(body).__name__)\n"
        'print(hasattr(body, "Shape"))\n'
        'print("Name" in dir(body))\n'
        "print(repr(1.5))\n"
        "try:\n"
        "    body.NoSuchAttribute\n"
        "except AttributeError:\n"
        '    print("caught")\n'
        'result = {"Body": body}\n'
    )
    payload = run(doc, source)
    assert payload["ok"] is True, payload.get("error")
    assert payload["stdout"] == "StubObject\nTrue\nTrue\n1.5\ncaught\n"


def test_banned_builtin_nameerror_carries_policy_hint() -> None:
    doc = StubDocument()
    payload = run(doc, "handle = open('/tmp/f')\n")
    assert payload["ok"] is False
    assert payload["exception_type"] == "NameError"
    assert "excludes" in payload["error"]
    assert "vibescript_api" in payload["policy_hint"]


def test_ordinary_typo_nameerror_has_no_policy_hint() -> None:
    doc = StubDocument()
    payload = run(doc, "value = not_a_real_name\n")
    assert payload["ok"] is False
    assert payload["exception_type"] == "NameError"
    assert "policy_hint" not in payload
    assert "excludes" not in payload["error"]


# --------------------------------------------------------------------------
# Shape facts
# --------------------------------------------------------------------------


def test_shape_facts_extraction() -> None:
    facts = vse.shape_facts(StubShape())
    assert facts["valid"] is True
    assert facts["solid_count"] == 1
    assert facts["face_count"] == 6
    assert facts["edge_count"] == 12
    assert facts["vertex_count"] == 8
    assert facts["volume_mm3"] == pytest.approx(6000.0)
    assert facts["surface_area_mm2"] == pytest.approx(2200.0)
    assert facts["bounds_mm"]["min"] == [0.0, 0.0, 0.0]
    assert facts["bounds_mm"]["max"] == [10.0, 20.0, 30.0]


def test_shape_facts_tolerates_minimal_shape() -> None:
    class Minimal:
        Solids = [object()]

    facts = vse.shape_facts(Minimal())
    assert facts == {"solid_count": 1}


def test_shape_facts_prefers_optimal_bounding_box() -> None:
    class TightBox(StubBoundBox):
        XMax = 9.5
        XLength = 9.5

    class BSplineShape(StubShape):
        def optimalBoundingBox(self) -> TightBox:
            return TightBox()

    facts = vse.shape_facts(BSplineShape())
    assert facts["bounds_mm"]["max"] == [9.5, 20.0, 30.0]
    assert facts["bounds_mm"]["size"] == [9.5, 20.0, 30.0]


def test_shape_facts_falls_back_when_optimal_box_fails() -> None:
    class BrittleShape(StubShape):
        def optimalBoundingBox(self) -> None:
            raise RuntimeError("cannot compute tight box")

    facts = vse.shape_facts(BrittleShape())
    assert facts["bounds_mm"]["max"] == [10.0, 20.0, 30.0]


def test_namespace_exposes_new_feature_helpers() -> None:
    doc = StubDocument()
    payload = run(
        doc,
        "names = sorted(n for n in dir() if not n.startswith('_'))\n"
        "print(*names)\n" + SOURCE_OK,
    )
    assert payload["ok"] is True
    exposed = set(payload["stdout"].split())
    expected = {
        "ArcSpec",
        "groove",
        "loft",
        "mirror",
        "new_body",
        "new_sketch",
        "polar_pattern",
        "revolve",
    }
    missing = expected - exposed
    assert not missing, f"missing from namespace: {sorted(missing)}"


# --------------------------------------------------------------------------
# BOPCheck (deep OCCT validity) and per-feature failure evidence
# --------------------------------------------------------------------------


class CheckedShape(StubShape):
    """Shape whose deep OCCT check (``check(True)``) passes."""

    def check(self, bop: bool = False) -> None:
        del bop


class DefectiveShape(StubShape):
    """Shape that passes ``isValid`` but fails the BOPCheck.

    Mirrors the silently-corrupt booleans OCCT produces from tangent face
    contact or plane faces piercing spline surfaces: recompute reports a
    clean state and only ``Shape.check(True)`` sees the defect.
    """

    def check(self, bop: bool = False) -> None:
        del bop
        raise ValueError("BOPAlgo SelfIntersect: shell is unorientable")


class BopDocument(StubDocument):
    """Document whose non-sketch objects carry BOP-checkable shapes.

    Objects named ``Bad*`` get a defective shape; everything else passes.
    """

    def addObject(self, type_id: str, name: str) -> Any:
        obj = super().addObject(type_id, name)
        if not type_id.startswith("Sketcher::"):
            obj.Shape = DefectiveShape() if name.startswith("Bad") else CheckedShape()
        return obj


def test_bop_check_passes_healthy_shape() -> None:
    assert vse.bop_check(CheckedShape()) == (True, None)


def test_bop_check_reports_defect_detail() -> None:
    ok, detail = vse.bop_check(DefectiveShape())
    assert ok is False
    assert "SelfIntersect" in (detail or "")


def test_bop_check_unknown_for_shapes_without_check() -> None:
    assert vse.bop_check(StubShape()) == (None, None)


def test_bop_check_unknown_for_null_shape() -> None:
    class NullShape(CheckedShape):
        def isNull(self) -> bool:
            return True

    assert vse.bop_check(NullShape()) == (None, None)


def test_bop_defective_output_rejected_despite_clean_recompute() -> None:
    # The 130k-mm3-missing incident: a defective boolean that recomputes
    # "successfully" must never be accepted as an output.
    doc = BopDocument()
    source = 'bad = doc.addObject("Part::Feature", "Bad")\nresult = {"Body": bad}\n'
    payload = run(doc, source)
    assert payload["ok"] is False
    assert payload["exception_kind"] == "contract_violation"
    assert "BOPCheck" in payload["error"]
    assert doc.transactions == [("open", vse.TRANSACTION_NAME), ("abort",)]
    # Even the contract rejection carries the per-feature evidence.
    assert payload["feature_report"]["first_defective"] == "Bad"


def test_failure_payload_attributes_first_defective_feature() -> None:
    # A defective feature computes cleanly and the *next* feature fails;
    # the report must point at the true culprit, not the downstream victim.
    doc = BopDocument()
    source = (
        'good = doc.addObject("Part::Feature", "Good")\n'
        'bad = doc.addObject("Part::Feature", "Bad")\n'
        'raise RuntimeError("downstream victim")\n'
    )
    payload = run(doc, source)
    assert payload["ok"] is False
    report = payload["feature_report"]
    assert report["first_defective"] == "Bad"
    by_name = {entry["object_name"]: entry for entry in report["features"]}
    assert list(by_name) == ["Good", "Bad"]  # creation order preserved
    assert by_name["Good"]["bop_ok"] is True
    assert by_name["Good"]["defective"] is False
    assert by_name["Bad"]["bop_ok"] is False
    assert by_name["Bad"]["defective"] is True
    assert "SelfIntersect" in by_name["Bad"]["bop_errors"]
    # isValid stayed clean: the defect is only visible to the BOPCheck.
    assert by_name["Bad"]["is_valid"] is True


def test_feature_report_collected_before_abort_rollback() -> None:
    # StubDocument.abortTransaction restores the object list snapshotted at
    # openTransaction, destroying the created objects exactly like FreeCAD's
    # rollback. The report can only mention the created feature if it was
    # collected BEFORE the abort; collecting after would find no new objects
    # and omit the key entirely.
    doc = StubDocument()
    source = (
        'body = doc.addObject("Part::Feature", "Victim")\nraise RuntimeError("boom")\n'
    )
    payload = run(doc, source)
    assert payload["ok"] is False
    names = [entry["object_name"] for entry in payload["feature_report"]["features"]]
    assert names == ["Victim"]
    assert doc.Objects == []  # rollback still ran after collection
    assert doc.transactions == [("open", vse.TRANSACTION_NAME), ("abort",)]


def test_success_payload_carries_no_feature_report() -> None:
    doc = StubDocument()
    payload = run(doc, SOURCE_OK)
    assert payload["ok"] is True
    assert "feature_report" not in payload
