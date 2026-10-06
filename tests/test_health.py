"""Tests for project health scoring and the innerHTML precision filter."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from opensourceguard.health import (
    WEIGHTS,
    _is_fixture_path,
    evaluate,
    to_markdown,
)
from opensourceguard.security import _innerhtml_is_safe, scan_repository

MIT_TEXT = """MIT License

Copyright (c) 2026 Example

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction.
"""

GOOD_README = """# Demo Project

A small demo project used by the health-scoring tests.

## 安装

```bash
pip install -e .
```

## 快速开始

```python
from demo import main
main()
```

## 功能

- 功能一
- 功能二

## License

MIT
"""


class InnerHtmlPrecisionTests(unittest.TestCase):
    """The XSS rule must flag real sinks without flooding on escaped renders."""

    def test_bare_variable_is_a_sink(self):
        self.assertFalse(_innerhtml_is_safe("el.innerHTML = untrustedHtml;"))

    def test_member_expression_is_a_sink(self):
        self.assertFalse(_innerhtml_is_safe("el.innerHTML = data.body;"))

    def test_unknown_function_result_is_a_sink(self):
        self.assertFalse(_innerhtml_is_safe("el.innerHTML = renderRow(item);"))

    def test_static_string_is_safe(self):
        self.assertTrue(_innerhtml_is_safe('el.innerHTML = "<b>static</b>";'))

    def test_unescaped_concatenation_is_a_sink(self):
        self.assertFalse(_innerhtml_is_safe('el.innerHTML = "<b>" + userInput;'))

    def test_escaped_concatenation_is_safe(self):
        self.assertTrue(_innerhtml_is_safe('el.innerHTML = "<b>" + escapeHtml(x);'))

    def test_raw_interpolation_is_a_sink(self):
        self.assertFalse(_innerhtml_is_safe("n.innerHTML = `<p>${value}</p>`;"))

    def test_escaped_interpolation_is_safe(self):
        self.assertTrue(_innerhtml_is_safe("n.innerHTML = `<p>${escapeHtml(value)}</p>`;"))

    def test_nested_template_with_raw_value_is_a_sink(self):
        self.assertFalse(_innerhtml_is_safe('n.innerHTML = `${flag ? `<b>${q}</b>` : ""}`;'))

    def test_nested_template_with_escaped_value_is_safe(self):
        self.assertTrue(_innerhtml_is_safe('n.innerHTML = `${flag ? `<b>${escapeHtml(q)}</b>` : ""}`;'))

    def test_map_chain_with_escaping_is_safe(self):
        line = 'n.innerHTML = rows.map((r) => `<li>${escapeHtml(r)}</li>`).join("");'
        self.assertTrue(_innerhtml_is_safe(line))

    def test_map_chain_without_escaping_is_a_sink(self):
        line = 'n.innerHTML = rows.map((r) => `<li>${r}</li>`).join("");'
        self.assertFalse(_innerhtml_is_safe(line))

    def test_static_ternary_class_is_safe(self):
        self.assertTrue(_innerhtml_is_safe('n.innerHTML = `<i class="${ok ? "on" : ""}"></i>`;'))

    def test_numeric_interpolation_is_safe(self):
        self.assertTrue(_innerhtml_is_safe("n.innerHTML = `${items.length} 个`;"))
        self.assertTrue(_innerhtml_is_safe("n.innerHTML = `${Math.round(size / 1024)} KB`;"))

    def test_real_vulnerable_fixture_is_still_detected(self):
        """Regression guard: precision work must not silence the real finding."""
        demo = Path(__file__).resolve().parents[1] / "examples" / "polyglot_demo"
        rules = {finding.rule_id for finding in scan_repository(demo)}
        self.assertIn("JS-INNERHTML", rules)

    def test_own_frontend_produces_few_false_positives(self):
        """The project's escaped frontend should not be flooded with findings."""
        root = Path(__file__).resolve().parents[1]
        findings = [f for f in scan_repository(root / "web") if f.rule_id == "JS-INNERHTML"]
        self.assertLessEqual(len(findings), 6, "innerHTML 规则误报过多，会让用户忽略扫描结果")


class FixturePathTests(unittest.TestCase):
    def test_example_and_test_directories_are_fixtures(self):
        for path in ("examples/demo/a.py", "tests/test_a.py", "testdata/x.go",
                     "fixtures/y.js", "src/__tests__/z.ts"):
            with self.subTest(path=path):
                self.assertTrue(_is_fixture_path(path))

    def test_application_code_is_not_a_fixture(self):
        for path in ("opensourceguard/pipeline.py", "web/app.js", "src/main.go"):
            with self.subTest(path=path):
                self.assertFalse(_is_fixture_path(path))


class HealthScoringTests(unittest.TestCase):
    def _repo(self, files):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        repo = Path(temp.name)
        for name, content in files.items():
            target = repo / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        return repo

    def test_weights_sum_to_one_hundred(self):
        self.assertEqual(sum(WEIGHTS.values()), 100)

    def test_healthy_project_scores_well(self):
        repo = self._repo({
            "LICENSE": MIT_TEXT,
            "README.md": GOOD_README,
            "CONTRIBUTING.md": "# 贡献指南\n\n请先运行测试。\n",
            "CODE_OF_CONDUCT.md": "# 行为准则\n",
            "SECURITY.md": "# 安全政策\n",
            "CHANGELOG.md": "# 更新日志\n",
            ".gitignore": ".venv\n__pycache__\n.env\n",
            "requirements.txt": "requests==2.31.0\n",
            "src/app.py": "def add(a, b):\n    return a + b\n",
            "tests/test_app.py": "from src.app import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n",
            ".github/workflows/ci.yml": "name: CI\non: [push]\n",
        })
        report = evaluate(repo)
        self.assertGreaterEqual(report.score, 80)
        self.assertIn(report.grade, {"A", "B"})

    def test_project_with_no_license_or_readme_scores_poorly(self):
        repo = self._repo({"app.py": "def f():\n    return 1\n"})
        report = evaluate(repo)
        self.assertLess(report.score, 70)
        self.assertTrue(report.blocking_issues)

    def test_high_severity_security_finding_lowers_security_score(self):
        repo = self._repo({
            "LICENSE": MIT_TEXT, "README.md": GOOD_README,
            "app.py": "import os\n\n\ndef run(cmd):\n    return os.system(cmd)\n",
        })
        report = evaluate(repo)
        security = next(d for d in report.dimensions if d.key == "security")
        self.assertLess(security.score, 100)
        self.assertTrue(security.deductions)

    def test_clean_code_keeps_full_security_score(self):
        repo = self._repo({
            "LICENSE": MIT_TEXT, "README.md": GOOD_README,
            "app.py": "def add(a, b):\n    return a + b\n",
        })
        security = next(d for d in evaluate(repo).dimensions if d.key == "security")
        self.assertEqual(security.score, 100)

    def test_fixture_findings_do_not_reduce_security_score(self):
        """A security tool must not be penalised for its own vulnerable fixtures."""
        clean = {
            "LICENSE": MIT_TEXT, "README.md": GOOD_README,
            "app.py": "def add(a, b):\n    return a + b\n",
        }
        with_fixture = dict(clean)
        with_fixture["examples/bad_demo/insecure.py"] = "import os\n\n\ndef r(c):\n    return os.system(c)\n"

        baseline = next(d for d in evaluate(self._repo(clean)).dimensions if d.key == "security")
        with_demo_report = evaluate(self._repo(with_fixture))
        with_demo = next(d for d in with_demo_report.dimensions if d.key == "security")

        self.assertEqual(baseline.score, with_demo.score)
        self.assertGreater(with_demo_report.stats["security_in_fixtures"], 0)

    def test_missing_tests_lowers_testing_score(self):
        repo = self._repo({
            "LICENSE": MIT_TEXT, "README.md": GOOD_README,
            "app.py": "def f():\n    return 1\n",
        })
        testing = next(d for d in evaluate(repo).dimensions if d.key == "testing")
        self.assertLess(testing.score, 60)
        self.assertTrue(any("测试" in action for action in testing.actions))

    def test_short_readme_lowers_documentation_score(self):
        repo = self._repo({"LICENSE": MIT_TEXT, "README.md": "# x\n", "app.py": "x = 1\n"})
        docs = next(d for d in evaluate(repo).dimensions if d.key == "documentation")
        self.assertLess(docs.score, 70)

    def test_unmeasured_dimension_is_excluded_from_average(self):
        """An empty repo cannot be scored on code quality; weights renormalise."""
        repo = self._repo({"LICENSE": MIT_TEXT, "README.md": GOOD_README})
        report = evaluate(repo)
        unmeasured = [d for d in report.dimensions if not d.measured]
        self.assertTrue(unmeasured)
        self.assertLess(report.stats["measured_weight"], 100)
        self.assertTrue(any("无法测量" in warning for warning in report.warnings))

    def test_score_is_bounded(self):
        for files in ({"app.py": "x = 1\n"},
                      {"LICENSE": MIT_TEXT, "README.md": GOOD_README, "app.py": "x = 1\n"}):
            report = evaluate(self._repo(files))
            with self.subTest(files=sorted(files)):
                self.assertGreaterEqual(report.score, 0)
                self.assertLessEqual(report.score, 100)

    def test_every_dimension_explains_itself(self):
        repo = self._repo({"LICENSE": MIT_TEXT, "README.md": GOOD_README, "app.py": "x = 1\n"})
        for dimension in evaluate(repo).dimensions:
            with self.subTest(dimension=dimension.key):
                self.assertTrue(dimension.actions, "每个维度都应给出下一步建议")
                self.assertIn(dimension.weight, WEIGHTS.values())

    def test_report_states_scoring_limitations(self):
        repo = self._repo({"LICENSE": MIT_TEXT, "README.md": GOOD_README, "app.py": "x = 1\n"})
        report = evaluate(repo)
        self.assertTrue(any("不评估代码正确性" in warning for warning in report.warnings))

    def test_report_is_json_serialisable(self):
        repo = self._repo({"LICENSE": MIT_TEXT, "README.md": GOOD_README, "app.py": "x = 1\n"})
        raw = json.dumps(evaluate(repo).to_dict(), ensure_ascii=False)
        self.assertIn("dimensions", raw)

    def test_markdown_contains_all_dimensions(self):
        repo = self._repo({"LICENSE": MIT_TEXT, "README.md": GOOD_README, "app.py": "x = 1\n"})
        markdown = to_markdown(evaluate(repo))
        self.assertIn("# 项目健康度报告", markdown)
        for label in ("安全", "合规", "测试", "文档", "可维护性"):
            self.assertIn(label, markdown)

    def test_missing_directory_raises_value_error(self):
        with self.assertRaises(ValueError):
            evaluate(Path("no-such-directory-osg-health"))

    def test_self_evaluation_runs_and_is_reasonable(self):
        """The tool must be able to score its own repository."""
        report = evaluate(Path(__file__).resolve().parents[1])
        self.assertGreater(report.score, 50)
        self.assertEqual(len(report.dimensions), len(WEIGHTS))


if __name__ == "__main__":
    unittest.main()
