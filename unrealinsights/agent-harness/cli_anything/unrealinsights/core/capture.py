"""
Capture orchestration helpers.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Sequence

from cli_anything.unrealinsights.utils import unrealinsights_backend as backend

DEFAULT_CHANNELS = "default"
EDITOR_BINARY_NAME = "UnrealEditor.exe"


def normalize_trace_output_path(
    target_exe: str,
    output_trace: str | None = None,
    current_trace: str | None = None,
    cwd: str | None = None,
) -> str:
    """Resolve the output trace path for a capture workflow."""
    if output_trace:
        path = Path(output_trace).expanduser()
    elif current_trace:
        path = Path(current_trace).expanduser()
    else:
        base_dir = Path(cwd or os.getcwd()).resolve()
        timestamp = time.strftime("%Y%m%d-%H%M%S")
        path = base_dir / f"{Path(target_exe).stem}-{timestamp}.utrace"

    if not path.suffix:
        path = path.with_suffix(".utrace")
    return str(path.resolve())


def build_exec_cmds_arg(exec_cmds: Sequence[str] | None) -> str | None:
    if not exec_cmds:
        return None
    commands = [cmd.strip() for cmd in exec_cmds if cmd.strip()]
    return ",".join(commands) if commands else None


def resolve_engine_root(engine_root: str) -> str:
    """Normalize an Unreal Engine installation root."""
    path = Path(engine_root).expanduser().resolve()
    root = path.parent if path.name.lower() == "engine" else path

    if not root.exists():
        raise RuntimeError(f"Engine root not found: {root}")
    if not (root / "Engine").is_dir():
        raise RuntimeError(f"Engine root must contain an Engine directory: {root}")

    return str(root)


def resolve_editor_target(engine_root: str) -> str:
    """Resolve UnrealEditor.exe from a UE install root or Engine directory."""
    root = Path(resolve_engine_root(engine_root))
    editor = root / "Engine" / "Binaries" / "Win64" / EDITOR_BINARY_NAME
    if not editor.is_file():
        raise RuntimeError(f"UnrealEditor.exe not found under engine root: {root}")
    return str(editor.resolve())


def resolve_capture_target(
    target_exe: str | None,
    project: str | None = None,
    engine_root: str | None = None,
    target_args: Sequence[str] | None = None,
) -> tuple[str, list[str], dict[str, str | None]]:
    """Resolve the effective target executable and launch args."""
    resolved_project = None
    resolved_engine_root = None
    launch_args = list(target_args or [])

    if project:
        project_path = Path(project).expanduser().resolve()
        if not project_path.is_file():
            raise RuntimeError(f"Project file not found: {project_path}")
        resolved_project = str(project_path)

    if target_exe:
        target_path = Path(target_exe).expanduser().resolve()
        if not target_path.is_file():
            raise RuntimeError(f"Target executable not found: {target_path}")
        resolved_target = str(target_path)
    else:
        if not resolved_project:
            raise RuntimeError("Either target_exe or --project must be provided.")
        if not engine_root:
            raise RuntimeError("--engine-root is required when inferring UnrealEditor.exe from --project.")
        resolved_engine_root = resolve_engine_root(engine_root)
        resolved_target = resolve_editor_target(resolved_engine_root)

    if engine_root and resolved_engine_root is None:
        resolved_engine_root = resolve_engine_root(engine_root)

    if resolved_project and resolved_project not in launch_args:
        launch_args = [resolved_project, *launch_args]

    return resolved_target, launch_args, {
        "project_path": resolved_project,
        "engine_root": resolved_engine_root,
    }


def build_capture_command(
    target_exe: str,
    output_trace: str,
    channels: str = DEFAULT_CHANNELS,
    exec_cmds: Sequence[str] | None = None,
    target_args: Sequence[str] | None = None,
) -> list[str]:
    """Build the traced target command line."""
    target_path = Path(target_exe).expanduser().resolve()
    if not target_path.is_file():
        raise RuntimeError(f"Target executable not found: {target_path}")

    command = [str(target_path)]
    command.extend(target_args or [])
    command.append(f"-trace={channels}")
    command.append(f"-tracefile={Path(output_trace).expanduser().resolve()}")

    exec_arg = build_exec_cmds_arg(exec_cmds)
    if exec_arg:
        command.append(f"-ExecCmds={exec_arg}")

    return command


def run_capture(
    target_exe: str,
    output_trace: str,
    channels: str = DEFAULT_CHANNELS,
    exec_cmds: Sequence[str] | None = None,
    target_args: Sequence[str] | None = None,
    wait: bool = False,
    timeout: float | None = None,
) -> dict[str, object]:
    """Launch a traced target executable."""
    backend.ensure_parent_dir(output_trace)
    command = build_capture_command(
        target_exe,
        output_trace=output_trace,
        channels=channels,
        exec_cmds=exec_cmds,
        target_args=target_args,
    )
    result = backend.run_process(command, timeout=timeout, wait=wait)

    trace_path = Path(output_trace).expanduser().resolve()
    trace_exists = trace_path.is_file()
    trace_size = trace_path.stat().st_size if trace_exists else None

    result.update(
        {
            "target_exe": str(Path(target_exe).expanduser().resolve()),
            "target_args": list(target_args or []),
            "trace_path": str(trace_path),
            "channels": channels,
            "trace_exists": trace_exists,
            "trace_size": trace_size,
            "succeeded": bool(trace_exists) if wait else True,
        }
    )
    return result
