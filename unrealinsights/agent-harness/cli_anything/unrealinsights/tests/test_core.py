"""
Unit tests for Unreal Insights harness modules.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner


class TestOutputUtils:
    def test_output_json(self):
        import io

        from cli_anything.unrealinsights.utils.output import output_json

        buf = io.StringIO()
        output_json({"ok": True, "value": 42}, file=buf)
        data = json.loads(buf.getvalue())
        assert data["ok"] is True
        assert data["value"] == 42

    def test_output_table_empty(self):
        import io

        from cli_anything.unrealinsights.utils.output import output_table

        buf = io.StringIO()
        output_table([], ["col"], file=buf)
        assert "(no data)" in buf.getvalue()

    def test_format_size(self):
        from cli_anything.unrealinsights.utils.output import format_size

        assert format_size(10) == "10 B"
        assert "KB" in format_size(4096)


class TestErrorUtils:
    def test_handle_error(self):
        from cli_anything.unrealinsights.utils.errors import handle_error

        result = handle_error(ValueError("bad"))
        assert result["error"] == "bad"
        assert result["type"] == "ValueError"


def _make_fake_binary(root: Path, binary_name: str) -> Path:
    target = root / "UE_5.5" / "Engine" / "Binaries" / "Win64" / binary_name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("fake-binary", encoding="utf-8")
    return target


class TestBackendDiscovery:
    @patch("cli_anything.unrealinsights.utils.unrealinsights_backend._read_windows_product_version", return_value="5.5.4")
    def test_explicit_path_precedence(self, _mock_version, tmp_path, monkeypatch):
        from cli_anything.unrealinsights.utils.unrealinsights_backend import resolve_unrealinsights_exe

        explicit = tmp_path / "explicit" / "UnrealInsights.exe"
        explicit.parent.mkdir(parents=True)
        explicit.write_text("x", encoding="utf-8")

        env_binary = tmp_path / "env" / "UnrealInsights.exe"
        env_binary.parent.mkdir(parents=True)
        env_binary.write_text("x", encoding="utf-8")
        monkeypatch.setenv("UNREALINSIGHTS_EXE", str(env_binary))

        auto_root = tmp_path / "Epic Games"
        _make_fake_binary(auto_root, "UnrealInsights.exe")

        result = resolve_unrealinsights_exe(str(explicit), search_roots=[auto_root])
        assert result["source"] == "explicit"
        assert result["path"] == str(explicit.resolve())

    @patch("cli_anything.unrealinsights.utils.unrealinsights_backend._read_windows_product_version", return_value="5.5.4")
    def test_env_path_precedence(self, _mock_version, tmp_path, monkeypatch):
        from cli_anything.unrealinsights.utils.unrealinsights_backend import resolve_unrealinsights_exe

        env_binary = tmp_path / "env" / "UnrealInsights.exe"
        env_binary.parent.mkdir(parents=True)
        env_binary.write_text("x", encoding="utf-8")
        monkeypatch.setenv("UNREALINSIGHTS_EXE", str(env_binary))

        auto_root = tmp_path / "Epic Games"
        _make_fake_binary(auto_root, "UnrealInsights.exe")

        result = resolve_unrealinsights_exe(search_roots=[auto_root])
        assert result["source"] == "env:UNREALINSIGHTS_EXE"
        assert result["path"] == str(env_binary.resolve())

    @patch("cli_anything.unrealinsights.utils.unrealinsights_backend._read_windows_product_version", return_value="5.5.4")
    def test_auto_discovery(self, _mock_version, tmp_path, monkeypatch):
        from cli_anything.unrealinsights.utils.unrealinsights_backend import resolve_unrealinsights_exe

        monkeypatch.delenv("UNREALINSIGHTS_EXE", raising=False)
        auto_root = tmp_path / "Epic Games"
        auto_binary = _make_fake_binary(auto_root, "UnrealInsights.exe")

        result = resolve_unrealinsights_exe(search_roots=[auto_root])
        assert result["source"].startswith("auto:")
        assert result["path"] == str(auto_binary.resolve())

    def test_missing_explicit_path_fails(self, tmp_path):
        from cli_anything.unrealinsights.utils.unrealinsights_backend import resolve_unrealinsights_exe

        with pytest.raises(RuntimeError):
            resolve_unrealinsights_exe(str(tmp_path / "missing.exe"))

    def test_build_insights_command(self, tmp_path):
        from cli_anything.unrealinsights.utils.unrealinsights_backend import build_insights_command

        command = build_insights_command(
            str(tmp_path / "UnrealInsights.exe"),
            str(tmp_path / "trace.utrace"),
            'TimingInsights.ExportThreads "D:\\out\\threads.csv"',
            str(tmp_path / "threads.log"),
        )
        assert any(part.startswith("-OpenTraceFile=") for part in command)
        assert any(part.startswith("-ExecOnAnalysisCompleteCmd=") for part in command)

    def test_build_insights_command_line(self, tmp_path):
        from cli_anything.unrealinsights.utils.unrealinsights_backend import build_insights_command_line

        command = build_insights_command_line(
            str(tmp_path / "UnrealInsights.exe"),
            str(tmp_path / "trace.utrace"),
            'TimingInsights.ExportThreads D:\\out\\threads.csv',
            str(tmp_path / "threads.log"),
        )
        assert "-ExecOnAnalysisCompleteCmd=" in command
        assert command.startswith('"')

    @patch("cli_anything.unrealinsights.utils.unrealinsights_backend._read_windows_product_version", return_value="5.3.0")
    def test_resolve_binary_from_engine_root(self, _mock_version, tmp_path):
        from cli_anything.unrealinsights.utils.unrealinsights_backend import resolve_binary_from_engine_root

        binary = _make_fake_binary(tmp_path, "UnrealInsights.exe")
        result = resolve_binary_from_engine_root("UnrealInsights.exe", str(tmp_path / "UE_5.5"))
        assert result["path"] == str(binary.resolve())
        assert result["source"] == "engine:UE_5.5"

    @patch("cli_anything.unrealinsights.utils.unrealinsights_backend.subprocess.run")
    def test_build_engine_program(self, mock_run, tmp_path):
        from cli_anything.unrealinsights.utils.unrealinsights_backend import build_engine_program

        build_bat = tmp_path / "UE_5.5" / "Engine" / "Build" / "BatchFiles" / "Build.bat"
        build_bat.parent.mkdir(parents=True, exist_ok=True)
        build_bat.write_text("echo build", encoding="utf-8")

        mock_run.return_value = type("Result", (), {"stdout": "ok", "stderr": "", "returncode": 0})()
        result = build_engine_program(str(tmp_path / "UE_5.5"), "UnrealInsights")
        assert result["succeeded"] is True
        assert Path(result["log_path"]).is_file()

    @patch("cli_anything.unrealinsights.utils.unrealinsights_backend._read_windows_product_version", return_value="5.3.0")
    @patch("cli_anything.unrealinsights.utils.unrealinsights_backend.build_engine_program")
    def test_ensure_engine_unrealinsights_builds_when_missing(self, mock_build, _mock_version, tmp_path):
        from cli_anything.unrealinsights.utils.unrealinsights_backend import ensure_engine_unrealinsights

        engine_root = tmp_path / "UE_5.5"
        (engine_root / "Engine" / "Binaries" / "Win64").mkdir(parents=True, exist_ok=True)
        (engine_root / "Engine" / "Build" / "BatchFiles").mkdir(parents=True, exist_ok=True)
        (engine_root / "Engine" / "Build" / "BatchFiles" / "Build.bat").write_text("echo build", encoding="utf-8")
        built_exe = engine_root / "Engine" / "Binaries" / "Win64" / "UnrealInsights.exe"
        built_exe.write_text("x", encoding="utf-8")
        mock_build.return_value = {
            "command": ["Build.bat"],
            "cwd": str(engine_root),
            "log_path": str(engine_root / "build.log"),
            "exit_code": 0,
            "timed_out": False,
            "stdout": "",
            "stderr": "",
            "succeeded": True,
        }

        result = ensure_engine_unrealinsights(str(engine_root))
        assert result["insights"]["path"] == str(built_exe.resolve())

    def test_ensure_engine_unrealinsights_no_build_errors_when_missing(self, tmp_path):
        from cli_anything.unrealinsights.utils.unrealinsights_backend import ensure_engine_unrealinsights

        engine_root = tmp_path / "UE_5.5"
        (engine_root / "Engine" / "Binaries" / "Win64").mkdir(parents=True, exist_ok=True)
        with pytest.raises(RuntimeError):
            ensure_engine_unrealinsights(str(engine_root), build_if_missing=False)


class TestCaptureCore:
    def test_normalize_trace_output_path_prefers_explicit(self, tmp_path):
        from cli_anything.unrealinsights.core.capture import normalize_trace_output_path

        path = normalize_trace_output_path("game.exe", output_trace=str(tmp_path / "capture"))
        assert path.endswith(".utrace")

    def test_build_exec_cmds_arg(self):
        from cli_anything.unrealinsights.core.capture import build_exec_cmds_arg

        assert build_exec_cmds_arg(["Trace.Bookmark Boot", "Trace.RegionBegin Boot"]) == (
            "Trace.Bookmark Boot,Trace.RegionBegin Boot"
        )

    def test_resolve_engine_root_from_engine_subdir(self, tmp_path):
        from cli_anything.unrealinsights.core.capture import resolve_engine_root

        engine_dir = tmp_path / "UE_5.5" / "Engine"
        engine_dir.mkdir(parents=True)
        assert resolve_engine_root(str(engine_dir)) == str((tmp_path / "UE_5.5").resolve())

    def test_resolve_editor_target(self, tmp_path):
        from cli_anything.unrealinsights.core.capture import resolve_editor_target

        editor = tmp_path / "UE_5.5" / "Engine" / "Binaries" / "Win64" / "UnrealEditor.exe"
        editor.parent.mkdir(parents=True)
        editor.write_text("x", encoding="utf-8")
        assert resolve_editor_target(str(tmp_path / "UE_5.5")) == str(editor.resolve())

    def test_resolve_capture_target_from_project_and_engine(self, tmp_path):
        from cli_anything.unrealinsights.core.capture import resolve_capture_target

        editor = tmp_path / "UE_5.5" / "Engine" / "Binaries" / "Win64" / "UnrealEditor.exe"
        editor.parent.mkdir(parents=True)
        editor.write_text("x", encoding="utf-8")
        project = tmp_path / "Project" / "MyGame.uproject"
        project.parent.mkdir(parents=True)
        project.write_text("{}", encoding="utf-8")

        target_exe, target_args, launch_info = resolve_capture_target(
            None,
            project=str(project),
            engine_root=str(tmp_path / "UE_5.5"),
            target_args=["-game"],
        )
        assert target_exe == str(editor.resolve())
        assert target_args[0] == str(project.resolve())
        assert "-game" in target_args
        assert launch_info["project_path"] == str(project.resolve())

    def test_build_capture_command(self, tmp_path):
        from cli_anything.unrealinsights.core.capture import build_capture_command

        exe = tmp_path / "Game.exe"
        exe.write_text("x", encoding="utf-8")
        trace = tmp_path / "capture.utrace"
        command = build_capture_command(
            str(exe),
            str(trace),
            channels="default,bookmark",
            exec_cmds=["Trace.Bookmark Boot"],
            target_args=["MyGame.uproject", "-game"],
        )
        assert command[0] == str(exe.resolve())
        assert "MyGame.uproject" in command
        assert "-trace=default,bookmark" in command
        assert any(arg.startswith("-tracefile=") for arg in command)
        assert any(arg.startswith("-ExecCmds=") for arg in command)


class TestExportCore:
    @pytest.mark.parametrize(
        ("exporter", "expected"),
        [
            ("threads", "TimingInsights.ExportThreads"),
            ("timers", "TimingInsights.ExportTimers"),
            ("timing-events", "TimingInsights.ExportTimingEvents"),
            ("timer-stats", "TimingInsights.ExportTimerStatistics"),
            ("timer-callees", "TimingInsights.ExportTimerCallees"),
            ("counters", "TimingInsights.ExportCounters"),
            ("counter-values", "TimingInsights.ExportCounterValues"),
        ],
    )
    def test_build_export_exec_command(self, exporter, expected, tmp_path):
        from cli_anything.unrealinsights.core.export import build_export_exec_command

        command = build_export_exec_command(
            exporter,
            str(tmp_path / f"{exporter}.csv"),
            columns="ThreadId,TimerId" if exporter in ("timing-events", "timer-stats", "counter-values") else None,
            threads="GameThread" if exporter in ("timing-events", "timer-stats", "timer-callees") else None,
            timers="*" if exporter in ("timing-events", "timer-stats", "timer-callees") else None,
            counter="*" if exporter == "counter-values" else None,
        )
        assert command.startswith(expected)

    def test_build_rsp_exec_command(self, tmp_path):
        from cli_anything.unrealinsights.core.export import build_rsp_exec_command

        command = build_rsp_exec_command(str(tmp_path / "exports.rsp"))
        assert command.startswith("@=")

    def test_build_export_exec_command_legacy_53_unquoted_filename(self, tmp_path):
        from cli_anything.unrealinsights.core.export import build_export_exec_command

        command = build_export_exec_command(
            "threads",
            str(tmp_path / "threads.csv"),
            insights_version="5.3.0",
        )
        assert '"{}"'.format(str((tmp_path / "threads.csv").resolve())) not in command
        assert str((tmp_path / "threads.csv").resolve()) in command

    def test_expected_outputs_from_rsp(self, tmp_path):
        from cli_anything.unrealinsights.core.export import expected_outputs_from_rsp

        rsp = tmp_path / "exports.rsp"
        rsp.write_text(
            "\n".join(
                [
                    "# comment",
                    f'TimingInsights.ExportThreads "{tmp_path / "threads.csv"}"',
                    f'TimingInsights.ExportTimers "{tmp_path / "timers.csv"}"',
                ]
            ),
            encoding="utf-8",
        )
        outputs = expected_outputs_from_rsp(str(rsp))
        assert str((tmp_path / "threads.csv").resolve()) in outputs
        assert str((tmp_path / "timers.csv").resolve()) in outputs

    def test_collect_materialized_outputs_placeholder(self, tmp_path):
        from cli_anything.unrealinsights.core.export import collect_materialized_outputs

        (tmp_path / "stats_GameThread.csv").write_text("ok", encoding="utf-8")
        outputs = collect_materialized_outputs(str(tmp_path / "stats_{region}.csv"))
        assert str((tmp_path / "stats_GameThread.csv").resolve()) in outputs


class TestCLIHelp:
    def test_main_help(self):
        from cli_anything.unrealinsights.unrealinsights_cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "Unreal Insights harness" in result.output

    def test_group_help(self):
        from cli_anything.unrealinsights.unrealinsights_cli import cli

        runner = CliRunner()
        for group in ("backend", "trace", "capture", "export", "batch"):
            result = runner.invoke(cli, [group, "--help"])
            assert result.exit_code == 0, f"{group} help failed"


class TestCLIJsonErrors:
    @patch("cli_anything.unrealinsights.unrealinsights_cli.resolve_unrealinsights_exe")
    def test_export_threads_requires_trace(self, _mock_resolve):
        from cli_anything.unrealinsights.unrealinsights_cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["--json", "export", "threads", "out.csv"])
        assert result.exit_code == 1
        data = json.loads(result.output)
        assert "error" in data

    @patch("cli_anything.unrealinsights.unrealinsights_cli.resolve_unrealinsights_exe")
    @patch("cli_anything.unrealinsights.unrealinsights_cli.resolve_trace_server_exe")
    def test_backend_info_json(self, mock_trace_server, mock_insights):
        from cli_anything.unrealinsights.unrealinsights_cli import cli

        mock_insights.return_value = {
            "available": True,
            "path": "C:/UE/UnrealInsights.exe",
            "source": "explicit",
            "version": "5.5.4",
            "engine_version_hint": "5.5",
        }
        mock_trace_server.return_value = {
            "available": False,
            "path": None,
            "source": "unresolved",
            "version": None,
            "engine_version_hint": None,
            "error": "missing",
        }

        runner = CliRunner()
        result = runner.invoke(cli, ["--json", "backend", "info"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["insights"]["path"].endswith("UnrealInsights.exe")

    def test_capture_project_requires_engine_root(self, tmp_path):
        from cli_anything.unrealinsights.unrealinsights_cli import cli

        project = tmp_path / "MyGame.uproject"
        project.write_text("{}", encoding="utf-8")

        runner = CliRunner()
        result = runner.invoke(cli, ["--json", "capture", "run", "--project", str(project)])
        assert result.exit_code == 1
        data = json.loads(result.output)
        assert "engine-root" in data["error"]

    @patch("cli_anything.unrealinsights.unrealinsights_cli.ensure_engine_unrealinsights")
    def test_backend_ensure_insights_json(self, mock_ensure):
        from cli_anything.unrealinsights.unrealinsights_cli import cli

        mock_ensure.return_value = {
            "engine_root": "D:/UE_5.3",
            "insights": {
                "available": True,
                "path": "D:/UE_5.3/Engine/Binaries/Win64/UnrealInsights.exe",
                "source": "engine:UE_5.3",
                "version": "5.3.0",
                "engine_version_hint": None,
            },
            "trace_server": {
                "available": False,
                "path": None,
                "source": "unresolved",
                "version": None,
                "engine_version_hint": None,
                "error": "missing",
            },
            "build_attempted": False,
            "build": None,
        }

        runner = CliRunner()
        result = runner.invoke(cli, ["--json", "backend", "ensure-insights", "--engine-root", "D:/UE_5.3"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["insights"]["path"].endswith("UnrealInsights.exe")


class TestREPLSessionState:
    def test_trace_set_then_info_in_repl(self):
        from cli_anything.unrealinsights.unrealinsights_cli import cli

        with patch(
            "cli_anything.unrealinsights.utils.repl_skin.ReplSkin.create_prompt_session",
            return_value=None,
        ):
            runner = CliRunner()
            result = runner.invoke(
                cli,
                input="trace set sample.utrace\ntrace info\nquit\n",
            )
        assert result.exit_code == 0
        assert "sample.utrace" in result.output


class TestCaptureCLIConvenience:
    @patch("cli_anything.unrealinsights.unrealinsights_cli.run_capture")
    def test_capture_run_with_project_and_engine_root(self, mock_run_capture, tmp_path):
        from cli_anything.unrealinsights.unrealinsights_cli import cli

        editor = tmp_path / "UE_5.5" / "Engine" / "Binaries" / "Win64" / "UnrealEditor.exe"
        editor.parent.mkdir(parents=True)
        editor.write_text("x", encoding="utf-8")
        project = tmp_path / "Project" / "MyGame.uproject"
        project.parent.mkdir(parents=True)
        project.write_text("{}", encoding="utf-8")

        mock_run_capture.return_value = {
            "command": [str(editor.resolve()), str(project.resolve()), "-trace=default"],
            "waited": True,
            "timed_out": False,
            "exit_code": 0,
            "stdout": "",
            "stderr": "",
            "pid": None,
            "target_exe": str(editor.resolve()),
            "target_args": [str(project.resolve())],
            "trace_path": str((tmp_path / "capture.utrace").resolve()),
            "channels": "default",
            "trace_exists": True,
            "trace_size": 10,
            "succeeded": True,
        }

        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "--json",
                "capture",
                "run",
                "--project",
                str(project),
                "--engine-root",
                str(tmp_path / "UE_5.5"),
                "--output-trace",
                str(tmp_path / "capture.utrace"),
                "--wait",
            ],
        )
        assert result.exit_code == 0
        mock_run_capture.assert_called_once()
        _, kwargs = mock_run_capture.call_args
        assert kwargs["target_args"][0] == str(project.resolve())
