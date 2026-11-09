"""Vercel's native FastAPI entrypoint (package staged by build.py)."""
import os

os.environ.setdefault("NEXUS_HOSTED", "true")
os.environ.setdefault("NEXUS_DATA_DIR", "/tmp/nexus")
from nexus.main import app  # noqa: E402,F401
