# 仓库开发约定

本文件适用于整个仓库，供开发者及代码助手在每次任务开始时阅读。具体步骤见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 必须遵守

1. 开始前检查 `git status`、当前分支和远端，保留其他人的未提交改动。远程主干为 `origin/main`。
2. 从最新主干创建任务分支，例如 `feat/save-history`、`fix/sqlite-lock`、`docs/development-workflow`。所有开发、文档和配置修改都在任务分支完成，禁止直接在 `main` 开发或推送提交，禁止强推主干。
3. 每次提交必须提供完整的 Conventional Commit 标题及 `Why:`、`Changes:`、`Validation:`、`Risks:`、`Refs:` 正文。写明实际执行的验证和未完成项；不得用 `update`、`fix bug` 等无上下文消息。格式见 [提交规范](docs/COMMIT_CONVENTION.md)，模板为 [.gitmessage](.gitmessage)。合并提交同样需要完整信息。
4. 每个行为性 bug 修复使用 `fix` 类型，在同一提交中加入修复代码、针对故障的单元回归测试以及 `docs/bugfixes/YYYY-MM-DD-short-name.md`。提交正文用 `Bugfix:` 引用记录路径。记录必须说明**原因、复现步骤、解决方案、单元测试**，并补充影响、验证范围及回滚方法。详情见 [bugfix 流程](docs/bugfixes/README.md)。
5. 提交前执行 Python 编译和全量 `unittest`；测试仅使用临时目录、合成存档与模拟进程。不得对用户真实存档执行测试或恢复操作。
6. 推送任务分支，创建目标为 `main` 的 PR，填写 PR 模板并等相关 CI 全部通过后合并。默认保留分支提交，使用 merge commit；合并后同步本地主干。报告 PR、提交 SHA 和实际验证结果。遇到权限或检查阻塞时说明具体原因，不能绕过检查或声称已合并。
7. 修改行为、接口、安装流程或维护流程时同步相关文档和 `CHANGELOG.md`。历史记录只能补充可核验事实，不得补造发布日期、复现结果或游戏兼容性结论。

## 工程边界

- Python 3.10+，沿用现有标准库 `unittest`；运行目标为 Windows，核心测试同时支持 Linux。
- 备份与恢复逻辑放在 `backup_core.py`，游戏桥接放在 `game_integration.py`，GUI 负责交互与调度。保持后台任务与 Tkinter 主线程的队列边界。
- 两份 `ZSM_Integration.lua` 必须字节一致；发布功能版本时同步 Python、Lua 与两个 `mod.info` 的版本。
- 不提交真实存档、日志、凭据、个人配置、构建产物或虚拟环境。
- 核心测试通过不等于 Windows 安装、Lua 运行或 Build 41 / 42 游戏联动通过；分别记录自动检查与人工验收。
- 不以空测试、源码字符串断言或忽略失败来代替对实际故障的回归验证；既有结构检查可保留。

## 常用验证

```text
python -m py_compile backup_core.py game_integration.py install_windows.py zomboid_save_manager.py start.pyw scripts/check_development_policy.py
python -m unittest discover -s tests -v
python scripts/check_development_policy.py --base origin/main --head HEAD
git diff --check
```

`check_development_policy.py` 在提交后执行，检查主干之外的新增提交；未提交的工作区内容不在该检查范围内。
