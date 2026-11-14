"""Stage the shared package and reject incomplete hosted dependency installs."""
import importlib
import sys
import tomllib
from pathlib import Path
from shutil import copytree
from tempfile import TemporaryDirectory
from types import SimpleNamespace

service = Path(__file__).resolve().parent
manifest = tomllib.loads((service / "pyproject.toml").read_text())
requirements = (service / "requirements.txt").read_text().splitlines()
if set(manifest["project"]["dependencies"]) != set(requirements):
    raise RuntimeError("Hosted pyproject dependencies and CI requirements must match.")
for module in (
    "fastapi", "uvicorn", "sqlalchemy", "alembic", "psycopg", "pymupdf",
    "pydantic_settings", "httpx", "python_multipart", "yaml", "onnxruntime",
    "tokenizers", "huggingface_hub", "numpy", "cryptography",
):
    importlib.import_module(module)
copytree(service.parents[1] / "apps" / "api" / "nexus", service / "nexus", dirs_exist_ok=True)

# Check the staged entrypoint in a fresh child, including native PDF and Markdown imports.
sys.path.insert(0, str(service))
bounded_extract = importlib.import_module("nexus.extraction").bounded_extract
pymupdf = importlib.import_module("pymupdf")
settings = SimpleNamespace(
    isolated_extraction=True, max_source_characters=2_000_000, max_pdf_pages=1000,
    ocr_enabled=False, ocr_max_pages=20, extraction_timeout_seconds=45,
)
with TemporaryDirectory(prefix="nexus-parser-build-") as directory:
    pdf_path = Path(directory) / "café.pdf"
    with pymupdf.open() as pdf:
        pdf.new_page().insert_text((72, 72), "café")
        pdf_path.write_bytes(pdf.tobytes())
    md_path = Path(directory) / "اردو.md"
    md_path.write_text("---\ntitle: اردو\n---\n# اردو\ncafé", encoding="utf-8")
    for path, expected in ((pdf_path, "café"), (md_path, "# اردو café")):
        passages = bounded_extract(path, path.suffix, settings)
        if [passage.text for passage in passages] != [expected]:
            raise RuntimeError("Staged extraction smoke test returned unexpected text.")
print("Staged extraction smoke test passed (PDF and Markdown).")
