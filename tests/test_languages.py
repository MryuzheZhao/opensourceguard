"""Tests for multi-language symbol extraction and language-aware security rules."""
from __future__ import annotations

import unittest
from pathlib import Path

from opensourceguard.indexer import index_repository, language_breakdown, rank_symbols
from opensourceguard.languages import (
    detect_languages,
    extract_symbols,
    is_test_path,
    language_label,
    language_of,
)
from opensourceguard.security import scan_repository, severity_counts

DEMO = Path(__file__).resolve().parents[1] / "examples" / "polyglot_demo"


class LanguageDetectionTests(unittest.TestCase):
    def test_known_suffixes_map_to_languages(self):
        cases = {
            "a.py": "python", "a.js": "javascript", "a.mjs": "javascript",
            "a.ts": "typescript", "a.tsx": "typescript", "a.java": "java",
            "a.go": "go", "a.rs": "rust", "a.rb": "ruby", "a.php": "php",
            "a.cs": "csharp", "a.kt": "kotlin", "a.swift": "swift",
            "a.c": "c", "a.cpp": "cpp", "a.sh": "shell",
        }
        for name, expected in cases.items():
            with self.subTest(name=name):
                self.assertEqual(language_of(Path(name)), expected)

    def test_unsupported_suffix_returns_none(self):
        self.assertIsNone(language_of(Path("image.png")))
        self.assertIsNone(language_of(Path("notes.docx")))

    def test_language_label_falls_back_to_id(self):
        self.assertEqual(language_label("python"), "Python")
        self.assertEqual(language_label("brainfuck"), "brainfuck")

    def test_detect_languages_counts_and_sorts(self):
        counts = detect_languages(["a.py", "b.py", "c.js", "d.txt"])
        self.assertEqual(counts, {"python": 2, "javascript": 1})

    def test_is_test_path_covers_common_conventions(self):
        for path in ["tests/test_a.py", "src/a.test.js", "src/a.spec.ts",
                     "src/__tests__/a.js", "src/FooTest.java", "spec/a_spec.rb"]:
            with self.subTest(path=path):
                self.assertTrue(is_test_path(path))
        self.assertFalse(is_test_path("src/parser.py"))


class SymbolExtractionTests(unittest.TestCase):
    def test_javascript_declaration_forms(self):
        source = (
            "export async function loadUser(id) {\n  return id;\n}\n"
            "export const computeTotal = (values) => values.length;\n"
            "class Renderer {\n  render(html) {\n    return html;\n  }\n}\n"
        )
        names = {symbol.name for symbol in extract_symbols(source, "javascript")}
        self.assertIn("loadUser", names)
        self.assertIn("computeTotal", names)
        self.assertIn("Renderer", names)
        self.assertIn("render", names)

    def test_typescript_interfaces_and_types(self):
        source = "export interface User {\n  id: string;\n}\nexport type Id = string;\n"
        kinds = {(s.name, s.kind) for s in extract_symbols(source, "typescript")}
        self.assertIn(("User", "type"), kinds)
        self.assertIn(("Id", "type"), kinds)

    def test_go_functions_methods_and_types(self):
        source = (
            "type Store struct {\n\tdb int\n}\n"
            "func (s *Store) Find(name string) error {\n\treturn nil\n}\n"
            "func Helper() {\n}\n"
        )
        result = {(s.name, s.kind) for s in extract_symbols(source, "go")}
        self.assertIn(("Store", "type"), result)
        self.assertIn(("Find", "method"), result)
        self.assertIn(("Helper", "function"), result)

    def test_rust_items(self):
        source = (
            "pub struct Config {\n    pub a: u32,\n}\n"
            "impl Config {\n    pub fn new() -> Self {\n        Config { a: 0 }\n    }\n}\n"
            "pub async unsafe fn risky() {}\n"
        )
        result = {(s.name, s.kind) for s in extract_symbols(source, "rust")}
        self.assertIn(("Config", "type"), result)
        self.assertIn(("new", "function"), result)
        self.assertIn(("risky", "function"), result)

    def test_java_class_and_methods(self):
        source = (
            "public class Repo {\n"
            "    public ResultSet find(String name) throws SQLException {\n"
            "        return null;\n"
            "    }\n"
            "    private int count() {\n        return 0;\n    }\n"
            "}\n"
        )
        result = {(s.name, s.kind) for s in extract_symbols(source, "java")}
        self.assertIn(("Repo", "class"), result)
        self.assertIn(("find", "method"), result)
        self.assertIn(("count", "method"), result)

    def test_comments_are_not_reported_as_symbols(self):
        source = "// function ghost() {}\n/* class Phantom {} */\nfunction real() {}\n"
        names = {symbol.name for symbol in extract_symbols(source, "javascript")}
        self.assertEqual(names, {"real"})

    def test_control_flow_is_not_a_symbol(self):
        source = "if (x) {\n}\nfor (;;) {\n}\nwhile (y) {\n}\n"
        self.assertEqual(extract_symbols(source, "javascript"), [])

    def test_unsupported_language_returns_empty(self):
        self.assertEqual(extract_symbols("anything", "cobol"), [])

    def test_oversized_source_is_skipped(self):
        self.assertEqual(extract_symbols("x" * 900_000, "javascript"), [])

    def test_symbols_are_marked_heuristic(self):
        symbols = extract_symbols("function a() {}\n", "javascript")
        self.assertTrue(symbols)
        self.assertTrue(all(symbol.confidence == "heuristic" for symbol in symbols))


class PolyglotIndexTests(unittest.TestCase):
    def test_demo_repository_indexes_four_languages(self):
        symbols = index_repository(DEMO)
        breakdown = language_breakdown(symbols)
        for language in ("javascript", "go", "java", "rust"):
            with self.subTest(language=language):
                self.assertIn(language, breakdown)

    def test_python_symbols_are_parsed_not_heuristic(self):
        symbols = index_repository(Path(__file__).resolve().parents[1] / "examples" / "buggy_csv")
        self.assertTrue(symbols)
        self.assertTrue(all(symbol.confidence == "parsed" for symbol in symbols))
        self.assertTrue(all(symbol.language == "python" for symbol in symbols))

    def test_non_python_symbols_are_marked_heuristic(self):
        symbols = [s for s in index_repository(DEMO) if s.language == "go"]
        self.assertTrue(symbols)
        self.assertTrue(all(symbol.confidence == "heuristic" for symbol in symbols))

    def test_ranking_prefers_declarations_over_whole_files(self):
        symbols = index_repository(DEMO)
        ranked = rank_symbols(symbols, ["parsecsv", "csv"], "parseCsv 在空输入时崩溃")
        self.assertTrue(ranked)
        self.assertEqual(ranked[0].path, "report.js")

    def test_ranking_deprioritises_test_files(self):
        symbols = index_repository(Path(__file__).resolve().parents[1] / "examples" / "buggy_csv")
        ranked = rank_symbols(symbols, ["parse_csv"], "parse_csv 崩溃")
        self.assertTrue(ranked)
        self.assertNotIn("test", ranked[0].path.lower())


class MultiLanguageSecurityTests(unittest.TestCase):
    def setUp(self):
        self.findings = scan_repository(DEMO)
        self.rules = {finding.rule_id for finding in self.findings}

    def test_detects_java_sql_injection(self):
        self.assertIn("JAVA-SQL-CONCAT", self.rules)

    def test_detects_java_command_execution(self):
        self.assertIn("JAVA-RUNTIME-EXEC", self.rules)

    def test_detects_go_sprintf_sql(self):
        self.assertIn("GO-SQL-SPRINTF", self.rules)

    def test_detects_go_weak_hash(self):
        self.assertIn("GO-WEAK-HASH", self.rules)

    def test_detects_javascript_xss_and_weak_random(self):
        self.assertIn("JS-INNERHTML", self.rules)
        self.assertIn("JS-MATH-RANDOM-TOKEN", self.rules)

    def test_detects_rust_shell_command(self):
        self.assertIn("RS-COMMAND", self.rules)

    def test_every_finding_carries_cwe_and_language(self):
        for finding in self.findings:
            with self.subTest(rule=finding.rule_id):
                self.assertTrue(finding.cwe.startswith("CWE-"))
                self.assertTrue(finding.language)
                self.assertTrue(finding.recommendation)

    def test_severity_counts_sum_matches_findings(self):
        counts = severity_counts(self.findings)
        self.assertEqual(sum(counts.values()), len(self.findings))

    def test_generic_secret_rules_detect_private_key(self):
        import tempfile

        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            (repo / "config.yaml").write_text(
                "key: |\n  -----BEGIN RSA PRIVATE KEY-----\n", encoding="utf-8")
            rules = {finding.rule_id for finding in scan_repository(repo)}
        self.assertIn("GEN-PRIVATE-KEY", rules)

    def test_suppression_comment_is_respected(self):
        import tempfile

        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            (repo / "app.py").write_text("eval('1+1')  # osg:ignore\n", encoding="utf-8")
            self.assertEqual(scan_repository(repo), [])

    def test_example_files_downgrade_secret_severity(self):
        import tempfile

        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            (repo / "config.example.env").write_text(
                'API_TOKEN = "replace-with-your-token"\n', encoding="utf-8")
            findings = [f for f in scan_repository(repo) if "SECRET" in f.rule_id or "TOKEN" in f.rule_id]
        for finding in findings:
            with self.subTest(rule=finding.rule_id):
                self.assertEqual(finding.severity, "low")


if __name__ == "__main__":
    unittest.main()
