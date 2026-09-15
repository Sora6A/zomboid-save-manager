# 开发与验证

开发流程以 [CONTRIBUTING.md](../CONTRIBUTING.md) 和 [AGENTS.md](../AGENTS.md) 为准：在任务分支开发，完整提交，经 PR / CI 后合并到远程 `main`。行为修复必须同步 [bugfix 记录](bugfixes/README.md) 与单元回归测试。

## 环境与入口

运行目标为 Windows + Python 3.10 或更新版本（含 Tkinter）。核心测试可在 Linux 执行；Linux 通过不代表 Windows 安装与游戏内联动已经通过。

```bat
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python start.pyw
```

`psutil` 用于进程探测；未安装时 Windows 代码会回退到 `tasklist`。`build_exe.bat` 另外安装 PyInstaller，生成 `dist\ZomboidSaveManager.exe`。依赖使用范围约束，当前不保证不同日期的构建字节可重现。

## 提交前检查

```text
python -m py_compile backup_core.py game_integration.py install_windows.py zomboid_save_manager.py start.pyw scripts/check_development_policy.py
python -m unittest discover -s tests -v
```

必须同时执行编译与测试。部分现有用例只检查源码字符串或包结构，即使 GUI 入口被截断，它们也可能通过；编译检查能捕获这类语法损坏。

测试只使用临时目录与伪造世界数据，不读写真实存档。数据库测试夹具显式关闭连接，以免 Windows 拒绝临时目录清理和恢复过程中的重命名。

CI 在 Windows/Linux、Python 3.10/3.12 上执行上述检查。配置参考 GitHub 官方 [checkout](https://github.com/actions/checkout) 与 [setup-python](https://github.com/actions/setup-python) 文档；CI 运行结果以仓库 Actions 记录为准。

完成提交后另行运行提交策略检查：

```text
python scripts/check_development_policy.py --base origin/main --head HEAD
git diff --check
```

PR 的 `Development policy` 会逐条检查新增提交的完整正文，并检查 `fix` 提交是否同时修改测试和对应 bugfix 记录。使用 `git fetch origin` 保持比较基线最新；历史导入提交不追溯整改。策略脚本使用标准库和 Git，不需要安装 Python 第三方包。

## 编码与测试约定

- Python 使用 4 空格缩进、UTF-8、LF 换行；批处理使用 CRLF，遵循 `.editorconfig` 和 `.gitattributes`。公共逻辑提供类型标注，注释解释设计原因。
- 保留当前根目录入口与模块分工。业务逻辑优先放入核心模块，以便脱离 GUI 和游戏进行测试；Tkinter 操作在主线程执行。
- 明确关闭数据库与文件句柄；覆盖旧槽位前先完整构建临时快照，异常时保留最后一份有效备份。涉及删除、覆盖与恢复时提供针对失败路径的测试。
- 文件操作使用 `pathlib.Path`；新增路径入口检查目录边界。日志应保留足够的故障上下文，示例不包含个人路径。
- 采用 `unittest`、`TemporaryDirectory` 和 `mock`。验证行为、数据及错误路径；不要仅根据源码包含某个字符串证明 bug 已修复。
- 依赖变更说明用途、兼容范围和构建影响；本项目尚未锁定构建依赖，不宣称字节可重现构建。
- 缺陷回归应记录修复前失败与修复后通过；无法执行的环境如实记录。完整示例见 [SQLite 文件锁记录](bugfixes/2026-09-15-sqlite-connection-lock.md)。

## Mod 与版本维护

- 两份 `ZSM_Integration.lua` 必须同步修改，安装包测试会比较其内容。
- 功能版本更新时，同步 GUI 的 `APP_VERSION`、两份 Lua 的 `version` 和两个 `mod.info` 的 `modversion`。
- Lua 的独立语法解析只能验证语法；PZ API、事件时机和 UI 行为仍须游戏实测。
- 不提交 `.venv`、EXE、压缩包、游戏存档、日志或含个人路径的运行时配置。

## Windows / 游戏人工验收

在测试用户目录和可丢弃的测试世界进行，记录操作系统、Python、游戏完整版本及模组列表。

1. 完整安装并检查 EXE、两套 Mod 入口、中文/英文快捷方式。
2. 模拟没有 `py.exe`、残缺 `.venv` 和缺失 pip 的安装场景。
3. 关闭游戏，测试自动槽、手动槽、覆盖、恢复及保险槽回滚，核对数据库和文件内容。
4. 入世界检查 BK 的位置和点击；隐藏管理器后测试 F8 和 F9，并核对槽位时间与 GUI 日志。
5. 游戏运行时确认 GUI 阻止恢复；退出游戏后核对退出快照。
6. 单独验证 Build 41 / 42、UI 缩放和其他模组冲突，记录失败结果。

在这些步骤完成前，不将源码测试通过描述为“游戏兼容已确认”。
