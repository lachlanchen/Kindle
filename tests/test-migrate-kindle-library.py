import contextlib
import hashlib
import importlib.util
import io
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from pathlib import PurePosixPath
from types import SimpleNamespace
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "migrate-kindle-library.py"
SPEC = importlib.util.spec_from_file_location("migrate_kindle_library", SCRIPT)
assert SPEC and SPEC.loader
MIGRATE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MIGRATE
SPEC.loader.exec_module(MIGRATE)


def local_book(filename, collection="LinguaLeaf", source=None):
    return MIGRATE.LocalBook(
        collection=collection,
        source=Path(source or filename),
        filename=filename,
        size=123,
        sha256="a" * 64,
        partial_md5="b" * 32,
    )


def plan_item(destination="LinguaLeaf/example.pdf"):
    return MIGRATE.PlanItem(
        collection="LinguaLeaf",
        source="example.pdf",
        filename="example.pdf",
        destination=destination,
        size=123,
        sha256="a" * 64,
        partial_md5="b" * 32,
        mapping="test",
        old_book=None,
    )


class LocalSftp:
    """Small local-filesystem SFTP double; it never opens a network connection."""

    def __init__(self, root):
        self.root = Path(root)

    def local(self, remote):
        path = PurePosixPath(remote)
        if not path.is_absolute() or ".." in path.parts:
            raise AssertionError(f"unsafe test path: {remote}")
        return self.root.joinpath(*path.parts[1:])

    def lstat(self, remote):
        return os.lstat(self.local(remote))

    def stat(self, remote):
        return os.stat(self.local(remote))

    def listdir_attr(self, remote):
        result = []
        for child in self.local(remote).iterdir():
            state = os.lstat(child)
            result.append(SimpleNamespace(filename=child.name, st_mode=state.st_mode, st_size=state.st_size))
        return result

    def open(self, remote, mode):
        return self.local(remote).open(mode)

    def mkdir(self, remote):
        self.local(remote).mkdir()

    def rename(self, source, destination):
        self.local(source).rename(self.local(destination))

    def remove(self, remote):
        self.local(remote).unlink()

    def rmdir(self, remote):
        self.local(remote).rmdir()


class LocalConnection:
    def __init__(self, root, available=2 * 1024 * 1024 * 1024, open_handles=None):
        self.sftp = LocalSftp(root)
        self._available = available
        self.open_handles = set(open_handles or ())
        self.open_handle_audit_error = None
        self.sftp.local(MIGRATE.REMOTE_LIBRARY_ROOT).mkdir(parents=True)

    def lstat(self, remote):
        try:
            return self.sftp.lstat(remote)
        except FileNotFoundError:
            return None

    def mkdirs(self, remote):
        self.sftp.local(remote).mkdir(parents=True, exist_ok=True)

    def available_bytes(self):
        return self._available

    def sha256_remote_file(self, remote):
        digest = hashlib.sha256()
        with self.sftp.open(remote, "rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    def has_open_file_handle(self, remote):
        if self.open_handle_audit_error is not None:
            raise self.open_handle_audit_error
        return remote in self.open_handles

    def write(self, remote, payload):
        path = self.sftp.local(remote)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)


class LivePreflightTests(unittest.TestCase):
    def test_posix_df_available_bytes(self):
        output = b"Filesystem 1024-blocks Used Available Capacity Mounted on\n/dev/loop/0 1000 200 800 20% /mnt/us\n"
        self.assertEqual(MIGRATE.parse_df_available_bytes(output), 800 * 1024)

    def test_unrecognized_df_output_fails_closed(self):
        with self.assertRaises(MIGRATE.MigrationError):
            MIGRATE.parse_df_available_bytes(b"not df output\n")

    def test_resume_manifest_cannot_move_between_hosts(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "resume.json"
            MIGRATE.ResumeState(state_path, [plan_item()], "old-a", "new-a")
            with self.assertRaises(MIGRATE.MigrationError):
                MIGRATE.ResumeState(state_path, [plan_item()], "old-a", "new-b")

    def test_legacy_resume_manifest_extends_one_item_and_preserves_all_ledgers(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "resume.json"
            legacy = plan_item("LinguaLeaf/one.pdf")
            legacy = MIGRATE.PlanItem(
                **{**MIGRATE.asdict(legacy), "source": "legacy/location/one.pdf"}
            )
            original = MIGRATE.ResumeState(state_path, [legacy], "old-a", "new-a")
            row = original.data["items"][legacy.destination]
            row.update(status="complete", verifiedSha256=legacy.sha256)
            # Real pre-extension schema-1 ledgers did not retain source paths.
            row.pop("source")
            original.data["misplacedBriefHistory"] = {"LinguaLeaf/wrong.pdf": "removed"}
            original.data["sidecars"] = {
                legacy.destination: {"status": "copied", "source": "LinguaLeaf/one.sdr"}
            }
            previous_fingerprint = original.data["planFingerprint"]
            original.save()

            # For a legacy row, a genuine append accepts the same destination,
            # SHA-256, and size even though the unavailable historic source path
            # cannot be proven.  This invocation's path becomes the baseline.
            current_legacy = MIGRATE.PlanItem(
                **{**MIGRATE.asdict(legacy), "source": "current/location/one.pdf"}
            )
            added = MIGRATE.PlanItem(
                **{
                    **MIGRATE.asdict(plan_item("LinguaLeaf/two.pdf")),
                    "source": "current/location/two.pdf",
                    "sha256": "c" * 64,
                    "size": 456,
                }
            )
            extended = MIGRATE.ResumeState(
                state_path, [current_legacy, added], "old-a", "new-a"
            )
            self.assertEqual(
                extended.data["items"][legacy.destination],
                {
                    "status": "complete",
                    "verifiedSha256": legacy.sha256,
                    "sha256": legacy.sha256,
                    "size": legacy.size,
                    "source": current_legacy.source,
                },
            )
            self.assertEqual(extended.data["items"][added.destination]["status"], "pending")
            self.assertEqual(
                extended.data["sidecars"][legacy.destination]["status"], "copied"
            )
            self.assertEqual(
                extended.data["misplacedBriefHistory"],
                {"LinguaLeaf/wrong.pdf": "removed"},
            )
            extension = extended.data["extensions"][-1]
            self.assertEqual(extension["fromPlanFingerprint"], previous_fingerprint)
            self.assertEqual(extension["addedDestinations"], [added.destination])
            self.assertEqual(extension["legacyIdentityBasis"], "destination+sha256+size")
            self.assertEqual(
                extension["legacySourceBaselinesAdded"], [legacy.destination]
            )
            self.assertEqual(
                json.loads(state_path.read_text(encoding="utf-8")), extended.data
            )

    def test_append_only_resume_refuses_removal_change_host_and_same_count_drift(self):
        def changed(item, **updates):
            return MIGRATE.PlanItem(**{**MIGRATE.asdict(item), **updates})

        first = plan_item("LinguaLeaf/one.pdf")
        second = changed(
            plan_item("LinguaLeaf/two.pdf"), source="two.pdf", sha256="c" * 64, size=456
        )
        cases = (
            ("removal", [first, second], [first], "old-a", "new-a"),
            (
                "changed-bytes",
                [first],
                [changed(first, sha256="d" * 64), second],
                "old-a",
                "new-a",
            ),
            ("host-change", [first], [first, second], "old-a", "new-b"),
            (
                "same-count-source-drift",
                [first],
                [changed(first, source="relocated/example.pdf")],
                "old-a",
                "new-a",
            ),
        )
        for name, initial, proposed, old_host, new_host in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                state_path = Path(directory) / "resume.json"
                MIGRATE.ResumeState(state_path, initial, "old-a", "new-a")
                before = state_path.read_bytes()
                with self.assertRaises(MIGRATE.MigrationError):
                    MIGRATE.ResumeState(state_path, proposed, old_host, new_host)
                self.assertEqual(state_path.read_bytes(), before)

    def test_resume_extension_refuses_collisions_and_malformed_ledger(self):
        first = plan_item("LinguaLeaf/Title.pdf")
        collision = MIGRATE.PlanItem(
            **{**MIGRATE.asdict(first), "destination": "lingualeaf/title.pdf", "source": "other.pdf"}
        )
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "resume.json"
            with self.assertRaises(MIGRATE.MigrationError):
                MIGRATE.ResumeState(state_path, [first, collision], "old-a", "new-a")
            self.assertFalse(state_path.exists())

            valid = MIGRATE.ResumeState(state_path, [first], "old-a", "new-a")
            valid.data["items"][first.destination]["size"] = "not-an-integer"
            valid.save()
            before = state_path.read_bytes()
            with self.assertRaises(MIGRATE.MigrationError):
                MIGRATE.ResumeState(
                    state_path,
                    [first, plan_item("LinguaLeaf/added.pdf")],
                    "old-a",
                    "new-a",
                )
            self.assertEqual(state_path.read_bytes(), before)

    def test_sidecar_inspection_does_not_change_the_book_plan_fingerprint(self):
        item = plan_item()
        inspected = MIGRATE.PlanItem(
            **{
                **MIGRATE.asdict(item),
                "old_sidecar": "LinguaLeaf/example.sdr",
                "sidecar_eligible": True,
                "sidecar_reason": "partial_md5_checksum-match",
            }
        )
        self.assertEqual(MIGRATE.plan_fingerprint([item]), MIGRATE.plan_fingerprint([inspected]))

    def test_existing_schema_one_ledger_without_sidecars_remains_compatible(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "resume.json"
            state = MIGRATE.ResumeState(state_path, [plan_item()], "old-a", "new-a")
            state.data.pop("sidecars")
            state.save()
            reloaded = MIGRATE.ResumeState(state_path, [plan_item()], "old-a", "new-a")
            reloaded.mark_sidecar("LinguaLeaf/example.pdf", "skipped-ineligible:partial_md5_checksum-mismatch")
            self.assertEqual(
                reloaded.data["sidecars"]["LinguaLeaf/example.pdf"]["status"],
                "skipped-ineligible:partial_md5_checksum-mismatch",
            )

    def test_sidecar_result_is_recorded_in_the_atomic_resume_ledger(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "resume.json"
            state = MIGRATE.ResumeState(state_path, [plan_item()], "old-a", "new-a")
            state.mark_sidecar(
                "LinguaLeaf/example.pdf",
                "copied",
                source="LinguaLeaf/example.sdr",
                destination="LinguaLeaf/example.sdr",
            )
            reloaded = MIGRATE.ResumeState(state_path, [plan_item()], "old-a", "new-a")
            self.assertEqual(
                reloaded.data["sidecars"]["LinguaLeaf/example.pdf"],
                {
                    "status": "copied",
                    "source": "LinguaLeaf/example.sdr",
                    "destination": "LinguaLeaf/example.sdr",
                },
            )

    def test_atomic_manifest_replace_retries_a_transient_windows_reader_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "resume.json"
            real_replace = os.replace
            attempts = 0

            def replace_after_one_lock(source, destination):
                nonlocal attempts
                attempts += 1
                if attempts == 1:
                    raise PermissionError("transient reader lock")
                return real_replace(source, destination)

            with mock.patch.object(MIGRATE.os, "replace", side_effect=replace_after_one_lock):
                MIGRATE.write_json_atomic(target, {"status": "ok"})
            self.assertEqual(attempts, 2)
            self.assertEqual(target.read_text(encoding="utf-8"), '{\n  "status": "ok"\n}\n')


class MappingTests(unittest.TestCase):
    def test_descriptor_fallbacks(self):
        cases = {
            "A｜English-日本語-中文｜黑白.pdf": "LinguaLeaf/en-jp-zh-blackwhite",
            "A｜文言文-English-日本語-中文｜黑白.pdf": "LinguaLeaf/wenyan-main-quadrilingual-blackwhite",
            "A｜日本語-中文｜黑白.pdf": "LinguaLeaf/jp-zh-blackwhite",
            "A｜العربية-English-日本語-中文｜黑白.pdf": "LinguaLeaf/ar-en-jp-zh-blackwhite",
            "A｜和歌仮名-English-日本語-中文｜黑白.pdf": "LinguaLeaf/waka-kana-en-jp-zh-blackwhite",
        }
        for filename, directory in cases.items():
            with self.subTest(filename=filename):
                destination, mapping, old = MIGRATE.destination_for_book(local_book(filename), {})
                self.assertEqual(destination, f"{directory}/{filename}")
                self.assertTrue(mapping.startswith("descriptor:"))
                self.assertIsNone(old)

    def test_four_classical_fallbacks_are_explicit(self):
        expected_directories = [
            "LinguaLeaf/wenyan-jp-zh-trilingual-leftovers-blackwhite",
            "LinguaLeaf/wenyan-jp-zh-trilingual-leftovers-blackwhite",
            "LinguaLeaf/jp-zh-blackwhite",
            "LinguaLeaf/wenyan-jp-zh-trilingual-leftovers-blackwhite",
        ]
        self.assertEqual(len(MIGRATE.CLASSICAL_PREDECESSORS), 4)
        for (filename, (_predecessor, directory)), expected in zip(
            MIGRATE.CLASSICAL_PREDECESSORS.items(), expected_directories
        ):
            destination, mapping, old = MIGRATE.destination_for_book(local_book(filename), {})
            self.assertEqual(directory, expected)
            self.assertEqual(destination, f"{expected}/{filename}")
            self.assertTrue(mapping.startswith("classical-fallback:"))
            self.assertIsNone(old)

    def test_classical_predecessor_parent_is_reused(self):
        filename, (predecessor, _fallback) = next(iter(MIGRATE.CLASSICAL_PREDECESSORS.items()))
        old_path = f"LinguaLeaf/audited/{predecessor}"
        destination, mapping, old = MIGRATE.destination_for_book(
            local_book(filename), {predecessor: [old_path]}
        )
        self.assertEqual(destination, f"LinguaLeaf/audited/{filename}")
        self.assertEqual(old, old_path)
        self.assertTrue(mapping.startswith("classical-predecessor:"))

    def test_shiji_predecessors_and_zizhi_part_one_keep_auditable_old_paths(self):
        shiji = {
            filename: predecessor
            for filename, (predecessor, _directory) in MIGRATE.CLASSICAL_PREDECESSORS.items()
            if "史記" in filename
        }
        self.assertEqual(len(shiji), 2)
        for filename, predecessor in shiji.items():
            old_path = f"LinguaLeaf/old-classics/{predecessor}"
            destination, mapping, old = MIGRATE.destination_for_book(
                local_book(filename), {predecessor: [old_path]}
            )
            self.assertEqual(destination, f"LinguaLeaf/old-classics/{filename}")
            self.assertEqual(old, old_path)
            self.assertTrue(mapping.startswith("classical-predecessor:"))

        zizhi_part_one = (
            "資治通鑑第一部（正文注釋辨識版・英文・現代日本語・現代中文注）｜文言文-English-日本語-中文｜黑白.pdf",
            "資治通鑑第一部（英文・現代日本語・現代中文注）｜文言文-English-日本語-中文｜黑白.pdf",
        )
        for filename in zizhi_part_one:
            old_path = f"LinguaLeaf/old-classics/{filename}"
            destination, mapping, old = MIGRATE.destination_for_book(
                local_book(filename), {filename: [old_path]}
            )
            self.assertEqual((destination, mapping, old), (old_path, "old-exact", old_path))

    def test_exact_old_path_wins_and_pocket_is_flat(self):
        lingua = "A｜English-日本語-中文｜黑白.pdf"
        old = f"LinguaLeaf/old-layout/{lingua}"
        self.assertEqual(
            MIGRATE.destination_for_book(local_book(lingua), {lingua: [old]})[0], old
        )
        pocket = "Pocket title.pdf"
        self.assertEqual(
            MIGRATE.destination_for_book(local_book(pocket, "PocketPolished"), {})[0],
            f"PocketPolished/{pocket}",
        )

    def test_brief_history_is_forced_canonical_even_if_old_is_ambiguous(self):
        name = MIGRATE.MISPLACED_BRIEF_HISTORY_NAME
        destination, _mapping, old = MIGRATE.destination_for_book(
            local_book(name), {name: [f"LinguaLeaf/{name}", f"PocketPolished/{name}"]}
        )
        self.assertEqual(destination, MIGRATE.CORRECT_BRIEF_HISTORY_RELATIVE)
        self.assertIsNone(old)

    def test_collisions_and_traversal_fail_closed(self):
        first = local_book("Title｜English-日本語-中文｜黑白.pdf", source="one")
        second = local_book("title｜English-日本語-中文｜黑白.pdf", source="two")
        with self.assertRaises(MIGRATE.MigrationError):
            MIGRATE.build_plan([first, second], [])
        for unsafe in ("../book.pdf", "/book.pdf", "safe/../../book.pdf", "safe\\book.pdf"):
            with self.subTest(unsafe=unsafe), self.assertRaises(MIGRATE.MigrationError):
                MIGRATE.safe_relative_path(unsafe)

    @unittest.skipUnless(
        MIGRATE.DEFAULT_LINGUA.is_dir()
        and sum(
            source.suffix.casefold() == ".pdf"
            for source in MIGRATE.DEFAULT_LINGUA.iterdir()
        )
        == 256,
        "legacy flat 256-file Nutstore corpus is unavailable",
    )
    def test_legacy_flat_lingualleaf_corpus_maps_all_256_files(self):
        counts = {}
        mapped = 0
        for source in MIGRATE.DEFAULT_LINGUA.iterdir():
            if source.suffix.casefold() != ".pdf":
                continue
            destination, _mapping, _old = MIGRATE.destination_for_book(local_book(source.name), {})
            directory = str(Path(destination).parent).replace("\\", "/")
            counts[directory] = counts.get(directory, 0) + 1
            mapped += 1
        self.assertEqual(mapped, 256)
        self.assertEqual(
            counts,
            {
                "LinguaLeaf/ar-en-jp-zh-blackwhite": 1,
                "LinguaLeaf/en-jp-zh-blackwhite": 177,
                "LinguaLeaf/jp-zh-blackwhite": 9,
                "LinguaLeaf/waka-kana-en-jp-zh-blackwhite": 2,
                "LinguaLeaf/wenyan-jp-zh-trilingual-leftovers-blackwhite": 3,
                "LinguaLeaf/wenyan-main-quadrilingual-blackwhite": 64,
            },
        )


class ChecksumAndSidecarTests(unittest.TestCase):
    def replacement_fixture(self, root, existing_payload=b"new-Kindle-state"):
        old = LocalConnection(root / "old")
        new = LocalConnection(root / "new")
        book_bytes = b"Nutstore authoritative PDF"
        checksum = hashlib.md5().hexdigest()  # The short fixture has no sample at offset 256.
        old_book = "LinguaLeaf/old-layout/title.pdf"
        old_sidecar = "LinguaLeaf/old-layout/title.sdr"
        destination = "LinguaLeaf/new-layout/title.pdf"
        destination_sidecar = MIGRATE.sidecar_destination(destination)
        old.write(
            MIGRATE.remote_join(MIGRATE.REMOTE_LIBRARY_ROOT, old_book),
            book_bytes,
        )
        old.write(
            MIGRATE.remote_join(MIGRATE.REMOTE_LIBRARY_ROOT, f"{old_sidecar}/metadata.pdf.lua"),
            f'return {{ partial_md5_checksum = "{checksum}", percent_finished = 0.75 }}'.encode(),
        )
        old.write(
            MIGRATE.remote_join(MIGRATE.REMOTE_LIBRARY_ROOT, f"{old_sidecar}/notes/highlights.txt"),
            b"old-PW2-reading-state",
        )
        new.write(
            MIGRATE.remote_join(MIGRATE.REMOTE_LIBRARY_ROOT, destination),
            book_bytes,
        )
        new.write(
            MIGRATE.remote_join(MIGRATE.REMOTE_LIBRARY_ROOT, f"{destination_sidecar}/local-state.txt"),
            existing_payload,
        )
        item = MIGRATE.PlanItem(
            collection="LinguaLeaf",
            source="Nutstore/title.pdf",
            filename="title.pdf",
            destination=destination,
            size=len(book_bytes),
            sha256=hashlib.sha256(book_bytes).hexdigest(),
            partial_md5=checksum,
            mapping="old-exact",
            old_book=old_book,
            old_sidecar=old_sidecar,
            sidecar_eligible=True,
            sidecar_reason="partial_md5_checksum-match",
        )
        return old, new, item, destination_sidecar

    def test_partial_md5_matches_koreader_sampling_offsets(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "sample.bin"
            data = bytes(range(251)) * 9000
            path.write_bytes(data)
            expected = hashlib.md5()  # compatibility checksum, not security
            for offset in [256 * (4**index) for index in range(12)]:
                sample = data[offset : offset + 1024]
                if not sample:
                    break
                expected.update(sample)
            self.assertEqual(MIGRATE.partial_md5(path), expected.hexdigest())
            self.assertEqual(MIGRATE.PARTIAL_MD5_OFFSETS[-1], 1_073_741_824)

    def test_sidecar_requires_matching_partial_md5(self):
        checksum = "0123456789abcdef0123456789abcdef"
        metadata = {"metadata.epub.lua": f'return {{ ["partial_md5_checksum"] = "{checksum}" }}'.encode()}
        self.assertEqual(
            MIGRATE.sidecar_eligibility(checksum, metadata),
            (True, "partial_md5_checksum-match"),
        )
        self.assertEqual(
            MIGRATE.sidecar_eligibility("f" * 32, metadata),
            (False, "partial_md5_checksum-mismatch"),
        )
        self.assertEqual(
            MIGRATE.sidecar_eligibility(checksum, {"metadata.lua": b"return {}"}),
            (False, "partial_md5_checksum-missing"),
        )

    def test_koreader_sidecar_path_drops_the_pdf_suffix(self):
        book = "LinguaLeaf/classics/史記.pdf"
        self.assertEqual(MIGRATE.sidecar_destination(book), "LinguaLeaf/classics/史記.sdr")
        self.assertEqual(
            MIGRATE.sidecar_candidates(book),
            ("LinguaLeaf/classics/史記.sdr", "LinguaLeaf/classics/史記.pdf.sdr"),
        )

    def test_copy_is_atomic_idempotent_and_scoped_to_one_matched_sidecar(self):
        book_bytes = b"Nutstore is authoritative"
        checksum = hashlib.md5().hexdigest()  # KOReader samples nothing below offset 256.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old = LocalConnection(root / "old")
            new = LocalConnection(root / "new")
            old_sidecar = "LinguaLeaf/old-classics/史記.sdr"
            old.write(
                MIGRATE.remote_join(MIGRATE.REMOTE_LIBRARY_ROOT, f"{old_sidecar}/metadata.pdf.lua"),
                f'return {{ ["partial_md5_checksum"] = "{checksum}", percent_finished = 0.42 }}'.encode(),
            )
            old.write(
                MIGRATE.remote_join(MIGRATE.REMOTE_LIBRARY_ROOT, f"{old_sidecar}/notes/highlights.txt"),
                b"book-specific note",
            )
            old.write(
                MIGRATE.remote_join(MIGRATE.REMOTE_LIBRARY_ROOT, "LinguaLeaf/old-classics/unrelated.sdr/metadata.pdf.lua"),
                b"unrelated",
            )
            destination = "LinguaLeaf/new-classics/史記.pdf"
            remote_book = MIGRATE.remote_join(MIGRATE.REMOTE_LIBRARY_ROOT, destination)
            new.write(remote_book, book_bytes)
            # An interrupted earlier run may leave only this exact owned temp.
            stale = MIGRATE.sidecar_destination(destination) + ".migrate-abc123.tmp"
            new.write(
                MIGRATE.remote_join(MIGRATE.REMOTE_LIBRARY_ROOT, f"{stale}/partial"),
                b"partial",
            )
            item = MIGRATE.PlanItem(
                collection="LinguaLeaf",
                source="Nutstore/史記.pdf",
                filename="史記.pdf",
                destination=destination,
                size=len(book_bytes),
                sha256=hashlib.sha256(book_bytes).hexdigest(),
                partial_md5=checksum,
                mapping="test",
                old_book="LinguaLeaf/old-classics/史記.pdf",
                old_sidecar=old_sidecar,
                sidecar_eligible=True,
                sidecar_reason="partial_md5_checksum-match",
            )
            old.write(
                MIGRATE.remote_join(MIGRATE.REMOTE_LIBRARY_ROOT, item.old_book),
                book_bytes,
            )

            self.assertEqual(MIGRATE.copy_sidecar_best_effort(item, old, new, "abc123"), "copied")
            destination_sidecar = new.sftp.local(
                MIGRATE.remote_join(MIGRATE.REMOTE_LIBRARY_ROOT, "LinguaLeaf/new-classics/史記.sdr")
            )
            self.assertEqual((destination_sidecar / "notes" / "highlights.txt").read_bytes(), b"book-specific note")
            self.assertFalse(new.sftp.local(MIGRATE.remote_join(MIGRATE.REMOTE_LIBRARY_ROOT, stale)).exists())
            self.assertFalse(
                new.sftp.local(
                    MIGRATE.remote_join(MIGRATE.REMOTE_LIBRARY_ROOT, "LinguaLeaf/new-classics/史記.pdf.sdr")
                ).exists()
            )
            self.assertFalse(
                new.sftp.local(
                    MIGRATE.remote_join(MIGRATE.REMOTE_LIBRARY_ROOT, "LinguaLeaf/new-classics/unrelated.sdr")
                ).exists()
            )
            self.assertEqual(new.sftp.local(remote_book).read_bytes(), book_bytes)
            self.assertFalse(any("backup" in path.name.casefold() or path.suffix == ".bak" for path in (root / "new").rglob("*")))
            self.assertEqual(
                MIGRATE.copy_sidecar_best_effort(item, old, new, "abc123"),
                "skipped-destination-exists",
            )

    def test_existing_sidecar_is_refused_by_default_without_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old, new, item, destination_sidecar = self.replacement_fixture(root)
            destination_root = new.sftp.local(
                MIGRATE.remote_join(MIGRATE.REMOTE_LIBRARY_ROOT, destination_sidecar)
            )
            before = (destination_root / "local-state.txt").read_bytes()
            with mock.patch.object(new.sftp, "rename", wraps=new.sftp.rename) as rename:
                result = MIGRATE.copy_sidecar_best_effort(item, old, new, "replace1")
            self.assertEqual(result, "skipped-destination-exists")
            rename.assert_not_called()
            self.assertEqual((destination_root / "local-state.txt").read_bytes(), before)

    def test_explicit_existing_sidecar_replacement_is_verified_and_leaves_no_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old, new, item, destination_sidecar = self.replacement_fixture(root)
            result = MIGRATE.copy_sidecar_best_effort(
                item, old, new, "replace2", replace_existing=True
            )
            self.assertEqual(result, "replaced-existing")
            destination_root = new.sftp.local(
                MIGRATE.remote_join(MIGRATE.REMOTE_LIBRARY_ROOT, destination_sidecar)
            )
            self.assertEqual(
                (destination_root / "notes" / "highlights.txt").read_bytes(),
                b"old-PW2-reading-state",
            )
            self.assertFalse((destination_root / "local-state.txt").exists())
            self.assertFalse(
                any(".migrate-replace2." in path.name for path in (root / "new").rglob("*"))
            )

    def test_explicit_replacement_rerun_resumes_an_exact_tree_without_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old, new, item, _destination_sidecar = self.replacement_fixture(root)
            self.assertEqual(
                MIGRATE.copy_sidecar_best_effort(
                    item, old, new, "replace3", replace_existing=True
                ),
                "replaced-existing",
            )
            with mock.patch.object(new.sftp, "rename", wraps=new.sftp.rename) as rename:
                result = MIGRATE.copy_sidecar_best_effort(
                    item, old, new, "replace3", replace_existing=True
                )
            self.assertEqual(result, "resumed-existing-match")
            rename.assert_not_called()

    def test_publish_failure_restores_existing_sidecar_and_removes_owned_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old, new, item, destination_sidecar = self.replacement_fixture(root)
            destination = MIGRATE.remote_join(MIGRATE.REMOTE_LIBRARY_ROOT, destination_sidecar)
            temp = destination + ".migrate-replace4.tmp"
            rollback = destination + ".migrate-replace4.rollback"
            original_rename = new.sftp.rename

            def fail_publish(source, target):
                if source == temp and target == destination:
                    raise OSError("injected publish failure")
                return original_rename(source, target)

            with mock.patch.object(new.sftp, "rename", side_effect=fail_publish):
                result = MIGRATE.copy_sidecar_best_effort(
                    item, old, new, "replace4", replace_existing=True
                )
            self.assertEqual(result, "skipped-replace-failed")
            destination_root = new.sftp.local(destination)
            self.assertEqual(
                (destination_root / "local-state.txt").read_bytes(),
                b"new-Kindle-state",
            )
            self.assertFalse(new.sftp.local(temp).exists())
            self.assertFalse(new.sftp.local(rollback).exists())

    def test_replacement_refuses_an_open_destination_book_or_failed_proc_audit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old, new, item, destination_sidecar = self.replacement_fixture(root)
            book = MIGRATE.remote_join(MIGRATE.REMOTE_LIBRARY_ROOT, item.destination)
            destination_root = new.sftp.local(
                MIGRATE.remote_join(MIGRATE.REMOTE_LIBRARY_ROOT, destination_sidecar)
            )
            new.open_handles.add(book)
            with mock.patch.object(new.sftp, "rename", wraps=new.sftp.rename) as rename:
                result = MIGRATE.copy_sidecar_best_effort(
                    item, old, new, "replace5", replace_existing=True
                )
            self.assertEqual(result, "skipped-destination-book-open")
            rename.assert_not_called()
            self.assertTrue((destination_root / "local-state.txt").exists())

            new.open_handles.clear()
            new.open_handle_audit_error = OSError("cannot inspect /proc")
            with mock.patch.object(new.sftp, "rename", wraps=new.sftp.rename) as rename:
                result = MIGRATE.copy_sidecar_best_effort(
                    item, old, new, "replace6", replace_existing=True
                )
            self.assertEqual(result, "skipped-open-handle-check-failed")
            rename.assert_not_called()

    def test_stale_metadata_is_allowed_only_when_current_old_book_matches_nutstore(self):
        stale_checksum = "f" * 32
        book_bytes = bytes(range(251)) * 24
        changed_bytes = bytes(reversed(range(251))) * 24
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            nutstore = root / "nutstore.pdf"
            nutstore.write_bytes(book_bytes)
            checksum = MIGRATE.partial_md5(nutstore)
            old = LocalConnection(root / "old")
            new = LocalConnection(root / "new")
            old_book = "LinguaLeaf/classics/資治通鑑第一部.pdf"
            old_sidecar = "LinguaLeaf/classics/資治通鑑第一部.sdr"
            old.write(MIGRATE.remote_join(MIGRATE.REMOTE_LIBRARY_ROOT, old_book), book_bytes)
            old.write(
                MIGRATE.remote_join(MIGRATE.REMOTE_LIBRARY_ROOT, f"{old_sidecar}/metadata.pdf.lua"),
                f'return {{ partial_md5_checksum = "{stale_checksum}", doc_pages = 18079, last_page = 4651 }}'.encode(),
            )
            destination = "LinguaLeaf/new-classics/資治通鑑第一部.pdf"
            item = MIGRATE.PlanItem(
                collection="LinguaLeaf", source=str(nutstore), filename=nutstore.name,
                destination=destination, size=len(book_bytes), sha256=hashlib.sha256(book_bytes).hexdigest(),
                partial_md5=checksum, mapping="old-exact", old_book=old_book,
            )

            inspected = MIGRATE.inspect_sidecars([item], old)[0]
            self.assertTrue(inspected.sidecar_eligible)
            self.assertEqual(inspected.old_sidecar, old_sidecar)
            self.assertEqual(
                inspected.sidecar_reason,
                "old-book-size-and-partial-md5-match:metadata-stale",
            )
            new.write(MIGRATE.remote_join(MIGRATE.REMOTE_LIBRARY_ROOT, destination), book_bytes)
            self.assertEqual(MIGRATE.copy_sidecar_best_effort(inspected, old, new, "abc123"), "copied")

            # An equal-size but different current PW2 PDF is not sufficient.
            old.write(MIGRATE.remote_join(MIGRATE.REMOTE_LIBRARY_ROOT, old_book), changed_bytes)
            second_destination = "LinguaLeaf/new-classics/changed.pdf"
            different = MIGRATE.PlanItem(
                **{
                    **MIGRATE.asdict(item),
                    "destination": second_destination,
                }
            )
            refused = MIGRATE.inspect_sidecars([different], old)[0]
            self.assertFalse(refused.sidecar_eligible)
            self.assertEqual(refused.sidecar_reason, "partial_md5_checksum-mismatch")
            new.write(MIGRATE.remote_join(MIGRATE.REMOTE_LIBRARY_ROOT, second_destination), book_bytes)
            self.assertNotEqual(MIGRATE.copy_sidecar_best_effort(refused, old, new, "def456"), "copied")

    def test_copy_requires_the_exact_existing_nutstore_destination(self):
        checksum = "0123456789abcdef0123456789abcdef"
        expected = b"expected Nutstore bytes"
        actual = b"unexpected old bytes!!!"
        self.assertEqual(len(expected), len(actual))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old = LocalConnection(root / "old")
            new = LocalConnection(root / "new")
            old_sidecar = "LinguaLeaf/title.sdr"
            old.write(
                MIGRATE.remote_join(MIGRATE.REMOTE_LIBRARY_ROOT, f"{old_sidecar}/metadata.pdf.lua"),
                f'return {{ partial_md5_checksum = "{checksum}" }}'.encode(),
            )
            destination = "LinguaLeaf/title.pdf"
            new.write(MIGRATE.remote_join(MIGRATE.REMOTE_LIBRARY_ROOT, destination), actual)
            item = MIGRATE.PlanItem(
                collection="LinguaLeaf", source="Nutstore/title.pdf", filename="title.pdf",
                destination=destination, size=len(expected), sha256=hashlib.sha256(expected).hexdigest(),
                partial_md5=checksum, mapping="test", old_book=destination,
                old_sidecar=old_sidecar, sidecar_eligible=True,
                sidecar_reason="partial_md5_checksum-match",
            )
            self.assertEqual(
                MIGRATE.copy_sidecar_best_effort(item, old, new, "abc123"),
                "skipped-destination-book-hash-mismatch",
            )
            self.assertFalse(
                new.sftp.local(
                    MIGRATE.remote_join(MIGRATE.REMOTE_LIBRARY_ROOT, MIGRATE.sidecar_destination(destination))
                ).exists()
            )

    def test_copy_refuses_checksum_mismatch_even_when_plan_claimed_eligible(self):
        checksum = "0123456789abcdef0123456789abcdef"
        book_bytes = b"Nutstore bytes"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old = LocalConnection(root / "old")
            new = LocalConnection(root / "new")
            old_sidecar = "LinguaLeaf/title.sdr"
            old.write(
                MIGRATE.remote_join(MIGRATE.REMOTE_LIBRARY_ROOT, f"{old_sidecar}/metadata.pdf.lua"),
                b'return { partial_md5_checksum = "ffffffffffffffffffffffffffffffff" }',
            )
            destination = "LinguaLeaf/title.pdf"
            new.write(MIGRATE.remote_join(MIGRATE.REMOTE_LIBRARY_ROOT, destination), book_bytes)
            item = MIGRATE.PlanItem(
                collection="LinguaLeaf", source="Nutstore/title.pdf", filename="title.pdf",
                destination=destination, size=len(book_bytes), sha256=hashlib.sha256(book_bytes).hexdigest(),
                partial_md5=checksum, mapping="test", old_book=destination,
                old_sidecar=old_sidecar, sidecar_eligible=True,
                sidecar_reason="partial_md5_checksum-match",
            )
            self.assertEqual(MIGRATE.copy_sidecar_best_effort(item, old, new, "abc123"), "skipped-source-changed")


class ApplySafetyTests(unittest.TestCase):
    def test_replace_existing_sdr_requires_apply_and_copy_sdr(self):
        invalid = (
            ["--replace-existing-sdr"],
            ["--replace-existing-sdr", "--apply"],
            ["--replace-existing-sdr", "--copy-sdr"],
        )
        for argv in invalid:
            with self.subTest(argv=argv), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    MIGRATE.parse_args(argv)
                self.assertEqual(raised.exception.code, 2)
        valid = MIGRATE.parse_args(
            ["--replace-existing-sdr", "--apply", "--copy-sdr"]
        )
        self.assertTrue(valid.replace_existing_sdr)

    def test_default_mode_never_connects_to_new_kindle(self):
        connections = []

        class FakeConnection:
            def __init__(self, host, *_args):
                connections.append(host)

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def list_pdf_relatives(self):
                return []

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            lingua = root / "lingua"
            pocket = root / "pocket"
            lingua.mkdir()
            pocket.mkdir()
            (lingua / "A｜English-日本語-中文｜黑白.pdf").write_bytes(b"lingua")
            (pocket / "Pocket.pdf").write_bytes(b"pocket")
            key = root / "key"
            key.write_text("not-used", encoding="ascii")
            argv = [
                "--lingua-root", str(lingua), "--pocket-root", str(pocket),
                "--key", str(key), "--known-hosts", str(root / "known_hosts"),
            ]
            with mock.patch.object(MIGRATE, "KindleConnection", FakeConnection):
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(MIGRATE.main(argv), 0)
        self.assertEqual(connections, [MIGRATE.OLD_HOST_DEFAULT])

    def test_exact_hash_cleanup_removes_only_two_noncanonical_copies(self):
        name = MIGRATE.MISPLACED_BRIEF_HISTORY_NAME
        item = MIGRATE.PlanItem(
            collection="LinguaLeaf", source="local.pdf", filename=name,
            destination=MIGRATE.CORRECT_BRIEF_HISTORY_RELATIVE, size=123,
            sha256="a" * 64, partial_md5="b" * 32, mapping="test", old_book=None,
        )

        class State:
            data = {}
            def status(self, _destination): return "complete"
            def save(self): pass

        class Sftp:
            def __init__(self): self.removed = []
            def remove(self, path): self.removed.append(path)

        class New:
            def __init__(self): self.sftp = Sftp()
            def lstat(self, path):
                book_paths = {
                    MIGRATE.remote_join(MIGRATE.REMOTE_LIBRARY_ROOT, MIGRATE.CORRECT_BRIEF_HISTORY_RELATIVE),
                    *(MIGRATE.remote_join(MIGRATE.REMOTE_LIBRARY_ROOT, p) for p in MIGRATE.MISPLACED_BRIEF_HISTORY_RELATIVES),
                }
                return SimpleNamespace(st_mode=stat.S_IFREG | 0o644, st_size=123) if path in book_paths else None
            def sha256_remote_file(self, _path): return "a" * 64

        new = New()
        result = MIGRATE.cleanup_misplaced_brief_history([item], new, State())
        expected = {
            MIGRATE.remote_join(MIGRATE.REMOTE_LIBRARY_ROOT, relative)
            for relative in MIGRATE.MISPLACED_BRIEF_HISTORY_RELATIVES
        }
        self.assertEqual(set(new.sftp.removed), expected)
        self.assertEqual(set(result), set(MIGRATE.MISPLACED_BRIEF_HISTORY_RELATIVES))

    def test_canonical_hash_mismatch_blocks_every_delete(self):
        item = MIGRATE.PlanItem(
            collection="LinguaLeaf", source="local.pdf", filename=MIGRATE.MISPLACED_BRIEF_HISTORY_NAME,
            destination=MIGRATE.CORRECT_BRIEF_HISTORY_RELATIVE, size=123,
            sha256="a" * 64, partial_md5="b" * 32, mapping="test", old_book=None,
        )

        class State:
            data = {}
            def status(self, _destination): return "complete"
            def save(self): pass

        class New:
            sftp = SimpleNamespace(remove=mock.Mock())
            def lstat(self, _path): return SimpleNamespace(st_mode=stat.S_IFREG | 0o644, st_size=123)
            def sha256_remote_file(self, _path): return "f" * 64

        new = New()
        with self.assertRaises(MIGRATE.MigrationError):
            MIGRATE.cleanup_misplaced_brief_history([item], new, State())
        new.sftp.remove.assert_not_called()


if __name__ == "__main__":
    unittest.main()
