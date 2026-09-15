# Zomboid Save Manager

僵尸毁灭工程存档管理器 · 应用版本 **1.1.8**

Windows companion app and Lua bridge for Project Zomboid save backups.

> 当前状态：个人工具的源码整理版。Build 41 / 42 是布局兼容目标，具体游戏版本、安装与联动仍需实机确认；参见[验证记录](docs/VALIDATION.md)和[已知问题](docs/TROUBLESHOOTING.md)。

文档：[安装与使用](#推荐安装方式mod-联动版) · [架构](docs/ARCHITECTURE.md) · [排错](docs/TROUBLESHOOTING.md) · [开发](docs/DEVELOPMENT.md) · [贡献流程](CONTRIBUTING.md) · [提交规范](docs/COMMIT_CONVENTION.md) · [Bugfix 记录](docs/bugfixes/README.md) · [版本记录](CHANGELOG.md)

这是一个面向 Windows 的《僵尸毁灭工程》存档保护系统，由本地 GUI 伴生程序、游戏内 Mod 和 Steam 联动启动器组成。

它提供：

- 一个自动存档槽，程序运行期间按设定间隔覆盖更新；
- 1～20 个可选的手动存档槽；
- 手动将当前游戏存档备份到指定槽位；
- 将任意非空槽位加载回游戏存档目录；
- 加载前自动生成“恢复前保险槽”；
- 检测游戏进程，避免在游戏运行时恢复存档；
- 先生成完整临时快照，成功后再替换旧槽，避免失败的备份破坏上一份有效备份；
- 对 SQLite 数据库使用在线备份接口，并在普通文件复制后进行一次变化复核。
- 游戏内 `BK` 按钮、`F8` 唤出管理器和 `F9` 快速备份；
- Mod 自动上报当前世界，伴生程序随游戏启动，并在退出快照完成后自动关闭；
- 根目录的 `mod.info + media` 负责 Build 41/旧加载器，`common + 42` 负责 Build 42，用于适配两套模组发现规则，实际加载以游戏测试结果为准。

## 推荐安装方式：Mod 联动版

1. 在 Windows 安装 [Python 3.10 或更高版本](https://www.python.org/downloads/windows/)，安装时勾选 **Add Python to PATH**。
2. 解压完整项目，双击 `setup_windows.bat`。

   安装脚本同时支持 `py -3` 启动器和普通的 `python` 命令。

3. 安装脚本会完成以下工作：

   - 构建独立的 `ZomboidSaveManager.exe`；
   - 把 Mod 安装到 `%USERPROFILE%\Zomboid\mods\ZomboidSaveManager`；
   - 把伴生程序安装到 `%LOCALAPPDATA%\ZomboidSaveManager`；
   - 在桌面创建“僵尸毁灭工程（带存档保护）”和“僵尸毁灭工程存档管理器”两个快捷方式。

4. 第一次进入游戏主菜单，在“模组”中启用 **Zomboid Save Manager Bridge**，此后无需重复启用。
5. 退出游戏，以后都从桌面的“僵尸毁灭工程（带存档保护）”启动。

仅修复同版本 Mod 文件时，请完全退出游戏，解压当前版本后双击 `repair_mod_windows.bat`。它只会替换 `%USERPROFILE%\Zomboid\mods\ZomboidSaveManager`，不会重新构建 EXE，也不会触碰游戏存档。

如果桌面没有“僵尸毁灭工程（带存档保护）”，双击 `repair_shortcuts_windows.bat`。脚本会同时创建中文快捷方式和 `Project Zomboid - Protected` 英文备用快捷方式，并显示 Windows 实际使用的桌面目录。也可以直接双击 `launch_game_protected.bat`，无需桌面快捷方式即可带存档保护启动游戏。

从 1.1.7 或更早版本升级到 1.1.8 时，必须先完全退出游戏和所有 `ZomboidSaveManager.exe` 进程，再运行 `setup_windows.bat`；本次修改了伴生 EXE，只运行 Mod 修复脚本不够。1.1.8 会在关闭 SQLite 目标连接后再替换临时文件，修复 Windows 上备份 `players.db`、`vehicles.db` 时的 `[WinError 32]`。它也包含此前的 `BK` 按钮右移、UI 置顶、后台指令监听和 `.venv`/pip 自动修复。

第一次构建 EXE 需要联网下载 PyInstaller 和 `psutil`。安装脚本会检查虚拟环境中的 pip；发现 `.venv` 创建不完整或缺少 pip 时，会先用 `ensurepip` 修复，必要时自动重建。安装完成后，日常启动不再依赖项目源码，也不用手动先开 Python 程序。

### 联动版的日常行为

- 双击专用快捷方式后，伴生程序隐藏启动，并通过 Steam 启动游戏；
- 世界载入时，Mod 自动告诉伴生程序正在玩的具体存档；
- 左侧的 `BK` 按钮或 `F8` 会把管理器窗口唤到前台；
- `F9` 会立即把当前世界备份到自动槽；
- 设定的周期自动备份仍在后台运行；
- 退出游戏后，伴生程序等待 4 秒，生成一份退出快照，然后自动关闭；
- 退出备份任务报错时会显示窗口和错误；但无法定位有效存档时，当前代码可能记录日志后直接关闭，不能只靠程序退出判断备份成功。

游戏内 Mod 通过 `%USERPROFILE%\Zomboid\Lua\ZomboidSaveManager_command.txt` 发送受限指令。它不能执行任意命令，也不会直接修改世界存档；实际文件操作仍由伴生程序完成。

`F8`/`F9` 需要伴生程序正在运行；请用桌面的“僵尸毁灭工程（带存档保护）”启动，而不是直接从 Steam 点“开始游戏”。`BK` 按钮的创建不依赖伴生程序；是否正常显示与可点击，还取决于游戏加载和 UI 冲突。

Mod 载入成功后会生成 `%USERPROFILE%\Zomboid\Lua\ZomboidSaveManager_status.txt`。正常内容类似 `1.1.8|ready|BK/F8/F9`；若文件不存在，应结合游戏日志检查 Lua 是否加载、文件写入是否成功及实际用户目录。

伴生 EXE 会生成 `%USERPROFILE%\Zomboid\Lua\ZomboidSaveManager_companion_status.txt`。正常启动时内容为 `1.1.8|running|...`，收到 F8 后变为 `1.1.8|received|SHOW:...`，可用于区分游戏端和伴生程序端故障。

## 不安装 Mod，单独运行 GUI

如果只想使用原来的独立程序，可以双击 `run.bat`，然后点击“自动查找”，或者直接选择一个具体世界存档目录，例如：

   `%USERPROFILE%\Zomboid\Saves\Builder\world-A`

请不要只选择上层的 `Saves` 或 `Builder` 文件夹。选择备份位置、保存设置后，保持程序运行再启动游戏。

`psutil` 不是启动 GUI 的硬性依赖；没有安装时，Windows 版会改用系统的 `tasklist` 检查游戏是否仍在运行。

## 手动备份

在槽位列表里选择“自动存档”或任一手动槽位，然后点击“备份到所选槽位”。已有内容时会询问是否覆盖。

自动存档槽始终只保留最近一次成功快照。如果新备份失败，旧快照不会被删除。

## 加载存档

1. 先保存并完全退出《僵尸毁灭工程》。只返回主菜单并不够稳妥。
2. 选择一个非空槽位，点击“加载所选槽位”。
3. 确认目标路径后，程序先把加载前的当前存档写入“恢复前保险槽”，再覆盖游戏存档。
4. 显示加载完成后再启动游戏。

如果需要撤销刚才的加载，可以在游戏仍然关闭时，选择“恢复前保险槽”并加载。加载保险槽本身不会先覆盖这份保险槽。

## 关于游戏运行中的自动备份

程序允许在游戏运行中自动备份，这是本工具的主要用途。它会：

- 尝试复制前后状态一致的文件；
- 对玩家等 SQLite 数据库生成一致快照；
- 完成第一遍复制后，再复核新增、删除或变化的文件。

但《僵尸毁灭工程》的地图区块可能在复制的同时持续写入，任何纯文件级热备份都无法承诺绝对的跨文件事务一致性。较稳妥的用法是把间隔设为 5～15 分钟，并定期在完全退出游戏后做一次手动备份。暂停或返回主菜单不代表所有写盘都已停止。

## 只生成独立 EXE

双击 `build_exe.bat`。脚本会在项目目录创建独立虚拟环境、安装 PyInstaller，并生成：

`dist\ZomboidSaveManager.exe`

该 EXE 可复制到其他 Windows 电脑使用，不要求目标电脑另装 Python。第一次构建需要联网下载依赖。

单独运行 EXE 会打开普通 GUI；添加参数可进入联动模式：

```text
ZomboidSaveManager.exe --launch-game --minimized --exit-with-game
```

## 文件位置

- 程序设置：`%APPDATA%\ZomboidSaveManager\config.json`
- 默认备份：`%USERPROFILE%\Documents\ZomboidSaveManager\Backups`
- 本地 Mod：`%USERPROFILE%\Zomboid\mods\ZomboidSaveManager`
- Mod 指令：`%USERPROFILE%\Zomboid\Lua\ZomboidSaveManager_command.txt`
- 每个槽位的数据：`备份位置\slots\槽位名\data`
- 每个槽位的说明：`备份位置\slots\槽位名\slot_meta.json`

备份里的 `data` 目录是完整世界存档，可在程序无法启动时手动取回。

## 运行测试

在项目目录打开命令提示符：

```bat
python -m py_compile backup_core.py game_integration.py install_windows.py zomboid_save_manager.py start.pyw scripts/check_development_policy.py
python -m unittest discover -s tests -v
```

测试只使用临时目录，不会接触真实游戏存档。

## 参与开发与维护

所有改动从 `main` 创建任务分支，提交完整的原因、改动、验证、风险与关联记录，通过 PR 和 CI 后 merge 到远程 `main`。每个 bug 修复必须在同一提交附带修复代码、单元回归测试和包含原因 / 复现 / 方案 / 测试的 bugfix 文档。开发者和代码助手请先阅读 [AGENTS.md](AGENTS.md) 与 [贡献流程](CONTRIBUTING.md)。

## 重要提醒

- 不要把备份位置设置在当前游戏存档目录内部。
- 恢复时务必完全退出游戏，否则游戏可能再次把内存中的旧状态写回磁盘。
- 游戏运行时按 `F8` 可以管理和备份槽位，但“加载槽位”仍会被禁止；必须先退出游戏再恢复。
- 自动槽不是版本历史，只保留最近一次成功备份；重要节点请另存到手动槽位，并定期把整个备份目录复制到另一块物理磁盘。

## 发布内容与许可

源码仓库包含 Python 程序、Lua Mod、Windows 脚本、测试与文档。历史安装包、虚拟环境、EXE 和个人存档不纳入源码历史。当前尚未选定开源许可证。
