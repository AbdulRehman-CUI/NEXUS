"""Opt-in local folder scanner. The HTTP server never receives or reads a folder path."""

import argparse
import hashlib
import io
import json
import os
import time
import zipfile
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from .config import Settings
from .vaults import excluded, safe_relative


def folder_snapshot(root: Path, settings: Settings):
    if root.is_symlink() or (hasattr(root, "is_junction") and root.is_junction()):
        raise ValueError("Select a real vault folder, not a symlink or junction.")
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Vault root must be a directory.")
    files, total, visited = [], 0, 0
    pending = [root]
    while pending:
        directory = pending.pop()
        for entry in sorted(os.scandir(directory), key=lambda e: e.name):
            visited += 1
            if visited > settings.max_vault_files * 4:
                raise ValueError("Folder scan exceeded its entry limit. Exclude caches or split the vault.")
            path = Path(entry.path)
            relative = safe_relative(path.relative_to(root).as_posix())
            if entry.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
                raise ValueError("Vault symlinks and junctions are unsupported, including ignored folders.")
            if excluded(relative, settings.vault_excludes):
                continue
            if not path.resolve(strict=True).is_relative_to(root):
                raise ValueError("Vault scan escaped its approved root.")
            if entry.is_dir(follow_symlinks=False):
                pending.append(path)
                continue
            if not entry.is_file(follow_symlinks=False):
                raise ValueError("Vault contains a device or special file.")
            if path.suffix.lower() != ".md":
                continue
            before = path.stat(follow_symlinks=False)
            if before.st_nlink > 1:
                raise ValueError("Vault hardlinks are unsupported; copy the note into the approved root.")
            if before.st_size > settings.max_note_bytes:
                raise ValueError("A vault note exceeds the per-file size limit.")
            flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
            with os.fdopen(os.open(path, flags), "rb") as source:
                opened = os.fstat(source.fileno())
                data = source.read(settings.max_note_bytes + 1)
            after = path.stat(follow_symlinks=False)
            if (
                (before.st_ino, before.st_dev, before.st_size, before.st_mtime_ns)
                != (after.st_ino, after.st_dev, after.st_size, after.st_mtime_ns)
                or opened.st_ino != before.st_ino
                or not path.resolve().is_relative_to(root)
            ):
                raise ValueError("A note changed during the scan. Retry a stable snapshot.")
            total += len(data)
            if (
                len(data) > settings.max_note_bytes
                or total > settings.max_vault_bytes
                or len(files) >= settings.max_vault_files
            ):
                raise ValueError("Vault scan exceeds its configured size/file limits.")
            files.append((relative, data))
    files.sort()
    manifest = hashlib.sha256(
        json.dumps([(p, hashlib.sha256(data).hexdigest()) for p, data in files], ensure_ascii=False).encode()
    ).hexdigest()
    archive = io.BytesIO()
    # Stored entries avoid compression-bomb ambiguity and are bounded by the same total byte limit.
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_STORED) as output:
        for relative, data in files:
            output.writestr(relative, data)
    if len(archive.getvalue()) > settings.max_upload_mb * 1024 * 1024:
        raise ValueError("Folder snapshot exceeds the configured upload size limit.")
    return archive.getvalue(), manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--vault-id")
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--interval", type=int, default=15)
    parser.add_argument("--once", action="store_true")
    parser.add_argument(
        "--username", help="Optional server-profile account; password is prompted, never saved."
    )
    parser.add_argument(
        "--password-stdin",
        action="store_true",
        help="Automation only: read a password line from a protected pipe, never an argument.",
    )
    args = parser.parse_args()
    if args.password_stdin and not args.username:
        parser.error("--password-stdin requires --username.")
    origin = urlsplit(args.api)
    if (
        origin.scheme != "http"
        or origin.hostname not in {"localhost", "127.0.0.1"}
        or origin.username
        or origin.password
        or origin.path not in {"", "/"}
    ):
        parser.error("--api must be a loopback HTTP origin. Remote folder transfer is not supported.")
    if args.interval < 5:
        parser.error("--interval must be at least five seconds.")
    settings, previous = Settings(), None
    with httpx.Client(
        base_url=args.api.rstrip("/"), timeout=60, follow_redirects=False, trust_env=False
    ) as client:
        if args.username:
            import getpass
            import sys

            password = (
                sys.stdin.readline(258).rstrip("\r\n")
                if args.password_stdin
                else getpass.getpass("Server password: ")
            )

            response = client.post(
                "/api/auth/login",
                json={"username": args.username, "password": password},
            )
            response.raise_for_status()
            client.headers["X-CSRF-Token"] = response.json()["csrf"]
        else:
            identity = client.get("/api/auth/me")
            if identity.status_code == 401:
                raise SystemExit("Server profile requires --username. No folder was scanned or transmitted.")
        while True:
            try:
                archive, manifest = folder_snapshot(args.root, settings)
                requested = False
                if args.vault_id:
                    status = client.get(
                        f"/api/vaults/{args.vault_id}/sync-status", params={"workspace_id": args.workspace}
                    )
                    status.raise_for_status()
                    requested = bool(status.json()["vault"]["scan_requested_at"])
                if previous != manifest or requested:
                    if args.vault_id:
                        path, params = f"/api/vaults/{args.vault_id}/sync", {"workspace_id": args.workspace}
                    else:
                        path, params = (
                            f"/api/workspaces/{args.workspace}/vaults/import",
                            {"name": args.root.name, "source_kind": "agent"},
                        )
                    response = client.post(
                        path, params=params, files={"file": ("vault.zip", archive, "application/zip")}
                    )
                    response.raise_for_status()
                    args.vault_id = response.json()["vault"]["id"]
                    previous = manifest
                    print(
                        f"Vault {args.vault_id}: snapshot accepted; indexing status is available in the vault manager.",
                        flush=True,
                    )
                if args.once:
                    break
            except (ValueError, OSError, httpx.HTTPError) as error:
                if args.once:
                    raise SystemExit(
                        f"Scan failed: {type(error).__name__}. Check the folder and local API."
                    ) from error
                print(
                    f"Scan warning: {type(error).__name__}. No partial snapshot sent; retrying next interval.",
                    flush=True,
                )
            time.sleep(args.interval)


if __name__ == "__main__":
    main()
