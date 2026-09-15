"""Validate the complete commit messages and bugfix evidence in a Git range."""

import argparse
import re
import subprocess
from collections.abc import Callable
from pathlib import Path


SUBJECT = re.compile(
    r"(?P<type>feat|fix|docs|refactor|test|ci|build|perf|style|chore|revert)"
    r"(?:\([a-z0-9][a-z0-9_./-]*\))?!?: \S.*"
)
FIELDS = ("Why", "Changes", "Validation", "Risks", "Refs")
BUGFIX_SECTIONS = (
    "基本信息", "复现步骤", "原因分析", "解决方案", "单元测试", "验证结果", "风险与回滚",
)
BUGFIX_PATH = re.compile(r"docs/bugfixes/\d{4}-\d{2}-\d{2}-[a-z0-9]+(?:-[a-z0-9]+)*\.md")
TEST_PATH = re.compile(r"tests/(?:[^/]+/)*test_[^/]+\.py")


def has_content(value: str) -> bool:
    """Ignore template comments and reject unfilled placeholder-only content."""
    value = re.sub(r"<!--.*?-->", "", value, flags=re.DOTALL)
    lines = [line for line in value.splitlines() if not line.lstrip().startswith("#")]
    value = "\n".join(lines).strip()
    if not value or re.search(r"<[^>\n]+>", value):
        return False
    return value.strip("- *\t\r\n").upper() not in {"TODO", "TBD", "待填写", "..."}


def split_sections(text: str, pattern: str) -> dict[str, list[str]]:
    matches = list(re.finditer(pattern, text, flags=re.MULTILINE))
    sections: dict[str, list[str]] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections.setdefault(match.group(1), []).append(text[match.end():end].strip())
    return sections


def validate_commit(
    message: str, changed_files: set[str], read_file: Callable[[str], str],
) -> list[str]:
    errors = []
    lines = message.strip().splitlines()
    subject = SUBJECT.fullmatch(lines[0]) if lines else None
    if subject is None:
        errors.append("标题必须为 type(scope): 具体摘要，type 见 docs/COMMIT_CONVENTION.md")
    if len(lines) < 3 or lines[1].strip():
        errors.append("标题与正文之间必须有一个空行")

    sections = split_sections("\n".join(lines[2:]), r"^([A-Za-z][A-Za-z -]*):[ \t]*")
    for field in FIELDS:
        values = sections.get(field, [])
        if len(values) != 1 or not has_content(values[0]):
            errors.append(f"{field}: 必须出现一次并填写具体内容")

    if subject is None or subject.group("type") != "fix":
        return errors

    records = sections.get("Bugfix", [])
    if not records:
        errors.append("fix 提交缺少 Bugfix: docs/bugfixes/YYYY-MM-DD-short-name.md")
    if not any(TEST_PATH.fullmatch(path) for path in changed_files):
        errors.append("fix 提交必须在同一提交新增或修改 tests/test_*.py 单元回归测试")
    for path in records:
        if not BUGFIX_PATH.fullmatch(path):
            errors.append(f"Bugfix 路径格式无效：{path}")
            continue
        if path not in changed_files:
            errors.append(f"fix 提交必须同时新增或更新记录：{path}")
            continue
        try:
            record = read_file(path)
        except (OSError, subprocess.CalledProcessError) as error:
            errors.append(f"无法读取 bugfix 记录 {path}：{error}")
            continue
        headings = split_sections(record, r"^## ([^\r\n]+)[\r\n]+")
        for heading in BUGFIX_SECTIONS:
            values = headings.get(heading, [])
            if len(values) != 1 or not has_content(values[0]):
                errors.append(f"{path} 的章节“{heading}”必须出现一次并填写具体内容")
    return errors


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", f"safe.directory={repo.resolve().as_posix()}", *args],
        cwd=repo, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8",
    ).stdout


def check_range(repo: Path, base: str, head: str) -> tuple[int, list[str]]:
    # Resolve refs first, so revision expressions and file reads use commit IDs.
    base_sha = git(repo, "rev-parse", "--verify", "--end-of-options", f"{base}^{{commit}}").strip()
    head_sha = git(repo, "rev-parse", "--verify", "--end-of-options", f"{head}^{{commit}}").strip()
    commits = git(repo, "rev-list", "--reverse", f"{base_sha}..{head_sha}").splitlines()
    errors = []
    for sha in commits:
        message = git(repo, "show", "-s", "--format=%B", sha)
        # Compare each commit to its first parent; deletions do not count as tests.
        parents = git(repo, "rev-list", "--parents", "-n", "1", sha).split()[1:]
        if parents:
            changed = git(repo, "diff", "--name-only", "--diff-filter=AM", "--no-renames", "-z", parents[0], sha)
        else:
            changed = git(repo, "diff-tree", "--root", "--no-commit-id", "--name-only", "--diff-filter=AM", "--no-renames", "-r", "-z", sha)
        files = set(changed.rstrip("\0").split("\0")) - {""}
        findings = validate_commit(message, files, lambda path: git(repo, "show", f"{sha}:{path}"))
        errors.extend(f"{sha[:12]}: {finding}" for finding in findings)
    return len(commits), errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, help="Base commit or branch, e.g. origin/main")
    parser.add_argument("--head", default="HEAD", help="Head commit or branch (default: HEAD)")
    args = parser.parse_args()
    try:
        count, errors = check_range(Path.cwd(), args.base, args.head)
    except (OSError, subprocess.CalledProcessError) as error:
        detail = error.stderr if isinstance(error, subprocess.CalledProcessError) else str(error)
        print(f"无法检查 Git 提交范围：{detail}")
        return 2
    if errors:
        print("开发规范检查失败：\n" + "\n".join(f"- {error}" for error in errors))
        return 1
    print(f"开发规范检查通过：{count} 个新增提交。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
