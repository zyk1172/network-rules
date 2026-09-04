#!/usr/bin/env python3
"""Evaluate generated client artifacts for representative routing cases."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

try:
    import yaml  # type: ignore
except ImportError:  # pragma: no cover - validation reports the dependency
    yaml = None

from rule_model import CanonicalRule, first_matching_rule, make_rule


ROOT = Path(__file__).resolve().parents[1]
QX_DIR = ROOT / "dist" / "quantumult-x" / "providers"
QX_PATH = QX_DIR
MIHOMO_PATH = ROOT / "dist" / "mihomo" / "merge.yaml"
PROVIDER_DIR = ROOT / "dist" / "mihomo" / "providers"
CASES_PATH = ROOT / "tests" / "routing-cases.json"
CATEGORY_MARKER = re.compile(r"^# ===== CATEGORY: .+ \(([^()]+)\) =====$")
CANONICAL_MARKER = re.compile(r"^# CANONICAL-CATEGORY: ([A-Za-z0-9_-]+)$")


class RoutingError(ValueError):
    """Raised when a generated artifact cannot be evaluated."""


def _rule_from_line(
    line: str,
    *,
    category: str,
    source: str,
    component: str,
) -> Optional[CanonicalRule]:
    parts = [part.strip() for part in line.strip().split(",")]
    if len(parts) < 2:
        return None
    rule, _reason = make_rule(
        parts[0],
        parts[1],
        category=category,
        source=source,
        component=component,
        source_rule=line.strip(),
    )
    return rule


def qx_output_paths(root: Path = ROOT) -> List[Path]:
    """Return QX files in the same priority order as the generated example."""

    manifest = json.loads((root / "sources" / "upstreams.json").read_text(encoding="utf-8"))
    output_dir = root / "dist" / "quantumult-x" / "providers"
    paths: List[Path] = []
    personal = output_dir / "personal-overlay.list"
    if personal.exists():
        paths.append(personal)
    sources = sorted(
        manifest.get("sources", []),
        key=lambda source: (int(source.get("priority", 10000)), str(source.get("id"))),
    )
    for source in sources:
        if source.get("enabled", True):
            paths.append(output_dir / f"{source['id']}.list")
    if not paths:
        raise RoutingError(f"缺少 Quantumult X 分类生成物：{output_dir}")
    return paths


def parse_qx_rules(path: Path = QX_PATH) -> List[CanonicalRule]:
    if path.is_dir():
        paths = qx_output_paths(ROOT) if path == QX_DIR else sorted(path.glob("*.list"))
        rules: List[CanonicalRule] = []
        for child in paths:
            rules.extend(parse_qx_rules(child))
        if not rules:
            raise RoutingError(f"Quantumult X 生成目录没有可评估规则：{path}")
        return rules
    if not path.exists():
        raise RoutingError(f"缺少 Quantumult X 生成物：{path}")
    rules: List[CanonicalRule] = []
    current_category: Optional[str] = None
    pending_category: Optional[str] = None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        marker = CATEGORY_MARKER.match(line)
        if marker:
            current_category = marker.group(1)
            pending_category = None
            continue
        canonical_marker = CANONICAL_MARKER.match(line)
        if canonical_marker:
            pending_category = canonical_marker.group(1)
            continue
        if not line or line.startswith("#") or line.startswith(";"):
            continue
        category = pending_category or current_category
        if category is None:
            continue
        rule = _rule_from_line(
            line,
            category=category,
            source="generated-qx",
            component=str(path.relative_to(ROOT)),
        )
        pending_category = None
        if rule is not None:
            rules.append(rule)
    if not rules:
        raise RoutingError(f"Quantumult X 生成物没有可评估规则：{path}")
    return rules


def _load_yaml(path: Path) -> Any:
    if yaml is None:
        raise RoutingError("路由语义测试需要 PyYAML；请安装 requirements.txt")
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RoutingError(f"YAML 解析失败：{path}: {exc}") from exc


def _load_policy_category_map(root: Path = ROOT) -> Dict[str, str]:
    path = root / "sources" / "policies.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    mapping = document.get("mihomo", {})
    reverse: Dict[str, List[str]] = {}
    for category, policy in mapping.items():
        reverse.setdefault(str(policy), []).append(str(category))
    return {
        policy: categories[0]
        for policy, categories in reverse.items()
        if len(categories) == 1
    }


def _provider_rules(
    provider_id: str,
    provider_dir: Path = PROVIDER_DIR,
) -> List[CanonicalRule]:
    path = provider_dir / f"{provider_id}.yaml"
    if not path.exists():
        raise RoutingError(f"缺少 Mihomo 本地 provider：{path}")
    document = _load_yaml(path)
    if not isinstance(document, dict) or not isinstance(document.get("payload"), list):
        raise RoutingError(f"Mihomo provider 缺少 payload：{path}")
    rules: List[CanonicalRule] = []
    for item in document["payload"]:
        if not isinstance(item, str):
            continue
        rule = _rule_from_line(
            item,
            category=provider_id,
            source="generated-mihomo-provider",
            component=str(path.relative_to(ROOT)),
        )
        if rule is not None:
            rules.append(rule)
    return rules


def parse_mihomo_rules(
    merge_path: Path = MIHOMO_PATH,
    provider_dir: Path = PROVIDER_DIR,
    policy_root: Path = ROOT,
) -> List[CanonicalRule]:
    if not merge_path.exists():
        raise RoutingError(f"缺少 Mihomo Merge 生成物：{merge_path}")
    document = _load_yaml(merge_path)
    if not isinstance(document, dict):
        raise RoutingError(f"Mihomo Merge 顶层不是对象：{merge_path}")
    provider_map = document.get("rule-providers")
    prepend_rules = document.get("prepend-rules")
    if not isinstance(provider_map, dict) or not isinstance(prepend_rules, list):
        raise RoutingError(f"Mihomo Merge 缺少 provider 或 prepend-rules：{merge_path}")

    reverse_policy = _load_policy_category_map(policy_root)
    rules: List[CanonicalRule] = []
    for item in prepend_rules:
        if not isinstance(item, str):
            continue
        parts = [part.strip() for part in item.split(",")]
        if len(parts) >= 3 and parts[0].upper() == "RULE-SET":
            provider_id = parts[1]
            if provider_id not in provider_map:
                raise RoutingError(f"Mihomo prepend-rules 引用未知 provider：{item}")
            rules.extend(_provider_rules(provider_id, provider_dir))
            continue
        if len(parts) < 2:
            continue
        category = reverse_policy.get(parts[2]) if len(parts) > 2 else None
        rule = _rule_from_line(
            item,
            category=category or "personal-overlay",
            source="generated-mihomo-overlay",
            component=str(merge_path.relative_to(ROOT)),
        )
        if rule is not None:
            rules.append(rule)
    if not rules:
        raise RoutingError(f"Mihomo 生成物没有可评估规则：{merge_path}")
    return rules


def load_cases(path: Path = CASES_PATH) -> List[Dict[str, Any]]:
    try:
        cases = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RoutingError(f"路由案例读取失败：{path}: {exc}") from exc
    if not isinstance(cases, list):
        raise RoutingError(f"路由案例顶层必须是列表：{path}")
    return cases


def run_routing_cases(root: Path = ROOT) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    cases = load_cases(root / "tests" / "routing-cases.json")
    qx_rules: List[CanonicalRule] = []
    for qx_path in qx_output_paths(root):
        qx_rules.extend(parse_qx_rules(qx_path))
    mihomo_rules = parse_mihomo_rules(
        root / "dist" / "mihomo" / "merge.yaml",
        root / "dist" / "mihomo" / "providers",
        root,
    )
    results: List[Dict[str, Any]] = []
    failures: List[Dict[str, Any]] = []
    for case in cases:
        case_id = str(case.get("id", case.get("host", "unnamed")))
        host = str(case.get("host", ""))
        expected = case.get("expected_category")
        qx_rule = first_matching_rule(qx_rules, host)
        mihomo_rule = first_matching_rule(mihomo_rules, host)
        result = {
            "id": case_id,
            "host": host,
            "expected": expected,
            "quantumult_x": qx_rule.category if qx_rule else None,
            "mihomo": mihomo_rule.category if mihomo_rule else None,
        }
        results.append(result)
        if (
            result["quantumult_x"] != expected
            or result["mihomo"] != expected
            or result["quantumult_x"] != result["mihomo"]
        ):
            failures.append(result)
    return results, failures
