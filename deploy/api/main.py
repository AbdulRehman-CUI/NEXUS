"""Vercel's native FastAPI entrypoint."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "api"))
os.environ.setdefault("NEXUS_HOSTED", "true")
os.environ.setdefault("NEXUS_DATA_DIR", "/tmp/nexus")
from nexus.main import app  # noqa: E402,F401
