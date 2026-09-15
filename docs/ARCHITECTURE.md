# 工程结构与数据流

## 模块职责

| 路径 | 职责 |
| --- | --- |
| `start.pyw` | 图形程序入口，调用 `main()` |
| `zomboid_save_manager.py` | Tkinter 窗口、配置、调度、任务队列与操作确认 |
| `backup_core.py` | 世界发现、槽位元数据、文件与 SQLite 快照、恢复与进程探测 |
| `game_integration.py` | 指令解析、后台轮询、世界路径定位、单实例与 Windows 唤窗 |
| `install_windows.py` | 安装 Mod / EXE、创建和验证桌面快捷方式 |
| `mod/ZomboidSaveManager/media/` | 旧版根目录加载入口的 Lua 脚本 |
| `mod/ZomboidSaveManager/common/media/` | 版本化布局共享的同一份 Lua 脚本 |
| `mod/ZomboidSaveManager/42/mod.info` | Build 42 模组清单 |
| `tests/` | 临时存档、备份恢复、指令处理和安装包结构验证 |

保留现有根目录入口，避免改变 Windows 批处理、PyInstaller 和测试的导入路径。两份 Lua 脚本必须保持字节一致，不能单独修改其中一份。

## 游戏与伴生程序通信

Lua 将一条命令写入 `%USERPROFILE%\Zomboid\Lua\ZomboidSaveManager_command.txt`，格式为：

```text
token|action|game_mode|save_folder
```

| action | 来源 | 伴生程序行为 |
| --- | --- | --- |
| `HELLO` | 按钮创建完成 | 尝试选择当前世界并记录连接 |
| `SHOW` | BK / F8 / 再次启动 EXE | 尝试选择当前世界并唤出窗口 |
| `BACKUP_AUTO` | F9 | 非忙碌状态下开始自动槽备份 |

`CommandPump` 默认每 0.15 秒轮询一次，将新命令送入 GUI 队列。GUI 每约 0.1 秒处理队列；备份和恢复在工作线程运行。

该文件是单条覆盖式信箱，不是持久队列；连续快速写入可能覆盖尚未读取的命令。监听器启动时忽略已有命令，避免重放旧请求。Mod 目前没有读取“备份完成”的回执；游戏内提示只能说明请求已写出。

## 快照与恢复

备份先写入槽位旁的临时目录。普通文件检查复制前后的大小与时间戳；SQLite 数据库通过在线备份 API 复制并显式关闭连接。完成第一遍复制后，再复核一遍新增、变化与删除的文件。

快照和元数据成功写完后才替换目标槽。目录替换采用先移动旧目录、再移入新目录、异常时尝试回退的流程；它不是断电级事务，也不提供持续历史版本。

恢复默认先备份当前世界到 `recovery`，再复制所选槽位到世界旁的临时目录并替换。加载 `recovery` 时不先覆盖它自身。游戏进程检查由 GUI 入口执行；直接调用 `restore_from_slot()` 的代码必须自行确保游戏已关闭。

## 配置与数据

默认自动间隔 10 分钟、手动槽 5 个；GUI 可设置 1～1440 分钟和 1～20 个手动槽。

每个槽位包含 `data/` 和 `slot_meta.json`。元数据包含原始存档路径、时间、文件数、体积和复制警告，因此真实备份不适合直接提交到公开仓库。

同一备份根目录中的自动槽、手动槽和保险槽会在不同世界之间共用，并非自动按世界隔离。切换世界前应确认槽位来源，或为各世界配置不同的备份目录。
