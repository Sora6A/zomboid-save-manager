# 整理基线与验证记录

本文件按日期保留验证记录，各节中的结果与未完成项仅对应当次验证。应用功能版本：1.1.8。

## 开发流程建设（2026-09-15）

基线提交：`ffb32039d347b7f0b481b8afe64a50142beef015`。本次在 `docs/development-workflow` 分支完善维护文档、模板、编辑器约定及开发规范 CI，未修改应用和 Lua 实现。

本地环境：Windows，Python 3.10.9，Git；所有测试在临时目录运行。

| 检查 | 结果 | 范围 |
| --- | --- | --- |
| Python 编译 | 通过 | 五个应用 / 安装入口与 `scripts/check_development_policy.py` |
| `python -m unittest discover -s tests -v` | 34 项通过 | 原有 19 项回归测试 + 15 项开发规范测试 |
| 开发规范测试 | 通过 | 完整提交、空字段 / 占位符、fix 记录与测试同提交、多记录、历史基线豁免、逐提交检查、读取提交中的记录、删除测试不能抵作新增回归 |
| 两份 CI YAML 解析 | 通过 | Source checks 与 Development policy；解析不代替远端执行 |
| Markdown 相对文件链接 | 通过 | 新旧文档中全部本地文件目标存在；不包含在线链接和标题锚点验证 |
| `git diff --check` | 通过 | 空白与补丁格式 |

复核命令：

```text
python -m py_compile backup_core.py game_integration.py install_windows.py zomboid_save_manager.py start.pyw scripts/check_development_policy.py
python -m unittest discover -s tests -v
python scripts/check_development_policy.py --base origin/main --head HEAD
git diff --check
```

提交范围检查应在任务分支提交后、合并前执行。GitHub CI 的实际结果以本次维护 PR 的 Checks 和 [Actions](https://github.com/Sora6A/zomboid-save-manager/actions) 为准；此处列出的是本地验证证据。

本次未执行 EXE 构建、原生安装、Lua 独立语法检查或游戏内 Build 41 / 42 验收，不能据此扩展游戏兼容性结论。既有 SQLite 缺陷的历史补录见 [bugfix 记录](bugfixes/2026-09-15-sqlite-connection-lock.md)。

## 原始整理基线（2026-09-13）

### 来源与改动范围

源码恢复自保存完整的 `ZomboidSaveManager-v1.1.8.zip`，原包 SHA-256：

```text
d8c197b6fbed4d14b6ac391cb22a6c764aa4a291404713e28c6c628782a4af49
```

整理时发现另一个工作副本的 `zomboid_save_manager.py` 在 `_write_companion_status` 定义后被截断，缺少后续方法和启动入口。本仓库使用完整包中的文件；保留原包以便追溯，不将损坏副本作为发布基线。

应用、Lua、安装器、启动脚本和运行依赖共 16 个文件与完整包逐字节一致。变动仅为文档与仓库配置，以及测试夹具中 SQLite 连接的显式关闭。

### 本地结果

| 检查 | 结果 | 范围 |
| --- | --- | --- |
| Python 编译 | 通过 | 五个程序 / 安装入口，包括 `start.pyw` |
| 既有回归测试 | 19 项通过 | 临时世界备份恢复、Windows 文件锁模拟、指令轮询、目录解析及安装结构 |
| Python 3.10 语法解析 | 通过 | 应用与测试源码；运行环境实际为 Linux / Python 3.12.14 |
| 两份 Lua 一致性 | 通过 | 由安装包测试比较字节 |
| CI YAML 解析 | 通过 | Windows/Linux × Python 3.10/3.12 配置 |
| 公开内容检查 | 未发现凭据或真实存档 | 移除文档中的个人用户名示例；检查候选文件清单与常见密钥模式 |

### 当时尚未完成

- Windows 原生安装、EXE 构建、桌面快捷方式与真实文件锁测试。
- 本轮未执行独立 Lua 语法解析，也未在游戏中运行 Lua。
- Build 41 / 42 的具体版本联动、窗口唤醒与恢复后的世界加载测试。
- GitHub Actions 的远端运行；工作流配置不等于远端已通过。

上述验证结果不能证明游戏更新后的兼容性或热备份的跨文件事务一致性。
