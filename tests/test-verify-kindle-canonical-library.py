from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import stat
import sys
import tempfile
import unittest
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
from typing import Self
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT_ROOT / "scripts" / "verify-kindle-canonical-library.py"
SPEC = importlib.util.spec_from_file_location("kindle_post_sync_verifier_tests", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
VERIFIER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = VERIFIER
SPEC.loader.exec_module(VERIFIER)


def digest(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


class FakeSFTP:
    def __init__(self, nodes: dict[str, dict]) -> None:
        self.nodes = nodes
        self.mutations: list[str] = []

    def listdir_attr(self, directory: str) -> list[SimpleNamespace]:
        prefix = directory.rstrip("/") + "/"
        found = []
        for path, node in self.nodes.items():
            if path == directory or not path.startswith(prefix):
                continue
            relative = path[len(prefix) :]
            if "/" in relative:
                continue
            found.append(
                SimpleNamespace(
                    filename=relative,
                    st_mode=node["mode"],
                    st_size=node.get("size", 0),
                    st_mtime=1,
                )
            )
        return sorted(found, key=lambda row: row.filename.casefold())

    def _mutation(self, name: str) -> None:
        self.mutations.append(name)
        raise AssertionError(f"read-only verifier attempted SFTP mutation: {name}")

    def mkdir(self, *_args) -> None:
        self._mutation("mkdir")

    def remove(self, *_args) -> None:
        self._mutation("remove")

    def rename(self, *_args) -> None:
        self._mutation("rename")

    def posix_rename(self, *_args) -> None:
        self._mutation("posix_rename")

    def open(self, *_args, **_kwargs) -> None:
        self._mutation("open")


class FakeConnection:
    def __init__(self, nodes: dict[str, dict]) -> None:
        self.nodes = nodes
        self.sftp = FakeSFTP(nodes)
        self.reader_running = False
        self.prevent_value = 1
        self.free_bytes = 2 * 1024**3
        self.operations: list[str] = []

    def __enter__(self) -> Self:
        self.operations.append("enter")
        return self

    def __exit__(self, *_args) -> None:
        self.operations.append("exit")

    def lstat(self, path: str):
        self.operations.append("lstat")
        node = self.nodes.get(path)
        if node is None:
            return None
        return SimpleNamespace(
            st_mode=node["mode"],
            st_size=node.get("size", 0),
            st_mtime=1,
        )

    @staticmethod
    def require_directory(path: str, state):
        if (
            state is None
            or stat.S_ISLNK(state.st_mode)
            or not stat.S_ISDIR(state.st_mode)
        ):
            raise VERIFIER.VerifyError(f"required directory is unsafe: {path}")
        return state

    @staticmethod
    def require_regular(path: str, state):
        if (
            state is None
            or stat.S_ISLNK(state.st_mode)
            or not stat.S_ISREG(state.st_mode)
        ):
            raise VERIFIER.VerifyError(f"required file is unsafe: {path}")
        return state

    def sha256_file(self, path: str, *, expected_size: int | None = None) -> str:
        self.operations.append("sha256")
        node = self.nodes[path]
        if expected_size != node["size"]:
            raise VERIFIER.VerifyError("remote size changed")
        return node["sha256"]

    def koreader_running(self) -> bool:
        self.operations.append("pidof")
        return self.reader_running

    def prevent_screen_saver(self) -> int:
        self.operations.append("lipc-get")
        return self.prevent_value

    def available_bytes(self) -> int:
        self.operations.append("df")
        return self.free_bytes

    def set_prevent_screen_saver(self, *_args) -> None:
        raise AssertionError("read-only verifier attempted power mutation")


class RunFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.nodes: dict[str, dict] = {}
        self.canonical: dict[str, VERIFIER.ExpectedFile] = {}
        self.standalone: dict[str, VERIFIER.ExpectedFile] = {}
        self.notes: dict[str, VERIFIER.ExpectedFile] = {}
        self.retained: dict[str, VERIFIER.ExpectedFile] = {}
        self.legacy: dict[str, VERIFIER.ExpectedFile] = {}
        self.manifest_sha = digest("manifest")
        self.allowlist = []
        self.connection_args = None
        self.add_dir("/mnt/us/documents")
        self.add_dir("/mnt/us/koreader")
        self.add_file("/mnt/us/DISABLE_KOREADER_AUTOSTART", 0, digest("marker"))
        self._make_expected_files()
        self.connection = FakeConnection(self.nodes)
        self.sync_module = SimpleNamespace(
            REMOTE_DOCUMENTS="/mnt/us/documents",
            REMOTE_NOTES_ROOT="/mnt/us/documents/LinguaLeaf-Notes",
            REMOTE_LEGACY_ROOT=(
                "/mnt/us/documents/LinguaLeaf-Legacy-with-reading-state"
            ),
            SAFETY_FREE_BYTES=64 * 1024**2,
        )

        def connection_factory(host, port, key, known_hosts):
            self.connection_args = (host, port, key, known_hosts)
            return self.connection

        self.sync_module.KindleConnection = connection_factory
        self.cleanup_module = SimpleNamespace(LEGACY_CANDIDATES=tuple(self.allowlist))
        self.sync_report_path = root / "sync-report.json"
        self.cleanup_report_path = root / "cleanup-report.json"
        self.output_path = root / "verification.json"
        self.sync_report_path.write_text(
            json.dumps(self._sync_report()), encoding="utf-8"
        )
        self.cleanup_report_path.write_text(
            json.dumps(self._cleanup_report()), encoding="utf-8"
        )
        self.args = SimpleNamespace(
            host="192.0.2.10",
            port=2222,
            key=root / "key",
            known_hosts=root / "known_hosts",
            manifest=root / "manifest.json",
            lingualleaf_root=root / "LinguaLeaf",
            lazyearn_root=root / "LazyEarn",
            lazytravel_root=root / "LazyTravel",
            sync_report=self.sync_report_path,
            cleanup_report=self.cleanup_report_path,
            report=self.output_path,
            expected_state="guarded",
            skip_full_hashes=False,
            state_only=False,
        )

    def add_dir(self, path: str, *, mode: int | None = None) -> None:
        if path != "/":
            parent = str(PurePosixPath(path).parent)
            if parent not in {".", path} and parent not in self.nodes:
                self.add_dir(parent)
        self.nodes[path] = {"mode": mode or (stat.S_IFDIR | 0o755), "size": 0}

    def add_file(
        self,
        path: str,
        size: int,
        sha256: str,
        *,
        mode: int | None = None,
    ) -> None:
        parent = str(PurePosixPath(path).parent)
        if parent not in self.nodes:
            self.add_dir(parent)
        self.nodes[path] = {
            "mode": mode or (stat.S_IFREG | 0o644),
            "size": size,
            "sha256": sha256,
        }

    def add_expected(
        self,
        target: dict[str, VERIFIER.ExpectedFile],
        path: str,
        index: int,
        kind: str,
    ) -> None:
        size = 1000 + index
        checksum = digest(path)
        target[path] = VERIFIER.ExpectedFile(path, size, checksum, kind)
        self.add_file(path, size, checksum)

    def _make_expected_files(self) -> None:
        self.expected_sidecars = {
            "/mnt/us/documents/LinguaLeaf/blackwhite/category/"
            f"audited-sidecar-{index}.sdr"
            for index in range(8)
        }
        self.resumed_sidecar = min(self.expected_sidecars)
        for index, sidecar in enumerate(sorted(self.expected_sidecars)):
            self.add_expected(
                self.canonical,
                str(PurePosixPath(sidecar).with_suffix(".pdf")),
                index,
                "canonical-pdf",
            )
            self.add_dir(sidecar)
        for index in range(8, 286):
            self.add_expected(
                self.canonical,
                f"/mnt/us/documents/LinguaLeaf/blackwhite/category/book-{index:03}.pdf",
                index,
                "canonical-pdf",
            )
        self.reported_sidecars = self.expected_sidecars - {self.resumed_sidecar}

        standalone_paths = [
            "/mnt/us/documents/LazyEarn/requested-v3.pdf",
            "/mnt/us/documents/LazyEarn/requested-aligned.pdf",
            "/mnt/us/documents/LazyTravel/Hakone.pdf",
            "/mnt/us/documents/LazyTravel/Lanzhou.pdf",
            "/mnt/us/documents/LazyTravel/Xian.pdf",
        ]
        for index, path in enumerate(standalone_paths, start=400):
            self.add_expected(self.standalone, path, index, "standalone-pdf")
        retained_path = (
            "/mnt/us/documents/LazyEarn/How You Got Rich - V2 - Pocket 1.2x.pdf"
        )
        self.add_expected(self.retained, retained_path, 500, "retained-standalone-pdf")
        self.add_dir(str(PurePosixPath(retained_path).with_suffix(".sdr")))

        for index in range(34):
            self.add_expected(
                self.notes,
                f"/mnt/us/documents/LinguaLeaf-Notes/note-{index:02}.md",
                600 + index,
                "note",
            )
        self.add_expected(
            self.notes,
            "/mnt/us/documents/LinguaLeaf-Notes/SYNC-2026-08-29.md",
            699,
            "generated-note",
        )

        for index in range(16):
            path = (
                "/mnt/us/documents/LinguaLeaf-Legacy-with-reading-state/"
                f"legacy-{index:02}.pdf"
            )
            self.add_expected(self.legacy, path, 800 + index, "legacy-pdf")
            self.add_dir(str(PurePosixPath(path).with_suffix(".sdr")))
        travel = (
            "/mnt/us/documents/LazyTravel-Legacy-with-reading-state/"
            "LazyTravel-Xian-ZH-JA-EN-B6-Pocket.pdf"
        )
        self.add_expected(self.legacy, travel, 899, "legacy-pdf")
        self.add_dir(str(PurePosixPath(travel).with_suffix(".sdr")))

        for index in range(10):
            path = f"/mnt/us/documents/LinguaLeaf/old/old-{index}.pdf"
            self.allowlist.append(
                SimpleNamespace(
                    path=path,
                    candidate_id=f"old-{index}",
                    size=9000 + index,
                    sha256=digest(f"old-{index}"),
                )
            )

    @staticmethod
    def action(item, action: str, *, sidecar: bool = False) -> dict:
        destination = item.path
        return {
            "action": action,
            "kind": item.kind,
            "destination": destination,
            "size": item.size,
            "sha256": item.sha256,
            "source_local": None
            if action in {"move", "reuse", "legacy-move"}
            else "local",
            "source_remote": (
                f"/mnt/us/documents/source/{PurePosixPath(destination).name}"
                if action in {"move", "legacy-move"}
                else None
            ),
            "sidecar_source": (
                f"/mnt/us/documents/source/{PurePosixPath(destination).stem}.sdr"
                if sidecar
                else None
            ),
            "sidecar_destination": (
                str(PurePosixPath(destination).with_suffix(".sdr")) if sidecar else None
            ),
            "reason": "fixture",
        }

    def _sync_report(self) -> dict:
        actions = []
        for item in self.canonical.values():
            sidecar = str(PurePosixPath(item.path).with_suffix(".sdr"))
            actions.append(
                self.action(item, "reuse", sidecar=sidecar in self.reported_sidecars)
            )
        actions.extend(self.action(item, "upload") for item in self.standalone.values())
        actions.extend(
            self.action(item, "upload")
            for item in self.notes.values()
            if item.kind == "note"
        )
        actions.extend(
            self.action(item, "legacy-move", sidecar=True)
            for item in self.legacy.values()
        )
        counts: dict[str, int] = {}
        for row in actions:
            counts[row["action"]] = counts.get(row["action"], 0) + 1
        requested = {
            **self.canonical,
            **self.standalone,
            **{path: item for path, item in self.notes.items() if item.kind == "note"},
        }
        return {
            "schemaVersion": 1,
            "status": "complete",
            "mode": "apply",
            "host": "192.0.2.10",
            "port": 2222,
            "remoteDocuments": "/mnt/us/documents",
            "keepAwakeRestored": True,
            "completedAt": "2026-08-29T00:00:00Z",
            "manifest": {
                "schemaVersion": 2,
                "blackwhiteRows": 286,
                "categories": 29,
                "sha256": self.manifest_sha,
            },
            "sourceSummary": {
                "byKind": {"canonical-pdf": 286, "note": 34, "standalone-pdf": 5},
                "items": 325,
                "bytes": sum(item.size for item in requested.values()),
            },
            "actionSummary": dict(sorted(counts.items())),
            "actions": actions,
        }

    def _cleanup_report(self) -> dict:
        return {
            "allowlistCount": 10,
            "host": "192.0.2.10",
            "port": 2222,
            "applyRequested": True,
            "transactionComplete": True,
            "applied": True,
            "failure": None,
            "manifest": {"sha256": self.manifest_sha},
            "candidates": [
                {
                    "status": "deleted",
                    "candidate": {
                        "path": candidate.path,
                        "candidate_id": candidate.candidate_id,
                        "size": candidate.size,
                        "sha256": candidate.sha256,
                    },
                }
                for candidate in self.allowlist
            ],
        }

    def rewrite_reports(self) -> None:
        self.sync_report_path.write_text(
            json.dumps(self._sync_report()), encoding="utf-8"
        )
        self.cleanup_report_path.write_text(
            json.dumps(self._cleanup_report()), encoding="utf-8"
        )

    def run(self) -> int:
        def fake_loader(path: Path, _name: str):
            return (
                self.sync_module
                if path == VERIFIER.SYNC_SCRIPT
                else self.cleanup_module
            )

        expectations = (
            self.canonical,
            self.standalone,
            self.notes,
            self.retained,
            self.expected_sidecars,
            self.manifest_sha,
        )
        with (
            mock.patch.object(VERIFIER, "load_sibling", side_effect=fake_loader),
            mock.patch.object(
                VERIFIER, "local_expectations", return_value=expectations
            ),
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            return VERIFIER.run(self.args)


class RunLevelVerificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.fixture = RunFixture(Path(self.temporary.name))

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_happy_path_is_strict_ssh_argument_bound_and_read_only(self) -> None:
        self.assertEqual(self.fixture.run(), 0)
        self.assertEqual(
            self.fixture.connection_args,
            (
                "192.0.2.10",
                2222,
                self.fixture.args.key,
                self.fixture.args.known_hosts,
            ),
        )
        self.assertEqual(self.fixture.connection.sftp.mutations, [])
        result = json.loads(self.fixture.output_path.read_text(encoding="utf-8"))
        self.assertEqual(result["hashesVerified"], 344)

    def test_standalone_extra_is_rejected(self) -> None:
        self.fixture.add_file(
            "/mnt/us/documents/LazyTravel/extra.pdf", 123, digest("extra")
        )
        with self.assertRaisesRegex(VERIFIER.VerifyError, "LazyTravel.*inventory"):
            self.fixture.run()

    def test_renamed_standalone_content_duplicate_is_rejected(self) -> None:
        original = next(iter(self.fixture.standalone.values()))
        self.fixture.add_file(
            "/mnt/us/documents/LazyEarn/renamed-duplicate.pdf",
            original.size,
            original.sha256,
        )
        with self.assertRaisesRegex(VERIFIER.VerifyError, "LazyEarn.*inventory"):
            self.fixture.run()

    def test_wrong_remote_hash_is_rejected(self) -> None:
        path = next(iter(self.fixture.canonical))
        self.fixture.nodes[path]["sha256"] = digest("corrupt")
        with self.assertRaisesRegex(VERIFIER.VerifyError, "SHA-256 differs"):
            self.fixture.run()

    def test_standalone_and_note_hashes_are_verified(self) -> None:
        for expected in (self.fixture.standalone, self.fixture.notes):
            with self.subTest(kind=next(iter(expected.values())).kind):
                fixture = RunFixture(Path(self.temporary.name))
                selected = (
                    fixture.standalone
                    if expected is self.fixture.standalone
                    else fixture.notes
                )
                path = next(iter(selected))
                fixture.nodes[path]["sha256"] = digest("wrong")
                with self.assertRaisesRegex(VERIFIER.VerifyError, "SHA-256 differs"):
                    fixture.run()

    def test_owned_temporary_is_rejected(self) -> None:
        self.fixture.add_file(
            "/mnt/us/documents/LazyEarn/.canonical-sync-run.part",
            1,
            digest("temp"),
        )
        with self.assertRaisesRegex(VERIFIER.VerifyError, "temporary remains"):
            self.fixture.run()

    def test_low_space_is_rejected(self) -> None:
        self.fixture.connection.free_bytes = 63 * 1024**2
        with self.assertRaisesRegex(VERIFIER.VerifyError, "64 MiB"):
            self.fixture.run()

    def test_canonical_non_pdf_extra_is_rejected(self) -> None:
        self.fixture.add_file(
            "/mnt/us/documents/LinguaLeaf/blackwhite/category/extra.txt",
            1,
            digest("extra"),
        )
        with self.assertRaisesRegex(VERIFIER.VerifyError, "regular-file inventory"):
            self.fixture.run()

    def test_canonical_symlink_and_special_are_rejected(self) -> None:
        for mode in (stat.S_IFLNK | 0o777, stat.S_IFIFO | 0o600):
            with self.subTest(mode=mode):
                fixture = RunFixture(Path(self.temporary.name))
                fixture.add_file(
                    "/mnt/us/documents/LinguaLeaf/blackwhite/category/unsafe",
                    0,
                    digest("unsafe"),
                    mode=mode,
                )
                with self.assertRaisesRegex(
                    VERIFIER.VerifyError, "symlink|special file"
                ):
                    fixture.run()

    def test_notes_extra_is_rejected(self) -> None:
        self.fixture.add_file(
            "/mnt/us/documents/LinguaLeaf-Notes/extra.md", 2, digest("note-extra")
        )
        with self.assertRaisesRegex(VERIFIER.VerifyError, "Notes file inventory"):
            self.fixture.run()

    def test_legacy_hash_and_size_are_bound_to_report(self) -> None:
        path = next(iter(self.fixture.legacy))
        self.fixture.nodes[path]["sha256"] = digest("wrong-legacy")
        with self.assertRaisesRegex(VERIFIER.VerifyError, "SHA-256 differs"):
            self.fixture.run()
        fixture = RunFixture(Path(self.temporary.name))
        path = next(iter(fixture.legacy))
        fixture.nodes[path]["size"] += 1
        with self.assertRaisesRegex(VERIFIER.VerifyError, "Remote size differs"):
            fixture.run()

    def test_cleanup_candidate_sidecar_is_rejected(self) -> None:
        path = self.fixture.allowlist[0].path
        self.fixture.add_dir(str(PurePosixPath(path).with_suffix(".sdr")))
        with self.assertRaisesRegex(VERIFIER.VerifyError, "sidecar remains"):
            self.fixture.run()

    def test_marker_triad_rejects_two_active_markers(self) -> None:
        self.fixture.add_file(
            "/mnt/us/_DISABLE_KOREADER_AUTOSTART", 0, digest("standard-marker")
        )
        with self.assertRaisesRegex(VERIFIER.VerifyError, "standardAutostartMarker"):
            self.fixture.run()

    def test_emergency_marker_must_be_absent_in_every_file_type(self) -> None:
        for mode in (
            stat.S_IFREG | 0o755,
            stat.S_IFLNK | 0o777,
            stat.S_IFIFO | 0o600,
        ):
            with self.subTest(mode=mode):
                fixture = RunFixture(Path(self.temporary.name))
                fixture.add_file(
                    "/mnt/us/emergency.sh", 1, digest("emergency"), mode=mode
                )
                with self.assertRaisesRegex(VERIFIER.VerifyError, "emergencyMarker"):
                    fixture.run()

    def test_unreviewed_lingualleaf_sibling_is_conservatively_allowed(self) -> None:
        self.fixture.add_file(
            "/mnt/us/documents/LinguaLeaf/old-layout/unreviewed.pdf",
            321,
            digest("unreviewed"),
        )
        self.assertEqual(self.fixture.run(), 0)
        report = json.loads(self.fixture.output_path.read_text(encoding="utf-8"))
        self.assertIn("blackwhite only", report["linguaLeafScope"])
        self.assertIn("conservatively retained", report["linguaLeafScope"])

    def test_exact_eighth_sidecar_identity_is_required(self) -> None:
        del self.fixture.nodes[self.fixture.resumed_sidecar]
        other = str(PurePosixPath(list(self.fixture.canonical)[20]).with_suffix(".sdr"))
        self.fixture.add_dir(other)
        with self.assertRaisesRegex(VERIFIER.VerifyError, "sidecar inventory"):
            self.fixture.run()

    def test_report_host_manifest_and_strict_types_are_bound(self) -> None:
        report = json.loads(self.fixture.sync_report_path.read_text(encoding="utf-8"))
        report["manifest"]["sha256"] = digest("other-manifest")
        self.fixture.sync_report_path.write_text(json.dumps(report), encoding="utf-8")
        with self.assertRaisesRegex(VERIFIER.VerifyError, "current canonical manifest"):
            self.fixture.run()
        self.fixture.rewrite_reports()
        report = json.loads(self.fixture.sync_report_path.read_text(encoding="utf-8"))
        report["actions"][0]["size"] = True
        self.fixture.sync_report_path.write_text(json.dumps(report), encoding="utf-8")
        with self.assertRaisesRegex(VERIFIER.VerifyError, "invalid typed field"):
            self.fixture.run()


class OperationalStateTests(unittest.TestCase):
    def test_restored_marker_triad(self) -> None:
        VERIFIER.validate_operational_state(
            {
                "readerRunning": False,
                "preventScreenSaver": 0,
                "temporaryDisableMarker": "absent",
                "standardAutostartMarker": "absent",
                "originalAutostartMarker": "regular",
                "emergencyMarker": "absent",
            },
            "restored",
        )


if __name__ == "__main__":
    unittest.main()
