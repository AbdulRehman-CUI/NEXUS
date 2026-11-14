import logging
import os
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import pdf_bytes
from test_release_operations import docx_bytes

from nexus.config import Settings
from nexus.extraction import NeedsOCR, bounded_extract, parser_environment, parser_output_limit


@pytest.fixture
def settings():
    return Settings(_env_file=None, max_source_characters=1000)


@pytest.fixture(autouse=True)
def capture_parser_logs(monkeypatch):
    # Other API tests may have configured the application's non-propagating logger.
    monkeypatch.setattr(logging.getLogger("nexus"), "propagate", True)


@pytest.mark.parametrize(
    "suffix, expected",
    [(".pdf", "café"), (".txt", "اردو café"), (".md", "# اردو café"), (".docx", "اردو café")],
)
def test_isolated_unicode_and_empty_documents(tmp_path, monkeypatch, settings, suffix, expected):
    # Simulate a host with non-UTF-8 text stream defaults. The protocol uses binary pipes.
    monkeypatch.setenv("PYTHONIOENCODING", "ascii")
    path = tmp_path / f"اردو café{suffix}"
    if suffix == ".pdf":
        content, empty = pdf_bytes("café"), pdf_bytes("")
    elif suffix == ".docx":
        xml = (
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            "<w:body><w:p><w:r><w:t>{}</w:t></w:r></w:p></w:body></w:document>"
        )
        content, empty = docx_bytes(xml.format("اردو café")), docx_bytes(xml.format(""))
    elif suffix == ".md":
        content = "---\ntitle: اردو\n---\n# اردو\ncafé".encode("utf-8")
        empty = b"---\ntitle: empty\n---"
    else:
        content, empty = "اردو café".encode("utf-8-sig"), b""
    path.write_bytes(content)
    passages = bounded_extract(path, suffix, settings)
    assert [passage.text for passage in passages] == [expected]
    assert passages[0].page == (1 if suffix == ".pdf" else None)
    path.write_bytes(empty)
    if suffix == ".pdf":
        with pytest.raises(NeedsOCR, match="No readable PDF text"):
            bounded_extract(path, suffix, settings)
    else:
        with pytest.raises(ValueError, match="no readable text"):
            bounded_extract(path, suffix, settings)


def test_parent_dependency_paths_reach_fresh_child(tmp_path, monkeypatch, settings):
    path = tmp_path / "document.pdf"
    path.write_bytes(pdf_bytes("hello"))
    marker = str(tmp_path / "runtime-libraries")
    monkeypatch.setenv("PYTHONPATH", marker)
    monkeypatch.setenv("NEXUS_PARSER_TEST_MARKER", "preserved")
    run = subprocess.run

    def without_site_initialization(command, **kwargs):
        assert command[0] == sys.executable
        assert marker in kwargs["env"]["PYTHONPATH"].split(os.pathsep)
        assert kwargs["env"]["NEXUS_PARSER_TEST_MARKER"] == "preserved"
        # Site-packages were found by the parent. The child gets only the supplied search paths.
        return run([command[0], "-S", *command[1:]], **kwargs)

    monkeypatch.setattr(subprocess, "run", without_site_initialization)
    assert bounded_extract(path, ".pdf", settings)[0].text == "hello"


def test_missing_child_dependency_is_sanitized(tmp_path, monkeypatch, settings, caplog):
    import pymupdf

    assert callable(pymupdf.open)
    (tmp_path / "pymupdf.py").write_text(
        "import sys\nprint('private-stderr', file=sys.stderr)\nraise ImportError('private-path')\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    with pytest.raises(ValueError, match="parser dependency is unavailable") as raised:
        bounded_extract(tmp_path / "private.pdf", ".pdf", settings)
    assert "reason=dependency_missing" in caplog.text
    assert any(size in caplog.text for size in ("stderr_bytes=15", "stderr_bytes=16"))
    assert "private-" not in caplog.text + str(raised.value)


@pytest.mark.parametrize("suffix", [".txt", ".md"])
def test_malformed_text_is_reported_as_invalid_utf8(tmp_path, settings, suffix):
    path = tmp_path / f"bad{suffix}"
    path.write_bytes(b"\xff")
    with pytest.raises(ValueError, match="must use UTF-8"):
        bounded_extract(path, suffix, settings)


def test_unexpected_parser_exception_is_sanitized(tmp_path, settings, caplog):
    path = tmp_path / "private.pdf"
    path.write_bytes(b"not a PDF")
    with pytest.raises(ValueError, match="Document parser failed") as raised:
        bounded_extract(path, ".pdf", settings)
    assert "reason=parser_failed" in caplog.text
    assert str(path) not in caplog.text + str(raised.value)


def test_output_limit_is_reported_by_child(settings, tmp_path, caplog):
    # A small source with many heading paths repeats the longest heading in output metadata.
    path = tmp_path / "headings.md"
    path.write_text("# " + "a" * 490 + "\n" + "## b\n" * 999, encoding="utf-8")
    settings.max_source_characters = 6000
    assert len(path.read_text(encoding="utf-8")) <= settings.max_source_characters
    with pytest.raises(ValueError, match="exceeded its output limit"):
        bounded_extract(path, ".md", settings)
    assert "reason=output_limit" in caplog.text
    assert "stdout_bytes=26" in caplog.text


@pytest.mark.parametrize(
    "exit_code, output, text, reason",
    [
        (17, b"", "exited unexpectedly", "exit_failed"),
        (0, b"\xff", "returned invalid output", "invalid_output"),
        (0, b"not-json", "returned invalid output", "invalid_output"),
        (0, b"[]", "returned invalid output", "invalid_output"),
        (
            0,
            b'{"status":"ok","passages":[{"text":"hi","page":true,"heading":null}]}',
            "returned invalid output",
            "invalid_output",
        ),
        (0, b"x" * (parser_output_limit(1000) + 1), "exceeded its output limit", "output_limit"),
    ],
)
def test_child_result_errors(monkeypatch, settings, caplog, exit_code, output, text, reason):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess([], exit_code, output, b"private"),
    )
    with pytest.raises(ValueError, match=text) as raised:
        bounded_extract(Path("private.md"), ".md", settings)
    assert f"reason={reason} format=.md exit={exit_code}" in caplog.text
    assert "private" not in caplog.text + str(raised.value)


@pytest.mark.parametrize(
    "error, text, reason",
    [
        (subprocess.TimeoutExpired(["private-path"], 1), "exceeded its process time limit", "timeout"),
        (OSError("private-path"), "could not start", "start_failed"),
    ],
)
def test_child_launch_errors(monkeypatch, settings, caplog, error, text, reason):
    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(subprocess, "run", fail)
    with pytest.raises(ValueError, match=text) as raised:
        bounded_extract(Path("private.md"), ".md", settings)
    assert f"reason={reason}" in caplog.text
    assert "private" not in caplog.text + str(raised.value)


def test_pythonpath_merge_deduplicates_paths(monkeypatch):
    source = str(Path(__file__).resolve().parents[1])
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join([source, "", source]))
    paths = parser_environment()["PYTHONPATH"].split(os.pathsep)
    assert paths[0] == source
    assert paths.count(source) == 1
    assert "" not in paths
