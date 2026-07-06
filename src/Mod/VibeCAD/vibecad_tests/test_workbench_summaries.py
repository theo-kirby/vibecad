# SPDX-License-Identifier: LGPL-2.1-or-later


from VibeCADCore import (
    VibeCADService,
)

from vibecad_tests.support import (
    SettingsSnapshotTestCase,
)


class TestVibeCADWorkbenchSummaries(SettingsSnapshotTestCase):
    def test_part_summary_reads_real_part_objects(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADPartSummaryTest")
        try:
            box = doc.addObject("Part::Box", "BoxForPartSummary")
            box.Label = "Readable Part Box"
            box.Length = 2
            box.Width = 3
            box.Height = 4
            doc.recompute()
            service = VibeCADService()
            summary = service.part_summary()
            self.assertEqual(summary["object_count"], 1)
            self.assertEqual(summary["objects"][0]["name"], box.Name)
            self.assertEqual(summary["objects"][0]["label"], "Readable Part Box")
            self.assertEqual(summary["objects"][0]["type"], "Part::Box")
            self.assertIn("shape", summary["objects"][0])
        finally:
            App.closeDocument(doc.Name)

    def test_document_summary_includes_shape_and_link_metadata_for_detail_features(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADDocumentDetailSummaryTest")
        try:
            base = doc.addObject("Part::Box", "DetailSummaryBase")
            base.Label = "Detail Summary Plate"
            base.Length = 30
            base.Width = 20
            base.Height = 4
            tool = doc.addObject("Part::Cylinder", "DetailSummaryHoleTool")
            tool.Label = "Detail Summary Hole Tool"
            tool.Radius = 3
            tool.Height = 10
            tool.Placement.Base.z = -3
            cut = doc.addObject("Part::Cut", "DetailSummaryCut")
            cut.Label = "Detail Summary Cut"
            cut.Base = base
            cut.Tool = tool
            doc.recompute()

            service = VibeCADService()
            summary = service.document_summary()
            cut_summary = next(
                item
                for item in summary["objects"]
                if item["name"] == cut.Name
            )
            self.assertEqual(cut_summary["type"], "Part::Cut")
            self.assertEqual(cut_summary["base"]["name"], base.Name)
            self.assertEqual(cut_summary["tool"]["name"], tool.Name)
            self.assertGreater(cut_summary["shape"]["faces"], 0)
            self.assertGreater(cut_summary["shape"]["edges"], 0)
            self.assertGreater(cut_summary["shape"]["volume"], 0.0)
            self.assertEqual(cut_summary["placement"]["base"], [0.0, 0.0, 0.0])
            self.assertIn("bound_box", cut_summary)
        finally:
            App.closeDocument(doc.Name)

    def test_document_summary_includes_material_appearance_state(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADDocumentMaterialSummaryTest")
        try:
            box = doc.addObject("Part::Box", "MaterialSummaryBox")
            box.Label = "Material Summary Box"
            service = VibeCADService()
            result = service.registry.call(
                "material.apply_appearance",
                object_name=box.Name,
                diffuse_color=[0.1, 0.4, 0.8],
                transparency=0.45,
            )
            self.assertTrue(result["ok"], result)
            summary = service.document_summary()
            box_summary = next(
                item
                for item in summary["objects"]
                if item["name"] == box.Name
            )
            self.assertEqual(box_summary["material"]["name"], "VibeCAD Appearance")
            self.assertEqual(
                box_summary["material"]["diffuse_color"],
                "(0.1000, 0.4000, 0.8000, 1.0)",
            )
            self.assertAlmostEqual(box_summary["material"]["transparency"], 0.45)
        finally:
            App.closeDocument(doc.Name)

    def test_mesh_summary_reads_real_mesh(self):
        import FreeCAD as App
        import Mesh

        doc = App.newDocument("VibeCADMeshSummaryTest")
        try:
            obj = doc.addObject("Mesh::Feature", "MeshForSummary")
            obj.Label = "Readable Mesh"
            obj.Mesh = Mesh.createBox(1.0, 2.0, 3.0)
            doc.recompute()
            service = VibeCADService()
            summary = service.mesh_summary()
            self.assertEqual(summary["object_count"], 1)
            self.assertEqual(summary["objects"][0]["name"], obj.Name)
            self.assertEqual(summary["objects"][0]["label"], "Readable Mesh")
            self.assertEqual(summary["objects"][0]["mesh"]["facets"], 12)
            self.assertIn("bound_box", summary["objects"][0]["mesh"])
        finally:
            App.closeDocument(doc.Name)

    def test_points_summary_reads_real_points(self):
        import FreeCAD as App
        import Points

        doc = App.newDocument("VibeCADPointsSummaryTest")
        try:
            obj = doc.addObject("Points::Feature", "PointsForSummary")
            obj.Label = "Readable Points"
            kernel = Points.Points()
            kernel.addPoints([
                App.Vector(0, 0, 0),
                App.Vector(1, 2, 3),
            ])
            obj.Points = kernel
            doc.recompute()
            service = VibeCADService()
            summary = service.points_summary()
            self.assertEqual(summary["object_count"], 1)
            self.assertEqual(summary["objects"][0]["name"], obj.Name)
            self.assertEqual(summary["objects"][0]["label"], "Readable Points")
            self.assertEqual(summary["objects"][0]["point_count"], 2)
            self.assertIn("bound_box", summary["objects"][0])
        finally:
            App.closeDocument(doc.Name)

    def test_material_summary_reads_shape_material_objects(self):
        import FreeCAD as App
        import Materials

        doc = App.newDocument("VibeCADMaterialSummaryTest")
        try:
            box = doc.addObject("Part::Box", "BoxForMaterialSummary")
            material = Materials.Material()
            material.Name = "Readable Material"
            material.addAppearanceModel(Materials.UUIDs().BasicRendering)
            material.setAppearanceValue("DiffuseColor", "(0.2000, 0.4000, 0.6000, 1.0)")
            material.setAppearanceValue("Transparency", "0.25")
            box.ShapeMaterial = material
            doc.recompute()
            service = VibeCADService()
            summary = service.material_summary()
            self.assertEqual(summary["object_count"], 1)
            self.assertEqual(summary["objects"][0]["name"], box.Name)
            self.assertEqual(summary["objects"][0]["material_name"], "Readable Material")
            self.assertEqual(summary["objects"][0]["diffusecolor"], "(0.2000, 0.4000, 0.6000, 1.0)")
            self.assertEqual(summary["objects"][0]["transparency"], 0.25)
        finally:
            App.closeDocument(doc.Name)

    def test_apply_material_appearance_applies_directly_for_provider_loop(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADMaterialDirectApplyTest")
        try:
            box = doc.addObject("Part::Box", "BoxForMaterialDirectApply")
            service = VibeCADService()
            result = service.registry.call(
                "material.apply_appearance",
                object_name=box.Name,
                diffuse_color=[0.7, 0.2, 0.1],
                transparency=0.35,
            )
            self.assertTrue(result["ok"], result)
            self.assertEqual(
                box.ShapeMaterial.getAppearanceValue("DiffuseColor"),
                "(0.7000, 0.2000, 0.1000, 1.0)",
            )
            self.assertAlmostEqual(float(box.ShapeMaterial.getAppearanceValue("Transparency")), 0.35)
            transaction_result = result["transaction"]["result"]
            self.assertEqual(transaction_result["object"], box.Name)
            self.assertEqual(transaction_result["diffuse_color"], "(0.7000, 0.2000, 0.1000, 1.0)")
            self.assertAlmostEqual(transaction_result["transparency"], 0.35)
        finally:
            App.closeDocument(doc.Name)

    def test_spreadsheet_summary_reads_real_sheet(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADSpreadsheetSummaryTest")
        try:
            sheet = doc.addObject("Spreadsheet::Sheet", "SheetForSummary")
            sheet.set("A1", "42")
            sheet.set("B2", "=A1")
            doc.recompute()
            service = VibeCADService()
            summary = service.spreadsheet_summary(sheet.Name)
            self.assertTrue(summary["found"])
            self.assertEqual(summary["sheet"]["name"], sheet.Name)
            cells = {item["cell"]: item for item in summary["cells"]}
            self.assertEqual(cells["A1"]["contents"], "42")
            self.assertEqual(cells["B2"]["contents"], "=A1")
        finally:
            App.closeDocument(doc.Name)

    def test_draft_summary_reads_real_draft_line(self):
        import FreeCAD as App
        import Draft

        doc = App.newDocument("VibeCADDraftSummaryTest")
        try:
            line = Draft.make_line(App.Vector(0, 0, 0), App.Vector(5, 0, 0))
            line.Label = "Readable Draft Line"
            doc.recompute()
            service = VibeCADService()
            summary = service.draft_summary()
            self.assertEqual(summary["object_count"], 1)
            self.assertEqual(summary["objects"][0]["label"], "Readable Draft Line")
        finally:
            App.closeDocument(doc.Name)

    def test_techdraw_summary_reads_real_page_template_and_view(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADTechDrawSummaryTest")
        try:
            page = doc.addObject("TechDraw::DrawPage", "PageForSummary")
            page.Label = "Readable Page"
            template = doc.addObject("TechDraw::DrawSVGTemplate", "TemplateForSummary")
            template.Label = "Readable Template"
            page.Template = template
            box = doc.addObject("Part::Box", "BoxForView")
            view = doc.addObject("TechDraw::DrawViewPart", "ViewForSummary")
            view.Label = "Readable View"
            view.Source = [box]
            page.addView(view)
            doc.recompute()
            service = VibeCADService()
            summary = service.techdraw_summary(page.Name)
            self.assertEqual(summary["page_count"], 1)
            self.assertEqual(summary["selected"]["name"], page.Name)
            self.assertEqual(summary["selected"]["label"], "Readable Page")
            self.assertEqual(summary["selected"]["template"]["name"], template.Name)
            self.assertEqual(summary["selected"]["view_count"], 1)
            self.assertEqual(summary["selected"]["views"][0]["name"], view.Name)
            self.assertEqual(summary["selected"]["views"][0]["source_count"], 1)
        finally:
            App.closeDocument(doc.Name)

    def test_create_techdraw_page_and_add_view_apply_directly_for_provider_loop(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADTechDrawDirectTest")
        try:
            box = doc.addObject("Part::Box", "BoxForDirectDrawing")
            box.Label = "Direct Drawing Source"
            doc.recompute()
            service = VibeCADService()
            page_result = service.registry.call("techdraw.create_page", label="AI Direct Drawing Page", with_template=True)
            self.assertTrue(page_result["ok"], page_result)
            page = next(
                obj for obj in doc.Objects
                if obj.isDerivedFrom("TechDraw::DrawPage")
            )
            self.assertEqual(page.Label, "AI Direct Drawing Page")
            self.assertIsNotNone(page.Template)

            view_result = service.registry.call(
                "techdraw.add_view",
                source_name="Direct Drawing Source",
                page_name="AI Direct Drawing Page",
                label="AI Direct Box View",
                x=80.0,
                y=120.0,
                scale=0.5,
            )
            self.assertTrue(view_result["ok"], view_result)
            views = list(getattr(page, "Views", []) or [])
            self.assertEqual(len(views), 1)
            view = views[0]
            self.assertEqual(view.TypeId, "TechDraw::DrawViewPart")
            self.assertEqual(view.Label, "AI Direct Box View")
            self.assertEqual(list(view.Source), [box])
            self.assertAlmostEqual(float(view.Scale), 0.5)
            summary = service.techdraw_summary(page.Name)
            self.assertEqual(summary["selected"]["view_count"], 1)
            self.assertEqual(summary["selected"]["views"][0]["source_count"], 1)
        finally:
            App.closeDocument(doc.Name)

    def test_fem_summary_reads_real_analysis(self):
        import FreeCAD as App
        import ObjectsFem

        doc = App.newDocument("VibeCADFemSummaryTest")
        try:
            analysis = ObjectsFem.makeAnalysis(doc, "AnalysisForSummary")
            analysis.Label = "Readable Analysis"
            doc.recompute()
            service = VibeCADService()
            summary = service.fem_summary(analysis.Name)
            self.assertEqual(summary["analysis_count"], 1)
            self.assertEqual(summary["selected"]["name"], analysis.Name)
            self.assertEqual(summary["selected"]["label"], "Readable Analysis")
            self.assertEqual(summary["selected"]["member_count"], 0)
        finally:
            App.closeDocument(doc.Name)

    def test_cam_summary_reads_real_job(self):
        import FreeCAD as App
        import Path.Main.Job as PathJob

        doc = App.newDocument("VibeCADCamSummaryTest")
        try:
            box = doc.addObject("Part::Box", "BoxForCam")
            job = PathJob.Create("JobForSummary", [box], None)
            job.Label = "Readable CAM Job"
            doc.recompute()
            service = VibeCADService()
            summary = service.cam_summary(job.Name)
            self.assertEqual(summary["job_count"], 1)
            self.assertEqual(summary["selected"]["name"], job.Name)
            self.assertEqual(summary["selected"]["label"], "Readable CAM Job")
            self.assertEqual(summary["selected"]["operations"]["object_count"], 0)
            self.assertGreaterEqual(summary["selected"]["tools"]["object_count"], 1)
            self.assertEqual(summary["selected"]["model"]["object_count"], 1)
        finally:
            App.closeDocument(doc.Name)

    def test_bim_summary_reads_real_building_part(self):
        import Arch
        import FreeCAD as App

        doc = App.newDocument("VibeCADBimSummaryTest")
        try:
            obj = Arch.makeBuildingPart(name="Readable BIM Part")
            obj.IfcType = "Building Element Part"
            doc.recompute()
            service = VibeCADService()
            summary = service.bim_summary()
            self.assertEqual(summary["object_count"], 1)
            self.assertEqual(summary["objects"][0]["name"], obj.Name)
            self.assertEqual(summary["objects"][0]["label"], "Readable BIM Part")
            self.assertEqual(summary["objects"][0]["ifc_type"], "Building Element Part")
            self.assertEqual(summary["ifc_type_counts"]["Building Element Part"], 1)
        finally:
            App.closeDocument(doc.Name)

    def test_inspection_summary_reads_real_inspection_feature(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADInspectionSummaryTest")
        try:
            actual = doc.addObject("Part::Box", "ActualBox")
            nominal = doc.addObject("Part::Box", "NominalBox")
            group = doc.addObject("Inspection::Group", "Inspection")
            feature = group.newObject("Inspection::Feature", "BoxInspect")
            feature.Label = "Readable Inspection"
            feature.Actual = actual
            feature.Nominals = [nominal]
            feature.SearchRadius = 0.25
            feature.Thickness = 0.1
            doc.recompute()
            service = VibeCADService()
            summary = service.inspection_summary()
            self.assertEqual(summary["group_count"], 1)
            self.assertEqual(summary["feature_count"], 1)
            self.assertGreaterEqual(summary["candidate_count"], 2)
            item = summary["features"][0]
            self.assertEqual(item["name"], feature.Name)
            self.assertEqual(item["label"], "Readable Inspection")
            self.assertEqual(item["actual"]["name"], actual.Name)
            self.assertEqual(item["nominal_count"], 1)
            self.assertEqual(item["nominals"][0]["name"], nominal.Name)
        finally:
            App.closeDocument(doc.Name)

    def test_openscad_summary_reads_relevant_objects(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADOpenSCADSummaryTest")
        try:
            box = doc.addObject("Part::Box", "BoxForOpenSCAD")
            box.Label = "OpenSCAD Candidate Box"
            doc.recompute()
            service = VibeCADService()
            summary = service.openscad_summary()
            self.assertEqual(summary["object_count"], 1)
            self.assertEqual(summary["objects"][0]["name"], box.Name)
            self.assertEqual(summary["objects"][0]["label"], "OpenSCAD Candidate Box")
            self.assertEqual(summary["objects"][0]["type"], "Part::Box")
            self.assertIn("openscad_executable_configured", summary)
        finally:
            App.closeDocument(doc.Name)

    def test_surface_summary_reads_real_surface_feature(self):
        import FreeCAD as App
        import Surface  # noqa: F401

        doc = App.newDocument("VibeCADSurfaceSummaryTest")
        try:
            feature = doc.addObject("Surface::Filling", "SurfaceForSummary")
            feature.Label = "Readable Surface"
            service = VibeCADService()
            summary = service.surface_summary()
            self.assertEqual(summary["object_count"], 1)
            self.assertEqual(summary["objects"][0]["name"], feature.Name)
            self.assertEqual(summary["objects"][0]["label"], "Readable Surface")
            self.assertEqual(summary["objects"][0]["type"], "Surface::Filling")
            self.assertIn("Surface::Filling", summary["feature_types"])
        finally:
            App.closeDocument(doc.Name)

    def test_reverseengineering_summary_reads_candidates_and_outputs(self):
        import FreeCAD as App
        import Points

        doc = App.newDocument("VibeCADReenSummaryTest")
        try:
            pts = Points.Points()
            pts.addPoints([(0, 0, 0), (1, 1, 0), (2, 0, 0), (3, -1, 0)])
            cloud = doc.addObject("Points::Feature", "CloudForReen")
            cloud.Points = pts
            spline = doc.addObject("Part::Spline", "SplineForReen")
            spline.Label = "Existing Fit"
            service = VibeCADService()
            summary = service.reverseengineering_summary()
            self.assertEqual(summary["candidate_count"], 1)
            self.assertEqual(summary["candidates"][0]["name"], cloud.Name)
            self.assertEqual(summary["reconstruction_count"], 1)
            self.assertEqual(summary["reconstructions"][0]["name"], spline.Name)
        finally:
            App.closeDocument(doc.Name)

    def test_robot_summary_reads_real_trajectory(self):
        import FreeCAD as App
        import Robot

        doc = App.newDocument("VibeCADRobotSummaryTest")
        try:
            robot = doc.addObject("Robot::RobotObject", "RobotForSummary")
            robot.Label = "Readable Robot"
            trajectory = doc.addObject("Robot::TrajectoryObject", "TrajectoryForSummary")
            trajectory.Label = "Readable Trajectory"
            traj = trajectory.Trajectory
            traj.insertWaypoints(
                Robot.Waypoint(
                    App.Placement(App.Vector(1, 2, 3), App.Rotation(App.Vector(1, 0, 0), 0)),
                    "LIN",
                    "Start",
                )
            )
            trajectory.Trajectory = traj
            service = VibeCADService()
            summary = service.robot_summary()
            self.assertEqual(summary["robot_count"], 1)
            self.assertEqual(summary["robots"][0]["label"], "Readable Robot")
            self.assertEqual(summary["trajectory_count"], 1)
            self.assertEqual(summary["trajectories"][0]["waypoint_count"], 1)
            self.assertEqual(summary["trajectories"][0]["waypoints"][0]["name"], "Start")
        finally:
            App.closeDocument(doc.Name)

    def test_meshpart_summary_reads_part_candidates_and_meshes(self):
        import FreeCAD as App
        import Mesh

        doc = App.newDocument("VibeCADMeshPartSummaryTest")
        try:
            box = doc.addObject("Part::Box", "BoxForMeshPart")
            mesh = doc.addObject("Mesh::Feature", "MeshForMeshPart")
            mesh.Mesh = Mesh.createBox(1, 1, 1)
            doc.recompute()
            service = VibeCADService()
            summary = service.meshpart_summary()
            self.assertEqual(summary["part_candidate_count"], 1)
            self.assertEqual(summary["part_candidates"][0]["name"], box.Name)
            self.assertEqual(summary["mesh_count"], 1)
            self.assertEqual(summary["meshes"][0]["name"], mesh.Name)
        finally:
            App.closeDocument(doc.Name)

    def test_large_document_summaries_are_bounded_with_truncation_metadata(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADLargeSummaryTest")
        try:
            try:
                import FreeCADGui as Gui

                Gui.activateWorkbench("PartWorkbench")
            except Exception:
                pass
            for index in range(55):
                obj = doc.addObject("Part::Box", f"LargeSummaryBox{index}")
                obj.Label = f"Large Summary Box {index}"
            doc.recompute()
            service = VibeCADService()

            document = service.document_summary()
            self.assertEqual(document["object_count"], 55)
            self.assertEqual(len(document["objects"]), document["object_limit"])
            self.assertTrue(document["objects_truncated"])
            self.assertEqual(
                document["objects_omitted"],
                document["object_count"] - len(document["objects"]),
            )

            workbench = service.workbench_object_summary("PartWorkbench")
            self.assertEqual(workbench["object_count"], 55)
            self.assertEqual(len(workbench["objects"]), workbench["object_limit"])
            self.assertTrue(workbench["objects_truncated"])
            self.assertEqual(
                workbench["objects_omitted"],
                workbench["object_count"] - len(workbench["objects"]),
            )
            context = service.context_summary()
            self.assertLess(
                len(context["document"]["objects"]),
                context["document"]["object_count"],
            )
            self.assertEqual(
                context["document"]["objects_omitted"],
                context["document"]["object_count"] - len(context["document"]["objects"]),
            )
            if context.get("workbench"):
                self.assertLess(
                    len(context["workbench_objects"]["objects"]),
                    context["workbench_objects"]["object_count"],
                )
            else:
                self.assertEqual(context["workbench_objects"]["object_count"], 0)
        finally:
            App.closeDocument(doc.Name)

    def test_object_property_summary_reads_real_object(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADObjectPropertyTest")
        try:
            box = doc.addObject("Part::Box", "BoxForProperties")
            box.Label = "Readable Box"
            service = VibeCADService()
            summary = service.object_property_summary(box.Name)
            self.assertTrue(summary["found"])
            self.assertEqual(summary["object"]["label"], "Readable Box")
            self.assertIn("Label", summary["properties"])
        finally:
            App.closeDocument(doc.Name)
