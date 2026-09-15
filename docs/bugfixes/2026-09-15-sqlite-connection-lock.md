# SQLite 连接未关闭导致 Windows 备份替换失败

## 基本信息

- 记录日期：2026-09-15。
- 状态：1.1.8 既有修复的历史补录；本次维护没有再修改应用实现。
- 影响版本与环境：版本记录将修复列在 1.1.8；旧版本在 Windows 备份 SQLite 数据库时可能出现 `[WinError 32]`。确切首次引入版本和游戏版本未确认。
- 来源：[CHANGELOG](../../CHANGELOG.md)、[backup_core.py](../../backup_core.py) 的 `_copy_sqlite()`、[回归测试](../../tests/test_backup_core.py)。源码导入提交为 `ffb32039d347b7f0b481b8afe64a50142beef015`，它已经包含修复，不能把它当作故障版本。
- 影响范围：`players.db`、`vehicles.db` 等数据库快照，可能使备份任务失败。

## 复现步骤

1. 在可丢弃的 Windows 测试环境中取得修复前实现，创建合成 SQLite 数据库，避免使用真实存档。
2. 完成 SQLite 在线备份，在目标连接仍打开时执行临时文件 `os.replace()`。
3. 观察文件替换结果及连接状态；也可使用现有回归测试中的模拟连接和 Windows 文件锁条件隔离这一触发条件。

- 预期结果：关闭全部数据库连接后成功替换目标文件。
- 实际故障：Windows 可拒绝重命名尚被打开的临时数据库，出现文件占用错误。
- 修复前证据：以上为根据现有实现、注释和测试还原的复现步骤。本轮未取得修复前可执行版本，未运行真实旧版，不声称已完成旧版复现。

## 原因分析

`sqlite3.Connection` 的上下文管理处理事务提交或回滚，不负责关闭连接。若只离开 `with` 块就替换临时数据库，目标连接可能仍持有文件句柄。Windows 的文件锁使这个生命周期问题表现为替换失败；仅在允许替换打开文件的平台测试，可能漏检。

证据是当前 `_copy_sqlite()` 的连接关闭顺序和专门回归测试：测试连接的 `__exit__` 不关闭句柄，模拟替换函数在任意连接未关闭时抛出 `PermissionError`。

## 解决方案

当前实现使用嵌套 `try/finally`，在完成 backup / commit 后显式关闭目标连接，再关闭源连接，随后调用 `copystat()` 和 `os.replace()`。外层 `finally` 尝试清理临时文件。存档与槽位数据格式不变。

升级时需要重新构建和安装伴生 EXE，单独更新 Lua Mod 不会替换 Python 备份核心。

## 单元测试

- 文件：`tests/test_backup_core.py`。
- 用例：`BackupCoreTests.test_sqlite_connections_close_before_windows_style_replace`。
- 仓库根目录命令：

  ```text
  python -m unittest discover -s tests -p test_backup_core.py -k test_sqlite_connections_close_before_windows_style_replace -v
  ```

- 关键断言：任何连接未关闭时模拟 `os.replace()` 拒绝执行；最终断言所有连接关闭且目标字节与源一致。测试使用临时目录和伪造连接，不接触真实存档。
- 修复前：本轮未运行旧版；若删除当前实现中的显式关闭，按测试的模拟条件将抛出占用异常。这是测试设计说明，不是本轮旧版执行记录。
- 修复后：2026-09-15 在 Windows / Python 3.10.9 上运行既有测试，通过。
- 边界：该用例模拟 Windows 替换约束，不能替代真实游戏数据库和系统文件锁验收。

## 验证结果

- 克隆后的 Python 编译：五个应用 / 安装入口通过。
- 克隆后的 `python -m unittest discover -s tests -v`：19 项既有回归测试全部通过。
- 本轮维护新加的策略测试及 CI 结果单独记入 [验证记录](../VALIDATION.md)，不混作本缺陷的历史结果。
- Windows 原生旧版复现、EXE 安装和游戏验收：本次未执行，需按复现步骤另行补验。

## 风险与回滚

此修复不提供多个文件之间的事务一致性，其他程序持有文件句柄等情况仍可能导致替换失败。回滚到未显式关闭连接的版本会重新引入占用风险，不建议作为日常解决办法。若需要撤回相关代码变更，应走独立回滚分支和 PR，保留已成功生成的备份，并在测试世界核对数据库完整性后再使用。
