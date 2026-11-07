"""Create a private runtime master-key file. Existing keys are never overwritten or printed."""

import argparse
import base64
import csv
import os
import subprocess
from pathlib import Path


def create_master_key(target, data_dir):
    target, data_dir = Path(target).resolve(), Path(data_dir).resolve()
    if target.is_relative_to(data_dir):
        raise ValueError("Store the master key outside NEXUS_DATA_DIR and its backups.")
    if target.exists():
        raise ValueError(
            "A key already exists. Never overwrite a key used by encrypted credentials."
        )
    # Restrict only a dedicated secrets directory, never an arbitrary parent/home directory.
    if target.parent.name not in {".secrets", "nexus-secrets"}:
        raise ValueError("Use a dedicated .secrets or nexus-secrets directory.")
    if target.parent.is_symlink() or (
        hasattr(target.parent, "is_junction") and target.parent.is_junction()
    ):
        raise ValueError("Secrets directories cannot be symbolic links or junctions.")
    if target.parent.exists() and any(target.parent.iterdir()):
        raise ValueError("Use an empty dedicated secrets directory; existing keys are never modified.")
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name == "nt":
        # An empty dedicated directory can safely discard pre-existing explicit grants.
        subprocess.run(["icacls", str(target.parent), "/reset"], capture_output=True, check=True)
        identity = subprocess.run(
            ["whoami", "/user", "/fo", "csv", "/nh"],
            capture_output=True,
            text=True,
            check=True,
        )
        sid = next(csv.reader(identity.stdout.splitlines()))[1]
        subprocess.run(
            [
                "icacls",
                str(target.parent),
                "/inheritance:r",
                "/grant:r",
                f"*{sid}:(OI)(CI)F",
                "*S-1-5-18:(OI)(CI)F",
            ],
            capture_output=True,
            check=True,
        )
    else:
        target.parent.chmod(0o700)
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as output:
        output.write(base64.b64encode(os.urandom(32)) + b"\n")
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, default=Path(".secrets/byok-master.key"))
    parser.add_argument("--data", type=Path, default=Path("data"))
    args = parser.parse_args()
    try:
        path = create_master_key(args.file, args.data)
    except (ValueError, OSError, subprocess.SubprocessError):
        parser.exit(
            1,
            "No master key created. Check the dedicated directory, permissions and existing-key safeguards.\n",
        )
    print(
        f"Master key created with private permissions at {path}. Key material was not printed."
    )
    print(
        f"Set NEXUS_BYOK_MASTER_KEY_FILE={path} in the API runtime configuration, then restart the API."
    )
