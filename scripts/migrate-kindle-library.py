#!/usr/bin/env python3
"""Plan or apply a guarded PW2 -> PW5SE library migration.

Book bytes always come from the two local Nutstore source directories.  The old
Kindle is used only to recover relative organization and, with --copy-sdr, a
compatible KOReader sidecar.  Without --apply this program performs no remote
mutation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import posixpath
import re
import stat
import sys
import tempfile
import time
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence


OLD_HOST_DEFAULT = "192.168.1.196"
NEW_HOST_DEFAULT = "192.168.1.127"
PORT_DEFAULT = 2222
REMOTE_LIBRARY_ROOT = "/mnt/us/documents"
PARTIAL_MD5_OFFSETS = tuple(256 * (4**index) for index in range(12))
PARTIAL_MD5_SAMPLE_SIZE = 1024
SAFETY_FREE_BYTES = 32 * 1024 * 1024

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_KEY = PROJECT_ROOT / "Handoff" / "keys" / "kindle_handoff_rsa"
DEFAULT_LINGUA = Path.home() / "Nutstore" / "1" / "Share" / "LinguaLeaf" / "blackwhite"
DEFAULT_POCKET = Path.home() / "Nutstore" / "1" / "Share" / "PocketPolished"
DEFAULT_STATE = PROJECT_ROOT / "device-backups" / "kindle-library-migration" / "resume.json"

DESCRIPTOR_DIRECTORIES: tuple[tuple[str, str], ...] = (
    ("｜العربية-English-日本語-中文｜", "LinguaLeaf/ar-en-jp-zh-blackwhite"),
    ("｜和歌仮名-English-日本語-中文｜", "LinguaLeaf/waka-kana-en-jp-zh-blackwhite"),
    ("｜文言文-English-日本語-中文｜", "LinguaLeaf/wenyan-main-quadrilingual-blackwhite"),
    ("｜English-日本語-中文｜", "LinguaLeaf/en-jp-zh-blackwhite"),
    ("｜日本語-中文｜", "LinguaLeaf/jp-zh-blackwhite"),
)

CLASSICAL_PREDECESSORS: Mapping[str, tuple[str, str]] = {
    "史記三家注（本文・日本語・現代中文）｜文言文-日本語-中文｜最大語種・大字版｜黑白.pdf": (
        "史記三家注（本文・日本語・現代中文）｜文言文-日本語-中文｜黑白.pdf",
        "LinguaLeaf/wenyan-jp-zh-trilingual-leftovers-blackwhite",
    ),
    "史記（現代日本語・現代中文注）｜文言文-日本語-中文｜最大語種・大字版｜黑白.pdf": (
        "史記（現代日本語・現代中文注）｜文言文-日本語-中文｜黑白.pdf",
        "LinguaLeaf/wenyan-jp-zh-trilingual-leftovers-blackwhite",
    ),
    "四書章句集注（中文注）｜日本語-中文｜最大語種・大字版｜黑白.pdf": (
        "四書章句集注（中文注）｜日本語-中文｜黑白.pdf",
        "LinguaLeaf/jp-zh-blackwhite",
    ),
    "四書章句集註（日文注）｜中文-日本語｜最大語種・大字版｜黑白.pdf": (
        "四書章句集註（日文注）｜中文-日本語｜黑白.pdf",
        "LinguaLeaf/wenyan-jp-zh-trilingual-leftovers-blackwhite",
    ),
}

MISPLACED_BRIEF_HISTORY_NAME = "A Brief History of Time（日文・中文注）｜English-日本語-中文｜黑白.pdf"
MISPLACED_BRIEF_HISTORY_RELATIVES = (
    f"LinguaLeaf/{MISPLACED_BRIEF_HISTORY_NAME}",
    f"PocketPolished/{MISPLACED_BRIEF_HISTORY_NAME}",
)
CORRECT_BRIEF_HISTORY_RELATIVE = f"LinguaLeaf/en-jp-zh-blackwhite/{MISPLACED_BRIEF_HISTORY_NAME}"

PARTIAL_MD5_PATTERNS = (
    re.compile(r'\[\s*["\']partial_md5_checksum["\']\s*\]\s*=\s*["\']([0-9a-fA-F]{32})["\']'),
    re.compile(r'(?<![A-Za-z0-9_])partial_md5_checksum\s*=\s*["\']([0-9a-fA-F]{32})["\']'),
)


class MigrationError(RuntimeError):
    """A fail-closed migration error safe to display."""


@dataclass(frozen=True)
class LocalBook:
    collection: str
    source: Path
    filename: str
    size: int
    sha256: str
    partial_md5: str


@dataclass(frozen=True)
class PlanItem:
    collection: str
    source: str
    filename: str
    destination: str
    size: int
    sha256: str
    partial_md5: str
    mapping: str
    old_book: str | None
    old_sidecar: str | None = None
    sidecar_eligible: bool = False
    sidecar_reason: str = "not-inspected"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def partial_md5(path: Path) -> str:
    """Match KOReader frontend/util.lua util.partialMD5 exactly."""
    digest = hashlib.md5()  # noqa: S324 - compatibility checksum, not security
    with path.open("rb") as handle:
        for offset in PARTIAL_MD5_OFFSETS:
            handle.seek(offset)
            sample = handle.read(PARTIAL_MD5_SAMPLE_SIZE)
            if not sample:
                break
            digest.update(sample)
    return digest.hexdigest()


def partial_md5_remote_file(connection: "KindleConnection", remote_path: str) -> str:
    """Calculate KOReader's partial MD5 through an already-open SFTP handle."""
    digest = hashlib.md5()  # noqa: S324 - compatibility checksum, not security
    with connection.sftp.open(remote_path, "rb") as handle:
        for offset in PARTIAL_MD5_OFFSETS:
            handle.seek(offset)
            sample = handle.read(PARTIAL_MD5_SAMPLE_SIZE)
            if not sample:
                break
            digest.update(sample)
    return digest.hexdigest()


def _safe_filename(name: str) -> str:
    normalized = unicodedata.normalize("NFC", name)
    if (
        normalized in {"", ".", ".."}
        or "/" in normalized
        or "\\" in normalized
        or any(ord(char) < 0x20 for char in normalized)
    ):
        raise MigrationError("A local filename is unsafe.")
    return normalized


def safe_relative_path(value: str) -> str:
    if "\\" in value or "\x00" in value:
        raise MigrationError("A remote relative path is unsafe.")
    path = PurePosixPath(unicodedata.normalize("NFC", value))
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise MigrationError("A remote relative path is unsafe.")
    return path.as_posix()


def remote_join(root: str, relative: str) -> str:
    relative = safe_relative_path(relative)
    joined = posixpath.normpath(posixpath.join(root, relative))
    prefix = root.rstrip("/") + "/"
    if not joined.startswith(prefix):
        raise MigrationError("A remote path escaped the library root.")
    return joined


def discover_local_books(lingua_root: Path, pocket_root: Path) -> list[LocalBook]:
    books: list[LocalBook] = []
    for collection, root in (("LinguaLeaf", lingua_root), ("PocketPolished", pocket_root)):
        if not root.is_dir() or root.is_symlink():
            raise MigrationError(f"The {collection} source root is missing or unsafe.")
        for source in sorted(root.iterdir(), key=lambda item: unicodedata.normalize("NFC", item.name).casefold()):
            if source.suffix.casefold() != ".pdf":
                continue
            if source.is_symlink() or not source.is_file():
                raise MigrationError(f"The {collection} source contains an unsafe PDF entry.")
            filename = _safe_filename(source.name)
            books.append(
                LocalBook(
                    collection=collection,
                    source=source.resolve(strict=True),
                    filename=filename,
                    size=source.stat().st_size,
                    sha256=sha256_file(source),
                    partial_md5=partial_md5(source),
                )
            )
    return books


def index_old_pdf_paths(paths: Iterable[str]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for raw in paths:
        relative = safe_relative_path(raw)
        if not relative.casefold().endswith(".pdf"):
            continue
        name = PurePosixPath(relative).name
        result.setdefault(unicodedata.normalize("NFC", name), []).append(relative)
    for values in result.values():
        values.sort(key=str.casefold)
    return result


def _unique_old_path(index: Mapping[str, Sequence[str]], filename: str) -> str | None:
    matches = list(index.get(filename, ()))
    if len(matches) > 1:
        raise MigrationError("The old Kindle has ambiguous duplicate paths for one exact filename.")
    return matches[0] if matches else None


def destination_for_book(book: LocalBook, old_index: Mapping[str, Sequence[str]]) -> tuple[str, str, str | None]:
    if book.collection == "PocketPolished":
        return safe_relative_path(f"PocketPolished/{book.filename}"), "pocket-flat", None

    if book.filename == MISPLACED_BRIEF_HISTORY_NAME:
        old_matches = list(old_index.get(book.filename, ()))
        old_book = old_matches[0] if len(old_matches) == 1 else None
        return CORRECT_BRIEF_HISTORY_RELATIVE, "misplaced-duplicate-correction", old_book

    exact = _unique_old_path(old_index, book.filename)
    if exact:
        return exact, "old-exact", exact

    classical = CLASSICAL_PREDECESSORS.get(book.filename)
    if classical:
        predecessor_name, fallback_directory = classical
        predecessor = _unique_old_path(old_index, predecessor_name)
        if predecessor:
            destination = PurePosixPath(predecessor).parent / book.filename
            return safe_relative_path(destination.as_posix()), f"classical-predecessor:{predecessor_name}", predecessor
        return safe_relative_path(f"{fallback_directory}/{book.filename}"), f"classical-fallback:{predecessor_name}", None

    for descriptor, directory in DESCRIPTOR_DIRECTORIES:
        if descriptor in book.filename:
            return safe_relative_path(f"{directory}/{book.filename}"), f"descriptor:{descriptor.strip('｜')}", None
    raise MigrationError("A LinguaLeaf filename has no audited language descriptor mapping.")


def build_plan(books: Sequence[LocalBook], old_pdf_paths: Iterable[str]) -> list[PlanItem]:
    old_index = index_old_pdf_paths(old_pdf_paths)
    planned: list[PlanItem] = []
    destinations: dict[str, str] = {}
    for book in books:
        destination, mapping, old_book = destination_for_book(book, old_index)
        collision_key = unicodedata.normalize("NFC", destination).casefold()
        if collision_key in destinations:
            raise MigrationError("Two local sources collide at one destination path.")
        destinations[collision_key] = str(book.source)
        planned.append(
            PlanItem(
                collection=book.collection,
                source=str(book.source),
                filename=book.filename,
                destination=destination,
                size=book.size,
                sha256=book.sha256,
                partial_md5=book.partial_md5,
                mapping=mapping,
                old_book=old_book,
            )
        )
    return sorted(planned, key=lambda item: unicodedata.normalize("NFC", item.destination).casefold())


def extract_partial_md5(metadata_files: Mapping[str, bytes]) -> str | None:
    found: set[str] = set()
    for relative, payload in metadata_files.items():
        safe_relative_path(relative)
        if len(payload) > 8 * 1024 * 1024:
            raise MigrationError("A sidecar metadata file is unexpectedly large.")
        text = payload.decode("utf-8", errors="ignore")
        for pattern in PARTIAL_MD5_PATTERNS:
            found.update(match.lower() for match in pattern.findall(text))
    if len(found) > 1:
        raise MigrationError("A sidecar contains conflicting partial_md5_checksum values.")
    return next(iter(found)) if found else None


def sidecar_eligibility(local_partial_md5: str, metadata_files: Mapping[str, bytes]) -> tuple[bool, str]:
    try:
        recorded = extract_partial_md5(metadata_files)
    except MigrationError as error:
        return False, str(error)
    if recorded is None:
        return False, "partial_md5_checksum-missing"
    if recorded != local_partial_md5.lower():
        return False, "partial_md5_checksum-mismatch"
    return True, "partial_md5_checksum-match"


def old_book_identity_matches(item: PlanItem, old: "KindleConnection") -> tuple[bool, str]:
    """Match the adjacent PW2 PDF to Nutstore by exact size and KOReader ID."""
    if not item.old_book:
        return False, "old-book-unmapped"
    remote = remote_join(REMOTE_LIBRARY_ROOT, item.old_book)
    state = old.lstat(remote)
    if state is None:
        return False, "old-book-missing"
    if stat.S_ISLNK(state.st_mode) or not stat.S_ISREG(state.st_mode):
        return False, "old-book-unsafe"
    if int(state.st_size) != item.size:
        return False, "old-book-size-mismatch"
    try:
        if partial_md5_remote_file(old, remote) != item.partial_md5:
            return False, "old-book-partial-md5-mismatch"
    except Exception:
        return False, "old-book-verification-failed"
    return True, "old-book-size-and-partial-md5-match"


def plan_fingerprint(items: Sequence[PlanItem]) -> str:
    stable = [
        {"destination": item.destination, "sha256": item.sha256, "size": item.size, "source": item.source}
        for item in items
    ]
    payload = json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def write_json_atomic(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    if temporary.exists():
        raise MigrationError("A local resume-manifest temporary file already exists.")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, sort_keys=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        for attempt in range(50):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                if attempt == 49:
                    raise
                # Windows readers can briefly deny the delete-sharing mode
                # required by an atomic replace. Keep the on-disk manifest
                # intact and retry the same already-fsynced temporary file.
                time.sleep(0.1)
    finally:
        if temporary.exists():
            temporary.unlink()


def parse_df_available_bytes(output: bytes) -> int:
    """Parse the POSIX ``df -Pk`` available-block field."""
    for line in reversed(output.decode("ascii", errors="strict").splitlines()):
        fields = line.split()
        if len(fields) >= 6 and fields[-3].isdigit() and fields[-2].endswith("%"):
            return int(fields[-3]) * 1024
    raise MigrationError("The Kindle free-space response was not recognized.")


class ResumeState:
    """Atomic schema-1 ledger with a narrowly defined append-only upgrade.

    Legacy schema-1 entries did not record ``source``.  For those entries only,
    destination + full SHA-256 + byte size is the documented identity proof
    during a genuine append (the new plan must contain at least one additional
    destination).  The current source is then baselined so later extensions
    also reject source-path relocation.  A same-count fingerprint change is
    never accepted, even if all destination bytes happen to match.
    """

    def __init__(self, path: Path, items: Sequence[PlanItem], old_host: str, new_host: str) -> None:
        self.path = path
        current = self._plan_items(items)
        fingerprint = plan_fingerprint(items)
        if path.exists():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as error:
                raise MigrationError("The existing resume manifest is malformed.") from error
            ledger_items = self._validate_ledger(raw)
            if raw.get("oldHost") != old_host or raw.get("newHost") != new_host:
                raise MigrationError("The existing resume manifest belongs to different Kindle hosts.")
            self.data = raw
            if raw["planFingerprint"] == fingerprint:
                self._require_exact_plan(ledger_items, current)
            else:
                self._extend_append_only(ledger_items, current, fingerprint)
        else:
            self.data = {
                "schema": 1,
                "planFingerprint": fingerprint,
                "oldHost": old_host,
                "newHost": new_host,
                "items": {
                    item.destination: {
                        "status": "pending",
                        "sha256": item.sha256,
                        "size": item.size,
                        "source": item.source,
                    }
                    for item in current.values()
                },
                "misplacedBriefHistory": "pending",
                "sidecars": {},
            }
            self.save()

    @staticmethod
    def _plan_items(items: Sequence[PlanItem]) -> dict[str, PlanItem]:
        result: dict[str, PlanItem] = {}
        folded: set[str] = set()
        for item in items:
            destination = safe_relative_path(item.destination)
            if destination != item.destination:
                raise MigrationError("A resume-plan destination is not normalized.")
            key = unicodedata.normalize("NFC", destination).casefold()
            if key in folded:
                raise MigrationError("The resume plan contains colliding destinations.")
            if (
                not isinstance(item.size, int)
                or isinstance(item.size, bool)
                or item.size < 0
                or not isinstance(item.sha256, str)
                or re.fullmatch(r"[0-9a-f]{64}", item.sha256) is None
                or not isinstance(item.source, str)
                or not item.source
            ):
                raise MigrationError("A resume-plan item is malformed.")
            folded.add(key)
            result[destination] = item
        return result

    @staticmethod
    def _validate_ledger(raw: Any) -> dict[str, dict[str, Any]]:
        if not isinstance(raw, dict) or raw.get("schema") != 1:
            raise MigrationError("The existing resume manifest is malformed.")
        fingerprint = raw.get("planFingerprint")
        if not isinstance(fingerprint, str) or re.fullmatch(r"[0-9a-f]{64}", fingerprint) is None:
            raise MigrationError("The existing resume manifest is malformed.")
        if not isinstance(raw.get("oldHost"), str) or not isinstance(raw.get("newHost"), str):
            raise MigrationError("The existing resume manifest is malformed.")
        ledger_items = raw.get("items")
        if not isinstance(ledger_items, dict):
            raise MigrationError("The existing resume manifest is malformed.")
        folded: set[str] = set()
        for destination, saved in ledger_items.items():
            if not isinstance(destination, str) or safe_relative_path(destination) != destination:
                raise MigrationError("The existing resume manifest is malformed.")
            key = unicodedata.normalize("NFC", destination).casefold()
            if key in folded or not isinstance(saved, dict):
                raise MigrationError("The existing resume manifest is malformed.")
            folded.add(key)
            size = saved.get("size")
            saved_sha = saved.get("sha256")
            source = saved.get("source")
            verified = saved.get("verifiedSha256")
            if (
                saved.get("status") not in {"pending", "uploading", "complete"}
                or not isinstance(saved_sha, str)
                or re.fullmatch(r"[0-9a-f]{64}", saved_sha) is None
                or not isinstance(size, int)
                or isinstance(size, bool)
                or size < 0
                or (source is not None and (not isinstance(source, str) or not source))
                or (verified is not None and verified != saved["sha256"])
            ):
                raise MigrationError("The existing resume manifest is malformed.")
        sidecars = raw.get("sidecars", {})
        if not isinstance(sidecars, dict) or any(
            not isinstance(key, str)
            or not isinstance(value, dict)
            or not isinstance(value.get("status"), str)
            for key, value in sidecars.items()
        ):
            raise MigrationError("The existing resume manifest is malformed.")
        if "extensions" in raw and (
            not isinstance(raw["extensions"], list)
            or any(not isinstance(extension, dict) for extension in raw["extensions"])
        ):
            raise MigrationError("The existing resume manifest is malformed.")
        return ledger_items

    @staticmethod
    def _saved_item_matches(saved: Mapping[str, Any], current: PlanItem) -> bool:
        return (
            saved.get("sha256") == current.sha256
            and saved.get("size") == current.size
            and (saved.get("source") is None or saved.get("source") == current.source)
        )

    def _require_exact_plan(
        self,
        ledger_items: Mapping[str, Mapping[str, Any]],
        current: Mapping[str, PlanItem],
    ) -> None:
        if set(ledger_items) != set(current) or any(
            not self._saved_item_matches(saved, current[destination])
            for destination, saved in ledger_items.items()
        ):
            raise MigrationError("The existing resume manifest is inconsistent with its migration plan.")

    def _extend_append_only(
        self,
        ledger_items: dict[str, dict[str, Any]],
        current: Mapping[str, PlanItem],
        fingerprint: str,
    ) -> None:
        # Count growth is required.  This single rule rejects removals and all
        # same-count drift, including source relocation hidden by legacy rows.
        if len(current) <= len(ledger_items):
            raise MigrationError("The existing resume manifest is not a safe append-only plan.")
        for destination, saved in ledger_items.items():
            item = current.get(destination)
            if item is None or not self._saved_item_matches(saved, item):
                raise MigrationError("The existing resume manifest is not a safe append-only plan.")
        added = [item for destination, item in current.items() if destination not in ledger_items]
        if len(added) != len(current) - len(ledger_items):
            raise MigrationError("The existing resume manifest is not a safe append-only plan.")

        previous = self.data["planFingerprint"]
        legacy_without_source = [
            destination for destination, saved in ledger_items.items() if saved.get("source") is None
        ]
        for destination, saved in ledger_items.items():
            saved.setdefault("source", current[destination].source)
        for item in added:
            ledger_items[item.destination] = {
                "status": "pending",
                "sha256": item.sha256,
                "size": item.size,
                "source": item.source,
            }
        self.data["planFingerprint"] = fingerprint
        self.data.setdefault("extensions", []).append(
            {
                "fromPlanFingerprint": previous,
                "toPlanFingerprint": fingerprint,
                "addedDestinations": sorted((item.destination for item in added), key=str.casefold),
                "legacyIdentityBasis": "destination+sha256+size",
                "legacySourceBaselinesAdded": sorted(legacy_without_source, key=str.casefold),
                "extendedAtUnix": int(time.time()),
            }
        )
        self.save()

    def save(self) -> None:
        write_json_atomic(self.path, self.data)

    def status(self, destination: str) -> str:
        return str(self.data["items"][destination]["status"])

    def mark(self, destination: str, status: str, **extra: Any) -> None:
        item = self.data["items"][destination]
        item["status"] = status
        item.update(extra)
        self.save()

    def mark_sidecar(self, book_destination: str, status: str, **extra: Any) -> None:
        sidecars = self.data.setdefault("sidecars", {})
        sidecars[book_destination] = {"status": status, **extra}
        self.save()


class KindleConnection:
    def __init__(self, host: str, port: int, key: Path, known_hosts: Path) -> None:
        try:
            import paramiko
        except ImportError as error:  # pragma: no cover - environment guard
            raise MigrationError("paramiko is required for Kindle SSH/SFTP migration.") from error
        known_hosts.parent.mkdir(parents=True, exist_ok=True)
        known_hosts.touch(exist_ok=True)
        self._paramiko = paramiko
        self.client = paramiko.SSHClient()
        self.client.load_host_keys(str(known_hosts))
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
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
            if transport is None:
                raise MigrationError("The Kindle SSH transport was not established.")
            transport.set_keepalive(30)
            self.sftp = self.client.open_sftp()
        except Exception as error:
            self.client.close()
            raise MigrationError("A Kindle SSH/SFTP connection failed.") from error

    def close(self) -> None:
        try:
            self.sftp.close()
        finally:
            self.client.close()

    def __enter__(self) -> "KindleConnection":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def exec_checked(self, command: str, purpose: str) -> bytes:
        _stdin, stdout, stderr = self.client.exec_command(command, timeout=60)
        data = stdout.read()
        stderr.read()  # captured and intentionally never printed
        code = stdout.channel.recv_exit_status()
        if code != 0:
            raise MigrationError(f"{purpose} failed with remote exit code {code}.")
        return data

    def lstat(self, path: str) -> Any | None:
        try:
            return self.sftp.lstat(path)
        except OSError as error:
            if getattr(error, "errno", None) in (2,):
                return None
            if "No such file" in str(error):
                return None
            raise

    def list_pdf_relatives(self, root: str = REMOTE_LIBRARY_ROOT) -> list[str]:
        found: list[str] = []

        def walk(directory: str, relative: PurePosixPath | None = None) -> None:
            for entry in self.sftp.listdir_attr(directory):
                if entry.filename in {".", ".."}:
                    continue
                name = _safe_filename(entry.filename)
                child = posixpath.join(directory, name)
                child_relative = PurePosixPath(name) if relative is None else relative / name
                mode = entry.st_mode
                if stat.S_ISLNK(mode):
                    raise MigrationError("The remote library contains a symlink.")
                if stat.S_ISDIR(mode):
                    if not name.casefold().endswith(".sdr"):
                        walk(child, child_relative)
                elif stat.S_ISREG(mode) and name.casefold().endswith(".pdf"):
                    found.append(safe_relative_path(child_relative.as_posix()))

        walk(root)
        return sorted(found, key=str.casefold)

    def mkdirs(self, remote_directory: str) -> None:
        root = REMOTE_LIBRARY_ROOT.rstrip("/")
        if remote_directory != root and not remote_directory.startswith(root + "/"):
            raise MigrationError("A remote directory escaped the library root.")
        current = root
        for part in PurePosixPath(remote_directory[len(root) :].lstrip("/")).parts:
            current = posixpath.join(current, part)
            existing = self.lstat(current)
            if existing is None:
                self.sftp.mkdir(current)
            elif stat.S_ISLNK(existing.st_mode) or not stat.S_ISDIR(existing.st_mode):
                raise MigrationError("A remote destination parent is unsafe.")

    def available_bytes(self) -> int:
        return parse_df_available_bytes(
            self.exec_checked("LC_ALL=C df -Pk /mnt/us", "Kindle free-space check")
        )

    def upload_book_atomic(self, source: Path, destination_relative: str, transaction_id: str) -> None:
        destination = remote_join(REMOTE_LIBRARY_ROOT, destination_relative)
        parent = posixpath.dirname(destination)
        self.mkdirs(parent)
        existing = self.lstat(destination)
        if existing is not None and (stat.S_ISLNK(existing.st_mode) or not stat.S_ISREG(existing.st_mode)):
            raise MigrationError("A remote book destination is not a regular file.")
        temporary = posixpath.join(parent, f".{PurePosixPath(destination).name}.migrate-{transaction_id}.tmp")
        temp_state = self.lstat(temporary)
        if temp_state is not None:
            if stat.S_ISLNK(temp_state.st_mode) or not stat.S_ISREG(temp_state.st_mode):
                raise MigrationError("An owned remote upload temporary path is unsafe.")
            self.sftp.remove(temporary)
        try:
            self.sftp.put(str(source), temporary, confirm=True)
            if int(self.sftp.stat(temporary).st_size) != source.stat().st_size:
                raise MigrationError("The SFTP temporary upload size is wrong.")
            try:
                self.sftp.posix_rename(temporary, destination)
            except OSError:
                if existing is not None:
                    self.sftp.remove(destination)
                self.sftp.rename(temporary, destination)
            if int(self.sftp.stat(destination).st_size) != source.stat().st_size:
                raise MigrationError("The published remote book size is wrong.")
        finally:
            leftover = self.lstat(temporary)
            if leftover is not None and stat.S_ISREG(leftover.st_mode):
                self.sftp.remove(temporary)

    def sha256_remote_file(self, remote_path: str) -> str:
        digest = hashlib.sha256()
        with self.sftp.open(remote_path, "rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    def has_open_file_handle(self, remote_path: str) -> bool:
        """Return whether a numeric Linux process has this exact path open.

        Numeric processes and descriptors can disappear during the scan; only
        those expected ENOENT races are ignored.  Any other inability to audit
        ``/proc`` fails closed so replacement cannot race an active reader.
        """
        if not remote_path.startswith("/") or posixpath.normpath(remote_path) != remote_path:
            raise MigrationError("The open-file audit target is unsafe.")

        def disappeared(error: OSError) -> bool:
            return getattr(error, "errno", None) in (2, 3) or "No such file" in str(error)

        try:
            processes = self.sftp.listdir_attr("/proc")
        except OSError as error:
            raise MigrationError("The Kindle open-file audit could not inspect /proc.") from error
        for process in processes:
            if not process.filename.isdecimal():
                continue
            descriptors = f"/proc/{process.filename}/fd"
            try:
                entries = self.sftp.listdir_attr(descriptors)
            except OSError as error:
                if disappeared(error):
                    continue
                raise MigrationError("The Kindle open-file audit could not inspect a process.") from error
            for entry in entries:
                if not entry.filename.isdecimal():
                    continue
                try:
                    linked = self.sftp.readlink(posixpath.join(descriptors, entry.filename))
                except OSError as error:
                    if disappeared(error):
                        continue
                    raise MigrationError("The Kindle open-file audit could not inspect a descriptor.") from error
                if linked == remote_path:
                    return True
        return False


def preflight_required_bytes(items: Sequence[PlanItem], new: KindleConnection, state: ResumeState) -> int:
    net_growth = 0
    largest_temporary = 0
    for item in items:
        target = remote_join(REMOTE_LIBRARY_ROOT, item.destination)
        existing = new.lstat(target)
        existing_size = 0
        if existing is not None:
            if stat.S_ISLNK(existing.st_mode) or not stat.S_ISREG(existing.st_mode):
                raise MigrationError("A planned destination is not a regular file.")
            existing_size = int(existing.st_size)
        if state.status(item.destination) == "complete" and existing_size == item.size:
            continue
        net_growth += item.size - existing_size
        largest_temporary = max(largest_temporary, item.size)
    return max(0, net_growth) + largest_temporary + SAFETY_FREE_BYTES


def sidecar_destination(book_relative: str) -> str:
    """Return KOReader's adjacent sidecar path (``book.pdf`` -> ``book.sdr``)."""
    path = PurePosixPath(safe_relative_path(book_relative))
    return safe_relative_path(path.with_suffix(".sdr").as_posix())


def sidecar_candidates(book_relative: str) -> tuple[str, ...]:
    path = PurePosixPath(safe_relative_path(book_relative))
    # Current KOReader removes the document's last suffix.  Retain the older
    # full-name spelling only as an input candidate, and fail closed if both
    # variants exist for one book.
    candidates = [sidecar_destination(path.as_posix()), path.as_posix() + ".sdr"]
    return tuple(dict.fromkeys(candidates))


def read_sidecar_metadata(old: KindleConnection, sidecar_relative: str) -> dict[str, bytes]:
    root = remote_join(REMOTE_LIBRARY_ROOT, sidecar_relative)
    root_state = old.lstat(root)
    if root_state is None or stat.S_ISLNK(root_state.st_mode) or not stat.S_ISDIR(root_state.st_mode):
        raise MigrationError("The old sidecar path is not a safe directory.")
    metadata: dict[str, bytes] = {}

    def walk(directory: str, relative: PurePosixPath | None = None) -> None:
        for entry in old.sftp.listdir_attr(directory):
            name = _safe_filename(entry.filename)
            child = posixpath.join(directory, name)
            child_relative = PurePosixPath(name) if relative is None else relative / name
            if stat.S_ISLNK(entry.st_mode):
                raise MigrationError("The old sidecar contains a symlink.")
            if stat.S_ISDIR(entry.st_mode):
                walk(child, child_relative)
            elif stat.S_ISREG(entry.st_mode):
                if entry.st_size > 8 * 1024 * 1024:
                    continue
                with old.sftp.open(child, "rb") as handle:
                    metadata[safe_relative_path(child_relative.as_posix())] = handle.read()
            else:
                raise MigrationError("The old sidecar contains a special file.")

    walk(root)
    return metadata


def inspect_sidecars(items: Sequence[PlanItem], old: KindleConnection) -> list[PlanItem]:
    result: list[PlanItem] = []
    for item in items:
        if not item.old_book:
            result.append(item)
            continue
        found: list[str] = []
        for candidate in sidecar_candidates(item.old_book):
            remote = remote_join(REMOTE_LIBRARY_ROOT, candidate)
            state = old.lstat(remote)
            if state is not None:
                if stat.S_ISLNK(state.st_mode) or not stat.S_ISDIR(state.st_mode):
                    found = []
                    break
                found.append(candidate)
        if len(found) != 1:
            result.append(PlanItem(**{**asdict(item), "sidecar_reason": "sidecar-absent-or-ambiguous"}))
            continue
        try:
            metadata = read_sidecar_metadata(old, found[0])
            eligible, reason = sidecar_eligibility(item.partial_md5, metadata)
            if not eligible and reason == "partial_md5_checksum-mismatch":
                old_matches, old_reason = old_book_identity_matches(item, old)
                if old_matches:
                    eligible, reason = True, f"{old_reason}:metadata-stale"
        except Exception:
            eligible, reason = False, "sidecar-inspection-failed"
        result.append(PlanItem(**{**asdict(item), "old_sidecar": found[0], "sidecar_eligible": eligible, "sidecar_reason": reason}))
    return result


def sidecar_tree_manifest(
    connection: KindleConnection, sidecar_relative: str
) -> dict[str, tuple[str, int, str]]:
    """Hash one exact sidecar tree, including its empty directories.

    The returned mapping is also a structural equality proof.  Every entry is
    lstat-checked, symlinks and special files are rejected, and regular files
    are checked again after reading so an in-flight size change fails closed.
    """
    root = remote_join(REMOTE_LIBRARY_ROOT, sidecar_relative)
    root_state = connection.lstat(root)
    if root_state is None or stat.S_ISLNK(root_state.st_mode) or not stat.S_ISDIR(root_state.st_mode):
        raise MigrationError("A sidecar path is not a safe directory.")
    manifest: dict[str, tuple[str, int, str]] = {}

    def walk(directory: str, relative: PurePosixPath | None = None) -> None:
        names: set[str] = set()
        for entry in connection.sftp.listdir_attr(directory):
            name = _safe_filename(entry.filename)
            collision_key = unicodedata.normalize("NFC", name).casefold()
            if collision_key in names:
                raise MigrationError("A sidecar directory contains ambiguous names.")
            names.add(collision_key)
            child = posixpath.join(directory, name)
            child_relative = PurePosixPath(name) if relative is None else relative / name
            key = safe_relative_path(child_relative.as_posix())
            if stat.S_ISLNK(entry.st_mode):
                raise MigrationError("A sidecar contains a symlink.")
            if stat.S_ISDIR(entry.st_mode):
                manifest[key] = ("directory", 0, "")
                walk(child, child_relative)
            elif stat.S_ISREG(entry.st_mode):
                digest = hashlib.sha256()
                copied = 0
                with connection.sftp.open(child, "rb") as handle:
                    for block in iter(lambda: handle.read(1024 * 1024), b""):
                        digest.update(block)
                        copied += len(block)
                after = connection.lstat(child)
                if (
                    after is None
                    or stat.S_ISLNK(after.st_mode)
                    or not stat.S_ISREG(after.st_mode)
                    or copied != int(entry.st_size)
                    or copied != int(after.st_size)
                ):
                    raise MigrationError("A sidecar file changed while it was being hashed.")
                manifest[key] = ("file", copied, digest.hexdigest())
            else:
                raise MigrationError("A sidecar contains a special file.")

    walk(root)
    return manifest


def sidecar_tree_size(connection: KindleConnection, sidecar_relative: str) -> int:
    """Measure one exact, symlink-free sidecar tree without following siblings."""
    return sum(size for kind, size, _digest in sidecar_tree_manifest(connection, sidecar_relative).values() if kind == "file")


def copy_sidecar_best_effort(
    item: PlanItem,
    old: KindleConnection,
    new: KindleConnection,
    transaction_id: str,
    replace_existing: bool = False,
) -> str:
    if not item.sidecar_eligible or not item.old_sidecar:
        return f"skipped-ineligible:{item.sidecar_reason}"
    if re.fullmatch(r"[A-Za-z0-9_-]{1,64}", transaction_id) is None:
        raise MigrationError("The sidecar transaction identifier is unsafe.")

    # A sidecar is never allowed to create or legitimize a book.  The already
    # published destination must still be the exact Nutstore PDF before any
    # reading state is considered.
    target = remote_join(REMOTE_LIBRARY_ROOT, item.destination)
    target_state = new.lstat(target)
    if target_state is None:
        return "skipped-destination-book-missing"
    if stat.S_ISLNK(target_state.st_mode) or not stat.S_ISREG(target_state.st_mode):
        return "skipped-destination-book-unsafe"
    if int(target_state.st_size) != item.size:
        return "skipped-destination-book-size-mismatch"
    try:
        if new.sha256_remote_file(target) != item.sha256:
            return "skipped-destination-book-hash-mismatch"
    except Exception:
        return "skipped-destination-book-verification-failed"

    destination_relative = sidecar_destination(item.destination)
    destination = remote_join(REMOTE_LIBRARY_ROOT, destination_relative)
    source_root = remote_join(REMOTE_LIBRARY_ROOT, item.old_sidecar)
    temp_relative = safe_relative_path(destination_relative + f".migrate-{transaction_id}.tmp")
    temp_root = remote_join(REMOTE_LIBRARY_ROOT, temp_relative)
    rollback_relative = safe_relative_path(destination_relative + f".migrate-{transaction_id}.rollback")
    rollback_root = remote_join(REMOTE_LIBRARY_ROOT, rollback_relative)
    temp_owned = False
    try:
        # Revalidate at copy time so a source sidecar changed after planning is
        # skipped rather than attached to the wrong Nutstore book.
        metadata = read_sidecar_metadata(old, item.old_sidecar)
        eligible, reason = sidecar_eligibility(item.partial_md5, metadata)
        if not eligible and reason == "partial_md5_checksum-mismatch":
            eligible, _reason = old_book_identity_matches(item, old)
        if not eligible:
            return "skipped-source-changed"

        # Metadata alone is not an identity proof.  Recheck the adjacent PW2
        # PDF for every eligible source, even when its metadata checksum was
        # already current.
        old_matches, old_reason = old_book_identity_matches(item, old)
        if not old_matches:
            return f"skipped-{old_reason}"
        source_manifest = sidecar_tree_manifest(old, item.old_sidecar)
        source_bytes = sum(
            size for kind, size, _digest in source_manifest.values() if kind == "file"
        )

        # A rollback name from another process or interrupted invocation is
        # ambiguous.  Validate it for diagnostics, but never mutate or discard
        # it automatically; ordinary failures below restore within this call.
        rollback_state = new.lstat(rollback_root)
        destination_state = new.lstat(destination)
        if rollback_state is not None:
            if stat.S_ISLNK(rollback_state.st_mode) or not stat.S_ISDIR(rollback_state.st_mode):
                return "skipped-stale-rollback-unsafe"
            try:
                sidecar_tree_manifest(new, rollback_relative)
            except Exception:
                return "skipped-stale-rollback-unsafe"
            return "skipped-stale-rollback-present"

        destination_manifest: dict[str, tuple[str, int, str]] | None = None
        if destination_state is not None:
            if stat.S_ISLNK(destination_state.st_mode) or not stat.S_ISDIR(destination_state.st_mode):
                return "skipped-destination-unsafe"
            try:
                destination_manifest = sidecar_tree_manifest(new, destination_relative)
            except Exception:
                return "skipped-destination-unsafe"
            # Default remains an unconditional never-overwrite policy.
            if not replace_existing:
                return "skipped-destination-exists"
            if destination_manifest == source_manifest:
                return "resumed-existing-match"
            try:
                if new.has_open_file_handle(target):
                    return "skipped-destination-book-open"
            except Exception:
                return "skipped-open-handle-check-failed"

        if new.available_bytes() < source_bytes + SAFETY_FREE_BYTES:
            return "skipped-insufficient-space"

        stale = new.lstat(temp_root)
        if stale is not None:
            if stat.S_ISLNK(stale.st_mode) or not stat.S_ISDIR(stale.st_mode):
                return "skipped-stale-temp-unsafe"
            try:
                sidecar_tree_manifest(new, temp_relative)
            except Exception:
                return "skipped-stale-temp-unsafe"
            remove_exact_tree(new, temp_relative)

        new.mkdirs(posixpath.dirname(destination))
        new.sftp.mkdir(temp_root)
        temp_owned = True

        def copy_tree(old_dir: str, new_dir: str) -> None:
            for entry in old.sftp.listdir_attr(old_dir):
                name = _safe_filename(entry.filename)
                old_child = posixpath.join(old_dir, name)
                new_child = posixpath.join(new_dir, name)
                if stat.S_ISLNK(entry.st_mode):
                    raise MigrationError("The eligible old sidecar changed to a symlink.")
                if stat.S_ISDIR(entry.st_mode):
                    new.sftp.mkdir(new_child)
                    copy_tree(old_child, new_child)
                elif stat.S_ISREG(entry.st_mode):
                    source_digest = hashlib.sha256()
                    with old.sftp.open(old_child, "rb") as source_handle:
                        with new.sftp.open(new_child, "wb") as destination_handle:
                            while True:
                                block = source_handle.read(1024 * 1024)
                                if not block:
                                    break
                                source_digest.update(block)
                                destination_handle.write(block)
                    copied_digest = hashlib.sha256()
                    with new.sftp.open(new_child, "rb") as copied_handle:
                        for block in iter(lambda: copied_handle.read(1024 * 1024), b""):
                            copied_digest.update(block)
                    if copied_digest.digest() != source_digest.digest():
                        raise MigrationError("A copied sidecar file failed SHA-256 verification.")
                else:
                    raise MigrationError("The eligible old sidecar changed to a special file.")

        copy_tree(source_root, temp_root)
        if sidecar_tree_manifest(new, temp_relative) != source_manifest:
            raise MigrationError("The copied sidecar tree failed verification.")

        # Final gates cover mutations during the potentially long copy.  The
        # source tree and PW2 identity must still match, and the destination PDF
        # must still be the exact full-SHA Nutstore book.
        if sidecar_tree_manifest(old, item.old_sidecar) != source_manifest:
            return "skipped-source-changed"
        final_old_matches, final_old_reason = old_book_identity_matches(item, old)
        if not final_old_matches:
            return f"skipped-{final_old_reason}"
        final_book = new.lstat(target)
        if (
            final_book is None
            or stat.S_ISLNK(final_book.st_mode)
            or not stat.S_ISREG(final_book.st_mode)
            or int(final_book.st_size) != item.size
            or new.sha256_remote_file(target) != item.sha256
        ):
            return "skipped-destination-book-changed"

        if destination_manifest is None:
            if new.lstat(destination) is not None:
                return "skipped-destination-appeared"
            new.sftp.rename(temp_root, destination)
            temp_owned = False
            if sidecar_tree_manifest(new, destination_relative) != source_manifest:
                remove_exact_tree(new, destination_relative)
                raise MigrationError("The published sidecar tree failed verification.")
            return "copied"

        # Replacement is opt-in and additionally blocked while KOReader (or
        # any other process) has the exact destination PDF open.
        try:
            if new.has_open_file_handle(target):
                return "skipped-destination-book-open"
        except Exception:
            return "skipped-open-handle-check-failed"
        if sidecar_tree_manifest(new, destination_relative) != destination_manifest:
            return "skipped-destination-changed"

        rollback_active = False
        published = False
        try:
            new.sftp.rename(destination, rollback_root)
            rollback_active = True
            new.sftp.rename(temp_root, destination)
            temp_owned = False
            published = True
            if sidecar_tree_manifest(new, destination_relative) != source_manifest:
                raise MigrationError("The replacement sidecar tree failed verification.")
            remove_exact_tree(new, rollback_relative)
            rollback_active = False
            return "replaced-existing"
        except Exception:
            # The newly published destination came only from our verified temp;
            # remove it before restoring the parked user tree.  If it no longer
            # matches, leave both paths untouched rather than deleting data.
            if published and new.lstat(destination) is not None:
                try:
                    if sidecar_tree_manifest(new, destination_relative) != source_manifest:
                        return "skipped-replace-rollback-blocked"
                    remove_exact_tree(new, destination_relative)
                except Exception:
                    return "skipped-replace-rollback-blocked"
            if rollback_active and new.lstat(rollback_root) is not None and new.lstat(destination) is None:
                try:
                    new.sftp.rename(rollback_root, destination)
                    rollback_active = False
                except Exception:
                    return "skipped-replace-rollback-failed"
            return "skipped-replace-failed"
    except Exception:
        return "skipped-copy-failed"
    finally:
        # Only the transaction-owned temporary tree is eligible for cleanup.
        # A failed cleanup is harmless and will be retried on the next run.
        try:
            temp_state = new.lstat(temp_root)
            if temp_owned and temp_state is not None and not stat.S_ISLNK(temp_state.st_mode) and stat.S_ISDIR(temp_state.st_mode):
                sidecar_tree_manifest(new, temp_relative)
                remove_exact_tree(new, temp_relative)
        except Exception:
            pass


def remove_exact_tree(connection: KindleConnection, relative: str) -> None:
    """Delete only one explicitly named regular file or symlink-free tree."""
    root = remote_join(REMOTE_LIBRARY_ROOT, relative)
    state = connection.lstat(root)
    if state is None:
        return
    if stat.S_ISLNK(state.st_mode):
        raise MigrationError("The exact misplaced sidecar path is a symlink.")
    if stat.S_ISREG(state.st_mode):
        connection.sftp.remove(root)
        return
    if not stat.S_ISDIR(state.st_mode):
        raise MigrationError("The exact misplaced sidecar path is unsafe.")
    for entry in connection.sftp.listdir_attr(root):
        child_relative = safe_relative_path(f"{relative}/{_safe_filename(entry.filename)}")
        remove_exact_tree(connection, child_relative)
    connection.sftp.rmdir(root)


def cleanup_misplaced_brief_history(items: Sequence[PlanItem], new: KindleConnection, state: ResumeState) -> dict[str, str]:
    correct = next((item for item in items if item.destination == CORRECT_BRIEF_HISTORY_RELATIVE), None)
    if correct is None or state.status(correct.destination) != "complete":
        raise MigrationError("The correct Brief History destination is not complete; misplaced cleanup is blocked.")
    canonical = remote_join(REMOTE_LIBRARY_ROOT, CORRECT_BRIEF_HISTORY_RELATIVE)
    canonical_state = new.lstat(canonical)
    if (
        canonical_state is None
        or stat.S_ISLNK(canonical_state.st_mode)
        or not stat.S_ISREG(canonical_state.st_mode)
        or int(canonical_state.st_size) != correct.size
        or new.sha256_remote_file(canonical) != correct.sha256
    ):
        raise MigrationError("The canonical Brief History copy does not match the Nutstore source hash.")

    saved = state.data.get("misplacedBriefHistory")
    results: dict[str, str] = dict(saved) if isinstance(saved, dict) else {}
    for misplaced_relative in MISPLACED_BRIEF_HISTORY_RELATIVES:
        if results.get(misplaced_relative) in {"removed", "absent"}:
            continue
        misplaced = remote_join(REMOTE_LIBRARY_ROOT, misplaced_relative)
        existing = new.lstat(misplaced)
        if existing is None:
            results[misplaced_relative] = "absent"
        else:
            if stat.S_ISLNK(existing.st_mode) or not stat.S_ISREG(existing.st_mode):
                raise MigrationError("An exact misplaced Brief History path is unsafe.")
            if int(existing.st_size) != correct.size or new.sha256_remote_file(misplaced) != correct.sha256:
                raise MigrationError("An exact misplaced Brief History file does not match the Nutstore source hash.")
            new.sftp.remove(misplaced)
            for candidate in sidecar_candidates(misplaced_relative):
                remove_exact_tree(new, candidate)
            results[misplaced_relative] = "removed"
        state.data["misplacedBriefHistory"] = results
        state.save()
    return results


def apply_plan(
    items: Sequence[PlanItem],
    old: KindleConnection,
    new: KindleConnection,
    state: ResumeState,
    copy_sdr: bool,
    replace_existing_sdr: bool = False,
) -> dict[str, Any]:
    required = preflight_required_bytes(items, new, state)
    available = new.available_bytes()
    if available < required:
        raise MigrationError("The new Kindle does not have enough free space for this resumable plan.")
    transaction_id = state.data["planFingerprint"][:12]
    copied = 0
    resumed = 0
    for item in items:
        target = remote_join(REMOTE_LIBRARY_ROOT, item.destination)
        if state.status(item.destination) == "complete":
            existing = new.lstat(target)
            if existing is not None and stat.S_ISREG(existing.st_mode) and int(existing.st_size) == item.size:
                saved = state.data["items"][item.destination]
                if saved.get("verifiedSha256") == item.sha256 or new.sha256_remote_file(target) == item.sha256:
                    if saved.get("verifiedSha256") != item.sha256:
                        state.mark(item.destination, "complete", verifiedSha256=item.sha256)
                    resumed += 1
                    continue
        state.mark(item.destination, "uploading")
        new.upload_book_atomic(Path(item.source), item.destination, transaction_id)
        if new.sha256_remote_file(target) != item.sha256:
            raise MigrationError("A published remote book failed SHA-256 verification.")
        state.mark(item.destination, "complete", verifiedSha256=item.sha256)
        copied += 1

    cleanup = cleanup_misplaced_brief_history(items, new, state)
    sidecars = {"copied": 0, "replaced": 0, "resumed": 0, "skipped": 0}
    if copy_sdr:
        for item in items:
            result = copy_sidecar_best_effort(
                item,
                old,
                new,
                transaction_id,
                replace_existing=replace_existing_sdr,
            )
            state.mark_sidecar(
                item.destination,
                result,
                source=item.old_sidecar,
                destination=sidecar_destination(item.destination),
                matchBasis=item.sidecar_reason,
            )
            if result == "copied":
                sidecars["copied"] += 1
            elif result == "replaced-existing":
                sidecars["replaced"] += 1
            elif result == "resumed-existing-match":
                sidecars["resumed"] += 1
            else:
                sidecars["skipped"] += 1
    return {"copied": copied, "resumed": resumed, "misplacedBriefHistory": cleanup, "sidecars": sidecars}


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old-host", default=OLD_HOST_DEFAULT)
    parser.add_argument("--new-host", default=NEW_HOST_DEFAULT)
    parser.add_argument("--port", type=int, default=PORT_DEFAULT)
    parser.add_argument("--key", type=Path, default=DEFAULT_KEY)
    parser.add_argument("--known-hosts", type=Path, default=Path.home() / ".ssh" / "known_hosts")
    parser.add_argument("--lingua-root", type=Path, default=DEFAULT_LINGUA)
    parser.add_argument("--pocket-root", type=Path, default=DEFAULT_POCKET)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--copy-sdr", action="store_true", help="Best-effort compatible KOReader sidecars after every book succeeds.")
    parser.add_argument(
        "--replace-existing-sdr",
        action="store_true",
        help="Transactionally replace an existing safe sidecar; requires --apply --copy-sdr.",
    )
    parser.add_argument("--apply", action="store_true", help="Mutate the new Kindle. Without this flag the command is plan-only.")
    args = parser.parse_args(argv)
    if not (1 <= args.port <= 65535):
        parser.error("--port must be between 1 and 65535")
    if args.replace_existing_sdr and not (args.apply and args.copy_sdr):
        parser.error("--replace-existing-sdr requires both --apply and --copy-sdr")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    key = args.key.resolve(strict=True)
    books = discover_local_books(args.lingua_root, args.pocket_root)
    with KindleConnection(args.old_host, args.port, key, args.known_hosts) as old:
        old_paths = old.list_pdf_relatives()
        items = build_plan(books, old_paths)
        if args.copy_sdr:
            items = inspect_sidecars(items, old)
        if not args.apply:
            summary = {
                "mode": "plan",
                "applyRequired": True,
                "localBookCount": len(items),
                "linguaLeafCount": sum(item.collection == "LinguaLeaf" for item in items),
                "pocketPolishedCount": sum(item.collection == "PocketPolished" for item in items),
                "oldExactMappings": sum(item.mapping == "old-exact" for item in items),
                "sidecarEligible": sum(item.sidecar_eligible for item in items),
                "planFingerprint": plan_fingerprint(items),
            }
            print(json.dumps(summary, ensure_ascii=True, sort_keys=True))
            return 0
        state = ResumeState(args.state, items, args.old_host, args.new_host)
        with KindleConnection(args.new_host, args.port, key, args.known_hosts) as new:
            result = apply_plan(
                items,
                old,
                new,
                state,
                args.copy_sdr,
                replace_existing_sdr=args.replace_existing_sdr,
            )
    # ASCII-escaped JSON is portable across Windows consoles whose active
    # code page cannot encode CJK paths in the cleanup summary.
    print(json.dumps({"mode": "apply", "status": "complete", "bookCount": len(items), **result}, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except MigrationError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
