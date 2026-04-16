# cli-anything-unrealinsights

Command-line interface for Unreal Insights trace capture and export workflows.

This harness wraps the real Unreal Engine tools:

- `UnrealInsights.exe` for headless `.utrace` analysis and exporters
- a traced UE/Game executable for file-mode capture generation

## Installation

```bash
cd unrealinsights/agent-harness
pip install -e .
```

## Prerequisites

- Windows
- Unreal Engine 5.5+ installed with `UnrealInsights.exe`
- optional `UnrealTraceServer.exe` for backend reporting

You can point the harness at explicit binaries:

```powershell
$env:UNREALINSIGHTS_EXE='D:\Program Files\Epic Games\UE_5.5\Engine\Binaries\Win64\UnrealInsights.exe'
$env:UNREAL_TRACE_SERVER_EXE='D:\Program Files\Epic Games\UE_5.5\Engine\Binaries\Win64\UnrealTraceServer.exe'
```

If those are not set, the harness auto-discovers common UE installs under
`<drive>:\Program Files\Epic Games\UE_*`.

## Quick Start

```powershell
# Inspect resolved backend binaries
cli-anything-unrealinsights --json backend info

# Find or build UnrealInsights.exe for a custom engine root
cli-anything-unrealinsights --json backend ensure-insights `
  --engine-root 'D:\code\D5\d5render-ue5_3'

# Bind a trace file for the current session
cli-anything-unrealinsights trace set D:\captures\session.utrace

# Export threads
cli-anything-unrealinsights --json -t D:\captures\session.utrace export threads D:\out\threads.csv

# Export timer statistics for a region
cli-anything-unrealinsights --json -t D:\captures\session.utrace export timer-stats `
  D:\out\timer_stats.csv --threads "GameThread" --timers "*" --region "EXPORT_CAPTURE"

# Execute a response file
cli-anything-unrealinsights --json -t D:\captures\session.utrace batch run-rsp D:\out\export.rsp

# Launch a traced UE target and wait for completion
cli-anything-unrealinsights --json capture run `
  --project 'D:\Projects\MyGame\MyGame.uproject' `
  --engine-root 'D:\Program Files\Epic Games\UE_5.5' `
  --output-trace D:\captures\editor_boot.utrace `
  --channels "default,bookmark" `
  --exec-cmd "Trace.Bookmark BootStart" `
  --wait --timeout 300

# Start REPL (default behavior)
cli-anything-unrealinsights
```

## Command Groups

- `backend`
  - `info`
  - `ensure-insights`
- `trace`
  - `set`
  - `info`
- `capture`
  - `run`
- `export`
  - `threads`
  - `timers`
  - `timing-events`
  - `timer-stats`
  - `timer-callees`
  - `counters`
  - `counter-values`
- `batch`
  - `run-rsp`
- `repl`

## Global Options

- `--json`: machine-readable output
- `--debug`: include traceback details in errors
- `--trace/-t`: current `.utrace` file
- `--insights-exe`: explicit `UnrealInsights.exe` path
- `--trace-server-exe`: explicit `UnrealTraceServer.exe` path

## Engine-Matched Insights

If you need an `UnrealInsights.exe` matching a custom source engine, use:

```powershell
cli-anything-unrealinsights --json backend ensure-insights `
  --engine-root 'D:\code\D5\d5render-ue5_3'
```

Behavior:

- looks for `Engine\Binaries\Win64\UnrealInsights.exe` under the given engine root
- if missing, runs that engine's `Engine\Build\BatchFiles\Build.bat UnrealInsights Win64 Development -WaitMutex`
- returns the resolved path plus the build log path when a build was attempted

## Capture Convenience Layer

`capture run` supports two launch styles:

```powershell
# 1. Convenience mode: infer UnrealEditor.exe from engine root
cli-anything-unrealinsights capture run `
  --project 'D:\Projects\MyGame\MyGame.uproject' `
  --engine-root 'D:\Program Files\Epic Games\UE_5.5'

# 2. Explicit mode: provide the exact executable yourself
cli-anything-unrealinsights capture run `
  'D:\Program Files\Epic Games\UE_5.5\Engine\Binaries\Win64\UnrealEditor.exe' `
  --target-arg 'D:\Projects\MyGame\MyGame.uproject'
```

Notes:

- `--project` prepends the `.uproject` path to the target command line.
- `--engine-root` accepts either the UE install root or its `Engine` subdirectory.
- If `target_exe` is omitted, `capture run` resolves `UnrealEditor.exe` from `--engine-root`.
- The original explicit `target_exe` path remains supported.

## Export Filters

`timing-events` and `timer-stats` support:

- `--columns`
- `--threads`
- `--timers`
- `--start-time`
- `--end-time`
- `--region`

`counter-values` supports:

- `--counter`
- `--columns`
- `--start-time`
- `--end-time`
- `--region`

## Testing

```bash
cd unrealinsights/agent-harness
pytest cli_anything/unrealinsights/tests/test_core.py -v
pytest cli_anything/unrealinsights/tests/test_full_e2e.py -v -s
```

Optional environment variables for E2E coverage:

- `UNREALINSIGHTS_TEST_TRACE`
- `UNREALINSIGHTS_TEST_TARGET_EXE`
