import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.check_development_policy import BUGFIX_SECTIONS, check_range, validate_commit


RECORD_PATH = "docs/bugfixes/2026-09-15-example-lock.md"


def complete_message(kind: str = "docs", extra: str = "") -> str:
    return (
        f"{kind}(workflow): 记录验证和修复证据\n\n"
        "Why:\n复现时缺少关闭连接的保证。\n\n"
        "Changes:\n- 显式关闭资源并记录变更。\n\n"
        "Validation:\n- 在临时数据库执行回归测试，通过。\n\n"
        "Risks:\n- 不改变数据格式；通过 revert 回滚。\n\n"
        "Refs:\n- 维护任务：建立可追溯流程。\n" + extra
    )


def complete_record() -> str:
    return "# 测试记录\n\n" + "\n\n".join(f"## {heading}\n\n实际证据。" for heading in BUGFIX_SECTIONS)


class CommitPolicyTests(unittest.TestCase):
    def test_complete_maintenance_message_needs_no_bugfix_record(self) -> None:
        self.assertEqual(validate_commit(complete_message(), set(), lambda _: ""), [])

    def test_accepts_breaking_change_subject_and_inline_field_content(self) -> None:
        message = complete_message().replace("docs(workflow):", "feat(config)!:")
        message = message.replace("Why:\n", "Why: ")
        self.assertEqual(validate_commit(message, set(), lambda _: ""), [])

    def test_rejects_short_message_and_missing_separator(self) -> None:
        for message in ("fix bug", complete_message().replace("\n\nWhy:", "\nWhy:", 1)):
            with self.subTest(message=message):
                self.assertTrue(validate_commit(message, set(), lambda _: ""))

    def test_each_required_field_must_have_real_content(self) -> None:
        for content in ("", "# 请填写", "<!-- 请填写 -->", "<实际结果>", "TODO", "- TBD"):
            with self.subTest(content=content):
                message = complete_message().replace("复现时缺少关闭连接的保证。", content)
                self.assertTrue(any("Why:" in e for e in validate_commit(message, set(), lambda _: "")))

    def test_duplicate_field_is_rejected(self) -> None:
        errors = validate_commit(complete_message(extra="\nWhy:\n第二次出现。"), set(), lambda _: "")
        self.assertTrue(any("Why:" in e for e in errors))

    def test_fix_requires_record_and_changed_test(self) -> None:
        errors = validate_commit(complete_message("fix"), set(), lambda _: "")
        self.assertTrue(any("Bugfix:" in e for e in errors))
        self.assertTrue(any("单元回归测试" in e for e in errors))

    def test_fix_accepts_record_and_test_in_same_commit(self) -> None:
        message = complete_message("fix", f"\nBugfix: {RECORD_PATH}\n")
        errors = validate_commit(message, {RECORD_PATH, "tests/test_backup_core.py"}, lambda _: complete_record())
        self.assertEqual(errors, [])

    def test_unchanged_record_and_non_test_file_are_rejected(self) -> None:
        message = complete_message("fix", f"\nBugfix: {RECORD_PATH}\n")
        errors = validate_commit(message, {"tests/helper.py"}, lambda _: complete_record())
        self.assertTrue(any("同时新增或更新记录" in e for e in errors))
        self.assertTrue(any("单元回归测试" in e for e in errors))

    def test_template_and_traversal_paths_are_rejected_without_reading(self) -> None:
        def unexpected_read(_path: str) -> str:
            self.fail("无效路径不得被读取")

        for path in ("docs/bugfixes/TEMPLATE.md", "docs/bugfixes/../../private.md"):
            with self.subTest(path=path):
                errors = validate_commit(complete_message("fix", f"\nBugfix: {path}\n"), {path, "tests/test_core.py"}, unexpected_read)
                self.assertTrue(any("路径格式无效" in e for e in errors))

    def test_record_needs_every_section_with_content(self) -> None:
        for heading in BUGFIX_SECTIONS:
            for replacement in ("", f"## {heading}\n\n<!-- 未填写 -->"):
                with self.subTest(heading=heading, replacement=replacement):
                    record = complete_record().replace(f"## {heading}\n\n实际证据。", replacement)
                    errors = validate_commit(
                        complete_message("fix", f"\nBugfix: {RECORD_PATH}\n"),
                        {RECORD_PATH, "tests/test_core.py"}, lambda _: record,
                    )
                    self.assertTrue(any(heading in e for e in errors))

    def test_multiple_records_are_all_validated(self) -> None:
        second = "docs/bugfixes/2026-09-15-second-lock.md"
        message = complete_message("fix", f"\nBugfix: {RECORD_PATH}\nBugfix: {second}\n")
        records = {RECORD_PATH: complete_record(), second: "# 空记录"}
        errors = validate_commit(message, {*records, "tests/test_core.py"}, records.__getitem__)
        self.assertTrue(any(second in e for e in errors))


class GitRangePolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        self.run_git("init", "--initial-branch=main")
        self.run_git("config", "user.name", "Policy Test")
        self.run_git("config", "user.email", "policy@example.invalid")
        self.commit("Legacy baseline is intentionally exempt")
        self.base = self.run_git("rev-parse", "HEAD").strip()

    def run_git(self, *args: str) -> str:
        return subprocess.run(
            ["git", "-c", "commit.gpgsign=false", *args], cwd=self.repo, check=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
        ).stdout

    def commit(self, message: str) -> str:
        self.run_git("add", ".")
        self.run_git("commit", "--allow-empty", "-m", message)
        return self.run_git("rev-parse", "HEAD").strip()

    def test_checks_earlier_commits_and_excludes_baseline(self) -> None:
        bad = self.commit("update")
        self.commit(complete_message())
        count, errors = check_range(self.repo, self.base, "HEAD")
        self.assertEqual(count, 2)
        self.assertTrue(errors)
        self.assertTrue(all(error.startswith(bad[:12]) for error in errors))

    def test_fix_record_is_read_from_its_commit_not_later_worktree(self) -> None:
        record = self.repo / RECORD_PATH
        record.parent.mkdir(parents=True)
        record.write_text(complete_record(), encoding="utf-8")
        tests = self.repo / "tests"
        tests.mkdir()
        (tests / "test_core.py").write_text("# Synthetic fixture for Git diff testing\n", encoding="utf-8")
        self.commit(complete_message("fix", f"\nBugfix: {RECORD_PATH}\n"))
        record.write_text("# Later uncommitted content", encoding="utf-8")
        self.assertEqual(check_range(self.repo, self.base, "HEAD"), (1, []))

    def test_deleting_a_test_does_not_satisfy_fix_requirement(self) -> None:
        tests = self.repo / "tests"
        tests.mkdir()
        test_file = tests / "test_core.py"
        test_file.write_text("# Synthetic Git fixture\n", encoding="utf-8")
        self.commit(complete_message("test"))
        record = self.repo / RECORD_PATH
        record.parent.mkdir(parents=True)
        record.write_text(complete_record(), encoding="utf-8")
        test_file.unlink()
        self.commit(complete_message("fix", f"\nBugfix: {RECORD_PATH}\n"))
        count, errors = check_range(self.repo, self.base, "HEAD")
        self.assertEqual(count, 2)
        self.assertTrue(any("单元回归测试" in e for e in errors))

    def test_empty_range_and_unknown_ref_are_distinct(self) -> None:
        self.assertEqual(check_range(self.repo, self.base, "HEAD"), (0, []))
        with self.assertRaises(subprocess.CalledProcessError):
            check_range(self.repo, "missing-branch", "HEAD")


if __name__ == "__main__":
    unittest.main()
