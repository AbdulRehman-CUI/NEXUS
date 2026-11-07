"""Stage the shared Python package inside the service's function bundle."""
from pathlib import Path
from shutil import copytree

service = Path(__file__).resolve().parent
copytree(service.parents[1] / "apps" / "api" / "nexus", service / "nexus", dirs_exist_ok=True)
