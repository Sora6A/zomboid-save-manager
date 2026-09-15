from __future__ import annotations

import csv
import json
import os
import re
import shutil
import sqlite3
import subprocess
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable, Optional


APP_NAME = "ZomboidSaveManager"
DATA_DIR_NAME = "data"
META_FILE_NAME = "slot_meta.json"
VALID_SLOT_ID = re.compile(r"^(auto|recovery|manual_[1-9][0-9]*)$")
SAVE_MARKERS = {
    "map_ver.bin",
    "map_p.bin",
    "map_t.bin",
    "players.db",
    "vehicles.db",
}
GAME_EXECUTABLES = {
    "projectzomboid.exe",
    "projectzomboid32.exe",
    "projectzomboid64.exe",
}

ProgressCallback = Callable[[int, int, str], None]


class SaveManagerError(RuntimeError):
    pass


class InvalidSaveError(SaveManagerError):
    pass


class BackupError(SaveManagerError):
    pass


class RestoreError(SaveManagerError):
    pass


@dataclass(frozen=True)
class SlotInfo:
    slot_id: str
    display_name: str
    exists: bool
    created_at: str = ""
    source_path: str = ""
    file_count: int = 0
    total_size: int = 0
    warnings: tuple[str, ...] = ()


def default_zomboid_saves_root() -> Path:
    home = Path(os.environ.get("USERPROFILE", Path.home()))
    return home / "Zomboid" / "Saves"


def default_backup_root() -> Path:
    home = Path(os.environ.get("USERPROFILE", Path.home()))
    documents = home / "Documents"
    return documents / APP_NAME / "Backups"


def config_path() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home()))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / APP_NAME / "config.json"


def load_json(path: Path, default: dict) -> dict:
    try:
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
        return value if isinstance(value, dict) else default.copy()
    except (OSError, ValueError, TypeError):
        return default.copy()


def save_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    with temp.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)


def normalize_path(value: str | os.PathLike[str]) -> Path:
    return Path(value).expanduser().resolve()


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def validate_save_directory(path: str | os.PathLike[str]) -> tuple[bool, str]:
    save_path = normalize_path(path)
    if not save_path.exists():
        return False, "存档目录不存在"
    if not save_path.is_dir():
        return False, "所选路径不是文件夹"
    try:
        names = {entry.name.lower() for entry in save_path.iterdir() if entry.is_file()}
    except OSError as exc:
        return False, f"无法读取存档目录：{exc}"
    if names.intersection(SAVE_MARKERS):
        return True, ""
    return False, "该目录不像一个具体的《僵尸毁灭工程》世界存档（未找到 map_ver.bin、players.db 等文件）"


def discover_save_directories(root: str | os.PathLike[str]) -> list[Path]:
    """Find concrete world directories without recursively walking chunk files."""
    root_path = normalize_path(root)
    if not root_path.is_dir():
        return []

    found: list[Path] = []
    candidates: list[Path] = [root_path]
    try:
        first_level = [p for p in root_path.iterdir() if p.is_dir()]
    except OSError:
        return []
    candidates.extend(first_level)
    for mode_dir in first_level:
        try:
            candidates.extend(p for p in mode_dir.iterdir() if p.is_dir())
        except OSError:
            continue

    for candidate in candidates:
        valid, _ = validate_save_directory(candidate)
        if valid:
            found.append(candidate)

    def newest_mtime(path: Path) -> int:
        try:
            return path.stat().st_mtime_ns
        except OSError:
            return 0

    return sorted(set(found), key=newest_mtime, reverse=True)


def validate_slot_id(slot_id: str) -> None:
    if not VALID_SLOT_ID.fullmatch(slot_id):
        raise ValueError(f"非法槽位 ID：{slot_id}")


def slot_directory(backup_root: str | os.PathLike[str], slot_id: str) -> Path:
    validate_slot_id(slot_id)
    return normalize_path(backup_root) / "slots" / slot_id


def slot_data_directory(backup_root: str | os.PathLike[str], slot_id: str) -> Path:
    return slot_directory(backup_root, slot_id) / DATA_DIR_NAME


def _display_name_for(slot_id: str) -> str:
    if slot_id == "auto":
        return "自动存档"
    if slot_id == "recovery":
        return "恢复前保险槽"
    return f"手动槽位 {slot_id.split('_', 1)[1]}"


def get_slot_info(backup_root: str | os.PathLike[str], slot_id: str) -> SlotInfo:
    directory = slot_directory(backup_root, slot_id)
    data_dir = directory / DATA_DIR_NAME
    metadata = load_json(directory / META_FILE_NAME, {})
    if not data_dir.is_dir():
        return SlotInfo(slot_id, _display_name_for(slot_id), False)
    warnings = metadata.get("warnings", [])
    if not isinstance(warnings, list):
        warnings = []
    return SlotInfo(
        slot_id=slot_id,
        display_name=str(metadata.get("display_name") or _display_name_for(slot_id)),
        exists=True,
        created_at=str(metadata.get("created_at", "")),
        source_path=str(metadata.get("source_path", "")),
        file_count=int(metadata.get("file_count", 0) or 0),
        total_size=int(metadata.get("total_size", 0) or 0),
        warnings=tuple(str(item) for item in warnings),
    )


def list_slot_infos(backup_root: str | os.PathLike[str], manual_slots: int) -> list[SlotInfo]:
    ids = ["auto"] + [f"manual_{number}" for number in range(1, manual_slots + 1)] + ["recovery"]
    return [get_slot_info(backup_root, slot_id) for slot_id in ids]


def _iter_files(root: Path) -> Iterable[tuple[Path, Path]]:
    for current, dir_names, file_names in os.walk(root, followlinks=False):
        dir_names.sort()
        file_names.sort()
        current_path = Path(current)
        for file_name in file_names:
            source = current_path / file_name
            if source.is_symlink():
                continue
            yield source, source.relative_to(root)


def _looks_like_sqlite(path: Path) -> bool:
    if path.suffix.lower() not in {".db", ".sqlite", ".sqlite3"}:
        return False
    try:
        with path.open("rb") as handle:
            return handle.read(16) == b"SQLite format 3\x00"
    except OSError:
        return False


def _copy_sqlite(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = destination.with_name(destination.name + f".{uuid.uuid4().hex}.part")
    try:
        source_uri = source.resolve().as_uri() + "?mode=ro"
        source_db = sqlite3.connect(source_uri, uri=True, timeout=2.0)
        try:
            destination_db = sqlite3.connect(str(temp), timeout=2.0)
            try:
                source_db.backup(destination_db, pages=256, sleep=0.03)
                destination_db.commit()
            finally:
                # sqlite3.Connection.__exit__ only commits or rolls back; it does
                # not close the file handle. Windows refuses os.replace() while
                # the destination database is still open.
                destination_db.close()
        finally:
            source_db.close()
        shutil.copystat(source, temp)
        os.replace(temp, destination)
    finally:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass


def _copy_file_stable(
    source: Path,
    destination: Path,
    *,
    sqlite_consistent: bool,
    attempts: int = 3,
) -> bool:
    destination.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(attempts):
        before = source.stat()
        try:
            if sqlite_consistent and _looks_like_sqlite(source):
                _copy_sqlite(source, destination)
            else:
                temp = destination.with_name(destination.name + f".{uuid.uuid4().hex}.part")
                try:
                    shutil.copy2(source, temp)
                    os.replace(temp, destination)
                finally:
                    try:
                        temp.unlink(missing_ok=True)
                    except OSError:
                        pass
        except (OSError, sqlite3.Error):
            if attempt + 1 >= attempts:
                raise
            time.sleep(0.15 * (attempt + 1))
            continue
        after = source.stat()
        if (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns):
            return True
        time.sleep(0.15 * (attempt + 1))
    return False


def _snapshot_stats(root: Path) -> tuple[int, int]:
    count = 0
    size = 0
    for path, _ in _iter_files(root):
        try:
            count += 1
            size += path.stat().st_size
        except OSError:
            continue
    return count, size


def copy_snapshot(
    source: Path,
    destination: Path,
    *,
    progress: Optional[ProgressCallback] = None,
    sqlite_consistent: bool = True,
) -> list[str]:
    """Copy a save and reconcile one more pass for files changed during copying."""
    destination.mkdir(parents=True, exist_ok=False)
    initial_files = list(_iter_files(source))
    total = max(len(initial_files), 1)
    warnings: list[str] = []
    errors: list[str] = []

    for index, (source_file, relative) in enumerate(initial_files, start=1):
        try:
            stable = _copy_file_stable(
                source_file,
                destination / relative,
                sqlite_consistent=sqlite_consistent,
            )
            if not stable:
                warnings.append(f"复制时持续变化：{relative}")
        except OSError as exc:
            errors.append(f"{relative}: {exc}")
        except sqlite3.Error as exc:
            errors.append(f"{relative}: SQLite 备份失败：{exc}")
        if progress:
            progress(index, total, str(relative))

    # A reconciliation pass catches new chunk files and most files modified while
    # the initial scan was being copied. It also removes files deleted meanwhile.
    try:
        current = {relative: path for path, relative in _iter_files(source)}
        copied = {relative: path for path, relative in _iter_files(destination)}
        for relative, source_file in current.items():
            destination_file = destination / relative
            needs_copy = relative not in copied
            if not needs_copy:
                try:
                    source_stat = source_file.stat()
                    destination_stat = destination_file.stat()
                    needs_copy = (source_stat.st_size, source_stat.st_mtime_ns) != (
                        destination_stat.st_size,
                        destination_stat.st_mtime_ns,
                    )
                except OSError:
                    needs_copy = True
            if needs_copy:
                try:
                    stable = _copy_file_stable(
                        source_file,
                        destination_file,
                        sqlite_consistent=sqlite_consistent,
                    )
                    if not stable:
                        warnings.append(f"复核时仍在变化：{relative}")
                except (OSError, sqlite3.Error) as exc:
                    errors.append(f"复核 {relative}: {exc}")
        for relative, copied_file in copied.items():
            if relative not in current:
                try:
                    copied_file.unlink()
                except OSError as exc:
                    errors.append(f"清理 {relative}: {exc}")
    except OSError as exc:
        errors.append(f"复核存档失败：{exc}")

    if errors:
        preview = "；".join(errors[:5])
        if len(errors) > 5:
            preview += f"；另有 {len(errors) - 5} 个错误"
        raise BackupError(preview)
    return warnings


def _atomic_replace_directory(staging: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    old = target.parent / f".old-{target.name}-{uuid.uuid4().hex}"
    had_target = target.exists()
    if had_target:
        os.replace(target, old)
    try:
        os.replace(staging, target)
    except BaseException:
        if had_target and old.exists() and not target.exists():
            os.replace(old, target)
        raise
    if old.exists():
        shutil.rmtree(old, ignore_errors=True)


def backup_to_slot(
    source: str | os.PathLike[str],
    backup_root: str | os.PathLike[str],
    slot_id: str,
    *,
    display_name: str = "",
    progress: Optional[ProgressCallback] = None,
) -> SlotInfo:
    validate_slot_id(slot_id)
    source_path = normalize_path(source)
    root_path = normalize_path(backup_root)
    valid, reason = validate_save_directory(source_path)
    if not valid:
        raise InvalidSaveError(reason)
    if _is_relative_to(root_path, source_path):
        raise InvalidSaveError("备份保存位置不能放在游戏存档目录内部，否则会无限递归")

    slots_root = root_path / "slots"
    slots_root.mkdir(parents=True, exist_ok=True)
    staging = slots_root / f".tmp-{slot_id}-{uuid.uuid4().hex}"
    data_dir = staging / DATA_DIR_NAME
    try:
        staging.mkdir(parents=False, exist_ok=False)
        warnings = copy_snapshot(source_path, data_dir, progress=progress, sqlite_consistent=True)
        file_count, total_size = _snapshot_stats(data_dir)
        created_at = datetime.now().astimezone().isoformat(timespec="seconds")
        metadata = {
            "format_version": 1,
            "slot_id": slot_id,
            "display_name": display_name or _display_name_for(slot_id),
            "created_at": created_at,
            "source_path": str(source_path),
            "file_count": file_count,
            "total_size": total_size,
            "warnings": warnings,
        }
        save_json(staging / META_FILE_NAME, metadata)
        _atomic_replace_directory(staging, slot_directory(root_path, slot_id))
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return get_slot_info(root_path, slot_id)


def restore_from_slot(
    source: str | os.PathLike[str],
    backup_root: str | os.PathLike[str],
    slot_id: str,
    *,
    progress: Optional[ProgressCallback] = None,
    create_recovery: bool = True,
) -> tuple[SlotInfo, Optional[SlotInfo]]:
    validate_slot_id(slot_id)
    if slot_id == "recovery" and create_recovery:
        # Do not overwrite the only recovery copy with the state being replaced.
        create_recovery = False

    source_path = normalize_path(source)
    root_path = normalize_path(backup_root)
    slot_info = get_slot_info(root_path, slot_id)
    slot_data = slot_data_directory(root_path, slot_id)
    if not slot_info.exists or not slot_data.is_dir():
        raise RestoreError("所选槽位没有可加载的备份")
    valid, reason = validate_save_directory(source_path)
    if not valid:
        raise InvalidSaveError(f"当前游戏存档不可用：{reason}")

    recovery_info: Optional[SlotInfo] = None
    if create_recovery:
        recovery_info = backup_to_slot(
            source_path,
            root_path,
            "recovery",
            display_name="恢复前保险槽",
            progress=progress,
        )

    parent = source_path.parent
    staging = parent / f".{source_path.name}.restore-{uuid.uuid4().hex}"
    old = parent / f".{source_path.name}.old-{uuid.uuid4().hex}"
    try:
        copy_snapshot(slot_data, staging, progress=progress, sqlite_consistent=False)
        os.replace(source_path, old)
        try:
            os.replace(staging, source_path)
        except BaseException:
            os.replace(old, source_path)
            raise
        shutil.rmtree(old, ignore_errors=True)
    except BaseException as exc:
        shutil.rmtree(staging, ignore_errors=True)
        if old.exists() and not source_path.exists():
            try:
                os.replace(old, source_path)
            except OSError:
                pass
        if isinstance(exc, SaveManagerError):
            raise
        raise RestoreError(str(exc)) from exc
    return slot_info, recovery_info


def running_game_processes() -> list[str]:
    names: set[str] = set()
    try:
        import psutil  # type: ignore

        for process in psutil.process_iter(["name"]):
            name = (process.info.get("name") or "").lower()
            if name in GAME_EXECUTABLES:
                names.add(process.info.get("name") or name)
        return sorted(names)
    except Exception:
        pass

    if os.name != "nt":
        return []
    try:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        result = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=5,
            creationflags=flags,
            check=False,
        )
        for row in csv.reader(result.stdout.splitlines()):
            if row and row[0].lower() in GAME_EXECUTABLES:
                names.add(row[0])
    except (OSError, subprocess.SubprocessError):
        return []
    return sorted(names)


def format_size(size: int) -> str:
    value = float(max(size, 0))
    units = ["B", "KB", "MB", "GB", "TB"]
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"
