# 安装与联动排错

先在游戏关闭时，用 GUI 对一个测试世界执行备份和恢复；成功后再检查游戏内联动。不要用唯一的真实存档做恢复验证。

## 按症状定位

| 症状 | 检查与处理 |
| --- | --- |
| `Python launcher was not found` | 用当前 `setup_windows.bat`；支持 `py -3` 和 `python`。在 CMD 检查 `python --version` 是否至少为 3.10。 |
| `.venv` 提示 `No module named pip` | 当前构建脚本会尝试 `ensurepip` 后重建；仍失败时保留完整安装输出，重点看 Python 安装完整性和依赖下载错误。 |
| Mod 目录有文件但没有 EXE | 两者是不同组件；完整运行 `setup_windows.bat`。Mod 位于 Zomboid 用户目录，EXE 位于 `%LOCALAPPDATA%\ZomboidSaveManager`。 |
| 桌面没有保护启动快捷方式 | 先确认 EXE 存在，再运行 `repair_shortcuts_windows.bat`，查看输出的实际桌面目录；也可运行 `launch_game_protected.bat`。 |
| 模组列表不显示 | 检查安装输出中的根目录清单和 `42\mod.info`；确认游戏实际使用的用户目录及完整版本号。不能仅凭“不显示”推断 Build 分支。 |
| BK 被遮挡或无法点击 | 当前偏移为 x=58，并尝试置顶；其他 UI 模组和缩放仍可能冲突。记录屏幕分辨率、UI 缩放和截图。 |
| BK / F8 能打开窗口但没有备份 | BK / F8 只唤窗。使用 F9 或 GUI 备份按钮。 |
| F9 提示成功但槽位没更新 | 游戏内提示表示请求已写出；核对 GUI 日志、槽位时间、当前世界路径和伴生程序是否运行。 |
| 备份数据库时报 `[WinError 32]` | 完整安装 1.1.8 以更新 EXE；只修复 Mod 不会更新备份核心。若仍报错，保留具体文件名和完整日志。 |
| 退出游戏没有生成快照 | 检查是否通过带 `--exit-with-game` 的入口启动、游戏进程是否被识别、世界路径是否有效。路径无法定位时当前代码可能直接关闭。 |

## 三个诊断文件

在 Windows CMD 执行：

```bat
type "%USERPROFILE%\Zomboid\Lua\ZomboidSaveManager_status.txt"
type "%USERPROFILE%\Zomboid\Lua\ZomboidSaveManager_companion_status.txt"
type "%USERPROFILE%\Zomboid\Lua\ZomboidSaveManager_command.txt"
findstr /I /C:"ZomboidSaveManager" "%USERPROFILE%\Zomboid\console.txt"
```

| 内容示例 | 能证明什么 |
| --- | --- |
| `1.1.8\|lua_loaded\|waiting_for_player` | Lua 曾载入并写出初始状态；不能单独判定按钮完全不存在。 |
| `1.1.8\|ready\|BK/F8/F9` | 按钮创建流程到达完成点；不证明未被其他 UI 遮挡或备份成功。 |
| `1.1.8\|running\|pid=...` | 伴生程序曾写出启动状态；文件可能是上次运行遗留。 |
| `1.1.8\|received\|SHOW:...` | GUI 已处理该 SHOW 请求；仍需观察窗口是否恢复。 |
| `token\|BACKUP_AUTO\|Sandbox\|world-A` | 游戏端已写出备份请求；不代表伴生程序已消费或完成。 |

比较按键前后的内容与文件修改时间。文件不存在也可能与路径、写入权限或日志被清理有关，应结合 `console.txt` 判断。

## 游戏更新后缺字或崩溃

已有反馈描述过游戏更新后主菜单部分文字丢失、进入世界崩溃，但本工程没有对应的完整游戏日志与受控复现记录，原因未确定。历史对话中提到的具体官方版本、公告和故障归因未经本仓库核实，不作为兼容性结论。

1. 退出游戏后另存一份原存档。
2. 记录实际游戏版本与 Steam 分支；禁用全部模组，用新建的测试世界复现。不要直接加载依赖模组的原世界。
3. 若纯净测试正常，再仅启用本桥接模组复测；若仍不正常，检查游戏文件完整性和游戏日志。
4. 提交差异结果及日志中的首个错误。仅移动本地 `mods` 目录不等于禁用了 Steam 创意工坊模组。

## 当前边界

- Build 41 / 42 是代码布局目标，尚无本仓库可复核的完整游戏版本实测矩阵。
- 文件热备份无法保证地图区块和多个数据库之间的事务一致性；游戏关闭后的快照更容易验证。
- 暂停或返回主菜单不代表所有写盘都已停止；恢复前完全退出游戏。
- 自定义 `-cachedir`、非默认用户目录、多人服务器与非 Steam 启动未完成验证。
- 进程识别依赖已知可执行文件名，探测失败不能证明游戏确实已退出。
- 当前工程没有游戏更新兼容性自动修复，也不能修复游戏本体崩溃。
