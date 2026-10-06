"""Transparent, dependency-free multi-language security rules.

Every rule is an explicit regex with a CWE reference, a human-readable message
and a concrete remediation. This is a fast first pass by design; a production
deployment can add Semgrep/Bandit/CodeQL as a second pass. Findings are always
presented as candidates requiring human review, never as confirmed vulnerabilities.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

from .languages import language_of
from .types import SecurityFinding

# (rule_id, severity, pattern, message, recommendation, cwe)
Rule = Tuple[str, str, "re.Pattern[str]", str, str, str]


PYTHON_RULES: List[Rule] = [
    ("PY-EVAL", "high", re.compile(r"\beval\s*\("),
     "动态执行 eval() 可能执行不受信任的输入。",
     "改用显式解析或白名单映射，并对输入做严格校验。", "CWE-95"),
    ("PY-EXEC", "high", re.compile(r"\bexec\s*\("),
     "动态执行 exec() 可能执行不受信任的输入。",
     "移除动态执行，或将可执行操作限制在显式白名单。", "CWE-95"),
    ("PY-SHELL", "high", re.compile(r"subprocess\.[A-Za-z_]+\([^\n]*shell\s*=\s*True"),
     "subprocess 使用 shell=True，可能造成命令注入。",
     "传入参数列表并保持 shell=False；必要时校验每个参数。", "CWE-78"),
    ("PY-OS-SYSTEM", "high", re.compile(r"\bos\.system\s*\("),
     "os.system() 直接交给 shell 执行字符串。",
     "改用 subprocess 参数列表，并避免把用户输入拼接进命令。", "CWE-78"),
    ("PY-PICKLE", "high", re.compile(r"\bpickle\.(load|loads)\s*\("),
     "pickle 反序列化不可信数据可能执行任意代码。",
     "使用安全的数据格式，或在可信边界内验证来源后再反序列化。", "CWE-502"),
    ("PY-SECRET", "high", re.compile(r"(?i)\b(api[_-]?(?:key|token)|secret|password|passwd|token)\s*=\s*['\"][^'\"]{8,}['\"]"),
     "源码中疑似包含硬编码凭据。",
     "撤销并轮换凭据，改用环境变量或密钥管理服务。", "CWE-798"),
    ("PY-YAML-LOAD", "medium", re.compile(r"\byaml\.load\s*\("),
     "yaml.load() 默认可能构造任意 Python 对象。",
     "使用 yaml.safe_load()，除非有明确且受控的构造需求。", "CWE-502"),
    ("PY-SQL-FORMAT", "high", re.compile(
        r"(?i)(?:execute|executemany|executescript)\s*\(\s*(?:f[\"']|[\"'])[^\"']*"
        r"\b(?:SELECT|INSERT\s+INTO|UPDATE|DELETE\s+FROM|DROP|ALTER)\b"
        r"[^)]*?(?:%\s*[\w(\[]|\.format\s*\(|\+\s*\w|\{\w*\})"),
     "SQL 语句疑似使用字符串拼接或格式化构造。",
     "改用参数化查询（占位符 + 参数元组），不要把变量拼进 SQL。", "CWE-89"),
    ("PY-SQL-FSTRING", "high", re.compile(
        r"(?i)(?:execute|executemany)\s*\(\s*f[\"'][^\"']*"
        r"\b(?:SELECT|INSERT\s+INTO|UPDATE|DELETE\s+FROM)\b"),
     "SQL 语句使用 f-string 构造，变量会直接进入语句文本。",
     "改用参数化查询占位符，把变量作为参数传入。", "CWE-89"),
    ("PY-VERIFY-OFF", "high", re.compile(r"verify\s*=\s*False"),
     "HTTP 请求关闭了 TLS 证书校验。",
     "保持 verify=True；内网自签证书应配置受信任的 CA 包。", "CWE-295"),
    ("PY-MD5", "medium", re.compile(r"hashlib\.(md5|sha1)\s*\("),
     "使用了已被攻破的哈希算法（MD5/SHA1）。",
     "口令请用 bcrypt/argon2，完整性校验请用 SHA-256 及以上。", "CWE-327"),
    ("PY-TEMPFILE", "medium", re.compile(r"\btempfile\.mktemp\s*\("),
     "tempfile.mktemp() 存在竞态条件风险。",
     "改用 tempfile.mkstemp() 或 NamedTemporaryFile。", "CWE-377"),
    ("PY-ASSERT-AUTH", "low", re.compile(r"(?i)^\s*assert\s+.*(?:auth|permission|is_admin|token)"),
     "使用 assert 做权限校验，在 -O 优化模式下会被移除。",
     "改用显式条件判断并抛出异常。", "CWE-617"),
    ("PY-DEBUG", "medium", re.compile(r"(?i)\bdebug\s*=\s*True"),
     "疑似在代码中开启调试模式。",
     "调试开关应来自环境变量，生产环境必须关闭。", "CWE-489"),
    ("PY-BIND-ALL", "medium", re.compile(r"['\"]0\.0\.0\.0['\"]"),
     "服务绑定到 0.0.0.0，会暴露在所有网络接口。",
     "本地工具应绑定 127.0.0.1；对外服务需配合防火墙和鉴权。", "CWE-1327"),
]

JS_RULES: List[Rule] = [
    ("JS-EVAL", "high", re.compile(r"\beval\s*\("),
     "eval() 会执行任意 JavaScript。",
     "改用 JSON.parse 或显式分支逻辑。", "CWE-95"),
    ("JS-NEW-FUNCTION", "high", re.compile(r"\bnew\s+Function\s*\("),
     "new Function() 等价于动态代码执行。",
     "移除动态构造函数，改用受控映射。", "CWE-95"),
    ("JS-INNERHTML", "medium", re.compile(r"\.innerHTML\s*=(?!=)"),
     "直接写入 innerHTML 可能导致 XSS。",
     "改用 textContent，或对插入的动态内容做转义/净化。", "CWE-79"),
    ("JS-DOC-WRITE", "medium", re.compile(r"\bdocument\.write\s*\("),
     "document.write() 容易引入 XSS 并阻塞渲染。",
     "改用 DOM API 创建节点。", "CWE-79"),
    ("JS-CHILD-PROCESS", "high", re.compile(r"(?:child_process\.)?exec(?:Sync)?\s*\(\s*[`\"'].*\$\{"),
     "shell 命令中插入了变量，可能造成命令注入。",
     "改用 execFile/spawn 并传入参数数组。", "CWE-78"),
    ("JS-SECRET", "high", re.compile(r"(?i)\b(?:api[_-]?key|apikey|secret|password|access[_-]?token)\s*[:=]\s*['\"][^'\"]{8,}['\"]"),
     "源码中疑似包含硬编码凭据。",
     "撤销并轮换凭据，改用环境变量或服务端代理。", "CWE-798"),
    ("JS-TLS-OFF", "high", re.compile(r"rejectUnauthorized\s*:\s*false|NODE_TLS_REJECT_UNAUTHORIZED\s*=\s*['\"]?0"),
     "关闭了 TLS 证书校验。",
     "保持证书校验开启，自签证书应配置 CA。", "CWE-295"),
    ("JS-MATH-RANDOM-TOKEN", "medium", re.compile(r"(?i)(?:token|secret|nonce|password|salt)\s*[:=][^\n]*Math\.random\s*\("),
     "使用 Math.random() 生成安全敏感的随机值。",
     "改用 crypto.randomUUID() 或 crypto.getRandomValues()。", "CWE-338"),
    ("JS-POSTMESSAGE", "medium", re.compile(r"postMessage\s*\([^,]+,\s*['\"]\*['\"]"),
     "postMessage 使用通配目标源。",
     "显式指定目标 origin，并在接收端校验 event.origin。", "CWE-346"),
]

JAVA_RULES: List[Rule] = [
    ("JAVA-RUNTIME-EXEC", "high", re.compile(r"Runtime\.getRuntime\(\)\.exec\s*\("),
     "Runtime.exec() 执行外部命令，存在注入风险。",
     "改用 ProcessBuilder 并传入参数列表，校验每个参数。", "CWE-78"),
    ("JAVA-DESERIALIZE", "high", re.compile(r"new\s+ObjectInputStream\s*\("),
     "Java 原生反序列化不可信数据可导致 RCE。",
     "改用 JSON 等数据格式，或配置反序列化白名单过滤器。", "CWE-502"),
    ("JAVA-SQL-CONCAT", "high", re.compile(r"(?i)(?:executeQuery|executeUpdate|createStatement\(\)\s*\.\s*execute\w*)\s*\(\s*\"[^\"]*\"\s*\+"),
     "SQL 语句使用字符串拼接。",
     "改用 PreparedStatement 占位符绑定参数。", "CWE-89"),
    ("JAVA-SECRET", "high", re.compile(r"(?i)(?:String|final\s+String)\s+\w*(?:password|secret|apikey|token)\w*\s*=\s*\"[^\"]{8,}\""),
     "源码中疑似包含硬编码凭据。",
     "改用配置中心、环境变量或密钥管理服务。", "CWE-798"),
    ("JAVA-XXE", "medium", re.compile(r"DocumentBuilderFactory\.newInstance\s*\(\s*\)"),
     "XML 解析器未显式禁用外部实体，可能存在 XXE。",
     "设置 FEATURE_SECURE_PROCESSING 并禁用 doctype 声明。", "CWE-611"),
    ("JAVA-WEAK-HASH", "medium", re.compile(r"MessageDigest\.getInstance\s*\(\s*\"(?i:md5|sha-?1)\""),
     "使用了已被攻破的哈希算法。",
     "改用 SHA-256 及以上；口令散列请用 bcrypt/argon2。", "CWE-327"),
    ("JAVA-TRUST-ALL", "high", re.compile(r"(?i)checkServerTrusted\s*\([^)]*\)\s*\{\s*\}"),
     "TrustManager 实现为空，等于信任所有证书。",
     "实现真实的证书校验逻辑或使用默认 TrustManager。", "CWE-295"),
]

GO_RULES: List[Rule] = [
    ("GO-EXEC", "high", re.compile(r"exec\.Command\s*\(\s*\"(?:sh|bash|cmd|powershell)\""),
     "通过 shell 执行拼接命令，存在注入风险。",
     "直接调用目标程序并传入参数切片，不经过 shell。", "CWE-78"),
    ("GO-TLS-SKIP", "high", re.compile(r"InsecureSkipVerify\s*:\s*true"),
     "关闭了 TLS 证书校验。",
     "移除该配置；自签证书应加入 RootCAs。", "CWE-295"),
    ("GO-SQL-CONCAT", "high", re.compile(r"(?i)(?:Query|Exec|QueryRow)\s*\(\s*(?:\"[^\"]*\"\s*\+|fmt\.Sprintf)"),
     "SQL 语句使用字符串拼接或 Sprintf 构造。",
     "改用 ? / $1 占位符并传入参数。", "CWE-89"),
    ("GO-SQL-SPRINTF", "high", re.compile(r"(?i)fmt\.Sprintf\s*\(\s*\"[^\"]*\b(?:SELECT|INSERT\s+INTO|UPDATE|DELETE\s+FROM)\b"),
     "使用 fmt.Sprintf 拼接 SQL 语句，存在注入风险。",
     "改用 ? / $1 占位符并把变量作为查询参数传入。", "CWE-89"),
    ("GO-SECRET", "high", re.compile(r"(?i)\b\w*(?:password|secret|apikey|api_key|token)\w*\s*(?::=|=)\s*\"[^\"]{8,}\""),
     "源码中疑似包含硬编码凭据。",
     "改用环境变量或密钥管理服务。", "CWE-798"),
    ("GO-WEAK-HASH", "medium", re.compile(r"(?:md5|sha1)\.New\s*\(\s*\)|crypto/(?:md5|sha1)"),
     "使用了已被攻破的哈希算法。",
     "改用 crypto/sha256 及以上。", "CWE-327"),
    ("GO-MATH-RAND", "medium", re.compile(r"(?i)(?:token|secret|key|nonce|salt)[^\n]*math/rand|math/rand[^\n]*(?:token|secret|key)"),
     "使用 math/rand 生成安全敏感的随机值。",
     "改用 crypto/rand。", "CWE-338"),
]

RUST_RULES: List[Rule] = [
    ("RS-UNSAFE", "medium", re.compile(r"^\s*unsafe\s*\{|^\s*(?:pub\s+)?unsafe\s+fn\b"),
     "使用了 unsafe 代码块，绕过了编译器的内存安全保证。",
     "尽量用安全抽象替代；必须保留时写明安全性约束注释。", "CWE-119"),
    ("RS-UNWRAP", "low", re.compile(r"\.unwrap\s*\(\s*\)|\.expect\s*\("),
     "unwrap()/expect() 在错误路径上会直接 panic。",
     "库代码应返回 Result，让调用方决定如何处理错误。", "CWE-248"),
    ("RS-COMMAND", "high", re.compile(r"Command::new\s*\(\s*\"(?:sh|bash|cmd|powershell)\""),
     "通过 shell 执行命令，存在注入风险。",
     "直接调用目标程序并使用 .arg() 传参。", "CWE-78"),
    ("RS-SECRET", "high", re.compile(r"(?i)\blet\s+\w*(?:password|secret|api_key|token)\w*\s*(?::\s*&?str\s*)?=\s*\"[^\"]{8,}\""),
     "源码中疑似包含硬编码凭据。",
     "改用环境变量或密钥管理服务。", "CWE-798"),
    ("RS-DANGER-ACCEPT", "high", re.compile(r"danger_accept_invalid_certs\s*\(\s*true\s*\)"),
     "关闭了 TLS 证书校验。",
     "移除该调用；自签证书应显式添加为受信任根证书。", "CWE-295"),
]

SHELL_RULES: List[Rule] = [
    ("SH-CURL-PIPE", "high", re.compile(r"curl[^\n|]*\|\s*(?:sudo\s+)?(?:ba)?sh"),
     "从网络下载脚本并直接执行。",
     "先下载、校验哈希或签名，人工检查后再执行。", "CWE-494"),
    ("SH-EVAL", "high", re.compile(r"^\s*eval\s+"),
     "eval 会执行拼接出来的命令字符串。",
     "改用数组和显式分支，避免动态拼接命令。", "CWE-78"),
    ("SH-RM-RF-VAR", "high", re.compile(r"rm\s+-[a-zA-Z]*r[a-zA-Z]*f?\s+[\"']?\$"),
     "使用变量作为递归删除的路径，变量为空时可能删除意外目录。",
     "校验变量非空并使用绝对路径，加上 -- 分隔参数。", "CWE-78"),
    ("SH-CHMOD-777", "medium", re.compile(r"chmod\s+(?:-R\s+)?0?777"),
     "赋予了任何用户可读写执行的权限。",
     "按最小权限原则设置，例如 755 或 644。", "CWE-732"),
    ("SH-SECRET", "high", re.compile(r"(?i)\b(?:export\s+)?\w*(?:password|secret|api_key|token)\w*=['\"]?[^\s'\"$]{8,}"),
     "脚本中疑似包含硬编码凭据。",
     "改用凭据文件（权限 600）或密钥管理服务。", "CWE-798"),
]

GENERIC_SECRET_RULES: List[Rule] = [
    ("GEN-PRIVATE-KEY", "high", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----"),
     "文件中包含私钥内容。",
     "立即移出版本库、轮换密钥，并把路径加入 .gitignore。", "CWE-798"),
    ("GEN-AWS-KEY", "high", re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
     "疑似 AWS Access Key ID。",
     "立即在 AWS 控制台停用并轮换该凭据。", "CWE-798"),
    ("GEN-GITHUB-PAT", "high", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
     "疑似 GitHub 个人访问令牌。",
     "立即在 GitHub 设置中吊销该令牌。", "CWE-798"),
    ("GEN-SLACK-TOKEN", "high", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
     "疑似 Slack 令牌。",
     "立即吊销并轮换该令牌。", "CWE-798"),
    ("GEN-JWT", "medium", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
     "疑似硬编码的 JWT。",
     "确认是否为真实令牌；测试数据请改用明显的占位值。", "CWE-798"),
]

RULES_BY_LANGUAGE: Dict[str, List[Rule]] = {
    "python": PYTHON_RULES,
    "javascript": JS_RULES,
    "typescript": JS_RULES,
    "java": JAVA_RULES,
    "kotlin": JAVA_RULES,
    "go": GO_RULES,
    "rust": RUST_RULES,
    "shell": SHELL_RULES,
}

# Backwards compatibility: the original module exported a 5-tuple RULES list for
# Python. Existing callers and tests keep working against Python rules.
RULES = [(rule[0], rule[1], rule[2], rule[3], rule[4]) for rule in PYTHON_RULES]

SKIP_PARTS = {".git", ".venv", "venv", "__pycache__", "node_modules", ".pytest_cache",
              "dist", "build", "target", "vendor", "coverage", ".mypy_cache", ".tox"}

# The scanner's own rule table is data, not vulnerable application code.
SELF_PATHS = ("opensourceguard/security.py", "opensourceguard/languages.py")

# Files where a matched secret is almost certainly an example, not a live credential.
EXAMPLE_MARKERS = ("example", "sample", "template", "fixture", "mock", ".md", "test")


def _iter_scannable_files(repo: Path) -> Iterable[Tuple[Path, str]]:
    count = 0
    for path in sorted(repo.rglob("*")):
        if count >= 1500:
            return
        if not path.is_file() or path.is_symlink():
            continue
        if any(part in SKIP_PARTS for part in path.parts):
            continue
        language = language_of(path)
        if language is None:
            # Still scan small config/text files for leaked credentials.
            if path.suffix.lower() not in {".json", ".yaml", ".yml", ".toml", ".ini",
                                           ".cfg", ".env", ".properties", ".xml", ".txt"}:
                continue
            language = "config"
        try:
            if path.stat().st_size > 800_000:
                continue
        except OSError:
            continue
        count += 1
        yield path, language


def _is_suppressed(line: str) -> bool:
    lowered = line.lower()
    return "osg:ignore" in lowered or "nosec" in lowered or "noqa: s" in lowered


# Sanitiser / escaping helpers. When every interpolation on an innerHTML line is
# wrapped in one of these, the line is not a credible XSS sink and reporting it
# would be a false positive that trains users to ignore the scanner.
_ESCAPE_HELPERS = re.compile(
    r"\b(?:escapeHtml|escapeHTML|escape|sanitize|sanitizeHtml|DOMPurify\.sanitize"
    r"|encodeURIComponent|htmlspecialchars|textContent)\b")
# Template interpolations and concatenated variables inside the assigned value.
_INTERPOLATION = re.compile(r"\$\{([^}]*)\}")


def _iter_interpolations(value: str) -> List[str]:
    """Extract ``${...}`` expressions with balanced braces.

    A plain regex cannot handle nested template literals such as
    ``${cond ? `<b>${escapeHtml(x)}</b>` : ""}``, which a JS renderer uses
    constantly. Scanning with a brace counter keeps each top-level expression
    intact so the safety check sees the whole thing instead of a truncated
    fragment.
    """
    results: List[str] = []
    index = 0
    length = len(value)
    while index < length - 1:
        if value[index] == "$" and value[index + 1] == "{":
            depth = 1
            cursor = index + 2
            start = cursor
            while cursor < length and depth:
                char = value[cursor]
                if char == "{":
                    depth += 1
                elif char == "}":
                    depth -= 1
                cursor += 1
            results.append(value[start:cursor - 1] if depth == 0 else value[start:])
            index = cursor
            continue
        index += 1
    return results


def _expression_is_safe(expression: str) -> bool:
    """Whether one interpolated expression can be trusted not to inject markup."""
    stripped = expression.strip()
    if not stripped:
        return True
    # Recurse into nested template literals: every nested interpolation must
    # itself be safe, and the surrounding literal text is static markup.
    nested = _iter_interpolations(stripped)
    if nested:
        return all(_expression_is_safe(item) for item in nested)
    if _ESCAPE_HELPERS.search(stripped):
        return True
    # A render chain that produces escaped markup, e.g.
    #   rows.map((r) => `<li>${escapeHtml(r)}</li>`).join("")
    if re.match(r"^[\w.$\[\]]+\s*\.\s*(?:map|flatMap|filter|slice|sort)\s*\(", stripped):
        # No nested interpolation was found above, so there is no dynamic markup
        # to escape; the chain only emits its own static template text.
        return True
    # Ternary with string-literal branches is static markup.
    if re.fullmatch(r"[^?`]*\?\s*(\"[^\"]*\"|'[^']*')\s*:\s*(\"[^\"]*\"|'[^']*')", stripped):
        return True
    # Chained ternaries of string literals, e.g. a ? "x" : b ? "y" : "z".
    if re.fullmatch(r"[^`]*?(?:\?\s*(?:\"[^\"]*\"|'[^']*')\s*:\s*)+(?:\"[^\"]*\"|'[^']*')", stripped):
        return True
    # The local icon() helper returns fixed <svg><use/></svg> markup.
    if re.fullmatch(r"icon\(\s*[^)]*\)", stripped):
        return True
    # Counts and numeric expressions cannot carry markup.
    if re.fullmatch(r"[\w.\[\]()\s+\-*/%|?:]*\b(?:length|count|size|score|number|index)\b[\w.\[\]()\s+\-*/%|?:]*",
                    stripped, re.I):
        return True
    if re.fullmatch(r"[\w.\[\]]+\s*\|\|\s*\d+", stripped):
        return True
    if re.fullmatch(r"[\d\s+\-*/().]+", stripped):
        return True
    # Numeric built-ins such as Math.round(...) / Number(...) / parseInt(...).
    if re.fullmatch(r"(?:Math\.\w+|Number|parseInt|parseFloat)\s*\(.*\)", stripped):
        return True
    return False


def _innerhtml_is_safe(line: str) -> bool:
    """Decide whether an innerHTML assignment is a credible XSS sink.

    Returns True (do not report) only when the assigned value is provably static
    or every dynamic part is escaped. A bare variable assignment is always
    treated as a sink, because its contents are unknown at this line.
    """
    _, _, value = line.partition("=")
    value = value.strip().rstrip(";").strip()
    if not value:
        return True

    # Known-safe local helpers that return fixed markup.
    if re.fullmatch(r"icon\([^)]*\)", value):
        return True
    # A value passed wholly through an escaping helper is safe.
    if re.fullmatch(r"(?:escapeHtml|escapeHTML|DOMPurify\.sanitize|sanitize|sanitizeHtml)\([^)]*\)", value):
        return True

    # Anything that is not a string/template literal is unknown content:
    #   el.innerHTML = untrustedHtml
    #   el.innerHTML = renderRow(item)
    # Both must be reported, because this line does not prove the value is safe.
    # One exception: an array render chain such as
    #   el.innerHTML = rows.map((r) => `<li>${escapeHtml(r)}</li>`).join("")
    # is a template literal in disguise, so analyse its interpolations instead.
    is_render_chain = bool(re.match(r"^[\w.$\[\]]+\s*\.\s*(?:map|flatMap|filter|reduce|slice|sort)\s*\(", value))
    if not value.startswith(("`", '"', "'")) and not is_render_chain:
        return False

    interpolations = _iter_interpolations(value)
    if not interpolations:
        if is_render_chain:
            # A render chain with no template literal at all is unverifiable here.
            return False
        if "+" in value:
            # "<b>" + something : only safe when escaped.
            return bool(_ESCAPE_HELPERS.search(value))
        # Pure static string literal.
        return True

    return all(_expression_is_safe(expression) for expression in interpolations)


def scan_repository(repo: Path, max_findings: int = 200) -> List[SecurityFinding]:
    """Scan a repository with language-aware rules plus generic secret detection."""
    findings: List[SecurityFinding] = []
    for path, language in _iter_scannable_files(repo):
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        rel = str(path.relative_to(repo)).replace("\\", "/")
        if any(rel.endswith(marker) for marker in SELF_PATHS):
            continue
        is_example = any(marker in rel.lower() for marker in EXAMPLE_MARKERS)
        active_rules = list(RULES_BY_LANGUAGE.get(language, [])) + GENERIC_SECRET_RULES
        for line_number, line in enumerate(content.splitlines(), 1):
            if len(line) > 2000 or _is_suppressed(line):
                continue
            for rule_id, severity, pattern, message, recommendation, cwe in active_rules:
                if not pattern.search(line):
                    continue
                # Rule-specific precision filters to avoid systematic false positives.
                if rule_id == "JS-INNERHTML" and _innerhtml_is_safe(line):
                    continue
                effective = severity
                note = message
                if is_example and ("SECRET" in rule_id or "KEY" in rule_id or "TOKEN" in rule_id):
                    # Demo/example files should not dominate the risk score.
                    effective = "low"
                    note = f"{message}（位于示例或测试文件，可能是占位值）"
                findings.append(SecurityFinding(
                    rule_id, effective, rel, line_number, note,
                    line.strip()[:240], recommendation,
                    language=language if language != "config" else "config", cwe=cwe,
                ))
                if len(findings) >= max_findings:
                    return findings
                break
    return findings


def severity_counts(findings: Iterable[SecurityFinding]) -> Dict[str, int]:
    counts = {"high": 0, "medium": 0, "low": 0}
    for finding in findings:
        if finding.severity in counts:
            counts[finding.severity] += 1
    return counts
