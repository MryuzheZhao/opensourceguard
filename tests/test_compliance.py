"""Tests for the dependency and licence compliance auditor."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from opensourceguard.compliance import (
    audit,
    detect_project_license,
    license_conflict,
    normalize_license,
    to_markdown,
)

MIT_TEXT = """MIT License

Copyright (c) 2026 Example

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction.
"""

GPL_TEXT = """                    GNU GENERAL PUBLIC LICENSE
                       Version 3, 29 June 2007

 Copyright (C) 2007 Free Software Foundation, Inc.
"""

APACHE_TEXT = """                                 Apache License
                           Version 2.0, January 2004

   Licensed under the Apache License, Version 2.0 (the "License");
"""


class NormalizeLicenseTests(unittest.TestCase):
    def test_common_aliases(self):
        cases = {
            "MIT": "MIT", "mit license": "MIT", "Expat": "MIT",
            "Apache 2.0": "Apache-2.0", "ASL 2.0": "Apache-2.0",
            "GPLv3": "GPL-3.0", "gpl-3.0": "GPL-3.0",
            "LGPLv3": "LGPL-3.0", "AGPLv3": "AGPL-3.0",
            "BSD": "BSD-3-Clause", "ISC": "ISC", "UNLICENSED": "Proprietary",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(normalize_license(raw), expected)

    def test_dual_license_picks_known_identifier(self):
        self.assertEqual(normalize_license("Apache-2.0 OR MIT"), "Apache-2.0")

    def test_empty_input(self):
        self.assertEqual(normalize_license(""), "")
        self.assertEqual(normalize_license("   "), "")

    def test_unknown_license_is_preserved_not_guessed(self):
        self.assertEqual(normalize_license("MyCompany-Internal-1.0"), "MyCompany-Internal-1.0")


class DetectProjectLicenseTests(unittest.TestCase):
    def _repo(self, files):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        repo = Path(temp.name)
        for name, content in files.items():
            (repo / name).write_text(content, encoding="utf-8")
        return repo

    def test_detects_mit_from_license_file(self):
        repo = self._repo({"LICENSE": MIT_TEXT})
        license_id, source, confidence = detect_project_license(repo)
        self.assertEqual(license_id, "MIT")
        self.assertEqual(source, "LICENSE")
        self.assertEqual(confidence, "high")

    def test_detects_gpl_from_license_file(self):
        repo = self._repo({"LICENSE": GPL_TEXT})
        self.assertEqual(detect_project_license(repo)[0], "GPL-3.0")

    def test_detects_apache_from_license_file(self):
        repo = self._repo({"LICENSE.md": APACHE_TEXT})
        self.assertEqual(detect_project_license(repo)[0], "Apache-2.0")

    def test_falls_back_to_package_json(self):
        repo = self._repo({"package.json": json.dumps({"name": "x", "license": "MIT"})})
        license_id, source, confidence = detect_project_license(repo)
        self.assertEqual(license_id, "MIT")
        self.assertEqual(source, "package.json")
        self.assertEqual(confidence, "medium")

    def test_no_license_returns_empty(self):
        repo = self._repo({"README.md": "# hi"})
        self.assertEqual(detect_project_license(repo), ("", "", "none"))

    def test_custom_license_text_is_unknown_not_guessed(self):
        repo = self._repo({"LICENSE": "All rights reserved by ACME Corp."})
        license_id, _, confidence = detect_project_license(repo)
        self.assertEqual(license_id, "unknown")
        self.assertEqual(confidence, "low")


class LicenseConflictTests(unittest.TestCase):
    def test_gpl_dependency_in_mit_project_is_high(self):
        result = license_conflict("MIT", "GPL-3.0")
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "high")

    def test_agpl_dependency_in_apache_project_is_high(self):
        self.assertEqual(license_conflict("Apache-2.0", "AGPL-3.0")[0], "high")

    def test_lgpl_dependency_in_mit_project_is_medium(self):
        self.assertEqual(license_conflict("MIT", "LGPL-3.0")[0], "medium")

    def test_proprietary_dependency_is_high(self):
        self.assertEqual(license_conflict("MIT", "Proprietary")[0], "high")

    def test_apache_dependency_in_gpl2_project_is_high(self):
        self.assertEqual(license_conflict("GPL-2.0", "Apache-2.0")[0], "high")

    def test_permissive_combination_has_no_conflict(self):
        self.assertIsNone(license_conflict("MIT", "Apache-2.0"))
        self.assertIsNone(license_conflict("Apache-2.0", "BSD-3-Clause"))

    def test_identical_licenses_have_no_conflict(self):
        self.assertIsNone(license_conflict("GPL-3.0", "GPL-3.0"))

    def test_gpl_project_accepts_gpl_dependency(self):
        self.assertIsNone(license_conflict("GPL-3.0", "MIT"))

    def test_unknown_licenses_are_not_reported_as_conflicts(self):
        self.assertIsNone(license_conflict("MIT", "unknown"))
        self.assertIsNone(license_conflict("", "GPL-3.0"))


class ManifestParsingTests(unittest.TestCase):
    def _audit(self, files):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        repo = Path(temp.name)
        for name, content in files.items():
            (repo / name).write_text(content, encoding="utf-8")
        return audit(repo)

    def test_requirements_txt(self):
        report = self._audit({
            "LICENSE": MIT_TEXT,
            "requirements.txt": "requests==2.31.0\n# comment\npyyaml>=6.0\n-r other.txt\n",
        })
        names = {entry["name"] for entry in report.dependencies}
        self.assertEqual(names, {"requests", "pyyaml"})
        self.assertIn("requirements.txt", report.manifests)

    def test_package_json_scopes(self):
        report = self._audit({
            "LICENSE": MIT_TEXT,
            "package.json": json.dumps({
                "name": "x", "license": "MIT",
                "dependencies": {"lodash": "^4.17.21"},
                "devDependencies": {"jest": "^29.0.0"},
            }),
        })
        scopes = {entry["name"]: entry["scope"] for entry in report.dependencies}
        self.assertEqual(scopes.get("lodash"), "runtime")
        self.assertEqual(scopes.get("jest"), "dev")

    def test_go_mod(self):
        report = self._audit({
            "LICENSE": MIT_TEXT,
            "go.mod": "module demo\n\ngo 1.21\n\nrequire (\n\tgithub.com/x/y v1.2.3\n\tgithub.com/a/b v0.1.0 // indirect\n)\n",
        })
        names = {entry["name"] for entry in report.dependencies}
        self.assertIn("github.com/x/y", names)
        indirect = [e for e in report.dependencies if e["name"] == "github.com/a/b"]
        self.assertEqual(indirect[0]["scope"], "indirect")

    def test_cargo_toml(self):
        report = self._audit({
            "LICENSE": MIT_TEXT,
            "Cargo.toml": '[package]\nname = "x"\n\n[dependencies]\nserde = "1.0"\n\n[dev-dependencies]\ncriterion = "0.5"\n',
        })
        scopes = {entry["name"]: entry["scope"] for entry in report.dependencies}
        self.assertEqual(scopes.get("serde"), "runtime")
        self.assertEqual(scopes.get("criterion"), "dev")

    def test_pom_xml(self):
        report = self._audit({
            "LICENSE": MIT_TEXT,
            "pom.xml": "<project><dependencies><dependency>"
                       "<groupId>org.x</groupId><artifactId>lib</artifactId>"
                       "<version>1.0</version><scope>test</scope>"
                       "</dependency></dependencies></project>",
        })
        entry = [e for e in report.dependencies if e["name"] == "lib"][0]
        self.assertEqual(entry["version"], "1.0")
        self.assertEqual(entry["scope"], "test")
        self.assertEqual(entry["ecosystem"], "maven")

    def test_pyproject_dependencies(self):
        report = self._audit({
            "LICENSE": MIT_TEXT,
            "pyproject.toml": '[project]\nname = "x"\ndependencies = [\n  "requests>=2.0",\n  "click",\n]\n',
        })
        names = {entry["name"] for entry in report.dependencies}
        self.assertEqual(names, {"requests", "click"})

    def test_malformed_manifest_does_not_crash(self):
        report = self._audit({"LICENSE": MIT_TEXT, "package.json": "{ not json"})
        self.assertIn("package.json", report.manifests)
        self.assertEqual(report.dependencies, [])

    def test_duplicate_dependencies_are_deduplicated(self):
        report = self._audit({
            "LICENSE": MIT_TEXT,
            "requirements.txt": "requests==2.31.0\n",
            "pyproject.toml": '[project]\ndependencies = ["requests>=2.0"]\n',
        })
        matches = [e for e in report.dependencies if e["name"] == "requests"]
        self.assertEqual(len(matches), 1)


class AuditBehaviourTests(unittest.TestCase):
    def _repo(self, files):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        repo = Path(temp.name)
        for name, content in files.items():
            (repo / name).write_text(content, encoding="utf-8")
        return repo

    def test_gpl_dependency_in_mit_project_produces_blocking_finding(self):
        repo = self._repo({
            "LICENSE": MIT_TEXT,
            "requirements.txt": "mysql-connector-python==8.0.33\n",
        })
        report = audit(repo)
        conflicts = [f for f in report.findings if f.kind == "license" and f.severity == "high"]
        self.assertTrue(conflicts)
        self.assertEqual(conflicts[0].subject, "mysql-connector-python")
        self.assertTrue(report.summary["blocking"])

    def test_missing_license_is_high_severity(self):
        report = audit(self._repo({"README.md": "# x"}))
        subjects = {f.subject: f.severity for f in report.findings}
        self.assertEqual(subjects.get("LICENSE"), "high")

    def test_credential_file_in_root_is_flagged(self):
        report = audit(self._repo({"LICENSE": MIT_TEXT, ".env.local": "TOKEN=abc\n"})) 
        flagged = [f for f in report.findings if f.subject == ".env.local"]
        self.assertTrue(flagged)
        self.assertEqual(flagged[0].severity, "high")

    def test_env_example_is_not_flagged_as_credential(self):
        report = audit(self._repo({"LICENSE": MIT_TEXT, ".env.example": "TOKEN=\n"}))
        self.assertFalse([f for f in report.findings if f.subject == ".env.example"])

    def test_unpinned_version_is_low_severity(self):
        report = audit(self._repo({"LICENSE": MIT_TEXT,
                                   "package.json": json.dumps({"dependencies": {"axios": "latest"}})}))
        findings = [f for f in report.findings if f.subject == "axios" and f.kind == "dependency"]
        self.assertTrue(findings)
        self.assertEqual(findings[0].severity, "low")

    def test_unknown_licenses_are_counted_and_warned(self):
        report = audit(self._repo({"LICENSE": MIT_TEXT,
                                   "requirements.txt": "some-internal-package==1.0\n"}))
        self.assertEqual(report.summary["unknown_licenses"], 1)
        self.assertTrue(any("unknown" in w for w in report.warnings))

    def test_report_always_states_it_is_not_legal_advice(self):
        report = audit(self._repo({"LICENSE": MIT_TEXT}))
        self.assertTrue(any("法律意见" in warning for warning in report.warnings))

    def test_summary_shape_is_stable(self):
        report = audit(self._repo({"LICENSE": MIT_TEXT}))
        for key in ("dependency_count", "manifest_count", "ecosystems",
                    "severity", "unknown_licenses", "resolved_licenses", "blocking"):
            self.assertIn(key, report.summary)

    def test_report_is_json_serialisable(self):
        report = audit(self._repo({"LICENSE": MIT_TEXT, "requirements.txt": "requests==2.31.0\n"}))
        raw = json.dumps(report.to_dict(), ensure_ascii=False)
        self.assertIn("requests", raw)

    def test_markdown_render_contains_key_sections(self):
        report = audit(self._repo({"LICENSE": MIT_TEXT, "requirements.txt": "requests==2.31.0\n"}))
        markdown = to_markdown(report)
        self.assertIn("# 依赖与许可证合规报告", markdown)
        self.assertIn("项目许可证", markdown)
        self.assertIn("requests", markdown)

    def test_missing_directory_raises_value_error(self):
        with self.assertRaises(ValueError):
            audit(Path("this-directory-does-not-exist-osg"))

    def test_polyglot_demo_detects_multiple_ecosystems(self):
        demo = Path(__file__).resolve().parents[1] / "examples" / "polyglot_demo"
        report = audit(demo)
        self.assertEqual(report.project_license, "MIT")
        self.assertIn("pypi", report.summary["ecosystems"])
        self.assertIn("npm", report.summary["ecosystems"])


if __name__ == "__main__":
    unittest.main()
