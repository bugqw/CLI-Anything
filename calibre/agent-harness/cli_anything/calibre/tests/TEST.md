# TEST.md

## Test Inventory Plan

- `test_core.py`: 8 unit tests planned
- `test_full_e2e.py`: 7 E2E tests planned

## Unit Test Plan

### `session.py`
- session initialization
- open library
- snapshot / undo / redo lifecycle
- save session JSON

### `library.py`
- open valid library
- reject missing library
- list fields

### `books.py`
- parse added book id
- field update plumbing via temp OPF

### `convert.py`
- preset lookup
- invalid preset rejection

## E2E Test Plan

Real workflows to test with installed calibre binaries:
- create temp calibre library
- add a sample EPUB into the library
- list/search books in JSON mode
- export a book to a temp directory
- convert EPUB to another format
- verify output artifacts exist and are non-empty

## Realistic Workflow Scenarios

### Workflow: ingest and inspect
- Simulates: adding a book to a library and inspecting it
- Operations chained: library open → book add → book list → book get
- Verified: JSON output shape, resulting book visibility

### Workflow: export and convert
- Simulates: operational automation for a reading-device pipeline
- Operations chained: export book → convert format
- Verified: files exist, non-zero size, expected extension/magic where possible

### Workflow: library mutation
- Simulates: full mutation chain on an existing book — field update followed by export
- Operations chained: book add → book set-field → book get → export book
- Verified: book get returns updated title/author after set-field; old title no longer present; export dir exists; epub non-empty; file header is valid ZIP magic bytes; exported filename contains updated title

### Workflow: metadata edit and verify
- Simulates: 对单本电子书文件做 metadata 自动化修订（标题/作者）
- Operations chained: meta show → meta set (--title/--authors) → meta show
- Verified: JSON 输出可解析；metadata 文本包含新 title/author；文件路径一致

---

## Test Results

Run date: 2026-04-01

```
============================= test session starts =============================
platform win32 -- Python 3.13.7, pytest-9.0.2, pluggy-1.6.0
rootdir: D:\AAA_work\openP\cli-anything\calibre\agent-harness

cli_anything/calibre/tests/test_core.py::test_session_initial_state PASSED
cli_anything/calibre/tests/test_core.py::test_session_open_library_and_status PASSED
cli_anything/calibre/tests/test_core.py::test_session_snapshot_undo_redo PASSED
cli_anything/calibre/tests/test_core.py::test_session_save_writes_json PASSED
cli_anything/calibre/tests/test_core.py::test_open_library_validates_metadata_db PASSED
cli_anything/calibre/tests/test_core.py::test_open_library_rejects_missing_metadata_db PASSED
cli_anything/calibre/tests/test_core.py::test_parse_added_id PASSED
cli_anything/calibre/tests/test_core.py::test_convert_presets_and_invalid_preset PASSED
cli_anything/calibre/tests/test_full_e2e.py::TestCLISubprocess::test_help PASSED
cli_anything/calibre/tests/test_full_e2e.py::test_calibredb_available PASSED
cli_anything/calibre/tests/test_full_e2e.py::test_ebook_convert_available PASSED
cli_anything/calibre/tests/test_full_e2e.py::test_json_library_command_requires_valid_library PASSED
cli_anything/calibre/tests/test_full_e2e.py::test_meta_show_missing_file_errors PASSED
cli_anything/calibre/tests/test_full_e2e.py::test_workflow_ingest_and_inspect PASSED
cli_anything/calibre/tests/test_full_e2e.py::test_workflow_export_and_convert PASSED

============================= 15 passed in 16.25s =============================
```

**15 / 15 passed.**

Run date: 2026-04-14 (full E2E suite)

Command:
- `python -m pytest -v -s cli_anything\calibre\tests\test_full_e2e.py`

```
============================ test session starts =============================
platform win32 -- Python 3.13.7, pytest-9.0.2, pluggy-1.6.0 -- D:\AAA_work\openP\.venv\Scripts\python.exe
rootdir: D:\AAA_work\openP\CLI-Anything\calibre\agent-harness
collected 8 items

cli_anything/calibre/tests/test_full_e2e.py::TestCLISubprocess::test_help PASSED
cli_anything/calibre/tests/test_full_e2e.py::test_calibredb_available PASSED
cli_anything/calibre/tests/test_full_e2e.py::test_ebook_convert_available PASSED
cli_anything/calibre/tests/test_full_e2e.py::test_json_library_command_requires_valid_library PASSED
cli_anything/calibre/tests/test_full_e2e.py::test_meta_show_missing_file_errors PASSED
cli_anything/calibre/tests/test_full_e2e.py::test_workflow_meta_set_then_show_reflects_changes PASSED
cli_anything/calibre/tests/test_full_e2e.py::test_workflow_ingest_and_inspect PASSED
cli_anything/calibre/tests/test_full_e2e.py::test_workflow_export_and_convert PASSED

============================= 8 passed in 20.62s =============================
```
**8 / 8 passed.**

Run date: 2026-04-16 (library mutation workflow added)

Command:
- `python -m pytest cli_anything/calibre/tests/test_full_e2e.py::test_workflow_library_mutation -v -s`

```
============================ test session starts =============================
platform win32 -- Python 3.13.9, pytest-9.0.3, pluggy-1.6.0 -- C:\Users\17614\AppData\Local\Programs\Python\Python313\python.exe
rootdir: D:\VSCODE-CODE\CLI-Anything-main\calibre\agent-harness
collected 1 item

cli_anything/calibre/tests/test_full_e2e.py::test_workflow_library_mutation PASSED

============================= 1 passed in 6.83s ==============================
```
**1 / 1 passed.**

### Workflow coverage added

- ingest and inspect: create temp calibre library → add sample EPUB → list/search/get in JSON mode
- export and convert: export added book to temp directory → verify exported EPUB magic bytes → convert to MOBI → verify `BOOKMOBI` signature
- metadata edit and verify: meta show → meta set (--title/--authors) → meta show (verify updated values in `ebook-meta` output)
- library mutation: book add → book set-field → book get (verify updated title/author, old title absent) → export book (verify dir structure, epub magic bytes, filename contains updated title)
- Windows stability: tests use short temp paths and explicit subprocess decoding to avoid calibre path-length and console-encoding failures

### CLI verification

```
$ cli-anything-calibre --help
Usage: cli-anything-calibre [OPTIONS] COMMAND [ARGS]...

  calibre CLI — stateful ebook library operations from the command line.

Commands:
  book     Book management commands.
  convert  Format conversion commands.
  export   Export and backup commands.
  library  Library management commands.
  meta     Standalone ebook metadata commands.
  repl     Start interactive REPL session.
  session  Session management commands.
```

Installed entry point: `D:\AAA_work\openP\.venv\Scripts\cli-anything-calibre.EXE`
