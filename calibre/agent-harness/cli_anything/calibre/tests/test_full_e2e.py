from __future__ import annotations

import json
import locale
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import pytest


def _resolve_cli(name):
    force = os.environ.get("CLI_ANYTHING_FORCE_INSTALLED", "").strip() == "1"
    path = shutil.which(name)
    if path:
        print(f"[_resolve_cli] Using installed command: {path}")
        return [path]
    if force:
        raise RuntimeError(f"{name} not found in PATH. Install with: pip install -e .")
    module = name.replace("cli-anything-", "cli_anything.") + "." + name.split("-")[-1] + "_cli"
    print(f"[_resolve_cli] Falling back to: {sys.executable} -m {module}")
    return [sys.executable, "-m", module]


def _make_sample_epub(path: Path, title: str = "Sample Book", author: str = "Test Author") -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr(
            "META-INF/container.xml",
            """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>""",
        )
        zf.writestr(
            "OEBPS/chapter.xhtml",
            """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
  <head><title>Sample</title></head>
  <body><h1>Sample</h1><p>Hello calibre.</p></body>
</html>""",
        )
        zf.writestr(
            "OEBPS/toc.ncx",
            """<?xml version="1.0" encoding="UTF-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <head>
    <meta name="dtb:uid" content="urn:uuid:12345678-1234-1234-1234-123456789abc"/>
  </head>
  <docTitle><text>Sample Book</text></docTitle>
  <navMap>
    <navPoint id="navPoint-1" playOrder="1">
      <navLabel><text>Chapter 1</text></navLabel>
      <content src="chapter.xhtml"/>
    </navPoint>
  </navMap>
</ncx>""",
        )
        zf.writestr(
            "OEBPS/content.opf",
            f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="BookId" version="2.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>{title}</dc:title>
    <dc:creator>{author}</dc:creator>
    <dc:language>en</dc:language>
    <dc:identifier id="BookId">urn:uuid:12345678-1234-1234-1234-123456789abc</dc:identifier>
  </metadata>
  <manifest>
    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
    <item id="chapter" href="chapter.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine toc="ncx">
    <itemref idref="chapter"/>
  </spine>
</package>""",
        )
    return path


def _run_raw(cmd, env=None):
    encoding = locale.getpreferredencoding(False) or "utf-8"
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env=env,
        encoding=encoding,
        errors="replace",
    )


def _run_cli(cli_base, args, env=None):
    return _run_raw(cli_base + args, env=env)


@pytest.fixture(scope="module")
def cli_base():
    return _resolve_cli("cli-anything-calibre")


@pytest.fixture
def workflow_root():
    root = Path(tempfile.mkdtemp(prefix="ccal-"))
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)


@pytest.fixture
def workflow_env(workflow_root):
    env = os.environ.copy()
    env["USERPROFILE"] = str(workflow_root / "home")
    return env


@pytest.fixture
def real_library(workflow_root):
    library = workflow_root / "lib"
    result = _run_raw(
        [shutil.which("calibredb"), "list", "--for-machine", "--fields", "id,title", "--with-library", str(library)]
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert (library / "metadata.db").exists()
    return library


@pytest.fixture
def sample_epub(workflow_root):
    return _make_sample_epub(workflow_root / "workflow-sample.epub", title="Workflow Sample", author="Workflow Fixture")


class TestCLISubprocess:
    def test_help(self, cli_base):
        result = _run_cli(cli_base, ["--help"])
        assert result.returncode == 0
        assert "library" in result.stdout


@pytest.mark.skipif(shutil.which("calibredb") is None, reason="calibredb not installed")
def test_calibredb_available():
    result = _run_raw([shutil.which("calibredb"), "--version"])
    assert result.returncode == 0


@pytest.mark.skipif(shutil.which("ebook-convert") is None, reason="ebook-convert not installed")
def test_ebook_convert_available():
    result = _run_raw([shutil.which("ebook-convert"), "--version"])
    assert result.returncode == 0


@pytest.mark.skipif(shutil.which("calibredb") is None, reason="calibredb not installed")
def test_json_library_command_requires_valid_library(tmp_path, cli_base, workflow_env):
    fake_lib = tmp_path / "fake"
    fake_lib.mkdir()
    result = _run_cli(
        cli_base,
        ["--json", "--library", str(fake_lib), "library", "info"],
        env=workflow_env,
    )
    assert result.returncode != 0
    data = json.loads(result.stdout)
    assert "error" in data


@pytest.mark.skipif(shutil.which("ebook-meta") is None, reason="ebook-meta not installed")
def test_meta_show_missing_file_errors(cli_base, workflow_env):
    result = _run_cli(
        cli_base,
        ["--json", "meta", "show", "definitely-missing.epub"],
        env=workflow_env,
    )
    assert result.returncode != 0
    data = json.loads(result.stdout)
    assert data["type"] in {"file_not_found", "RuntimeError", "FileNotFoundError"}


@pytest.mark.skipif(
    shutil.which("calibredb") is None or shutil.which("ebook-meta") is None,
    reason="calibre metadata tools not installed",
)
def test_workflow_ingest_and_inspect(cli_base, workflow_env, real_library, sample_epub):
    add_result = _run_cli(
        cli_base,
        [
            "--json",
            "--library",
            str(real_library),
            "book",
            "add",
            str(sample_epub),
            "--title",
            "Workflow Book",
            "--authors",
            "Workflow Author",
            "--tags",
            "workflow,test",
        ],
        env=workflow_env,
    )
    assert add_result.returncode == 0
    add_data = json.loads(add_result.stdout)
    assert "input" in add_data

    list_result = _run_cli(
        cli_base,
        ["--json", "--library", str(real_library), "book", "list"],
        env=workflow_env,
    )
    assert list_result.returncode == 0
    books = json.loads(list_result.stdout)
    assert len(books) == 1
    book = books[0]
    assert book["title"] == "Workflow Book"
    assert book["id"] == 1
    assert "Workflow Author" in str(book.get("authors"))
    assert book.get("formats")
    book_id = book["id"]

    search_result = _run_cli(
        cli_base,
        ["--json", "--library", str(real_library), "book", "search", "Workflow"],
        env=workflow_env,
    )
    assert search_result.returncode == 0
    search_books = json.loads(search_result.stdout)
    assert any(item["id"] == book_id for item in search_books)

    get_result = _run_cli(
        cli_base,
        ["--json", "--library", str(real_library), "book", "get", str(book_id)],
        env=workflow_env,
    )
    assert get_result.returncode == 0
    get_data = json.loads(get_result.stdout)
    assert get_data["book_id"] == book_id
    assert "Workflow Book" in get_data["metadata"]
    assert "Workflow Author" in get_data["metadata"]

    meta_result = _run_cli(
        cli_base,
        ["--json", "meta", "show", str(sample_epub)],
        env=workflow_env,
    )
    assert meta_result.returncode == 0
    meta_data = json.loads(meta_result.stdout)
    assert meta_data["path"] == str(sample_epub)
    assert "Workflow Sample" in meta_data["metadata"]


@pytest.mark.skipif(
    shutil.which("calibredb") is None or shutil.which("ebook-convert") is None,
    reason="calibre export/convert tools not installed",
)
def test_workflow_export_and_convert(cli_base, workflow_env, real_library, sample_epub, workflow_root):
    add_result = _run_cli(
        cli_base,
        [
            "--json",
            "--library",
            str(real_library),
            "book",
            "add",
            str(sample_epub),
            "--title",
            "Export Workflow Book",
            "--authors",
            "Export Workflow Author",
        ],
        env=workflow_env,
    )
    assert add_result.returncode == 0

    list_result = _run_cli(
        cli_base,
        ["--json", "--library", str(real_library), "book", "list"],
        env=workflow_env,
    )
    books = json.loads(list_result.stdout)
    assert books
    book_id = books[0]["id"]

    export_dir = workflow_root / "exported"
    export_result = _run_cli(
        cli_base,
        [
            "--json",
            "--library",
            str(real_library),
            "export",
            "book",
            str(book_id),
            "--to-dir",
            str(export_dir),
            "--single-dir",
        ],
        env=workflow_env,
    )
    assert export_result.returncode == 0
    export_data = json.loads(export_result.stdout)
    assert export_data["book_ids"] == [book_id]
    exported_files = [p for p in export_dir.rglob("*") if p.is_file()]
    assert exported_files
    exported_epubs = [p for p in exported_files if p.suffix.lower() == ".epub"]
    assert exported_epubs
    exported_epub = exported_epubs[0]
    assert exported_epub.stat().st_size > 0
    assert exported_epub.read_bytes()[:4] == b"PK\x03\x04"

    converted = workflow_root / "converted" / "workflow-output.mobi"
    convert_result = _run_cli(
        cli_base,
        ["--json", "convert", "run", str(exported_epub), str(converted), "--preset", "kindle"],
        env=workflow_env,
    )
    assert convert_result.returncode == 0
    convert_data = json.loads(convert_result.stdout)
    assert convert_data["output"] == str(converted.resolve())
    assert convert_data["exists"] is True
    assert convert_data["file_size"] > 0
    assert converted.exists()
    header = converted.read_bytes()[:128]
    assert b"BOOKMOBI" in header
