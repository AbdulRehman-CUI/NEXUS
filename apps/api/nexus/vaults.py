import fnmatch
import hashlib
import io
import json
import posixpath
import re
import stat
import struct
import unicodedata
import zipfile
from collections import Counter
from pathlib import PurePosixPath
from urllib.parse import unquote, urlencode, urlsplit

import yaml
from fastapi import HTTPException
from sqlalchemy import delete, func, or_, select
from yaml.tokens import AliasToken, AnchorToken

from .database import Document, Note, NoteLink, NoteTag, SyncRun, Vault, now, uid

IGNORED = {".obsidian", ".git", ".trash", "__macosx", "node_modules"}
DEVICES = re.compile(r"^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)", re.I)


def safe_relative(raw):
    path = unicodedata.normalize("NFC", raw)
    if not path or len(path) > 512 or path.startswith(("/", "\\")) or "\\" in path:
        raise ValueError("Vault paths must be safe relative paths, without drive or network prefixes.")
    parts = path.split("/")
    if any(
        not part
        or part in {".", ".."}
        or part.endswith((".", " "))
        or DEVICES.match(part)
        or re.search(r'[\x00-\x1f:<>"|?*]', part)
        for part in parts
    ):
        raise ValueError("Vault contains an unsafe, device, or traversal path.")
    return path


def excluded(path, patterns):
    parts = PurePosixPath(path).parts
    return any(
        part.casefold() in IGNORED or any(fnmatch.fnmatchcase(part, pattern) for pattern in patterns)
        for part in parts
    )


def parse_markdown(text):
    metadata, body = {}, text
    if text.startswith("---\n") or text.startswith("---\r\n"):
        match = re.match(r"\A---\r?\n(.*?)\r?\n(?:---|\.\.\.)\s*(?:\r?\n|$)", text, re.S)
        if not match or len(match[1].encode()) > 16384:
            raise ValueError("Frontmatter must be terminated safe YAML under 16 KB.")
        try:
            if any(isinstance(token, (AliasToken, AnchorToken)) for token in yaml.scan(match[1])):
                raise ValueError("YAML anchors and aliases are unsupported; use plain properties.")
            parsed = yaml.safe_load(match[1]) or {}
        except yaml.YAMLError as error:
            raise ValueError("Invalid safe YAML frontmatter. Export plain scalar/list properties.") from error
        if not isinstance(parsed, dict) or len(parsed) > 100:
            raise ValueError("Frontmatter must be a small property mapping.")
        for key in ("title", "aliases", "tags"):
            value = parsed.get(key)
            if value is not None:
                if not isinstance(value, (str, list)) or (
                    isinstance(value, list)
                    and (len(value) > 100 or any(not isinstance(v, str) for v in value))
                ):
                    raise ValueError(f"Frontmatter {key} must be text or a short list of strings.")
                metadata[key] = value
        body = text[match.end() :]
    # Ignore fenced code and inline code when interpreting relationships; it remains source data.
    without_code = re.sub(r"(?ms)^\s*(```|~~~).*?^\s*\1[^\n]*$", "", body)
    without_code = re.sub(r"`[^`\n]+`", "", without_code)
    front_tags = metadata.get("tags", [])
    if isinstance(front_tags, str):
        front_tags = re.split(r"[,\s]+", front_tags)
    tags = set(t.lstrip("#") for t in front_tags if t.strip())
    tags.update(re.findall(r"(?<![\w/#])#([\w/-]+)", without_code, re.UNICODE))
    tags = sorted(t for t in tags if len(t) <= 100 and re.fullmatch(r"[\w/-]+", t, re.UNICODE))[:100]
    aliases = metadata.get("aliases", [])
    if isinstance(aliases, str):
        aliases = [aliases]
    headings = [m[1].strip().rstrip("#").strip() for m in re.finditer(r"(?m)^#{1,6}\s+(.+)$", without_code)]
    blocks = re.findall(r"(?m)\^([\w-]+)\s*$", without_code)
    links = []
    for match in re.finditer(r"(!?)\[\[([^\]\n]+)\]\]", without_code):
        destination, _, label = match[2].partition("|")
        target, _, anchor = destination.partition("#")
        links.append(
            {
                "target": target.strip(),
                "anchor": anchor.strip() or None,
                "label": label.strip() or destination,
                "kind": "embed" if match[1] else "wikilink",
            }
        )
    for match in re.finditer(r"(!?)\[([^\]\n]*)\]\(([^\n)]+)\)", without_code):
        destination = match[3].strip().split(' "', 1)[0].strip("<>")
        target, _, anchor = unquote(destination).partition("#")
        links.append(
            {
                "target": target,
                "anchor": anchor or None,
                "label": match[2] or target,
                "kind": "embed" if match[1] else "markdown",
            }
        )
    if len(links) > 1000:
        raise ValueError("A note exceeds the 1000-link limit. Split it into smaller notes.")
    return {
        "title": str(metadata.get("title", ""))[:300],
        "aliases": aliases[:100],
        "tags": tags,
        "headings": headings[:1000],
        "blocks": blocks[:1000],
        "links": links,
        "body": body,
    }


def read_vault_zip(content, settings):
    if len(content) > settings.max_upload_mb * 1024 * 1024:
        raise ValueError("Vault ZIP exceeds the upload limit.")
    notes, total, seen = [], 0, set()
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            entries = archive.infolist()
            if len(entries) > settings.max_vault_files:
                raise ValueError("Vault ZIP exceeds the file-count limit, including ignored entries.")
            for info in entries:
                path = safe_relative(info.filename.rstrip("/"))
                mode = info.external_attr >> 16
                if stat.S_IFMT(mode) not in {0, stat.S_IFREG, stat.S_IFDIR}:
                    raise ValueError("Vault archives cannot contain symlinks, devices, or special files.")
                extra = info.extra
                while extra:
                    if len(extra) < 4:
                        raise ValueError("Malformed ZIP metadata.")
                    kind, size = struct.unpack("<HH", extra[:4])
                    if kind not in {0x0001, 0x000A, 0x5455, 0x7075, 0x6375, 0x7875} or len(extra) < 4 + size:
                        raise ValueError("Unsupported ZIP link/extra metadata; export a regular-file ZIP.")
                    extra = extra[4 + size :]
                if info.flag_bits & 1:
                    raise ValueError("Encrypted vault ZIPs are unsupported.")
                total += info.file_size
                if info.file_size > settings.max_note_bytes or total > settings.max_vault_bytes:
                    raise ValueError("Vault exceeds per-file or total uncompressed size limits.")
                if info.file_size / max(1, info.compress_size) > settings.max_zip_ratio:
                    raise ValueError("Vault ZIP exceeds the decompression-ratio limit.")
                canonical = path.casefold()
                if canonical in seen:
                    raise ValueError("Duplicate or case-colliding paths in vault ZIP.")
                seen.add(canonical)
                if (
                    info.is_dir()
                    or excluded(path, settings.vault_excludes)
                    or not path.lower().endswith(".md")
                ):
                    continue
                with archive.open(info) as source:
                    data = source.read(settings.max_note_bytes + 1)
                if len(data) != info.file_size or len(data) > settings.max_note_bytes:
                    raise ValueError("Vault file exceeds declared size.")
                text = data.decode("utf-8-sig")
                if any(ord(c) < 32 and c not in "\n\r\t" for c in text):
                    raise ValueError("Vault notes must be UTF-8 text without binary controls.")
                parsed = parse_markdown(text)
                parsed.pop("body")
                notes.append(
                    {"path": path, "hash": hashlib.sha256(data).hexdigest(), "data": data, "metadata": parsed}
                )
    except (zipfile.BadZipFile, UnicodeError, RuntimeError) as error:
        raise ValueError("Invalid vault ZIP or UTF-8 note. Export a regular, unencrypted ZIP.") from error
    return sorted(notes, key=lambda n: n["path"])


def resolve_link(source, link, notes):
    raw = link["target"]
    if raw.startswith(("/", "\\")) or "\\" in raw or "\x00" in raw:
        return None, "blocked", []
    try:
        scheme = urlsplit(raw).scheme.lower()
    except ValueError:
        return None, "blocked", []
    if scheme:
        return None, "external" if scheme in {"http", "https", "mailto"} else "blocked", []
    target = unicodedata.normalize("NFC", raw)
    if not target:
        candidates = [source]
    else:
        if not PurePosixPath(target).suffix:
            target += ".md"
        relative = posixpath.normpath(posixpath.join(posixpath.dirname(source.path), target))
        if relative.startswith("../") or target.startswith("../") and relative == "..":
            return None, "blocked", []
        direct = [note for note in notes if note.path.casefold() == relative.casefold()]
        root = [note for note in notes if note.path.casefold() == target.casefold()]
        candidates = direct or root
        if not candidates and "/" not in target:
            stem = PurePosixPath(target).stem.casefold()
            candidates = [note for note in notes if PurePosixPath(note.path).stem.casefold() == stem]
        if not candidates:
            return None, "unresolved", []
    if len(candidates) != 1:
        return None, "ambiguous", sorted(n.path for n in candidates)
    note = candidates[0]
    anchor = link.get("anchor")
    status = "resolved"
    if anchor:
        values = note.metadata_json.get("blocks" if anchor.startswith("^") else "headings", [])
        if anchor.lstrip("^").casefold() not in {v.casefold() for v in values}:
            status = "missing_anchor"
    return note.id, status, []


class VaultService:
    def __init__(self, service):
        self.service = service

    def prepare(self, workspace_id, content, name=None, vault_id=None, source_kind="snapshot"):
        try:
            entries = read_vault_zip(content, self.service.settings)
        except ValueError as error:
            raise HTTPException(415, str(error)) from error
        if not entries and not vault_id:
            raise HTTPException(415, "No Markdown notes found. Select a vault ZIP containing .md files.")
        manifest_hash = hashlib.sha256(
            json.dumps([(e["path"], e["hash"]) for e in entries], ensure_ascii=False).encode()
        ).hexdigest()
        staged = []
        try:
            with self.service.lock, self.service.sessions.begin() as session:
                self.service.repo.workspace(session, workspace_id)
                vault = (
                    self.service.repo.get(session, Vault, vault_id, workspace_id)
                    if vault_id
                    else Vault(
                        workspace_id=workspace_id,
                        name=(name or "Imported vault")[:100],
                        source_kind=source_kind,
                    )
                )
                if not vault_id:
                    session.add(vault)
                    session.flush()
                active = session.scalar(
                    select(SyncRun).where(
                        SyncRun.vault_id == vault.id, SyncRun.status.in_(["queued", "processing"])
                    )
                )
                if active:
                    if active.manifest_hash == manifest_hash:
                        return vault, active
                    raise HTTPException(
                        409,
                        "This vault has a pending sync. Finish or retry it before replacing the manifest.",
                    )
                previous = session.scalar(
                    select(SyncRun).where(SyncRun.vault_id == vault.id).order_by(SyncRun.created_at.desc())
                )
                if previous and previous.status == "failed":
                    previous.status = "superseded"
                known = list(session.scalars(select(Note).where(Note.vault_id == vault.id)))
                intact = {n.path: n.content_hash for n in known if not n.deleted and n.status == "ready"}
                if (
                    previous
                    and previous.status == "ready"
                    and previous.manifest_hash == manifest_hash
                    and intact == {e["path"]: e["hash"] for e in entries}
                ):
                    vault.last_scan, vault.scan_requested_at = now(), None
                    return vault, previous
                by_path = {n.path: n for n in known}
                desired_paths = {e["path"] for e in entries}
                removed = [n for n in known if not n.deleted and n.path not in desired_paths]
                new_hashes = Counter(e["hash"] for e in entries if e["path"] not in by_path)
                old_hashes = Counter(n.content_hash for n in removed)
                counts = {"created": 0, "updated": 0, "renamed": 0, "deleted": 0, "unchanged": 0}
                manifest, renamed = [], set()
                for entry in entries:
                    note = by_path.get(entry["path"])
                    if note is None and new_hashes[entry["hash"]] == old_hashes[entry["hash"]] == 1:
                        note = next(n for n in removed if n.content_hash == entry["hash"])
                        renamed.add(note.id)
                        note.path = entry["path"]
                        counts["renamed"] += 1
                    elif note is None:
                        note = Note(
                            workspace_id=workspace_id,
                            vault_id=vault.id,
                            path=entry["path"],
                            content_hash=entry["hash"],
                        )
                        session.add(note)
                        session.flush()
                        counts["created"] += 1
                    changed = (
                        note.content_hash != entry["hash"]
                        or note.deleted
                        or note.document_id is None
                        or note.status == "failed"
                    )
                    if changed and note.document_id is not None:
                        counts["updated"] += 1
                    if not changed and note.id not in renamed:
                        counts["unchanged"] += 1
                    note.deleted, note.updated_at = False, now()
                    if changed:
                        note.status = "pending"  # revoke old retrieval before the new bytes are indexed
                    entry_metadata = entry["metadata"]
                    note.tags, note.metadata_json = entry_metadata["tags"], entry_metadata
                    note.content_hash = entry["hash"]
                    session.execute(delete(NoteTag).where(NoteTag.note_id == note.id))
                    session.add_all(
                        NoteTag(note_id=note.id, tag=tag, workspace_id=workspace_id) for tag in note.tags
                    )
                    if changed:
                        key = f"{uid()}.stage"
                        self.service.files.write(key, entry["data"])
                        staged.append(key)
                        manifest.append(
                            {
                                "note_id": note.id,
                                "path": entry["path"],
                                "hash": entry["hash"],
                                "storage_key": key,
                            }
                        )
                for note in removed:
                    if note.id not in renamed:
                        note.deleted, note.status, note.updated_at = True, "deleted", now()
                        counts["deleted"] += 1
                        session.execute(delete(NoteTag).where(NoteTag.note_id == note.id))
                        session.execute(
                            delete(NoteLink).where(
                                or_(NoteLink.source_id == note.id, NoteLink.target_id == note.id)
                            )
                        )
                run = SyncRun(
                    workspace_id=workspace_id,
                    vault_id=vault.id,
                    manifest_hash=manifest_hash,
                    manifest=manifest,
                    counts=counts,
                    attempts=1,
                )
                session.add(run)
                vault.status, vault.error = "queued", None
                session.flush()
            self.service.wake.set()
            return vault, run
        except Exception:
            for key in staged:
                self.service.files.delete(key)
            raise

    def resolve(self, session, vault_id, workspace_id):
        notes = list(
            session.scalars(
                select(Note).where(
                    Note.vault_id == vault_id, Note.workspace_id == workspace_id, Note.deleted.is_(False)
                )
            )
        )
        session.execute(
            delete(NoteLink).where(NoteLink.vault_id == vault_id, NoteLink.workspace_id == workspace_id)
        )
        for source in notes:
            for ordinal, link in enumerate(source.metadata_json.get("links", [])):
                target_id, status, candidates = resolve_link(source, link, notes)
                link_id = hashlib.sha256(
                    f"{source.id}:{ordinal}:{json.dumps(link, sort_keys=True)}".encode()
                ).hexdigest()
                session.add(
                    NoteLink(
                        id=link_id,
                        workspace_id=workspace_id,
                        vault_id=vault_id,
                        source_id=source.id,
                        target_id=target_id,
                        target=link["target"],
                        label=link["label"],
                        kind=link["kind"],
                        anchor=link.get("anchor"),
                        status=status,
                        candidates=candidates,
                    )
                )

    def process_one(self):
        with self.service.lock:
            with self.service.sessions.begin() as session:
                run = session.scalar(
                    select(SyncRun)
                    .where(SyncRun.status.in_(["queued", "processing"]))
                    .order_by(SyncRun.created_at)
                )
                if run is None:
                    return False
                run.status = "processing"
                run_id, vault_id, workspace_id = run.id, run.vault_id, run.workspace_id
                session.get(Vault, vault_id).status = "processing"
                entry = run.manifest[run.cursor] if run.cursor < len(run.manifest) else None
            try:
                if entry:
                    data = self.service.files.read(entry["storage_key"])
                    if hashlib.sha256(data).hexdigest() != entry["hash"]:
                        raise ValueError("Staged note failed its content hash check.")
                    result = self.service.upload(
                        workspace_id, PurePosixPath(entry["path"]).name, "text/markdown", data, origin="vault"
                    )
                    with self.service.sessions.begin() as session:
                        note = self.service.repo.get(session, Note, entry["note_id"], workspace_id)
                        if note.path != entry["path"] or note.content_hash != entry["hash"] or note.deleted:
                            raise ValueError("The note manifest changed during indexing.")
                        note.document_id = result["document"]["id"]
                        state = result["document"]["status"]
                        note.status = (
                            "ready"
                            if state == "ready"
                            else ("failed" if state in {"failed", "needs_ocr"} else "pending")
                        )
                        session.get(SyncRun, run_id).cursor += 1
                    # Staging is retained through success so retries can repeat an interrupted step safely.
                    return True
                with self.service.sessions.begin() as session:
                    notes = list(
                        session.scalars(
                            select(Note).where(Note.vault_id == vault_id, Note.deleted.is_(False))
                        )
                    )
                    if any(n.status == "failed" for n in notes):
                        raise ValueError(
                            "One or more notes failed indexing. Retry the sync after fixing the local embedding/runtime issue."
                        )
                    if any(n.status == "pending" for n in notes):
                        return False
                    self.resolve(session, vault_id, workspace_id)
                    vault, stored = session.get(Vault, vault_id), session.get(SyncRun, run_id)
                    vault.status, vault.last_scan, vault.error, vault.scan_requested_at = (
                        "ready",
                        now(),
                        None,
                        None,
                    )
                    stored.status, stored.error = "ready", None
                    staging = [e["storage_key"] for e in stored.manifest]
                    for previous in session.scalars(
                        select(SyncRun).where(SyncRun.vault_id == vault_id, SyncRun.status == "superseded")
                    ):
                        staging.extend(e["storage_key"] for e in previous.manifest)
                for key in staging:
                    self.service.files.delete(key)
                self.cleanup_superseded(workspace_id)
            except Exception as error:
                with self.service.sessions.begin() as session:
                    stored, vault = session.get(SyncRun, run_id), session.get(Vault, vault_id)
                    stored.status = vault.status = "failed"
                    stored.error = vault.error = (
                        "Sync failed. Check note ingestion errors and local storage, then retry (up to three attempts)."
                    )
                self.service.log_failure("vault_sync", run_id, error)
            return True

    def cleanup_superseded(self, workspace_id):
        with self.service.sessions() as session:
            unused = list(
                session.scalars(
                    select(Document.id).where(
                        Document.workspace_id == workspace_id,
                        Document.origin == "vault",
                        Document.status.not_in(["deleting", "queued", "processing"]),
                        ~select(Note.id)
                        .where(Note.document_id == Document.id, Note.deleted.is_(False))
                        .exists(),
                    )
                )
            )
        for document_id in unused:
            self.service.enqueue(workspace_id, document_id, "delete")

    def retry(self, workspace_id, vault_id):
        with self.service.lock, self.service.sessions.begin() as session:
            vault = self.service.repo.get(session, Vault, vault_id, workspace_id)
            run = session.scalar(
                select(SyncRun).where(SyncRun.vault_id == vault_id).order_by(SyncRun.created_at.desc())
            )
            if run is None or run.status != "failed" or run.attempts >= 3:
                raise HTTPException(
                    409,
                    "Retry requires a failed sync with fewer than three attempts. Upload a new snapshot otherwise.",
                )
            run.status, run.error, vault.status, vault.error = "queued", None, "queued", None
            run.attempts += 1
            # Index jobs that failed are retried through their existing note/document pointer.
            failed = list(
                session.scalars(
                    select(Note.document_id).where(
                        Note.vault_id == vault_id, Note.status == "failed", Note.deleted.is_(False)
                    )
                )
            )
        for document_id in failed:
            if document_id:
                self.service.enqueue(workspace_id, document_id)
        self.service.wake.set()
        return vault, run

    def graph(self, session, workspace_id, vault_id=None, tag=None, kind=None, query="", limit=150):
        self.service.repo.workspace(session, workspace_id)
        if vault_id:
            self.service.repo.get(session, Vault, vault_id, workspace_id)
        selection = select(Note).where(Note.workspace_id == workspace_id, Note.deleted.is_(False))
        if vault_id:
            selection = selection.where(Note.vault_id == vault_id)
        if tag:
            selection = selection.where(
                select(NoteTag.note_id)
                .where(NoteTag.note_id == Note.id, NoteTag.tag == tag, NoteTag.workspace_id == workspace_id)
                .exists()
            )
        if query:
            selection = selection.where(Note.path.icontains(query, autoescape=True))
        total = session.scalar(select(func.count()).select_from(selection.subquery()))
        notes = list(session.scalars(selection.order_by(Note.path).limit(limit)))
        ids = [n.id for n in notes]
        nodes = [
            {
                "id": n.id,
                "label": n.path,
                "type": "note",
                "status": n.status,
                "tags": n.tags,
                "source_url": f"/api/documents/{n.document_id}/source?"
                + urlencode({"workspace_id": workspace_id, "note_id": n.id})
                if n.document_id and n.status == "ready"
                else None,
            }
            for n in notes
        ]
        links = session.scalars(
            select(NoteLink).where(
                NoteLink.workspace_id == workspace_id,
                NoteLink.source_id.in_(ids),
                NoteLink.target_id.in_(ids),
                NoteLink.status.in_(["resolved", "missing_anchor"]),
            )
        )
        edges = [
            {
                "id": e.id,
                "source": e.source_id,
                "target": e.target_id,
                "type": e.kind,
                "provenance": "authored",
            }
            for e in links
            if not kind or e.kind == kind
        ]
        if not kind or kind == "tag":
            tag_ids = {}
            for note in notes:
                for value in note.tags:
                    tag_id = "tag:" + hashlib.sha256(f"{workspace_id}:{value}".encode()).hexdigest()[:20]
                    if value not in tag_ids:
                        if len(nodes) >= limit * 2:
                            continue
                        tag_ids[value] = tag_id
                        nodes.append({"id": tag_id, "label": "#" + value, "type": "tag", "source_url": None})
                    edges.append(
                        {
                            "id": f"{note.id}:{tag_id}",
                            "source": note.id,
                            "target": tag_id,
                            "type": "tag",
                            "provenance": "authored",
                        }
                    )
        return {
            "nodes": nodes,
            "edges": edges,
            "total_notes": total,
            "shown_notes": len(notes),
            "truncated": total > len(notes),
        }
