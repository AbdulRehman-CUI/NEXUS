import json
import logging
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("nexus")


class ExtractionRejected(ValueError):
    """An application-authored validation error that is safe to show to the user."""


class NeedsOCR(ExtractionRejected):
    pass


def parser_output_limit(max_chars: int) -> int:
    return max_chars * 8 + 100_000


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\x00", "")).strip()


@dataclass
class Passage:
    text: str
    page: int | None = None
    heading: str | None = None


def extract(
    path: Path, extension: str, max_chars: int, max_pages: int, ocr=False, ocr_max_pages=20
) -> list[Passage]:
    passages = []
    if extension == ".pdf":
        import pymupdf

        # MuPDF's native path handling on Windows can fail on Unicode filenames.
        if os.name == "nt" and not str(path).isascii():
            document = pymupdf.open(stream=path.read_bytes(), filetype="pdf")
        else:
            document = pymupdf.open(path)
        with document as pdf:
            if pdf.needs_pass:
                raise ExtractionRejected(
                    "Password-protected PDF. Export an unlocked text-based PDF and retry."
                )
            if len(pdf) > max_pages:
                raise ExtractionRejected(
                    f"PDF exceeds the {max_pages}-page limit. Split it into smaller files."
                )
            total = 0
            ocr_pages = 0
            for number, page in enumerate(pdf, 1):
                text = normalize(page.get_text(sort=True))
                if not text and ocr:
                    ocr_pages += 1
                    if ocr_pages > ocr_max_pages:
                        raise NeedsOCR(
                            "OCR page budget reached. Split the PDF or raise the explicit OCR page limit."
                        )
                    try:
                        textpage = page.get_textpage_ocr(language="eng", dpi=150, full=True)
                        text = normalize(page.get_text(textpage=textpage, sort=True))
                    except Exception as error:
                        raise NeedsOCR(
                            "Optional OCR is unavailable. Install Tesseract/English tessdata and configure TESSDATA_PREFIX, or upload a text export."
                        ) from error
                total += len(text)
                if total > max_chars:
                    raise ExtractionRejected(
                        "Extracted text exceeds the configured limit. Split the document."
                    )
                if text:
                    passages.append(Passage(text, page=number))
        if not passages:
            raise NeedsOCR(
                "No readable PDF text. Run OCR or upload a text-based PDF, Markdown, or TXT export."
            )
    elif extension == ".docx":
        passages = extract_docx(path, max_chars)
    else:
        try:
            text = path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            raise ExtractionRejected("Text files must use UTF-8 encoding.") from None
        if len(text) > max_chars:
            raise ExtractionRejected("Text exceeds the configured limit. Split the document.")
        if extension == ".txt":
            passages = [Passage(normalize(text))] if normalize(text) else []
        else:
            from .vaults import parse_markdown

            try:
                text = parse_markdown(text)["body"]
            except ValueError:
                raise ExtractionRejected(
                    "Invalid Markdown properties or links. Export plain Markdown and retry."
                ) from None
            headings: list[tuple[int, str]] = []
            lines: list[str] = []
            fenced = False

            def flush():
                if normalize("\n".join(lines)):
                    passages.append(
                        Passage(
                            normalize("\n".join(lines)), heading=" / ".join(h for _, h in headings) or None
                        )
                    )
                lines.clear()

            for line in text.splitlines():
                if line.lstrip().startswith(("```", "~~~")):
                    fenced = not fenced
                match = re.match(r"^(#{1,6})\s+(.+?)\s*#*\s*$", line) if not fenced else None
                if match:
                    flush()
                    level = len(match[1])
                    headings = [(n, h) for n, h in headings if n < level] + [(level, match[2])]
                lines.append(line)
            flush()
    if not passages:
        raise ExtractionRejected("Document has no readable text. Add text and upload again.")
    return passages


def split_passage(text: str, size: int, overlap: int):
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            # Prefer sentence/line boundaries in the final half, then a word boundary.
            window = text[start + size // 2 : end]
            boundaries = list(re.finditer(r"[.!?]\s+|\n+", window))
            if boundaries:
                end = start + size // 2 + boundaries[-1].end()
            elif " " in window:
                end = start + size // 2 + window.rfind(" ") + 1
        piece = text[start:end]
        left = len(piece) - len(piece.lstrip())
        piece = piece.strip()
        if piece:
            yield piece, start + left, start + left + len(piece)
        if end == len(text):
            break
        start = max(start + 1, end - overlap)


def extract_docx(path, max_chars):
    """Text/headings/tables only; never evaluate fields, external relationships or embedded objects."""
    import zipfile
    from xml.etree import ElementTree as ET

    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        if len(entries) > 2000 or sum(i.file_size for i in entries) > 30_000_000:
            raise ExtractionRejected("DOCX archive exceeds the extraction limits.")
        if any(i.flag_bits & 1 or i.file_size / max(1, i.compress_size) > 100 for i in entries):
            raise ExtractionRejected("Unsafe DOCX encryption or compression ratio.")
        if "word/document.xml" not in archive.namelist() or "[Content_Types].xml" not in archive.namelist():
            raise ExtractionRejected("Invalid DOCX package.")
        raw = archive.read("word/document.xml")
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper() or len(raw) > 10_000_000:
        raise ExtractionRejected("Unsafe DOCX XML declaration or size.")
    root = ET.fromstring(raw)
    passages, lines, headings, total = [], [], [], 0

    def flush():
        if lines:
            passages.append(
                Passage(normalize("\n".join(lines)), heading=" / ".join(h for _, h in headings) or None)
            )
            lines.clear()

    body = root.find("w:body", namespace)
    if body is None:
        raise ExtractionRejected("DOCX has no document body.")
    for element in body:
        text = normalize(" ".join(t.text or "" for t in element.findall(".//w:t", namespace)))
        if not text:
            continue
        total += len(text)
        if total > max_chars:
            raise ExtractionRejected("Extracted text exceeds the configured limit. Split the document.")
        style = element.find("w:pPr/w:pStyle", namespace)
        name = style.get("{" + namespace["w"] + "}val", "") if style is not None else ""
        match = re.fullmatch(r"Heading([1-6])", name, re.IGNORECASE)
        if match:
            flush()
            level = int(match[1])
            headings = [(n, h) for n, h in headings if n < level] + [(level, text)]
        if element.tag.endswith("}tbl"):
            for row in element.findall("w:tr", namespace):
                cells = [
                    normalize(" ".join(t.text or "" for t in cell.findall(".//w:t", namespace)))
                    for cell in row.findall("w:tc", namespace)
                ]
                lines.append(" | ".join(cells))
        else:
            lines.append(text)
    flush()
    return passages


def parser_environment():
    environment = os.environ.copy()
    paths = [str(Path(__file__).resolve().parents[1])]
    paths.extend(path for path in environment.get("PYTHONPATH", "").split(os.pathsep) if path)
    # Hosted runtimes can also add bundled dependencies directly to the parent interpreter.
    paths.extend(path for path in sys.path if os.path.isabs(path))
    environment["PYTHONPATH"] = os.pathsep.join(dict.fromkeys(paths))
    return environment


PARSER_ERRORS = {
    "start_failed": "The extraction process could not start. Contact the deployment operator.",
    "dependency_missing": "A document parser dependency is unavailable. Contact the deployment operator.",
    "exit_failed": "The extraction process exited unexpectedly. Retry or contact the deployment operator.",
    "timeout": "Extraction exceeded its process time limit. Split the file or retry with a larger explicit limit.",
    "invalid_output": "The extraction process returned invalid output. Retry or contact the deployment operator.",
    "output_limit": "Extraction exceeded its output limit. Split the document into smaller files.",
    "parser_failed": "Document parser failed. Export a valid text document and retry.",
    "invalid_request": "The extraction process could not read its request. Contact the deployment operator.",
}


def bounded_extract(path, extension, settings):
    options = {
        "max_chars": settings.max_source_characters,
        "max_pages": settings.max_pdf_pages,
        "ocr": settings.ocr_enabled,
        "ocr_max_pages": settings.ocr_max_pages,
    }
    if not settings.isolated_extraction:
        return extract(path, extension, **options)

    started = time.monotonic()

    def failed(reason, result=None):
        # Parser stderr can contain document text, absolute paths, or environment details.
        exit_code = result.returncode if isinstance(result, subprocess.CompletedProcess) else None
        logger.warning(
            "extraction_failed reason=%s format=%s exit=%s elapsed_ms=%s stdout_bytes=%s stderr_bytes=%s",
            reason,
            extension,
            exit_code,
            round((time.monotonic() - started) * 1000),
            len(result.stdout or b"") if result is not None else None,
            len(result.stderr or b"") if result is not None else None,
        )
        return ExtractionRejected(PARSER_ERRORS[reason])

    try:
        payload = json.dumps({"path": str(path), "extension": extension, **options}, ensure_ascii=False)
        result = subprocess.run(
            [sys.executable, "-B", "-P", "-X", "utf8", "-m", "nexus.extract_worker"],
            input=payload.encode("utf-8"),
            capture_output=True,
            timeout=settings.extraction_timeout_seconds,
            env=parser_environment(),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired as error:
        raise failed("timeout", error) from None
    except OSError:
        raise failed("start_failed") from None
    except UnicodeEncodeError:
        raise failed("invalid_request") from None
    if result.returncode:
        raise failed("exit_failed", result)
    limit = parser_output_limit(settings.max_source_characters)
    if len(result.stdout) > limit * 4:
        raise failed("output_limit", result)
    try:
        serialized = result.stdout.decode("utf-8")
    except UnicodeDecodeError:
        raise failed("invalid_output", result) from None
    if len(serialized) > limit:
        raise failed("output_limit", result)
    try:
        output = json.loads(serialized)
    except (ValueError, RecursionError):
        raise failed("invalid_output", result) from None
    if not isinstance(output, dict):
        raise failed("invalid_output", result)
    status = output.get("status")
    if isinstance(status, str) and status in PARSER_ERRORS:
        raise failed(status, result)
    if status in ("rejected", "needs_ocr"):
        message = output.get("message")
        if isinstance(message, str) and 0 < len(message) <= 500:
            raise (NeedsOCR if status == "needs_ocr" else ExtractionRejected)(message)
    if status == "ok":
        passages = output.get("passages")
        if (
            isinstance(passages, list)
            and passages
            and all(
                isinstance(item, dict)
                and item.keys() == {"text", "page", "heading"}
                and isinstance(item["text"], str)
                and (item["heading"] is None or isinstance(item["heading"], str))
                and (item["page"] is None or (type(item["page"]) is int and item["page"] >= 1))
                for item in passages
            )
        ):
            return [Passage(**item) for item in passages]
    raise failed("invalid_output", result)
