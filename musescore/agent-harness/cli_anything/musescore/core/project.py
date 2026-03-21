"""Project management — create, open, save, info."""

import os
from pathlib import Path

from cli_anything.musescore.utils import musescore_backend as backend
from cli_anything.musescore.utils import mscx_xml as xml_utils


def open_project(path: str) -> dict:
    """Open a score file and return project data.

    Supports .mscz, .mxl, .musicxml, .mid formats.
    """
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Score file not found: {path}")

    fmt = xml_utils.detect_format(path)
    project = {
        "name": Path(path).stem,
        "path": str(Path(path).resolve()),
        "format": fmt,
    }

    # Try to get metadata from mscore
    try:
        meta = backend.get_score_meta(path)
        project["metadata"] = meta
        if meta.get("title"):
            project["name"] = meta["title"]
    except Exception:
        # Fall back to XML parsing for metadata
        try:
            tree = xml_utils.read_score_tree(path)
            title = xml_utils.get_score_title(tree)
            if title:
                project["name"] = title
            project["metadata"] = {
                "key_signature": xml_utils.get_key_signature(tree),
                "time_signature": xml_utils.get_time_signature(tree),
                "instruments": xml_utils.get_instruments(tree),
                "measures": xml_utils.count_measures(tree),
                "notes": xml_utils.count_notes(tree),
            }
        except Exception:
            pass

    return project


def save_project(project: dict, path: str | None = None) -> str:
    """Save a project. Currently just returns the path (scores are
    saved via mscore export, not by rewriting the file directly)."""
    save_path = path or project.get("path")
    if not save_path:
        raise RuntimeError("No save path specified.")
    return str(save_path)


def project_info(path: str) -> dict:
    """Get comprehensive info about a score file."""
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Score file not found: {path}")

    info = {
        "path": str(Path(path).resolve()),
        "format": xml_utils.detect_format(path),
        "size_bytes": os.path.getsize(path),
    }

    # Try mscore --score-meta first (most complete)
    try:
        meta = backend.get_score_meta(path)
        info["metadata"] = meta
        return info
    except Exception:
        pass

    # Fall back to XML parsing
    try:
        tree = xml_utils.read_score_tree(path)
        info["metadata"] = {
            "title": xml_utils.get_score_title(tree),
            "key_signature": xml_utils.get_key_signature(tree),
            "key_name": _key_sig_name(xml_utils.get_key_signature(tree)),
            "time_signature": xml_utils.get_time_signature(tree),
            "instruments": xml_utils.get_instruments(tree),
            "measures": xml_utils.count_measures(tree),
            "notes": xml_utils.count_notes(tree),
        }
    except Exception as e:
        info["error"] = f"Could not parse score: {e}"

    return info


def _key_sig_name(key_int: int | None) -> str | None:
    if key_int is None:
        return None
    try:
        return xml_utils.key_int_to_name(key_int)
    except ValueError:
        return f"keysig={key_int}"
