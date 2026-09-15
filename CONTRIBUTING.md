# 贡献与维护流程

目标：每项改动都能追溯动机、实现、验证和回滚方式；每次修复都留下可重复执行的回归测试。

先阅读 [AGENTS.md](AGENTS.md)、[架构](docs/ARCHITECTURE.md) 和 [开发环境与验证](docs/DEVELOPMENT.md)。

## 1. 克隆与本地配置

```text
git clone https://github.com/Sora6A/zomboid-save-manager.git
cd zomboid-save-manager
git config --local commit.template .gitmessage
git config --local pull.ff only
```

确认 `git config user.name` 和 `git config user.email` 属于实际提交者；如需调整，使用仓库级配置。模板与 Git 配置不会随 clone 自动启用，新工作副本需要重新配置。使用 `git commit -m` 会跳过模板展示，但仍须满足完整消息要求。

## 2. 从主干创建分支

确认工作区干净后执行：

```text
git switch main
git pull --ff-only origin main
git switch -c feat/save-history
```

| 改动 | 分支示例 | 提交类型 |
| --- | --- | --- |
| 新功能 | `feat/save-history` | `feat` |
| 行为缺陷修复 | `fix/sqlite-lock` | `fix` |
| 文档 / 维护规范 | `docs/development-workflow` | `docs` / `chore` |
| 重构 / 测试 / CI | `refactor/backup-core`、`test/restore`、`ci/source-checks` | 对应类型 |

一个分支围绕一个任务；不要混入无关重构或格式化。未提交改动应先妥善保存，不能用 reset 或 checkout 覆盖他人的工作。

## 3. 实现与记录

- 功能改动：更新使用方式、架构或维护说明，并按实际行为补充测试。
- bug 修复：按 [bugfix 流程](docs/bugfixes/README.md)，在同一提交交付原因、复现、解决方案、回归测试及记录。先运行测试重现故障，再验证修复使其通过。
- 仅纠正文档文字可使用 `docs`；不得把行为修复标成 `chore` 或 `docs` 来跳过 bugfix 记录。
- 用户可见变化和工程维护变化分别记入 `CHANGELOG.md` 的待发布章节；纯维护改动无需提高应用功能版本。

## 4. 验证与完整提交

执行 [开发文档](docs/DEVELOPMENT.md) 的编译、单元测试及与改动相关的人工验收。记录命令、环境、结果和验证边界。

```text
git diff --check
git diff
git add <本次任务的文件>
git diff --cached
git commit
python scripts/check_development_policy.py --base origin/main --head HEAD
```

`git add` 中的占位符必须换成实际文件。提交正文遵循 [完整提交规范](docs/COMMIT_CONVENTION.md)。需要通过脚本提交时，将完整消息写入临时文件，再执行 `git commit -F <消息文件>`；不要把字面量 `\n` 当成换行。

## 5. 推送、PR 与合并

```text
git push -u origin feat/save-history
```

在 GitHub 创建任务分支 → `main` 的 PR，填写 [.github/PULL_REQUEST_TEMPLATE.md](.github/PULL_REQUEST_TEMPLATE.md)，提供动机、变化、测试、风险、回滚和 bugfix 链接。PR 标题也遵循提交标题格式。

合并条件：

- 已查看完整差异，提交信息齐全，无未处理的检查失败或评审意见。
- `Source checks` 的 Windows/Linux × Python 3.10/3.12 四个任务通过。
- `Development policy` 通过：逐条校验 PR 新增提交，`fix` 提交必须同时包含 bugfix 记录和新增或更新的测试文件。
- 涉及 Windows 安装或游戏内行为时，在 PR 明确写出人工验证结果及尚未验证的部分。

使用 **Create a merge commit** 保留分支历史，并将合并提交的标题与正文改为完整提交格式，`Refs:` 关联 PR。GitHub 自动生成的简短合并消息不满足本项目约定。若选择 squash，最终消息也必须保留全部动机、验证和 bugfix 引用。

主干前进或发生冲突时，在任务分支执行 `git fetch origin`、`git merge --no-commit origin/main`，解决冲突后执行全部相关检查；如产生合并提交，用完整消息提交。只在任务分支解决冲突，然后重新推送并等待 CI。

合并后同步并核实：

```text
git switch main
git pull --ff-only origin main
git status --short --branch
git log -1 --format=fuller
```

保留任务分支以便追溯，确认合并后可按需清理；不得强推 `main` 或重写公开主干历史。

## 6. 远端规则与检查边界

本仓库的 CI 检查 PR 增量，不追溯重写规范引入前的历史提交。它只能验证格式、文件关联与自动测试，原因分析和用例质量仍需查看差异。更改检查脚本或工作流本身时也必须评审。

GitHub 管理员可对 `main` 启用保护规则：要求 PR、要求上述五项状态检查通过、禁止强推和删除。是否强制执行以仓库 Settings 中实际规则为准；提交配置文件不会自动开启远端保护。个人仓库无需强制另一位评审者签字，但合并前仍须检查差异和结果。配置方法见 [GitHub 官方说明](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/managing-a-branch-protection-rule)。

## 7. 发布与回滚

发布前完成 [开发文档](docs/DEVELOPMENT.md) 中的版本同步和 Windows / 游戏验收，填写版本记录。不能将 CI 成功描述为完整游戏兼容。

回滚通过新的任务分支和 PR 完成：使用 `git revert --no-commit <提交>`（合并提交需先确认主线父提交，再使用 `-m 1`），执行相关测试并以完整 `revert` 消息提交。回滚代码不能替代用户数据恢复；涉及数据格式时在 PR 说明兼容性与恢复步骤。
