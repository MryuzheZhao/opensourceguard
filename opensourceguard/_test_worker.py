"""Runs inside a repository subprocess/container; never imported into the server."""
from __future__ import annotations

import os
import sys
sys.path = [item for item in sys.path if os.path.abspath(item or ".") != os.path.dirname(os.path.abspath(__file__))]

import io
import json
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

PREFIX = "OSG_TEST_RESULT="
root = Path.cwd()
sys.path.insert(0, str(root))
if (root / "src").is_dir():
    sys.path.insert(0, str(root / "src"))
target = sys.argv[1] if len(sys.argv) > 1 else ""
framework = sys.argv[2] if len(sys.argv) > 2 else "unittest"
summary = dict(tests_run=0, failures=0, errors=0, skipped=0, infrastructure_error=False)
try:
    if framework == "pytest":
        import pytest
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            xml_path = Path(tmp) / "results.xml"
            code = int(pytest.main(["-q", "-p", "no:cacheprovider", "--junitxml=" + str(xml_path)] + ([target] if target else [])))
            if xml_path.exists():
                suites = ET.parse(xml_path).getroot().iter("testsuite")
                for suite in suites:
                    for key, attr in [("tests_run", "tests"), ("failures", "failures"), ("errors", "errors"), ("skipped", "skipped")]:
                        summary[key] += int(suite.get(attr, 0))
            summary["infrastructure_error"] = code not in {0, 1} or summary["tests_run"] == 0
    else:
        loader = unittest.TestLoader()
        if target:
            import importlib.util
            target_path = root / target
            spec = importlib.util.spec_from_file_location("osg_reproduction", target_path)
            module = importlib.util.module_from_spec(spec)
            sys.path.insert(0, str(root))
            spec.loader.exec_module(module)
            suite = loader.loadTestsFromModule(module)
        else:
            suite = loader.discover(str(root), pattern="test*.py", top_level_dir=str(root))
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        summary.update(tests_run=result.testsRun, failures=len(result.failures), errors=len(result.errors), skipped=len(result.skipped))
        summary["infrastructure_error"] = bool(loader.errors) or result.testsRun == 0
        code = 0 if result.wasSuccessful() and result.testsRun > len(result.skipped) else 1
except BaseException as exc:
    import traceback
    traceback.print_exc()
    summary["infrastructure_error"] = True
    code = 2
print(PREFIX + json.dumps(summary), flush=True)
raise SystemExit(code)
