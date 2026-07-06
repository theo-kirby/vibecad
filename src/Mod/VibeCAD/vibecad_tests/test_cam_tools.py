# SPDX-License-Identifier: LGPL-2.1-or-later
"""Tests for the cam.* machining service tools.

Covers the machine-validated machining chain: machine definition, job
setup, tool controllers with RPM pre-validation, operation creation,
machine safety validation, and gated G-code post-processing.
OpenCamLib-dependent tests skip when the runtime is unavailable.
"""

import os
import tempfile

from VibeCADCore import VibeCADService

from vibecad_tests.support import SettingsSnapshotTestCase


def _opencamlib_available() -> bool:
    try:
        import ocl  # noqa: F401

        return True
    except ImportError:
        try:
            import opencamlib  # noqa: F401

            return True
        except ImportError:
            return False


class TestVibeCADCAMTools(SettingsSnapshotTestCase):
    """Machine-validated machining workflow through the service registry."""

    def setUp(self):
        super().setUp()
        from Machine.models import MachineFactory

        # Isolate machine configuration storage so tests never touch user assets.
        self._old_config_dir = MachineFactory._config_dir  # noqa: SLF001 - test fixture
        self._tmpdir = tempfile.TemporaryDirectory(prefix="vibecad_cam_test_")
        MachineFactory.set_config_directory(self._tmpdir.name)

    def tearDown(self):
        from Machine.models import MachineFactory

        MachineFactory._config_dir = self._old_config_dir  # noqa: SLF001 - test fixture
        self._tmpdir.cleanup()
        super().tearDown()

    # -- helpers ---------------------------------------------------------

    def _define_machine(
        self,
        service,
        name="Test Mill",
        *,
        max_rpm=20000,
        postprocessor="linuxcnc",
        output_tlo=True,
    ):
        result = service.registry.call(
            "cam.define_machine",
            name=name,
            linear_axes=[
                {"name": "X", "min_limit": -300, "max_limit": 300, "max_velocity": 4000},
                {"name": "Y", "min_limit": -300, "max_limit": 300, "max_velocity": 4000},
                {"name": "Z", "min_limit": -150, "max_limit": 150, "max_velocity": 1500},
            ],
            spindle={
                "name": "Spindle",
                "max_rpm": max_rpm,
                "min_rpm": 100,
                "max_power_kw": 2.0,
            },
            postprocessor=postprocessor,
            output_tool_length_offset=output_tlo,
        )
        self.assertTrue(result["ok"], result)
        return result

    def _build_job(self, service, doc, machine_name="Test Mill", box_name="CAMBox"):
        box = doc.addObject("Part::Box", box_name)
        box.Length = 50
        box.Width = 50
        box.Height = 10
        doc.recompute()
        result = service.registry.call(
            "cam.create_job",
            model_names=[box.Name],
            machine_name=machine_name,
            stock_extension=1.0,
        )
        self.assertTrue(result["ok"], result)
        job = doc.getObject(result["job"])
        self.assertIsNotNone(job)
        # Remove default tool controllers for deterministic tool numbering.
        for tc in list(job.Tools.Group):
            doc.removeObject(tc.Name)
        doc.recompute()
        return job

    def _add_endmill(self, service, job, *, spindle_speed=12000, tool_length_offset=0):
        result = service.registry.call(
            "cam.add_tool",
            job_name=job.Name,
            label="TC: 6mm Endmill",
            tool_number=1,
            diameter=6.0,
            spindle_speed=spindle_speed,
            horiz_feed=1000,
            vert_feed=250,
            tool_length_offset=tool_length_offset,
        )
        self.assertTrue(result["ok"], result)
        return result

    # -- machine definition ----------------------------------------------

    def test_define_machine_saves_and_is_reloadable(self):
        from Machine.models import MachineFactory

        service = VibeCADService()
        result = self._define_machine(service, name="Probe Router", max_rpm=24000)
        self.assertTrue(str(result["saved_path"]).endswith(".fcm"))
        machine = result["machine"]
        self.assertEqual(set(machine["linear_axes"]), {"X", "Y", "Z"})
        self.assertEqual(machine["toolheads"][0]["max_rpm"], 24000)
        loaded = MachineFactory.get_machine("Probe Router")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.name, "Probe Router")

    def test_define_machine_validates_input(self):
        service = VibeCADService()
        missing_name = service.registry.call("cam.define_machine", name="")
        self.assertFalse(missing_name["ok"], missing_name)
        self.assertTrue(missing_name["recoverable"])
        bad_axis = service.registry.call(
            "cam.define_machine",
            name="Bad Axis Machine",
            linear_axes=[{"name": "Q", "min_limit": 0, "max_limit": 100}],
        )
        self.assertFalse(bad_axis["ok"], bad_axis)
        self.assertIn("Q", bad_axis["error"])
        self.assertTrue(bad_axis["recoverable"])

    # -- job setup ---------------------------------------------------------

    def test_create_job_binds_machine_and_applies_stock(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADCAMJobTest")
        try:
            service = VibeCADService()
            self._define_machine(service)
            job = self._build_job(service, doc)
            self.assertEqual(str(job.Machine), "Test Mill")
            stock = job.Stock
            self.assertIsNotNone(stock)
            self.assertAlmostEqual(float(stock.ExtXpos.Value), 1.0)
            # Job summaries expose the machine binding for contract gating.
            summary = service.cam_summary()
            self.assertGreaterEqual(summary["job_count"], 1)
            entry = summary["jobs"][0]
            self.assertEqual(entry["machine"], "Test Mill")
            self.assertIn("postprocessor", entry)
        finally:
            App.closeDocument(doc.Name)

    def test_create_job_unknown_machine_is_recoverable(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADCAMJobMissingMachineTest")
        try:
            service = VibeCADService()
            box = doc.addObject("Part::Box", "Box")
            doc.recompute()
            result = service.registry.call(
                "cam.create_job",
                model_names=[box.Name],
                machine_name="No Such Machine",
            )
            self.assertFalse(result["ok"], result)
            self.assertTrue(result["recoverable"])
            self.assertIn("available_machines", result)
        finally:
            App.closeDocument(doc.Name)

    # -- tool controllers --------------------------------------------------

    def test_add_tool_sets_feeds_speeds_and_tool_number(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADCAMAddToolTest")
        try:
            service = VibeCADService()
            self._define_machine(service)
            job = self._build_job(service, doc)
            result = self._add_endmill(service, job, spindle_speed=18000)
            tc_info = result["tool_controller"]
            self.assertEqual(tc_info["tool_number"], 1)
            self.assertEqual(tc_info["spindle_speed"], 18000)
            self.assertAlmostEqual(tc_info["tool"]["diameter"], 6.0)
        finally:
            App.closeDocument(doc.Name)

    def test_add_tool_rejects_spindle_speed_over_machine_limit(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADCAMOverRPMTest")
        try:
            service = VibeCADService()
            self._define_machine(service, max_rpm=20000)
            job = self._build_job(service, doc)
            self._add_endmill(service, job)
            result = service.registry.call(
                "cam.add_tool",
                job_name=job.Name,
                label="TC: too fast",
                tool_number=2,
                spindle_speed=99999,
            )
            self.assertFalse(result["ok"], result)
            self.assertTrue(result["recoverable"])
            self.assertIn("20000", result["error"])
            # No controller was created for the rejected request.
            self.assertEqual(len(list(job.Tools.Group)), 1)
        finally:
            App.closeDocument(doc.Name)

    # -- operations ----------------------------------------------------------

    def test_create_operation_profile_generates_toolpath(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADCAMProfileTest")
        try:
            service = VibeCADService()
            self._define_machine(service)
            job = self._build_job(service, doc)
            self._add_endmill(service, job)
            result = service.registry.call(
                "cam.create_operation",
                operation_type="profile",
                job_name=job.Name,
                label="Profile Outside",
            )
            self.assertTrue(result["ok"], result)
            self.assertGreater(result["command_count"], 0)
            op = doc.getObject(result["operation"])
            self.assertIsNotNone(op)
            self.assertEqual(op.Label, "Profile Outside")
        finally:
            App.closeDocument(doc.Name)

    def test_create_operation_unknown_type_is_recoverable(self):
        service = VibeCADService()
        result = service.registry.call("cam.create_operation", operation_type="lathe")
        self.assertFalse(result["ok"], result)
        self.assertTrue(result["recoverable"])
        self.assertIn("lathe", result["error"])

    def test_create_operation_requires_tool_controller(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADCAMNoToolTest")
        try:
            service = VibeCADService()
            self._define_machine(service)
            job = self._build_job(service, doc)
            result = service.registry.call(
                "cam.create_operation",
                operation_type="profile",
                job_name=job.Name,
            )
            self.assertFalse(result["ok"], result)
            self.assertTrue(result["recoverable"])
            next_tools = [item["tool"] for item in result.get("next_actions", [])]
            self.assertIn("cam.add_tool", next_tools)
        finally:
            App.closeDocument(doc.Name)

    def test_surface_operation_generates_commands_with_opencamlib(self):
        if not _opencamlib_available():
            self.skipTest("OpenCamLib runtime (ocl/opencamlib) unavailable")
        import FreeCAD as App

        doc = App.newDocument("VibeCADCAMSurfaceTest")
        try:
            service = VibeCADService()
            self._define_machine(service)
            job = self._build_job(service, doc)
            self._add_endmill(service, job)
            result = service.registry.call(
                "cam.create_operation",
                operation_type="surface",
                job_name=job.Name,
                label="3D Surface",
            )
            self.assertTrue(result["ok"], result)
            self.assertGreater(result["command_count"], 0)
        finally:
            App.closeDocument(doc.Name)

    def test_surface_operation_without_opencamlib_reports_dependency(self):
        if _opencamlib_available():
            self.skipTest("OpenCamLib is installed; missing-dependency path unreachable")
        service = VibeCADService()
        result = service.registry.call("cam.create_operation", operation_type="surface")
        self.assertFalse(result["ok"], result)
        self.assertTrue(result["recoverable"])
        self.assertIn("opencamlib", result["error"].lower())

    # -- validation and postprocess -------------------------------------------

    def test_validate_job_passes_clean_job_and_flags_rpm_violation(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADCAMValidateTest")
        try:
            service = VibeCADService()
            self._define_machine(service)
            job = self._build_job(service, doc)
            self._add_endmill(service, job)
            service.registry.call(
                "cam.create_operation", operation_type="profile", job_name=job.Name
            )
            result = service.registry.call("cam.validate_job", job_name=job.Name)
            self.assertTrue(result["ok"], result)
            self.assertTrue(result["valid"], result.get("violations"))

            # Bypass the cam.add_tool pre-check: set the property directly.
            tc = job.Tools.Group[0]
            tc.SpindleSpeed = 99999.0
            doc.recompute()
            result = service.registry.call("cam.validate_job", job_name=job.Name)
            self.assertTrue(result["ok"], result)
            self.assertFalse(result["valid"])
            codes = {item["code"] for item in result["violations"]}
            self.assertIn("spindle_rpm_exceeded", codes)
        finally:
            App.closeDocument(doc.Name)

    def test_postprocess_gates_on_validation_and_emits_tool_length_offset(self):
        import FreeCAD as App

        doc = App.newDocument("VibeCADCAMPostTest")
        try:
            service = VibeCADService()
            self._define_machine(service, postprocessor="linuxcnc", output_tlo=True)
            job = self._build_job(service, doc)
            self._add_endmill(service, job, tool_length_offset=7)
            service.registry.call(
                "cam.create_operation", operation_type="profile", job_name=job.Name
            )

            out_path = os.path.join(self._tmpdir.name, "gated.nc")
            tc = job.Tools.Group[0]

            # Error violations block G-code output and write no file.
            tc.SpindleSpeed = 99999.0
            doc.recompute()
            refused = service.registry.call(
                "cam.postprocess", job_name=job.Name, output_path=out_path
            )
            self.assertFalse(refused["ok"], refused)
            self.assertTrue(refused["recoverable"])
            self.assertTrue(refused["validation"]["violations"])
            self.assertFalse(os.path.exists(out_path))

            # force=true overrides the gate but flags the output.
            forced_path = os.path.join(self._tmpdir.name, "forced.nc")
            forced = service.registry.call(
                "cam.postprocess", job_name=job.Name, output_path=forced_path, force=True
            )
            self.assertTrue(forced["ok"], forced)
            self.assertTrue(os.path.exists(forced_path))
            self.assertIn("force", forced["warning"])
            self.assertTrue(forced["validation"]["forced"])

            # Fixing the violation lets postprocess emit clean G-code with
            # toolchange, motion, and the explicit H register (G43 H7).
            tc.SpindleSpeed = 12000.0
            doc.recompute()
            emitted = service.registry.call(
                "cam.postprocess", job_name=job.Name, output_path=out_path
            )
            self.assertTrue(emitted["ok"], emitted)
            self.assertEqual(emitted["output_path"], out_path)
            with open(out_path, encoding="utf-8") as handle:
                gcode = handle.read()
            self.assertIn("M6", gcode)
            self.assertTrue(
                any(word in gcode for word in ("G1 ", "G1\n", "G01", "G2 ", "G3 ")),
                gcode[:300],
            )
            self.assertIn("G43 H7", gcode)
        finally:
            App.closeDocument(doc.Name)

    # -- capability report -----------------------------------------------------

    def test_tool_shape_report_lists_machining_capabilities(self):
        service = VibeCADService()
        report = service.registry.call("core.get_tool_shape_report", workbench="CAMWorkbench")
        capabilities = report.get("capabilities", {})
        for name in (
            "machine_definition",
            "machining_job_setup",
            "machining_tool_controllers",
            "machining_operations",
            "machine_limit_validation",
            "gcode_postprocessing",
        ):
            self.assertIn(name, capabilities)
            self.assertTrue(capabilities[name].get("available"), name)
