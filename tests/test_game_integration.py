import queue
import tempfile
import unittest
from pathlib import Path

from game_integration import (
    CommandPump,
    CommandWatcher,
    parse_command,
    resolve_reported_save_directory,
)
from install_windows import install_mod


def make_save(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / "map_ver.bin").write_bytes(b"42")
    (path / "players.db").write_bytes(b"not-needed-for-resolution-test")
    return path


class CommandProtocolTests(unittest.TestCase):
    def test_parse_command_with_world_context(self) -> None:
        command = parse_command("123|BACKUP_AUTO|Builder|08-11-2024_10-37-57")
        self.assertIsNotNone(command)
        assert command is not None
        self.assertEqual(command.action, "BACKUP_AUTO")
        self.assertEqual(command.game_mode, "Builder")
        self.assertEqual(command.save_folder, "08-11-2024_10-37-57")

    def test_rejects_unknown_or_malformed_command(self) -> None:
        self.assertIsNone(parse_command(""))
        self.assertIsNone(parse_command("123"))
        self.assertIsNone(parse_command("123|DELETE_EVERYTHING"))

    def test_watcher_ignores_stale_command_and_emits_new_one_once(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "command.txt"
            path.write_text("1|SHOW||", encoding="utf-8")
            watcher = CommandWatcher(path)
            self.assertIsNone(watcher.poll())

            path.write_text("2|BACKUP_AUTO|Sandbox|world-A", encoding="utf-8")
            command = watcher.poll()
            self.assertIsNotNone(command)
            assert command is not None
            self.assertEqual(command.token, "2")
            self.assertIsNone(watcher.poll())

    def test_command_pump_receives_commands_independently(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "command.txt"
            received: queue.Queue = queue.Queue()
            pump = CommandPump(
                received.put,
                CommandWatcher(path),
                poll_interval=0.05,
            )
            pump.start()
            try:
                path.write_text("3|SHOW||", encoding="utf-8")
                command = received.get(timeout=1.0)
            finally:
                pump.stop()
            self.assertEqual(command.action, "SHOW")
            self.assertEqual(command.token, "3")


class SaveResolutionTests(unittest.TestCase):
    def test_resolves_mode_and_folder_case_insensitively(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "Saves"
            expected = make_save(root / "Builder" / "World-A")
            actual = resolve_reported_save_directory("builder", "world-a", root)
            self.assertEqual(actual, expected.resolve())

    def test_resolves_folder_that_already_contains_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "Saves"
            expected = make_save(root / "Sandbox" / "World-B")
            actual = resolve_reported_save_directory("", "Sandbox\\World-B", root)
            self.assertEqual(actual, expected.resolve())

    def test_does_not_allow_parent_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "Saves"
            make_save(Path(temp) / "outside")
            actual = resolve_reported_save_directory("Sandbox", "../../outside", root)
            self.assertIsNone(actual)


class ModPackageTests(unittest.TestCase):
    def test_installer_copies_legacy_and_versioned_bridges(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp:
            destination = install_mod(project_root, Path(temp))
            legacy_bridge = destination / "media" / "lua" / "client" / "ZSM_Integration.lua"
            versioned_bridge = (
                destination / "common" / "media" / "lua" / "client" / "ZSM_Integration.lua"
            )
            self.assertTrue((destination / "mod.info").is_file())
            self.assertTrue((destination / "42" / "mod.info").is_file())
            self.assertTrue(legacy_bridge.is_file())
            self.assertTrue(versioned_bridge.is_file())
            self.assertEqual(legacy_bridge.read_bytes(), versioned_bridge.read_bytes())

    def test_installer_removes_stale_legacy_layout(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp:
            profile = Path(temp)
            old_mod = profile / "Zomboid" / "mods" / "ZomboidSaveManager"
            old_mod.mkdir(parents=True)
            (old_mod / "mod.info").write_text("stale", encoding="utf-8")
            (old_mod / "media").mkdir()
            destination = install_mod(project_root, profile)
            self.assertNotEqual(
                (destination / "mod.info").read_text(encoding="utf-8"),
                "stale",
            )
            self.assertTrue(
                (destination / "media" / "lua" / "client" / "ZSM_Integration.lua").is_file()
            )

    def test_bridge_has_startup_diagnostics_and_retry_events(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        bridge = (
            project_root
            / "mod"
            / "ZomboidSaveManager"
            / "common"
            / "media"
            / "lua"
            / "client"
            / "ZSM_Integration.lua"
        ).read_text(encoding="utf-8")
        self.assertIn("ZomboidSaveManager_status.txt", bridge)
        self.assertIn("Events.OnTick.Add(onTick)", bridge)
        self.assertIn("Events.OnCreatePlayer.Add(requestButton)", bridge)
        self.assertIn("Keyboard.KEY_F8", bridge)
        self.assertIn("_G.ZomboidSaveManagerBridgeLoaded", bridge)
        self.assertIn("buttonPending = true", bridge)
        self.assertIn("buttonOffsetX = 58", bridge)
        self.assertIn("button:bringToTop()", bridge)
        self.assertIn("button:setEnable(true)", bridge)
        self.assertIn("folder = cleanField(world:getWorld())", bridge)
        self.assertIn('writeStatus("lua_loaded", "waiting_for_player")\nrequestButton()', bridge)

    def test_windows_scripts_fall_back_when_py_launcher_is_missing(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        build_script = (project_root / "build_exe.bat").read_text(encoding="utf-8")
        setup_script = (project_root / "setup_windows.bat").read_text(encoding="utf-8")
        run_script = (project_root / "run.bat").read_text(encoding="utf-8")
        repair_script = (project_root / "repair_mod_windows.bat").read_text(encoding="utf-8")
        shortcut_script = (project_root / "repair_shortcuts_windows.bat").read_text(
            encoding="utf-8"
        )
        protected_launcher = (project_root / "launch_game_protected.bat").read_text(
            encoding="utf-8"
        )
        self.assertIn("where python", build_script)
        self.assertIn('set "PYTHON_EXE=python"', build_script)
        self.assertIn('call :validate_venv', build_script)
        self.assertIn('-m ensurepip --upgrade', build_script)
        self.assertIn('-m venv --clear ".venv"', build_script)
        self.assertIn('-m PyInstaller --noconfirm', build_script)
        self.assertIn('".venv\\Scripts\\python.exe" install_windows.py', setup_script)
        self.assertIn("where python", run_script)
        self.assertIn("where python", repair_script)
        self.assertIn("install_windows.py --mod-only", repair_script)
        self.assertIn("where python", shortcut_script)
        self.assertIn("install_windows.py --shortcuts-only", shortcut_script)
        self.assertIn("--launch-game --minimized --exit-with-game", protected_launcher)

    def test_installer_has_verified_shortcut_repair_mode(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        installer = (project_root / "install_windows.py").read_text(encoding="utf-8")
        self.assertIn("--shortcuts-only", installer)
        self.assertIn("Project Zomboid - Protected.lnk", installer)
        self.assertIn("PowerShell 未返回桌面目录", installer)
        self.assertIn("快捷方式创建不完整", installer)

    def test_gui_uses_independent_command_pump_and_status_file(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        gui = (project_root / "zomboid_save_manager.py").read_text(encoding="utf-8")
        integration = (project_root / "game_integration.py").read_text(encoding="utf-8")
        self.assertIn("CommandPump(", gui)
        self.assertIn('self.events.put(("game_command", command))', gui)
        self.assertIn("finally:\n            try:\n                self.root.after(100", gui)
        self.assertIn("ZomboidSaveManager_companion_status.txt", integration)


if __name__ == "__main__":
    unittest.main()
