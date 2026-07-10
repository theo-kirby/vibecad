# SPDX-License-Identifier: LGPL-2.1-or-later

"""Workbench-specific VibeCAD tool-surface metadata.

A workbench lists provider tools only after that surface has a complete,
native, exact-target implementation. Empty packs are intentionally unsupported;
they do not expose partial or legacy operations to the model.
"""

from __future__ import annotations

from dataclasses import dataclass, field


SKETCHER_PACK_TOOL_NAMES: tuple[str, ...] = (
    "sketcher.draw_rectangle",
    "sketcher.add_polyline",
    "sketcher.add_arc",
    "sketcher.add_circle",
    "sketcher.add_ellipse",
    "sketcher.add_spline",
    "sketcher.add_hole_pattern",
    "sketcher.add_slot",
    "sketcher.constrain",
    "sketcher.edit_constraint",
    "sketcher.move_point",
    "sketcher.transform_geometry",
    "sketcher.modify_geometry",
    "sketcher.add_external_geometry",
    "sketcher.remove_external_geometry",
    "sketcher.delete_items",
    "sketcher.set_construction",
)

PARTDESIGN_PACK_TOOL_NAMES: tuple[str, ...] = (
    "partdesign.find_subelements",
    "partdesign.measure",
    "partdesign.create_body",
    "partdesign.create_sketch",
    "partdesign.create_datum_plane",
    "partdesign.create_datum_axis",
    "partdesign.create_datum_point",
    "partdesign.create_shape_binder",
    "partdesign.create_subshape_binder",
    "partdesign.additive_primitive",
    "partdesign.subtractive_primitive",
    "partdesign.pad",
    "partdesign.pocket",
    "partdesign.hole",
    "partdesign.revolution",
    "partdesign.groove",
    "partdesign.additive_loft",
    "partdesign.subtractive_loft",
    "partdesign.additive_pipe",
    "partdesign.subtractive_pipe",
    "partdesign.additive_helix",
    "partdesign.subtractive_helix",
    "partdesign.linear_pattern",
    "partdesign.polar_pattern",
    "partdesign.mirror",
    "partdesign.multi_transform",
    "partdesign.fillet",
    "partdesign.chamfer",
    "partdesign.draft",
    "partdesign.thickness",
    "partdesign.boolean",
    "partdesign.edit_feature",
    "partdesign.set_tip",
)

# PartDesign owns its sketches, so it requires the Sketcher editing tools while
# a human-opened Body sketch is active.
PARTDESIGN_REQUIRED_ADJACENT_TOOL_NAMES: tuple[str, ...] = SKETCHER_PACK_TOOL_NAMES


@dataclass(frozen=True)
class WorkbenchToolPack:
    workbench: str
    domain: str
    instructions: str
    command_prefixes: tuple[str, ...]
    object_types: tuple[str, ...] = ()
    object_templates: tuple[dict[str, str], ...] = ()
    tool_names: tuple[str, ...] = field(default=())
    required_adjacent_tool_names: tuple[str, ...] = field(default=())

    def provider_tool_names(self) -> tuple[str, ...]:
        names: list[str] = []
        for tool_name in self.tool_names + self.required_adjacent_tool_names:
            if tool_name not in names:
                names.append(tool_name)
        return tuple(names)

    def summary(self) -> dict[str, object]:
        return {
            "workbench": self.workbench,
            "domain": self.domain,
            "instructions": self.instructions,
            "command_prefixes": list(self.command_prefixes),
            "object_types": list(self.object_types),
            "object_templates": list(self.object_templates),
            "tool_names": list(self.tool_names),
            "required_adjacent_tool_names": list(self.required_adjacent_tool_names),
            "provider_tool_names": list(self.provider_tool_names()),
        }


WORKBENCH_TOOL_PACKS: dict[str, WorkbenchToolPack] = {
    "AssemblyWorkbench": WorkbenchToolPack(
        "AssemblyWorkbench",
        "assemblies",
        "Components, joints, solve, clash.",
        ("Assembly_",),
        ("Assembly::AssemblyObject",),
        ({"name": "assembly", "object_type": "Assembly::AssemblyObject"},),
    ),
    "BIMWorkbench": WorkbenchToolPack(
        "BIMWorkbench",
        "BIM",
        "Preserve BIM/IFC.",
        ("BIM_", "Arch_", "Draft_"),
        ("Arch::", "BIM::"),
        (
            {"name": "building", "object_type": "App::DocumentObjectGroup"},
            {"name": "level", "object_type": "App::DocumentObjectGroup"},
        ),
    ),
    "CAMWorkbench": WorkbenchToolPack(
        "CAMWorkbench",
        "CAM",
        "Machine, job, toolpath, validate, post.",
        ("CAM_",),
        (),
        ({"name": "job_container", "object_type": "App::DocumentObjectGroup"},),
    ),
    "DraftWorkbench": WorkbenchToolPack(
        "DraftWorkbench",
        "drafting",
        "2D/3D curves, arrays.",
        ("Draft_",),
        ("Part::Part2DObject",),
        (
            {"name": "draft_group", "object_type": "App::DocumentObjectGroup"},
            {"name": "annotation_group", "object_type": "App::DocumentObjectGroup"},
        ),
    ),
    "FemWorkbench": WorkbenchToolPack(
        "FemWorkbench",
        "FEA",
        "Loads, mesh, solve.",
        ("Fem_",),
        ("Fem::",),
        (
            {"name": "analysis_group", "object_type": "App::DocumentObjectGroup"},
            {"name": "constraint_group", "object_type": "App::DocumentObjectGroup"},
        ),
    ),
    "InspectionWorkbench": WorkbenchToolPack(
        "InspectionWorkbench",
        "inspection",
        "Measure.",
        ("Inspection_",),
        (),
        ({"name": "inspection_group", "object_type": "App::DocumentObjectGroup"},),
    ),
    "MaterialWorkbench": WorkbenchToolPack(
        "MaterialWorkbench",
        "materials",
        "Material/appearance.",
        ("Material_", "Mat"),
        (),
        ({"name": "material_group", "object_type": "App::DocumentObjectGroup"},),
    ),
    "MeshWorkbench": WorkbenchToolPack(
        "MeshWorkbench",
        "mesh",
        "Inspect/repair mesh.",
        ("Mesh_",),
        ("Mesh::",),
        ({"name": "mesh_group", "object_type": "App::DocumentObjectGroup"},),
    ),
    "MeshPartWorkbench": WorkbenchToolPack(
        "MeshPartWorkbench",
        "mesh conversion",
        "Mesh<->BREP; verify source.",
        ("MeshPart_",),
        ("Mesh::", "Part::"),
        ({"name": "mesh_from_shape", "object_type": "Mesh::Feature"},),
    ),
    "NoneWorkbench": WorkbenchToolPack(
        "NoneWorkbench",
        "no active workbench",
        "Inspect the current document.",
        (),
        (),
        ({"name": "context_group", "object_type": "App::DocumentObjectGroup"},),
    ),
    "OpenSCADWorkbench": WorkbenchToolPack(
        "OpenSCADWorkbench",
        "CSG",
        "Inspect CSG.",
        ("OpenSCAD_",),
        (),
        ({"name": "csg_group", "object_type": "App::DocumentObjectGroup"},),
    ),
    "PartDesignWorkbench": WorkbenchToolPack(
        "PartDesignWorkbench",
        "solids",
        "Body, sketch, feature. Match form; verify DoF/topology.",
        ("PartDesign_", "Sketcher_"),
        ("PartDesign::", "Sketcher::SketchObject"),
        (
            {"name": "body", "object_type": "PartDesign::Body"},
            {"name": "sketch", "object_type": "Sketcher::SketchObject"},
        ),
        tool_names=PARTDESIGN_PACK_TOOL_NAMES,
        required_adjacent_tool_names=PARTDESIGN_REQUIRED_ADJACENT_TOOL_NAMES,
    ),
    "PartWorkbench": WorkbenchToolPack(
        "PartWorkbench",
        "boundary-representation solids",
        "Direct BREP edit.",
        ("Part_",),
        ("Part::",),
        (
            {"name": "box", "object_type": "Part::Box"},
            {"name": "cylinder", "object_type": "Part::Cylinder"},
            {"name": "sphere", "object_type": "Part::Sphere"},
        ),
    ),
    "PointsWorkbench": WorkbenchToolPack(
        "PointsWorkbench",
        "point clouds",
        "Preserve cloud.",
        ("Points_",),
        ("Points::",),
        ({"name": "points_group", "object_type": "App::DocumentObjectGroup"},),
    ),
    "ReverseEngineeringWorkbench": WorkbenchToolPack(
        "ReverseEngineeringWorkbench",
        "reverse engineering",
        "Reconstruct surfaces.",
        ("ReverseEngineering_",),
        (),
        (
            {
                "name": "reverse_engineering_group",
                "object_type": "App::DocumentObjectGroup",
            },
        ),
    ),
    "RobotWorkbench": WorkbenchToolPack(
        "RobotWorkbench",
        "robot simulation",
        "Trajectories/setup.",
        ("Robot_",),
        ("Robot::",),
        (
            {
                "name": "robot_simulation_group",
                "object_type": "App::DocumentObjectGroup",
            },
        ),
    ),
    "SketcherWorkbench": WorkbenchToolPack(
        "SketcherWorkbench",
        "sketching",
        "Lines/arcs/splines/slots. Constrain; DoF 0.",
        ("Sketcher_",),
        ("Sketcher::SketchObject",),
        ({"name": "sketch", "object_type": "Sketcher::SketchObject"},),
        tool_names=SKETCHER_PACK_TOOL_NAMES,
    ),
    "SpreadsheetWorkbench": WorkbenchToolPack(
        "SpreadsheetWorkbench",
        "spreadsheet",
        "Aliases/formulas.",
        ("Spreadsheet_",),
        ("Spreadsheet::Sheet",),
        ({"name": "sheet", "object_type": "Spreadsheet::Sheet"},),
        tool_names=(),
    ),
    "SurfaceWorkbench": WorkbenchToolPack(
        "SurfaceWorkbench",
        "surfaces",
        "Curves, fills, sections, thicken.",
        ("Surface_",),
        ("Surface::",),
        (
            {"name": "filling", "object_type": "Surface::Filling"},
            {"name": "geom_fill_surface", "object_type": "Surface::GeomFillSurface"},
            {"name": "sections", "object_type": "Surface::Sections"},
        ),
    ),
    "TechDrawWorkbench": WorkbenchToolPack(
        "TechDrawWorkbench",
        "drawings",
        "Pages/views.",
        ("TechDraw_",),
        ("TechDraw::",),
        (
            {"name": "page_group", "object_type": "App::DocumentObjectGroup"},
            {"name": "drawing_group", "object_type": "App::DocumentObjectGroup"},
        ),
    ),
    "TestWorkbench": WorkbenchToolPack(
        "TestWorkbench",
        "test framework",
        "Read-only.",
        ("Test_", "Std_Test"),
        (),
        ({"name": "test_group", "object_type": "App::DocumentObjectGroup"},),
    ),
}


def get_tool_pack(workbench: str | None) -> WorkbenchToolPack | None:
    if not workbench:
        return None
    return WORKBENCH_TOOL_PACKS.get(workbench)


def list_tool_packs() -> list[dict[str, object]]:
    return [pack.summary() for pack in WORKBENCH_TOOL_PACKS.values()]
