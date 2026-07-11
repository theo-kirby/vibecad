# VibeCAD Tool Pack — Runtime Verification Checklist

All 118 tool specs import, validate, and pass the guardrail pytest suite
(`vibecad_tests/`) **without a FreeCAD runtime** (FreeCAD/FreeCADGui are
stubbed). Geometry execution, external binaries, and GUI behavior can only be
verified inside a running FreeCAD 1.x instance. This checklist covers the
runtime-dependent items a human should smoke-test, per pack, roughly in
dependency order.

Every write tool runs inside a FreeCAD transaction, so a failed check is
undoable with Ctrl+Z.

## Part (10 tools) — verify first; other packs depend on it

- [ ] `part.create_primitive` — each variant (box, cylinder, sphere, cone,
      torus) produces a valid solid with the requested dimensions.
- [ ] `part.boolean` — union/cut/intersection on two overlapping solids;
      confirm non-solid operands are rejected with a clean error.
- [ ] `part.extrude` / `part.revolve` — from a closed Draft profile
      (`make_face=true`); result reports `ok:true` only for a valid shape.
- [ ] `part.mirror`, `part.set_placement` — placement math (position mm +
      axis-angle degrees) matches what the 3D view shows.
- [ ] `part.fillet` / `part.chamfer` — on exact edge names resolved via
      `part.find_subelements`; confirm invalid edge names error actionably.
- [ ] `part.find_subelements` / `part.measure` — subelement names returned
      match the names FreeCAD shows in the status bar on hover.

## Draft (7 tools)

- [ ] `draft.create_wire` / `create_circle` / `create_rectangle` /
      `create_bspline` — with `make_face=true`, results feed `part.extrude`.
- [ ] `draft.create_circle` arc variant (start/end angles) draws the expected
      arc direction.
- [ ] `draft.create_array` — orthogonal and polar variants place copies where
      expected.
- [ ] `draft.create_text` — annotation appears at the given position
      (non-shape; returns mutation result, not a shape result).

## Spreadsheet (3 tools)

- [ ] `spreadsheet.set_cells` — batch with an alias and a same-batch formula
      referencing that alias evaluates correctly (aliases are set before
      content by design).
- [ ] `spreadsheet.read_sheet` — Quantity cells return unit-bearing strings
      (UserString), not raw floats.

## Assembly (6 tools) — most FreeCAD-1.x-API-sensitive pack

- [ ] `assembly.create_assembly` — creates `Assembly::AssemblyObject` with a
      JointGroup (requires the Assembly workbench built into FreeCAD 1.x).
- [ ] `assembly.insert_component` — plain objects insert as `App::Link`;
      nested assemblies as `Assembly::AssemblyLink`.
- [ ] `assembly.ground_component` — GroundedJoint appears; duplicate ground
      attempts are rejected.
- [ ] `assembly.create_joint` — each of the 6 variants (fixed, revolute,
      cylindrical, slider, ball, distance) creates a native joint AND the
      embedded solve runs; deliberately over-constrain to confirm the `ok`
      downgrade + hint text fires.
- [ ] `assembly.solve` — solver return-code → verdict mapping
      (0/-1/…/-6 per `AssemblyObject.pyi`) matches your FreeCAD build.

## Surface (5 tools)

- [ ] `surface.fill` — closed loop of exact edges produces a Filling patch.
- [ ] `surface.loft` / `surface.blend` — sections/GeomFillSurface compute;
      blend `fill_style` enum values map to native styles.
- [ ] `surface.extend` — U/V percent enlargement visible on the face.
- [ ] `surface.thicken` — Part::Offset produces a solid wall; signed
      thickness direction is correct.

## TechDraw (5 tools)

- [ ] `techdraw.create_page` — ISO blank templates resolve from
      `App.getResourceDir()/Mod/TechDraw/Templates/ISO/`; test the fallback by
      requesting each sheet_size.
- [ ] `techdraw.add_view` — each view_direction enum projects the expected
      orientation (front = Direction (0,-1,0)).
- [ ] `techdraw.add_dimension` — each of the 7 variants on projected
      `Edge*`/`Vertex*` names computes a value; give it unsuitable references
      to confirm the `ok` downgrade with hint.
- [ ] Confirm projected element names (Edge0 within a view) versus model
      subelement names don't confuse the workflow in practice.

## Material (3 tools)

- [ ] `material.list_materials` — MaterialManager cards list with real UUIDs;
      filter narrows; >50 results sets `truncated`.
- [ ] `material.apply_material` — ShapeMaterial set; physical-property summary
      (Density, YoungsModulus, …) matches the card.
- [ ] `material.set_appearance` — **GUI-only**: color/transparency change in
      the 3D view; run once in headless mode to confirm the clean
      "FreeCAD is running without a GUI" error.

## Mesh + MeshPart (5 tools)

- [ ] `mesh.analyze` — defect report on a known-broken mesh (non-manifold,
      holes) is accurate.
- [ ] `mesh.repair` — before/after comparison shows improvement; hole filling
      respects `fill_holes_max_edges`.
- [ ] `meshpart.mesh_from_shape` — deflection parameters (mm / degrees)
      visibly change tessellation density.
- [ ] `meshpart.shape_from_mesh` — `make_solid=true` on a non-watertight mesh
      errors with the pointer to `mesh.repair`.

## FEM (6 tools) — requires external binaries

- [ ] **Gmsh installed**: `fem.mesh_analysis` produces a mesh with nodes;
      without Gmsh, confirm the actionable install/preferences error.
- [ ] **CalculiX (ccx) installed**: `fem.solve` end-to-end on a simple
      cantilever (create_analysis → add_material → fixed + force constraints →
      mesh → solve) returns plausible peak von Mises / displacement.
- [ ] `fem.add_material` with a card lacking YoungsModulus triggers the
      warning downgrade.
- [ ] `fem.add_constraint` — all 5 variants attach to model subelements
      (not FEM mesh entities).
- [ ] `fem.solve` failure stages each yield distinct errors (missing
      prerequisites, missing binary, nonzero exit, no results).

## CAM (4 tools)

- [ ] `cam.create_job` — stock margins apply per axis.
- [ ] `cam.add_tool` — ToolBit shape ids resolve (endmill, ballend, drill,
      chamfer, v-bit); tool controller registers with feeds/speeds.
- [ ] `cam.add_operation` — profile/pocket/drilling/face each produce
      non-empty toolpaths on a suitable model; **critical**: depths set via
      the tool must override SetupSheet expressions (the tool clears
      expressions first — verify the literal values stick).
- [ ] Empty-toolpath downgrade fires when depths are wrong.
- [ ] G-code postprocessing is intentionally *not* exposed — confirm the pack
      instructions direct users to the GUI for that.

## BIM (5 tools)

- [ ] `bim.create_spatial_structure` — Site → Building → Levels hierarchy with
      per-level elevations shows correctly in the tree.
- [ ] `bim.create_wall` — wall extrudes along a Draft baseline; Center/Left/
      Right alignment behaves; wall files into the given level.
- [ ] `bim.create_structure` — column/beam/slab variants; slab extrudes
      *downward* from the profile (Normal (0,0,-1)).
- [ ] `bim.add_window` — each preset (fixed_window, open_window, door,
      glass_door) stands upright (the ×Rotation(X,90) correction) and cuts an
      opening in the host wall via Hosts.

## Long-tail READ packs (Points, Inspection, OpenSCAD, RevEng, Robot)

- [ ] Each single `*.list_*` tool returns accurate summaries against a
      document containing the relevant objects (import an OpenSCAD CSG file,
      a point cloud, etc.).

## Cross-cutting

- [ ] Workbench switching: activating each workbench in the GUI surfaces
      exactly its pack (owned + adjacent + 5 core tools) to the provider —
      spot-check Sketcher (17+core), Part (10+core), FEM (6+3 adjacent+core).
- [ ] Undo: every write tool's transaction undoes cleanly in one Ctrl+Z.
- [ ] Headless (`FreeCADCmd`): GUI-dependent tools (`material.set_appearance`,
      `core.capture_view_screenshot`, `core.set_view`) fail with actionable
      text instead of crashing.
- [ ] Version drift: Assembly joints (`JointObject`), FEM (`femtools`,
      `ObjectsFem`), and CAM (`Path.Main.Job`, ToolBit) APIs were coded
      against FreeCAD 1.x — re-run this checklist after any FreeCAD upgrade.
