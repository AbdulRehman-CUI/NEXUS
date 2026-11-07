import re
from dataclasses import dataclass
from pathlib import Path

import pymupdf


class NeedsOCR(ValueError):
    pass


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
        with pymupdf.open(path) as pdf:
            if pdf.needs_pass:
                raise ValueError("Password-protected PDF. Export an unlocked text-based PDF and retry.")
            if len(pdf) > max_pages:
                raise ValueError(f"PDF exceeds the {max_pages}-page limit. Split it into smaller files.")
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
                    raise ValueError("Extracted text exceeds the configured limit. Split the document.")
                if text:
                    passages.append(Passage(text, page=number))
        if not passages:
            raise NeedsOCR(
                "No readable PDF text. Run OCR or upload a text-based PDF, Markdown, or TXT export."
            )
    elif extension == ".docx":
        passages = extract_docx(path, max_chars)
    else:
        text = path.read_text(encoding="utf-8-sig")
        if len(text) > max_chars:
            raise ValueError("Text exceeds the configured limit. Split the document.")
        if extension == ".txt":
            passages = [Passage(normalize(text))] if normalize(text) else []
        else:
            from .vaults import parse_markdown

            text = parse_markdown(text)["body"]
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
        raise ValueError("Document has no readable text. Add text and upload again.")
    return passages


def split_passage(text: str, size: int, overlap: int):
    from llama_index.core.node_parser import SentenceSplitter

    # Character tokenizer avoids hidden tokenizer downloads in offline mode.
    splitter = SentenceSplitter(chunk_size=size, chunk_overlap=overlap, tokenizer=list)
    previous_start = -1
    for piece in splitter.split_text(text):
        start = text.find(piece, previous_start + 1)
        if start < 0:
            raise ValueError("Chunk could not be mapped to its normalized source span.")
        end = start + len(piece)
        yield piece, start, end
        previous_start = start


def extract_docx(path, max_chars):
    """Text/headings/tables only; never evaluate fields, external relationships or embedded objects."""
    import zipfile
    from xml.etree import ElementTree as ET

    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        if len(entries) > 2000 or sum(i.file_size for i in entries) > 30_000_000:
            raise ValueError("DOCX archive exceeds the extraction limits.")
        if any(i.flag_bits & 1 or i.file_size / max(1, i.compress_size) > 100 for i in entries):
            raise ValueError("Unsafe DOCX encryption or compression ratio.")
        if "word/document.xml" not in archive.namelist() or "[Content_Types].xml" not in archive.namelist():
            raise ValueError("Invalid DOCX package.")
        raw = archive.read("word/document.xml")
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper() or len(raw) > 10_000_000:
        raise ValueError("Unsafe DOCX XML declaration or size.")
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
        raise ValueError("DOCX has no document body.")
    for element in body:
        text = normalize(" ".join(t.text or "" for t in element.findall(".//w:t", namespace)))
        if not text:
            continue
        total += len(text)
        if total > max_chars:
            raise ValueError("Extracted text exceeds the configured limit. Split the document.")
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


def bounded_extract(path, extension, settings):
    if not settings.isolated_extraction:
        return extract(
            path,
            extension,
            settings.max_source_characters,
            settings.max_pdf_pages,
            settings.ocr_enabled,
            settings.ocr_max_pages,
        )
    import json
    import os
    import subprocess
    import sys

    environment = {
        key: value
        for key, value in os.environ.items()
        if not any(secret in key.upper() for secret in ("KEY", "TOKEN", "SECRET", "PASSWORD"))
    }
    environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    payload = json.dumps(
        {
            "path": str(path),
            "extension": extension,
            "max_chars": settings.max_source_characters,
            "max_pages": settings.max_pdf_pages,
            "ocr": settings.ocr_enabled,
            "ocr_max_pages": settings.ocr_max_pages,
        }
    )
    try:
        result = subprocess.run(
            [sys.executable, "-m", "nexus.extract_worker"],
            input=payload,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=settings.extraction_timeout_seconds,
            env=environment,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired as error:
        raise ValueError(
            "Extraction exceeded its process time limit. Split the file or retry with a larger explicit limit."
        ) from error
    if result.returncode or len(result.stdout) > settings.max_source_characters * 8 + 100_000:
        raise ValueError("Extraction process failed or exceeded its output limit.")
    output = json.loads(result.stdout)
    if output.get("needs_ocr"):
        raise NeedsOCR(output["error"])
    if output.get("error"):
        raise ValueError(output["error"])
    return [Passage(**p) for p in output["passages"]]
