"""Dependency and licence compliance auditing.

Fully offline and dependency-free. The module parses common manifests, detects
the project's own licence from ``LICENSE``/manifest metadata, and reports
licence-compatibility risks using a transparent compatibility matrix.

Important honesty boundary: dependency licences are only known when the manifest
declares them or the package appears in the small curated table below. Anything
else is reported as ``unknown`` rather than guessed, and the report says so.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .types import ComplianceReport, LicenseFinding

# --------------------------------------------------------------------------
# Licence identification
# --------------------------------------------------------------------------

# Distinctive phrases from licence texts -> SPDX identifier.
LICENSE_SIGNATURES: List[Tuple[str, str]] = [
    ("GNU AFFERO GENERAL PUBLIC LICENSE", "AGPL-3.0"),
    ("GNU LESSER GENERAL PUBLIC LICENSE", "LGPL-3.0"),
    ("GNU GENERAL PUBLIC LICENSE", "GPL-3.0"),
    ("MOZILLA PUBLIC LICENSE", "MPL-2.0"),
    ("APACHE LICENSE", "Apache-2.0"),
    ("MIT LICENSE", "MIT"),
    ("BSD 3-CLAUSE", "BSD-3-Clause"),
    ("BSD 2-CLAUSE", "BSD-2-Clause"),
    ("ISC LICENSE", "ISC"),
    ("THE UNLICENSE", "Unlicense"),
    ("CC0 1.0", "CC0-1.0"),
    ("ECLIPSE PUBLIC LICENSE", "EPL-2.0"),
]

# Normalisation for licence strings found in manifests.
LICENSE_ALIASES: Dict[str, str] = {
    "mit": "MIT", "mit license": "MIT", "expat": "MIT",
    "apache 2.0": "Apache-2.0", "apache-2.0": "Apache-2.0",
    "apache license 2.0": "Apache-2.0", "asl 2.0": "Apache-2.0", "apache2": "Apache-2.0",
    "bsd": "BSD-3-Clause", "bsd-3-clause": "BSD-3-Clause", "bsd 3-clause": "BSD-3-Clause",
    "bsd-2-clause": "BSD-2-Clause", "new bsd": "BSD-3-Clause",
    "gpl-3.0": "GPL-3.0", "gplv3": "GPL-3.0", "gpl v3": "GPL-3.0", "gpl3": "GPL-3.0",
    "gpl-2.0": "GPL-2.0", "gplv2": "GPL-2.0",
    "lgpl-3.0": "LGPL-3.0", "lgplv3": "LGPL-3.0", "lgpl-2.1": "LGPL-2.1",
    "agpl-3.0": "AGPL-3.0", "agplv3": "AGPL-3.0",
    "mpl-2.0": "MPL-2.0", "mpl 2.0": "MPL-2.0",
    "isc": "ISC", "unlicense": "Unlicense", "cc0-1.0": "CC0-1.0",
    "epl-2.0": "EPL-2.0", "proprietary": "Proprietary", "unlicensed": "Proprietary",
}

# Copyleft strength, used for the compatibility decision.
STRONG_COPYLEFT = {"GPL-2.0", "GPL-3.0", "AGPL-3.0"}
WEAK_COPYLEFT = {"LGPL-2.1", "LGPL-3.0", "MPL-2.0", "EPL-2.0"}
PERMISSIVE = {"MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC",
              "Unlicense", "CC0-1.0", "Zlib", "PSF-2.0"}

# Minimal curated table for very common packages whose manifests rarely travel
# with the dependency declaration. Deliberately small and auditable.
KNOWN_PACKAGE_LICENSES: Dict[str, str] = {
    # Python
    "requests": "Apache-2.0", "urllib3": "MIT", "certifi": "MPL-2.0",
    "pyyaml": "MIT", "numpy": "BSD-3-Clause", "pandas": "BSD-3-Clause",
    "flask": "BSD-3-Clause", "django": "BSD-3-Clause", "fastapi": "MIT",
    "click": "BSD-3-Clause", "jinja2": "BSD-3-Clause", "pytest": "MIT",
    "paramiko": "LGPL-2.1", "cryptography": "Apache-2.0", "chardet": "LGPL-2.1",
    "mysql-connector-python": "GPL-2.0", "pymysql": "MIT", "psycopg2": "LGPL-3.0",
    "scikit-learn": "BSD-3-Clause", "matplotlib": "PSF-2.0", "pillow": "MIT",
    # JavaScript
    "lodash": "MIT", "react": "MIT", "vue": "MIT", "express": "MIT",
    "axios": "MIT", "jest": "MIT", "typescript": "Apache-2.0",
    "webpack": "MIT", "eslint": "MIT", "left-pad": "WTFPL",
}

# Packages with well-known supply-chain or maintenance concerns.
RISKY_PACKAGES: Dict[str, str] = {
    "left-pad": "该包曾因从 npm 撤回导致大规模构建失败，功能可用 String.prototype.padStart 替代。",
    "request": "已于 2020 年正式废弃，不再接收安全修复，建议迁移到 undici 或 axios。",
    "node-uuid": "已废弃，请改用 uuid。",
    "event-stream": "历史上曾被注入恶意代码，请确认使用的版本与来源。",
    "colors": "曾因维护者主动注入死循环导致下游故障，建议锁定版本或改用 chalk。",
}


def normalize_license(raw: str) -> str:
    """Normalise a licence string to an SPDX-like identifier."""
    if not raw:
        return ""
    text = raw.strip().strip('"').strip("'")
    if not text:
        return ""
    lowered = text.lower()
    if lowered in LICENSE_ALIASES:
        return LICENSE_ALIASES[lowered]
    # Strip common decorations such as "MIT License", "Apache-2.0 OR MIT".
    cleaned = re.sub(r"\s*(?:license|licence)\s*$", "", lowered).strip()
    if cleaned in LICENSE_ALIASES:
        return LICENSE_ALIASES[cleaned]
    for part in re.split(r"\s+(?:or|and)\s+|/|,", cleaned):
        candidate = part.strip()
        if candidate in LICENSE_ALIASES:
            return LICENSE_ALIASES[candidate]
    return text[:60]


def detect_project_license(repo: Path) -> Tuple[str, str, str]:
    """Return (licence, source, confidence) for the project's own licence."""
    for name in ("LICENSE", "LICENSE.txt", "LICENSE.md", "LICENCE",
                 "COPYING", "COPYING.txt", "LICENSE-MIT", "LICENSE-APACHE"):
        path = repo / name
        if not path.is_file():
            continue
        try:
            head = path.read_text(encoding="utf-8", errors="replace")[:4000].upper()
        except OSError:
            continue
        for signature, spdx in LICENSE_SIGNATURES:
            if signature in head:
                return spdx, name, "high"
        return "unknown", name, "low"
    # Fall back to manifest metadata.
    package_json = repo / "package.json"
    if package_json.is_file():
        try:
            data = json.loads(package_json.read_text(encoding="utf-8"))
            declared = data.get("license") or data.get("licence")
            if isinstance(declared, str) and declared:
                return normalize_license(declared), "package.json", "medium"
        except (OSError, json.JSONDecodeError):
            pass
    pyproject = repo / "pyproject.toml"
    if pyproject.is_file():
        try:
            text = pyproject.read_text(encoding="utf-8")
        except OSError:
            text = ""
        match = re.search(r"(?m)^\s*license\s*=\s*[\{\"']([^\"'\}]+)", text)
        if match:
            return normalize_license(match.group(1)), "pyproject.toml", "medium"
    return "", "", "none"


# --------------------------------------------------------------------------
# Manifest parsing
# --------------------------------------------------------------------------

_REQ_LINE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:\[[^\]]*\])?\s*([=<>!~]=?[^;#]*)?")


def _parse_requirements(path: Path) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return entries
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "-r", "--", "git+", "http")):
            continue
        match = _REQ_LINE.match(stripped)
        if not match:
            continue
        entries.append({
            "name": match.group(1),
            "version": (match.group(2) or "").strip() or "*",
            "ecosystem": "pypi",
            "scope": "runtime",
            "manifest": path.name,
        })
    return entries


def _parse_package_json(path: Path) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return entries
    for key, scope in (("dependencies", "runtime"), ("devDependencies", "dev"),
                       ("peerDependencies", "peer"), ("optionalDependencies", "optional")):
        block = data.get(key)
        if not isinstance(block, dict):
            continue
        for name, version in block.items():
            entries.append({
                "name": str(name),
                "version": str(version) or "*",
                "ecosystem": "npm",
                "scope": scope,
                "manifest": path.name,
            })
    return entries


def _parse_pyproject(path: Path) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return entries
    block = re.search(r"(?ms)^\s*dependencies\s*=\s*\[(.*?)\]", text)
    if block:
        for raw in re.findall(r"[\"']([^\"']+)[\"']", block.group(1)):
            match = _REQ_LINE.match(raw.strip())
            if match:
                entries.append({
                    "name": match.group(1),
                    "version": (match.group(2) or "").strip() or "*",
                    "ecosystem": "pypi",
                    "scope": "runtime",
                    "manifest": path.name,
                })
    return entries


def _parse_go_mod(path: Path) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return entries
    in_block = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("require ("):
            in_block = True
            continue
        if in_block and stripped == ")":
            in_block = False
            continue
        target = stripped
        if stripped.startswith("require "):
            target = stripped[len("require "):].strip()
        elif not in_block:
            continue
        if not target or target.startswith("//"):
            continue
        parts = target.split()
        if len(parts) >= 2:
            entries.append({
                "name": parts[0],
                "version": parts[1],
                "ecosystem": "go",
                "scope": "indirect" if "// indirect" in line else "runtime",
                "manifest": path.name,
            })
    return entries


def _parse_cargo_toml(path: Path) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return entries
    scope: Optional[str] = None
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("["):
            if stripped in {"[dependencies]", "[dependencies.workspace]"}:
                scope = "runtime"
            elif stripped == "[dev-dependencies]":
                scope = "dev"
            elif stripped == "[build-dependencies]":
                scope = "build"
            else:
                scope = None
            continue
        if scope is None or not stripped or stripped.startswith("#"):
            continue
        match = re.match(r"^([A-Za-z0-9_-]+)\s*=\s*(.+)$", stripped)
        if not match:
            continue
        version = match.group(2).strip()
        inline = re.search(r'version\s*=\s*"([^"]+)"', version)
        if inline:
            version = inline.group(1)
        entries.append({
            "name": match.group(1),
            "version": version.strip('"'),
            "ecosystem": "cargo",
            "scope": scope,
            "manifest": path.name,
        })
    return entries


def _parse_pom(path: Path) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return entries
    for block in re.findall(r"(?s)<dependency>(.*?)</dependency>", text):
        artifact = re.search(r"<artifactId>([^<]+)</artifactId>", block)
        version = re.search(r"<version>([^<]+)</version>", block)
        scope = re.search(r"<scope>([^<]+)</scope>", block)
        if artifact:
            entries.append({
                "name": artifact.group(1).strip(),
                "version": (version.group(1).strip() if version else "*"),
                "ecosystem": "maven",
                "scope": (scope.group(1).strip() if scope else "runtime"),
                "manifest": path.name,
            })
    return entries


MANIFEST_PARSERS = {
    "requirements.txt": _parse_requirements,
    "requirements-dev.txt": _parse_requirements,
    "package.json": _parse_package_json,
    "pyproject.toml": _parse_pyproject,
    "go.mod": _parse_go_mod,
    "Cargo.toml": _parse_cargo_toml,
    "pom.xml": _parse_pom,
}


# --------------------------------------------------------------------------
# Compatibility analysis
# --------------------------------------------------------------------------

def license_conflict(project: str, dependency: str) -> Optional[Tuple[str, str, str]]:
    """Check one dependency licence against the project licence.

    Returns (severity, message, recommendation) or None when compatible.
    This encodes the common, widely-documented direction of incompatibility:
    a permissively licensed project cannot distribute strong-copyleft code
    without adopting that licence.
    """
    if not project or not dependency or dependency == "unknown":
        return None
    if project == dependency:
        return None
    if dependency in STRONG_COPYLEFT and project in PERMISSIVE:
        return (
            "high",
            f"依赖为 {dependency}（强 Copyleft），而项目声明为 {project}（宽松许可）。"
            "以二进制或源码形式分发时，整体作品通常需要采用同样的 Copyleft 许可。",
            f"改用等价的宽松许可依赖，或把项目许可改为 {dependency}，或将该依赖隔离为独立进程/服务后通过接口调用。",
        )
    if dependency in STRONG_COPYLEFT and project in WEAK_COPYLEFT:
        return (
            "high",
            f"依赖为 {dependency}（强 Copyleft），与项目的 {project}（弱 Copyleft）在分发时可能不兼容。",
            "请法务确认分发形式，或替换该依赖。",
        )
    if dependency in WEAK_COPYLEFT and project in PERMISSIVE:
        return (
            "medium",
            f"依赖为 {dependency}（弱 Copyleft）。动态链接通常可接受，"
            f"但静态链接或修改其源码后，需要按 {dependency} 的条款开放相应部分。",
            "保持动态依赖、不修改其源码；如需修改请单独开源该部分。",
        )
    if dependency == "Proprietary":
        return (
            "high",
            "依赖为专有许可，无法随开源项目自由分发。",
            "确认商业授权范围，或替换为开源实现。",
        )
    if dependency == "WTFPL":
        return (
            "low",
            "依赖使用 WTFPL，部分企业合规流程不接受该许可。",
            "若面向企业用户分发，建议替换为 MIT/Apache-2.0 等主流许可。",
        )
    if dependency == "Apache-2.0" and project == "GPL-2.0":
        return (
            "high",
            "Apache-2.0 的专利条款与 GPL-2.0 被广泛认为不兼容。",
            "升级项目许可到 GPL-3.0，或替换该依赖。",
        )
    return None


def audit(repo: Path) -> ComplianceReport:
    """Run a full offline compliance audit on a repository."""
    repo = repo.resolve()
    if not repo.is_dir():
        raise ValueError(f"仓库目录不存在：{repo}")

    project_license, license_source, license_confidence = detect_project_license(repo)
    findings: List[LicenseFinding] = []
    warnings: List[str] = []

    if not project_license:
        findings.append(LicenseFinding(
            kind="file", severity="high", subject="LICENSE",
            message="仓库没有 LICENSE 文件，也没有在清单中声明许可证。",
            recommendation="添加 LICENSE 文件（个人项目通常选 MIT 或 Apache-2.0），并在 README 中说明。",
            source="repository root",
        ))
    elif project_license == "unknown":
        findings.append(LicenseFinding(
            kind="license", severity="medium", subject=license_source,
            message="找到了许可证文件，但内容无法匹配任何已知的标准许可证。",
            recommendation="使用标准 SPDX 许可证全文，避免自定义条款造成下游使用障碍。",
            source=license_source, detected_license="unknown",
        ))

    # Collect dependencies from every manifest found in the repository root and
    # one level of subdirectories (covers common monorepo layouts).
    manifests: List[str] = []
    dependencies: List[Dict[str, Any]] = []
    search_paths = [repo] + [p for p in sorted(repo.iterdir()) if p.is_dir()
                             and p.name not in {".git", "node_modules", ".venv", "venv",
                                                "__pycache__", "dist", "build", "target"}][:20]
    for directory in search_paths:
        for name, parser in MANIFEST_PARSERS.items():
            path = directory / name
            if not path.is_file():
                continue
            relative = str(path.relative_to(repo)).replace("\\", "/")
            manifests.append(relative)
            for entry in parser(path):
                entry["manifest"] = relative
                dependencies.append(entry)

    if not manifests:
        warnings.append("未找到任何依赖清单（requirements.txt / package.json / pyproject.toml / go.mod / Cargo.toml / pom.xml）。")

    # Deduplicate by (ecosystem, name) keeping the first declaration.
    seen: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for entry in dependencies:
        key = (entry["ecosystem"], entry["name"].lower())
        if key not in seen:
            seen[key] = entry
    unique = list(seen.values())

    unknown_count = 0
    for entry in unique:
        declared = KNOWN_PACKAGE_LICENSES.get(entry["name"].lower(), "")
        entry["license"] = declared or "unknown"
        entry["license_source"] = "curated table" if declared else "not resolved offline"
        if not declared:
            unknown_count += 1
            continue
        conflict = license_conflict(project_license, declared)
        if conflict:
            severity, message, recommendation = conflict
            findings.append(LicenseFinding(
                kind="license", severity=severity, subject=entry["name"],
                message=message, recommendation=recommendation,
                source=entry["manifest"], detected_license=declared,
            ))

    for entry in unique:
        note = RISKY_PACKAGES.get(entry["name"].lower())
        if note:
            findings.append(LicenseFinding(
                kind="dependency", severity="medium", subject=entry["name"],
                message=note,
                recommendation="评估是否可以移除或替换该依赖，并锁定版本。",
                source=entry["manifest"], detected_license=entry.get("license", ""),
            ))
        if entry["version"] in {"*", "latest", ""} or entry["version"].startswith("^0.0"):
            findings.append(LicenseFinding(
                kind="dependency", severity="low", subject=entry["name"],
                message=f"依赖版本约束为 {entry['version'] or '空'}，构建结果不可复现。",
                recommendation="使用明确的版本范围，并提交 lock 文件。",
                source=entry["manifest"], detected_license=entry.get("license", ""),
            ))

    # Repository hygiene checks that reviewers and competition judges look for.
    for name, message, recommendation, severity in (
        ("README.md", "缺少 README，使用者无法快速了解项目。",
         "添加 README，说明用途、安装方式、快速开始和许可证。", "medium"),
        ("CONTRIBUTING.md", "缺少贡献指南，新贡献者不知道如何参与。",
         "添加 CONTRIBUTING.md，说明开发环境、提交规范和评审流程。", "low"),
        ("CODE_OF_CONDUCT.md", "缺少行为准则，社区协作缺少共同约定。",
         "可直接采用 Contributor Covenant。", "low"),
        ("SECURITY.md", "缺少安全披露政策，漏洞报告没有明确渠道。",
         "添加 SECURITY.md，说明私下报告渠道和响应时限。", "low"),
        (".gitignore", "缺少 .gitignore，容易误提交虚拟环境、缓存或凭据。",
         "添加 .gitignore，至少排除 .env、虚拟环境和构建产物。", "medium"),
    ):
        if not (repo / name).exists():
            findings.append(LicenseFinding(
                kind="file", severity=severity, subject=name,
                message=message, recommendation=recommendation, source="repository root",
            ))

    # Credential files that must never be committed.
    for candidate in sorted(repo.glob("*")):
        if candidate.is_file() and (candidate.name.startswith(".env") and candidate.name != ".env.example"
                                    or candidate.suffix.lower() in {".pem", ".key", ".p12", ".pfx"}):
            findings.append(LicenseFinding(
                kind="file", severity="high", subject=candidate.name,
                message="仓库根目录存在疑似凭据文件，一旦提交将泄露密钥。",
                recommendation="确认该文件已被 .gitignore 排除；若已提交，请轮换凭据并清理历史。",
                source="repository root",
            ))

    if unknown_count:
        warnings.append(
            f"{unknown_count} 个依赖的许可证无法离线确定，已标记为 unknown，"
            "不代表它们没有问题；如需完整结论请联网查询各包的 SPDX 信息。"
        )
    warnings.append("本审计基于清单声明与内置对照表，属于快速初筛，不构成法律意见。")

    severity_counts = {"high": 0, "medium": 0, "low": 0, "info": 0}
    for finding in findings:
        if finding.severity in severity_counts:
            severity_counts[finding.severity] += 1

    ecosystems: Dict[str, int] = {}
    for entry in unique:
        ecosystems[entry["ecosystem"]] = ecosystems.get(entry["ecosystem"], 0) + 1

    summary = {
        "dependency_count": len(unique),
        "manifest_count": len(manifests),
        "ecosystems": ecosystems,
        "severity": severity_counts,
        "unknown_licenses": unknown_count,
        "resolved_licenses": len(unique) - unknown_count,
        "blocking": severity_counts["high"] > 0,
    }

    return ComplianceReport(
        repo=str(repo),
        project_license=project_license,
        license_source=license_source,
        license_confidence=license_confidence,
        manifests=manifests,
        dependencies=unique,
        findings=findings,
        summary=summary,
        warnings=warnings,
    )


def to_markdown(report: ComplianceReport) -> str:
    """Render a compliance report as reviewable Markdown."""
    lines = ["# 依赖与许可证合规报告", "", f"- 仓库：`{report.repo}`"]
    license_text = report.project_license or "未声明"
    lines.append(f"- 项目许可证：**{license_text}**"
                 + (f"（来源 {report.license_source}，置信度 {report.license_confidence}）"
                    if report.license_source else ""))
    lines.append(f"- 依赖清单：{', '.join(report.manifests) if report.manifests else '未找到'}")
    lines.append(f"- 依赖数量：{report.summary['dependency_count']}"
                 f"（已解析许可证 {report.summary['resolved_licenses']}，"
                 f"未知 {report.summary['unknown_licenses']}）")
    severity = report.summary["severity"]
    lines.append(f"- 问题统计：高 {severity['high']} · 中 {severity['medium']} · 低 {severity['low']}")
    lines.append("")

    if report.findings:
        lines += ["## 发现的问题", ""]
        order = {"high": 0, "medium": 1, "low": 2, "info": 3}
        for finding in sorted(report.findings, key=lambda f: order.get(f.severity, 9)):
            label = {"high": "高", "medium": "中", "low": "低", "info": "提示"}.get(finding.severity, finding.severity)
            lines.append(f"### [{label}] {finding.subject}")
            lines.append(f"- 类型：{finding.kind}")
            if finding.detected_license:
                lines.append(f"- 识别到的许可证：{finding.detected_license}")
            lines.append(f"- 说明：{finding.message}")
            lines.append(f"- 建议：{finding.recommendation}")
            if finding.source:
                lines.append(f"- 来源：{finding.source}")
            lines.append("")
    else:
        lines += ["## 发现的问题", "", "未发现明显的合规问题。", ""]

    if report.dependencies:
        lines += ["## 依赖清单", "", "| 名称 | 版本 | 生态 | 范围 | 许可证 |", "|---|---|---|---|---|"]
        for entry in report.dependencies[:80]:
            lines.append(f"| {entry['name']} | {entry['version']} | {entry['ecosystem']} "
                         f"| {entry['scope']} | {entry.get('license', 'unknown')} |")
        if len(report.dependencies) > 80:
            lines.append(f"| … 其余 {len(report.dependencies) - 80} 个依赖略 | | | | |")
        lines.append("")

    if report.warnings:
        lines += ["## 边界说明", ""] + [f"- {warning}" for warning in report.warnings] + [""]
    return "\n".join(lines)
