"""Stage the shared package and reject incomplete hosted dependency installs."""
import importlib
import tomllib
from pathlib import Path
from shutil import copytree

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
