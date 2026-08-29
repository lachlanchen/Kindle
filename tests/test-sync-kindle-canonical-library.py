import hashlib
import importlib.util
import json
import os
import shutil
import stat
import sys
import tempfile
import unittest
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
from unittest import mock

SCRIPT = (
    Path(__file__).resolve().parents[1] / "scripts" / "sync-kindle-canonical-library.py"
)
SPEC = importlib.util.spec_from_file_location("sync_kindle_canonical_library", SCRIPT)
assert SPEC and SPEC.loader
SYNC = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = SYNC
SPEC.loader.exec_module(SYNC)


def pdf_bytes(label="fixture"):
    return b"%PDF-1.4\n" + label.encode("utf-8") + b"\n%%EOF\n"


def write_file(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def local_item(
    source,
    destination="LinguaLeaf/blackwhite/01-Chinese-Classics/01-Test/\u53f2\u8a18.pdf",
    *,
    kind="canonical-pdf",
    book_id="shiji-sanjiazhu",
):
    source = Path(source)
    payload = source.read_bytes()
    return SYNC.LocalItem(
        kind=kind,
        source=source,
        destination=destination,
        size=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
        book_id=book_id,
    )


class LocalSftp:
    """Local-filesystem SFTP double; it never opens a network connection."""

    def __init__(self, root):
        self.root = Path(root)
        self.puts = []
        self.opens = []
        self.renames = []
        self.removes = []
        self.fail_remove = set()

    def local(self, remote):
        path = PurePosixPath(remote)
        if not path.is_absolute() or ".." in path.parts:
            raise AssertionError(f"unsafe fixture path: {remote}")
        return self.root.joinpath(*path.parts[1:])

    def lstat(self, remote):
        return os.lstat(self.local(remote))

    def stat(self, remote):
        return os.stat(self.local(remote))

    def listdir_attr(self, remote):
        result = []
        for child in self.local(remote).iterdir():
            state = os.lstat(child)
            result.append(
                SimpleNamespace(
                    filename=child.name,
                    st_mode=state.st_mode,
                    st_size=state.st_size,
                    st_mtime=int(state.st_mtime),
                )
            )
        return result

    def open(self, remote, mode):
        self.opens.append((remote, mode))
        return self.local(remote).open(mode)

    def chmod(self, remote, mode):
        os.chmod(self.local(remote), mode)

    def mkdir(self, remote):
        self.local(remote).mkdir()

    def rename(self, source, destination):
        self.renames.append((source, destination))
        self.local(source).rename(self.local(destination))

    def posix_rename(self, source, destination):
        self.renames.append((source, destination))
        os.replace(self.local(source), self.local(destination))

    def remove(self, remote):
        self.removes.append(remote)
        if remote in self.fail_remove:
            raise OSError("injected remove failure")
        self.local(remote).unlink()

    def rmdir(self, remote):
        self.local(remote).rmdir()

    def put(self, source, destination, confirm=True):
        self.puts.append((str(source), destination, confirm))
        shutil.copyfile(source, self.local(destination))
        return self.stat(destination)

    def readlink(self, remote):
        return os.readlink(self.local(remote))


class LocalConnection:
    def __init__(self, root):
        self.sftp = LocalSftp(root)
        self.sftp.local(SYNC.REMOTE_DOCUMENTS).mkdir(parents=True)
        self._hash_cache = {}
        self.open_handles = set()

    def lstat(self, remote):
        try:
            return self.sftp.lstat(remote)
        except FileNotFoundError:
            return None

    require_regular = staticmethod(SYNC.KindleConnection.require_regular)
    require_directory = staticmethod(SYNC.KindleConnection.require_directory)

    def inventory_pdfs(self, root):
        return SYNC.KindleConnection.inventory_pdfs(self, root)

    def inventory_sidecar_pdfs(self, root):
        return SYNC.KindleConnection.inventory_sidecar_pdfs(self, root)

    def sha256_file(self, remote, expected_size=None):
        state = self.require_regular(remote, self.lstat(remote))
        if expected_size is not None and state.st_size != expected_size:
            raise SYNC.SyncError("wrong fixture size")
        digest = hashlib.sha256(self.sftp.local(remote).read_bytes()).hexdigest()
        return digest

    def forget_hash(self, *paths):
        for path in paths:
            self._hash_cache.pop(path, None)

    def transfer_cached_hash(self, source, destination):
        self.forget_hash(source, destination)

    def read_regular_bytes(self, path, maximum):
        state_before = self.require_regular(path, self.lstat(path))
        if state_before.st_size > maximum:
            raise SYNC.SyncError("fixture metadata is too large")
        payload = self.sftp.local(path).read_bytes()
        return payload, stat.S_IMODE(state_before.st_mode)

    def mkdirs(self, remote):
        normalized = PurePosixPath(remote)
        if not normalized.is_absolute() or ".." in normalized.parts:
            raise SYNC.SyncError("unsafe fixture mkdir")
        current = PurePosixPath(SYNC.REMOTE_DOCUMENTS)
        relative = normalized.relative_to(current)
        for part in relative.parts:
            current /= part
            existing = self.lstat(current.as_posix())
            if existing is None:
                self.sftp.mkdir(current.as_posix())
            else:
                self.require_directory(current.as_posix(), existing)

    def has_open_file_handle(self, path):
        return path in self.open_handles

    @staticmethod
    def assert_koreader_stopped():
        return None


class ManifestTests(unittest.TestCase):
    def test_manifest_backed_canonical_discovery_does_not_full_hash_source(self):
        with tempfile.TemporaryDirectory() as directory:
            source = write_file(
                Path(directory) / "canonical.pdf", pdf_bytes("cold-cloud-file")
            )
            expected = "d" * 64
            with (
                mock.patch.object(
                    SYNC, "validate_local_metadata", return_value=source.stat().st_size
                ) as metadata,
                mock.patch.object(
                    SYNC,
                    "hash_local_stable",
                    side_effect=AssertionError(
                        "canonical source was hydrated/full-hashed"
                    ),
                ),
            ):
                item = SYNC._source_item(
                    kind="canonical-pdf",
                    source=source,
                    destination="LinguaLeaf/blackwhite/01-Chinese-Classics/01-Test/book.pdf",
                    expect_pdf=True,
                    expected_size=source.stat().st_size,
                    expected_sha256=expected,
                    book_id="book",
                    trust_manifest_hash=True,
                )
            metadata.assert_called_once()
            self.assertEqual(item.sha256, expected)

    def test_malformed_row_is_reported_as_sync_error(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lingua = root / "LinguaLeaf"
            lingua.mkdir()
            (lingua / "CANONICAL-LIBRARY.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "rows": ["not-an-object"],
                        "replacements": [],
                        "summary": {"by_mode": {"blackwhite": 0}},
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(SYNC.SyncError):
                SYNC.discover_sources(lingua, root / "LazyEarn", root / "LazyTravel")

    def test_truncated_manifest_cannot_self_authorize_a_smaller_library(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lingua = root / "LinguaLeaf"
            earn = root / "LazyEarn"
            travel = root / "LazyTravel"
            rows = []
            for index, top in enumerate(sorted(SYNC.EXPECTED_TOP_CATEGORIES)):
                category = f"{top}/01-Fixture"
                filename = f"Book-{index}.pdf"
                payload = pdf_bytes(filename)
                source = write_file(
                    lingua / "blackwhite" / category / filename, payload
                )
                write_file(source.parent / "README.md", b"fixture\n")
                rows.append(
                    {
                        "book_id": f"book-{index}",
                        "category": category,
                        "mode": "blackwhite",
                        "destination": f"blackwhite/{category}/{filename}",
                        "bytes": len(payload),
                        "sha256": hashlib.sha256(payload).hexdigest(),
                    }
                )
            manifest = {
                "schema_version": 1,
                "rows": rows,
                "replacements": [],
                "summary": {"by_mode": {"blackwhite": len(rows)}},
            }
            lingua.mkdir(exist_ok=True)
            (lingua / "CANONICAL-LIBRARY.json").write_text(
                json.dumps(manifest), encoding="utf-8"
            )
            for filename in SYNC.ROOT_NOTES:
                if filename != "CANONICAL-LIBRARY.json":
                    write_file(lingua / filename, b"fixture note\n")
            for collection, filename in SYNC.STANDALONE_FILES:
                parent = earn if collection == "LazyEarn" else travel
                write_file(parent / filename, pdf_bytes(filename))
            with self.assertRaises(SYNC.SyncError):
                SYNC.discover_sources(lingua, earn, travel)

    def test_unicode_and_traversal_path_rules(self):
        self.assertEqual(
            SYNC.sidecar_for_pdf(
                "/mnt/us/documents/LinguaLeaf/blackwhite/\u53f2\u8a18\uff08\u6ce8\uff09\uff5c\u65e5\u672c\u8a9e.pdf"
            ),
            "/mnt/us/documents/LinguaLeaf/blackwhite/\u53f2\u8a18\uff08\u6ce8\uff09\uff5c\u65e5\u672c\u8a9e.sdr",
        )
        for value in ("../escape.pdf", "/absolute.pdf", "a\\b.pdf", "a/\x01b.pdf"):
            with self.subTest(value=value), self.assertRaises(SYNC.SyncError):
                SYNC.safe_relative(value)


class PlanningTests(unittest.TestCase):
    def test_exact_pdf_moves_with_adjacent_same_stem_sidecar(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = write_file(
                root / "local" / "\u53f2\u8a18.pdf", pdf_bytes("\u53f2\u8a18")
            )
            item = local_item(source)
            connection = LocalConnection(root / "remote")
            old_pdf = (
                "/mnt/us/documents/LinguaLeaf/en-jp-zh-blackwhite/\u53f2\u8a18.pdf"
            )
            write_file(connection.sftp.local(old_pdf), source.read_bytes())
            connection.sftp.local(SYNC.sidecar_for_pdf(old_pdf)).mkdir()

            actions, _inventory, conflicts = SYNC.plan_sync([item], connection)

            self.assertEqual(conflicts, [])
            self.assertEqual(len(actions), 1)
            action = actions[0]
            self.assertEqual(action.action, "move")
            self.assertEqual(action.sidecar_source, old_pdf[:-4] + ".sdr")
            self.assertEqual(
                action.sidecar_destination,
                "/mnt/us/documents/" + item.destination[:-4] + ".sdr",
            )
            self.assertNotIn(".pdf.sdr", action.sidecar_destination)

    def test_existing_destination_sidecar_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = write_file(root / "local" / "book.pdf", pdf_bytes("same"))
            item = local_item(source)
            connection = LocalConnection(root / "remote")
            old_pdf = "/mnt/us/documents/LinguaLeaf/old/book.pdf"
            target_pdf = SYNC.remote_from_relative(item.destination)
            write_file(connection.sftp.local(old_pdf), source.read_bytes())
            connection.sftp.local(SYNC.sidecar_for_pdf(old_pdf)).mkdir()
            connection.sftp.local(SYNC.sidecar_for_pdf(target_pdf)).mkdir(parents=True)

            actions, _inventory, conflicts = SYNC.plan_sync([item], connection)

            self.assertEqual(actions[0].action, "upload")
            self.assertTrue(conflicts)
            self.assertTrue(
                connection.sftp.local(SYNC.sidecar_for_pdf(old_pdf)).is_dir()
            )
            self.assertTrue(
                connection.sftp.local(SYNC.sidecar_for_pdf(target_pdf)).is_dir()
            )

    def test_symlink_in_managed_inventory_is_rejected(self):
        class SyntheticSftp:
            @staticmethod
            def listdir_attr(_remote):
                return [
                    SimpleNamespace(
                        filename="escape",
                        st_mode=stat.S_IFLNK | 0o777,
                        st_size=0,
                        st_mtime=0,
                    )
                ]

        connection = SimpleNamespace()
        connection.sftp = SyntheticSftp()
        connection.lstat = lambda _path: SimpleNamespace(st_mode=stat.S_IFDIR | 0o755)
        connection.require_directory = SYNC.KindleConnection.require_directory
        with self.assertRaises(SYNC.SyncError):
            SYNC.KindleConnection.inventory_pdfs(
                connection, "/mnt/us/documents/LinguaLeaf"
            )

    def test_mismatched_standalone_with_sidecar_is_preserved_or_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = write_file(root / "local" / "Xian.pdf", pdf_bytes("new-edition"))
            item = local_item(
                source,
                destination="LazyTravel/LazyTravel-Xian-ZH-JA-EN-B6-Pocket.pdf",
                kind="standalone-pdf",
                book_id=None,
            )
            connection = LocalConnection(root / "remote")
            target = SYNC.remote_from_relative(item.destination)
            write_file(connection.sftp.local(target), pdf_bytes("old-edition"))
            connection.sftp.local(SYNC.sidecar_for_pdf(target)).mkdir()

            try:
                actions, _inventory, _conflicts = SYNC.plan_sync([item], connection)
            except SYNC.SyncError:
                return  # A fail-closed refusal is safe.

            uploads = [action for action in actions if action.action == "upload"]
            preserved = [
                action
                for action in actions
                if action.action == "legacy-move"
                and action.source_remote == target
                and action.sidecar_source == SYNC.sidecar_for_pdf(target)
            ]
            self.assertEqual(len(uploads), 1)
            self.assertEqual(
                len(preserved),
                1,
                "mismatched standalone upload would retain an incompatible old .sdr",
            )


class MutationTests(unittest.TestCase):
    def test_upload_uses_verified_owned_part_then_atomic_publish(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = write_file(root / "local" / "\u672c.pdf", pdf_bytes("atomic"))
            item = local_item(source)
            action = SYNC.SyncAction(
                action="upload",
                kind=item.kind,
                destination=SYNC.remote_from_relative(item.destination),
                size=item.size,
                sha256=item.sha256,
                source_local=str(item.source),
            )
            connection = LocalConnection(root / "remote")

            SYNC.upload_atomic(connection, action, source, "fixture-run")

            self.assertEqual(
                connection.sftp.local(action.destination).read_bytes(),
                source.read_bytes(),
            )
            temporary = next(
                path
                for path, mode in connection.sftp.opens
                if mode == "wb" and path.endswith(".part")
            )
            self.assertIn(".canonical-sync-fixture-run.part", temporary)
            self.assertIn((temporary, action.destination), connection.sftp.renames)
            self.assertFalse(connection.sftp.local(temporary).exists())
            self.assertFalse(
                any(
                    "canonical-sync-fixture-run.rollback" in str(path)
                    for path in root.rglob("*")
                )
            )

    def test_cleanup_remove_failure_rolls_sidecar_back(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            connection = LocalConnection(root / "remote")
            payload = pdf_bytes("duplicate")
            source_pdf = "/mnt/us/documents/LinguaLeaf/old/duplicate.pdf"
            target_pdf = "/mnt/us/documents/LinguaLeaf/blackwhite/canonical.pdf"
            source_sdr = SYNC.sidecar_for_pdf(source_pdf)
            target_sdr = SYNC.sidecar_for_pdf(target_pdf)
            write_file(connection.sftp.local(source_pdf), payload)
            write_file(connection.sftp.local(target_pdf), payload)
            connection.sftp.local(source_sdr).mkdir()
            write_file(connection.sftp.local(source_sdr) / "metadata.lua", b"history")
            connection.sftp.fail_remove.add(source_pdf)
            action = SYNC.CleanupAction(
                cleanup_kind="exact-duplicate",
                path=source_pdf,
                canonical_target=target_pdf,
                observed_sha256=hashlib.sha256(payload).hexdigest(),
                observed_size=len(payload),
                expected_target_sha256=hashlib.sha256(payload).hexdigest(),
                expected_target_size=len(payload),
                sidecar_source=source_sdr,
                sidecar_destination=target_sdr,
            )

            with self.assertRaises(SYNC.SyncError):
                SYNC.apply_cleanup(connection, action, "cleanup-rollback")

            self.assertTrue(connection.sftp.local(source_pdf).is_file())
            self.assertTrue(connection.sftp.local(source_sdr).is_dir())
            self.assertFalse(connection.sftp.local(target_sdr).exists())

    def test_explicit_replacement_never_transplants_incompatible_sidecar(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = write_file(
                root / "local" / "successor.pdf", pdf_bytes("successor")
            )
            item = local_item(
                source,
                destination="LinguaLeaf/blackwhite/07-Business/Lean Startup Repaired.pdf",
                book_id="lean-startup-complete-structure-repair",
            )
            connection = LocalConnection(root / "remote")
            target = SYNC.remote_from_relative(item.destination)
            old = "/mnt/us/documents/LinguaLeaf/old/The Lean Startup\uff08old\uff09.pdf"
            write_file(connection.sftp.local(target), source.read_bytes())
            write_file(connection.sftp.local(old), pdf_bytes("old-edition"))
            connection.sftp.local(SYNC.sidecar_for_pdf(old)).mkdir()
            inventory = connection.inventory_pdfs("/mnt/us/documents/LinguaLeaf")
            actions = [
                SYNC.SyncAction(
                    action="reuse",
                    kind=item.kind,
                    destination=target,
                    size=item.size,
                    sha256=item.sha256,
                )
            ]

            cleanup, _conflicts = SYNC.plan_cleanup(
                [item],
                [
                    {
                        "removed": "lean-startup",
                        "kept": "lean-startup-complete-structure-repair",
                    }
                ],
                actions,
                inventory,
                connection,
            )

            self.assertEqual(cleanup, [])
            self.assertTrue(
                any(
                    conflict.get("replacement")
                    == "lean-startup->lean-startup-complete-structure-repair"
                    and "no authoritative old-edition hash"
                    in conflict.get("reason", "")
                    for conflict in _conflicts
                )
            )
            legacy, legacy_conflicts = SYNC.plan_legacy_sidecar_preservation(
                actions, connection
            )
            self.assertEqual(legacy_conflicts, [])
            self.assertEqual(len(legacy), 1)
            self.assertEqual(legacy[0].action, "legacy-move")
            self.assertEqual(legacy[0].source_remote, old)
            self.assertEqual(legacy[0].sidecar_source, SYNC.sidecar_for_pdf(old))
            self.assertTrue(
                legacy[0].destination.startswith(SYNC.REMOTE_LEGACY_ROOT + "/")
            )
            self.assertEqual(
                legacy[0].sidecar_destination,
                SYNC.sidecar_for_pdf(legacy[0].destination),
            )

    def test_unplanned_sidecar_appearance_refuses_pdf_only_move(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            connection = LocalConnection(root / "remote")
            payload = pdf_bytes("late-sidecar")
            source_pdf = "/mnt/us/documents/LinguaLeaf/old/book.pdf"
            target_pdf = "/mnt/us/documents/LinguaLeaf/blackwhite/new/book.pdf"
            write_file(connection.sftp.local(source_pdf), payload)
            # Simulate KOReader state appearing after planning.  The action did
            # not bind a sidecar and must not strand this directory.
            connection.sftp.local(SYNC.sidecar_for_pdf(source_pdf)).mkdir()
            action = SYNC.SyncAction(
                action="move",
                kind="canonical-pdf",
                destination=target_pdf,
                size=len(payload),
                sha256=hashlib.sha256(payload).hexdigest(),
                source_remote=source_pdf,
            )

            with self.assertRaises(SYNC.SyncError):
                SYNC.apply_move(connection, action, "late-sidecar")

            self.assertTrue(connection.sftp.local(source_pdf).is_file())
            self.assertTrue(
                connection.sftp.local(SYNC.sidecar_for_pdf(source_pdf)).is_dir()
            )
            self.assertFalse(connection.sftp.local(target_pdf).exists())

    def test_unplanned_sidecar_appearance_refuses_cleanup_delete(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            connection = LocalConnection(root / "remote")
            payload = pdf_bytes("late-cleanup-sidecar")
            source_pdf = "/mnt/us/documents/LinguaLeaf/old/duplicate.pdf"
            target_pdf = "/mnt/us/documents/LinguaLeaf/blackwhite/new/canonical.pdf"
            write_file(connection.sftp.local(source_pdf), payload)
            write_file(connection.sftp.local(target_pdf), payload)
            connection.sftp.local(SYNC.sidecar_for_pdf(source_pdf)).mkdir()
            digest = hashlib.sha256(payload).hexdigest()
            action = SYNC.CleanupAction(
                cleanup_kind="exact-duplicate",
                path=source_pdf,
                canonical_target=target_pdf,
                observed_sha256=digest,
                observed_size=len(payload),
                expected_target_sha256=digest,
                expected_target_size=len(payload),
            )

            with self.assertRaises(SYNC.SyncError):
                SYNC.apply_cleanup(connection, action, "late-cleanup-sidecar")

            self.assertTrue(connection.sftp.local(source_pdf).is_file())
            self.assertTrue(
                connection.sftp.local(SYNC.sidecar_for_pdf(source_pdf)).is_dir()
            )

    def test_koreader_history_rewrite_uses_verified_temp_and_posix_rename(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            connection = LocalConnection(root / "remote")
            old = "/mnt/us/documents/LinguaLeaf/old/\u53f2\u8a18.pdf"
            new = "/mnt/us/documents/LinguaLeaf/blackwhite/history/\u53f2\u8a18.pdf"
            history = SYNC.KOREADER_PATH_FILES[0]
            original = f'recent = "{old}"\n'.encode("utf-8")
            write_file(connection.sftp.local(history), original)

            rewrites = SYNC.stage_metadata_rewrites(
                connection, old, new, "history-fixture"
            )

            self.assertEqual(len(rewrites), 1)
            rewrite = rewrites[0]
            self.assertEqual(connection.sftp.local(history).read_bytes(), original)
            self.assertEqual(
                connection.sftp.local(rewrite.temporary).read_bytes(),
                original.replace(old.encode("utf-8"), new.encode("utf-8")),
            )
            counts = SYNC.publish_metadata_rewrites(connection, rewrites)
            self.assertEqual(counts, {history: 1})
            self.assertEqual(
                connection.sftp.local(history).read_bytes(),
                original.replace(old.encode("utf-8"), new.encode("utf-8")),
            )
            self.assertFalse(connection.sftp.local(rewrite.temporary).exists())
            self.assertIn((rewrite.temporary, history), connection.sftp.renames)

    def test_history_rewrite_does_not_replace_a_longer_path_prefix(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            connection = LocalConnection(root / "remote")
            old = "/mnt/us/documents/LinguaLeaf/old/book.pdf"
            new = "/mnt/us/documents/LinguaLeaf/blackwhite/new/book.pdf"
            history = SYNC.KOREADER_PATH_FILES[0]
            original = (f'one = "{old}"\ntwo = "{old}.backup"\n').encode("utf-8")
            write_file(connection.sftp.local(history), original)

            rewrites = SYNC.stage_metadata_rewrites(
                connection, old, new, "history-boundary"
            )

            self.assertEqual(len(rewrites), 1)
            self.assertEqual(rewrites[0].replacements, 1)
            expected = original.replace(
                f'"{old}"'.encode("utf-8"), f'"{new}"'.encode("utf-8")
            )
            self.assertEqual(rewrites[0].updated, expected)

    def test_completed_pdf_move_can_finish_interrupted_history_rewrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            connection = LocalConnection(root / "remote")
            old = "/mnt/us/documents/LinguaLeaf/old/book.pdf"
            new = "/mnt/us/documents/LinguaLeaf/blackwhite/new/book.pdf"
            payload = pdf_bytes("already-moved")
            write_file(connection.sftp.local(new), payload)
            history = SYNC.KOREADER_PATH_FILES[0]
            write_file(
                connection.sftp.local(history), f'recent = "{old}"\n'.encode("utf-8")
            )
            action = SYNC.SyncAction(
                action="move",
                kind="canonical-pdf",
                destination=new,
                size=len(payload),
                sha256=hashlib.sha256(payload).hexdigest(),
                source_remote=old,
            )

            result, counts = SYNC.apply_move(connection, action, "resume-history")

            self.assertEqual(result, "already-complete")
            self.assertEqual(counts, {history: 1})
            self.assertIn(
                new.encode("utf-8"), connection.sftp.local(history).read_bytes()
            )

    def test_generated_sync_note_is_uploaded_to_separate_notes_shelf(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            connection = LocalConnection(root / "remote")
            report = root / "host" / "report.json"
            result = SYNC.upload_generated_sync_note(
                connection,
                report_path=report,
                manifest_meta={"sha256": "a" * 64},
                actions=[],
                cleanup=[],
                results=[],
                conflicts=[],
                history_counts={},
                run_id="generated-note",
            )

            self.assertTrue(
                result["destination"].startswith(SYNC.REMOTE_NOTES_ROOT + "/")
            )
            payload = connection.sftp.local(result["destination"]).read_text(
                encoding="utf-8"
            )
            self.assertIn("# Kindle canonical-library sync", payload)
            self.assertIn("LinguaLeaf-Legacy-with-reading-state", payload)
            self.assertIn("a" * 64, payload)


class LedgerAndKeepAwakeTests(unittest.TestCase):
    def test_atomic_json_replace_retries_transient_windows_lock_then_succeeds(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "resume.json"
            path.write_text('{"old": true}\n', encoding="utf-8")
            real_replace = os.replace
            calls = []

            def flaky_replace(source, destination):
                calls.append((Path(source), Path(destination)))
                if len(calls) == 1:
                    raise PermissionError(13, "injected transient destination lock")
                return real_replace(source, destination)

            with (
                mock.patch.object(SYNC.os, "replace", side_effect=flaky_replace),
                mock.patch.object(SYNC.time, "sleep") as sleep,
            ):
                SYNC.write_json_atomic(path, {"new": True})

            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8")), {"new": True}
            )
            self.assertEqual(len(calls), 2)
            sleep.assert_called_once_with(SYNC.LOCAL_REPLACE_INITIAL_DELAY)
            self.assertEqual(list(root.glob(".resume.json.*.tmp")), [])

    def test_atomic_json_replace_persistent_lock_fails_bounded_and_cleans_temp(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "resume.json"
            original = b'{"old": true}\n'
            path.write_bytes(original)
            locked = OSError("injected persistent sharing violation")
            locked.winerror = 32

            with (
                mock.patch.object(SYNC, "LOCAL_REPLACE_RETRY_SECONDS", 0.0),
                mock.patch.object(SYNC.os, "replace", side_effect=locked) as replace,
                mock.patch.object(SYNC.time, "sleep") as sleep,
            ):
                with self.assertRaisesRegex(SYNC.SyncError, "remained locked"):
                    SYNC.write_json_atomic(path, {"new": True})

            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(replace.call_count, 1)
            sleep.assert_not_called()
            self.assertEqual(list(root.glob(".resume.json.*.tmp")), [])

    def test_failed_completion_save_resumes_verified_remote_history_repair(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = write_file(root / "book.pdf", pdf_bytes("journal-crash"))
            item = local_item(source)
            path = root / "resume.json"
            fingerprint = SYNC.items_fingerprint([item])
            ledger = SYNC.Ledger(
                path, host="kindle-a", port=2222, fingerprint=fingerprint, items=[item]
            )
            old = "/mnt/us/documents/LinguaLeaf/old/book.pdf"
            destination = SYNC.remote_from_relative(item.destination)
            move = SYNC.SyncAction(
                action="move",
                kind=item.kind,
                destination=destination,
                size=item.size,
                sha256=item.sha256,
                source_remote=old,
            )
            ledger.plan_path_rewrite(move)
            with mock.patch.object(
                SYNC,
                "write_json_atomic",
                side_effect=PermissionError("injected save crash"),
            ):
                with self.assertRaises(PermissionError):
                    ledger.complete_path_rewrite(old, {SYNC.KOREADER_PATH_FILES[0]: 1})

            # A fresh process sees the durable "planned" row.  The book move
            # and metadata rewrite may already be remote, so an exact target is
            # sufficient to schedule an idempotent history repair.
            resumed = SYNC.Ledger(
                path, host="kindle-a", port=2222, fingerprint=fingerprint, items=[item]
            )
            connection = LocalConnection(root / "remote")
            write_file(connection.sftp.local(destination), source.read_bytes())
            reuse = SYNC.SyncAction(
                action="reuse",
                kind=item.kind,
                destination=destination,
                size=item.size,
                sha256=item.sha256,
            )
            repairs, conflicts = SYNC.plan_pending_history_repairs(
                resumed, [reuse], connection
            )

            self.assertEqual(conflicts, [])
            self.assertEqual(len(repairs), 1)
            self.assertEqual(repairs[0].action, "history-repair")
            self.assertEqual(repairs[0].source_remote, old)
            self.assertEqual(repairs[0].destination, destination)

    def test_resume_refuses_changed_prior_item_and_different_host(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = write_file(root / "one.pdf", pdf_bytes("one"))
            first = local_item(source)
            path = root / "resume.json"
            fingerprint = SYNC.items_fingerprint([first])
            ledger = SYNC.Ledger(
                path, host="kindle-a", port=2222, fingerprint=fingerprint, items=[first]
            )
            ledger.mark_item(first.destination, "verified")
            before = path.read_bytes()
            changed = SYNC.LocalItem(**{**first.__dict__, "sha256": "f" * 64})
            with self.assertRaises(SYNC.SyncError):
                SYNC.Ledger(
                    path,
                    host="kindle-a",
                    port=2222,
                    fingerprint=SYNC.items_fingerprint([changed]),
                    items=[changed],
                )
            self.assertEqual(path.read_bytes(), before)
            with self.assertRaises(SYNC.SyncError):
                SYNC.Ledger(
                    path,
                    host="kindle-b",
                    port=2222,
                    fingerprint=fingerprint,
                    items=[first],
                )

    def test_keepawake_restores_after_body_error(self):
        class Connection:
            value = 0

            def prevent_screen_saver(self):
                return self.value

            def set_prevent_screen_saver(self, value):
                self.value = value

        class Ledger:
            def __init__(self):
                self.events = []

            def keepawake(self, **event):
                self.events.append(event)

        connection = Connection()
        ledger = Ledger()
        with self.assertRaisesRegex(RuntimeError, "body"):
            with SYNC.KeepAwake(connection, ledger):
                self.assertEqual(connection.value, 1)
                raise RuntimeError("body")
        self.assertEqual(connection.value, 0)
        self.assertFalse(ledger.events[-1]["active"])

    def test_partial_keepawake_enable_failure_is_rolled_back(self):
        class Connection:
            def __init__(self):
                self.value = 0
                self.failed = False

            def prevent_screen_saver(self):
                return self.value

            def set_prevent_screen_saver(self, value):
                self.value = value
                if value == 1 and not self.failed:
                    self.failed = True
                    raise SYNC.SyncError("injected post-mutation verification failure")

        class Ledger:
            def __init__(self):
                self.events = []

            def keepawake(self, **event):
                self.events.append(event)

        connection = Connection()
        ledger = Ledger()
        with self.assertRaises(SYNC.SyncError):
            with SYNC.KeepAwake(connection, ledger):
                self.fail("keep-awake entry should have failed")
        self.assertEqual(connection.value, 0)
        self.assertFalse(ledger.events[-1]["active"])

    def test_stale_keepawake_ledger_is_restored_before_new_capture(self):
        class Connection:
            def __init__(self):
                self.value = 1

            def prevent_screen_saver(self):
                return self.value

            def set_prevent_screen_saver(self, value):
                self.value = value

        class Ledger:
            def __init__(self):
                self.events = []

            @staticmethod
            def stale_keepawake_original():
                return 0

            def keepawake(self, **event):
                self.events.append(event)

        connection = Connection()
        ledger = Ledger()
        self.assertTrue(SYNC.recover_stale_keepawake(connection, ledger))
        self.assertEqual(connection.value, 0)
        self.assertEqual(ledger.events[-1], {"active": False, "original": 0})


class CliAndConnectionTests(unittest.TestCase):
    def test_dry_run_is_default(self):
        args = SYNC.build_parser().parse_args([])
        self.assertFalse(args.apply)

    def test_paramiko_connection_is_key_only_and_strict_known_host(self):
        class RejectPolicy:
            pass

        class Transport:
            def __init__(self):
                self.keepalive = None

            @staticmethod
            def is_active():
                return True

            def set_keepalive(self, value):
                self.keepalive = value

        class Sftp:
            @staticmethod
            def close():
                pass

        class Client:
            def __init__(self):
                self.loaded = None
                self.policy = None
                self.kwargs = None
                self.transport = Transport()

            def load_host_keys(self, value):
                self.loaded = value

            def set_missing_host_key_policy(self, value):
                self.policy = value

            def connect(self, **kwargs):
                self.kwargs = kwargs

            def get_transport(self):
                return self.transport

            @staticmethod
            def open_sftp():
                return Sftp()

            @staticmethod
            def close():
                pass

        client = Client()
        module = SimpleNamespace(SSHClient=lambda: client, RejectPolicy=RejectPolicy)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            key = write_file(root / "kindle_rsa", b"fixture key")
            known_hosts = write_file(root / "known_hosts", b"fixture host key")
            with mock.patch.dict(sys.modules, {"paramiko": module}):
                connection = SYNC.KindleConnection("192.0.2.10", 2222, key, known_hosts)
            try:
                self.assertEqual(client.loaded, str(known_hosts))
                self.assertIsInstance(client.policy, RejectPolicy)
                self.assertEqual(
                    client.kwargs,
                    {
                        "hostname": "192.0.2.10",
                        "port": 2222,
                        "username": "root",
                        "key_filename": str(key),
                        "look_for_keys": False,
                        "allow_agent": False,
                        "timeout": 15,
                        "auth_timeout": 15,
                        "banner_timeout": 15,
                    },
                )
                self.assertEqual(client.transport.keepalive, 30)
            finally:
                connection.__exit__(None, None, None)

    def test_koreader_process_causes_fail_closed_apply_gate(self):
        connection = SYNC.KindleConnection.__new__(SYNC.KindleConnection)
        connection.exec_checked = mock.Mock(return_value=b"1\n")
        self.assertTrue(connection.koreader_running())
        with self.assertRaisesRegex(SYNC.SyncError, "KOReader is running"):
            connection.assert_koreader_stopped()
        connection.exec_checked.assert_called_with(
            "command -v pidof >/dev/null 2>&1 || exit 127; "
            "pidof reader.lua >/dev/null 2>&1; rc=$?; "
            "case $rc in 0) printf '1\\n';; 1) printf '0\\n';; *) exit $rc;; esac",
            "KOReader process inspection",
            timeout=15,
        )

    def test_koreader_process_lookup_reports_stopped(self):
        connection = SYNC.KindleConnection.__new__(SYNC.KindleConnection)
        connection.exec_checked = mock.Mock(return_value=b"0\n")
        self.assertFalse(connection.koreader_running())
        connection.assert_koreader_stopped()

    def test_koreader_process_lookup_rejects_malformed_output(self):
        connection = SYNC.KindleConnection.__new__(SYNC.KindleConnection)
        connection.exec_checked = mock.Mock(return_value=b"unexpected\n")
        with self.assertRaisesRegex(SYNC.SyncError, "invalid result"):
            connection.koreader_running()


if __name__ == "__main__":
    unittest.main()
