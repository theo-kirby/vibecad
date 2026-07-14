# SPDX-License-Identifier: LGPL-2.1-or-later

"""FreeCADCmd worker that converts OpenSCAD CSG or mesh output to BREP."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import traceback


def _write(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _shape_facts(shape) -> dict:
    box = shape.BoundBox
    return {
        "valid": bool(shape.isValid()),
        "solids": len(shape.Solids),
        "faces": len(shape.Faces),
        "edges": len(shape.Edges),
        "volume_mm3": float(shape.Volume),
        "bbox": {
            "min": [float(box.XMin), float(box.YMin), float(box.ZMin)],
            "max": [float(box.XMax), float(box.YMax), float(box.ZMax)],
        },
    }


def _root_shapes(doc):
    shapes = []
    non_solid_roots = []
    for obj in list(doc.RootObjects):
        shape = getattr(obj, "Shape", None)
        if shape is None or shape.isNull():
            continue
        if not shape.Solids:
            non_solid_roots.append(str(getattr(obj, "Name", "unnamed")))
            continue
        shapes.extend(list(shape.Solids))
    if non_solid_roots:
        raise RuntimeError(
            "The CSG importer produced non-solid root geometry: "
            + ", ".join(non_solid_roots)
        )
    return shapes


def _from_csg(request: dict):
    import FreeCAD as App
    import Part
    import importCSG

    App.ParamGet("User parameter:BaseApp/Preferences/Mod/OpenSCAD").SetString(
        "openscadexecutable", str(request["openscad_executable"])
    )
    doc = App.newDocument("VibeCADOpenSCADConversion")
    importCSG.insert(str(request["input_path"]), doc.Name)
    doc.recompute()
    solids = _root_shapes(doc)
    if not solids:
        raise RuntimeError("The CSG importer produced no solid root shape.")
    shape = solids[0] if len(solids) == 1 else Part.makeCompound(solids)
    csg_text = Path(request.get("csg_text_path") or request["input_path"]).read_text(
        encoding="utf-8", errors="replace"
    )
    mesh_markers = ("hull(", "minkowski(", "surface(", "polyhedron(")
    mesh_import = re.search(
        r"\bimport\s*\([^\n;]*\.(?:stl|off|amf|3mf)\b",
        csg_text,
        flags=re.IGNORECASE,
    )
    fidelity = (
        "faceted_brep"
        if any(marker in csg_text for marker in mesh_markers) or mesh_import
        else "exact_brep"
    )
    return shape, fidelity, []


def _from_mesh(request: dict):
    import Mesh
    import Part

    mesh = Mesh.Mesh(str(request["input_path"]))
    components = list(mesh.getSeparateComponents() or [mesh])
    shape = Part.Shape()
    shape.makeShapeFromMesh(mesh.Topology, 0.05)
    shell_records = []
    for index, shell in enumerate(shape.Shells, start=1):
        try:
            solid = Part.makeSolid(shell)
        except Exception as exc:
            raise RuntimeError(
                f"Rendered shell {index} could not be converted into a solid: {exc}"
            ) from exc
        if solid.isNull() or solid.Volume <= 0:
            raise RuntimeError(
                f"Rendered shell {index} produced an empty or zero-volume solid."
            )
        if not shell.Vertexes:
            raise RuntimeError(f"Rendered shell {index} has no vertices.")
        shell_records.append(
            {
                "index": index,
                "shell": shell,
                "filled_solid": solid,
                "probe": shell.Vertexes[0].Point,
                "parent": None,
            }
        )
    for record in shell_records:
        containers = [
            candidate
            for candidate in shell_records
            if candidate is not record
            and candidate["filled_solid"].Volume > record["filled_solid"].Volume
            and candidate["filled_solid"].isInside(record["probe"], 1e-5, True)
        ]
        if containers:
            record["parent"] = min(
                containers, key=lambda item: item["filled_solid"].Volume
            )

    def nesting_depth(record):
        depth = 0
        current = record
        while current["parent"] is not None:
            depth += 1
            current = current["parent"]
        return depth

    solids = []
    for record in shell_records:
        if nesting_depth(record) % 2:
            continue
        child_cavities = [
            candidate["shell"]
            for candidate in shell_records
            if candidate["parent"] is record and nesting_depth(candidate) % 2
        ]
        shell_group = Part.makeCompound([record["shell"], *child_cavities])
        try:
            solid = Part.makeSolid(shell_group)
        except Exception as exc:
            raise RuntimeError(
                f"Rendered outer shell {record['index']} and its cavities could not "
                f"be converted into a solid: {exc}"
            ) from exc
        if solid.isNull() or not solid.isValid() or solid.Volume <= 0:
            raise RuntimeError(
                f"Rendered outer shell {record['index']} produced an invalid solid."
            )
        solids.append(solid)
    if not solids:
        raise RuntimeError("The rendered OpenSCAD mesh could not be converted into a closed solid.")
    components.sort(
        key=lambda item: (
            round(float(item.BoundBox.XMin), 9),
            round(float(item.BoundBox.YMin), 9),
            round(float(item.BoundBox.ZMin), 9),
            int(item.CountFacets),
        )
    )
    return (
        solids[0] if len(solids) == 1 else Part.makeCompound(solids),
        "faceted_brep",
        components,
    )


def _sorted_solids(shape):
    solids = list(shape.Solids)
    solids.sort(
        key=lambda item: (
            round(float(item.BoundBox.XMin), 9),
            round(float(item.BoundBox.YMin), 9),
            round(float(item.BoundBox.ZMin), 9),
            round(float(item.Volume), 9),
        )
    )
    return solids


def _write_output_artifacts(output_path: Path, shape, components) -> list[dict]:
    artifact_directory = output_path.parent / "output-artifacts"
    artifact_directory.mkdir(parents=True, exist_ok=True)
    solids = _sorted_solids(shape)
    records = []
    for index, solid in enumerate(solids, start=1):
        brep_path = artifact_directory / f"solid-{index:03d}.brep"
        solid.exportBrep(str(brep_path))
        records.append(
            {
                "index": index,
                "brep_path": str(brep_path),
                "mesh_path": None,
                "shape": _shape_facts(solid),
            }
        )
    if components and len(components) == len(records):
        for record, component in zip(records, components):
            mesh_path = artifact_directory / f"solid-{record['index']:03d}.stl"
            component.write(Filename=str(mesh_path), Format="STL")
            record["mesh_path"] = str(mesh_path)
            record["triangles"] = int(component.CountFacets)
    return records


def main() -> int:
    request_path = Path(os.environ["VIBECAD_OPENSCAD_CONVERSION_REQUEST"])
    request = json.loads(request_path.read_text(encoding="utf-8"))
    result_path = Path(request["result_path"])
    try:
        if request["mode"] == "csg":
            shape, fidelity, components = _from_csg(request)
        elif request["mode"] == "mesh":
            shape, fidelity, components = _from_mesh(request)
        else:
            raise RuntimeError(f"Unknown conversion mode: {request['mode']!r}")
        facts = _shape_facts(shape)
        if not facts["valid"] or facts["solids"] < 1 or facts["volume_mm3"] <= 0:
            raise RuntimeError(f"Converted shape is not a valid solid: {facts}")
        output_path = Path(request["output_path"])
        shape.exportBrep(str(output_path))
        output_artifacts = _write_output_artifacts(
            output_path,
            shape,
            components,
        )
        _write(
            result_path,
            {
                "ok": True,
                "output_path": str(output_path),
                "fidelity": fidelity,
                "shape": facts,
                "output_artifacts": output_artifacts,
            },
        )
        return 0
    except Exception as exc:
        _write(
            result_path,
            {
                "ok": False,
                "error": str(exc),
                "exception_type": exc.__class__.__name__,
                "traceback": traceback.format_exc(),
            },
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
