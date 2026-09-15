import os
from contextlib import closing
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from backup_core import (
    _copy_sqlite,
    InvalidSaveError,
    backup_to_slot,
    discover_save_directories,
    get_slot_info,
    restore_from_slot,
    slot_data_directory,
)


def write_fake_save(path: Path, label: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "map_ver.bin").write_bytes(b"version-1")
    (path / "map_100_200.bin").write_text(f"chunk-{label}", encoding="utf-8")
    (path / "nested").mkdir(exist_ok=True)
    (path / "nested" / "state.txt").write_text(label, encoding="utf-8")
    with closing(sqlite3.connect(path / "players.db")) as database, database:
        database.execute("CREATE TABLE IF NOT EXISTS player (name TEXT)")
        database.execute("DELETE FROM player")
        database.execute("INSERT INTO player VALUES (?)", (label,))


def read_player(path: Path) -> str:
    with closing(sqlite3.connect(path / "players.db")) as database, database:
        row = database.execute("SELECT name FROM player").fetchone()
    assert row is not None
    return str(row[0])


class BackupCoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.save = self.root / "Zomboid" / "Saves" / "Builder" / "world-A"
        self.backups = self.root / "backup-location"
        write_fake_save(self.save, "original")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_backup_creates_complete_slot_and_metadata(self) -> None:
        info = backup_to_slot(self.save, self.backups, "manual_1")
        data = slot_data_directory(self.backups, "manual_1")

        self.assertTrue(info.exists)
        self.assertGreaterEqual(info.file_count, 4)
        self.assertEqual((data / "nested" / "state.txt").read_text(encoding="utf-8"), "original")
        self.assertEqual(read_player(data), "original")
        self.assertTrue(get_slot_info(self.backups, "manual_1").created_at)

    def test_overwrite_slot_does_not_leave_stale_files(self) -> None:
        backup_to_slot(self.save, self.backups, "auto")
        (self.save / "nested" / "state.txt").unlink()
        (self.save / "new-file.bin").write_bytes(b"new")

        backup_to_slot(self.save, self.backups, "auto")
        data = slot_data_directory(self.backups, "auto")
        self.assertFalse((data / "nested" / "state.txt").exists())
        self.assertEqual((data / "new-file.bin").read_bytes(), b"new")

    def test_restore_replaces_save_and_keeps_pre_restore_recovery(self) -> None:
        backup_to_slot(self.save, self.backups, "manual_1")
        (self.save / "map_100_200.bin").write_text("chunk-current", encoding="utf-8")
        (self.save / "only-current.txt").write_text("keep in recovery", encoding="utf-8")
        with closing(sqlite3.connect(self.save / "players.db")) as database, database:
            database.execute("UPDATE player SET name='current'")

        restored, recovery = restore_from_slot(self.save, self.backups, "manual_1")

        self.assertEqual(restored.slot_id, "manual_1")
        self.assertIsNotNone(recovery)
        self.assertEqual(read_player(self.save), "original")
        self.assertFalse((self.save / "only-current.txt").exists())
        recovery_data = slot_data_directory(self.backups, "recovery")
        self.assertEqual(read_player(recovery_data), "current")
        self.assertEqual((recovery_data / "only-current.txt").read_text(encoding="utf-8"), "keep in recovery")

    def test_discovers_world_but_not_mode_container(self) -> None:
        saves_root = self.root / "Zomboid" / "Saves"
        found = discover_save_directories(saves_root)
        self.assertEqual(found, [self.save.resolve()])

    def test_rejects_backup_location_inside_save(self) -> None:
        with self.assertRaises(InvalidSaveError):
            backup_to_slot(self.save, self.save / "bad-backups", "auto")

    def test_sqlite_connections_close_before_windows_style_replace(self) -> None:
        source = self.save / "players.db"
        destination = self.root / "copied" / "players.db"
        connections = []

        class FakeConnection:
            def __init__(self) -> None:
                self.closed = False

            def __enter__(self):
                return self

            def __exit__(self, *_args) -> bool:
                # Match sqlite3.Connection: leaving a with block does not close.
                return False

            def backup(self, target, **_kwargs) -> None:
                target.output_path.write_bytes(source.read_bytes())

            def commit(self) -> None:
                pass

            def close(self) -> None:
                self.closed = True

        def fake_connect(database, *_args, **_kwargs):
            connection = FakeConnection()
            if not str(database).startswith("file:"):
                connection.output_path = Path(database)
            connections.append(connection)
            return connection

        real_replace = os.replace

        def windows_style_replace(source_path, destination_path) -> None:
            if any(not connection.closed for connection in connections):
                raise PermissionError(32, "另一个程序正在使用此文件")
            real_replace(source_path, destination_path)

        with (
            mock.patch("backup_core.sqlite3.connect", side_effect=fake_connect),
            mock.patch("backup_core.os.replace", side_effect=windows_style_replace),
        ):
            _copy_sqlite(source, destination)

        self.assertTrue(all(connection.closed for connection in connections))
        self.assertEqual(destination.read_bytes(), source.read_bytes())


if __name__ == "__main__":
    unittest.main()
