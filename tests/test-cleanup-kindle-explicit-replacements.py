import hashlib
import importlib.util
import json
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "cleanup-kindle-explicit-replacements.py"
)
SPEC = importlib.util.spec_from_file_location(
    "cleanup_kindle_explicit_replacements", SCRIPT
)
assert SPEC and SPEC.loader
CLEANUP = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = CLEANUP
SPEC.loader.exec_module(CLEANUP)


def manifest_value():
    rows = []
    seen = set()
    for candidate in CLEANUP.LEGACY_CANDIDATES:
        if candidate.successor_book_id in seen:
            continue
        seen.add(candidate.successor_book_id)
        payload = ("target:" + candidate.successor_book_id).encode("utf-8")
        rows.append(
            {
                "book_id": candidate.successor_book_id,
                "mode": "blackwhite",
                "destination": candidate.successor_destination,
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    return {
        "schema_version": 1,
        "generated_at": "fixture",
        "replacements": [
            {"removed": removed, "kept": kept, "reason": "fixture"}
            for removed, kept in CLEANUP.EXPECTED_REPLACEMENTS
        ],
        "rows": rows,
    }


def write_manifest(root, value=None):
    path = Path(root) / "CANONICAL-LIBRARY.json"
    path.write_text(
        json.dumps(value or manifest_value(), ensure_ascii=False), encoding="utf-8"
    )
    return path


def targets_from_value(value=None):
    value = value or manifest_value()
    result = {}
    for row in value["rows"]:
        result[row["book_id"]] = CLEANUP.CanonicalTarget(
            book_id=row["book_id"],
            destination=row["destination"],
            path=(CLEANUP.REMOTE_DOCUMENTS + "/LinguaLeaf/" + row["destination"]),
            size=row["bytes"],
            sha256=row["sha256"],
        )
    return result


class FakeConnection:
    def __init__(self, targets, *, include_candidates=True):
        self.files = {}
        for target in targets.values():
            self.files[target.path] = {
                "mode": stat.S_IFREG | 0o644,
                "size": target.size,
                "sha256": target.sha256,
                "mtime": 10,
            }
        if include_candidates:
            for candidate in CLEANUP.LEGACY_CANDIDATES:
                self.files[candidate.path] = {
                    "mode": stat.S_IFREG | 0o644,
                    "size": candidate.size,
                    "sha256": candidate.sha256,
                    "mtime": 10,
                }
        self.open_paths = set()
        self.running = False
        self.keepawake = 0
        self.keepawake_sets = []
        self.removed = []
        self.hash_calls = []
        self.before_remove = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def lstat(self, path):
        row = self.files.get(path)
        if row is None:
            return None
        return SimpleNamespace(
            st_mode=row["mode"], st_size=row["size"], st_mtime=row["mtime"]
        )

    require_regular = staticmethod(CLEANUP.KindleConnection.require_regular)

    @staticmethod
    def signature(state):
        return int(state.st_size), int(state.st_mtime)

    def sha256_file(self, path, *, expected_size=None, force=False):
        row = self.files[path]
        self.hash_calls.append((path, expected_size, force))
        if expected_size is not None and row["size"] != expected_size:
            raise CLEANUP.GuardRefusal("fixture wrong size")
        return row["sha256"]

    def has_open_file_handle(self, path):
        return path in self.open_paths

    def koreader_running(self):
        return self.running

    def assert_koreader_stopped(self):
        if self.running:
            raise CLEANUP.GuardRefusal("KOReader is running")

    def prevent_screen_saver(self):
        return self.keepawake

    def set_prevent_screen_saver(self, value):
        self.keepawake_sets.append(value)
        self.keepawake = value

    def remove_candidate(self, path):
        if self.before_remove is not None:
            self.before_remove(path)
        if path not in {row.path for row in CLEANUP.LEGACY_CANDIDATES}:
            raise AssertionError("not allowlisted")
        self.removed.append(path)
        self.files.pop(path)


class FakeLedger:
    def __init__(self):
        self.rows = []
        self.keepawake = {"active": False}
        self.fail_deleted = False

    def mark_candidate(self, candidate, status, **details):
        self.rows.append((candidate.candidate_id, status, details))
        if status == "deleted" and self.fail_deleted:
            raise OSError("injected ledger save failure")

    def mark_keepawake(self, *, active, original=None):
        self.keepawake = {"active": active, "original": original}

    def stale_keepawake_original(self):
        return self.keepawake.get("original") if self.keepawake.get("active") else None


class AllowlistTests(unittest.TestCase):
    def test_allowlist_is_exactly_ten_unique_literal_paths(self):
        CLEANUP.validate_allowlist()
        rows = CLEANUP.LEGACY_CANDIDATES
        self.assertEqual(10, len(rows))
        self.assertEqual(10, len({row.candidate_id for row in rows}))
        self.assertEqual(10, len({row.path for row in rows}))
        self.assertTrue(
            all(row.path.startswith("/mnt/us/documents/LinguaLeaf/") for row in rows)
        )
        self.assertTrue(
            all("Legacy-with-reading-state" not in row.path for row in rows)
        )

    def test_remove_candidate_rejects_every_nonliteral_path(self):
        connection = object.__new__(CLEANUP.KindleConnection)
        connection._hash_cache = {}
        connection.sftp = mock.Mock()
        moved = CLEANUP.LEGACY_CANDIDATES[0].path.replace(
            "/LinguaLeaf/", "/LinguaLeaf-Legacy-with-reading-state/"
        )
        with self.assertRaises(CLEANUP.CleanupError):
            connection.remove_candidate(moved)
        connection.sftp.remove.assert_not_called()

    def test_connection_uses_only_supplied_known_host_and_key(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            key = root / "kindle-key"
            known_hosts = root / "known_hosts"
            key.write_text("fixture", encoding="ascii")
            known_hosts.write_text("fixture", encoding="ascii")
            transport = mock.Mock()
            transport.is_active.return_value = True
            client = mock.Mock()
            client.get_transport.return_value = transport
            client.open_sftp.return_value = mock.Mock()
            policy = object()
            paramiko = SimpleNamespace(
                SSHClient=mock.Mock(return_value=client),
                RejectPolicy=mock.Mock(return_value=policy),
            )
            with mock.patch.dict(sys.modules, {"paramiko": paramiko}):
                connection = CLEANUP.KindleConnection(
                    "192.0.2.8", 2208, key, known_hosts
                )
                connection.__exit__()
        client.load_host_keys.assert_called_once_with(str(known_hosts))
        client.set_missing_host_key_policy.assert_called_once_with(policy)
        client.connect.assert_called_once_with(
            hostname="192.0.2.8",
            port=2208,
            username="root",
            key_filename=str(key),
            look_for_keys=False,
            allow_agent=False,
            timeout=15,
            auth_timeout=15,
            banner_timeout=15,
        )


class KoreaderProbeTests(unittest.TestCase):
    COMMAND = (
        "command -v pidof >/dev/null 2>&1 || exit 127; "
        "pidof reader.lua >/dev/null 2>&1; rc=$?; "
        "case $rc in 0) printf '1\n';; 1) printf '0\n';; *) exit $rc;; esac"
    )

    def connection(self, output):
        connection = CLEANUP.KindleConnection.__new__(CLEANUP.KindleConnection)
        connection.exec_checked = mock.Mock(return_value=output)
        return connection

    def test_pidof_zero_reports_running_and_blocks_apply(self):
        connection = self.connection(b"1\n")
        self.assertTrue(connection.koreader_running())
        with self.assertRaisesRegex(CLEANUP.GuardRefusal, "KOReader is running"):
            connection.assert_koreader_stopped()
        connection.exec_checked.assert_called_with(
            self.COMMAND, "KOReader process inspection", timeout=15
        )

    def test_pidof_one_reports_stopped(self):
        connection = self.connection(b"0\n")
        self.assertFalse(connection.koreader_running())
        connection.assert_koreader_stopped()

    def test_probe_rejects_malformed_output(self):
        for output in (b"", b"2\n", b"01\n", b"unexpected\n", b"0\n1\n"):
            with self.subTest(output=output):
                connection = self.connection(output)
                with self.assertRaisesRegex(CLEANUP.CleanupError, "invalid result"):
                    connection.koreader_running()

    def test_missing_pidof_and_other_nonzero_fail_closed(self):
        for exit_code in (127, 2):
            with self.subTest(exit_code=exit_code):
                connection = CLEANUP.KindleConnection.__new__(CLEANUP.KindleConnection)
                expected = CLEANUP.CleanupError(
                    f"KOReader process inspection failed with remote exit code {exit_code}."
                )
                connection.exec_checked = mock.Mock(side_effect=expected)
                with self.assertRaises(CLEANUP.CleanupError) as caught:
                    connection.koreader_running()
                self.assertIs(expected, caught.exception)
                connection.exec_checked.assert_called_once_with(
                    self.COMMAND, "KOReader process inspection", timeout=15
                )


class ManifestTests(unittest.TestCase):
    def test_manifest_binds_unique_blackwhite_successors(self):
        with tempfile.TemporaryDirectory() as temporary:
            targets, meta = CLEANUP.load_manifest_targets(write_manifest(temporary))
        self.assertEqual(7, len(targets))
        self.assertRegex(meta["sha256"], r"^[0-9a-f]{64}$")
        for candidate in CLEANUP.LEGACY_CANDIDATES:
            target = targets[candidate.successor_book_id]
            self.assertEqual(candidate.successor_destination, target.destination)

    def test_manifest_rejects_missing_replacement_pair(self):
        value = manifest_value()
        value["replacements"].pop()
        with (
            tempfile.TemporaryDirectory() as temporary,
            self.assertRaises(CLEANUP.CleanupError),
        ):
            CLEANUP.load_manifest_targets(write_manifest(temporary, value))

    def test_manifest_rejects_duplicate_successor_row(self):
        value = manifest_value()
        value["rows"].append(dict(value["rows"][0]))
        with (
            tempfile.TemporaryDirectory() as temporary,
            self.assertRaises(CLEANUP.CleanupError),
        ):
            CLEANUP.load_manifest_targets(write_manifest(temporary, value))

    def test_manifest_rejects_changed_target_path(self):
        value = manifest_value()
        value["rows"][0]["destination"] = "blackwhite/moved.pdf"
        with (
            tempfile.TemporaryDirectory() as temporary,
            self.assertRaises(CLEANUP.CleanupError),
        ):
            CLEANUP.load_manifest_targets(write_manifest(temporary, value))


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.targets = targets_from_value()
        self.connection = FakeConnection(self.targets)

    def audit(self, running=False):
        return CLEANUP.audit_candidates(
            self.connection, self.targets, koreader_running=running
        )

    def test_exact_fixture_is_eligible(self):
        rows = self.audit()
        self.assertEqual({"eligible"}, {row.status for row in rows})
        self.assertEqual([], self.connection.removed)

    def test_absent_original_is_skipped_and_moved_copy_is_never_chased(self):
        candidate = CLEANUP.LEGACY_CANDIDATES[0]
        moved = candidate.path.replace(
            "/LinguaLeaf/", "/LinguaLeaf-Legacy-with-reading-state/"
        )
        self.connection.files[moved] = self.connection.files.pop(candidate.path)
        rows = self.audit()
        row = next(value for value in rows if value.candidate == candidate)
        self.assertEqual("already-absent", row.status)
        self.assertNotIn(moved, [path for path, _, _ in self.connection.hash_calls])

    def test_absent_original_still_requires_exact_successor(self):
        candidate = CLEANUP.LEGACY_CANDIDATES[0]
        target = self.targets[candidate.successor_book_id]
        self.connection.files.pop(candidate.path)
        self.connection.files.pop(target.path)
        rows = self.audit()
        row = next(value for value in rows if value.candidate == candidate)
        self.assertEqual("refuse", row.status)
        self.assertIn("successor", row.reason)

    def test_sidecar_refuses_without_hash_or_delete(self):
        candidate = CLEANUP.LEGACY_CANDIDATES[0]
        self.connection.files[CLEANUP.sidecar_for_pdf(candidate.path)] = {
            "mode": stat.S_IFDIR | 0o755,
            "size": 0,
            "sha256": "",
            "mtime": 10,
        }
        rows = self.audit()
        row = next(value for value in rows if value.candidate == candidate)
        self.assertEqual("refuse", row.status)
        self.assertIn(".sdr", row.reason)
        self.assertNotIn(
            candidate.path, [path for path, _, _ in self.connection.hash_calls]
        )

    def test_symlink_candidate_refuses(self):
        candidate = CLEANUP.LEGACY_CANDIDATES[0]
        self.connection.files[candidate.path]["mode"] = stat.S_IFLNK | 0o777
        row = self.audit()[0]
        self.assertEqual("refuse", row.status)
        self.assertIn("non-symlink", row.reason)

    def test_wrong_candidate_hash_refuses(self):
        candidate = CLEANUP.LEGACY_CANDIDATES[0]
        self.connection.files[candidate.path]["sha256"] = "0" * 64
        row = self.audit()[0]
        self.assertEqual("refuse", row.status)
        self.assertIn("SHA-256", row.reason)

    def test_wrong_successor_hash_refuses(self):
        candidate = CLEANUP.LEGACY_CANDIDATES[0]
        target = self.targets[candidate.successor_book_id]
        self.connection.files[target.path]["sha256"] = "0" * 64
        row = self.audit()[0]
        self.assertEqual("refuse", row.status)
        self.assertIn("successor SHA-256", row.reason)

    def test_open_candidate_refuses(self):
        candidate = CLEANUP.LEGACY_CANDIDATES[0]
        self.connection.open_paths.add(candidate.path)
        row = self.audit()[0]
        self.assertEqual("refuse", row.status)
        self.assertIn("open file", row.reason)

    def test_running_koreader_refuses_all_present_candidates(self):
        rows = self.audit(running=True)
        self.assertEqual({"refuse"}, {row.status for row in rows})


class ApplyTests(unittest.TestCase):
    def setUp(self):
        self.targets = targets_from_value()
        self.connection = FakeConnection(self.targets)
        self.ledger = FakeLedger()

    def test_apply_revalidates_and_deletes_only_allowlist(self):
        rows = CLEANUP.audit_candidates(
            self.connection, self.targets, koreader_running=False
        )
        deleted = CLEANUP.apply_audits(self.connection, self.ledger, rows)
        self.assertEqual(10, len(deleted))
        self.assertEqual(set(deleted), set(self.connection.removed))
        self.assertTrue(
            all(
                path in {row.path for row in CLEANUP.LEGACY_CANDIDATES}
                for path in deleted
            )
        )
        forced_candidates = {
            path
            for path, _, force in self.connection.hash_calls
            if force and path in deleted
        }
        self.assertEqual(set(deleted), forced_candidates)
        kojiki_target = self.targets["kojiki-wenyan"].path
        forced_target_hashes = [
            path
            for path, _, force in self.connection.hash_calls
            if force and path == kojiki_target
        ]
        self.assertEqual(3, len(forced_target_hashes))

    def test_any_preflight_refusal_causes_no_delete(self):
        candidate = CLEANUP.LEGACY_CANDIDATES[0]
        self.connection.files[CLEANUP.sidecar_for_pdf(candidate.path)] = {
            "mode": stat.S_IFDIR | 0o755,
            "size": 0,
            "sha256": "",
            "mtime": 10,
        }
        rows = CLEANUP.audit_candidates(
            self.connection, self.targets, koreader_running=False
        )
        with self.assertRaises(CLEANUP.CleanupError):
            CLEANUP.apply_audits(self.connection, self.ledger, rows)
        self.assertEqual([], self.connection.removed)

    def test_late_sidecar_refuses_before_any_unlink(self):
        rows = CLEANUP.audit_candidates(
            self.connection, self.targets, koreader_running=False
        )
        candidate = CLEANUP.LEGACY_CANDIDATES[0]
        self.connection.files[CLEANUP.sidecar_for_pdf(candidate.path)] = {
            "mode": stat.S_IFDIR | 0o755,
            "size": 0,
            "sha256": "",
            "mtime": 10,
        }
        with self.assertRaises(CLEANUP.CleanupError):
            CLEANUP.apply_audits(self.connection, self.ledger, rows)
        self.assertEqual([], self.connection.removed)

    def test_koreader_restart_refuses_before_unlink(self):
        rows = CLEANUP.audit_candidates(
            self.connection, self.targets, koreader_running=False
        )
        self.connection.running = True
        with self.assertRaises(CLEANUP.GuardRefusal):
            CLEANUP.apply_audits(self.connection, self.ledger, rows)
        self.assertEqual([], self.connection.removed)

    def test_keepawake_restores_on_interrupt(self):
        def interrupt(_path):
            raise KeyboardInterrupt()

        rows = CLEANUP.audit_candidates(
            self.connection, self.targets, koreader_running=False
        )
        self.connection.before_remove = interrupt
        with (
            self.assertRaises(KeyboardInterrupt),
            CLEANUP.KeepAwake(self.connection, self.ledger),
        ):
            CLEANUP.apply_audits(self.connection, self.ledger, rows)
        self.assertEqual(0, self.connection.keepawake)
        self.assertEqual([1, 0], self.connection.keepawake_sets)
        self.assertFalse(self.ledger.keepawake["active"])

    def test_verified_unlink_is_reported_before_deleted_ledger_save(self):
        rows = CLEANUP.audit_candidates(
            self.connection, self.targets, koreader_running=False
        )
        self.ledger.fail_deleted = True
        deleted = []
        failed = {}
        with self.assertRaises(OSError):
            CLEANUP.apply_audits(
                self.connection,
                self.ledger,
                rows,
                deleted_out=deleted,
                failed_out=failed,
            )
        self.assertEqual([CLEANUP.LEGACY_CANDIDATES[0].path], deleted)
        self.assertEqual(
            CLEANUP.LEGACY_CANDIDATES[0].candidate_id, failed["candidateId"]
        )


class LedgerTests(unittest.TestCase):
    def test_ledger_rejects_host_port_or_fingerprint_drift(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "ledger.json"
            CLEANUP.Ledger(path, host="one", port=2222, fingerprint="a" * 64)
            for values in (
                ("two", 2222, "a" * 64),
                ("one", 22, "a" * 64),
                ("one", 2222, "b" * 64),
            ):
                with self.assertRaises(CLEANUP.CleanupError):
                    CLEANUP.Ledger(
                        path,
                        host=values[0],
                        port=values[1],
                        fingerprint=values[2],
                    )

    def test_ledger_rejects_malformed_root_and_nested_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "ledger.json"
            valid = {
                "schemaVersion": 1,
                "host": "one",
                "port": 2222,
                "planFingerprint": "a" * 64,
                "candidates": {},
                "keepAwake": {"active": False},
            }
            malformed = (
                [],
                {**valid, "candidates": []},
                {**valid, "keepAwake": "no"},
            )
            for value in malformed:
                path.write_text(json.dumps(value), encoding="utf-8")
                with self.assertRaises(CLEANUP.CleanupError):
                    CLEANUP.Ledger(path, host="one", port=2222, fingerprint="a" * 64)

    def test_stale_keepawake_is_recovered(self):
        connection = FakeConnection(targets_from_value(), include_candidates=False)
        connection.keepawake = 1
        ledger = FakeLedger()
        ledger.keepawake = {"active": True, "original": 0}
        self.assertTrue(CLEANUP.recover_stale_keepawake(connection, ledger))
        self.assertEqual(0, connection.keepawake)
        self.assertFalse(ledger.keepawake["active"])


class ReportingTests(unittest.TestCase):
    def test_partial_late_failure_is_written_to_report(self):
        targets = targets_from_value()
        connection = FakeConnection(targets)
        first = CLEANUP.LEGACY_CANDIDATES[0]
        second = CLEANUP.LEGACY_CANDIDATES[1]

        def sidecar_after_first(path):
            if path == first.path:
                connection.files[CLEANUP.sidecar_for_pdf(second.path)] = {
                    "mode": stat.S_IFDIR | 0o755,
                    "size": 0,
                    "sha256": "",
                    "mtime": 10,
                }

        connection.before_remove = sidecar_after_first
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            report = root / "report.json"
            args = SimpleNamespace(
                apply=True,
                host="fixture",
                port=2222,
                key=root / "key",
                known_hosts=root / "known_hosts",
                manifest=write_manifest(root),
                ledger=root / "ledger.json",
                report=report,
            )
            with (
                mock.patch.object(CLEANUP, "KindleConnection", return_value=connection),
                mock.patch("builtins.print"),
                self.assertRaises(CLEANUP.CleanupError),
            ):
                CLEANUP.run(args)
            payload = json.loads(report.read_text(encoding="utf-8"))
        self.assertEqual([first.path], payload["deleted"])
        self.assertTrue(payload["applied"])
        self.assertFalse(payload["transactionComplete"])
        self.assertIn("sidecar", payload["failure"].lower())
        statuses = {
            row["candidate"]["candidate_id"]: row["status"]
            for row in payload["candidates"]
        }
        self.assertEqual("deleted", statuses[first.candidate_id])
        self.assertEqual("failed-late", statuses[second.candidate_id])
        self.assertEqual([first.path], connection.removed)
        self.assertEqual(0, connection.keepawake)


if __name__ == "__main__":
    unittest.main()
