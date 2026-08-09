from __future__ import annotations

import base64
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

import paramiko


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import build  # noqa: E402
from app import kindle_sender as sender  # noqa: E402


SHARED_PRIVATE_KEY = REPOSITORY_ROOT / "Handoff" / "keys" / "kindle_handoff_rsa"
SHARED_PUBLIC_KEY = SHARED_PRIVATE_KEY.with_suffix(".pub")


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class SharedKeyTests(unittest.TestCase):
    def test_tracked_shared_identity_matches_pin_and_companion_public_key(self) -> None:
        key = sender.load_pinned_shared_key(SHARED_PRIVATE_KEY)
        self.assertEqual(sender.openssh_sha256_fingerprint(key), sender.SHARED_KEY_FINGERPRINT)
        self.assertEqual(
            sender.public_key_file_fingerprint(SHARED_PUBLIC_KEY),
            sender.SHARED_KEY_FINGERPRINT,
        )
        self.assertEqual(sender.bundled_shared_private_key_path().resolve(), SHARED_PRIVATE_KEY)

    def test_public_line_is_derived_from_pinned_private_key(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "keys"
            store = sender.KeyStore(root, SHARED_PRIVATE_KEY)
            fields = store.public_key_line.split()
            self.assertGreaterEqual(len(fields), 2)
            derived = paramiko.RSAKey(data=base64.b64decode(fields[1], validate=True))
            self.assertEqual(sender.openssh_sha256_fingerprint(derived), sender.SHARED_KEY_FINGERPRINT)
            self.assertFalse((root / "kindle_sender_rsa").exists())
            self.assertFalse((root / "kindle_sender_rsa.pub").exists())

    def test_authorized_key_identity_ignores_comment(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = sender.KeyStore(Path(temporary) / "keys", SHARED_PRIVATE_KEY)
            key_type, key_blob, _ = store.public_key_line.split(maxsplit=2)
            existing = f"{key_type}\t{key_blob} already-live-on-kindle\n"

            self.assertTrue(
                sender.authorized_keys_contains_identity(existing, store.public_key_line)
            )
            self.assertEqual(
                sender.public_key_identity(existing),
                sender.public_key_identity(store.public_key_line),
            )
            self.assertIsNone(sender.public_key_identity("ssh-rsa not-valid-base64"))

    def test_usb_pairing_does_not_duplicate_same_key_with_other_comment(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "Kindle"
            ssh_directory = root / "koreader" / "settings" / "SSH"
            ssh_directory.mkdir(parents=True)
            store = sender.KeyStore(Path(temporary) / "keys", SHARED_PRIVATE_KEY)
            key_type, key_blob, _ = store.public_key_line.split(maxsplit=2)
            original = f"{key_type} {key_blob} handoff-existing-comment\n"
            authorized_keys = ssh_directory / "authorized_keys"
            authorized_keys.write_text(original, encoding="ascii", newline="\n")

            with mock.patch.object(sender, "find_mounted_kindles", return_value=[root]):
                self.assertEqual(sender.install_public_key_on_usb(store), [root])

            self.assertEqual(authorized_keys.read_text(encoding="ascii"), original)

    def test_remote_install_command_matches_key_fields_not_comment(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = sender.KeyStore(Path(temporary) / "keys", SHARED_PRIVATE_KEY)
            command = sender.authorized_key_install_command(store.public_key_line)

            self.assertIn("awk -v key_type=", command)
            self.assertIn("-v key_blob=", command)
            self.assertIn("$1 == key_type && $2 == key_blob", command)
            self.assertNotIn("grep -F -x", command)

    def test_prior_per_computer_pair_is_moved_to_one_private_backup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "keys"
            root.mkdir(parents=True)
            legacy_private = root / "kindle_sender_rsa"
            legacy_public = root / "kindle_sender_rsa.pub"
            legacy = paramiko.RSAKey.generate(bits=1024)
            legacy.write_private_key_file(str(legacy_private))
            legacy_public.write_text(
                f"{legacy.get_name()} {legacy.get_base64()} old-local-test-key\n",
                encoding="ascii",
            )
            expected_private_hash = file_sha256(legacy_private)
            expected_public_hash = file_sha256(legacy_public)

            output = io.StringIO()
            with redirect_stdout(output), redirect_stderr(output):
                store = sender.KeyStore(root, SHARED_PRIVATE_KEY)
                key = store.ensure()

            self.assertEqual(output.getvalue(), "")
            self.assertEqual(sender.openssh_sha256_fingerprint(key), sender.SHARED_KEY_FINGERPRINT)
            self.assertFalse(legacy_private.exists())
            self.assertFalse(legacy_public.exists())
            backups = list((root / "legacy-key-backups").glob("legacy-*"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(file_sha256(backups[0] / legacy_private.name), expected_private_hash)
            self.assertEqual(file_sha256(backups[0] / legacy_public.name), expected_public_hash)

            store.ensure()
            self.assertEqual(len(list((root / "legacy-key-backups").glob("legacy-*"))), 1)

    def test_unreadable_legacy_files_are_backed_up_without_being_loaded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "keys"
            root.mkdir(parents=True)
            legacy_private = root / "kindle_sender_rsa"
            legacy_public = root / "kindle_sender_rsa.pub"
            legacy_private.write_bytes(b"opaque legacy private test data")
            legacy_public.write_bytes(b"opaque legacy public test data")
            expected = (file_sha256(legacy_private), file_sha256(legacy_public))

            sender.KeyStore(root, SHARED_PRIVATE_KEY).ensure()

            backup = next((root / "legacy-key-backups").glob("legacy-*"))
            self.assertEqual(file_sha256(backup / legacy_private.name), expected[0])
            self.assertEqual(file_sha256(backup / legacy_public.name), expected[1])
            self.assertFalse(legacy_private.exists())
            self.assertFalse(legacy_public.exists())

    def test_bad_shared_asset_fails_before_legacy_key_moves(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "keys"
            root.mkdir(parents=True)
            legacy_private = root / "kindle_sender_rsa"
            legacy = paramiko.RSAKey.generate(bits=1024)
            legacy.write_private_key_file(str(legacy_private))
            bad_shared = Path(temporary) / "wrong-shared-key"
            paramiko.RSAKey.generate(bits=1024).write_private_key_file(str(bad_shared))

            with self.assertRaisesRegex(RuntimeError, "pinned fingerprint"):
                sender.KeyStore(root, bad_shared).ensure()
            self.assertTrue(legacy_private.is_file())
            self.assertFalse((root / "legacy-key-backups").exists())

    def test_build_paths_bundle_only_the_existing_tracked_private_asset(self) -> None:
        self.assertEqual(build.SHARED_KEY.resolve(), SHARED_PRIVATE_KEY)
        self.assertEqual(build.SHARED_KEY_BUNDLE_DIRECTORY, "Handoff/keys")
        spec = (REPOSITORY_ROOT / "app" / "Kindle Book Sender.spec").read_text(encoding="utf-8")
        self.assertIn("kindle_handoff_rsa", spec)
        self.assertIn("Handoff/keys", spec)


if __name__ == "__main__":
    unittest.main()
