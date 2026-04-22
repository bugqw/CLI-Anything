"""Preview bundle generation for the Blender harness."""

from __future__ import annotations

import copy
import os
from typing import Any, Dict, List, Optional, Tuple

from ..utils import blender_backend
from ..utils.preview_bundle import (
    artifact_record,
    finalize_bundle,
    find_latest_manifest,
    fingerprint_data,
    prepare_bundle,
)
from . import render as render_mod
from .lighting import add_camera, add_light
from .session import Session

HARNESS_VERSION = "1.0.0"

RECIPES: Dict[str, Dict[str, Any]] = {
    "quick": {
        "description": "Two still renders for fast scene review",
        "primary_preset": "eevee_preview",
        "secondary_preset": "workbench",
        "secondary_resolution_percentage": 50,
        "timeout": 300,
    },
}


def list_recipes() -> List[Dict[str, Any]]:
    """Return available preview recipes."""
    return [
        {
            "name": name,
            "description": config["description"],
            "bundle_kind": "capture",
            "artifacts": ["hero", "gallery"],
            "presets": [config["primary_preset"], config["secondary_preset"]],
        }
        for name, config in RECIPES.items()
    ]


def _project_fingerprint(session: Session) -> str:
    project = session.get_project()
    return fingerprint_data(
        {
            "project_path": session.project_path,
            "project": project,
        }
    )


def _ensure_preview_rig(project: Dict[str, Any]) -> List[str]:
    warnings: List[str] = []
    cameras = project.setdefault("cameras", [])
    if not cameras:
        add_camera(
            project,
            name="PreviewCamera",
            location=[6.5, -6.5, 4.75],
            rotation=[63.0, 0.0, 46.0],
            focal_length=45.0,
            set_active=True,
        )
        warnings.append("No camera found; injected PreviewCamera for bundle capture.")
    elif not any(camera.get("is_active") for camera in cameras):
        cameras[0]["is_active"] = True
        warnings.append(f"No active camera set; using {cameras[0]['name']} as the preview camera.")

    lights = project.setdefault("lights", [])
    if not lights:
        add_light(
            project,
            light_type="SUN",
            name="PreviewSun",
            rotation=[42.0, 0.0, 32.0],
            power=2.2,
        )
        warnings.append("No light found; injected PreviewSun for preview legibility.")

    return warnings


def _render_image(
    project: Dict[str, Any],
    output_path: str,
    *,
    preset: str,
    frame: int,
    timeout: int,
    resolution_percentage: Optional[int] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    render_project = copy.deepcopy(project)
    kwargs: Dict[str, Any] = {
        "preset": preset,
        "output_format": "PNG",
        "film_transparent": False,
    }
    if resolution_percentage is not None:
        kwargs["resolution_percentage"] = resolution_percentage
    render_mod.set_render_settings(render_project, **kwargs)
    script = render_mod.generate_bpy_script(render_project, output_path, frame=frame, animation=False)
    backend_result = blender_backend.render_scene_headless(script, output_path, timeout=timeout)
    settings = render_mod.get_render_settings(render_project)
    return backend_result, settings


def capture(
    session: Session,
    recipe: str = "quick",
    *,
    root_dir: Optional[str] = None,
    force: bool = False,
    command: Optional[str] = None,
) -> Dict[str, Any]:
    """Render a preview bundle for the active Blender project."""
    if not session.has_project():
        raise RuntimeError("No scene loaded. Use 'scene new' or 'scene open' first.")
    if recipe not in RECIPES:
        raise ValueError(
            f"Unknown preview recipe: {recipe!r}. Available: {', '.join(sorted(RECIPES))}"
        )

    config = RECIPES[recipe]
    source_fingerprint = _project_fingerprint(session)
    prepared = prepare_bundle(
        software="blender",
        recipe=recipe,
        bundle_kind="capture",
        source_fingerprint=source_fingerprint,
        options=config,
        harness_version=HARNESS_VERSION,
        project_path=session.project_path,
        root_dir=root_dir,
        force=force,
    )
    if prepared["cached"]:
        manifest = dict(prepared["manifest"])
        manifest["cached"] = True
        return manifest

    project = copy.deepcopy(session.get_project())
    warnings = _ensure_preview_rig(project)
    bundle_dir = prepared["bundle_dir"]
    artifacts_dir = prepared["artifacts_dir"]
    frame = int(project.get("scene", {}).get("frame_current", 1) or 1)

    hero_path = os.path.join(artifacts_dir, "hero.png")
    hero_result, hero_settings = _render_image(
        project,
        hero_path,
        preset=config["primary_preset"],
        frame=frame,
        timeout=config["timeout"],
    )

    alt_path = os.path.join(artifacts_dir, "workbench.png")
    alt_result, alt_settings = _render_image(
        project,
        alt_path,
        preset=config["secondary_preset"],
        frame=frame,
        timeout=config["timeout"],
        resolution_percentage=config["secondary_resolution_percentage"],
    )

    def _size(settings: Dict[str, Any]) -> Tuple[int, int]:
        effective = settings.get("effective_resolution", "0x0").split("x", 1)
        try:
            return int(effective[0]), int(effective[1])
        except (ValueError, IndexError):
            return 0, 0

    hero_w, hero_h = _size(hero_settings)
    alt_w, alt_h = _size(alt_settings)

    artifacts = [
        artifact_record(
            bundle_dir,
            hero_result["output"],
            artifact_id="hero",
            role="hero",
            kind="image",
            label="Eevee preview",
            width=hero_w or None,
            height=hero_h or None,
            preset=config["primary_preset"],
            blender_method=hero_result.get("method"),
        ),
        artifact_record(
            bundle_dir,
            alt_result["output"],
            artifact_id="workbench",
            role="gallery",
            kind="image",
            label="Workbench structure view",
            width=alt_w or None,
            height=alt_h or None,
            preset=config["secondary_preset"],
            blender_method=alt_result.get("method"),
        ),
    ]

    scene = project.get("scene", {})
    metrics = {
        "object_count": len(project.get("objects", [])),
        "material_count": len(project.get("materials", [])),
        "camera_count": len(project.get("cameras", [])),
        "light_count": len(project.get("lights", [])),
        "frame_current": frame,
    }
    summary = {
        "headline": f"Blender {recipe} preview rendered for frame {frame}",
        "facts": {
            "recipe": recipe,
            "scene_name": project.get("name", "untitled"),
            "frame": frame,
            "hero_resolution": hero_settings.get("effective_resolution"),
            "workbench_resolution": alt_settings.get("effective_resolution"),
            **metrics,
        },
        "warnings": warnings,
        "next_actions": [
            "Inspect hero.png for shading, materials, and framing.",
            "Inspect workbench.png for silhouette and structural problems.",
        ],
    }

    manifest = finalize_bundle(
        bundle_dir=bundle_dir,
        bundle_id=prepared["bundle_id"],
        bundle_kind="capture",
        software="blender",
        recipe=recipe,
        source={
            "project_path": session.project_path,
            "project_name": os.path.basename(session.project_path) if session.project_path else project.get("name"),
            "project_fingerprint": source_fingerprint,
        },
        artifacts=artifacts,
        summary=summary,
        cache_key=prepared["cache_key"],
        generator={
            "entry_point": "cli-anything-blender",
            "harness_version": HARNESS_VERSION,
            "command": command or f"cli-anything-blender preview capture --recipe {recipe}",
        },
        status="partial" if warnings else "ok",
        warnings=warnings or None,
        context={
            "frame_range": f"{scene.get('frame_start', 1)}-{scene.get('frame_end', 250)}",
            "fps": scene.get("fps", 24),
            "primary_preset": config["primary_preset"],
            "secondary_preset": config["secondary_preset"],
        },
        metrics=metrics,
        labels=["3d", "scene", "preview"],
    )
    manifest["cached"] = False
    return manifest


def latest(
    *,
    project_path: Optional[str] = None,
    recipe: Optional[str] = None,
    root_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Return the latest preview bundle manifest for Blender."""
    manifest = find_latest_manifest(
        software="blender",
        recipe=recipe,
        bundle_kind="capture",
        project_path=project_path,
        root_dir=root_dir,
    )
    if manifest is None:
        raise FileNotFoundError("No Blender preview bundle found")
    return manifest
