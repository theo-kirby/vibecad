# SPDX-License-Identifier: LGPL-2.1-or-later

"""Unit tests for the pure-logic layers of the VibeScript authoring library.

These run under plain pytest with no FreeCAD: constraint spec construction,
selector predicates, and parameter validation never touch a live document.
"""

from __future__ import annotations

import pytest

import vibescript_api as vs


# --------------------------------------------------------------------------
# Params
# --------------------------------------------------------------------------


class TestParams:
    def test_attribute_and_mapping_access(self) -> None:
        params = vs.Params(width=80, height=50.5)
        assert params.width == 80.0
        assert params["height"] == 50.5
        assert set(params) == {"width", "height"}
        assert len(params) == 2

    def test_unknown_parameter_lists_defined_names(self) -> None:
        params = vs.Params(width=80)
        with pytest.raises(vs.ParameterError, match="width"):
            _ = params.thickness

    def test_rejects_non_numeric_value(self) -> None:
        with pytest.raises(vs.ParameterError, match="must be a number"):
            vs.Params(width="80")

    def test_rejects_bool_value(self) -> None:
        with pytest.raises(vs.ParameterError, match="must be a number"):
            vs.Params(flag=True)

    def test_rejects_non_finite_value(self) -> None:
        with pytest.raises(vs.ParameterError, match="finite"):
            vs.Params(width=float("nan"))

    def test_rejects_underscore_name(self) -> None:
        with pytest.raises(vs.ParameterError, match="underscore"):
            vs.Params(_width=80)

    def test_immutable(self) -> None:
        params = vs.Params(width=80)
        with pytest.raises(vs.ParameterError, match="immutable"):
            params.width = 90

    def test_expression_reference(self) -> None:
        params = vs.Params(width=80)
        assert params.expression("width") == "Params.width"
        assert params.expression("width", object_name="Config") == "Config.width"
        with pytest.raises(vs.ParameterError):
            params.expression("nope")


# --------------------------------------------------------------------------
# SketchBuilder: constraint spec construction
# --------------------------------------------------------------------------


class TestSketchBuilderSpecs:
    def test_line_returns_sequential_refs(self) -> None:
        builder = vs.SketchBuilder()
        a = builder.line((0, 0), (10, 0))
        b = builder.line((10, 0), (10, 5))
        assert (a.index, b.index) == (0, 1)

    def test_line_rejects_degenerate(self) -> None:
        builder = vs.SketchBuilder()
        with pytest.raises(vs.SketchBuilderError, match="differ"):
            builder.line((1, 1), (1, 1))

    def test_polyline_auto_coincident_open(self) -> None:
        builder = vs.SketchBuilder()
        refs = builder.polyline([(0, 0), (10, 0), (10, 5)])
        assert len(refs) == 2
        kinds = [spec.kind for spec in builder.constraints]
        assert kinds == ["Coincident"]
        spec = builder.constraints[0]
        assert spec.args == (vs.GeoArg(0), vs.END, vs.GeoArg(1), vs.START)

    def test_polyline_closed_chains_back_to_start(self) -> None:
        builder = vs.SketchBuilder()
        refs = builder.polyline([(0, 0), (10, 0), (10, 5)], closed=True)
        assert len(refs) == 3
        coincidents = [
            spec for spec in builder.constraints if spec.kind == "Coincident"
        ]
        assert len(coincidents) == 3
        assert coincidents[-1].args == (
            vs.GeoArg(2),
            vs.END,
            vs.GeoArg(0),
            vs.START,
        )

    def test_polyline_needs_enough_points(self) -> None:
        builder = vs.SketchBuilder()
        with pytest.raises(vs.SketchBuilderError, match="at least 2"):
            builder.polyline([(0, 0)])
        with pytest.raises(vs.SketchBuilderError, match="at least 3"):
            builder.polyline([(0, 0), (1, 1)], closed=True)

    def test_rectangle_is_fully_constrained_by_construction(self) -> None:
        builder = vs.SketchBuilder()
        rect = builder.rectangle(80, 50, center=(40, 25))
        assert len(builder.geometry) == 4
        kinds = sorted(spec.kind for spec in builder.constraints)
        assert kinds == sorted(
            ["Coincident"] * 4
            + ["Horizontal"] * 2
            + ["Vertical"] * 2
            + ["DistanceX", "DistanceY"]
            + ["Distance"] * 2
        )
        # 4 lines x 4 DoF = 16 DoF; 4 coincident x2 + 4 h/v x1 + 4 dims = 16.
        consumed = sum(
            {
                "Coincident": 2,
                "Horizontal": 1,
                "Vertical": 1,
                "Distance": 1,
                "DistanceX": 1,
                "DistanceY": 1,
            }[spec.kind]
            for spec in builder.constraints
        )
        assert consumed == 16
        assert rect.lines == (rect.bottom, rect.right, rect.top, rect.left)

    def test_rectangle_named_dimensions(self) -> None:
        builder = vs.SketchBuilder()
        builder.rectangle(80, 50, width_name="width", height_name="height")
        names = [spec.name for spec in builder.constraints if spec.name is not None]
        assert names == ["width", "height"]

    def test_rectangle_rejects_non_positive(self) -> None:
        with pytest.raises(vs.ParameterError, match="positive"):
            vs.SketchBuilder().rectangle(0, 50)
        with pytest.raises(vs.ParameterError, match="positive"):
            vs.SketchBuilder().rectangle(80, -1)

    def test_circle_fully_constrained_by_construction(self) -> None:
        builder = vs.SketchBuilder()
        builder.circle((5, 7), 2.5, radius_name="hole_r")
        kinds = sorted(spec.kind for spec in builder.constraints)
        assert kinds == ["DistanceX", "DistanceY", "Radius"]
        radius_spec = next(
            spec for spec in builder.constraints if spec.kind == "Radius"
        )
        assert radius_spec.name == "hole_r"
        assert radius_spec.args == (vs.GeoArg(0), 2.5)

    def test_arc_records_spec_and_auto_blocks(self) -> None:
        builder = vs.SketchBuilder()
        ref = builder.arc((0, 0), 10, 30, 120)
        assert builder.geometry == (vs.ArcSpec((0.0, 0.0), 10.0, 30.0, 120.0),)
        kinds = [spec.kind for spec in builder.constraints]
        assert kinds == ["Block"]
        assert builder.constraints[0].args == (vs.GeoArg(ref.index),)

    def test_arc_rejects_degenerate_sweep(self) -> None:
        builder = vs.SketchBuilder()
        with pytest.raises(vs.SketchBuilderError, match="sweep"):
            builder.arc((0, 0), 10, 45, 45)
        with pytest.raises(vs.SketchBuilderError, match="sweep"):
            builder.arc((0, 0), 10, 0, 360)

    def test_arc_rejects_non_positive_radius(self) -> None:
        with pytest.raises(vs.ParameterError, match="positive"):
            vs.SketchBuilder().arc((0, 0), 0, 0, 90)

    def test_block_constraint(self) -> None:
        builder = vs.SketchBuilder()
        line = builder.line((0, 0), (10, 0))
        spec = builder.block(line)
        assert spec.kind == "Block"
        assert spec.args == (vs.GeoArg(0),)

    def test_fix_all_blocks_unblocked_geometry_only(self) -> None:
        builder = vs.SketchBuilder()
        builder.line((0, 0), (10, 0))
        builder.line((10, 0), (10, 5))
        builder.arc((0, 0), 5, 0, 90)  # auto-blocked
        added = builder.fix_all()
        assert [spec.args for spec in added] == [(vs.GeoArg(0),), (vs.GeoArg(1),)]
        blocks = [spec for spec in builder.constraints if spec.kind == "Block"]
        assert len(blocks) == 3
        assert builder.fix_all() == []  # idempotent

    def test_constraint_rejects_unknown_geometry(self) -> None:
        builder = vs.SketchBuilder()
        builder.line((0, 0), (10, 0))
        with pytest.raises(vs.SketchBuilderError, match="does not exist"):
            builder.horizontal(5)

    def test_no_raw_index_tuples_needed(self) -> None:
        """The rectangle + circle idiom never exposes constraint indices."""
        builder = vs.SketchBuilder()
        rect = builder.rectangle(80, 50, center=(40, 25))
        hole = builder.circle((40, 25), 2.5)
        assert isinstance(rect.bottom, vs.GeometryRef)
        assert isinstance(hole, vs.GeometryRef)
        for spec in builder.constraints:
            assert all(isinstance(arg, (vs.GeoArg, int, float)) for arg in spec.args)

    def test_resolve_constraint_args_applies_offset(self) -> None:
        spec = vs.ConstraintSpec(
            kind="Coincident",
            args=(vs.GeoArg(0), vs.END, vs.GeoArg(1), vs.START),
        )
        assert vs.resolve_constraint_args(spec, 7) == (7, vs.END, 8, vs.START)

    def test_resolve_constraint_args_keeps_values(self) -> None:
        spec = vs.ConstraintSpec(kind="Distance", args=(vs.GeoArg(2), 80.0))
        assert vs.resolve_constraint_args(spec, 10) == (12, 80.0)

    def test_distance_between_points(self) -> None:
        builder = vs.SketchBuilder()
        a = builder.line((0, 0), (10, 0))
        b = builder.line((0, 5), (10, 5))
        spec = builder.distance_between(a.start(), b.start(), 5, name="gap")
        assert spec.args == (vs.GeoArg(0), vs.START, vs.GeoArg(1), vs.START, 5.0)
        assert spec.name == "gap"

    def test_fix_point_emits_two_dimensions(self) -> None:
        builder = vs.SketchBuilder()
        a = builder.line((0, 0), (10, 0))
        x_spec, y_spec = builder.fix_point(a.start(), 1, 2)
        assert x_spec.kind == "DistanceX"
        assert y_spec.kind == "DistanceY"


# --------------------------------------------------------------------------
# Selector predicates
# --------------------------------------------------------------------------


def _box_edges() -> list[vs.EdgeFacts]:
    """Edges of an 80 x 50 x 6 box, in FreeCAD-like 1-based order."""
    facts = []
    index = 1
    # 4 vertical edges (Z direction, length 6)
    for x, y in ((0, 0), (80, 0), (80, 50), (0, 50)):
        facts.append(
            vs.EdgeFacts(
                index=index,
                curve="Line",
                length=6.0,
                midpoint=(float(x), float(y), 3.0),
                direction=(0.0, 0.0, 1.0),
            )
        )
        index += 1
    # 4 X-direction edges (length 80) at z=0 and z=6
    for y, z in ((0, 0), (50, 0), (0, 6), (50, 6)):
        facts.append(
            vs.EdgeFacts(
                index=index,
                curve="Line",
                length=80.0,
                midpoint=(40.0, float(y), float(z)),
                direction=(1.0, 0.0, 0.0),
            )
        )
        index += 1
    # 4 Y-direction edges (length 50) at z=0 and z=6
    for x, z in ((0, 0), (80, 0), (0, 6), (80, 6)):
        facts.append(
            vs.EdgeFacts(
                index=index,
                curve="Line",
                length=50.0,
                midpoint=(float(x), 25.0, float(z)),
                direction=(0.0, 1.0, 0.0),
            )
        )
        index += 1
    return facts


class TestSelectors:
    def test_is_parallel_axis_names_and_antiparallel(self) -> None:
        assert vs.is_parallel((0, 0, 1), "Z")
        assert vs.is_parallel((0, 0, -1), "Z")
        assert not vs.is_parallel((1, 0, 0), "Z")

    def test_is_perpendicular(self) -> None:
        assert vs.is_perpendicular((1, 0, 0), "Z")
        assert not vs.is_perpendicular((0, 0, 1), "Z")

    def test_unknown_axis_name_rejected(self) -> None:
        with pytest.raises(vs.SelectorError, match="unknown axis"):
            vs.is_parallel((0, 0, 1), "W")

    def test_zero_direction_rejected(self) -> None:
        with pytest.raises(vs.SelectorError, match="zero-length"):
            vs.is_parallel((0, 0, 0), "Z")

    def test_vertical_edges_of_box(self) -> None:
        query = vs.edges(_box_edges()).parallel_to("Z")
        assert query.names() == ["Edge1", "Edge2", "Edge3", "Edge4"]

    def test_top_edges_of_box(self) -> None:
        query = vs.edges(_box_edges()).perpendicular_to("Z").top()
        assert len(query) == 4
        assert all(fact.midpoint[2] == 6.0 for fact in query)

    def test_of_length_and_longest(self) -> None:
        query = vs.edges(_box_edges())
        assert len(query.of_length(80)) == 4
        assert len(query.longest()) == 4
        assert len(query.shortest()) == 4
        assert query.shortest().facts[0].length == 6.0

    def test_at_midpoint_filter(self) -> None:
        one = vs.edges(_box_edges()).at(x=0, y=0).one()
        assert one.name == "Edge1"
        with pytest.raises(vs.SelectorError, match="at least one"):
            vs.edges(_box_edges()).at()

    def test_one_raises_on_ambiguity(self) -> None:
        with pytest.raises(vs.SelectorError, match="matched 4"):
            vs.edges(_box_edges()).parallel_to("Z").one()

    def test_require_exact_count(self) -> None:
        query = vs.edges(_box_edges()).parallel_to("Z")
        assert query.require(4) is query
        with pytest.raises(vs.SelectorError, match="Expected exactly 2"):
            query.require(2)

    def test_chained_filters_compose(self) -> None:
        names = vs.edges(_box_edges()).lines().parallel_to("X").top().names()
        assert names == ["Edge7", "Edge8"]

    def test_edge_facts_from_shape_requires_edges(self) -> None:
        with pytest.raises(vs.SelectorError, match="no Edges"):
            vs.edge_facts_from_shape(object())

    def test_query_from_query_is_identity(self) -> None:
        query = vs.edges(_box_edges())
        assert vs.edges(query) is query


# --------------------------------------------------------------------------
# Feature helper validation (stub objects, no FreeCAD)
# --------------------------------------------------------------------------


class _StubFeature:
    def __init__(self, type_id: str, name: str) -> None:
        self.TypeId = type_id
        self.Name = name


class _StubBody:
    def __init__(self) -> None:
        self.created: list[_StubFeature] = []

    def newObject(self, type_id: str, name: str) -> _StubFeature:
        feature = _StubFeature(type_id, name)
        self.created.append(feature)
        return feature


class _StubOriginPlane:
    def __init__(self, role: str) -> None:
        self.Role = role
        self.Name = role


class _StubOrigin:
    def __init__(self) -> None:
        self.OriginFeatures = [
            _StubOriginPlane("XY_Plane"),
            _StubOriginPlane("XZ_Plane"),
            _StubOriginPlane("YZ_Plane"),
        ]


class _StubBodyWithOrigin(_StubBody):
    def __init__(self) -> None:
        super().__init__()
        self.Origin = _StubOrigin()


class _StubDocument:
    def __init__(self) -> None:
        self.added: list[_StubFeature] = []

    def addObject(self, type_id: str, name: str) -> _StubFeature:
        feature = _StubFeature(type_id, name)
        self.added.append(feature)
        return feature


class TestFeatureHelpers:
    def test_pad_sets_properties(self) -> None:
        body = _StubBody()
        profile = object()
        feature = vs.pad(body, profile, 6, name="BasePad", midplane=True)
        assert feature.TypeId == "PartDesign::Pad"
        assert feature.Profile is profile
        assert feature.Length == 6.0
        assert feature.Midplane is True
        assert feature.Reversed is False
        assert feature.Refine is True

    def test_pad_rejects_non_positive_length(self) -> None:
        with pytest.raises(vs.ParameterError, match="positive"):
            vs.pad(_StubBody(), object(), 0)

    def test_pocket_sets_properties(self) -> None:
        feature = vs.pocket(_StubBody(), object(), 3, reverse=True)
        assert feature.TypeId == "PartDesign::Pocket"
        assert feature.Length == 3.0
        assert feature.Reversed is True

    def test_pocket_through_all(self) -> None:
        feature = vs.pocket(_StubBody(), object(), through_all=True)
        assert feature.TypeId == "PartDesign::Pocket"
        assert feature.Type == "ThroughAll"
        assert not hasattr(feature, "Length")

    def test_pocket_through_all_rejects_length(self) -> None:
        with pytest.raises(vs.FeatureError, match="do not pass"):
            vs.pocket(_StubBody(), object(), 5, through_all=True)

    def test_pocket_requires_length_or_through_all(self) -> None:
        with pytest.raises(vs.FeatureError, match="through_all"):
            vs.pocket(_StubBody(), object())

    def test_revolve_defaults_to_profile_vertical_axis(self) -> None:
        body = _StubBody()
        profile = object()
        feature = vs.revolve(body, profile, 270)
        assert feature.TypeId == "PartDesign::Revolution"
        assert feature.Profile is profile
        assert feature.ReferenceAxis == (profile, ["V_Axis"])
        assert feature.Angle == 270.0
        assert feature.Reversed is False
        assert feature.Midplane is False
        assert feature.Refine is True

    def test_revolve_accepts_explicit_axis_tuple(self) -> None:
        datum = object()
        feature = vs.revolve(_StubBody(), object(), axis=(datum, "Edge1"))
        assert feature.ReferenceAxis == (datum, ["Edge1"])

    def test_revolve_rejects_bad_angle_and_axis(self) -> None:
        with pytest.raises(vs.FeatureError, match="angle"):
            vs.revolve(_StubBody(), object(), 0)
        with pytest.raises(vs.FeatureError, match="angle"):
            vs.revolve(_StubBody(), object(), 361)
        with pytest.raises(vs.FeatureError, match="unknown axis"):
            vs.revolve(_StubBody(), object(), axis="Q")

    def test_groove_is_subtractive_revolve(self) -> None:
        profile = object()
        feature = vs.groove(_StubBody(), profile, axis="H")
        assert feature.TypeId == "PartDesign::Groove"
        assert feature.ReferenceAxis == (profile, ["H_Axis"])
        assert feature.Angle == 360.0

    def test_loft_orders_profile_and_sections(self) -> None:
        body = _StubBody()
        a, b, c = object(), object(), object()
        feature = vs.loft(body, [a, b, c])
        assert feature.TypeId == "PartDesign::AdditiveLoft"
        assert feature.Profile is a
        assert feature.Sections == [b, c]
        assert feature.Ruled is False
        assert feature.Closed is False

    def test_loft_subtractive_variant(self) -> None:
        feature = vs.loft(_StubBody(), [object(), object()], subtractive=True)
        assert feature.TypeId == "PartDesign::SubtractiveLoft"

    def test_loft_needs_two_sections(self) -> None:
        with pytest.raises(vs.FeatureError, match="at least 2"):
            vs.loft(_StubBody(), [object()])

    def test_polar_pattern_uses_profile_normal_axis(self) -> None:
        body = _StubBody()
        sketch = object()
        original = _StubFeature("PartDesign::Pad", "Blade")
        original.Profile = sketch
        feature = vs.polar_pattern(body, original, 12)
        assert feature.TypeId == "PartDesign::PolarPattern"
        assert feature.Originals == [original]
        assert feature.Axis == (sketch, ["N_Axis"])
        assert feature.Angle == 360.0
        assert feature.Occurrences == 12

    def test_polar_pattern_unwraps_profile_tuple(self) -> None:
        sketch = object()
        original = _StubFeature("PartDesign::Pad", "Blade")
        original.Profile = (sketch, [""])
        feature = vs.polar_pattern(_StubBody(), [original], 6)
        assert feature.Axis == (sketch, ["N_Axis"])

    def test_polar_pattern_rejects_low_count_and_empty(self) -> None:
        with pytest.raises(vs.FeatureError, match="at least 2"):
            vs.polar_pattern(_StubBody(), _StubFeature("T", "F"), 1)
        with pytest.raises(vs.FeatureError, match="non-empty"):
            vs.polar_pattern(_StubBody(), [], 6)

    def test_mirror_uses_plane_reference(self) -> None:
        sketch = object()
        original = _StubFeature("PartDesign::Pad", "Rib")
        original.Profile = sketch
        feature = vs.mirror(_StubBody(), original, "V")
        assert feature.TypeId == "PartDesign::Mirrored"
        assert feature.Originals == [original]
        assert feature.MirrorPlane == (sketch, ["V_Axis"])

    def test_mirror_accepts_datum_tuple(self) -> None:
        datum = object()
        feature = vs.mirror(_StubBody(), _StubFeature("T", "F"), (datum, ""))
        assert feature.MirrorPlane == (datum, [""])

    def test_fillet_accepts_edge_query(self) -> None:
        body = _StubBody()
        base = object()
        query = vs.edges(_box_edges()).parallel_to("Z")
        feature = vs.fillet(body, base, query, 1.5)
        assert feature.TypeId == "PartDesign::Fillet"
        assert feature.Base == (base, ["Edge1", "Edge2", "Edge3", "Edge4"])
        assert feature.Radius == 1.5

    def test_fillet_rejects_empty_selection(self) -> None:
        empty = vs.edges(_box_edges()).of_length(999)
        with pytest.raises(vs.FeatureError, match="matched nothing"):
            vs.fillet(_StubBody(), object(), empty, 1.5)

    def test_fillet_rejects_non_positive_radius(self) -> None:
        with pytest.raises(vs.ParameterError, match="positive"):
            vs.fillet(_StubBody(), object(), ["Edge1"], -1)


class TestPlacementHelpers:
    def test_new_body_adds_partdesign_body(self) -> None:
        doc = _StubDocument()
        body = vs.new_body(doc, "Hub", label="Impeller hub")
        assert body.TypeId == "PartDesign::Body"
        assert body.Name == "Hub"
        assert body.Label == "Impeller hub"
        assert doc.added == [body]

    def test_new_sketch_attaches_to_origin_plane(self) -> None:
        body = _StubBodyWithOrigin()
        sketch = vs.new_sketch(body, "XZ", name="ProfileSketch")
        assert sketch.TypeId == "Sketcher::SketchObject"
        assert sketch.Name == "ProfileSketch"
        plane, subnames = sketch.Support[0]
        assert plane.Role == "XZ_Plane"
        assert subnames == [""]
        assert sketch.MapMode == "FlatFace"
        assert body.created == [sketch]

    def test_new_sketch_attaches_to_face_tuple(self) -> None:
        body = _StubBodyWithOrigin()
        pad = object()
        sketch = vs.new_sketch(body, (pad, "Face3"))
        assert sketch.Support == [(pad, ["Face3"])]

    def test_new_sketch_rejects_unknown_plane_name(self) -> None:
        with pytest.raises(vs.FeatureError, match="unknown plane"):
            vs.new_sketch(_StubBodyWithOrigin(), "AB")

    def test_new_sketch_reports_missing_origin_plane(self) -> None:
        body = _StubBody()  # no Origin attribute
        with pytest.raises(vs.FeatureError, match="origin plane"):
            vs.new_sketch(body, "XY")


# --------------------------------------------------------------------------
# Sketch validation (stub sketches, no FreeCAD)
# --------------------------------------------------------------------------


class _StubSketch:
    def __init__(
        self, *, solve_status: int = 0, fully_constrained: bool = True
    ) -> None:
        self.Name = "Sketch"
        self.FullyConstrained = fully_constrained
        self._solve_status = solve_status

    def solve(self) -> int:
        return self._solve_status


class TestAssertFullyConstrained:
    def test_passes_for_solved_constrained_sketch(self) -> None:
        vs.assert_fully_constrained(_StubSketch())

    def test_raises_on_solver_failure(self) -> None:
        with pytest.raises(vs.SketchValidationError, match="failed to solve"):
            vs.assert_fully_constrained(_StubSketch(solve_status=-2))

    def test_raises_on_remaining_dof(self) -> None:
        with pytest.raises(vs.SketchValidationError, match="not fully constrained"):
            vs.assert_fully_constrained(_StubSketch(fully_constrained=False))


# --------------------------------------------------------------------------
# End-to-end authoring shape (stub apply target, no FreeCAD)
# --------------------------------------------------------------------------


def test_import_without_freecad() -> None:
    """The library must import and build specs with no FreeCAD available."""
    import sys

    assert "vibescript_api" in sys.modules
    builder = vs.SketchBuilder()
    builder.rectangle(80, 50, width_name="width", height_name="height")
    builder.circle((0, 0), 2.5, radius_name="hole_r")
    assert len(builder.geometry) == 5
    assert all(isinstance(s.kind, str) for s in builder.constraints)
