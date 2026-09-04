#!/usr/bin/env python3
"""Validate the manifest, canonical build report and generated client artifacts."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "sources" / "upstreams.json"
POLICIES_PATH = ROOT / "sources" / "policies.json"
PATCHES_DIR = ROOT / "patches"
LOCK_PATH = ROOT / "sources" / "upstreams.lock.json"
REPORT_PATH = ROOT / "dist" / "build-report.json"
MIHOMO_PATH = ROOT / "dist" / "mihomo" / "merge.yaml"
PROVIDER_DIR = ROOT / "dist" / "mihomo" / "providers"
QX_PATH = ROOT / "dist" / "quantumult-x" / "aggregate.list"

sys.path.insert(0, str(ROOT / "scripts"))
from build import (  # noqa: E402
    CLIENTS,
    BuildError,
    load_json,
    validate_manifest as validate_build_manifest,
)
from patch_engine import load_patches  # noqa: E402
from routing import run_routing_cases  # noqa: E402
from rule_model import (  # noqa: E402
    CANONICAL_TYPES,
    CLIENT_SUPPORTED_TYPES,
    canonicalize_type,
)


REQUIRED_REPORT_KEYS = {
    "upstreams",
    "canonical_rules",
    "patches",
    "duplicates",
    "conflicts",
    "categories",
    "client_outputs",
    "unsupported_rules",
    "dropped_rules",
    "obsolete_patch_candidates",
}
ALLOWED_PATCH_STATUSES = {"applied", "obsolete_candidate", "failed"}


def add_error(errors: List[str], message: str) -> None:
    errors.append(message)


def integer(value: Any, default: int = -1) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def load_yaml(path: Path) -> Any:
    try:
        import yaml  # type: ignore
    except ImportError as exc:
        raise BuildError("验证 YAML 需要 PyYAML；请安装 requirements.txt") from exc
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise BuildError(f"YAML 解析失败：{path}: {exc}") from exc


def validate_manifest(
    manifest: Dict[str, Any], policies: Dict[str, Any], errors: List[str]
) -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    try:
        return validate_build_manifest(manifest, policies)
    except BuildError as exc:
        add_error(errors, str(exc))
        return [], {}


def sort_key(source: Dict[str, Any]) -> Tuple[int, str]:
    return int(source.get("priority", 10000)), str(source["id"])


def active_ids(sources: Sequence[Dict[str, Any]]) -> List[str]:
    return [
        str(source["id"])
        for source in sorted(sources, key=sort_key)
        if source.get("enabled", True)
    ]


def all_ids(sources: Sequence[Dict[str, Any]]) -> List[str]:
    return [str(source["id"]) for source in sources]


def component_map(source: Dict[str, Any], client: str) -> Dict[str, Dict[str, Any]]:
    return {
        str(component["id"]): component
        for component in source["components"][client]
    }


def validate_lock(
    sources: Sequence[Dict[str, Any]], errors: List[str]
) -> Dict[str, Any] | None:
    if not LOCK_PATH.exists():
        add_error(errors, f"缺少上游锁定信息：{LOCK_PATH}")
        return None
    try:
        lock = load_json(LOCK_PATH)
    except BuildError as exc:
        add_error(errors, str(exc))
        return None
    if lock.get("schema_version") != 2:
        add_error(errors, "upstreams.lock.json 必须使用 schema_version=2")
        return lock
    lock_categories = lock.get("categories")
    expected_ids = set(all_ids(sources))
    if not isinstance(lock_categories, dict):
        add_error(errors, "upstreams.lock.json 缺少 categories 对象")
        return lock
    if set(lock_categories) != expected_ids:
        add_error(errors, "upstreams.lock.json 与上游清单的 category id 集合不一致")

    for source in sources:
        category_id = str(source["id"])
        record = lock_categories.get(category_id)
        if not isinstance(record, dict):
            add_error(errors, f"锁定信息缺少分类：{category_id}")
            continue
        enabled = bool(source.get("enabled", True))
        if record.get("enabled") is not enabled:
            add_error(errors, f"锁定信息 enabled 不一致：{category_id}")
        locked_components = record.get("components")
        if not isinstance(locked_components, dict):
            add_error(errors, f"锁定信息缺少组件对象：{category_id}")
            continue
        for client in CLIENTS:
            expected_components = component_map(source, client) if enabled else {}
            actual_components = locked_components.get(client)
            if not isinstance(actual_components, dict):
                add_error(errors, f"锁定信息缺少组件客户端：{category_id}/{client}")
                continue
            if set(actual_components) != set(expected_components):
                add_error(
                    errors,
                    f"锁定信息组件集合不一致：{category_id}/{client}; "
                    f"expected={sorted(expected_components)}, actual={sorted(actual_components)}",
                )
            for component_id, component_record in actual_components.items():
                if not isinstance(component_record, dict):
                    add_error(errors, f"锁定信息格式错误：{category_id}/{client}/{component_id}")
                    continue
                manifest_component = expected_components.get(component_id)
                if manifest_component is None:
                    continue
                if component_record.get("url") != manifest_component.get("url"):
                    add_error(errors, f"锁定 URL 与清单不一致：{category_id}/{client}/{component_id}")
                if not re.fullmatch(r"[0-9a-f]{64}", str(component_record.get("sha256", ""))):
                    add_error(errors, f"锁定信息缺少 SHA-256：{category_id}/{client}/{component_id}")
                try:
                    size = int(component_record.get("bytes", 0))
                except (TypeError, ValueError):
                    size = 0
                if size <= 0:
                    add_error(errors, f"锁定信息字节数无效：{category_id}/{client}/{component_id}")
                if not isinstance(component_record.get("stale_cache"), bool):
                    add_error(errors, f"锁定信息 stale_cache 无效：{category_id}/{client}/{component_id}")
    return lock


def validate_report(
    sources: Sequence[Dict[str, Any]],
    errors: List[str],
    warnings: List[str],
) -> Dict[str, Any] | None:
    if not REPORT_PATH.exists():
        add_error(errors, f"缺少构建报告：{REPORT_PATH}")
        return None
    try:
        report = load_json(REPORT_PATH)
    except BuildError as exc:
        add_error(errors, str(exc))
        return None
    if report.get("schema_version") != 2:
        add_error(errors, "dist/build-report.json 必须使用 schema_version=2")
    missing = REQUIRED_REPORT_KEYS - set(report)
    if missing:
        add_error(errors, f"构建报告缺少字段：{sorted(missing)}")

    upstream_report = report.get("upstreams", {})
    if not isinstance(upstream_report, dict):
        add_error(errors, "构建报告 upstreams 必须是对象")
        upstream_report = {}
    components = upstream_report.get("components")
    expected_component_count = sum(
        len(source["components"][client])
        for source in sources
        if source.get("enabled", True)
        for client in CLIENTS
    )
    if not isinstance(components, list):
        add_error(errors, "构建报告 upstreams.components 必须是列表")
        components = []
    if integer(upstream_report.get("component_count")) != len(components):
        add_error(errors, "构建报告 component_count 与 components 不一致")
    if len(components) != expected_component_count:
        add_error(
            errors,
            f"构建报告组件数量不符合启用清单：{len(components)}!={expected_component_count}",
        )
    manifest_components = {
        (str(source["id"]), client, str(component["id"])): component
        for source in sources
        if source.get("enabled", True)
        for client in CLIENTS
        for component in source["components"][client]
    }
    for component in components:
        if not isinstance(component, dict):
            add_error(errors, "构建报告存在非对象组件记录")
            continue
        key = (
            str(component.get("category")),
            str(component.get("client")),
            str(component.get("id")),
        )
        manifest_component = manifest_components.get(key)
        if manifest_component is None:
            add_error(errors, f"构建报告存在未登记组件：{key}")
            continue
        if component.get("canonical") != bool(manifest_component.get("canonical", False)):
            add_error(errors, f"构建报告 canonical 标志不一致：{key}")
        if component.get("canonical"):
            unsupported = integer(component.get("unsupported_rules"), 0)
            if unsupported:
                add_error(errors, f"canonical 组件含未转换规则：{key}, count={unsupported}")
            if not isinstance(component.get("parsed_rules"), int):
                add_error(errors, f"canonical 组件缺少 parsed_rules：{key}")

    category_records = report.get("categories")
    expected_category_ids = {"personal-overlay", *all_ids(sources)}
    if not isinstance(category_records, list):
        add_error(errors, "构建报告 categories 必须是列表")
    else:
        actual_category_ids = {
            str(item.get("id")) for item in category_records if isinstance(item, dict)
        }
        if actual_category_ids != expected_category_ids:
            add_error(
                errors,
                "构建报告分类集合不一致："
                f"expected={sorted(expected_category_ids)}, actual={sorted(actual_category_ids)}",
            )
        for item in category_records:
            if not isinstance(item, dict):
                continue
            for field in ("raw_rules", "normalized", "after_patch", "after_dedup", "final"):
                try:
                    if integer(item.get(field)) < 0:
                        raise ValueError
                except (TypeError, ValueError):
                    add_error(errors, f"构建报告分类 {item.get('id')} 的 {field} 无效")

    patch_summary = report.get("patches")
    if not isinstance(patch_summary, dict):
        add_error(errors, "构建报告 patches 必须是对象")
    else:
        details = patch_summary.get("details")
        if not isinstance(details, list):
            add_error(errors, "构建报告 patches.details 必须是列表")
            details = []
        for detail in details:
            if not isinstance(detail, dict):
                add_error(errors, "构建报告存在非对象 patch 结果")
                continue
            status = detail.get("status")
            if status not in ALLOWED_PATCH_STATUSES:
                add_error(errors, f"patch {detail.get('id')} 状态无效：{status}")
            if status == "failed":
                add_error(errors, f"patch {detail.get('id')} 失败：{detail.get('error', 'unknown')}")
            if status == "obsolete_candidate":
                if detail.get("required", True):
                    add_error(
                        errors,
                        f"关键 patch 已成为陈旧候选：{detail.get('id')}；请人工审查后删除或更新",
                    )
                else:
                    warnings.append(f"非关键 patch 已成为陈旧候选：{detail.get('id')}")
        expected_counts = {
            "applied": sum(
                isinstance(item, dict) and item.get("status") == "applied"
                for item in details
            ),
            "obsolete_candidates": sum(
                isinstance(item, dict) and item.get("status") == "obsolete_candidate"
                for item in details
            ),
            "failed": sum(
                isinstance(item, dict) and item.get("status") == "failed"
                for item in details
            ),
        }
        for field, expected in expected_counts.items():
            if integer(patch_summary.get(field)) != expected:
                add_error(errors, f"patch 汇总 {field} 不一致")

    obsolete = report.get("obsolete_patch_candidates")
    if not isinstance(obsolete, list):
        add_error(errors, "obsolete_patch_candidates 必须是列表")
    unsupported_report = report.get("unsupported_rules")
    if not isinstance(unsupported_report, dict):
        add_error(errors, "构建报告 unsupported_rules 必须是对象")
    else:
        upstream_total = sum(
            integer(item.get("unsupported_rules"), 0)
            for item in components
            if isinstance(item, dict)
        )
        client_reports = unsupported_report.get("client_outputs", {})
        mihomo_report = (
            client_reports.get("mihomo", {})
            if isinstance(client_reports, dict)
            else {}
        )
        client_total = integer(mihomo_report.get("total"), 0) if isinstance(mihomo_report, dict) else 0
        if integer(unsupported_report.get("total")) != upstream_total + client_total:
            add_error(errors, "构建报告 unsupported_rules.total 不一致")
    return report


def validate_qx(
    sources: Sequence[Dict[str, Any]],
    policies: Dict[str, Any],
    report: Dict[str, Any] | None,
    errors: List[str],
) -> None:
    if not QX_PATH.exists():
        add_error(errors, f"缺少生成文件：{QX_PATH}")
        return
    active = set(active_ids(sources))
    all_category_ids = set(all_ids(sources))
    policy_map = policies.get("quantumult-x", {})
    raw_lines = QX_PATH.read_text(encoding="utf-8").splitlines()
    if "# GENERATED-BY: network-rules-project/scripts/build.py" not in raw_lines:
        add_error(errors, "Quantumult X 生成物缺少生成器标记")
    current_category: str | None = None
    pending_category: str | None = None
    seen_categories = set()
    rule_count = 0
    section_counts: Dict[str, int] = {}
    for number, raw_line in enumerate(raw_lines, 1):
        line = raw_line.strip()
        marker = re.match(r"^# ===== CATEGORY: .+ \(([^()]+)\) =====$", line)
        if marker:
            current_category = marker.group(1)
            pending_category = None
            seen_categories.add(current_category)
            section_counts.setdefault(current_category, 0)
            if current_category != "personal-overlay" and current_category not in active:
                add_error(errors, f"Quantumult X 使用了非启用分类：{current_category}")
            continue
        canonical_marker = re.match(r"^# CANONICAL-CATEGORY: ([A-Za-z0-9_-]+)$", line)
        if canonical_marker:
            pending_category = canonical_marker.group(1)
            if pending_category not in all_category_ids:
                add_error(errors, f"Quantumult X 使用了未知 canonical category：{pending_category}")
            continue
        if not line or line.startswith("#") or line.startswith(";"):
            continue
        if current_category is None:
            add_error(errors, f"Quantumult X 第 {number} 行规则位于分类段之外")
            continue
        category = pending_category or current_category
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 3:
            add_error(errors, f"Quantumult X 第 {number} 行缺少策略：{line}")
            continue
        if canonicalize_type(parts[0]) not in CANONICAL_TYPES:
            add_error(errors, f"Quantumult X 第 {number} 行类型不属于 canonical model：{parts[0]}")
        expected_policy = policy_map.get(category)
        if expected_policy is None:
            add_error(errors, f"Quantumult X 第 {number} 行分类没有策略映射：{category}")
        elif parts[2] != str(expected_policy):
            add_error(
                errors,
                f"Quantumult X 第 {number} 行策略与 category 不一致："
                f"{category} expected={expected_policy!r} actual={parts[2]!r}",
            )
        if any(token in line for token in ("OWNER/REPOSITORY", "REPLACE_ME", "<YOUR_")):
            add_error(errors, f"Quantumult X 第 {number} 行包含占位符")
        rule_count += 1
        section_counts[current_category] = section_counts.get(current_category, 0) + 1
        pending_category = None

    expected_sections = set(active)
    personal_report: Dict[str, Any] = {}
    if isinstance(report, dict):
        category_records = report.get("categories", [])
        if isinstance(category_records, list):
            personal_report = next(
                (
                    item
                    for item in category_records
                    if isinstance(item, dict) and item.get("id") == "personal-overlay"
                ),
                {},
            )
    if integer(personal_report.get("final"), 0) > 0:
        expected_sections.add("personal-overlay")
    if seen_categories != expected_sections:
        add_error(
            errors,
            "Quantumult X 分类段集合不一致："
            f"expected={sorted(expected_sections)}, actual={sorted(seen_categories)}",
        )
    if rule_count == 0:
        add_error(errors, "Quantumult X 生成物没有规则")
    if report is not None:
        client_outputs = report.get("client_outputs", {})
        qx_report = (
            client_outputs.get("quantumult-x", {})
            if isinstance(client_outputs, dict)
            else {}
        )
        if not isinstance(qx_report, dict):
            add_error(errors, "构建报告缺少 Quantumult X client_outputs")
            qx_report = {}
        if integer(qx_report.get("rules")) != rule_count:
            add_error(errors, "构建报告与 Quantumult X 实际规则数不一致")
        report_sections = {
            str(item.get("id")): integer(item.get("rules"))
            for item in qx_report.get("categories", [])
            if isinstance(item, dict)
        }
        if report_sections != section_counts:
            add_error(errors, "构建报告与 Quantumult X 分类规则数不一致")


def validate_provider_file(
    path: Path,
    category_id: str,
    errors: List[str],
) -> int:
    if not path.exists():
        add_error(errors, f"缺少 Mihomo 本地 provider：{path}")
        return 0
    raw_lines = path.read_text(encoding="utf-8").splitlines()
    if "# GENERATED-BY: network-rules-project/scripts/build.py" not in raw_lines[:5]:
        add_error(errors, f"Mihomo provider 缺少生成器标记：{path}")
    if not any(f"({category_id})" in line for line in raw_lines[:3]):
        add_error(errors, f"Mihomo provider 分类标记不一致：{path}")
    try:
        data = load_yaml(path)
    except BuildError as exc:
        add_error(errors, str(exc))
        return 0
    if not isinstance(data, dict) or not isinstance(data.get("payload"), list):
        add_error(errors, f"Mihomo provider 缺少 payload 列表：{path}")
        return 0
    count = 0
    for number, item in enumerate(data["payload"], 1):
        if not isinstance(item, str):
            add_error(errors, f"Mihomo provider 第 {number} 条不是字符串：{path}")
            continue
        parts = [part.strip() for part in item.split(",")]
        if (
            len(parts) < 2
            or canonicalize_type(parts[0]) not in CLIENT_SUPPORTED_TYPES["mihomo"]
        ):
            add_error(errors, f"Mihomo provider 第 {number} 条不是 canonical 规则：{item}")
            continue
        count += 1
    if count == 0:
        add_error(errors, f"Mihomo provider 没有可用规则：{path}")
    return count


def validate_mihomo(
    manifest: Dict[str, Any],
    sources: Sequence[Dict[str, Any]],
    policies: Dict[str, Any],
    report: Dict[str, Any] | None,
    errors: List[str],
) -> None:
    if not MIHOMO_PATH.exists():
        add_error(errors, f"缺少生成文件：{MIHOMO_PATH}")
        return
    try:
        data = load_yaml(MIHOMO_PATH)
    except BuildError as exc:
        add_error(errors, str(exc))
        return
    if not isinstance(data, dict):
        add_error(errors, "Mihomo Merge 文件顶层不是对象")
        return
    provider_map = data.get("rule-providers")
    prepend_rules = data.get("prepend-rules")
    if not isinstance(provider_map, dict):
        add_error(errors, "Mihomo Merge 缺少 rule-providers 对象")
        provider_map = {}
    if not isinstance(prepend_rules, list):
        add_error(errors, "Mihomo Merge 缺少 prepend-rules 列表")
        prepend_rules = []

    expected_ids = active_ids(sources)
    if set(provider_map) != set(expected_ids):
        add_error(
            errors,
            "Mihomo provider 集合不一致："
            f"expected={sorted(expected_ids)}, actual={sorted(provider_map)}",
        )
    publication = manifest.get("publication", {})
    base_url = f"https://raw.githubusercontent.com/{publication.get('repository')}/{publication.get('ref')}"
    provider_rule_counts: Dict[str, int] = {}
    for source in sources:
        category_id = str(source["id"])
        provider = provider_map.get(category_id)
        if not source.get("enabled", True):
            if provider is not None:
                add_error(errors, f"Mihomo Merge 引用了禁用分类：{category_id}")
            continue
        if not isinstance(provider, dict):
            add_error(errors, f"Mihomo Merge 缺少 provider：{category_id}")
            continue
        expected_values = {
            "type": "http",
            "behavior": "classical",
            "format": "yaml",
            "url": f"{base_url}/dist/mihomo/providers/{category_id}.yaml",
        }
        for key, expected in expected_values.items():
            if provider.get(key) != expected:
                add_error(
                    errors,
                    f"Mihomo provider {category_id} 的 {key} 不正确："
                    f"expected={expected!r}, actual={provider.get(key)!r}",
                )
        path_value = str(provider.get("path", ""))
        if not path_value.endswith(f"/network-rules/{category_id}.yaml"):
            add_error(errors, f"Mihomo provider {category_id} path 不属于本项目：{path_value}")
        provider_rule_counts[category_id] = validate_provider_file(
            PROVIDER_DIR / f"{category_id}.yaml", category_id, errors
        )

    referenced = []
    for item in prepend_rules:
        if not isinstance(item, str):
            add_error(errors, "Mihomo prepend-rules 含非字符串")
            continue
        parts = [part.strip() for part in item.split(",")]
        if parts and parts[0].upper() == "RULE-SET":
            if len(parts) < 3 or parts[1] not in provider_map:
                add_error(errors, f"Mihomo RULE-SET 未知 provider：{item}")
            else:
                referenced.append(parts[1])
                if str(policies.get("mihomo", {}).get(parts[1])) != parts[2]:
                    add_error(errors, f"Mihomo RULE-SET 策略与 category 不一致：{item}")
            continue
        if len(parts) < 3 or canonicalize_type(parts[0]) not in CANONICAL_TYPES:
            add_error(errors, f"Mihomo prepend-rules 含非 canonical 规则：{item}")
    if set(referenced) != set(expected_ids) or len(referenced) != len(expected_ids):
        add_error(
            errors,
            "Mihomo prepend-rules 未按分类各引用一次 provider："
            f"expected={expected_ids}, actual={referenced}",
        )
    if report is not None:
        client_outputs = report.get("client_outputs", {})
        mihomo_report = (
            client_outputs.get("mihomo", {})
            if isinstance(client_outputs, dict)
            else {}
        )
        if not isinstance(mihomo_report, dict):
            add_error(errors, "构建报告缺少 Mihomo client_outputs")
            mihomo_report = {}
        if mihomo_report.get("provider_ids") != expected_ids:
            add_error(errors, "构建报告与 Mihomo provider 顺序不一致")
        report_counts = mihomo_report.get("provider_rules", {})
        if report_counts != provider_rule_counts:
            add_error(errors, "构建报告与 Mihomo provider 规则数不一致")


def validate_patches(errors: List[str]) -> None:
    try:
        load_patches(PATCHES_DIR)
    except Exception as exc:
        add_error(errors, f"patch 文件校验失败：{exc}")


def validate_routing(errors: List[str]) -> None:
    try:
        _results, failures = run_routing_cases()
    except Exception as exc:
        add_error(errors, f"代表性路由测试无法执行：{exc}")
        return
    for failure in failures:
        add_error(errors, f"代表性路由不一致：{json.dumps(failure, ensure_ascii=False)}")


def main() -> int:
    errors: List[str] = []
    warnings: List[str] = []
    try:
        manifest = load_json(MANIFEST_PATH)
        policies = load_json(POLICIES_PATH)
    except BuildError as exc:
        print(f"validation failed: {exc}", file=sys.stderr)
        return 2

    sources, _categories = validate_manifest(manifest, policies, errors)
    validate_patches(errors)
    lock = validate_lock(sources, errors)
    report = validate_report(sources, errors, warnings)
    if sources:
        validate_qx(sources, policies, report, errors)
        validate_mihomo(manifest, sources, policies, report, errors)
    validate_routing(errors)

    if warnings:
        print("validation warnings:")
        for warning in warnings:
            print(f"- {warning}")
    if errors:
        print("validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1

    stale = sum(
        1
        for category in (lock or {}).get("categories", {}).values()
        if isinstance(category, dict)
        for client_components in category.get("components", {}).values()
        if isinstance(client_components, dict)
        for component in client_components.values()
        if isinstance(component, dict) and component.get("stale_cache")
    )
    print(
        "validation passed: manifest, patches, lock, canonical report, "
        f"Quantumult X, Mihomo local providers, semantic routing (stale components: {stale})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
