import os
import re
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4


class FileStorage:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, key: str) -> Path:
        candidate = (self.root / key).resolve()
        if not candidate.is_relative_to(self.root) or candidate == self.root:
            raise ValueError("Invalid storage path")
        return candidate

    def write(self, key: str, content: bytes):
        target = self.path(key)
        temporary = self.path(f"{uuid4()}.tmp")
        try:
            with temporary.open("xb") as file:
                file.write(content)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)

    def delete(self, key: str):
        self.path(key).unlink(missing_ok=True)

    def read(self, key: str):
        return self.path(key).read_bytes()

    @contextmanager
    def materialize(self, key: str):
        yield self.path(key)


class DatabaseFileStorage:
    def __init__(self, sessions):
        self.sessions = sessions

    def write(self, key: str, content: bytes, session=None):
        from .database import StoredFile

        if session is not None:
            session.add(StoredFile(key=key, content=content))
        else:
            with self.sessions.begin() as writer:
                self.write(key, content, writer)

    def read(self, key: str, session=None):
        from .database import StoredFile

        if session is None:
            with self.sessions() as reader:
                return self.read(key, reader)
        row = session.get(StoredFile, key)
        if row is None:
            raise FileNotFoundError()
        return row.content

    def delete(self, key: str, session=None):
        from sqlalchemy import delete

        from .database import StoredFile

        if session is not None:
            session.execute(delete(StoredFile).where(StoredFile.key == key))
        else:
            with self.sessions.begin() as writer:
                self.delete(key, writer)

    @contextmanager
    def materialize(self, key: str):
        with TemporaryDirectory(prefix="nexus-source-") as directory:
            path = Path(directory) / key
            path.write_bytes(self.read(key))
            yield path


def validate_upload(filename: str, mime: str, content: bytes) -> tuple[str, str]:
    if (
        not filename
        or len(filename) > 180
        or re.search(r'[\x00-\x1f\\/:<>"|?*]', filename)
        or filename in {".", ".."}
    ):
        raise ValueError("Use a plain filename without folders or special path characters.")
    extension = Path(filename).suffix.lower()
    allowed = {
        ".pdf": {"application/pdf", "application/octet-stream"},
        ".md": {"text/markdown", "text/plain", "application/octet-stream"},
        ".txt": {"text/plain", "application/octet-stream"},
        ".docx": {
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/octet-stream",
        },
    }
    if extension not in allowed:
        raise ValueError("Unsupported format. Upload PDF, Markdown (.md), TXT or DOCX.")
    if mime.split(";")[0].lower() not in allowed[extension]:
        raise ValueError("The file type does not match its extension.")
    if not content:
        raise ValueError("The file is empty.")
    if extension == ".pdf":
        if not content.startswith(b"%PDF-"):
            raise ValueError("Invalid PDF signature. Export a valid PDF and retry.")
    elif extension == ".docx":
        if not content.startswith(b"PK\x03\x04"):
            raise ValueError("Invalid DOCX package signature.")
        import io
        import zipfile

        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                entries = archive.infolist()
                if not {"word/document.xml", "[Content_Types].xml"}.issubset(archive.namelist()):
                    raise ValueError("Invalid DOCX package.")
                if (
                    len(entries) > 2000
                    or sum(i.file_size for i in entries) > 30_000_000
                    or any(i.flag_bits & 1 or i.file_size / max(1, i.compress_size) > 100 for i in entries)
                ):
                    raise ValueError("DOCX archive exceeds the safety limits.")
        except zipfile.BadZipFile as error:
            raise ValueError("Invalid DOCX package.") from error
    else:
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise ValueError("Text files must use UTF-8 encoding.") from error
        if "\x00" in text or any(ord(c) < 32 and c not in "\n\r\t" for c in text):
            raise ValueError("This appears to be binary data. Upload a UTF-8 text export.")
        if content.startswith((b"%PDF", b"PK\x03\x04", b"MZ")):
            raise ValueError("File signature does not match a text document.")
    return filename.strip(), extension
