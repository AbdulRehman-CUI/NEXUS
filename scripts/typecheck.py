"""Scoped static checking of configuration/API contracts, without persistent caches."""

import os
import subprocess
import sys

raise SystemExit(
    subprocess.call(
        [
            sys.executable,
            "-m",
            "mypy",
            "--follow-imports=skip",
            "--cache-dir",
            os.devnull,
            "apps/api/nexus/config.py",
            "apps/api/nexus/contracts.py",
        ]
    )
)
