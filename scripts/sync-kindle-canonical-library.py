#!/usr/bin/env python3
"""Safely plan or apply the canonical PW5SE library layout.

The normal invocation is read-only with respect to the Kindle.  It validates
the local Nutstore corpus, inventories the Kindle, and writes a JSON plan.  An
explicit ``--apply`` is required before any remote directory, file, sidecar,
or power setting is changed.

Book bytes always come from Nutstore.  Existing Kindle PDFs are used only when
their complete SHA-256 equals the canonical source.  Such files are renamed in
place before uploads begin, which avoids needlessly copying large PDFs over
Wi-Fi.  KOReader's adjacent ``book.sdr`` directory follows a moved book only
when the destination sidecar does not already exist.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import posixpath
import re
import secrets
import shlex
import signal
import stat
import sys
import tempfile
import time
import unicodedata
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

HOST_DEFAULT = "192.168.1.127"
PORT_DEFAULT = 2222
REMOTE_DOCUMENTS = "/mnt/us/documents"
REMOTE_NOTES_ROOT = f"{REMOTE_DOCUMENTS}/LinguaLeaf-Notes"
REMOTE_LEGACY_ROOT = f"{REMOTE_DOCUMENTS}/LinguaLeaf-Legacy-with-reading-state"
SAFETY_FREE_BYTES = 64 * 1024 * 1024
HASH_CHUNK = 4 * 1024 * 1024
LOCAL_REPLACE_RETRY_SECONDS = 3.0
LOCAL_REPLACE_INITIAL_DELAY = 0.025
LOCAL_REPLACE_MAX_DELAY = 0.250

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SHARE_ROOT = Path.home() / "Nutstore" / "1" / "Share"
DEFAULT_LINGUA_ROOT = SHARE_ROOT / "LinguaLeaf"
DEFAULT_LAZYEARN_ROOT = SHARE_ROOT / "LazyEarn"
DEFAULT_LAZYTRAVEL_ROOT = SHARE_ROOT / "LazyTravel"
DEFAULT_KEY = PROJECT_ROOT / "Handoff" / "keys" / "kindle_handoff_rsa"
DEFAULT_KNOWN_HOSTS = Path.home() / ".ssh" / "known_hosts"
DEFAULT_LEDGER = (
    PROJECT_ROOT / "device-backups" / "kindle-canonical-library-sync" / "resume.json"
)
DEFAULT_REPORT = (
    PROJECT_ROOT / "device-backups" / "kindle-canonical-library-sync" / "report.json"
)

ROOT_NOTES = (
    "CANONICAL-LIBRARY.json",
    "KINDLE-HANDOFF.md",
    "MIGRATION-AND-VERIFICATION-2026-08-26.md",
    "README.md",
    "REMOVED-AND-REPLACED.md",
)

KOREADER_PATH_FILES = (
    "/mnt/us/koreader/history.lua",
    "/mnt/us/koreader/settings.reader.lua",
)
MAX_KOREADER_PATH_FILE_BYTES = 64 * 1024 * 1024
CANONICAL_BLACKWHITE_COUNT = 286
CANONICAL_CATEGORY_COUNT = 29

STANDALONE_FILES: tuple[tuple[str, str], ...] = (
    ("LazyEarn", "How You Got Rich - V3 - Pocket 1.2x.pdf"),
    ("LazyEarn", "How You Got Rich - EN-JA-ZH Aligned - Pocket 1.2x.pdf"),
    ("LazyTravel", "LazyTravel-Hakone-ZH-JA-EN-B6-Pocket.pdf"),
    ("LazyTravel", "LazyTravel-Lanzhou-ZH-JA-EN-B6-Pocket.pdf"),
    ("LazyTravel", "LazyTravel-Xian-ZH-JA-EN-B6-Pocket.pdf"),
)

EXPECTED_TOP_CATEGORIES = {
    "01-Chinese-Classics",
    "02-Japanese-Literature",
    "03-World-Literature",
    "04-History-and-Civilization",
    "05-Philosophy-and-Religion",
    "06-Science-and-Technology",
    "07-Business-Wealth-and-Leadership",
    "08-Fantasy-and-Science-Fiction",
}

HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")
REMOTE_HASH_LINE = re.compile(rb"^([0-9a-fA-F]{64})(?:[ \t]|$)")


class SyncError(RuntimeError):
    """A fail-closed error whose message is safe to display."""


class SyncInterrupted(SyncError):
    """Raised for a handled termination signal."""


@dataclass(frozen=True)
class LocalItem:
    kind: str
    source: Path
    destination: str
    size: int
    sha256: str
    book_id: str | None = None


@dataclass(frozen=True)
class RemotePdf:
    path: str
    size: int
    mtime: int


@dataclass(frozen=True)
class SyncAction:
    action: str
    kind: str
    destination: str
    size: int
    sha256: str
    source_local: str | None = None
    source_remote: str | None = None
    sidecar_source: str | None = None
    sidecar_destination: str | None = None
    reason: str = ""


@dataclass(frozen=True)
class CleanupAction:
    cleanup_kind: str
    path: str
    canonical_target: str
    observed_sha256: str
    observed_size: int
    expected_target_sha256: str
    expected_target_size: int
    replacement_removed: str | None = None
    replacement_kept: str | None = None
    sidecar_source: str | None = None
    sidecar_destination: str | None = None
    reason: str = ""


@dataclass
class MetadataRewrite:
    path: str
    temporary: str
    original: bytes
    updated: bytes
    mode: int
    replacements: int


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def configure_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def _is_transient_local_replace_error(error: OSError) -> bool:
    return isinstance(error, PermissionError) or getattr(error, "winerror", None) in {
        5,
        32,
    }


def _replace_local_with_retry(temporary: Path, destination: Path) -> None:
    """Retry short-lived Windows destination locks without losing the old JSON."""
    deadline = time.monotonic() + LOCAL_REPLACE_RETRY_SECONDS
    delay = LOCAL_REPLACE_INITIAL_DELAY
    while True:
        try:
            os.replace(temporary, destination)
            return
        except OSError as error:
            if not _is_transient_local_replace_error(error):
                raise
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise SyncError(
                    "The local JSON destination remained locked after bounded retries."
                ) from error
            time.sleep(min(delay, remaining))
            delay = min(delay * 2, LOCAL_REPLACE_MAX_DELAY)


def write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="\n",
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
        delete=False,
    )
    temporary = Path(handle.name)
    try:
        with handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        _replace_local_with_retry(temporary, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()


def safe_name(value: str) -> str:
    value = unicodedata.normalize("NFC", value)
    if (
        value in {"", ".", ".."}
        or "/" in value
        or "\\" in value
        or any(ord(character) < 0x20 or ord(character) == 0x7F for character in value)
    ):
        raise SyncError("An unsafe filename was encountered.")
    return value


def safe_relative(value: str) -> str:
    if "\\" in value or "\x00" in value:
        raise SyncError("An unsafe relative path was encountered.")
    normalized = unicodedata.normalize("NFC", value)
    path = PurePosixPath(normalized)
    if (
        path.is_absolute()
        or not path.parts
        or any(
            part in {"", ".", ".."}
            or any(
                ord(character) < 0x20 or ord(character) == 0x7F for character in part
            )
            for part in path.parts
        )
    ):
        raise SyncError("An unsafe relative path was encountered.")
    return path.as_posix()


def remote_from_relative(relative: str) -> str:
    relative = safe_relative(relative)
    result = posixpath.normpath(posixpath.join(REMOTE_DOCUMENTS, relative))
    if not result.startswith(REMOTE_DOCUMENTS.rstrip("/") + "/"):
        raise SyncError("A remote path escaped the documents root.")
    return result


def remote_relative(path: str) -> str:
    normalized = posixpath.normpath(path)
    prefix = REMOTE_DOCUMENTS.rstrip("/") + "/"
    if not normalized.startswith(prefix):
        raise SyncError("A remote path escaped the documents root.")
    return safe_relative(normalized[len(prefix) :])


def sidecar_for_pdf(remote_pdf: str) -> str:
    path = PurePosixPath(remote_pdf)
    if path.suffix.casefold() != ".pdf":
        raise SyncError("A sidecar was requested for a non-PDF path.")
    return path.with_suffix(".sdr").as_posix()


def local_signature(state: os.stat_result) -> tuple[int, int, int, int]:
    return (
        int(state.st_dev),
        int(state.st_ino),
        int(state.st_size),
        int(state.st_mtime_ns),
    )


def hash_local_stable(
    path: Path,
    *,
    expect_pdf: bool,
    expected_size: int | None = None,
    expected_sha256: str | None = None,
) -> tuple[int, str]:
    try:
        before = path.lstat()
    except OSError as error:
        raise SyncError(f"A required local source is unavailable: {path}") from error
    if path.is_symlink() or not stat.S_ISREG(before.st_mode):
        raise SyncError(
            f"A required local source is not a regular, non-symlink file: {path}"
        )
    if expected_size is not None and int(before.st_size) != expected_size:
        raise SyncError(f"A canonical source has the wrong size: {path}")
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            header = handle.read(5)
            if expect_pdf and header != b"%PDF-":
                raise SyncError(
                    f"A requested source does not have a PDF header: {path}"
                )
            digest.update(header)
            for block in iter(lambda: handle.read(HASH_CHUNK), b""):
                digest.update(block)
    except SyncError:
        raise
    except OSError as error:
        raise SyncError(f"A required local source could not be read: {path}") from error
    try:
        after = path.lstat()
    except OSError as error:
        raise SyncError(
            f"A local source disappeared while it was read: {path}"
        ) from error
    if path.is_symlink() or local_signature(before) != local_signature(after):
        raise SyncError(f"A local source changed while it was read: {path}")
    result = digest.hexdigest()
    if expected_sha256 is not None and result != expected_sha256.casefold():
        raise SyncError(f"A canonical source failed its manifest SHA-256: {path}")
    return int(after.st_size), result


def validate_local_metadata(
    path: Path,
    *,
    expect_pdf: bool,
    expected_size: int | None = None,
) -> int:
    """Lightweight source gate for manifest-backed canonical PDFs."""
    try:
        before = path.lstat()
    except OSError as error:
        raise SyncError(f"A required local source is unavailable: {path}") from error
    if path.is_symlink() or not stat.S_ISREG(before.st_mode):
        raise SyncError(
            f"A required local source is not a regular, non-symlink file: {path}"
        )
    if expected_size is not None and int(before.st_size) != expected_size:
        raise SyncError(f"A canonical source has the wrong size: {path}")
    if expect_pdf:
        try:
            with path.open("rb") as handle:
                header = handle.read(5)
        except OSError as error:
            raise SyncError(
                f"A required local source could not be opened: {path}"
            ) from error
        if header != b"%PDF-":
            raise SyncError(f"A requested source does not have a PDF header: {path}")
    try:
        after = path.lstat()
    except OSError as error:
        raise SyncError(
            f"A local source disappeared while it was inspected: {path}"
        ) from error
    if path.is_symlink() or local_signature(before) != local_signature(after):
        raise SyncError(f"A local source changed while it was inspected: {path}")
    return int(after.st_size)


def load_manifest(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SyncError("CANONICAL-LIBRARY.json is missing or invalid.") from error
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != 2
        or not isinstance(value.get("rows"), list)
    ):
        raise SyncError("CANONICAL-LIBRARY.json has an unsupported schema.")
    replacements = value.get("replacements")
    if (
        not isinstance(replacements, list)
        or len(replacements) != 10
        or not all(isinstance(replacement, dict) for replacement in replacements)
    ):
        raise SyncError("The canonical replacement list is missing.")
    return value, replacements


def _source_item(
    *,
    kind: str,
    source: Path,
    destination: str,
    expect_pdf: bool,
    expected_size: int | None = None,
    expected_sha256: str | None = None,
    book_id: str | None = None,
    trust_manifest_hash: bool = False,
) -> LocalItem:
    if trust_manifest_hash:
        if expected_size is None or expected_sha256 is None:
            raise SyncError(
                "A manifest-backed item is missing size or SHA-256 metadata."
            )
        # Do not open Cloud Files placeholders while planning; the one-pass
        # upload checks both the PDF header and manifest SHA-256.
        size = validate_local_metadata(
            source, expect_pdf=False, expected_size=expected_size
        )
        digest = expected_sha256.casefold()
    else:
        size, digest = hash_local_stable(
            source,
            expect_pdf=expect_pdf,
            expected_size=expected_size,
            expected_sha256=expected_sha256,
        )
    return LocalItem(
        kind=kind,
        source=source,
        destination=safe_relative(destination),
        size=size,
        sha256=digest,
        book_id=book_id,
    )


def discover_sources(
    lingua_root: Path,
    lazyearn_root: Path,
    lazytravel_root: Path,
) -> tuple[list[LocalItem], list[dict[str, Any]], dict[str, Any]]:
    manifest_path = lingua_root / "CANONICAL-LIBRARY.json"
    manifest, replacements = load_manifest(manifest_path)
    items: list[LocalItem] = []
    categories: set[str] = set()
    book_ids: set[str] = set()
    if not all(isinstance(row, dict) for row in manifest["rows"]):
        raise SyncError("The canonical manifest contains a non-object row.")
    summary = manifest.get("summary")
    if (
        not isinstance(summary, dict)
        or summary.get("logical_book_count") != CANONICAL_BLACKWHITE_COUNT
        or summary.get("pdf_count") != CANONICAL_BLACKWHITE_COUNT * 2
        or len(manifest["rows"]) != CANONICAL_BLACKWHITE_COUNT * 2
    ):
        raise SyncError("The canonical manifest corpus totals are inconsistent.")
    black_rows = [row for row in manifest["rows"] if row.get("mode") == "blackwhite"]
    expected_count = manifest.get("summary", {}).get("by_mode", {}).get("blackwhite")
    if (
        not isinstance(expected_count, int)
        or expected_count != CANONICAL_BLACKWHITE_COUNT
        or len(black_rows) != CANONICAL_BLACKWHITE_COUNT
    ):
        raise SyncError("The black-and-white manifest row count is inconsistent.")

    for index, row in enumerate(black_rows, start=1):
        try:
            destination = safe_relative(str(row["destination"]))
            category = safe_relative(str(row["category"]))
            book_id = safe_relative(str(row["book_id"]))
            expected_size = int(row["bytes"])
            expected_sha = str(row["sha256"]).casefold()
        except (KeyError, TypeError, ValueError, SyncError) as error:
            raise SyncError("A black-and-white manifest row is invalid.") from error
        if not destination.startswith(
            "blackwhite/"
        ) or not destination.casefold().endswith(".pdf"):
            raise SyncError(
                "A black-and-white manifest destination is outside its mode tree."
            )
        if PurePosixPath(destination).parent.as_posix() != f"blackwhite/{category}":
            raise SyncError("A manifest category and destination disagree.")
        if expected_size <= 0 or not HEX_SHA256.fullmatch(expected_sha):
            raise SyncError("A canonical manifest checksum or size is invalid.")
        if book_id in book_ids:
            raise SyncError("A duplicate black-and-white book ID was found.")
        book_ids.add(book_id)
        categories.add(category)
        source = lingua_root.joinpath(*PurePosixPath(destination).parts)
        items.append(
            _source_item(
                kind="canonical-pdf",
                source=source,
                destination=f"LinguaLeaf/{destination}",
                expect_pdf=True,
                expected_size=expected_size,
                expected_sha256=expected_sha,
                book_id=book_id,
                trust_manifest_hash=True,
            )
        )
        if index % 25 == 0 or index == len(black_rows):
            print(f"Validated canonical PDF sources: {index}/{len(black_rows)}")

    top_categories = {PurePosixPath(category).parts[0] for category in categories}
    if (
        top_categories != EXPECTED_TOP_CATEGORIES
        or len(categories) != CANONICAL_CATEGORY_COUNT
    ):
        raise SyncError(
            "The manifest does not contain the expected eight category roots."
        )

    roots: Mapping[str, Path] = {
        "LazyEarn": lazyearn_root,
        "LazyTravel": lazytravel_root,
    }
    seen_standalones: set[tuple[str, str]] = set()
    for collection, filename in STANDALONE_FILES:
        filename = safe_name(filename)
        identity = (collection.casefold(), filename.casefold())
        if identity in seen_standalones:
            continue
        seen_standalones.add(identity)
        items.append(
            _source_item(
                kind="standalone-pdf",
                source=roots[collection] / filename,
                destination=f"{collection}/{filename}",
                expect_pdf=True,
            )
        )

    for filename in ROOT_NOTES:
        filename = safe_name(filename)
        items.append(
            _source_item(
                kind="note",
                source=lingua_root / filename,
                destination=f"LinguaLeaf-Notes/{filename}",
                expect_pdf=False,
            )
        )
    for category in sorted(categories, key=str.casefold):
        source = lingua_root.joinpath(
            "blackwhite", *PurePosixPath(category).parts, "README.md"
        )
        items.append(
            _source_item(
                kind="note",
                source=source,
                destination=f"LinguaLeaf-Notes/blackwhite/{category}/README.md",
                expect_pdf=False,
            )
        )

    destinations: set[str] = set()
    for item in items:
        folded = item.destination.casefold()
        if folded in destinations:
            raise SyncError("Two local items would collide on the Kindle.")
        destinations.add(folded)

    manifest_meta = {
        "path": str(manifest_path),
        "schemaVersion": manifest.get("schema_version"),
        "generatedAt": manifest.get("generated_at"),
        "blackwhiteRows": len(black_rows),
        "categories": len(categories),
        "sha256": hash_local_stable(manifest_path, expect_pdf=False)[1],
    }
    return items, replacements, manifest_meta


def remote_signature(state: Any) -> tuple[int, int]:
    return int(state.st_size), int(getattr(state, "st_mtime", 0))


class KindleConnection:
    """Strict, key-only Paramiko connection to one already-known Kindle."""

    def __init__(self, host: str, port: int, key: Path, known_hosts: Path) -> None:
        if not key.is_file() or key.is_symlink():
            raise SyncError("The configured Kindle private key is missing or unsafe.")
        if not known_hosts.is_file() or known_hosts.is_symlink():
            raise SyncError("The configured known_hosts file is missing or unsafe.")
        try:
            import paramiko
        except ImportError as error:  # pragma: no cover - environment guard
            raise SyncError("paramiko is required for Kindle SSH/SFTP sync.") from error
        self._paramiko = paramiko
        self.client = paramiko.SSHClient()
        try:
            self.client.load_host_keys(str(known_hosts))
            self.client.set_missing_host_key_policy(paramiko.RejectPolicy())
            self.client.connect(
                hostname=host,
                port=port,
                username="root",
                key_filename=str(key),
                look_for_keys=False,
                allow_agent=False,
                timeout=15,
                auth_timeout=15,
                banner_timeout=15,
            )
            transport = self.client.get_transport()
            if transport is None or not transport.is_active():
                raise SyncError("The Kindle SSH transport was not established.")
            transport.set_keepalive(30)
            self.sftp = self.client.open_sftp()
        except Exception as error:
            self.client.close()
            if isinstance(error, SyncError):
                raise
            raise SyncError(
                "Strict Kindle SSH failed; check the saved host key, device address, and key login."
            ) from error
        self._hash_cache: dict[str, tuple[tuple[int, int], str]] = {}

    def __enter__(self) -> "KindleConnection":
        return self

    def __exit__(self, *_: object) -> None:
        try:
            self.sftp.close()
        finally:
            self.client.close()

    def exec_checked(self, command: str, purpose: str, timeout: int = 300) -> bytes:
        _stdin, stdout, stderr = self.client.exec_command(command, timeout=timeout)
        payload = stdout.read()
        stderr.read()  # Never echo remote stderr; filenames may contain private data.
        code = stdout.channel.recv_exit_status()
        if code != 0:
            raise SyncError(f"{purpose} failed with remote exit code {code}.")
        return payload

    def lstat(self, path: str) -> Any | None:
        try:
            return self.sftp.lstat(path)
        except OSError as error:
            if getattr(error, "errno", None) == 2 or "No such file" in str(error):
                return None
            raise SyncError("A remote lstat operation failed.") from error

    @staticmethod
    def require_regular(path: str, state: Any | None) -> Any:
        if state is None:
            raise SyncError("A required remote file disappeared.")
        if stat.S_ISLNK(state.st_mode) or not stat.S_ISREG(state.st_mode):
            raise SyncError(f"A managed remote file is not regular: {path}")
        return state

    @staticmethod
    def require_directory(path: str, state: Any | None) -> Any:
        if state is None:
            raise SyncError("A required remote directory disappeared.")
        if stat.S_ISLNK(state.st_mode) or not stat.S_ISDIR(state.st_mode):
            raise SyncError(f"A managed remote directory is unsafe: {path}")
        return state

    def directory_state(self, path: str) -> Any | None:
        state = self.lstat(path)
        if state is not None:
            self.require_directory(path, state)
        return state

    def inventory_pdfs(self, root: str) -> list[RemotePdf]:
        root_state = self.lstat(root)
        if root_state is None:
            return []
        self.require_directory(root, root_state)
        found: list[RemotePdf] = []

        def walk(directory: str) -> None:
            try:
                entries = self.sftp.listdir_attr(directory)
            except OSError as error:
                raise SyncError("The Kindle library inventory failed.") from error
            for entry in entries:
                name = safe_name(entry.filename)
                child = posixpath.join(directory, name)
                if stat.S_ISLNK(entry.st_mode):
                    raise SyncError(
                        f"A symlink was found in the managed Kindle tree: {child}"
                    )
                if stat.S_ISDIR(entry.st_mode):
                    if not name.casefold().endswith(".sdr"):
                        walk(child)
                elif stat.S_ISREG(entry.st_mode):
                    if name.casefold().endswith(".pdf"):
                        found.append(
                            RemotePdf(
                                path=child,
                                size=int(entry.st_size),
                                mtime=int(getattr(entry, "st_mtime", 0)),
                            )
                        )
                else:
                    raise SyncError(
                        f"A special file was found in the managed Kindle tree: {child}"
                    )

        walk(root)
        return sorted(found, key=lambda row: row.path.casefold())

    def inventory_sidecar_pdfs(self, root: str) -> list[tuple[RemotePdf, str]]:
        """Return PDFs that have an exact adjacent same-stem .sdr directory."""
        result: list[tuple[RemotePdf, str]] = []
        for pdf in self.inventory_pdfs(root):
            sidecar = sidecar_for_pdf(pdf.path)
            state = self.lstat(sidecar)
            if state is not None:
                self.require_directory(sidecar, state)
                result.append((pdf, sidecar))
        return result

    def sha256_file(self, path: str, *, expected_size: int | None = None) -> str:
        state_before = self.require_regular(path, self.lstat(path))
        if expected_size is not None and int(state_before.st_size) != expected_size:
            raise SyncError("A remote file changed size before SHA-256 verification.")
        signature = remote_signature(state_before)
        cached = self._hash_cache.get(path)
        if cached is not None and cached[0] == signature:
            return cached[1]
        command = f"LC_ALL=C sha256sum {shlex.quote(path)}"
        output = self.exec_checked(command, "Remote SHA-256 verification", timeout=900)
        match = REMOTE_HASH_LINE.match(output.strip())
        if match is None:
            raise SyncError("The Kindle returned an invalid SHA-256 result.")
        digest = match.group(1).decode("ascii").casefold()
        state_after = self.require_regular(path, self.lstat(path))
        if remote_signature(state_after) != signature:
            raise SyncError("A remote file changed while it was hashed.")
        self._hash_cache[path] = (signature, digest)
        return digest

    def forget_hash(self, *paths: str) -> None:
        for path in paths:
            self._hash_cache.pop(path, None)

    def transfer_cached_hash(self, source: str, destination: str) -> None:
        cached = self._hash_cache.pop(source, None)
        self._hash_cache.pop(destination, None)
        if cached is None:
            return
        state = self.require_regular(destination, self.lstat(destination))
        self._hash_cache[destination] = (remote_signature(state), cached[1])

    def read_regular_bytes(self, path: str, maximum: int) -> tuple[bytes, int]:
        state_before = self.require_regular(path, self.lstat(path))
        if int(state_before.st_size) > maximum:
            raise SyncError("A managed metadata file is unexpectedly large.")
        try:
            with self.sftp.open(path, "rb") as handle:
                payload = handle.read()
        except OSError as error:
            raise SyncError("A managed metadata file could not be read.") from error
        state_after = self.require_regular(path, self.lstat(path))
        if remote_signature(state_after) != remote_signature(state_before):
            raise SyncError("A managed metadata file changed while it was read.")
        if len(payload) != int(state_after.st_size):
            raise SyncError("A managed metadata file was only partially read.")
        return payload, stat.S_IMODE(state_after.st_mode)

    def koreader_running(self) -> bool:
        """Use the Kindle's BusyBox process lookup without scanning every /proc entry."""
        output = self.exec_checked(
            "command -v pidof >/dev/null 2>&1 || exit 127; "
            "pidof reader.lua >/dev/null 2>&1; rc=$?; "
            "case $rc in 0) printf '1\\n';; 1) printf '0\\n';; *) exit $rc;; esac",
            "KOReader process inspection",
            timeout=15,
        ).strip()
        if output not in {b"0", b"1"}:
            raise SyncError("KOReader process inspection returned an invalid result.")
        return output == b"1"

    def assert_koreader_stopped(self) -> None:
        if self.koreader_running():
            raise SyncError(
                "KOReader is running; stop it before applying library moves."
            )

    def mkdirs(self, directory: str) -> None:
        normalized = posixpath.normpath(directory)
        prefix = REMOTE_DOCUMENTS.rstrip("/") + "/"
        if normalized != REMOTE_DOCUMENTS and not normalized.startswith(prefix):
            raise SyncError("A remote directory escaped the documents root.")
        root_state = self.lstat(REMOTE_DOCUMENTS)
        self.require_directory(REMOTE_DOCUMENTS, root_state)
        current = REMOTE_DOCUMENTS
        relative = normalized[len(REMOTE_DOCUMENTS) :].lstrip("/")
        for part in PurePosixPath(relative).parts if relative else ():
            safe_name(part)
            current = posixpath.join(current, part)
            existing = self.lstat(current)
            if existing is None:
                try:
                    self.sftp.mkdir(current)
                except OSError as error:
                    raise SyncError(
                        "A remote directory could not be created."
                    ) from error
            else:
                self.require_directory(current, existing)

    def available_bytes(self) -> int:
        output = self.exec_checked("LC_ALL=C df -Pk /mnt/us", "Kindle free-space check")
        lines = [
            line.split() for line in output.decode("ascii", "replace").splitlines()
        ]
        candidates = [
            fields for fields in lines if len(fields) >= 6 and fields[-1] == "/mnt/us"
        ]
        if len(candidates) != 1 or not candidates[0][-3].isdigit():
            raise SyncError("The Kindle free-space result was not understood.")
        return int(candidates[0][-3]) * 1024

    def prevent_screen_saver(self) -> int:
        output = (
            self.exec_checked(
                "lipc-get-prop com.lab126.powerd preventScreenSaver",
                "Kindle keep-awake inspection",
            )
            .decode("ascii", "strict")
            .strip()
        )
        if output not in {"0", "1"}:
            raise SyncError("The Kindle returned an invalid keep-awake value.")
        return int(output)

    def set_prevent_screen_saver(self, value: int) -> None:
        if value not in {0, 1}:
            raise SyncError("An invalid Kindle keep-awake value was requested.")
        self.exec_checked(
            f"lipc-set-prop com.lab126.powerd preventScreenSaver {value}",
            "Kindle keep-awake update",
        )
        if self.prevent_screen_saver() != value:
            raise SyncError("The Kindle keep-awake update did not verify.")

    def has_open_file_handle(self, path: str) -> bool:
        if not path.startswith("/") or posixpath.normpath(path) != path:
            raise SyncError("The open-file audit target is unsafe.")

        def disappeared(error: OSError) -> bool:
            return getattr(error, "errno", None) in {2, 3} or "No such file" in str(
                error
            )

        try:
            processes = self.sftp.listdir_attr("/proc")
        except OSError as error:
            raise SyncError(
                "The Kindle open-file audit could not inspect /proc."
            ) from error
        for process in processes:
            if not process.filename.isdecimal():
                continue
            directory = f"/proc/{process.filename}/fd"
            try:
                descriptors = self.sftp.listdir_attr(directory)
            except OSError as error:
                if disappeared(error):
                    continue
                raise SyncError(
                    "The Kindle open-file audit could not inspect a process."
                ) from error
            for descriptor in descriptors:
                if not descriptor.filename.isdecimal():
                    continue
                try:
                    linked = self.sftp.readlink(
                        posixpath.join(directory, descriptor.filename)
                    )
                except OSError as error:
                    if disappeared(error):
                        continue
                    raise SyncError(
                        "The Kindle open-file audit could not inspect a descriptor."
                    ) from error
                if linked == path:
                    return True
        return False


class Ledger:
    SCHEMA = 1

    def __init__(
        self,
        path: Path,
        *,
        host: str,
        port: int,
        fingerprint: str,
        items: Sequence[LocalItem],
    ) -> None:
        self.path = path
        if path.exists():
            try:
                self.data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as error:
                raise SyncError("The local resume ledger is invalid.") from error
            if (
                self.data.get("schemaVersion") != self.SCHEMA
                or self.data.get("host") != host
                or self.data.get("port") != port
                or self.data.get("remoteDocuments") != REMOTE_DOCUMENTS
            ):
                raise SyncError(
                    "The local resume ledger belongs to a different target or schema."
                )
        else:
            self.data = {
                "schemaVersion": self.SCHEMA,
                "host": host,
                "port": port,
                "remoteDocuments": REMOTE_DOCUMENTS,
                "createdAt": now_iso(),
                "items": {},
                "cleanup": {},
                "history": [],
            }
        previous_fingerprint = self.data.get("planFingerprint")
        current_destinations = {item.destination for item in items}
        rows = self.data.setdefault("items", {})
        if previous_fingerprint and previous_fingerprint != fingerprint:
            if any(destination not in current_destinations for destination in rows):
                raise SyncError(
                    "The resume plan removed destinations; use a new ledger after review."
                )
            current_by_destination = {item.destination: item for item in items}
            for destination, row in rows.items():
                item = current_by_destination[destination]
                identity = {"size": item.size, "sha256": item.sha256, "kind": item.kind}
                if any(row.get(key) != value for key, value in identity.items()):
                    raise SyncError(
                        "The resume plan changed an existing destination; use a new ledger after review."
                    )
            self.data.setdefault("history", []).append(
                {
                    "event": "append-only-plan-extension",
                    "from": previous_fingerprint,
                    "to": fingerprint,
                    "at": now_iso(),
                }
            )
        self.data["planFingerprint"] = fingerprint
        for item in items:
            identity = {"size": item.size, "sha256": item.sha256, "kind": item.kind}
            existing = rows.get(item.destination)
            if existing is None:
                rows[item.destination] = {**identity, "status": "pending"}
            elif any(existing.get(key) != value for key, value in identity.items()):
                raise SyncError(
                    "The resume ledger identity differs from the current source plan."
                )
                rows[item.destination] = {**identity, "status": "pending"}
        self.save()

    def save(self) -> None:
        self.data["updatedAt"] = now_iso()
        write_json_atomic(self.path, self.data)

    def mark_item(self, destination: str, status: str, **details: Any) -> None:
        row = self.data["items"][destination]
        row.update(status=status, updatedAt=now_iso(), **details)
        self.save()

    def mark_cleanup(self, path: str, status: str, **details: Any) -> None:
        self.data.setdefault("cleanup", {})[path] = {
            "status": status,
            "updatedAt": now_iso(),
            **details,
        }
        self.save()

    def mark_legacy(self, path: str, status: str, **details: Any) -> None:
        self.data.setdefault("legacyPreservation", {})[path] = {
            "status": status,
            "updatedAt": now_iso(),
            **details,
        }
        self.save()

    def plan_path_rewrite(self, action: SyncAction) -> None:
        if action.source_remote is None:
            raise SyncError("A path-rewrite journal entry has no source.")
        rows = self.data.setdefault("pathRewriteJournal", {})
        identity = {
            "source": action.source_remote,
            "destination": action.destination,
            "size": action.size,
            "sha256": action.sha256,
        }
        existing = rows.get(action.source_remote)
        if existing is not None and any(
            existing.get(key) != value for key, value in identity.items()
        ):
            raise SyncError("A pending path-rewrite journal identity changed.")
        rows[action.source_remote] = {
            **identity,
            "status": "planned",
            "updatedAt": now_iso(),
        }
        self.save()

    def complete_path_rewrite(self, source: str, counts: Mapping[str, int]) -> None:
        row = self.data.setdefault("pathRewriteJournal", {}).get(source)
        if not isinstance(row, dict):
            raise SyncError("A path-rewrite journal entry is missing.")
        row.update(status="complete", historyRewrites=dict(counts), updatedAt=now_iso())
        self.save()

    def pending_path_rewrites(self) -> list[dict[str, Any]]:
        rows = self.data.get("pathRewriteJournal", {})
        if not isinstance(rows, dict):
            raise SyncError("The path-rewrite journal is invalid.")
        return [dict(row) for row in rows.values() if row.get("status") == "planned"]

    def keepawake(self, *, active: bool, original: int | None = None) -> None:
        value = self.data.setdefault("keepAwake", {})
        value.update(active=active, updatedAt=now_iso())
        if original is not None:
            value["original"] = original
        self.save()

    def stale_keepawake_original(self) -> int | None:
        value = self.data.get("keepAwake")
        if not isinstance(value, dict) or value.get("active") is not True:
            return None
        original = value.get("original")
        if original not in {0, 1}:
            raise SyncError("The resume ledger has invalid stale keep-awake state.")
        return int(original)


class KeepAwake:
    def __init__(self, connection: KindleConnection, ledger: Ledger) -> None:
        self.connection = connection
        self.ledger = ledger
        self.original: int | None = None

    def __enter__(self) -> "KeepAwake":
        self.original = self.connection.prevent_screen_saver()
        self.ledger.keepawake(active=True, original=self.original)
        try:
            if self.original != 1:
                self.connection.set_prevent_screen_saver(1)
        except Exception:
            try:
                if self.connection.prevent_screen_saver() != self.original:
                    self.connection.set_prevent_screen_saver(self.original)
                self.ledger.keepawake(active=False, original=self.original)
            except Exception as restore_error:
                raise SyncError(
                    "Keep-awake enable failed and its original value could not be restored."
                ) from restore_error
            raise
        return self

    def __exit__(self, error_type: object, error: object, traceback: object) -> None:
        if self.original is None:
            return
        try:
            if self.connection.prevent_screen_saver() != self.original:
                self.connection.set_prevent_screen_saver(self.original)
        except Exception as restore_error:
            self.ledger.keepawake(active=True, original=self.original)
            raise SyncError(
                "The original Kindle keep-awake value could not be restored."
            ) from restore_error
        self.ledger.keepawake(active=False, original=self.original)


def recover_stale_keepawake(connection: KindleConnection, ledger: Ledger) -> bool:
    """Restore a prior interrupted transaction before recording a new baseline."""
    original = ledger.stale_keepawake_original()
    if original is None:
        return False
    if connection.prevent_screen_saver() != original:
        connection.set_prevent_screen_saver(original)
    ledger.keepawake(active=False, original=original)
    return True


def items_fingerprint(items: Sequence[LocalItem]) -> str:
    rows = [
        {
            "kind": item.kind,
            "destination": item.destination,
            "size": item.size,
            "sha256": item.sha256,
        }
        for item in sorted(items, key=lambda value: value.destination.casefold())
    ]
    payload = json.dumps(
        rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def is_safe_sidecar(connection: KindleConnection, path: str) -> bool:
    state = connection.lstat(path)
    if state is None:
        return False
    connection.require_directory(path, state)
    return True


def choose_exact_candidate(
    connection: KindleConnection,
    candidates: Sequence[RemotePdf],
    destination: str,
) -> tuple[RemotePdf | None, str | None]:
    if not candidates:
        return None, None
    destination_sidecar = sidecar_for_pdf(destination)
    destination_has_sidecar = is_safe_sidecar(connection, destination_sidecar)
    usable: list[tuple[RemotePdf, bool]] = []
    rejected_for_conflict = False
    for candidate in candidates:
        source_has_sidecar = is_safe_sidecar(
            connection, sidecar_for_pdf(candidate.path)
        )
        if source_has_sidecar and destination_has_sidecar:
            rejected_for_conflict = True
            continue
        usable.append((candidate, source_has_sidecar))
    with_sidecars = [candidate for candidate, has_sidecar in usable if has_sidecar]
    if len(with_sidecars) == 1:
        return with_sidecars[0], None
    if len(with_sidecars) > 1:
        return (
            None,
            "multiple exact copies have sidecars; progress identity is ambiguous",
        )
    without_sidecars = [candidate for candidate, _has_sidecar in usable]
    if without_sidecars:
        return sorted(without_sidecars, key=lambda row: row.path.casefold())[0], None
    if rejected_for_conflict:
        return None, "an exact source and destination both have sidecars"
    return None, None


def plan_sync(
    items: Sequence[LocalItem],
    connection: KindleConnection,
) -> tuple[list[SyncAction], list[RemotePdf], list[dict[str, str]]]:
    inventory = connection.inventory_pdfs(f"{REMOTE_DOCUMENTS}/LinguaLeaf")
    by_size: dict[int, list[RemotePdf]] = defaultdict(list)
    for remote in inventory:
        by_size[remote.size].append(remote)
    canonical_targets = {
        remote_from_relative(item.destination)
        for item in items
        if item.kind == "canonical-pdf"
    }
    reserved_sources: set[str] = set()
    actions: list[SyncAction] = []
    conflicts: list[dict[str, str]] = []

    for item in items:
        target = remote_from_relative(item.destination)
        target_state = connection.lstat(target)
        if target_state is not None:
            connection.require_regular(target, target_state)
            if (
                int(target_state.st_size) == item.size
                and connection.sha256_file(target, expected_size=item.size)
                == item.sha256
            ):
                actions.append(
                    SyncAction(
                        action="reuse",
                        kind=item.kind,
                        destination=target,
                        size=item.size,
                        sha256=item.sha256,
                        source_local=str(item.source),
                        reason="existing destination has the expected complete SHA-256",
                    )
                )
                continue
            if item.kind == "standalone-pdf":
                old_sidecar = sidecar_for_pdf(target)
                old_sidecar_state = connection.lstat(old_sidecar)
                if old_sidecar_state is not None:
                    connection.require_directory(old_sidecar, old_sidecar_state)
                    old_size = int(target_state.st_size)
                    old_digest = connection.sha256_file(target, expected_size=old_size)
                    collection = PurePosixPath(item.destination).parts[0]
                    if collection not in {"LazyEarn", "LazyTravel"}:
                        raise SyncError(
                            "A standalone legacy collection is not recognized."
                        )
                    legacy_target = (
                        f"{REMOTE_DOCUMENTS}/{collection}-Legacy-with-reading-state/"
                        f"{PurePosixPath(target).name}"
                    )
                    legacy_sidecar = sidecar_for_pdf(legacy_target)
                    if (
                        connection.lstat(legacy_target) is not None
                        or connection.lstat(legacy_sidecar) is not None
                    ):
                        stem = PurePosixPath(target).stem
                        suffix = PurePosixPath(target).suffix
                        legacy_target = (
                            f"{REMOTE_DOCUMENTS}/{collection}-Legacy-with-reading-state/"
                            f"{stem}--legacy-{old_digest[:12]}{suffix}"
                        )
                        legacy_sidecar = sidecar_for_pdf(legacy_target)
                    if (
                        connection.lstat(legacy_target) is not None
                        or connection.lstat(legacy_sidecar) is not None
                    ):
                        raise SyncError(
                            "A mismatched standalone PDF + sidecar pair cannot be safely preserved."
                        )
                    actions.append(
                        SyncAction(
                            action="legacy-move",
                            kind="legacy-pdf",
                            destination=legacy_target,
                            size=old_size,
                            sha256=old_digest,
                            source_remote=target,
                            sidecar_source=old_sidecar,
                            sidecar_destination=legacy_sidecar,
                            reason=(
                                "changed standalone PDF and its old reading state are preserved together"
                            ),
                        )
                    )
            actions.append(
                SyncAction(
                    action="upload",
                    kind=item.kind,
                    destination=target,
                    size=item.size,
                    sha256=item.sha256,
                    source_local=str(item.source),
                    reason="destination exists but does not match the requested source",
                )
            )
            continue

        if item.kind == "canonical-pdf":
            exact: list[RemotePdf] = []
            for candidate in by_size.get(item.size, []):
                if (
                    candidate.path in canonical_targets
                    or candidate.path in reserved_sources
                ):
                    continue
                if (
                    connection.sha256_file(candidate.path, expected_size=item.size)
                    == item.sha256
                ):
                    exact.append(candidate)
            selected, conflict = choose_exact_candidate(connection, exact, target)
            if selected is not None:
                source_sidecar = sidecar_for_pdf(selected.path)
                destination_sidecar = sidecar_for_pdf(target)
                has_sidecar = is_safe_sidecar(connection, source_sidecar)
                reserved_sources.add(selected.path)
                actions.append(
                    SyncAction(
                        action="move",
                        kind=item.kind,
                        destination=target,
                        size=item.size,
                        sha256=item.sha256,
                        source_remote=selected.path,
                        sidecar_source=source_sidecar if has_sidecar else None,
                        sidecar_destination=destination_sidecar
                        if has_sidecar
                        else None,
                        reason="old Kindle PDF has the exact canonical SHA-256",
                    )
                )
                continue
            if conflict:
                conflicts.append({"destination": target, "reason": conflict})

        actions.append(
            SyncAction(
                action="upload",
                kind=item.kind,
                destination=target,
                size=item.size,
                sha256=item.sha256,
                source_local=str(item.source),
                reason="no safely movable exact Kindle copy was found",
            )
        )
    return actions, inventory, conflicts


def plan_legacy_sidecar_preservation(
    actions: Sequence[SyncAction],
    connection: KindleConnection,
) -> tuple[list[SyncAction], list[dict[str, str]]]:
    """Move incompatible legacy PDF+.sdr pairs out of the canonical tree.

    Exact canonical move sources carry their sidecars to the canonical path and
    exact reusable targets remain in place.  Every other sidecar-bearing PDF is
    kept together with its reading state in the sibling legacy tree; it is
    never attached to changed canonical bytes.
    """
    move_sources = {
        action.source_remote
        for action in actions
        if action.action in {"move", "legacy-move"} and action.source_remote is not None
    }
    exact_reuse_targets = {
        action.destination for action in actions if action.action == "reuse"
    }
    planned: list[SyncAction] = []
    conflicts: list[dict[str, str]] = []

    def preserve_pair(pdf: RemotePdf, sidecar: str, root: str, relative: str) -> None:
        relative = safe_relative(relative)
        digest = connection.sha256_file(pdf.path, expected_size=pdf.size)
        target = posixpath.join(root, relative)
        target_sidecar = sidecar_for_pdf(target)
        if (
            connection.lstat(target) is not None
            or connection.lstat(target_sidecar) is not None
        ):
            stem = PurePosixPath(relative).stem
            suffix = PurePosixPath(relative).suffix
            parent = PurePosixPath(relative).parent.as_posix()
            renamed = f"{stem}--legacy-{digest[:12]}{suffix}"
            relative = renamed if parent == "." else f"{parent}/{renamed}"
            target = posixpath.join(root, relative)
            target_sidecar = sidecar_for_pdf(target)
        if (
            connection.lstat(target) is not None
            or connection.lstat(target_sidecar) is not None
        ):
            conflicts.append(
                {
                    "path": pdf.path,
                    "reason": "legacy preservation destination is occupied; pair left untouched",
                }
            )
            return
        planned.append(
            SyncAction(
                action="legacy-move",
                kind="legacy-pdf",
                destination=target,
                size=pdf.size,
                sha256=digest,
                source_remote=pdf.path,
                sidecar_source=sidecar,
                sidecar_destination=target_sidecar,
                reason="older PDF and its incompatible reading state are preserved together",
            )
        )

    source_prefix = f"{REMOTE_DOCUMENTS}/LinguaLeaf/"
    for pdf, sidecar in connection.inventory_sidecar_pdfs(
        f"{REMOTE_DOCUMENTS}/LinguaLeaf"
    ):
        if pdf.path in move_sources or pdf.path in exact_reuse_targets:
            continue
        if not pdf.path.startswith(source_prefix):
            raise SyncError("A legacy sidecar PDF escaped the LinguaLeaf tree.")
        relative = safe_relative(pdf.path[len(source_prefix) :])
        preserve_pair(pdf, sidecar, REMOTE_LEGACY_ROOT, relative)

    # A changed standalone edition must not inherit a stale sidecar merely
    # because its filename stayed the same (notably LazyTravel Xian).
    for action in actions:
        if action.action != "upload" or action.kind != "standalone-pdf":
            continue
        if action.destination in move_sources:
            continue
        state = connection.lstat(action.destination)
        sidecar = sidecar_for_pdf(action.destination)
        sidecar_state = connection.lstat(sidecar)
        if state is None or sidecar_state is None:
            continue
        connection.require_regular(action.destination, state)
        connection.require_directory(sidecar, sidecar_state)
        collection = PurePosixPath(remote_relative(action.destination)).parts[0]
        if collection not in {"LazyEarn", "LazyTravel"}:
            raise SyncError("A standalone legacy collection is not recognized.")
        pdf = RemotePdf(
            path=action.destination,
            size=int(state.st_size),
            mtime=int(getattr(state, "st_mtime", 0)),
        )
        root = f"{REMOTE_DOCUMENTS}/{collection}-Legacy-with-reading-state"
        preserve_pair(pdf, sidecar, root, PurePosixPath(action.destination).name)
    return planned, conflicts


def plan_pending_history_repairs(
    ledger: Ledger,
    actions: Sequence[SyncAction],
    connection: KindleConnection,
) -> tuple[list[SyncAction], list[dict[str, str]]]:
    active_pairs = {
        (action.source_remote, action.destination)
        for action in actions
        if action.action in {"move", "legacy-move"} and action.source_remote
    }
    repairs: list[SyncAction] = []
    conflicts: list[dict[str, str]] = []
    for row in ledger.pending_path_rewrites():
        try:
            source = str(row["source"])
            destination = str(row["destination"])
            size = int(row["size"])
            digest = str(row["sha256"])
        except (KeyError, TypeError, ValueError) as error:
            raise SyncError("A pending path-rewrite journal row is invalid.") from error
        if (source, destination) in active_pairs:
            continue
        target = connection.lstat(destination)
        if target is not None:
            connection.require_regular(destination, target)
            if (
                int(target.st_size) == size
                and connection.sha256_file(destination, expected_size=size) == digest
            ):
                repairs.append(
                    SyncAction(
                        action="history-repair",
                        kind="metadata-repair",
                        destination=destination,
                        size=size,
                        sha256=digest,
                        source_remote=source,
                        reason="resume an exact KOReader path rewrite after an interrupted move",
                    )
                )
                continue
        conflicts.append(
            {
                "path": source,
                "reason": "pending history rewrite has no verified moved destination",
            }
        )
    return repairs, conflicts


def _cleanup_with_sidecar(
    connection: KindleConnection,
    *,
    cleanup_kind: str,
    candidate: RemotePdf,
    target: str,
    observed_sha256: str,
    expected_target_sha256: str,
    expected_target_size: int,
    reason: str,
) -> tuple[CleanupAction | None, dict[str, str] | None]:
    source_sidecar = sidecar_for_pdf(candidate.path)
    target_sidecar = sidecar_for_pdf(target)
    source_has = is_safe_sidecar(connection, source_sidecar)
    target_has = is_safe_sidecar(connection, target_sidecar)
    if source_has and target_has:
        return None, {
            "path": candidate.path,
            "reason": "cleanup refused because source and canonical sidecars both exist",
        }
    return (
        CleanupAction(
            cleanup_kind=cleanup_kind,
            path=candidate.path,
            canonical_target=target,
            observed_sha256=observed_sha256,
            observed_size=candidate.size,
            expected_target_sha256=expected_target_sha256,
            expected_target_size=expected_target_size,
            sidecar_source=source_sidecar if source_has else None,
            sidecar_destination=target_sidecar if source_has else None,
            reason=reason,
        ),
        None,
    )


def plan_cleanup(
    items: Sequence[LocalItem],
    replacements: Sequence[Mapping[str, Any]],
    actions: Sequence[SyncAction],
    inventory: Sequence[RemotePdf],
    connection: KindleConnection,
) -> tuple[list[CleanupAction], list[dict[str, str]]]:
    canonical = [item for item in items if item.kind == "canonical-pdf"]
    target_by_sha: dict[str, list[str]] = defaultdict(list)
    item_by_target: dict[str, LocalItem] = {}
    for item in canonical:
        target = remote_from_relative(item.destination)
        target_by_sha[item.sha256].append(target)
        item_by_target[target] = item
    target_paths = {path for paths in target_by_sha.values() for path in paths}
    reserved_sources = {
        action.source_remote
        for action in actions
        if action.action in {"move", "legacy-move"} and action.source_remote
    }
    cleanup: list[CleanupAction] = []
    conflicts: list[dict[str, str]] = []
    expected_sizes = {item.size for item in canonical}

    for candidate in inventory:
        if (
            candidate.path in target_paths
            or candidate.path in reserved_sources
            or candidate.size not in expected_sizes
        ):
            continue
        digest = connection.sha256_file(candidate.path, expected_size=candidate.size)
        targets = target_by_sha.get(digest, [])
        if not targets:
            continue
        if len(targets) != 1:
            conflicts.append(
                {
                    "path": candidate.path,
                    "reason": "exact duplicate maps to multiple canonical targets",
                }
            )
            continue
        action, conflict = _cleanup_with_sidecar(
            connection,
            cleanup_kind="exact-duplicate",
            candidate=candidate,
            target=targets[0],
            observed_sha256=digest,
            expected_target_sha256=item_by_target[targets[0]].sha256,
            expected_target_size=item_by_target[targets[0]].size,
            reason="noncanonical PDF is byte-identical to a canonical target",
        )
        if conflict:
            conflicts.append(conflict)
        elif action:
            cleanup.append(action)

    # The replacement table identifies logical IDs but does not provide the old
    # edition hashes.  Filename-slug guessing is not sufficient authority to
    # delete data, so these remain visible refusals.  Sidecar-bearing old PDFs
    # are handled separately by the Legacy preservation stage.
    for replacement in replacements:
        removed = str(replacement.get("removed", ""))
        kept = str(replacement.get("kept", ""))
        if not removed or not kept:
            conflicts.append(
                {
                    "replacement": f"{removed}->{kept}",
                    "reason": "invalid replacement mapping",
                }
            )
            continue
        conflicts.append(
            {
                "replacement": f"{removed}->{kept}",
                "reason": (
                    "explicit replacement deletion deferred: no authoritative old-edition hash"
                ),
            }
        )

    return sorted(cleanup, key=lambda row: row.path.casefold()), conflicts


def rename_absent(connection: KindleConnection, source: str, destination: str) -> None:
    if connection.lstat(destination) is not None:
        raise SyncError("A remote rename destination unexpectedly exists.")
    connection.mkdirs(posixpath.dirname(destination))
    source_state = connection.lstat(source)
    if source_state is None or stat.S_ISLNK(source_state.st_mode):
        raise SyncError("An in-place rename source is missing or unsafe.")
    try:
        connection.sftp.rename(source, destination)
    except OSError as error:
        raise SyncError("An in-place Kindle rename failed.") from error
    if stat.S_ISREG(source_state.st_mode):
        connection.transfer_cached_hash(source, destination)
    else:
        connection.forget_hash(source, destination)


def _write_metadata_temporary(
    connection: KindleConnection,
    path: str,
    payload: bytes,
    mode: int,
) -> None:
    state = connection.lstat(path)
    if state is not None:
        connection.require_regular(path, state)
        connection.sftp.remove(path)
    try:
        with connection.sftp.open(path, "wb") as handle:
            handle.write(payload)
        connection.sftp.chmod(path, mode)
    except OSError as error:
        raise SyncError(
            "A KOReader metadata temporary file could not be staged."
        ) from error
    observed, _mode = connection.read_regular_bytes(path, MAX_KOREADER_PATH_FILE_BYTES)
    if observed != payload:
        raise SyncError("A KOReader metadata temporary file did not verify.")


def replace_serialized_exact_path(
    payload: bytes,
    old_path: bytes,
    new_path: bytes,
) -> tuple[bytes, int]:
    """Replace a complete serialized Lua path, never a longer path prefix."""
    if not old_path or b"\x00" in old_path or b"\x00" in new_path:
        raise SyncError("A KOReader path rewrite is unsafe.")
    before_delimiters = b"\x00\t\r\n '\"[(=,{"
    after_delimiters = b"\x00\t\r\n '\"])}=,;{"
    output = bytearray()
    cursor = 0
    count = 0
    while True:
        index = payload.find(old_path, cursor)
        if index < 0:
            output.extend(payload[cursor:])
            break
        end = index + len(old_path)
        before_ok = index == 0 or payload[index - 1] in before_delimiters
        after_ok = end == len(payload) or payload[end] in after_delimiters
        if before_ok and after_ok:
            output.extend(payload[cursor:index])
            output.extend(new_path)
            cursor = end
            count += 1
        else:
            output.extend(payload[cursor:end])
            cursor = end
    return bytes(output), count


def stage_metadata_rewrites(
    connection: KindleConnection,
    old_pdf: str,
    new_pdf: str,
    run_id: str,
) -> list[MetadataRewrite]:
    connection.assert_koreader_stopped()
    old_bytes = old_pdf.encode("utf-8")
    new_bytes = new_pdf.encode("utf-8")
    rewrites: list[MetadataRewrite] = []
    try:
        for path in KOREADER_PATH_FILES:
            state = connection.lstat(path)
            if state is None:
                continue
            payload, mode = connection.read_regular_bytes(
                path, MAX_KOREADER_PATH_FILE_BYTES
            )
            updated, count = replace_serialized_exact_path(
                payload, old_bytes, new_bytes
            )
            if count == 0:
                continue
            temporary = posixpath.join(
                posixpath.dirname(path),
                f".{PurePosixPath(path).name}.canonical-sync-{run_id}.part",
            )
            rewrite = MetadataRewrite(
                path=path,
                temporary=temporary,
                original=payload,
                updated=updated,
                mode=mode,
                replacements=count,
            )
            rewrites.append(rewrite)
            _write_metadata_temporary(connection, temporary, updated, mode)
    except Exception:
        discard_metadata_temporaries(connection, rewrites)
        raise
    return rewrites


def discard_metadata_temporaries(
    connection: KindleConnection, rewrites: Sequence[MetadataRewrite]
) -> None:
    for rewrite in rewrites:
        state = connection.lstat(rewrite.temporary)
        if state is not None:
            connection.require_regular(rewrite.temporary, state)
            with contextlib.suppress(OSError):
                connection.sftp.remove(rewrite.temporary)


def publish_metadata_rewrites(
    connection: KindleConnection,
    rewrites: Sequence[MetadataRewrite],
) -> dict[str, int]:
    published: list[MetadataRewrite] = []
    try:
        for rewrite in rewrites:
            connection.assert_koreader_stopped()
            try:
                # Atomic replacement is mandatory; do not fall back to an
                # unlink window and do not keep an on-device backup.
                connection.sftp.posix_rename(rewrite.temporary, rewrite.path)
            except (AttributeError, OSError) as error:
                raise SyncError(
                    "Atomic KOReader metadata replacement is unavailable."
                ) from error
            published.append(rewrite)
            observed, _mode = connection.read_regular_bytes(
                rewrite.path, MAX_KOREADER_PATH_FILE_BYTES
            )
            if observed != rewrite.updated:
                raise SyncError("Published KOReader metadata did not verify.")
    except Exception:
        # Restore any already-published file from the in-memory original.  No
        # persistent on-device backup is created.
        for rewrite in reversed(published):
            try:
                _write_metadata_temporary(
                    connection, rewrite.temporary, rewrite.original, rewrite.mode
                )
                connection.sftp.posix_rename(rewrite.temporary, rewrite.path)
            except Exception as restore_error:
                raise SyncError("KOReader metadata rollback failed.") from restore_error
        discard_metadata_temporaries(connection, rewrites)
        raise
    discard_metadata_temporaries(connection, rewrites)
    return {rewrite.path: rewrite.replacements for rewrite in rewrites}


def restore_published_metadata(
    connection: KindleConnection,
    rewrites: Sequence[MetadataRewrite],
) -> None:
    for rewrite in reversed(rewrites):
        _write_metadata_temporary(
            connection, rewrite.temporary, rewrite.original, rewrite.mode
        )
        try:
            connection.sftp.posix_rename(rewrite.temporary, rewrite.path)
        except (AttributeError, OSError) as error:
            raise SyncError("KOReader metadata rollback failed.") from error
    discard_metadata_temporaries(connection, rewrites)


def apply_move(
    connection: KindleConnection,
    action: SyncAction,
    run_id: str,
) -> tuple[str, dict[str, int]]:
    if action.source_remote is None:
        raise SyncError("A move action has no remote source.")
    connection.assert_koreader_stopped()
    target_state = connection.lstat(action.destination)
    if target_state is not None:
        connection.require_regular(action.destination, target_state)
        if (
            int(target_state.st_size) == action.size
            and connection.sha256_file(action.destination, expected_size=action.size)
            == action.sha256
        ):
            rewrites = stage_metadata_rewrites(
                connection, action.source_remote, action.destination, run_id
            )
            counts = publish_metadata_rewrites(connection, rewrites)
            return "already-complete", counts
        raise SyncError("A move destination became occupied by different content.")
    source_state = connection.require_regular(
        action.source_remote, connection.lstat(action.source_remote)
    )
    if (
        int(source_state.st_size) != action.size
        or connection.sha256_file(action.source_remote, expected_size=action.size)
        != action.sha256
    ):
        raise SyncError("A planned move source no longer has the canonical SHA-256.")
    if connection.has_open_file_handle(action.source_remote):
        raise SyncError("A planned move source is currently open on the Kindle.")
    if action.sidecar_source is None:
        unexpected_sidecar = sidecar_for_pdf(action.source_remote)
        if connection.lstat(unexpected_sidecar) is not None:
            raise SyncError(
                "A sidecar appeared after planning; the PDF-only move was refused."
            )

    rewrites = stage_metadata_rewrites(
        connection, action.source_remote, action.destination, run_id
    )
    connection.assert_koreader_stopped()

    sidecar_moved = False
    if action.sidecar_source and action.sidecar_destination:
        connection.require_directory(
            action.sidecar_source, connection.lstat(action.sidecar_source)
        )
        if connection.lstat(action.sidecar_destination) is not None:
            raise SyncError(
                "A move was refused because the destination sidecar now exists."
            )
        rename_absent(connection, action.sidecar_source, action.sidecar_destination)
        sidecar_moved = True
    try:
        rename_absent(connection, action.source_remote, action.destination)
        if (
            connection.sha256_file(action.destination, expected_size=action.size)
            != action.sha256
        ):
            raise SyncError("An in-place move did not preserve the expected SHA-256.")
        connection.assert_koreader_stopped()
        history_counts = publish_metadata_rewrites(connection, rewrites)
    except Exception:
        if (
            connection.lstat(action.source_remote) is None
            and connection.lstat(action.destination) is not None
        ):
            with contextlib.suppress(Exception):
                rename_absent(connection, action.destination, action.source_remote)
        if sidecar_moved and action.sidecar_source and action.sidecar_destination:
            if (
                connection.lstat(action.sidecar_source) is None
                and connection.lstat(action.sidecar_destination) is not None
            ):
                with contextlib.suppress(Exception):
                    rename_absent(
                        connection, action.sidecar_destination, action.sidecar_source
                    )
        discard_metadata_temporaries(connection, rewrites)
        raise
    return ("moved-with-sidecar" if sidecar_moved else "moved"), history_counts


def apply_history_repair(
    connection: KindleConnection,
    action: SyncAction,
    run_id: str,
) -> dict[str, int]:
    if action.source_remote is None:
        raise SyncError("A history-repair action has no old path.")
    connection.assert_koreader_stopped()
    target = connection.require_regular(
        action.destination, connection.lstat(action.destination)
    )
    if (
        int(target.st_size) != action.size
        or connection.sha256_file(action.destination, expected_size=action.size)
        != action.sha256
    ):
        raise SyncError("A history-repair destination failed identity verification.")
    rewrites = stage_metadata_rewrites(
        connection, action.source_remote, action.destination, run_id
    )
    return publish_metadata_rewrites(connection, rewrites)


def _owned_temporary(destination: str, run_id: str, suffix: str) -> str:
    parent = posixpath.dirname(destination)
    token = hashlib.sha256(destination.encode("utf-8")).hexdigest()[:16]
    # Do not append to the potentially near-255-byte book filename.
    return posixpath.join(parent, f".canonical-sync-{run_id}.{suffix}.{token}.{suffix}")


def remove_owned_regular(connection: KindleConnection, path: str) -> None:
    state = connection.lstat(path)
    if state is None:
        return
    connection.require_regular(path, state)
    try:
        connection.sftp.remove(path)
    except OSError as error:
        raise SyncError("An owned temporary file could not be removed.") from error
    connection.forget_hash(path)


def upload_atomic(
    connection: KindleConnection,
    action: SyncAction,
    source: Path,
    run_id: str,
) -> None:
    destination = action.destination
    connection.mkdirs(posixpath.dirname(destination))
    existing = connection.lstat(destination)
    if existing is not None:
        connection.require_regular(destination, existing)
        if connection.has_open_file_handle(destination):
            raise SyncError(
                "A destination replacement was refused because the PDF is open."
            )
    temporary = _owned_temporary(destination, run_id, "part")
    rollback = _owned_temporary(destination, run_id, "rollback")
    remove_owned_regular(connection, temporary)
    if connection.lstat(rollback) is not None:
        raise SyncError(
            "A prior rollback file requires manual inspection before continuing."
        )
    before = source.lstat()
    if (
        source.is_symlink()
        or not stat.S_ISREG(before.st_mode)
        or int(before.st_size) != action.size
    ):
        raise SyncError(
            "A local upload source is missing, unsafe, or has changed size."
        )
    digest = hashlib.sha256()
    total = 0
    first_block = True
    try:
        with (
            source.open("rb") as local_handle,
            connection.sftp.open(temporary, "wb") as remote_handle,
        ):
            set_pipelined = getattr(remote_handle, "set_pipelined", None)
            if set_pipelined is not None:
                set_pipelined(True)
            while True:
                block = local_handle.read(HASH_CHUNK)
                if not block:
                    break
                if first_block:
                    first_block = False
                    if action.kind.endswith("pdf") and not block.startswith(b"%PDF-"):
                        raise SyncError("A local upload source lost its PDF header.")
                digest.update(block)
                remote_handle.write(block)
                total += len(block)
    except SyncError:
        with contextlib.suppress(Exception):
            remove_owned_regular(connection, temporary)
        raise
    except OSError as error:
        with contextlib.suppress(Exception):
            remove_owned_regular(connection, temporary)
        raise SyncError(
            "A local source could not be uploaded to the Kindle."
        ) from error
    after = source.lstat()
    if source.is_symlink() or local_signature(before) != local_signature(after):
        remove_owned_regular(connection, temporary)
        raise SyncError("A local source changed while it was uploaded.")
    if total != action.size or digest.hexdigest() != action.sha256:
        remove_owned_regular(connection, temporary)
        raise SyncError(
            "The one-pass local upload hash does not match the requested source."
        )
    temp_state = connection.require_regular(temporary, connection.lstat(temporary))
    if (
        int(temp_state.st_size) != action.size
        or connection.sha256_file(temporary, expected_size=action.size) != action.sha256
    ):
        remove_owned_regular(connection, temporary)
        raise SyncError("The temporary Kindle upload failed SHA-256 verification.")

    published = False
    rollback_created = False
    try:
        if existing is None:
            connection.sftp.rename(temporary, destination)
        else:
            try:
                connection.sftp.posix_rename(temporary, destination)
            except (AttributeError, OSError):
                connection.sftp.rename(destination, rollback)
                rollback_created = True
                try:
                    connection.sftp.rename(temporary, destination)
                except Exception:
                    connection.sftp.rename(rollback, destination)
                    rollback_created = False
                    raise
        published = True
        connection.transfer_cached_hash(temporary, destination)
        if (
            connection.sha256_file(destination, expected_size=action.size)
            != action.sha256
        ):
            raise SyncError("The published Kindle file failed SHA-256 verification.")
        if rollback_created:
            remove_owned_regular(connection, rollback)
            rollback_created = False
    except Exception as error:
        if rollback_created:
            with contextlib.suppress(Exception):
                bad = connection.lstat(destination)
                if bad is not None:
                    connection.require_regular(destination, bad)
                    connection.sftp.remove(destination)
                connection.sftp.rename(rollback, destination)
                connection.forget_hash(destination, rollback)
                rollback_created = False
        if isinstance(error, SyncError):
            raise
        raise SyncError(
            "The verified upload could not be published atomically."
        ) from error
    finally:
        if not published or connection.lstat(temporary) is not None:
            with contextlib.suppress(Exception):
                remove_owned_regular(connection, temporary)


def apply_upload(connection: KindleConnection, action: SyncAction, run_id: str) -> str:
    connection.assert_koreader_stopped()
    target = connection.lstat(action.destination)
    if target is not None:
        connection.require_regular(action.destination, target)
        if (
            int(target.st_size) == action.size
            and connection.sha256_file(action.destination, expected_size=action.size)
            == action.sha256
        ):
            return "already-complete"
        if action.kind in {"canonical-pdf", "standalone-pdf"}:
            unexpected_sidecar = connection.lstat(sidecar_for_pdf(action.destination))
            if unexpected_sidecar is not None:
                raise SyncError(
                    "A changed PDF still has a sidecar; preserve the old pair before upload."
                )
    if action.source_local is None:
        raise SyncError("An upload action has no local source.")
    source = Path(action.source_local)
    upload_atomic(connection, action, source, run_id)
    return "uploaded"


def apply_cleanup(
    connection: KindleConnection,
    action: CleanupAction,
    run_id: str,
) -> tuple[str, dict[str, int]]:
    connection.assert_koreader_stopped()
    target_state = connection.require_regular(
        action.canonical_target, connection.lstat(action.canonical_target)
    )
    if int(target_state.st_size) != action.expected_target_size:
        raise SyncError(
            "Cleanup was refused because the canonical target size changed."
        )
    target_hash = connection.sha256_file(
        action.canonical_target, expected_size=action.expected_target_size
    )
    if target_hash != action.expected_target_sha256:
        raise SyncError(
            "Cleanup was refused because the canonical target hash changed."
        )
    source_state = connection.lstat(action.path)
    if source_state is None:
        return "already-absent", {}
    connection.require_regular(action.path, source_state)
    if (
        int(source_state.st_size) != action.observed_size
        or connection.sha256_file(action.path, expected_size=action.observed_size)
        != action.observed_sha256
    ):
        raise SyncError(
            "Cleanup was refused because the candidate changed after planning."
        )
    if connection.has_open_file_handle(action.path):
        raise SyncError(
            "Cleanup was refused because the candidate is open on the Kindle."
        )
    if (
        action.sidecar_source is None
        and connection.lstat(sidecar_for_pdf(action.path)) is not None
    ):
        raise SyncError("Cleanup was refused because an unplanned sidecar appeared.")
    rewrites = stage_metadata_rewrites(
        connection, action.path, action.canonical_target, run_id
    )
    sidecar_moved = False
    if action.sidecar_source and action.sidecar_destination:
        connection.require_directory(
            action.sidecar_source, connection.lstat(action.sidecar_source)
        )
        if connection.lstat(action.sidecar_destination) is not None:
            raise SyncError(
                "Cleanup was refused because the canonical sidecar now exists."
            )
        rename_absent(connection, action.sidecar_source, action.sidecar_destination)
        sidecar_moved = True
    try:
        history_counts = publish_metadata_rewrites(connection, rewrites)
        connection.sftp.remove(action.path)
    except OSError as error:
        with contextlib.suppress(Exception):
            restore_published_metadata(connection, rewrites)
        if sidecar_moved and action.sidecar_source and action.sidecar_destination:
            if (
                connection.lstat(action.sidecar_source) is None
                and connection.lstat(action.sidecar_destination) is not None
            ):
                with contextlib.suppress(Exception):
                    rename_absent(
                        connection, action.sidecar_destination, action.sidecar_source
                    )
        raise SyncError(
            "A verified duplicate could not be removed; state was rolled back."
        ) from error
    except Exception:
        if sidecar_moved and action.sidecar_source and action.sidecar_destination:
            if (
                connection.lstat(action.sidecar_source) is None
                and connection.lstat(action.sidecar_destination) is not None
            ):
                with contextlib.suppress(Exception):
                    rename_absent(
                        connection, action.sidecar_destination, action.sidecar_source
                    )
        discard_metadata_temporaries(connection, rewrites)
        raise
    connection.forget_hash(action.path)
    return (
        "removed-with-sidecar-move" if action.sidecar_source else "removed",
        history_counts,
    )


def required_free_bytes(actions: Sequence[SyncAction]) -> int:
    uploads = [action for action in actions if action.action == "upload"]
    if not uploads:
        return SAFETY_FREE_BYTES
    # Conservative: all uploaded bytes plus the largest simultaneously staged .part.
    return (
        sum(action.size for action in uploads)
        + max(action.size for action in uploads)
        + SAFETY_FREE_BYTES
    )


def verify_all(
    connection: KindleConnection,
    items: Sequence[LocalItem],
    ledger: Ledger,
) -> None:
    for index, item in enumerate(items, start=1):
        path = remote_from_relative(item.destination)
        state = connection.require_regular(path, connection.lstat(path))
        if (
            int(state.st_size) != item.size
            or connection.sha256_file(path, expected_size=item.size) != item.sha256
        ):
            raise SyncError(f"Final verification failed for destination item {index}.")
        ledger.mark_item(item.destination, "verified", verifiedAt=now_iso())
        if index % 50 == 0 or index == len(items):
            print(f"Verified Kindle destinations: {index}/{len(items)}")


def action_summary(actions: Iterable[SyncAction]) -> dict[str, int]:
    return dict(sorted(Counter(action.action for action in actions).items()))


def cleanup_summary(actions: Iterable[CleanupAction]) -> dict[str, int]:
    return dict(sorted(Counter(action.cleanup_kind for action in actions).items()))


def upload_generated_sync_note(
    connection: KindleConnection,
    *,
    report_path: Path,
    manifest_meta: Mapping[str, Any],
    actions: Sequence[SyncAction],
    cleanup: Sequence[CleanupAction],
    results: Sequence[Mapping[str, str]],
    conflicts: Sequence[Mapping[str, str]],
    history_counts: Mapping[str, int],
    run_id: str,
) -> dict[str, str]:
    result_counts = Counter(row.get("result", "unknown") for row in results)
    sidecar_moves = sum(
        1
        for action in actions
        if action.sidecar_source
        and any(
            row.get("destination") == action.destination
            and row.get("result", "").startswith(("moved", "already-complete"))
            for row in results
        )
    )
    lines = [
        "# Kindle canonical-library sync — 2026-08-29",
        "",
        f"- Manifest SHA-256: `{manifest_meta.get('sha256')}`",
        f"- Planned actions: `{json.dumps(action_summary(actions), sort_keys=True)}`",
        f"- Actual results: `{json.dumps(dict(sorted(result_counts.items())), sort_keys=True)}`",
        f"- Planned cleanup: `{json.dumps(cleanup_summary(cleanup), sort_keys=True)}`",
        f"- Legacy PDF + sidecar pairs preserved: `{sum(1 for a in actions if a.action == 'legacy-move')}`",
        f"- Sidecars moved with an exact PDF pair: `{sidecar_moves}`",
        f"- KOReader exact path replacements: `{sum(history_counts.values())}`",
        f"- Refusals retained for review: `{len(conflicts)}`",
        "- Keep-awake: restoration to the captured original value is the next guarded step after this note is published.",
        "",
        "KOReader path files:",
        "",
    ]
    for path, count in sorted(history_counts.items()):
        lines.append(f"- `{path}`: `{count}` exact replacements")
    if not history_counts:
        lines.append("- No exact legacy path occurrence required rewriting.")
    lines.extend(
        [
            "",
            "Safety policy: changed-edition sidecars were not attached to canonical PDFs. "
            "Older PDF + sidecar pairs were kept together in sibling shelves: "
            "`LinguaLeaf-Legacy-with-reading-state`, "
            "`LazyTravel-Legacy-with-reading-state`, or "
            "`LazyEarn-Legacy-with-reading-state`.",
            "",
        ]
    )
    local_note = report_path.parent / "SYNC-2026-08-29.md"
    local_note.parent.mkdir(parents=True, exist_ok=True)
    local_note.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    size, digest = hash_local_stable(local_note, expect_pdf=False)
    action = SyncAction(
        action="upload",
        kind="note",
        destination=f"{REMOTE_NOTES_ROOT}/SYNC-2026-08-29.md",
        size=size,
        sha256=digest,
        source_local=str(local_note),
        reason="generated verified sync handoff",
    )
    result = apply_upload(connection, action, run_id)
    return {"destination": action.destination, "result": result}


def print_plan(
    actions: Sequence[SyncAction],
    cleanup: Sequence[CleanupAction],
    conflicts: Sequence[Mapping[str, str]],
    report_path: Path,
    apply: bool,
) -> None:
    print(f"Mode: {'APPLY' if apply else 'DRY RUN (Kindle read-only)'}")
    print(f"Sync actions: {action_summary(actions)}")
    print(f"Cleanup actions: {cleanup_summary(cleanup)}")
    print(f"Conflicts/refusals: {len(conflicts)}")
    for action in actions:
        if action.action in {"move", "legacy-move"}:
            suffix = " + .sdr" if action.sidecar_source else ""
            label = "PRESERVE" if action.action == "legacy-move" else "MOVE"
            print(f"{label}{suffix}: {action.source_remote} -> {action.destination}")
    for action in cleanup:
        suffix = " + sidecar preservation" if action.sidecar_source else ""
        print(f"REMOVE {action.cleanup_kind}{suffix}: {action.path}")
    for conflict in conflicts:
        label = (
            conflict.get("path")
            or conflict.get("destination")
            or conflict.get("replacement")
        )
        print(f"REFUSE: {label}: {conflict.get('reason')}")
    print(f"JSON report: {report_path}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Plan or apply the canonical Nutstore -> Kindle PW5SE library sync."
    )
    parser.add_argument(
        "--apply", action="store_true", help="allow guarded Kindle mutations"
    )
    parser.add_argument(
        "--skip-cleanup",
        action="store_true",
        help="do not remove verified exact duplicates or explicit replacements",
    )
    parser.add_argument("--host", default=HOST_DEFAULT)
    parser.add_argument("--port", type=int, default=PORT_DEFAULT)
    parser.add_argument("--key", type=Path, default=DEFAULT_KEY)
    parser.add_argument("--known-hosts", type=Path, default=DEFAULT_KNOWN_HOSTS)
    parser.add_argument("--lingualleaf-root", type=Path, default=DEFAULT_LINGUA_ROOT)
    parser.add_argument("--lazyearn-root", type=Path, default=DEFAULT_LAZYEARN_ROOT)
    parser.add_argument("--lazytravel-root", type=Path, default=DEFAULT_LAZYTRAVEL_ROOT)
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser


def install_signal_handlers() -> None:
    def terminate(signum: int, _frame: object) -> None:
        raise SyncInterrupted(f"Interrupted by signal {signum}.")

    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, terminate)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, terminate)


def run(args: argparse.Namespace) -> int:
    if not (1 <= args.port <= 65535):
        raise SyncError("The SSH port is invalid.")
    if args.ledger.resolve() == args.report.resolve():
        raise SyncError("The resume ledger and JSON report must use different paths.")
    install_signal_handlers()
    print("Validating local Nutstore metadata (canonical files remain unhydrated)...")
    items, replacements, manifest_meta = discover_sources(
        args.lingualleaf_root,
        args.lazyearn_root,
        args.lazytravel_root,
    )
    fingerprint = items_fingerprint(items)
    ledger = Ledger(
        args.ledger,
        host=args.host,
        port=args.port,
        fingerprint=fingerprint,
        items=items,
    )
    report: dict[str, Any] = {
        "schemaVersion": 1,
        "generatedAt": now_iso(),
        "mode": "apply" if args.apply else "dry-run",
        "host": args.host,
        "port": args.port,
        "remoteDocuments": REMOTE_DOCUMENTS,
        "planFingerprint": fingerprint,
        "manifest": manifest_meta,
        "sourceSummary": {
            "items": len(items),
            "bytes": sum(item.size for item in items),
            "byKind": dict(sorted(Counter(item.kind for item in items).items())),
        },
        "status": "planning",
    }
    write_json_atomic(args.report, report)

    with KindleConnection(
        args.host, args.port, args.key, args.known_hosts
    ) as connection:
        print("Inventorying existing Kindle library (no remote changes yet)...")
        actions, inventory, plan_conflicts = plan_sync(items, connection)
        legacy_actions, legacy_conflicts = plan_legacy_sidecar_preservation(
            actions, connection
        )
        actions.extend(legacy_actions)
        history_repairs, history_repair_conflicts = plan_pending_history_repairs(
            ledger, actions, connection
        )
        actions.extend(history_repairs)
        cleanup: list[CleanupAction] = []
        cleanup_conflicts: list[dict[str, str]] = []
        if not args.skip_cleanup:
            cleanup, cleanup_conflicts = plan_cleanup(
                items, replacements, actions, inventory, connection
            )
        conflicts = [
            *plan_conflicts,
            *legacy_conflicts,
            *history_repair_conflicts,
            *cleanup_conflicts,
        ]
        report.update(
            status="planned",
            plannedAt=now_iso(),
            kindleInventory={"linguaLeafPdfs": len(inventory)},
            actionSummary=action_summary(actions),
            cleanupSummary=cleanup_summary(cleanup),
            actions=[asdict(action) for action in actions],
            cleanup=[asdict(action) for action in cleanup],
            conflicts=conflicts,
        )
        write_json_atomic(args.report, report)
        print_plan(actions, cleanup, conflicts, args.report, args.apply)
        if not args.apply:
            report.update(status="dry-run-complete", completedAt=now_iso())
            write_json_atomic(args.report, report)
            return 0

        # This is the last gate before any remote mutation, including recovery
        # of an interrupted keep-awake transaction.
        connection.assert_koreader_stopped()
        stale_keepawake_recovered = recover_stale_keepawake(connection, ledger)
        needed = required_free_bytes(actions)
        available = connection.available_bytes()
        report["spacePreflight"] = {
            "requiredBytes": needed,
            "availableBytes": available,
        }
        write_json_atomic(args.report, report)
        if available < needed:
            raise SyncError(
                "The Kindle does not have enough free space for the guarded upload plan."
            )

        run_id = f"{int(time.time())}-{os.getpid()}-{secrets.token_hex(8)}"
        results: list[dict[str, str]] = []
        history_counts: Counter[str] = Counter()
        for action in actions:
            if action.action in {"move", "legacy-move"}:
                ledger.plan_path_rewrite(action)
        report.update(
            status="applying",
            applyStartedAt=now_iso(),
            runId=run_id,
            staleKeepAwakeRecovered=stale_keepawake_recovered,
        )
        write_json_atomic(args.report, report)
        with KeepAwake(connection, ledger):
            moves = [action for action in actions if action.action == "move"]
            legacy_moves = [
                action for action in actions if action.action == "legacy-move"
            ]
            history_repairs = [
                action for action in actions if action.action == "history-repair"
            ]
            uploads = [action for action in actions if action.action == "upload"]
            reuses = [action for action in actions if action.action == "reuse"]
            for action in reuses:
                path = remote_relative(action.destination)
                ledger.mark_item(path, "verified-existing", verifiedAt=now_iso())
                results.append({"destination": action.destination, "result": "reused"})
            for index, action in enumerate(moves, start=1):
                result, rewritten = apply_move(connection, action, run_id)
                history_counts.update(rewritten)
                if action.source_remote:
                    ledger.complete_path_rewrite(action.source_remote, rewritten)
                ledger.mark_item(
                    remote_relative(action.destination), result, appliedAt=now_iso()
                )
                results.append({"destination": action.destination, "result": result})
                print(f"Applied in-place moves: {index}/{len(moves)}")
            for index, action in enumerate(legacy_moves, start=1):
                result, rewritten = apply_move(connection, action, run_id)
                history_counts.update(rewritten)
                if action.source_remote:
                    ledger.complete_path_rewrite(action.source_remote, rewritten)
                ledger.mark_legacy(
                    action.source_remote or action.destination,
                    result,
                    destination=action.destination,
                    historyRewrites=rewritten,
                )
                results.append({"destination": action.destination, "result": result})
                print(
                    f"Preserved legacy PDF + sidecar pairs: {index}/{len(legacy_moves)}"
                )
            for index, action in enumerate(history_repairs, start=1):
                rewritten = apply_history_repair(connection, action, run_id)
                history_counts.update(rewritten)
                if action.source_remote:
                    ledger.complete_path_rewrite(action.source_remote, rewritten)
                results.append(
                    {"destination": action.destination, "result": "history-repaired"}
                )
                print(
                    f"Repaired interrupted KOReader paths: {index}/{len(history_repairs)}"
                )
            for index, action in enumerate(uploads, start=1):
                result = apply_upload(connection, action, run_id)
                ledger.mark_item(
                    remote_relative(action.destination), result, appliedAt=now_iso()
                )
                results.append({"destination": action.destination, "result": result})
                print(f"Applied uploads: {index}/{len(uploads)}")

            # Removal is deliberately after every requested destination verifies.
            verify_all(connection, items, ledger)
            for index, action in enumerate(cleanup, start=1):
                try:
                    result, rewritten = apply_cleanup(connection, action, run_id)
                    history_counts.update(rewritten)
                    ledger.mark_cleanup(
                        action.path,
                        result,
                        canonicalTarget=action.canonical_target,
                        cleanupKind=action.cleanup_kind,
                    )
                    results.append({"cleanup": action.path, "result": result})
                except SyncError as error:
                    # A cleanup refusal never invalidates already-synced books.
                    result = f"refused: {error}"
                    ledger.mark_cleanup(action.path, "refused", reason=str(error))
                    results.append({"cleanup": action.path, "result": result})
                print(f"Applied cleanup checks: {index}/{len(cleanup)}")
            verify_all(connection, items, ledger)
            generated_note_result = upload_generated_sync_note(
                connection,
                report_path=args.report,
                manifest_meta=manifest_meta,
                actions=actions,
                cleanup=cleanup,
                results=results,
                conflicts=conflicts,
                history_counts=history_counts,
                run_id=run_id,
            )
            results.append(generated_note_result)

        report.update(
            status="complete",
            completedAt=now_iso(),
            results=results,
            historyRewrites=dict(sorted(history_counts.items())),
            keepAwakeRestored=True,
        )
        write_json_atomic(args.report, report)
    print(
        "Canonical Kindle sync completed and the original keep-awake value was restored."
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    configure_console()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return run(args)
    except KeyboardInterrupt:
        with contextlib.suppress(Exception):
            value = json.loads(args.report.read_text(encoding="utf-8"))
            value.update(status="interrupted", failedAt=now_iso())
            write_json_atomic(args.report, value)
        print(
            "ERROR: Interrupted; any active keep-awake context attempted restoration.",
            file=sys.stderr,
        )
        return 130
    except SyncError as error:
        with contextlib.suppress(Exception):
            value = json.loads(args.report.read_text(encoding="utf-8"))
            value.update(status="failed", failedAt=now_iso(), failure=str(error))
            write_json_atomic(args.report, value)
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
