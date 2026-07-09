# SPDX-License-Identifier: LGPL-2.1-or-later
"""Tests for surface-first modeling tools and fused Draft arrays."""

from VibeCADCore import VibeCADService

from vibecad_tests.support import (
    SettingsSnapshotTestCase,
)


class TestVibeCADSurfaceModeling(SettingsSnapshotTestCase):
    def test_draft_create_wire_builds_nonplanar_bspline(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADWireTest")
        try:
            service = VibeCADService()
            result = service.registry.call(
                "draft.create_wire",
                points=[
                    {"x": 0, "y": 0, "z": 0},
                    {"x": 20, "y": 5, "z": 8},
                    {"x": 40, "y": -5, "z": 16},
                    {"x": 60, "y": 0, "z": 24},
                ],
                curve_type="bspline",
                label="Space Spine",
            )
            self.assertTrue(result["ok"], result)
            created = result["transaction"]["result"]
            self.assertEqual(created["curve_type"], "bspline")
            self.assertEqual(created["point_count"], 4)
            self.assertGreater(created["length_mm"], 60.0)
            wire = doc.getObject(created["object"])
            self.assertIsNotNone(wire)
            self.assertEqual(wire.Label, "Space Spine")
            # The points span all three axes: no sketch plane could hold this.
            bbox = wire.Shape.BoundBox
            self.assertGreater(bbox.XLength, 1.0)
            self.assertGreater(bbox.YLength, 1.0)
            self.assertGreater(bbox.ZLength, 1.0)
        finally:
            App.closeDocument(doc.Name)

    def test_draft_create_wire_rejects_degenerate_input(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADWireRejectTest")
        try:
            service = VibeCADService()
            result = service.registry.call(
                "draft.create_wire",
                points=[{"x": 1, "y": 1, "z": 1}, {"x": 1, "y": 1, "z": 1}],
            )
            self.assertFalse(result["ok"], result)
            self.assertIn("coincident", result["error"])
            result = service.registry.call(
                "draft.create_wire",
                points=[{"x": 0, "y": 0, "z": 0}],
            )
            self.assertFalse(result["ok"], result)
        finally:
            App.closeDocument(doc.Name)

    def test_surface_create_surface_geomfill_from_wires(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADGeomFillTest")
        try:
            service = VibeCADService()
            first = service.registry.call(
                "draft.create_wire",
                points=[
                    {"x": 0, "y": 0, "z": 0},
                    {"x": 30, "y": 0, "z": 5},
                    {"x": 60, "y": 0, "z": 0},
                ],
                curve_type="bspline",
                label="Leading Curve",
            )
            self.assertTrue(first["ok"], first)
            second = service.registry.call(
                "draft.create_wire",
                points=[
                    {"x": 0, "y": 40, "z": 10},
                    {"x": 30, "y": 40, "z": 18},
                    {"x": 60, "y": 40, "z": 10},
                ],
                curve_type="bspline",
                label="Trailing Curve",
            )
            self.assertTrue(second["ok"], second)
            surface = service.registry.call(
                "surface.create_surface",
                operation="geomfill",
                boundaries=[
                    {"object_name": first["transaction"]["result"]["object"]},
                    {"object_name": second["transaction"]["result"]["object"]},
                ],
                fill_type="Stretched",
                label="Blend Surface",
            )
            self.assertTrue(surface["ok"], surface)
            created = surface["transaction"]["result"]
            self.assertEqual(created["operation"], "geomfill")
            self.assertEqual(created["boundary_count"], 2)
            self.assertGreaterEqual(created["face_count"], 1)
            self.assertGreater(created["area_mm2"], 100.0)
            self.assertTrue(created["valid"])
            feature = doc.getObject(created["object"])
            self.assertIsNotNone(feature)
            self.assertEqual(feature.TypeId, "Surface::GeomFillSurface")
            # Result surfaces are discoverable through the surface summary.
            summary = service.surface_summary()
            self.assertGreaterEqual(summary["object_count"], 1)
        finally:
            App.closeDocument(doc.Name)

    def test_surface_create_surface_sections_lofts_through_curves(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADSectionsTest")
        try:
            service = VibeCADService()
            names = []
            for z, sag in ((0, 0), (25, 6), (50, 2)):
                wire = service.registry.call(
                    "draft.create_wire",
                    points=[
                        {"x": 0, "y": 0, "z": z},
                        {"x": 25, "y": sag, "z": z},
                        {"x": 50, "y": 0, "z": z},
                    ],
                    curve_type="bspline",
                    label=f"Section z{z}",
                )
                self.assertTrue(wire["ok"], wire)
                names.append(wire["transaction"]["result"]["object"])
            surface = service.registry.call(
                "surface.create_surface",
                operation="sections",
                boundaries=[{"object_name": name} for name in names],
                label="Sections Surface",
            )
            self.assertTrue(surface["ok"], surface)
            created = surface["transaction"]["result"]
            self.assertEqual(created["operation"], "sections")
            self.assertEqual(created["boundary_count"], 3)
            self.assertGreaterEqual(created["face_count"], 1)
        finally:
            App.closeDocument(doc.Name)

    def test_surface_create_surface_validates_input(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADSurfaceValidateTest")
        try:
            service = VibeCADService()
            result = service.registry.call(
                "surface.create_surface",
                operation="geomfill",
                boundaries=[{"object_name": "NoSuchCurve"}, {"object_name": "Nope"}],
            )
            self.assertFalse(result["ok"], result)
            self.assertIn("not found", result["error"])
            result = service.registry.call(
                "surface.create_surface",
                operation="sections",
                boundaries=[{"object_name": "OnlyOne"}],
            )
            self.assertFalse(result["ok"], result)
            self.assertIn("at least two", result["error"].lower())
            result = service.registry.call(
                "surface.create_surface",
                operation="warp",
                boundaries=[{"object_name": "Anything"}],
            )
            self.assertFalse(result["ok"], result)
            self.assertIn("Unknown operation", result["error"])
        finally:
            App.closeDocument(doc.Name)

    def test_part_thicken_surface_turns_surface_into_solid(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADThickenTest")
        try:
            service = VibeCADService()
            first = service.registry.call(
                "draft.create_wire",
                points=[
                    {"x": 0, "y": 0, "z": 0},
                    {"x": 40, "y": 0, "z": 6},
                    {"x": 80, "y": 0, "z": 0},
                ],
                curve_type="bspline",
                label="Skin Edge A",
            )
            self.assertTrue(first["ok"], first)
            second = service.registry.call(
                "draft.create_wire",
                points=[
                    {"x": 0, "y": 50, "z": 4},
                    {"x": 40, "y": 50, "z": 12},
                    {"x": 80, "y": 50, "z": 4},
                ],
                curve_type="bspline",
                label="Skin Edge B",
            )
            self.assertTrue(second["ok"], second)
            surface = service.registry.call(
                "surface.create_surface",
                operation="geomfill",
                boundaries=[
                    {"object_name": first["transaction"]["result"]["object"]},
                    {"object_name": second["transaction"]["result"]["object"]},
                ],
                label="Skin Surface",
            )
            self.assertTrue(surface["ok"], surface)
            surface_name = surface["transaction"]["result"]["object"]
            thick = service.registry.call(
                "part.thicken_surface",
                object_name=surface_name,
                thickness=2.0,
                label="Skin Solid",
            )
            self.assertTrue(thick["ok"], thick)
            created = thick["transaction"]["result"]
            self.assertGreaterEqual(created["solids"], 1)
            self.assertTrue(created["valid"])
            self.assertGreater(created["volume_mm3"], 100.0)
            feature = doc.getObject(created["object"])
            self.assertIsNotNone(feature)
            self.assertEqual(feature.TypeId, "Part::Offset")
        finally:
            App.closeDocument(doc.Name)

    def test_part_thicken_surface_validates_input(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADThickenValidateTest")
        try:
            service = VibeCADService()
            missing = service.registry.call(
                "part.thicken_surface", object_name="NoSuchSurface"
            )
            self.assertFalse(missing["ok"], missing)
            self.assertIn("not found", missing["error"])
            box = doc.addObject("Part::Box", "ThickenBox")
            doc.recompute()
            zero = service.registry.call(
                "part.thicken_surface", object_name=box.Name, thickness=0.0
            )
            self.assertFalse(zero["ok"], zero)
            self.assertIn("non-zero", zero["error"])
        finally:
            App.closeDocument(doc.Name)

    def test_part_cut_cylindrical_hole_requires_explicit_geometry(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADHoleCutExplicitGeometryTest")
        try:
            service = VibeCADService()
            box = doc.addObject("Part::Box", "HoleCutBox")
            box.Length = 10
            box.Width = 10
            box.Height = 10
            doc.recompute()

            before_names = {obj.Name for obj in doc.Objects}
            result = service.registry.call(
                "part.cut_cylindrical_hole",
                target_name=box.Name,
                radius=1.25,
                depth=12.0,
                x=5.0,
                y=5.0,
                z=-1.0,
            )
            self.assertFalse(result["ok"], result)
            self.assertIn("axis is required", result["error"])
            self.assertFalse(result.get("retry_same_call", True))
            self.assertEqual(before_names, {obj.Name for obj in doc.Objects})

            spec = service.registry.get("part.cut_cylindrical_hole").to_schema()
            required = set(spec["parameters"]["required"])
            self.assertTrue(
                {"target_name", "radius", "depth", "x", "y", "z", "axis"} <= required
            )
            serialized = str(spec).lower()
            self.assertNotIn("default 2", serialized)
            self.assertNotIn("default 20", serialized)
            self.assertNotIn("default z", serialized)
        finally:
            App.closeDocument(doc.Name)

    def test_part_cut_cylindrical_hole_cuts_with_explicit_geometry(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADHoleCutExplicitSuccessTest")
        try:
            service = VibeCADService()
            box = doc.addObject("Part::Box", "HoleCutBox")
            box.Length = 10
            box.Width = 10
            box.Height = 10
            doc.recompute()

            result = service.registry.call(
                "part.cut_cylindrical_hole",
                target_name=box.Name,
                radius=1.25,
                depth=12.0,
                x=5.0,
                y=5.0,
                z=-1.0,
                axis="Z",
                label="Explicit Vertical Hole",
            )
            self.assertTrue(result["ok"], result)
            created = result["transaction"]["result"]
            self.assertEqual(created["radius"], 1.25)
            self.assertEqual(created["depth"], 12.0)
            self.assertEqual(created["placement"], [5.0, 5.0, -1.0])
            self.assertEqual(created["axis"], "Z")
            cut = doc.getObject(created["object"])
            self.assertIsNotNone(cut)
            self.assertEqual(cut.TypeId, "Part::Cut")
            self.assertGreater(len(cut.Shape.Faces), 0)
            self.assertLess(cut.Shape.Volume, box.Shape.Volume)
        finally:
            App.closeDocument(doc.Name)

    def test_draft_create_array_fuse_merges_touching_copies(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADFusedArrayTest")
        try:
            service = VibeCADService()
            box = doc.addObject("Part::Box", "ArrayBrick")
            box.Length = 10
            box.Width = 10
            box.Height = 5
            doc.recompute()
            fused = service.registry.call(
                "draft.create_array",
                object_name=box.Name,
                array_type="ortho",
                number_x=3,
                number_y=1,
                number_z=1,
                interval_x=8.0,  # < Length: copies overlap and must merge
                fuse=True,
                label="Fused Brick Row",
            )
            self.assertTrue(fused["ok"], fused)
            created = fused["transaction"]["result"]
            self.assertTrue(created["fuse"])
            self.assertEqual(created["solids"], 1)
            array_obj = doc.getObject(created["object"])
            self.assertIsNotNone(array_obj)
            self.assertEqual(len(array_obj.Shape.Solids), 1)
        finally:
            App.closeDocument(doc.Name)

    def test_draft_create_array_fuse_rejects_link_arrays(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADFusedLinkArrayTest")
        try:
            service = VibeCADService()
            box = doc.addObject("Part::Box", "LinkBrick")
            doc.recompute()
            result = service.registry.call(
                "draft.create_array",
                object_name=box.Name,
                array_type="ortho",
                number_x=2,
                use_link=True,
                fuse=True,
            )
            self.assertFalse(result["ok"], result)
            self.assertIn("use_link=false", result["error"])
        finally:
            App.closeDocument(doc.Name)
