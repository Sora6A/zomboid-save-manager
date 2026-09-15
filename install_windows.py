from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from pathlib import Path


APP_NAME = "ZomboidSaveManager"
MOD_NAME = "ZomboidSaveManager"


def install_mod(project_root: Path, user_profile: Path) -> Path:
    source = project_root / "mod" / MOD_NAME
    destination = user_profile / "Zomboid" / "mods" / MOD_NAME
    if not source.is_dir():
        raise FileNotFoundError(f"找不到 Mod 源目录：{source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Replace the owned mod directory so stale files from an older layout
    # cannot affect how the game chooses its Build 41/42 entry point.
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination)

    required = (
        destination / "mod.info",
        destination / "media" / "lua" / "client" / "ZSM_Integration.lua",
        destination / "common" / "media" / "lua" / "client" / "ZSM_Integration.lua",
        destination / "42" / "mod.info",
    )
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError("Mod 安装不完整：" + "，".join(missing))
    return destination


def install_companion(project_root: Path, local_app_data: Path) -> Path:
    source = project_root / "dist" / f"{APP_NAME}.exe"
    if not source.is_file():
        raise FileNotFoundError("尚未生成 dist\\ZomboidSaveManager.exe，请先运行 build_exe.bat")
    destination_dir = local_app_data / APP_NAME
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / source.name
    shutil.copy2(source, destination)
    shutil.copy2(project_root / "README.md", destination_dir / "README.md")
    return destination


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def create_shortcuts(executable: Path) -> Path:
    exe = _ps_quote(str(executable))
    working = _ps_quote(str(executable.parent))
    script = f"""
$desktop = [Environment]::GetFolderPath('Desktop')
if ([string]::IsNullOrWhiteSpace($desktop)) {{
    $desktop = Join-Path $env:USERPROFILE 'Desktop'
}}
New-Item -ItemType Directory -Force -Path $desktop | Out-Null
$shell = New-Object -ComObject WScript.Shell
$game = $shell.CreateShortcut((Join-Path $desktop '僵尸毁灭工程（带存档保护）.lnk'))
$game.TargetPath = {exe}
$game.Arguments = '--launch-game --minimized --exit-with-game'
$game.WorkingDirectory = {working}
$game.IconLocation = {exe}
$game.Description = '启动游戏、自动备份，并在退出快照完成后关闭'
$game.Save()
$gameEnglish = $shell.CreateShortcut((Join-Path $desktop 'Project Zomboid - Protected.lnk'))
$gameEnglish.TargetPath = {exe}
$gameEnglish.Arguments = '--launch-game --minimized --exit-with-game'
$gameEnglish.WorkingDirectory = {working}
$gameEnglish.IconLocation = {exe}
$gameEnglish.Description = 'Launch Project Zomboid with automatic save protection'
$gameEnglish.Save()
$manager = $shell.CreateShortcut((Join-Path $desktop '僵尸毁灭工程存档管理器.lnk'))
$manager.TargetPath = {exe}
$manager.WorkingDirectory = {working}
$manager.IconLocation = {exe}
$manager.Description = '打开存档槽位管理器'
$manager.Save()
Write-Output ('DESKTOP=' + $desktop)
"""
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        check=False,
        capture_output=True,
        text=True,
        errors="replace",
    )
    if result.returncode != 0:
        raise OSError(result.stderr.strip() or "PowerShell 创建桌面快捷方式失败")
    marker = next(
        (line for line in result.stdout.splitlines() if line.startswith("DESKTOP=")),
        "",
    )
    if not marker:
        raise OSError("PowerShell 未返回桌面目录，无法确认快捷方式位置")
    desktop = Path(marker.removeprefix("DESKTOP="))
    required = (
        desktop / "僵尸毁灭工程（带存档保护）.lnk",
        desktop / "Project Zomboid - Protected.lnk",
        desktop / "僵尸毁灭工程存档管理器.lnk",
    )
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError("快捷方式创建不完整：" + "，".join(missing))
    return desktop


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="安装僵尸毁灭工程存档管理器")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--mod-only", action="store_true", help="仅重新安装游戏 Mod")
    group.add_argument("--shortcuts-only", action="store_true", help="仅重新创建桌面快捷方式")
    return parser.parse_args()


def main() -> int:
    if os.name != "nt":
        print("此安装脚本只支持 Windows。")
        return 1
    project_root = Path(__file__).resolve().parent
    user_profile = Path(os.environ.get("USERPROFILE", Path.home()))
    local_app_data = Path(os.environ.get("LOCALAPPDATA", user_profile / "AppData" / "Local"))
    args = parse_args()
    try:
        if args.shortcuts_only:
            executable = local_app_data / APP_NAME / f"{APP_NAME}.exe"
            if not executable.is_file():
                raise FileNotFoundError(
                    f"找不到已安装的伴生程序：{executable}，请先运行 setup_windows.bat"
                )
            desktop = create_shortcuts(executable)
            print("桌面快捷方式修复完成。")
            print(f"桌面目录：{desktop}")
            print(f"保护启动：{desktop / '僵尸毁灭工程（带存档保护）.lnk'}")
            print(f"英文备用：{desktop / 'Project Zomboid - Protected.lnk'}")
            return 0

        mod_path = install_mod(project_root, user_profile)
        executable = None
        desktop = None
        if not args.mod_only:
            executable = install_companion(project_root, local_app_data)
            desktop = create_shortcuts(executable)
    except (OSError, shutil.Error) as exc:
        print(f"安装失败：{exc}")
        return 1

    print("Mod 安装完成。" if args.mod_only else "安装完成。")
    print(f"Mod：{mod_path}")
    print(f"Build 41 清单：{mod_path / 'mod.info'}")
    print(f"Build 42 清单：{mod_path / '42' / 'mod.info'}")
    if executable is not None:
        print(f"伴生程序：{executable}")
    if desktop is not None:
        print(f"桌面快捷方式：{desktop}")
    print("请在游戏的“模组”菜单中启用 Zomboid Save Manager Bridge 一次。")
    if executable is not None:
        print("以后使用桌面的“僵尸毁灭工程（带存档保护）”启动游戏。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
