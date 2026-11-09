"""Verified stopped backups. No endpoint takes arbitrary filesystem destinations."""

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import stat
import zipfile
from pathlib import Path, PurePosixPath

from .lease import DataLease


def file_hash(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def check_sql(path):
    with sqlite3.connect(path) as connection:
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("SQLite integrity check failed.")
        if connection.execute("PRAGMA foreign_key_check").fetchone():
            raise ValueError("SQLite foreign-key check failed.")
        return connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]


def backup(root, output, include_models=False):
    root, output = Path(root).resolve(), Path(output).resolve()
    if output.is_relative_to(root):
        raise ValueError("Place backups outside the data directory.")
    if not (root / "nexus.sqlite3").is_file():
        raise ValueError("No NEXUS database found.")
    with DataLease(root):
        version = check_sql(root / "nexus.sqlite3")
        with sqlite3.connect(root / "nexus.sqlite3") as connection:
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        files = []
        for path in sorted(root.rglob("*")):
            if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
                raise ValueError("Backup refuses symbolic links or junctions.")
            if not path.is_file():
                continue
            relative = path.relative_to(root).as_posix()
            if (
                relative == ".nexus.lock"
                or relative.endswith(("-wal", "-shm"))
                or (not include_models and relative.startswith("models/"))
            ):
                continue
            if path.stat().st_nlink > 1 or not stat.S_ISREG(path.stat().st_mode):
                raise ValueError("Backup refuses hardlinks or nonregular files.")
            # Known data stores only; .env and arbitrary operator files are never bundled.
            if relative not in {"nexus.sqlite3", "provider.json"} and not relative.startswith(
                ("originals/", "chroma/", "models/")
            ):
                continue
            files.append((relative, path))
        manifest = {
            "schema_version": 1,
            "database_revision": version,
            "models_included": include_models,
            "files": {
                name: {"sha256": file_hash(path), "bytes": path.stat().st_size} for name, path in files
            },
        }
        output.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive create prevents overwriting a valuable previous backup.
        with output.open("xb") as stream:
            with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_STORED) as archive:
                archive.writestr("manifest.json", json.dumps(manifest, sort_keys=True))
                for name, path in files:
                    archive.write(path, name)
        os.chmod(output, 0o600)
        return {"files": len(files), "bytes": output.stat().st_size, "database_revision": version}


def restore(archive_path, target):
    target = Path(target).resolve()
    if target.exists():
        raise ValueError("Restore requires a new nonexistent directory; existing data is never overwritten.")
    with zipfile.ZipFile(archive_path) as archive:
        entries = archive.infolist()
        names = [i.filename for i in entries]
        if (
            len(names) != len(set(names))
            or len(names) > 200000
            or sum(i.file_size for i in entries) > 10_000_000_000
        ):
            raise ValueError("Invalid backup archive bounds or duplicate paths.")
        for item in entries:
            from .vaults import safe_relative

            safe_relative(item.filename)
            path = PurePosixPath(item.filename)
            if (
                path.is_absolute()
                or any(p in {"..", "."} or ":" in p or "\\" in p for p in path.parts)
                or stat.S_IFMT(item.external_attr >> 16) not in {0, stat.S_IFREG}
            ):
                raise ValueError("Unsafe backup entry.")
        if archive.getinfo("manifest.json").file_size > 20_000_000:
            raise ValueError("Backup manifest too large.")
        manifest = json.loads(archive.read("manifest.json"))
        if manifest.get("schema_version") != 1 or set(names) != set(manifest["files"]) | {"manifest.json"}:
            raise ValueError("Backup manifest mismatch.")
        for name, info in manifest["files"].items():
            digest = hashlib.sha256()
            length = 0
            with archive.open(name) as source:
                for part in iter(lambda: source.read(1024 * 1024), b""):
                    length += len(part)
                    digest.update(part)
            if length != info["bytes"] or digest.hexdigest() != info["sha256"]:
                raise ValueError("Backup checksum mismatch. Nothing was restored.")
        target.mkdir(parents=True, exist_ok=False)
        with DataLease(target):
            marker = target / ".restoring"
            marker.write_text("Incomplete restores must not be served.")
            for name in manifest["files"]:
                output = target / name
                output.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(name) as source, output.open("xb") as destination:
                    shutil.copyfileobj(source, destination, length=1024 * 1024)
            version = check_sql(target / "nexus.sqlite3")
            if version != manifest["database_revision"]:
                raise ValueError("Restored schema revision mismatch; incomplete restore remains blocked.")
            # Sessions from backups must not revive logged-out/expired credentials.
            with sqlite3.connect(target / "nexus.sqlite3") as connection:
                if connection.execute("SELECT name FROM sqlite_master WHERE name='auth_sessions'").fetchone():
                    connection.execute("DELETE FROM auth_sessions")
                if connection.execute(
                    "SELECT name FROM sqlite_master WHERE name='guest_sessions'"
                ).fetchone():
                    # Keep the nonce tombstones so a retry cannot restore access.
                    connection.execute("UPDATE guest_sessions SET expires_at = 0")
            marker.unlink()
    return {
        "restored": True,
        "files": len(manifest["files"]),
        "database_revision": version,
        "sessions_revoked": True,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="operation", required=True)
    save = sub.add_parser("backup")
    save.add_argument("--data", type=Path, required=True)
    save.add_argument("--output", type=Path, required=True)
    save.add_argument("--include-models", action="store_true")
    load = sub.add_parser("restore")
    load.add_argument("--archive", type=Path, required=True)
    load.add_argument("--target", type=Path, required=True)
    args = parser.parse_args()
    result = (
        backup(args.data, args.output, args.include_models)
        if args.operation == "backup"
        else restore(args.archive, args.target)
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
