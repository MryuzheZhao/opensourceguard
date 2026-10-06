from __future__ import annotations

"""Optional TypeSafe AI ranking with a deterministic offline fallback."""

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

DEFAULT_BASE_URL = "https://api.typesafe.ai"
DEFAULT_MODEL = "jev-latest"
MAX_PROJECTS = 50
MAX_TEXT = 700


def _api_key() -> str:
    return os.getenv("TYPESAFE_API_KEY", "").strip()


def _base_url() -> str:
    return os.getenv("TYPESAFE_BASE_URL", DEFAULT_BASE_URL).strip().rstrip("/") or DEFAULT_BASE_URL


def _endpoint() -> str:
    return os.getenv("TYPESAFE_API_URL", "").strip() or f"{_base_url()}/v1/systemone"


def _model() -> str:
    return os.getenv("TYPESAFE_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL


def status() -> Dict[str, Any]:
    configured = bool(_api_key())
    return {
        "configured": configured,
        "ready": configured,
        "provider": "TypeSafe AI",
        "model": _model(),
        "endpoint_host": urllib.parse.urlparse(_endpoint()).netloc,
        "mode": "typesafe_system_one" if configured else "local_ranker",
        "token_configured": configured,
    }


def _tokens(value: str) -> List[str]:
    return re.findall(r"[a-z0-9][a-z0-9_+#.-]*|[\u4e00-\u9fff]{2,}", str(value or "").lower())


def _text(project: Mapping[str, Any]) -> str:
    fields = [project.get("name"), project.get("full_name"), project.get("description"),
              project.get("platform_label"), project.get("platform")]
    return " ".join(str(item or "") for item in fields)[:MAX_TEXT]


def _local_score(project: Mapping[str, Any], interests: str, avoid: str) -> Tuple[float, List[str]]:
    source = _text(project).lower()
    positive = [term for term in _tokens(interests) if len(term) >= 2]
    negative = [term for term in _tokens(avoid) if len(term) >= 2]
    matched = [term for term in positive if term in source]
    rejected = [term for term in negative if term in source]
    score = 50.0 + min(45.0, len(matched) * 16.0) - min(42.0, len(rejected) * 24.0)
    if project.get("demo"):
        score -= 2.0
    reasons: List[str] = []
    if matched:
        reasons.append("匹配关注：" + "、".join(matched[:3]))
    if rejected:
        reasons.append("包含暂不关注：" + "、".join(rejected[:3]))
    if not reasons:
        reasons.append("等待更多兴趣信息")
    return max(0.0, min(100.0, score)), reasons


def _post(payload: Mapping[str, Any], timeout: float = 12.0) -> Mapping[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        _endpoint(), data=data, method="POST",
        headers={"Accept": "application/json", "Content-Type": "application/json",
                 "Authorization": f"Bearer {_api_key()}", "User-Agent": "OpenSourceGuard/0.4"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        parsed = json.loads(response.read().decode("utf-8") or "{}")
    if not isinstance(parsed, Mapping):
        raise ValueError("TypeSafe 返回格式无效")
    return parsed


def _answer(response: Mapping[str, Any], key: str) -> Optional[Tuple[float, float]]:
    answers = response.get("answers")
    if not isinstance(answers, Mapping):
        answers = response.get("scores") if isinstance(response.get("scores"), Mapping) else {}
    item = answers.get(key) if isinstance(answers, Mapping) else None
    if not isinstance(item, Mapping):
        return None
    try:
        score = float(item.get("score"))
    except (TypeError, ValueError):
        return None
    try:
        confidence = float(item.get("confidence", 0.5))
    except (TypeError, ValueError):
        confidence = 0.5
    return max(0.0, min(100.0, score / 3.0 * 100.0)), max(0.0, min(1.0, confidence))


def _safe_project(project: Mapping[str, Any]) -> Dict[str, Any]:
    return {"id": str(project.get("id") or ""), "name": str(project.get("name") or ""),
            "description": str(project.get("description") or "")[:MAX_TEXT],
            "platform": str(project.get("platform") or ""),
            "open_issues": int(project.get("open_issues", 0) or 0)}


def recommend(projects: Sequence[Mapping[str, Any]], interests: str = "", avoid: str = "") -> Dict[str, Any]:
    rows = [dict(item) for item in projects if isinstance(item, Mapping)][:MAX_PROJECTS]
    profile = {"interests": str(interests or "")[:500], "avoid": str(avoid or "")[:500]}
    if not rows:
        return {"projects": [], "mode": "local_ranker", "configured": bool(_api_key()), "profile": profile}

    local: List[Tuple[float, List[str]]] = [_local_score(row, interests, avoid) for row in rows]
    remote: Dict[int, Tuple[float, float]] = {}
    remote_error = ""
    if _api_key():
        questions = {
            f"project_{index}": {
                "type": "score",
                "instructions": (
                    "How relevant is the open-source project named "
                    f"{str(row.get('name') or row.get('id') or index)!r} "
                    "for the user's stated interests? Evaluate only this project."
                ),
                "criteria": ["not a fit", "possibly useful", "relevant", "excellent match"],
            }
            for index, row in enumerate(rows)
        }
        state = {"user_interests": profile["interests"], "user_avoid": profile["avoid"],
                 "projects": [_safe_project(row) for row in rows]}
        try:
            response = _post({"state": state, "model": _model(), "questions": questions})
            for index in range(len(rows)):
                parsed = _answer(response, f"project_{index}")
                if parsed is not None:
                    remote[index] = parsed
        except (OSError, urllib.error.HTTPError, urllib.error.URLError, ValueError, json.JSONDecodeError) as exc:
            remote_error = type(exc).__name__

    ranked: List[Dict[str, Any]] = []
    for index, row in enumerate(rows):
        local_score, reasons = local[index]
        if index in remote:
            remote_score, confidence = remote[index]
            score = remote_score * 0.72 + local_score * 0.28
            source = "typesafe"
            if confidence < 0.55:
                reasons.append("TypeSafe 信心较低，建议人工判断")
            else:
                reasons.append(f"TypeSafe 评分信心 {round(confidence * 100)}%")
        else:
            score, confidence, source = local_score, None, "local"
        item = dict(row)
        item["relevance_score"] = round(score, 1)
        item["relevance_source"] = source
        item["relevance_confidence"] = round(confidence, 3) if confidence is not None else None
        item["relevance_reasons"] = reasons[:4]
        item["recommendation_rank"] = index
        ranked.append(item)
    ranked.sort(key=lambda item: (-float(item.get("relevance_score", 0)), int(item.get("recommendation_rank", 0))))
    for rank, item in enumerate(ranked, 1):
        item["recommendation_rank"] = rank
    result: Dict[str, Any] = {"projects": ranked, "mode": "typesafe" if remote else "local_ranker",
                              "configured": bool(_api_key()), "profile": profile}
    if remote_error:
        result.update({"fallback": True, "error": remote_error})
    return result
