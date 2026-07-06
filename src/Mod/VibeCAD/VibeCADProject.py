# SPDX-License-Identifier: LGPL-2.1-or-later

"""Project persistence for VibeCAD.

Stores a small durable manifest per CAD project (title, summary, document
scope) plus a sqlite index of known projects. Deliberately contains no
workflow state: tool availability is driven by the active workbench pack,
not by project lifecycle gates.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import time
from typing import Any


PROJECT_SCHEMA = "vibecad-project-v2"


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def slugify(value: str, fallback: str = "vibecad-project") -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "").strip()).strip("._")
    return slug[:80] or fallback


def _freecad_user_appdata() -> Path | None:
    """FreeCAD's per-user application data dir, or None when unavailable."""
    try:
        import FreeCAD as App

        raw = str(App.getUserAppDataDir() or "").strip()
        if raw:
            return Path(raw).expanduser()
    except Exception:
        pass
    return None


def _platform_data_dir() -> Path:
    """Platform-appropriate per-user data dir without FreeCAD."""
    if os.name == "nt":
        appdata = str(os.environ.get("APPDATA") or "").strip()
        if appdata:
            return Path(appdata) / "VibeCAD"
        try:
            return Path.home() / "AppData" / "Roaming" / "VibeCAD"
        except Exception:
            return Path.cwd() / "VibeCAD"
    xdg = str(os.environ.get("XDG_DATA_HOME") or "").strip()
    if xdg:
        return Path(xdg).expanduser() / "vibecad"
    try:
        return Path.home() / ".local" / "share" / "vibecad"
    except Exception:
        return Path.cwd() / ".vibecad"


def vibecad_data_dir() -> Path:
    """Central VibeCAD data directory.

    Resolution order:
    1. ``VIBECAD_HOME`` environment override (tests, power users).
    2. FreeCAD's user appdata dir + ``VibeCAD`` when FreeCAD is importable
       (``~/.local/share/FreeCAD/VibeCAD`` on Linux,
       ``%APPDATA%/FreeCAD/VibeCAD`` on Windows).
    3. Platform default without FreeCAD (``$XDG_DATA_HOME/vibecad`` or
       ``~/.local/share/vibecad`` on Linux, ``%APPDATA%/VibeCAD`` on Windows).
    """
    configured = str(os.environ.get("VIBECAD_HOME") or "").strip()
    if configured:
        return Path(configured).expanduser()
    appdata = _freecad_user_appdata()
    if appdata is not None:
        return appdata / "VibeCAD"
    return _platform_data_dir()


def _vibecad_home() -> Path:
    """Backward-compatible alias for the central data dir."""
    return vibecad_data_dir()


def _legacy_vibecad_home() -> Path:
    """Pre-move home dir (``VIBECAD_HOME`` or ``~/.vibecad``) for migration reads."""
    configured = str(os.environ.get("VIBECAD_HOME") or "").strip()
    if configured:
        return Path(configured).expanduser()
    try:
        return Path.home() / ".vibecad"
    except Exception:
        return Path.cwd() / ".vibecad"


def _default_index_path() -> Path:
    try:
        return vibecad_data_dir() / "index.sqlite"
    except Exception:
        return Path.cwd() / ".vibecad" / "index.sqlite"


def _active_document_info() -> dict[str, Any]:
    try:
        import FreeCAD as App
    except Exception:
        return {"document": None, "label": None, "file_path": None, "saved": False}

    doc = getattr(App, "ActiveDocument", None)
    if doc is None:
        return {"document": None, "label": None, "file_path": None, "saved": False}
    file_path = str(getattr(doc, "FileName", "") or "")
    return {
        "document": str(getattr(doc, "Name", "") or ""),
        "label": str(getattr(doc, "Label", "") or getattr(doc, "Name", "") or ""),
        "file_path": file_path or None,
        "saved": bool(file_path),
    }


def _project_id_for_scope(scope: dict[str, Any], session_id: str) -> str:
    file_path = scope.get("file_path")
    source = str(Path(str(file_path)).expanduser().resolve()) if file_path else session_id
    return hashlib.sha1(source.encode("utf-8")).hexdigest()[:16]


def project_root_for_document_file(file_path: str | Path) -> Path:
    """Per-document project folder for a saved CAD file.

    Matches ``VibeCADProjectStore.project_scope()`` for saved documents so all
    document artifacts (manifest, conversation, screenshots, references) share
    one folder under the central data dir.
    """
    cad_path = Path(str(file_path)).expanduser()
    source = str(cad_path.resolve())
    project_id = hashlib.sha1(source.encode("utf-8")).hexdigest()[:16]
    folder_name = f"{slugify(cad_path.stem)}-{project_id[:8]}"
    return vibecad_data_dir() / "projects" / folder_name


class VibeCADProjectStore:
    """Small durable project store keyed to the active CAD document."""

    def __init__(self, session_id: str, index_path: Path | None = None) -> None:
        self.session_id = str(session_id)
        self.index_path = index_path or _default_index_path()

    def project_scope(self) -> dict[str, Any]:
        doc = _active_document_info()
        project_id = _project_id_for_scope(doc, self.session_id)
        label = doc.get("label") or doc.get("document") or "Unsaved VibeCAD Project"
        if doc.get("file_path"):
            cad_path = Path(str(doc["file_path"])).expanduser()
            folder_name = f"{slugify(cad_path.stem)}-{project_id[:8]}"
            legacy_root = cad_path.parent / ".vibecad" / folder_name
            root = project_root_for_document_file(cad_path)
        else:
            folder_name = f"{slugify(str(label))}-{project_id[:8]}"
            legacy_root = _legacy_vibecad_home() / "projects" / folder_name
            root = vibecad_data_dir() / "projects" / folder_name
        persistent = True
        return {
            "project_id": project_id,
            "title": str(label),
            "root": str(root),
            "manifest_path": str(root / "project.vibecad.json"),
            "persistent": persistent,
            "document_saved": bool(doc.get("saved")),
            "document": doc,
            "index_path": str(self.index_path),
            "legacy_root": str(legacy_root),
            "legacy_manifest_path": str(legacy_root / "project.vibecad.json"),
        }

    def load_manifest(self) -> dict[str, Any]:
        scope = self.project_scope()
        for candidate in self._manifest_candidates(scope):
            if not candidate.exists():
                continue
            try:
                data = json.loads(candidate.read_text(encoding="utf-8"))
                if isinstance(data, dict) and data.get("schema") == PROJECT_SCHEMA:
                    return self._merge_manifest_defaults(data, scope)
            except (OSError, ValueError):
                continue
        return self._default_manifest(scope)

    @staticmethod
    def _manifest_candidates(scope: dict[str, Any]) -> list[Path]:
        """New manifest location first; legacy sidecar only as a read fallback."""
        candidates = [Path(str(scope["manifest_path"]))]
        legacy = str(scope.get("legacy_manifest_path") or "")
        if legacy and legacy != str(scope["manifest_path"]):
            candidates.append(Path(legacy))
        return candidates

    def save_manifest(self, manifest: dict[str, Any]) -> dict[str, Any]:
        scope = self.project_scope()
        merged = self._merge_manifest_defaults(manifest, scope)
        merged["updated_at"] = now_iso()
        path = Path(str(scope["manifest_path"]))
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.tmp")
        tmp.write_text(json.dumps(merged, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(path)
        self._update_index(merged, scope)
        return merged

    def context(self) -> dict[str, Any]:
        scope = self.project_scope()
        manifest = self.save_manifest(self.load_manifest())
        return {
            "schema": "vibecad-project-context-v2",
            "project_id": manifest["project_id"],
            "title": manifest.get("title") or scope.get("title"),
            "summary": manifest.get("summary") or "",
            "root": scope["root"],
            "manifest_path": scope["manifest_path"],
            "index_path": scope["index_path"],
            "persistent": bool(scope.get("persistent")),
            "document_saved": bool(scope.get("document_saved")),
            "document": scope.get("document", {}),
            "documents": manifest.get("documents", {}),
        }

    def update_summary(self, *, title: str = "", summary: str = "") -> dict[str, Any]:
        """Update the human-facing title/summary for the project."""
        manifest = self.load_manifest()
        if str(title or "").strip():
            manifest["title"] = str(title).strip()
        if str(summary or "").strip():
            manifest["summary"] = str(summary).strip()
        saved = self.save_manifest(manifest)
        return {
            "ok": True,
            "title": saved.get("title"),
            "summary": saved.get("summary"),
            "manifest_path": self.project_scope()["manifest_path"],
            "updated_at": saved.get("updated_at"),
        }

    def _default_manifest(self, scope: dict[str, Any]) -> dict[str, Any]:
        return {
            "schema": PROJECT_SCHEMA,
            "version": 1,
            "project_id": scope["project_id"],
            "title": scope["title"],
            "summary": "",
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "documents": {"active": scope.get("document", {})},
        }

    def _merge_manifest_defaults(self, manifest: dict[str, Any], scope: dict[str, Any]) -> dict[str, Any]:
        default = self._default_manifest(scope)
        merged = dict(default)
        merged.update(
            {key: value for key, value in manifest.items() if key in default and value is not None}
        )
        merged["schema"] = PROJECT_SCHEMA
        merged["project_id"] = scope["project_id"]
        merged["documents"] = dict(merged.get("documents") or {})
        merged["documents"]["active"] = scope.get("document", {})
        return merged

    def _update_index(self, manifest: dict[str, Any], scope: dict[str, Any]) -> None:
        try:
            self.index_path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(str(self.index_path)) as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS projects_v2 (
                        project_id TEXT PRIMARY KEY,
                        title TEXT NOT NULL,
                        summary TEXT NOT NULL,
                        root TEXT NOT NULL,
                        manifest_path TEXT NOT NULL,
                        cad_file TEXT,
                        updated_at TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    INSERT INTO projects_v2 (
                        project_id, title, summary, root, manifest_path, cad_file, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(project_id) DO UPDATE SET
                        title=excluded.title,
                        summary=excluded.summary,
                        root=excluded.root,
                        manifest_path=excluded.manifest_path,
                        cad_file=excluded.cad_file,
                        updated_at=excluded.updated_at
                    """,
                    (
                        manifest["project_id"],
                        str(manifest.get("title") or scope.get("title") or ""),
                        str(manifest.get("summary") or ""),
                        str(scope["root"]),
                        str(scope["manifest_path"]),
                        (scope.get("document") or {}).get("file_path"),
                        str(manifest.get("updated_at") or now_iso()),
                    ),
                )
        except (OSError, sqlite3.Error):
            pass
