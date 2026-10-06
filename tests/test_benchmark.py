"""Tests for the reproducible benchmark runner."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "eval"))

from run_eval import main, regressions, run_case, summarise, to_markdown  # noqa: E402

CASES = json.loads((ROOT / "eval" / "cases.json").read_text(encoding="utf-8"))


class CaseDefinitionTests(unittest.TestCase):
    def test_every_case_has_required_fields(self):
        for case in CASES:
            with self.subTest(case=case.get("id")):
                for field in ("id", "repo", "issue", "category", "expected_path"):
                    self.assertIn(field, case)

    def test_case_ids_are_unique(self):
        ids = [case["id"] for case in CASES]
        self.assertEqual(len(ids), len(set(ids)))

    def test_every_referenced_repo_exists(self):
        for case in CASES:
            with self.subTest(case=case["id"]):
                self.assertTrue((ROOT / case["repo"]).is_dir())

    def test_expected_path_exists_in_repo(self):
        for case in CASES:
            with self.subTest(case=case["id"]):
                self.assertTrue((ROOT / case["repo"] / case["expected_path"]).is_file())

    def test_suite_covers_bug_security_and_negative_categories(self):
        categories = {case["category"] for case in CASES}
        for expected in ("bug", "security", "negative"):
            self.assertIn(expected, categories)

    def test_suite_covers_more_than_one_language(self):
        languages = {case.get("language") for case in CASES}
        self.assertGreater(len(languages), 1)

    def test_negative_control_expects_no_findings(self):
        negatives = [case for case in CASES if case["category"] == "negative"]
        self.assertTrue(negatives)
        for case in negatives:
            self.assertTrue(case.get("expect_no_findings"))


class RunCaseTests(unittest.TestCase):
    def test_run_case_returns_scored_row(self):
        case = next(c for c in CASES if c["id"] == "csv-empty-crash")
        row = run_case(case, "skip", 10)
        self.assertEqual(row["id"], "csv-empty-crash")
        self.assertTrue(row["top1_localisation"])
        self.assertTrue(row["symbol_hit"])
        self.assertGreaterEqual(row["duration_seconds"], 0)

    def test_negative_control_produces_no_unexpected_findings(self):
        case = next(c for c in CASES if c["category"] == "negative")
        row = run_case(case, "skip", 10)
        self.assertEqual(row["unexpected_findings"], [])

    def test_security_case_fires_expected_rules(self):
        case = next(c for c in CASES if c["id"] == "sql-injection")
        row = run_case(case, "skip", 10)
        self.assertIn("PY-SQL-FORMAT", row["fired_rules"])

    def test_non_python_case_is_marked_heuristic(self):
        case = next(c for c in CASES if c["id"] == "polyglot-java-sql")
        row = run_case(case, "skip", 10)
        self.assertEqual(row["evidence_confidence"], "heuristic")


class SummariseTests(unittest.TestCase):
    def _row(self, **overrides):
        base = {
            "id": "x", "category": "bug", "language": "python", "issue": "i",
            "expected_path": "a.py", "top_path": "a.py", "evidence_paths": ["a.py"],
            "expected_symbol": "f", "top_symbol": "f",
            "top1_localisation": True, "top3_localisation": True,
            "symbol_hit": True, "symbol_checked": True,
            "expected_rules": [], "fired_rules": [], "matched_rules": [],
            "unexpected_findings": [], "issue_type": "bug", "expected_issue_type": "bug",
            "issue_type_hit": True, "has_patch": True, "expect_patch": True,
            "verification_status": "verified", "verified": True, "expect_verified": True,
            "evidence_confidence": "parsed", "primary_language": "python",
            "model_used": "heuristic", "duration_seconds": 0.1,
        }
        base.update(overrides)
        return base

    def test_all_hits_yields_full_scores(self):
        summary = summarise([self._row(), self._row()])
        self.assertEqual(summary["top1_localisation"], 1.0)
        self.assertEqual(summary["symbol_accuracy"], 1.0)
        self.assertEqual(summary["patch_rate"], 1.0)
        self.assertEqual(summary["verified_rate"], 1.0)

    def test_partial_hits_are_averaged(self):
        summary = summarise([self._row(), self._row(top1_localisation=False)])
        self.assertEqual(summary["top1_localisation"], 0.5)

    def test_security_recall_uses_rule_counts_not_case_counts(self):
        rows = [
            self._row(expected_rules=["A", "B"], matched_rules=["A"]),
            self._row(expected_rules=["C"], matched_rules=["C"]),
        ]
        # 2 of 3 expected rules matched.
        self.assertAlmostEqual(summarise(rows)["security_recall"], 0.6667, places=3)

    def test_false_positives_counted_from_negative_rows_only(self):
        rows = [
            self._row(category="negative", unexpected_findings=["R1", "R2"]),
            self._row(category="bug", unexpected_findings=["R3"]),
        ]
        self.assertEqual(summarise(rows)["false_positives_on_clean_repo"], 2)

    def test_empty_denominators_do_not_divide_by_zero(self):
        summary = summarise([self._row(symbol_checked=False, expect_patch=False,
                                       expect_verified=False, expected_path=None)])
        self.assertEqual(summary["symbol_accuracy"], 0.0)
        self.assertEqual(summary["patch_rate"], 0.0)
        self.assertEqual(summary["top1_localisation"], 0.0)

    def test_language_and_category_breakdowns_are_present(self):
        summary = summarise([self._row(language="go", category="security")])
        self.assertIn("go", summary["by_language"])
        self.assertIn("security", summary["by_category"])


class RegressionTests(unittest.TestCase):
    def _row(self, **overrides):
        base = {
            "id": "case", "expected_path": "a.py", "top3_localisation": True,
            "expected_rules": [], "fired_rules": [], "unexpected_findings": [],
            "expect_patch": False, "has_patch": False,
            "expect_verified": False, "verified": False, "verification_status": "skipped",
        }
        base.update(overrides)
        return base

    def test_clean_run_reports_no_regressions(self):
        self.assertEqual(regressions([self._row()]), [])

    def test_missed_localisation_is_reported(self):
        failures = regressions([self._row(top3_localisation=False)])
        self.assertTrue(any("未出现在前 3 条证据" in item for item in failures))

    def test_missed_security_rule_is_reported(self):
        failures = regressions([self._row(expected_rules=["PY-SHELL"], fired_rules=[])])
        self.assertTrue(any("PY-SHELL" in item for item in failures))

    def test_false_positive_is_reported(self):
        failures = regressions([self._row(unexpected_findings=["X"])])
        self.assertTrue(any("误报" in item for item in failures))

    def test_verification_expectation_ignored_in_skip_mode(self):
        row = self._row(expect_verified=True, verified=False)
        self.assertEqual(regressions([row], execute="skip"), [])

    def test_verification_expectation_enforced_in_local_mode(self):
        row = self._row(expect_verified=True, verified=False)
        self.assertTrue(regressions([row], execute="local"))


class EndToEndTests(unittest.TestCase):
    def test_full_benchmark_run_has_no_regressions(self):
        rows = [run_case(case, "skip", 15) for case in CASES]
        self.assertEqual(regressions(rows, "skip"), [])

    def test_full_benchmark_localisation_is_perfect_on_fixtures(self):
        rows = [run_case(case, "skip", 15) for case in CASES]
        summary = summarise(rows)
        self.assertEqual(summary["top1_localisation"], 1.0)
        self.assertEqual(summary["false_positives_on_clean_repo"], 0)

    def test_markdown_report_states_its_limitations(self):
        rows = [run_case(case, "skip", 15) for case in CASES]
        markdown = to_markdown({
            "generated_at": "now", "execute_mode": "skip",
            "python_version": "3.12", "platform": "test",
            "summary": summarise(rows), "regressions": [], "rows": rows,
        })
        self.assertIn("SWE-bench", markdown)
        self.assertIn("启发式", markdown)

    def test_cli_writes_json_artifact(self):
        import tempfile

        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "benchmark.json"
            code = main(["--output", str(target), "--fail-on-regression"])
            self.assertEqual(code, 0)
            payload = json.loads(target.read_text(encoding="utf-8"))
        self.assertIn("summary", payload)
        self.assertEqual(payload["summary"]["cases"], len(CASES))


if __name__ == "__main__":
    unittest.main()
