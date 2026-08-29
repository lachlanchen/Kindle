#!/usr/bin/env python3
"""Read-only, independent post-sync audit for the 2026-08-29 PW5SE library.

The verifier never opens a remote file for writing and never changes Kindle
power or autostart state.  It compares the complete canonical PDF inventory to
CANONICAL-LIBRARY.json, hashes every requested destination on the Kindle, and
checks the deliberately preserved KOReader sidecars and legacy shelves.  Exact
inventory enforcement is intentionally limited to ``LinguaLeaf/blackwhite``;
unreviewed old-layout siblings are retained unless they are one of the ten
explicit Markdown-backed replacement candidates.
"""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import json
import posixpath
import re
import stat
import sys
import time
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import ModuleType
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SYNC_SCRIPT = PROJECT_ROOT / "scripts" / "sync-kindle-canonical-library.py"
CLEANUP_SCRIPT = PROJECT_ROOT / "scripts" / "cleanup-kindle-explicit-replacements.py"
DEFAULT_SYNC_REPORT = (
    PROJECT_ROOT / "device-backups" / "kindle-canonical-library-sync" / "report.json"
)
DEFAULT_CLEANUP_REPORT = (
    PROJECT_ROOT
    / "device-backups"
    / "kindle-explicit-replacement-cleanup"
    / "report.json"
)
DEFAULT_REPORT = (
    PROJECT_ROOT / "device-backups" / "kindle-post-sync-verification" / "report.json"
)
CANONICAL_SIDECAR_COUNT = 8
LEGACY_PAIR_COUNT = 17
LINGUA_LEGACY_PAIR_COUNT = 16
LAZYTRAVEL_LEGACY_PAIR_COUNT = 1
NOTE_COUNT = 35
HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")
ACTION_KEYS = {
    "action",
    "kind",
    "destination",
    "size",
    "sha256",
    "source_local",
    "source_remote",
    "sidecar_source",
    "sidecar_destination",
    "reason",
}
MANIFEST_ROW_KEYS = {
    "book_id",
    "family",
    "edition",
    "category",
    "mode",
    "source",
    "destination",
    "bytes",
    "sha256",
    "reason",
}

# These eight audited books had byte-identical PDFs and compatible reading
# state.  `a-briefer-history-of-time` moved in the first resumable apply, so a
# later report may list only a subset of these sidecar moves.
RESUMED_CANONICAL_SIDECAR_BOOK_ID = "a-briefer-history-of-time"
EXPECTED_CANONICAL_SIDECAR_BOOK_IDS = frozenset(
    {
        RESUMED_CANONICAL_SIDECAR_BOOK_ID,
        "cao-pi-wei-wendi-ji",
        "quran",
        "sahara-cultural-history-illustrated",
        "shijing",
        "tokugawa-ieyasu-yamaoka",
        "xijing-zaji-siku",
        "zizhi-tongjian-part-01",
    }
)
RETAINED_STANDALONE_FILES = (("LazyEarn", "How You Got Rich - V2 - Pocket 1.2x.pdf"),)


class VerifyError(RuntimeError):
    """A fail-closed verification error."""


@dataclass(frozen=True)
class ExpectedFile:
    path: str
    size: int
    sha256: str
    kind: str


@dataclass(frozen=True)
class TreeInventory:
    files: frozenset[str]
    pdfs: frozenset[str]
    sidecars: frozenset[str]
    file_sizes: Mapping[str, int]


def load_sibling(path: Path, module_name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise VerifyError(f"Could not load required sibling script: {path.name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise VerifyError(f"{label} is missing or invalid: {path}") from error
    if not isinstance(value, dict):
        raise VerifyError(f"{label} must contain one JSON object.")
    return value


def exact_set(label: str, actual: Iterable[str], expected: Iterable[str]) -> None:
    actual_set = set(actual)
    expected_set = set(expected)
    if actual_set == expected_set:
        return
    missing = sorted(expected_set - actual_set, key=str.casefold)
    extra = sorted(actual_set - expected_set, key=str.casefold)
    details = []
    if missing:
        details.append(f"missing={missing[:3]!r}")
    if extra:
        details.append(f"unexpected={extra[:3]!r}")
    raise VerifyError(f"{label} differs ({'; '.join(details)}).")


def strict_int(value: Any) -> bool:
    return type(value) is int


def safe_remote_path(value: Any, *, suffix: str | None = None) -> str:
    if not isinstance(value, str) or not value.startswith("/mnt/us/documents/"):
        raise VerifyError("A report action contains an invalid remote path.")
    if (
        posixpath.normpath(value) != value
        or "\\" in value
        or any(ord(character) < 0x20 or ord(character) == 0x7F for character in value)
    ):
        raise VerifyError("A report action contains an unsafe remote path.")
    if suffix is not None and not value.casefold().endswith(suffix.casefold()):
        raise VerifyError("A report action path has the wrong suffix.")
    return value


def validate_sync_report(
    report: Mapping[str, Any],
    *,
    host: str,
    port: int,
    manifest_sha256: str,
    expected_items: Mapping[str, ExpectedFile],
) -> tuple[dict[str, ExpectedFile], set[str]]:
    if (
        report.get("schemaVersion") != 1
        or type(report.get("schemaVersion")) is not int
        or report.get("status") != "complete"
        or report.get("mode") != "apply"
        or report.get("host") != host
        or report.get("port") != port
        or type(report.get("port")) is not int
        or report.get("remoteDocuments") != "/mnt/us/documents"
        or report.get("keepAwakeRestored") is not True
        or not isinstance(report.get("completedAt"), str)
    ):
        raise VerifyError(
            "The canonical sync report is not a completed apply for this host and port."
        )
    manifest = report.get("manifest")
    if (
        not isinstance(manifest, Mapping)
        or manifest.get("schemaVersion") != 2
        or type(manifest.get("schemaVersion")) is not int
        or manifest.get("blackwhiteRows") != 286
        or type(manifest.get("blackwhiteRows")) is not int
        or manifest.get("categories") != 29
        or type(manifest.get("categories")) is not int
        or manifest.get("sha256") != manifest_sha256
    ):
        raise VerifyError(
            "The sync report is not bound to the current canonical manifest."
        )
    summary = report.get("sourceSummary")
    expected_by_kind = {
        "canonical-pdf": 286,
        "note": 34,
        "standalone-pdf": 5,
    }
    expected_bytes = sum(item.size for item in expected_items.values())
    if (
        not isinstance(summary, Mapping)
        or summary.get("byKind") != expected_by_kind
        or summary.get("items") != len(expected_items)
        or type(summary.get("items")) is not int
        or summary.get("bytes") != expected_bytes
        or type(summary.get("bytes")) is not int
        or len(expected_items) != 325
    ):
        raise VerifyError("The canonical sync report has unexpected source totals.")

    actions = report.get("actions")
    if not isinstance(actions, list):
        raise VerifyError("The canonical sync report action list is invalid.")
    expected_seen: set[str] = set()
    legacy: dict[str, ExpectedFile] = {}
    reported_canonical_sidecars: set[str] = set()
    action_counts: Counter[str] = Counter()
    for row in actions:
        if not isinstance(row, dict) or set(row) != ACTION_KEYS:
            raise VerifyError("A sync report action has an unexpected schema.")
        action = row["action"]
        kind = row["kind"]
        reason = row["reason"]
        size = row["size"]
        digest = row["sha256"]
        if (
            not isinstance(action, str)
            or action
            not in {"move", "reuse", "upload", "legacy-move", "history-repair"}
            or not isinstance(kind, str)
            or not isinstance(reason, str)
            or not strict_int(size)
            or size <= 0
            or not isinstance(digest, str)
            or not HEX_SHA256.fullmatch(digest)
        ):
            raise VerifyError("A sync report action contains an invalid typed field.")
        destination = safe_remote_path(
            row["destination"], suffix=None if kind == "note" else ".pdf"
        )
        for field in (
            "source_local",
            "source_remote",
            "sidecar_source",
            "sidecar_destination",
        ):
            if row[field] is not None and not isinstance(row[field], str):
                raise VerifyError("A sync report optional path has an invalid type.")
        if row["source_remote"] is not None:
            safe_remote_path(row["source_remote"], suffix=".pdf")
        sidecar_source = row["sidecar_source"]
        sidecar_destination = row["sidecar_destination"]
        if (sidecar_source is None) != (sidecar_destination is None):
            raise VerifyError("A sync report action contains an unpaired sidecar path.")
        if sidecar_source is not None:
            safe_remote_path(sidecar_source, suffix=".sdr")
            safe_remote_path(sidecar_destination, suffix=".sdr")
            if sidecar_destination != str(
                PurePosixPath(destination).with_suffix(".sdr")
            ):
                raise VerifyError("A sync report sidecar is not adjacent to its PDF.")
        action_counts[action] += 1

        if kind in {"canonical-pdf", "standalone-pdf", "note"}:
            if action not in {"move", "reuse", "upload"}:
                raise VerifyError("A requested item has an invalid report action.")
            expected = expected_items.get(destination)
            if expected is None or expected.kind != kind:
                raise VerifyError(
                    "The sync report contains an unexpected requested item."
                )
            if destination in expected_seen:
                raise VerifyError("The sync report repeats a requested destination.")
            if size != expected.size or digest != expected.sha256:
                raise VerifyError(
                    "A sync report requested item differs from its source identity."
                )
            expected_seen.add(destination)
            if kind == "canonical-pdf" and sidecar_destination is not None:
                reported_canonical_sidecars.add(sidecar_destination)
        elif kind == "legacy-pdf":
            if action != "legacy-move" or sidecar_destination is None:
                raise VerifyError("A legacy report action is invalid.")
            if destination in legacy:
                raise VerifyError(
                    "The canonical sync report repeats a legacy destination."
                )
            legacy[destination] = ExpectedFile(destination, size, digest, "legacy-pdf")
        elif kind == "metadata-repair":
            if action != "history-repair" or sidecar_destination is not None:
                raise VerifyError("A metadata repair action is invalid.")
        else:
            raise VerifyError("A sync report action has an unknown kind.")

    exact_set("Sync report requested destinations", expected_seen, expected_items)
    if len(legacy) != LEGACY_PAIR_COUNT:
        raise VerifyError("The canonical sync report legacy action count is invalid.")
    action_summary = report.get("actionSummary")
    if (
        not isinstance(action_summary, dict)
        or any(
            not isinstance(key, str) or not strict_int(value)
            for key, value in action_summary.items()
        )
        or action_summary != dict(sorted(action_counts.items()))
        or action_summary.get("legacy-move") != LEGACY_PAIR_COUNT
    ):
        raise VerifyError("The canonical sync action summary does not match its rows.")
    return legacy, reported_canonical_sidecars


def validate_cleanup_report(
    report: Mapping[str, Any],
    allowlisted: Mapping[str, Any],
    *,
    host: str,
    port: int,
    manifest_sha256: str,
) -> None:
    if (
        report.get("allowlistCount") != 10
        or type(report.get("allowlistCount")) is not int
        or report.get("host") != host
        or report.get("port") != port
        or type(report.get("port")) is not int
        or report.get("applyRequested") is not True
        or report.get("transactionComplete") is not True
        or report.get("applied") is not True
        or report.get("failure") is not None
        or not isinstance(report.get("manifest"), Mapping)
        or report["manifest"].get("sha256") != manifest_sha256
    ):
        raise VerifyError("The explicit replacement cleanup report is not complete.")
    candidates = report.get("candidates")
    if not isinstance(candidates, list) or len(candidates) != 10:
        raise VerifyError(
            "The explicit replacement cleanup report has invalid candidates."
        )
    reported_paths: set[str] = set()
    for row in candidates:
        if not isinstance(row, dict) or row.get("status") not in {
            "deleted",
            "already-absent",
        }:
            raise VerifyError(
                "An explicit replacement was not safely removed or absent."
            )
        candidate = row.get("candidate")
        if not isinstance(candidate, dict) or not isinstance(
            candidate.get("path"), str
        ):
            raise VerifyError("An explicit replacement report row is invalid.")
        path = str(candidate["path"])
        expected = allowlisted.get(path)
        if (
            expected is None
            or candidate.get("candidate_id") != expected.candidate_id
            or candidate.get("size") != expected.size
            or type(candidate.get("size")) is not int
            or candidate.get("sha256") != expected.sha256
        ):
            raise VerifyError(
                "An explicit cleanup report identity differs from its allowlist."
            )
        reported_paths.add(path)
    exact_set("Explicit cleanup allowlist", reported_paths, allowlisted)


def local_expectations(
    sync: ModuleType,
    manifest_path: Path,
    lingua_root: Path,
    lazyearn_root: Path,
    lazytravel_root: Path,
    generated_note: Path,
) -> tuple[
    dict[str, ExpectedFile],
    dict[str, ExpectedFile],
    dict[str, ExpectedFile],
    dict[str, ExpectedFile],
    set[str],
    str,
]:
    manifest = load_json(manifest_path, "Canonical manifest")
    rows = manifest.get("rows")
    summary = manifest.get("summary")
    if (
        manifest.get("schema_version") != 2
        or type(manifest.get("schema_version")) is not int
        or not isinstance(rows, list)
        or len(rows) != 572
        or not isinstance(summary, Mapping)
        or summary.get("logical_book_count") != 286
        or type(summary.get("logical_book_count")) is not int
        or summary.get("pdf_count") != 572
        or type(summary.get("pdf_count")) is not int
        or not strict_int(summary.get("bytes"))
        or summary.get("bytes", 0) <= 0
        or summary.get("by_mode") != {"blackwhite": 286, "color": 286}
    ):
        raise VerifyError("Canonical manifest schema or totals are invalid.")
    black_rows: list[Mapping[str, Any]] = []
    color_book_ids: set[str] = set()
    black_book_ids: set[str] = set()
    all_destinations: set[str] = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != MANIFEST_ROW_KEYS:
            raise VerifyError("A canonical manifest row has an unexpected schema.")
        if any(
            not isinstance(row[field], str) for field in MANIFEST_ROW_KEYS - {"bytes"}
        ) or not strict_int(row["bytes"]):
            raise VerifyError(
                "A canonical manifest row contains an invalid typed field."
            )
        if row["mode"] not in {"blackwhite", "color"}:
            raise VerifyError("A canonical manifest row has an invalid mode.")
        try:
            destination = sync.safe_relative(row["destination"])
            category = sync.safe_relative(row["category"])
            book_id = sync.safe_relative(row["book_id"])
        except RuntimeError as error:
            raise VerifyError("A canonical manifest path is invalid.") from error
        if (
            not destination.startswith(f"{row['mode']}/")
            or PurePosixPath(destination).parent.as_posix()
            != f"{row['mode']}/{category}"
            or row["bytes"] <= 0
            or not HEX_SHA256.fullmatch(row["sha256"])
        ):
            raise VerifyError("A canonical manifest identity is invalid.")
        folded = destination.casefold()
        if folded in all_destinations:
            raise VerifyError("Canonical manifest repeats a destination.")
        all_destinations.add(folded)
        ids = black_book_ids if row["mode"] == "blackwhite" else color_book_ids
        if book_id in ids:
            raise VerifyError("Canonical manifest repeats a book ID within one mode.")
        ids.add(book_id)
        if row["mode"] == "blackwhite":
            black_rows.append(row)
    if len(black_rows) != 286:
        raise VerifyError(
            "Canonical manifest does not contain 286 black-and-white rows."
        )
    if black_book_ids != color_book_ids or len(color_book_ids) != 286:
        raise VerifyError("Canonical manifest black-and-white/color book IDs differ.")
    canonical: dict[str, ExpectedFile] = {}
    canonical_by_book_id: dict[str, str] = {}
    categories: set[str] = set()
    for row in black_rows:
        destination = row["destination"]
        category = row["category"]
        size = row["bytes"]
        digest = row["sha256"]
        path = f"{sync.REMOTE_DOCUMENTS}/LinguaLeaf/{destination}"
        if path in canonical:
            raise VerifyError("Canonical manifest repeats a destination.")
        canonical[path] = ExpectedFile(path, size, digest, "canonical-pdf")
        canonical_by_book_id[row["book_id"]] = path
        categories.add(category)
    top_categories = {PurePosixPath(category).parts[0] for category in categories}
    if len(categories) != 29 or top_categories != sync.EXPECTED_TOP_CATEGORIES:
        raise VerifyError("Canonical manifest does not contain 29 leaf categories.")

    roots = {"LazyEarn": lazyearn_root, "LazyTravel": lazytravel_root}
    standalone: dict[str, ExpectedFile] = {}
    for collection, filename in sync.STANDALONE_FILES:
        source = roots[collection] / filename
        size, digest = sync.hash_local_stable(source, expect_pdf=True)
        path = f"{sync.REMOTE_DOCUMENTS}/{collection}/{filename}"
        if path in standalone:
            raise VerifyError("The standalone request repeats a destination.")
        standalone[path] = ExpectedFile(path, size, digest, "standalone-pdf")
    if len(standalone) != 5:
        raise VerifyError(
            "The standalone request does not resolve to five unique PDFs."
        )
    retained: dict[str, ExpectedFile] = {}
    for collection, filename in RETAINED_STANDALONE_FILES:
        source = roots[collection] / filename
        size, digest = sync.hash_local_stable(source, expect_pdf=True)
        path = f"{sync.REMOTE_DOCUMENTS}/{collection}/{filename}"
        retained[path] = ExpectedFile(path, size, digest, "retained-standalone-pdf")

    notes: dict[str, ExpectedFile] = {}
    sources: list[tuple[Path, str]] = [
        (lingua_root / name, f"{sync.REMOTE_NOTES_ROOT}/{name}")
        for name in sync.ROOT_NOTES
    ]
    sources.extend(
        (
            lingua_root.joinpath(
                "blackwhite", *PurePosixPath(category).parts, "README.md"
            ),
            f"{sync.REMOTE_NOTES_ROOT}/blackwhite/{category}/README.md",
        )
        for category in sorted(categories, key=str.casefold)
    )
    sources.append((generated_note, f"{sync.REMOTE_NOTES_ROOT}/SYNC-2026-08-29.md"))
    for index, (source, path) in enumerate(sources):
        size, digest = sync.hash_local_stable(source, expect_pdf=False)
        if path in notes:
            raise VerifyError("The notes request repeats a destination.")
        kind = "generated-note" if index == len(sources) - 1 else "note"
        notes[path] = ExpectedFile(path, size, digest, kind)
    if len(notes) != NOTE_COUNT:
        raise VerifyError("The notes request does not resolve to 35 unique files.")
    _manifest_size, manifest_digest = sync.hash_local_stable(
        manifest_path, expect_pdf=False
    )
    if not EXPECTED_CANONICAL_SIDECAR_BOOK_IDS.issubset(canonical_by_book_id):
        raise VerifyError(
            "An audited canonical sidecar book ID is absent from the manifest."
        )
    expected_sidecars = {
        str(PurePosixPath(canonical_by_book_id[book_id]).with_suffix(".sdr"))
        for book_id in EXPECTED_CANONICAL_SIDECAR_BOOK_IDS
    }
    if len(expected_sidecars) != CANONICAL_SIDECAR_COUNT:
        raise VerifyError("Audited canonical sidecar identities are not exactly eight.")
    return canonical, standalone, notes, retained, expected_sidecars, manifest_digest


def inventory_tree(connection: Any, root: str) -> TreeInventory:
    connection.require_directory(root, connection.lstat(root))
    files: set[str] = set()
    pdfs: set[str] = set()
    sidecars: set[str] = set()
    file_sizes: dict[str, int] = {}

    def walk(directory: str) -> None:
        try:
            entries = connection.sftp.listdir_attr(directory)
        except OSError as error:
            raise VerifyError(
                f"Could not inventory managed Kindle tree: {root}"
            ) from error
        for entry in entries:
            name = entry.filename
            child = posixpath.join(directory, name)
            if stat.S_ISLNK(entry.st_mode):
                raise VerifyError(f"Managed Kindle tree contains a symlink: {child}")
            if stat.S_ISDIR(entry.st_mode):
                if name.casefold().endswith(".sdr"):
                    sidecars.add(child)
                else:
                    walk(child)
            elif stat.S_ISREG(entry.st_mode):
                files.add(child)
                file_sizes[child] = int(entry.st_size)
                if name.casefold().endswith(".pdf"):
                    pdfs.add(child)
            else:
                raise VerifyError(
                    f"Managed Kindle tree contains a special file: {child}"
                )

    walk(root)
    return TreeInventory(
        frozenset(files), frozenset(pdfs), frozenset(sidecars), file_sizes
    )


def verify_expected_files(
    connection: Any,
    expected: Mapping[str, ExpectedFile],
    *,
    hashes: bool,
    progress_label: str,
) -> int:
    for index, item in enumerate(expected.values(), start=1):
        state = connection.require_regular(item.path, connection.lstat(item.path))
        if int(state.st_size) != item.size:
            raise VerifyError(f"Remote size differs for {item.path}")
        if (
            hashes
            and connection.sha256_file(item.path, expected_size=item.size)
            != item.sha256
        ):
            raise VerifyError(f"Remote SHA-256 differs for {item.path}")
        if hashes and (index % 25 == 0 or index == len(expected)):
            print(
                f"Verified {progress_label} hashes: {index}/{len(expected)}",
                file=sys.stderr,
            )
    return len(expected) if hashes else 0


def verify_standalone_inventory(
    connection: Any,
    requested: Mapping[str, ExpectedFile],
    retained: Mapping[str, ExpectedFile],
) -> tuple[dict[str, TreeInventory], int]:
    expected_all = {**requested, **retained}
    roots = {
        "/mnt/us/documents/LazyEarn",
        "/mnt/us/documents/LazyTravel",
    }
    inventories: dict[str, TreeInventory] = {}
    duplicate_hash_checks = 0
    for root in roots:
        inventory = inventory_tree(connection, root)
        inventories[root] = inventory
        expected_for_root = {
            path: item
            for path, item in expected_all.items()
            if posixpath.dirname(path) == root
        }
        exact_set(f"{root} PDF inventory", inventory.pdfs, expected_for_root)
        exact_set(f"{root} regular-file inventory", inventory.files, expected_for_root)
        expected_sidecars = (
            {
                str(PurePosixPath(path).with_suffix(".sdr"))
                for path in retained
                if posixpath.dirname(path) == root
            }
            if root.endswith("/LazyEarn")
            else set()
        )
        exact_set(f"{root} sidecar inventory", inventory.sidecars, expected_sidecars)

        # The exact-set gates above reject extras.  This second identity gate
        # makes a future relaxation unable to admit a renamed content duplicate.
        seen: set[tuple[int, str]] = set()
        for path in inventory.pdfs:
            item = expected_all[path]
            identity = (item.size, item.sha256)
            if identity in seen:
                raise VerifyError("Standalone inventory contains a content duplicate.")
            seen.add(identity)
            duplicate_hash_checks += 1
    return inventories, duplicate_hash_checks


def scan_owned_temporaries(connection: Any) -> set[str]:
    found: set[str] = set()

    def walk(directory: str) -> None:
        try:
            entries = connection.sftp.listdir_attr(directory)
        except OSError as error:
            raise VerifyError(
                "Could not scan for owned synchronization temporaries."
            ) from error
        for entry in entries:
            name = entry.filename
            child = posixpath.join(directory, name)
            if ".canonical-sync-" in name:
                found.add(child)
            if (
                stat.S_ISDIR(entry.st_mode)
                and not stat.S_ISLNK(entry.st_mode)
                and not name.casefold().endswith(".sdr")
            ):
                walk(child)

    walk("/mnt/us/documents")
    for entry in connection.sftp.listdir_attr("/mnt/us/koreader"):
        if ".canonical-sync-" in entry.filename:
            found.add(posixpath.join("/mnt/us/koreader", entry.filename))
    return found


def marker_kind(connection: Any, path: str) -> str:
    state = connection.lstat(path)
    if state is None:
        return "absent"
    if stat.S_ISLNK(state.st_mode):
        return "symlink"
    if stat.S_ISREG(state.st_mode):
        return "regular"
    return "other"


def validate_operational_state(state: Mapping[str, Any], expected: str) -> None:
    wanted = {
        "guarded": {
            "readerRunning": False,
            "preventScreenSaver": 1,
            "temporaryDisableMarker": "regular",
            "standardAutostartMarker": "absent",
            "originalAutostartMarker": "absent",
            "emergencyMarker": "absent",
        },
        "restored": {
            "readerRunning": False,
            "preventScreenSaver": 0,
            "temporaryDisableMarker": "absent",
            "standardAutostartMarker": "absent",
            "originalAutostartMarker": "regular",
            "emergencyMarker": "absent",
        },
    }[expected]
    for key, value in wanted.items():
        if state.get(key) != value:
            raise VerifyError(
                f"Kindle {key} is {state.get(key)!r}; expected {value!r} for {expected} state."
            )


def write_json_atomic(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{time.time_ns()}.tmp")
    try:
        temporary.write_text(
            json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        temporary.replace(path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()


def run(args: argparse.Namespace) -> int:
    sync = load_sibling(SYNC_SCRIPT, "kindle_canonical_sync_for_verification")
    cleanup = load_sibling(CLEANUP_SCRIPT, "kindle_cleanup_for_verification")
    if not 1 <= args.port <= 65535:
        raise VerifyError("SSH port is invalid.")
    allowlisted = {candidate.path: candidate for candidate in cleanup.LEGACY_CANDIDATES}
    if len(allowlisted) != 10:
        raise VerifyError("Local explicit cleanup allowlist is not exactly ten paths.")

    canonical: dict[str, ExpectedFile] = {}
    standalone: dict[str, ExpectedFile] = {}
    notes: dict[str, ExpectedFile] = {}
    retained: dict[str, ExpectedFile] = {}
    legacy: dict[str, ExpectedFile] = {}
    reported_canonical_sidecars: set[str] = set()
    expected_canonical_sidecars: set[str] = set()
    if not args.state_only:
        (
            canonical,
            standalone,
            notes,
            retained,
            expected_canonical_sidecars,
            manifest_digest,
        ) = local_expectations(
            sync,
            args.manifest,
            args.lingualleaf_root,
            args.lazyearn_root,
            args.lazytravel_root,
            args.sync_report.parent / "SYNC-2026-08-29.md",
        )
        expected_report_items = {
            **canonical,
            **standalone,
            **{path: item for path, item in notes.items() if item.kind == "note"},
        }
        sync_report = load_json(args.sync_report, "Canonical sync report")
        cleanup_report = load_json(args.cleanup_report, "Explicit cleanup report")
        legacy, reported_canonical_sidecars = validate_sync_report(
            sync_report,
            host=args.host,
            port=args.port,
            manifest_sha256=manifest_digest,
            expected_items=expected_report_items,
        )
        validate_cleanup_report(
            cleanup_report,
            allowlisted,
            host=args.host,
            port=args.port,
            manifest_sha256=manifest_digest,
        )

    with sync.KindleConnection(
        args.host, args.port, args.key, args.known_hosts
    ) as connection:
        operational = {
            "readerRunning": connection.koreader_running(),
            "preventScreenSaver": connection.prevent_screen_saver(),
            "temporaryDisableMarker": marker_kind(
                connection, "/mnt/us/DISABLE_KOREADER_AUTOSTART"
            ),
            "standardAutostartMarker": marker_kind(
                connection, "/mnt/us/_DISABLE_KOREADER_AUTOSTART"
            ),
            "originalAutostartMarker": marker_kind(
                connection, "/mnt/us/_DISABLE_KOREADER_AUTOSTART_FRAMEWORK_STOP"
            ),
            "emergencyMarker": marker_kind(connection, "/mnt/us/emergency.sh"),
        }
        validate_operational_state(operational, args.expected_state)
        available = connection.available_bytes()
        if available < sync.SAFETY_FREE_BYTES:
            raise VerifyError("Kindle has less than the 64 MiB safety reserve free.")
        temporaries = scan_owned_temporaries(connection)
        if temporaries:
            raise VerifyError(
                f"Owned synchronization temporary remains: {min(temporaries)}"
            )

        hashes_verified = 0
        canonical_sidecars = 0
        legacy_pairs = 0
        if not args.state_only:
            canonical_tree = inventory_tree(
                connection, f"{sync.REMOTE_DOCUMENTS}/LinguaLeaf/blackwhite"
            )
            exact_set("Canonical PDF inventory", canonical_tree.pdfs, canonical)
            exact_set(
                "Canonical regular-file inventory", canonical_tree.files, canonical
            )
            if not reported_canonical_sidecars.issubset(expected_canonical_sidecars):
                raise VerifyError(
                    "The sync report records an unaudited canonical sidecar."
                )
            for sidecar in expected_canonical_sidecars:
                if str(PurePosixPath(sidecar).with_suffix(".pdf")) not in canonical:
                    raise VerifyError(
                        "An expected canonical sidecar has no canonical PDF."
                    )
            exact_set(
                "Canonical sidecar inventory",
                canonical_tree.sidecars,
                expected_canonical_sidecars,
            )
            canonical_sidecars = len(canonical_tree.sidecars)

            hashes_verified += verify_expected_files(
                connection,
                canonical,
                hashes=not args.skip_full_hashes,
                progress_label="canonical PDF",
            )
            hashes_verified += verify_expected_files(
                connection,
                standalone,
                hashes=not args.skip_full_hashes,
                progress_label="standalone PDF",
            )
            _standalone_inventories, _duplicate_checks = verify_standalone_inventory(
                connection, standalone, retained
            )
            hashes_verified += verify_expected_files(
                connection,
                retained,
                hashes=not args.skip_full_hashes,
                progress_label="retained standalone PDF",
            )

            notes_tree = inventory_tree(connection, sync.REMOTE_NOTES_ROOT)
            exact_set("Notes file inventory", notes_tree.files, notes)
            if notes_tree.sidecars:
                raise VerifyError(
                    "The notes shelf unexpectedly contains a .sdr directory."
                )
            hashes_verified += verify_expected_files(
                connection,
                notes,
                hashes=not args.skip_full_hashes,
                progress_label="note",
            )

            lingua_legacy = inventory_tree(connection, sync.REMOTE_LEGACY_ROOT)
            travel_legacy_root = (
                f"{sync.REMOTE_DOCUMENTS}/LazyTravel-Legacy-with-reading-state"
            )
            travel_legacy = inventory_tree(connection, travel_legacy_root)
            if (
                len(lingua_legacy.pdfs) != LINGUA_LEGACY_PAIR_COUNT
                or len(travel_legacy.pdfs) != LAZYTRAVEL_LEGACY_PAIR_COUNT
            ):
                raise VerifyError("Legacy shelf PDF counts are not 16 + 1.")
            actual_legacy = set(lingua_legacy.pdfs) | set(travel_legacy.pdfs)
            exact_set("Legacy PDF inventory", actual_legacy, legacy)
            exact_set(
                "LinguaLeaf legacy regular-file inventory",
                lingua_legacy.files,
                lingua_legacy.pdfs,
            )
            exact_set(
                "LazyTravel legacy regular-file inventory",
                travel_legacy.files,
                travel_legacy.pdfs,
            )
            actual_legacy_sidecars = set(lingua_legacy.sidecars) | set(
                travel_legacy.sidecars
            )
            expected_legacy_sidecars = {
                str(PurePosixPath(path).with_suffix(".sdr")) for path in legacy
            }
            exact_set(
                "Legacy sidecar inventory",
                actual_legacy_sidecars,
                expected_legacy_sidecars,
            )
            legacy_pairs = len(actual_legacy)
            hashes_verified += verify_expected_files(
                connection,
                legacy,
                hashes=not args.skip_full_hashes,
                progress_label="legacy PDF",
            )

            for path in allowlisted:
                if connection.lstat(path) is not None:
                    raise VerifyError(
                        f"Explicit superseded PDF remains after cleanup: {path}"
                    )
                sidecar = str(PurePosixPath(path).with_suffix(".sdr"))
                if connection.lstat(sidecar) is not None:
                    raise VerifyError(
                        f"Explicit superseded PDF sidecar remains after cleanup: {sidecar}"
                    )

        result = {
            "schemaVersion": 1,
            "status": "pass",
            "verifiedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "host": args.host,
            "port": args.port,
            "mode": "state-only" if args.state_only else "full",
            "fullHashesSkipped": bool(args.skip_full_hashes or args.state_only),
            "canonicalPdfs": len(canonical),
            "standalonePdfs": len(standalone),
            "retainedStandalonePdfs": len(retained),
            "notes": len(notes),
            "canonicalSidecars": canonical_sidecars,
            "legacyPdfSidecarPairs": legacy_pairs,
            "explicitOldCandidatesAbsent": 0 if args.state_only else len(allowlisted),
            "hashesVerified": hashes_verified,
            "ownedTemporaries": 0,
            "availableBytes": available,
            "expectedOperationalState": args.expected_state,
            "operationalState": operational,
            "linguaLeafScope": (
                "Exact inventory applies to LinguaLeaf/blackwhite only; "
                "unreviewed old-layout siblings are conservatively retained, "
                "apart from the ten explicitly reviewed replacements."
            ),
        }
    write_json_atomic(args.report, result)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def build_parser() -> argparse.ArgumentParser:
    sync = load_sibling(SYNC_SCRIPT, "kindle_canonical_sync_for_parser")
    parser = argparse.ArgumentParser(
        description="Strict read-only post-sync verifier for the canonical PW5SE library."
    )
    parser.add_argument("--host", default=sync.HOST_DEFAULT)
    parser.add_argument("--port", type=int, default=sync.PORT_DEFAULT)
    parser.add_argument("--key", type=Path, default=sync.DEFAULT_KEY)
    parser.add_argument("--known-hosts", type=Path, default=sync.DEFAULT_KNOWN_HOSTS)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=sync.DEFAULT_LINGUA_ROOT / "CANONICAL-LIBRARY.json",
    )
    parser.add_argument(
        "--lingualleaf-root", type=Path, default=sync.DEFAULT_LINGUA_ROOT
    )
    parser.add_argument(
        "--lazyearn-root", type=Path, default=sync.DEFAULT_LAZYEARN_ROOT
    )
    parser.add_argument(
        "--lazytravel-root", type=Path, default=sync.DEFAULT_LAZYTRAVEL_ROOT
    )
    parser.add_argument("--sync-report", type=Path, default=DEFAULT_SYNC_REPORT)
    parser.add_argument("--cleanup-report", type=Path, default=DEFAULT_CLEANUP_REPORT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument(
        "--expected-state",
        choices=("guarded", "restored"),
        default="restored",
        help="assert temporary keep-awake guards or the final restored state",
    )
    parser.add_argument(
        "--skip-full-hashes",
        action="store_true",
        help="still verify exact paths and sizes, but skip remote SHA-256 (for a second state check)",
    )
    parser.add_argument(
        "--state-only",
        action="store_true",
        help="only verify power/autostart/reader state, free space, and absence of owned temps",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        return run(build_parser().parse_args(argv))
    except (VerifyError, RuntimeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
