from __future__ import annotations

import ctypes
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from backup_core import default_zomboid_saves_root, normalize_path, validate_save_directory


STEAM_GAME_URI = "steam://rungameid/108600"
COMMAND_FILE_NAME = "ZomboidSaveManager_command.txt"
COMPANION_STATUS_FILE_NAME = "ZomboidSaveManager_companion_status.txt"
MUTEX_NAME = "Local\\ZomboidSaveManager-7D9E19A4"
KNOWN_COMMANDS = {"HELLO", "SHOW", "BACKUP_AUTO"}


@dataclass(frozen=True)
class GameCommand:
    token: str
    action: str
    game_mode: str = ""
    save_folder: str = ""


def zomboid_user_root() -> Path:
    home = Path(os.environ.get("USERPROFILE", Path.home()))
    return home / "Zomboid"


def command_file_path() -> Path:
    return zomboid_user_root() / "Lua" / COMMAND_FILE_NAME


def companion_status_file_path() -> Path:
    return zomboid_user_root() / "Lua" / COMPANION_STATUS_FILE_NAME


def parse_command(text: str) -> Optional[GameCommand]:
    line = text.strip().splitlines()[-1] if text.strip() else ""
    fields = line.split("|", 3)
    if len(fields) < 2:
        return None
    token = fields[0].strip()
    action = fields[1].strip().upper()
    if not token or action not in KNOWN_COMMANDS:
        return None
    game_mode = fields[2].strip() if len(fields) >= 3 else ""
    save_folder = fields[3].strip() if len(fields) >= 4 else ""
    return GameCommand(token=token, action=action, game_mode=game_mode, save_folder=save_folder)


def _clean_field(value: str) -> str:
    return value.replace("|", "_").replace("\r", " ").replace("\n", " ").strip()


def write_companion_command(action: str, game_mode: str = "", save_folder: str = "") -> Path:
    action = action.upper()
    if action not in KNOWN_COMMANDS:
        raise ValueError(f"未知联动命令：{action}")
    path = command_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    token = str(time.time_ns())
    text = "|".join((token, action, _clean_field(game_mode), _clean_field(save_folder)))
    temp = path.with_name(path.name + f".{os.getpid()}.tmp")
    temp.write_text(text, encoding="utf-8")
    os.replace(temp, path)
    return path


def write_companion_status(version: str, phase: str, detail: str = "") -> Path:
    path = companion_status_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    safe_detail = _clean_field(detail)
    text = "|".join((version, _clean_field(phase), safe_detail))
    temp = path.with_name(path.name + f".{os.getpid()}.tmp")
    temp.write_text(text, encoding="utf-8")
    os.replace(temp, path)
    return path


class CommandWatcher:
    """Poll the small Lua bridge file and ignore commands left by an older run."""

    def __init__(self, path: Optional[Path] = None, *, ignore_existing: bool = True) -> None:
        self.path = path or command_file_path()
        self._last_text = self._read_text() if ignore_existing else ""
        parsed = parse_command(self._last_text)
        self._last_token = parsed.token if parsed else ""

    def _read_text(self) -> str:
        try:
            return self.path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

    def poll(self) -> Optional[GameCommand]:
        text = self._read_text()
        if not text or text == self._last_text:
            return None
        self._last_text = text
        command = parse_command(text)
        if command is None or command.token == self._last_token:
            return None
        self._last_token = command.token
        return command


class CommandPump:
    """Poll commands independently of Tk and forward them to the GUI queue."""

    def __init__(
        self,
        on_command: Callable[[GameCommand], None],
        watcher: Optional[CommandWatcher] = None,
        *,
        poll_interval: float = 0.15,
        on_error: Optional[Callable[[BaseException], None]] = None,
    ) -> None:
        self.on_command = on_command
        self.watcher = watcher or CommandWatcher()
        self.poll_interval = max(0.05, poll_interval)
        self.on_error = on_error
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="zomboid-command-watcher",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=0.5)

    def _run(self) -> None:
        while not self._stop.wait(self.poll_interval):
            try:
                command = self.watcher.poll()
                if command is not None:
                    self.on_command(command)
            except BaseException as exc:
                if self.on_error is not None:
                    self.on_error(exc)


def _casefold_child(parent: Path, name: str) -> Optional[Path]:
    wanted = name.casefold()
    try:
        for child in parent.iterdir():
            if child.is_dir() and child.name.casefold() == wanted:
                return child
    except OSError:
        return None
    return None


def _safe_candidate(root: Path, relative: str) -> Optional[Path]:
    relative = relative.replace("\\", "/").strip().strip("/")
    if not relative:
        return None
    parts = [part for part in relative.split("/") if part not in {"", "."}]
    if any(part == ".." for part in parts):
        return None
    candidate = (root / Path(*parts)).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate


def resolve_reported_save_directory(
    game_mode: str,
    save_folder: str,
    saves_root: Optional[Path] = None,
) -> Optional[Path]:
    """Resolve getGameMode()/getSaveFolder() values without allowing traversal."""
    root = normalize_path(saves_root or default_zomboid_saves_root())
    folder = save_folder.strip()
    mode = game_mode.strip()
    candidates: list[Path] = []

    if folder:
        raw = Path(folder)
        if raw.is_absolute():
            absolute = raw.resolve()
            try:
                absolute.relative_to(root)
            except ValueError:
                pass
            else:
                candidates.append(absolute)
        direct = _safe_candidate(root, folder)
        if direct is not None:
            candidates.append(direct)
    if mode and folder:
        combined = _safe_candidate(root, f"{mode}/{folder}")
        if combined is not None:
            candidates.insert(0, combined)
        actual_mode = _casefold_child(root, mode)
        if actual_mode is not None:
            actual_folder = _casefold_child(actual_mode, folder.replace("\\", "/").split("/")[-1])
            if actual_folder is not None:
                candidates.insert(0, actual_folder.resolve())

    # Some game builds report only the leaf save folder. Search one level below
    # every game-mode directory as a case-insensitive fallback.
    if folder:
        leaf = folder.replace("\\", "/").split("/")[-1]
        try:
            for mode_dir in root.iterdir():
                if not mode_dir.is_dir():
                    continue
                match = _casefold_child(mode_dir, leaf)
                if match is not None:
                    candidates.append(match.resolve())
        except OSError:
            pass

    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        valid, _ = validate_save_directory(candidate)
        if valid:
            return candidate
    return None


def launch_project_zomboid() -> None:
    if os.name != "nt":
        raise OSError("联动启动器目前只支持 Windows Steam 版")
    os.startfile(STEAM_GAME_URI)  # type: ignore[attr-defined]


def acquire_single_instance() -> tuple[object | None, bool]:
    """Return (handle, already_running). The handle must stay alive."""
    if os.name != "nt":
        return None, False
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if not handle:
        return None, False
    already_running = kernel32.GetLastError() == 183
    return handle, already_running


def release_single_instance(handle: object | None) -> None:
    if os.name == "nt" and handle:
        try:
            ctypes.windll.kernel32.CloseHandle(handle)
        except OSError:
            pass


def bring_tk_window_to_front(root: object) -> None:
    # Kept in this module so all Windows-specific integration has one boundary.
    root.deiconify()
    root.state("normal")
    root.update_idletasks()
    root.lift()
    root.attributes("-topmost", True)
    root.after(250, lambda: root.attributes("-topmost", False))
    root.focus_force()
    if os.name == "nt":
        try:
            hwnd = root.winfo_id()
            ctypes.windll.user32.ShowWindow(hwnd, 9)
            ctypes.windll.user32.SetForegroundWindow(hwnd)
        except OSError:
            pass
