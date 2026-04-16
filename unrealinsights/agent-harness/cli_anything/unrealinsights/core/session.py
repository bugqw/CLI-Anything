"""
In-memory session state for Unreal Insights CLI workflows.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class UnrealInsightsSession:
    trace_path: str | None = None
    insights_exe: str | None = None
    trace_server_exe: str | None = None

    def set_trace(self, trace_path: str | None):
        self.trace_path = str(Path(trace_path).expanduser().resolve()) if trace_path else None

    def set_insights_exe(self, path: str | None):
        self.insights_exe = str(Path(path).expanduser().resolve()) if path else None

    def set_trace_server_exe(self, path: str | None):
        self.trace_server_exe = str(Path(path).expanduser().resolve()) if path else None

    def trace_info(self) -> dict[str, object]:
        if self.trace_path is None:
            return {
                "trace_path": None,
                "exists": False,
            }

        path = Path(self.trace_path)
        return {
            "trace_path": str(path),
            "exists": path.is_file(),
            "file_size": path.stat().st_size if path.is_file() else None,
        }
