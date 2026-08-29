#!/usr/bin/env python3
"""Delete only the ten audited, explicitly superseded Kindle PDFs.

The default mode is a remote read-only audit.  ``--apply`` is required before
the tool changes the Kindle.  Every deletion is allowlisted by its complete
remote path, byte count, and SHA-256.  It is additionally gated on an exact
canonical successor from ``CANONICAL-LIBRARY.json``, a stopped KOReader, no
open file handle, no adjacent ``.sdr``, and regular (non-symlink) files.

This intentionally does not perform general duplicate discovery.  New or
merely similar files can never become deletion candidates at runtime.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import posixpath
import re
import shlex
import signal
import stat
import sys
import tempfile
import time
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Self

HOST_DEFAULT = "192.168.1.127"
PORT_DEFAULT = 2222
REMOTE_DOCUMENTS = "/mnt/us/documents"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = (
    Path.home() / "Nutstore" / "1" / "Share" / "LinguaLeaf" / "CANONICAL-LIBRARY.json"
)
DEFAULT_KEY = PROJECT_ROOT / "Handoff" / "keys" / "kindle_handoff_rsa"
DEFAULT_KNOWN_HOSTS = Path.home() / ".ssh" / "known_hosts"
DEFAULT_LEDGER = (
    PROJECT_ROOT
    / "device-backups"
    / "kindle-explicit-replacement-cleanup"
    / "ledger.json"
)
DEFAULT_REPORT = (
    PROJECT_ROOT
    / "device-backups"
    / "kindle-explicit-replacement-cleanup"
    / "report.json"
)

HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")
REMOTE_HASH_LINE = re.compile(rb"^([0-9a-fA-F]{64})(?:[ \t]|$)")


class CleanupError(RuntimeError):
    """Fail-closed error whose text is safe to show to the user."""


class CleanupInterrupted(CleanupError):
    """Raised by the installed termination-signal handlers."""


class GuardRefusal(CleanupError):
    """One allowlisted candidate did not pass a deletion guard."""


@dataclass(frozen=True)
class LegacyCandidate:
    candidate_id: str
    removed_book_id: str
    successor_book_id: str
    path: str
    size: int
    sha256: str
    successor_destination: str


@dataclass(frozen=True)
class CanonicalTarget:
    book_id: str
    destination: str
    path: str
    size: int
    sha256: str


@dataclass(frozen=True)
class AuditRow:
    candidate: LegacyCandidate
    target: CanonicalTarget
    status: str
    reason: str
    candidate_observed_size: int | None = None
    candidate_observed_sha256: str | None = None
    target_observed_size: int | None = None
    target_observed_sha256: str | None = None


EXPECTED_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    ("chronicle-lord-nobunaga", "chronicle-lord-nobunaga-illustrated"),
    ("kojiki", "kojiki-wenyan"),
    ("lean-startup", "lean-startup-complete-structure-repair"),
    ("origins-earth-human-history", "origins-earth-human-history-illustrated"),
    ("round-heads-sahara", "round-heads-sahara-illustrated"),
    ("sahara-cultural-history", "sahara-cultural-history-illustrated"),
    ("sanguozhi", "sanguozhi-pei-zhu"),
    ("shiji-aginti", "shiji-sanjiazhu"),
    ("sishu-jizhu", "sishu-jizhu-aginti"),
    ("your-money-or-your-life", "your-money-or-your-life-complete-structure-repair"),
)


# These ten physical files were observed and hashed on the PW5SE.  This is the
# complete deletion allowlist.  Do not broaden it to basename or fuzzy matches.
LEGACY_CANDIDATES: tuple[LegacyCandidate, ...] = (
    LegacyCandidate(
        "kojiki-jp-zh-chinese-note",
        "kojiki",
        "kojiki-wenyan",
        "/mnt/us/documents/LinguaLeaf/jp-zh-blackwhite/古事記（中文注）｜日本語-中文｜黑白.pdf",
        14_139_604,
        "5889964e7696b9b0d619349c231446cbde6c5ec78740720439ed9310310ba549",
        "blackwhite/02-Japanese-Literature/01-Classical/古事記（現代日本語・現代中文・英文注）｜文言文-English-日本語-中文｜最大語種・大字版・黑白.pdf",
    ),
    LegacyCandidate(
        "kojiki-jp-zh-japanese-note",
        "kojiki",
        "kojiki-wenyan",
        "/mnt/us/documents/LinguaLeaf/jp-zh-blackwhite/古事記（日文注）｜日本語-中文｜黑白.pdf",
        14_157_424,
        "9324b1785fb1e453a5d14d22bf4b1bf37932d585d406b85571a8c35cb33a2ba7",
        "blackwhite/02-Japanese-Literature/01-Classical/古事記（現代日本語・現代中文・英文注）｜文言文-English-日本語-中文｜最大語種・大字版・黑白.pdf",
    ),
    LegacyCandidate(
        "kojiki-wenyan-old-edition",
        "kojiki",
        "kojiki-wenyan",
        "/mnt/us/documents/LinguaLeaf/wenyan-main-quadrilingual-blackwhite/古事記（現代日本語・現代中文・英文注）｜文言文-English-日本語-中文｜黑白.pdf",
        15_535_742,
        "6fe45696ff9bbda59e121b397ea4b29a31626cb53905f13f0816070c83523377",
        "blackwhite/02-Japanese-Literature/01-Classical/古事記（現代日本語・現代中文・英文注）｜文言文-English-日本語-中文｜最大語種・大字版・黑白.pdf",
    ),
    LegacyCandidate(
        "origins-earth-human-history-unillustrated",
        "origins-earth-human-history",
        "origins-earth-human-history-illustrated",
        "/mnt/us/documents/LinguaLeaf/en-jp-zh-blackwhite/Origins： How Earth's History Shaped Human History（日文・中文注）｜English-日本語-中文｜黑白.pdf",
        8_097_503,
        "0b5ab1201afda5b88f2fa85932d57f71b8f1ec65cf2d87ec4063302d40934286",
        "blackwhite/04-History-and-Civilization/03-Global-and-Modern/Origins： How Earth's History Shaped Human History（図版収録・日文・中文注）｜English-日本語-中文｜最大語種・大字版・黑白.pdf",
    ),
    LegacyCandidate(
        "round-heads-sahara-unillustrated",
        "round-heads-sahara",
        "round-heads-sahara-illustrated",
        "/mnt/us/documents/LinguaLeaf/en-jp-zh-blackwhite/Round Heads： The Earliest Rock Paintings in the Sahara（日文・中文注）｜English-日本語-中文｜黑白.pdf",
        5_022_978,
        "115d0670ab3478071d32bc9433641818bbe0c2248a97e2bffe650b83cb3cdcaf",
        "blackwhite/04-History-and-Civilization/03-Global-and-Modern/Round Heads： The Earliest Rock Paintings in the Sahara（図版収録・日文・中文注）｜English-日本語-中文｜最大語種・大字版・黑白.pdf",
    ),
    LegacyCandidate(
        "sahara-cultural-history-unillustrated",
        "sahara-cultural-history",
        "sahara-cultural-history-illustrated",
        "/mnt/us/documents/LinguaLeaf/en-jp-zh-blackwhite/The Sahara： A Cultural History（日文・中文注）｜English-日本語-中文｜黑白.pdf",
        7_892_617,
        "c9975ab84c84e709c04fb4414e647cfb1bdf66694c65c270cf4f5db470189a9e",
        "blackwhite/04-History-and-Civilization/03-Global-and-Modern/The Sahara： A Cultural History（図版収録・日文・中文注）｜English-日本語-中文｜最大語種・大字版・黑白.pdf",
    ),
    LegacyCandidate(
        "sanguozhi-plain",
        "sanguozhi",
        "sanguozhi-pei-zhu",
        "/mnt/us/documents/LinguaLeaf/wenyan-main-quadrilingual-blackwhite/三國志（英文・現代日本語・現代中文注）｜文言文-English-日本語-中文｜黑白.pdf",
        51_278_585,
        "a165ed9bf85cef070e6ae593a13e0f5ecb647260f0e0c1f06c7d6821f2255a36",
        "blackwhite/01-Chinese-Classics/02-History-and-Geography/三國志裴松之注（英文・現代日本語・現代中文注）｜文言文-English-日本語-中文｜最大語種・大字版・黑白.pdf",
    ),
    LegacyCandidate(
        "sanguozhi-pei-zhu-old-edition",
        "sanguozhi",
        "sanguozhi-pei-zhu",
        "/mnt/us/documents/LinguaLeaf/wenyan-main-quadrilingual-blackwhite/三國志裴松之注（英文・現代日本語・現代中文注）｜文言文-English-日本語-中文｜黑白.pdf",
        85_471_171,
        "8ff21959b0c666b319bd9db89790999161178295a8107e8e0d85d827b7e25012",
        "blackwhite/01-Chinese-Classics/02-History-and-Geography/三國志裴松之注（英文・現代日本語・現代中文注）｜文言文-English-日本語-中文｜最大語種・大字版・黑白.pdf",
    ),
    LegacyCandidate(
        "shiji-aginti-old-edition",
        "shiji-aginti",
        "shiji-sanjiazhu",
        "/mnt/us/documents/LinguaLeaf/wenyan-jp-zh-trilingual-leftovers-blackwhite/史記（現代日本語・現代中文注）｜文言文-日本語-中文｜最大語種・大字版｜黑白.pdf",
        57_198_561,
        "179022a72755e24192b5922d43d59a6a97414d5c2589f9b93ccd9d93e0e3f68b",
        "blackwhite/01-Chinese-Classics/02-History-and-Geography/史記三家注（本文・日本語・現代中文）｜文言文-日本語-中文｜最大語種・大字版・黑白.pdf",
    ),
    LegacyCandidate(
        "sishu-jizhu-old-edition",
        "sishu-jizhu",
        "sishu-jizhu-aginti",
        "/mnt/us/documents/LinguaLeaf/jp-zh-blackwhite/四書章句集注（中文注）｜日本語-中文｜最大語種・大字版｜黑白.pdf",
        24_901_373,
        "c80f620c0b27cf688ead5d971131d643580b0f2fa830510ec96bf9ed8d1f12db",
        "blackwhite/01-Chinese-Classics/01-Philosophy-and-Thought/四書章句集註（日文注）｜中文-日本語｜最大語種・大字版・黑白.pdf",
    ),
)


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def configure_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        assert temporary is not None
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            with contextlib.suppress(FileNotFoundError):
                temporary.unlink()


def validate_allowlist() -> None:
    if len(LEGACY_CANDIDATES) != 10:
        raise CleanupError(
            "The explicit cleanup allowlist must contain exactly ten files."
        )
    ids = {row.candidate_id for row in LEGACY_CANDIDATES}
    paths = {row.path for row in LEGACY_CANDIDATES}
    if len(ids) != 10 or len(paths) != 10:
        raise CleanupError("The explicit cleanup allowlist contains a duplicate.")
    replacement_map = dict(EXPECTED_REPLACEMENTS)
    for row in LEGACY_CANDIDATES:
        normalized = posixpath.normpath(row.path)
        if (
            normalized != row.path
            or not normalized.startswith(REMOTE_DOCUMENTS + "/LinguaLeaf/")
            or not normalized.casefold().endswith(".pdf")
            or row.size <= 0
            or not HEX_SHA256.fullmatch(row.sha256)
        ):
            raise CleanupError(
                "The explicit cleanup allowlist contains an unsafe identity."
            )
        if replacement_map.get(row.removed_book_id) != row.successor_book_id:
            raise CleanupError(
                "An allowlisted file disagrees with the replacement policy."
            )
        safe_manifest_destination(row.successor_destination)


def safe_manifest_destination(value: str) -> str:
    if "\\" in value or "\x00" in value:
        raise CleanupError("The manifest contains an unsafe destination.")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or len(path.parts) < 2
        or path.parts[0] != "blackwhite"
        or path.suffix.casefold() != ".pdf"
        or any(
            part in {"", ".", ".."}
            or any(
                ord(character) < 0x20 or ord(character) == 0x7F for character in part
            )
            for part in path.parts
        )
    ):
        raise CleanupError("The manifest contains an unsafe destination.")
    return path.as_posix()


def sidecar_for_pdf(path: str) -> str:
    candidate = PurePosixPath(path)
    if candidate.suffix.casefold() != ".pdf":
        raise CleanupError("A sidecar guard was requested for a non-PDF.")
    return candidate.with_suffix(".sdr").as_posix()


def stable_manifest(path: Path) -> tuple[dict[str, Any], str]:
    try:
        state_before = path.lstat()
    except OSError as error:
        raise CleanupError("The canonical manifest is missing.") from error
    if path.is_symlink() or not stat.S_ISREG(state_before.st_mode):
        raise CleanupError(
            "The canonical manifest must be a regular, non-symlink file."
        )
    if state_before.st_size <= 0 or state_before.st_size > 32 * 1024 * 1024:
        raise CleanupError("The canonical manifest has an unexpected size.")
    try:
        payload = path.read_bytes()
        state_after = path.lstat()
    except OSError as error:
        raise CleanupError("The canonical manifest could not be read.") from error
    signature_before = (
        state_before.st_size,
        state_before.st_mtime_ns,
        state_before.st_ino,
    )
    signature_after = (state_after.st_size, state_after.st_mtime_ns, state_after.st_ino)
    if signature_before != signature_after or len(payload) != state_after.st_size:
        raise CleanupError("The canonical manifest changed while it was read.")
    try:
        parsed = json.loads(payload.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise CleanupError("The canonical manifest is invalid JSON.") from error
    if not isinstance(parsed, dict):
        raise CleanupError("The canonical manifest root is invalid.")
    return parsed, hashlib.sha256(payload).hexdigest()


def load_manifest_targets(
    path: Path,
) -> tuple[dict[str, CanonicalTarget], dict[str, Any]]:
    manifest, manifest_sha256 = stable_manifest(path)
    replacements = manifest.get("replacements")
    if not isinstance(replacements, list):
        raise CleanupError("The canonical replacement policy is missing.")
    observed_pairs: list[tuple[str, str]] = []
    for row in replacements:
        if not isinstance(row, dict):
            raise CleanupError("The canonical replacement policy is malformed.")
        removed, kept = row.get("removed"), row.get("kept")
        if not isinstance(removed, str) or not isinstance(kept, str):
            raise CleanupError("The canonical replacement policy is malformed.")
        observed_pairs.append((removed, kept))
    if len(observed_pairs) != 10 or set(observed_pairs) != set(EXPECTED_REPLACEMENTS):
        raise CleanupError(
            "The canonical replacement policy is not the reviewed ten-pair policy."
        )

    rows = manifest.get("rows")
    if not isinstance(rows, list):
        raise CleanupError("The canonical manifest rows are missing.")
    needed_ids = {candidate.successor_book_id for candidate in LEGACY_CANDIDATES}
    matched: dict[str, list[Mapping[str, Any]]] = {
        book_id: [] for book_id in needed_ids
    }
    for row in rows:
        if not isinstance(row, dict):
            raise CleanupError("A canonical manifest row is malformed.")
        book_id = row.get("book_id")
        if book_id in needed_ids and row.get("mode") == "blackwhite":
            matched[book_id].append(row)

    expected_destinations: dict[str, str] = {}
    for candidate in LEGACY_CANDIDATES:
        previous = expected_destinations.setdefault(
            candidate.successor_book_id, candidate.successor_destination
        )
        if previous != candidate.successor_destination:
            raise CleanupError("Two candidates disagree about their canonical target.")

    targets: dict[str, CanonicalTarget] = {}
    for book_id, candidates in matched.items():
        if len(candidates) != 1:
            raise CleanupError("A canonical successor is missing or ambiguous.")
        row = candidates[0]
        destination = row.get("destination")
        size = row.get("bytes")
        digest = row.get("sha256")
        if not isinstance(destination, str):
            raise CleanupError("A canonical successor destination is invalid.")
        destination = safe_manifest_destination(destination)
        if destination != expected_destinations[book_id]:
            raise CleanupError(
                "A canonical successor moved from its reviewed destination."
            )
        if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
            raise CleanupError("A canonical successor size is invalid.")
        if not isinstance(digest, str) or not HEX_SHA256.fullmatch(digest):
            raise CleanupError("A canonical successor SHA-256 is invalid.")
        target_path = posixpath.join(REMOTE_DOCUMENTS, "LinguaLeaf", destination)
        targets[book_id] = CanonicalTarget(
            book_id=book_id,
            destination=destination,
            path=target_path,
            size=size,
            sha256=digest,
        )
    return targets, {
        "path": str(path),
        "sha256": manifest_sha256,
        "schemaVersion": manifest.get("schema_version"),
        "generatedAt": manifest.get("generated_at"),
    }


class KindleConnection:
    """Strict saved-host-key, key-only Paramiko connection to the PW5SE."""

    def __init__(self, host: str, port: int, key: Path, known_hosts: Path) -> None:
        if not key.is_file() or key.is_symlink():
            raise CleanupError(
                "The configured Kindle private key is missing or unsafe."
            )
        if not known_hosts.is_file() or known_hosts.is_symlink():
            raise CleanupError("The configured known_hosts file is missing or unsafe.")
        try:
            import paramiko
        except ImportError as error:  # pragma: no cover - environment guard
            raise CleanupError("paramiko is required for Kindle cleanup.") from error
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
                raise CleanupError("The Kindle SSH transport was not established.")
            transport.set_keepalive(30)
            self.sftp = self.client.open_sftp()
        except Exception as error:
            self.client.close()
            if isinstance(error, CleanupError):
                raise
            raise CleanupError(
                "Strict Kindle SSH failed; check its saved host key and key login."
            ) from error
        self._hash_cache: dict[str, tuple[tuple[int, int], str]] = {}

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        try:
            self.sftp.close()
        finally:
            self.client.close()

    def exec_checked(self, command: str, purpose: str, timeout: int = 300) -> bytes:
        _stdin, stdout, stderr = self.client.exec_command(command, timeout=timeout)
        payload = stdout.read()
        stderr.read()
        code = stdout.channel.recv_exit_status()
        if code != 0:
            raise CleanupError(f"{purpose} failed with remote exit code {code}.")
        return payload

    def lstat(self, path: str) -> Any | None:
        try:
            return self.sftp.lstat(path)
        except OSError as error:
            if getattr(error, "errno", None) == 2 or "No such file" in str(error):
                return None
            raise CleanupError("A remote lstat operation failed.") from error

    @staticmethod
    def require_regular(path: str, state: Any | None) -> Any:
        if state is None:
            raise GuardRefusal(f"required file is missing: {path}")
        if stat.S_ISLNK(state.st_mode) or not stat.S_ISREG(state.st_mode):
            raise GuardRefusal(
                f"required path is not a regular non-symlink file: {path}"
            )
        return state

    @staticmethod
    def signature(state: Any) -> tuple[int, int]:
        return int(state.st_size), int(getattr(state, "st_mtime", 0))

    def sha256_file(
        self, path: str, *, expected_size: int | None = None, force: bool = False
    ) -> str:
        before = self.require_regular(path, self.lstat(path))
        if expected_size is not None and int(before.st_size) != expected_size:
            raise GuardRefusal(f"file size differs from its reviewed identity: {path}")
        signature = self.signature(before)
        cached = self._hash_cache.get(path)
        if not force and cached is not None and cached[0] == signature:
            return cached[1]
        output = self.exec_checked(
            f"LC_ALL=C sha256sum {shlex.quote(path)}",
            "Remote SHA-256 verification",
            timeout=900,
        )
        match = REMOTE_HASH_LINE.match(output.strip())
        if match is None:
            raise CleanupError("The Kindle returned an invalid SHA-256 result.")
        digest = match.group(1).decode("ascii").casefold()
        after = self.require_regular(path, self.lstat(path))
        if self.signature(after) != signature:
            raise GuardRefusal(f"file changed while it was hashed: {path}")
        self._hash_cache[path] = (signature, digest)
        return digest

    def koreader_running(self) -> bool:
        """Use BusyBox's exact reader.lua lookup; never scan SFTP's /proc path."""
        output = self.exec_checked(
            "command -v pidof >/dev/null 2>&1 || exit 127; "
            "pidof reader.lua >/dev/null 2>&1; rc=$?; "
            "case $rc in 0) printf '1\n';; 1) printf '0\n';; *) exit $rc;; esac",
            "KOReader process inspection",
            timeout=15,
        ).strip()
        if output not in {b"0", b"1"}:
            raise CleanupError(
                "KOReader process inspection returned an invalid result."
            )
        return output == b"1"

    def assert_koreader_stopped(self) -> None:
        if self.koreader_running():
            raise GuardRefusal("KOReader is running; exit it before explicit cleanup.")

    def has_open_file_handle(self, path: str) -> bool:
        if not path.startswith("/") or posixpath.normpath(path) != path:
            raise CleanupError("The open-file audit path is unsafe.")

        def disappeared(error: OSError) -> bool:
            return getattr(error, "errno", None) in {2, 3} or "No such file" in str(
                error
            )

        try:
            processes = self.sftp.listdir_attr("/proc")
        except OSError as error:
            raise CleanupError(
                "The open-file audit could not inspect /proc."
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
                raise CleanupError(
                    "The open-file audit could not inspect a process."
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
                    raise CleanupError(
                        "The open-file audit could not inspect a descriptor."
                    ) from error
                if linked == path or linked == path + " (deleted)":
                    return True
        return False

    def prevent_screen_saver(self) -> int:
        value = (
            self.exec_checked(
                "lipc-get-prop com.lab126.powerd preventScreenSaver",
                "Kindle keep-awake inspection",
            )
            .decode("ascii", "strict")
            .strip()
        )
        if value not in {"0", "1"}:
            raise CleanupError("The Kindle returned an invalid keep-awake value.")
        return int(value)

    def set_prevent_screen_saver(self, value: int) -> None:
        if value not in {0, 1}:
            raise CleanupError("An invalid keep-awake value was requested.")
        self.exec_checked(
            f"lipc-set-prop com.lab126.powerd preventScreenSaver {value}",
            "Kindle keep-awake update",
        )
        if self.prevent_screen_saver() != value:
            raise CleanupError("The Kindle keep-awake update did not verify.")

    def remove_candidate(self, path: str) -> None:
        if path not in {candidate.path for candidate in LEGACY_CANDIDATES}:
            raise CleanupError("Refusing to remove a path outside the fixed allowlist.")
        try:
            self.sftp.remove(path)
        except OSError as error:
            raise CleanupError("An allowlisted PDF could not be removed.") from error
        self._hash_cache.pop(path, None)
        if self.lstat(path) is not None:
            raise CleanupError("An allowlisted PDF removal did not verify.")


class Ledger:
    SCHEMA = 1

    def __init__(self, path: Path, *, host: str, port: int, fingerprint: str) -> None:
        self.path = path
        if path.exists():
            if path.is_symlink() or not path.is_file():
                raise CleanupError("The cleanup ledger is unsafe.")
            try:
                self.data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as error:
                raise CleanupError("The cleanup ledger is invalid.") from error
            if not isinstance(self.data, dict):
                raise CleanupError("The cleanup ledger root is invalid.")
            if (
                self.data.get("schemaVersion") != self.SCHEMA
                or self.data.get("host") != host
                or self.data.get("port") != port
                or self.data.get("planFingerprint") != fingerprint
            ):
                raise CleanupError(
                    "The cleanup ledger belongs to a different reviewed plan."
                )
            if not isinstance(self.data.get("candidates"), dict):
                raise CleanupError("The cleanup ledger candidate state is invalid.")
            if not isinstance(self.data.get("keepAwake"), dict):
                raise CleanupError("The cleanup ledger keep-awake state is invalid.")
        else:
            self.data = {
                "schemaVersion": self.SCHEMA,
                "host": host,
                "port": port,
                "planFingerprint": fingerprint,
                "createdAt": now_iso(),
                "candidates": {},
                "keepAwake": {"active": False},
            }
        self.save()

    def save(self) -> None:
        self.data["updatedAt"] = now_iso()
        write_json_atomic(self.path, self.data)

    def mark_candidate(
        self, candidate: LegacyCandidate, status: str, **details: Any
    ) -> None:
        self.data.setdefault("candidates", {})[candidate.candidate_id] = {
            "path": candidate.path,
            "size": candidate.size,
            "sha256": candidate.sha256,
            "status": status,
            "updatedAt": now_iso(),
            **details,
        }
        self.save()

    def mark_keepawake(self, *, active: bool, original: int | None = None) -> None:
        row = self.data.setdefault("keepAwake", {})
        row.update(active=active, updatedAt=now_iso())
        if original is not None:
            row["original"] = original
        self.save()

    def stale_keepawake_original(self) -> int | None:
        row = self.data.get("keepAwake")
        if not isinstance(row, dict) or row.get("active") is not True:
            return None
        original = row.get("original")
        if original not in {0, 1}:
            raise CleanupError(
                "The cleanup ledger has invalid keep-awake recovery state."
            )
        return int(original)


class KeepAwake:
    def __init__(self, connection: KindleConnection, ledger: Ledger) -> None:
        self.connection = connection
        self.ledger = ledger
        self.original: int | None = None

    def __enter__(self) -> Self:
        self.original = self.connection.prevent_screen_saver()
        self.ledger.mark_keepawake(active=True, original=self.original)
        try:
            if self.original != 1:
                self.connection.set_prevent_screen_saver(1)
        except BaseException:
            try:
                if self.connection.prevent_screen_saver() != self.original:
                    self.connection.set_prevent_screen_saver(self.original)
                self.ledger.mark_keepawake(active=False, original=self.original)
            except BaseException as restore_error:
                raise CleanupError(
                    "Keep-awake enable failed and its original value could not be restored."
                ) from restore_error
            raise
        return self

    def __exit__(self, *_: object) -> None:
        if self.original is None:
            return
        try:
            if self.connection.prevent_screen_saver() != self.original:
                self.connection.set_prevent_screen_saver(self.original)
        except BaseException as restore_error:
            # Leave active=true so a later --apply can recover the known baseline.
            raise CleanupError(
                "The original Kindle keep-awake value could not be restored."
            ) from restore_error
        self.ledger.mark_keepawake(active=False, original=self.original)


def recover_stale_keepawake(connection: KindleConnection, ledger: Ledger) -> bool:
    original = ledger.stale_keepawake_original()
    if original is None:
        return False
    if connection.prevent_screen_saver() != original:
        connection.set_prevent_screen_saver(original)
    ledger.mark_keepawake(active=False, original=original)
    return True


def plan_fingerprint(targets: Mapping[str, CanonicalTarget]) -> str:
    payload = {
        "candidates": [asdict(candidate) for candidate in LEGACY_CANDIDATES],
        "targets": [asdict(targets[key]) for key in sorted(targets)],
        "replacementPolicy": list(EXPECTED_REPLACEMENTS),
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def verify_target(
    connection: KindleConnection, target: CanonicalTarget, *, force: bool
) -> tuple[int, str]:
    try:
        state = connection.require_regular(target.path, connection.lstat(target.path))
    except GuardRefusal as error:
        raise GuardRefusal(f"canonical successor guard failed: {error}") from error
    observed_size = int(state.st_size)
    if observed_size != target.size:
        raise GuardRefusal("canonical successor size differs from the manifest")
    observed_hash = connection.sha256_file(
        target.path, expected_size=target.size, force=force
    )
    if observed_hash != target.sha256:
        raise GuardRefusal("canonical successor SHA-256 differs from the manifest")
    return observed_size, observed_hash


def verify_candidate(
    connection: KindleConnection,
    candidate: LegacyCandidate,
    target: CanonicalTarget,
    *,
    force_hashes: bool,
) -> tuple[int, str, int, str]:
    state = connection.require_regular(candidate.path, connection.lstat(candidate.path))
    observed_size = int(state.st_size)
    if observed_size != candidate.size:
        raise GuardRefusal("legacy candidate size differs from its audited identity")
    if connection.lstat(sidecar_for_pdf(candidate.path)) is not None:
        raise GuardRefusal("an adjacent .sdr exists; reading state must not be deleted")
    observed_hash = connection.sha256_file(
        candidate.path, expected_size=candidate.size, force=force_hashes
    )
    if observed_hash != candidate.sha256:
        raise GuardRefusal("legacy candidate SHA-256 differs from its audited identity")
    if connection.has_open_file_handle(candidate.path):
        raise GuardRefusal("the legacy candidate currently has an open file handle")
    target_size, target_hash = verify_target(connection, target, force=force_hashes)
    return observed_size, observed_hash, target_size, target_hash


def audit_candidates(
    connection: KindleConnection,
    targets: Mapping[str, CanonicalTarget],
    *,
    koreader_running: bool,
) -> list[AuditRow]:
    rows: list[AuditRow] = []
    for candidate in LEGACY_CANDIDATES:
        target = targets[candidate.successor_book_id]
        if connection.lstat(candidate.path) is None:
            try:
                target_size, target_hash = verify_target(
                    connection, target, force=False
                )
                if koreader_running:
                    raise GuardRefusal(
                        "KOReader is running; exit it before explicit cleanup"
                    )
                rows.append(
                    AuditRow(
                        candidate,
                        target,
                        "already-absent",
                        "candidate is absent and its exact successor is present",
                        target_observed_size=target_size,
                        target_observed_sha256=target_hash,
                    )
                )
            except GuardRefusal as error:
                rows.append(AuditRow(candidate, target, "refuse", str(error)))
            continue
        try:
            candidate_size, candidate_hash, target_size, target_hash = verify_candidate(
                connection, candidate, target, force_hashes=False
            )
            if koreader_running:
                raise GuardRefusal(
                    "KOReader is running; exit it before explicit cleanup"
                )
            rows.append(
                AuditRow(
                    candidate,
                    target,
                    "eligible",
                    "all exact deletion guards passed",
                    candidate_size,
                    candidate_hash,
                    target_size,
                    target_hash,
                )
            )
        except GuardRefusal as error:
            rows.append(AuditRow(candidate, target, "refuse", str(error)))
    return rows


def apply_one(
    connection: KindleConnection,
    ledger: Ledger,
    row: AuditRow,
    deleted: list[str],
) -> None:
    connection.assert_koreader_stopped()
    # Hash this candidate first, prove it is not open, then force-hash its
    # successor even when another candidate shares that successor.
    candidate_state = connection.require_regular(
        row.candidate.path, connection.lstat(row.candidate.path)
    )
    if int(candidate_state.st_size) != row.candidate.size:
        raise CleanupError("A candidate changed after preflight; cleanup stopped.")
    if connection.lstat(sidecar_for_pdf(row.candidate.path)) is not None:
        raise CleanupError("A sidecar appeared after preflight; cleanup stopped.")
    candidate_hash = connection.sha256_file(
        row.candidate.path, expected_size=row.candidate.size, force=True
    )
    if candidate_hash != row.candidate.sha256:
        raise CleanupError("A candidate changed after preflight; cleanup stopped.")
    if connection.has_open_file_handle(row.candidate.path):
        raise CleanupError("A candidate became open after preflight; cleanup stopped.")
    candidate_signature = connection.signature(
        connection.require_regular(
            row.candidate.path, connection.lstat(row.candidate.path)
        )
    )
    verify_target(connection, row.target, force=True)

    # The successor hash can take time.  Close the resulting window by
    # rechecking the candidate's exact identity guards immediately before
    # the one allowlisted unlink.
    final_state = connection.require_regular(
        row.candidate.path, connection.lstat(row.candidate.path)
    )
    if (
        int(final_state.st_size) != row.candidate.size
        or connection.signature(final_state) != candidate_signature
    ):
        raise CleanupError("A candidate changed while its successor was verified.")
    if connection.lstat(sidecar_for_pdf(row.candidate.path)) is not None:
        raise CleanupError(
            "A sidecar appeared after successor verification; cleanup stopped."
        )
    if connection.has_open_file_handle(row.candidate.path):
        raise CleanupError(
            "A candidate became open after successor verification; cleanup stopped."
        )
    connection.assert_koreader_stopped()
    ledger.mark_candidate(row.candidate, "deleting", target=row.target.path)
    connection.remove_candidate(row.candidate.path)
    # The remote absence has already been verified by remove_candidate().
    # Record it for the failure report before the subsequent local ledger save.
    deleted.append(row.candidate.path)
    ledger.mark_candidate(row.candidate, "deleted", target=row.target.path)


def apply_audits(
    connection: KindleConnection,
    ledger: Ledger,
    rows: Sequence[AuditRow],
    *,
    deleted_out: list[str] | None = None,
    failed_out: dict[str, str] | None = None,
) -> list[str]:
    conflicts = [row for row in rows if row.status == "refuse"]
    if conflicts:
        raise CleanupError(
            "At least one candidate refused its guards; nothing was deleted."
        )
    eligible = [row for row in rows if row.status == "eligible"]
    deleted = deleted_out if deleted_out is not None else []
    for row in eligible:
        try:
            apply_one(connection, ledger, row, deleted)
        except BaseException as error:
            if failed_out is not None:
                failed_out.update(
                    candidateId=row.candidate.candidate_id,
                    path=row.candidate.path,
                    reason=str(error) if str(error) else type(error).__name__,
                )
            raise
    for row in rows:
        if row.status == "already-absent":
            ledger.mark_candidate(
                row.candidate, "already-absent", target=row.target.path
            )
    return deleted


def report_value(
    *,
    args: argparse.Namespace,
    manifest_meta: Mapping[str, Any],
    fingerprint: str,
    rows: Sequence[AuditRow],
    started_at: str,
    applied: bool,
    deleted: Sequence[str],
    stale_keepawake_recovered: bool,
    failure: str | None = None,
    transaction_complete: bool = False,
    failed_candidate: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    deleted_set = set(deleted)
    failed_id = failed_candidate.get("candidateId") if failed_candidate else None

    def effective_status(row: AuditRow) -> str:
        if row.candidate.path in deleted_set:
            return "deleted"
        if row.candidate.candidate_id == failed_id:
            return "failed-late"
        return row.status

    counts: dict[str, int] = {}
    for row in rows:
        status = effective_status(row)
        counts[status] = counts.get(status, 0) + 1
    return {
        "schemaVersion": 1,
        "startedAt": started_at,
        "finishedAt": now_iso(),
        "host": args.host,
        "port": args.port,
        "applyRequested": bool(args.apply),
        "applied": applied,
        "transactionComplete": transaction_complete,
        "failure": failure,
        "failedCandidate": dict(failed_candidate) if failed_candidate else None,
        "planFingerprint": fingerprint,
        "manifest": dict(manifest_meta),
        "allowlistCount": len(LEGACY_CANDIDATES),
        "counts": counts,
        "deleted": list(deleted),
        "staleKeepAwakeRecovered": stale_keepawake_recovered,
        "candidates": [
            {
                "candidate": asdict(row.candidate),
                "target": asdict(row.target),
                "status": effective_status(row),
                "reason": (
                    failed_candidate["reason"]
                    if failed_candidate and row.candidate.candidate_id == failed_id
                    else row.reason
                ),
                "candidateObservedSize": row.candidate_observed_size,
                "candidateObservedSha256": row.candidate_observed_sha256,
                "targetObservedSize": row.target_observed_size,
                "targetObservedSha256": row.target_observed_sha256,
            }
            for row in rows
        ],
    }


def print_plan(rows: Sequence[AuditRow], *, apply: bool, report: Path) -> None:
    print("Explicit Kindle replacement cleanup")
    print(f"Mode: {'APPLY' if apply else 'DRY-RUN (remote read-only)'}")
    print(f"Fixed allowlist: {len(LEGACY_CANDIDATES)} PDFs")
    for row in rows:
        if row.status == "eligible":
            label = "DELETE" if apply else "WOULD DELETE"
        elif row.status == "already-absent":
            label = "SKIP"
        else:
            label = "REFUSE"
        print(f"{label}: {row.candidate.path}")
        print(f"  successor: {row.target.path}")
        print(f"  reason: {row.reason}")
    print(f"JSON report: {report}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit or remove only the ten reviewed superseded PW5SE PDFs."
    )
    parser.add_argument(
        "--apply", action="store_true", help="allow guarded Kindle deletions"
    )
    parser.add_argument("--host", default=HOST_DEFAULT)
    parser.add_argument("--port", type=int, default=PORT_DEFAULT)
    parser.add_argument("--key", type=Path, default=DEFAULT_KEY)
    parser.add_argument("--known-hosts", type=Path, default=DEFAULT_KNOWN_HOSTS)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser


def install_signal_handlers() -> None:
    def terminate(signum: int, _frame: object) -> None:
        raise CleanupInterrupted(f"Interrupted by signal {signum}.")

    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, terminate)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, terminate)


def run(args: argparse.Namespace) -> int:
    validate_allowlist()
    if not 1 <= args.port <= 65535:
        raise CleanupError("The SSH port is invalid.")
    if args.ledger.resolve() == args.report.resolve():
        raise CleanupError("The ledger and report paths must differ.")
    started_at = now_iso()
    targets, manifest_meta = load_manifest_targets(args.manifest)
    fingerprint = plan_fingerprint(targets)
    ledger = Ledger(
        args.ledger, host=args.host, port=args.port, fingerprint=fingerprint
    )
    rows: list[AuditRow] = []
    deleted: list[str] = []
    applied = False
    stale_recovered = False
    failure: str | None = None
    transaction_complete = False
    failed_candidate: dict[str, str] = {}
    try:
        with KindleConnection(
            args.host, args.port, args.key, args.known_hosts
        ) as connection:
            running = connection.koreader_running()
            if args.apply:
                if running:
                    rows = audit_candidates(connection, targets, koreader_running=True)
                    raise CleanupError("KOReader is running; nothing was deleted.")
                stale_recovered = recover_stale_keepawake(connection, ledger)
                with KeepAwake(connection, ledger):
                    connection.assert_koreader_stopped()
                    rows = audit_candidates(connection, targets, koreader_running=False)
                    preliminary = report_value(
                        args=args,
                        manifest_meta=manifest_meta,
                        fingerprint=fingerprint,
                        rows=rows,
                        started_at=started_at,
                        applied=False,
                        deleted=(),
                        stale_keepawake_recovered=stale_recovered,
                    )
                    write_json_atomic(args.report, preliminary)
                    print_plan(rows, apply=True, report=args.report)
                    apply_audits(
                        connection,
                        ledger,
                        rows,
                        deleted_out=deleted,
                        failed_out=failed_candidate,
                    )
                    applied = True
                    transaction_complete = True
            else:
                rows = audit_candidates(connection, targets, koreader_running=running)
    except BaseException as error:
        failure = str(error) if str(error) else type(error).__name__
        applied = bool(deleted)
        if rows:
            failed_report = report_value(
                args=args,
                manifest_meta=manifest_meta,
                fingerprint=fingerprint,
                rows=rows,
                started_at=started_at,
                applied=applied,
                deleted=deleted,
                stale_keepawake_recovered=stale_recovered,
                failure=failure,
                transaction_complete=False,
                failed_candidate=failed_candidate,
            )
            write_json_atomic(args.report, failed_report)
        raise

    report = report_value(
        args=args,
        manifest_meta=manifest_meta,
        fingerprint=fingerprint,
        rows=rows,
        started_at=started_at,
        applied=applied,
        deleted=deleted,
        stale_keepawake_recovered=stale_recovered,
        failure=failure,
        transaction_complete=transaction_complete,
        failed_candidate=failed_candidate,
    )
    write_json_atomic(args.report, report)
    if not args.apply:
        print_plan(rows, apply=False, report=args.report)
    elif applied:
        print(f"Deleted and verified absent: {len(deleted)}")
        print(f"JSON report: {args.report}")
    return 2 if any(row.status == "refuse" for row in rows) else 0


def main(argv: Sequence[str] | None = None) -> int:
    configure_console()
    install_signal_handlers()
    try:
        return run(build_parser().parse_args(argv))
    except (CleanupError, KeyboardInterrupt) as error:
        message = str(error) if str(error) else "Interrupted."
        print(f"ERROR: {message}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
