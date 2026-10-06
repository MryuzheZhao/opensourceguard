from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List


@dataclass
class CodeSymbol:
    path: str
    name: str
    kind: str
    start_line: int
    end_line: int
    signature: str = ""
    text: str = ""
    keywords: List[str] = field(default_factory=list)
    language: str = "python"
    # "parsed" for AST-derived symbols, "heuristic" for regex scanners.
    confidence: str = "parsed"


@dataclass
class Evidence:
    path: str
    start_line: int
    end_line: int
    reason: str
    score: float
    language: str = "python"
    confidence: str = "parsed"
    symbol: str = ""


@dataclass
class IssueAnalysis:
    issue: str
    issue_type: str
    severity: str
    keywords: List[str]
    expected_behavior: str
    actual_behavior: str


@dataclass
class SecurityFinding:
    rule_id: str
    severity: str
    path: str
    line: int
    message: str
    evidence: str
    recommendation: str
    language: str = "python"
    cwe: str = ""


@dataclass
class LicenseFinding:
    """A licence or dependency compliance observation."""

    kind: str          # "license" | "dependency" | "file"
    severity: str      # "high" | "medium" | "low" | "info"
    subject: str       # package name, file path or licence id
    message: str
    recommendation: str
    source: str = ""
    detected_license: str = ""


@dataclass
class ComplianceReport:
    repo: str
    project_license: str
    license_source: str
    license_confidence: str
    manifests: List[str]
    dependencies: List[Dict[str, Any]]
    findings: List[LicenseFinding]
    summary: Dict[str, Any]
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TestResult:
    command: List[str]
    return_code: int
    passed: bool
    stdout: str
    stderr: str
    stage: str = "baseline"
    timed_out: bool = False
    tests_run: int = 0
    failures: int = 0
    errors: int = 0
    skipped: int = 0
    infrastructure_error: bool = False


@dataclass
class AnalysisReport:
    repo: str
    issue: IssueAnalysis
    evidence: List[Evidence]
    reproduction_test: str
    patch_plan: str
    patch: str
    tests: List[TestResult]
    next_actions: List[str]
    security_findings: List[SecurityFinding] = field(default_factory=list)
    model_used: str = "heuristic"
    warnings: List[str] = field(default_factory=list)
    verification_status: str = "not_run"
    execution_mode: str = "skip"
    snapshot_sha256: str = ""
    patch_source: str = "none"
    security_findings_after: List[SecurityFinding] = field(default_factory=list)
    languages: Dict[str, int] = field(default_factory=dict)
    primary_language: str = ""
    evidence_confidence: str = "parsed"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
