#!/usr/bin/env python3
"""Validate generated artifacts without touching any installed VPN client."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Sequence

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "sources" / "upstreams.json"
POLICIES_PATH = ROOT / "sources" / "policies.json"
OVERRIDES_PATH = ROOT / "overrides" / "rules.txt"
LOCK_PATH = ROOT / "sources" / "upstreams.lock.json"
REPORT_PATH = ROOT / "dist" / "build-report.json"
MIHOMO_PATH = ROOT / "dist" / "mihomo" / "merge.yaml"
QX_PATH = ROOT / "dist" / "quantumult-x" / "aggregate.list"

sys.path.insert(0, str(ROOT / "scripts"))
from build import (  # noqa: E402  (shared parser and policy rules)
    BuildError,
    QX_TYPE_MAP,
    action_index,
    load_json,
    parse_local_rules,
    render_local_rule,
    split_rule,
)


def add_error(errors: List[str], message: str) -> None:
    errors.append(message)


def load_yaml(path: Path) -> Any:
    try:
        import yaml  # type: ignore
    except ImportError:
        # The generated file is intentionally simple. The fallback still
        # catches missing top-level sections when PyYAML is not installed.
        text = path.read_text(encoding="utf-8")
        if "rule-providers:" not in text or "prepend-rules:" not in text:
            raise BuildError(f"{path} 缺少 Merge 配置段")
        return None
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:  # PyYAML exposes several parser exception types.
        raise BuildError(f"YAML 解析失败：{path}: {exc}") from exc


def validate_manifest(
    manifest: Dict[str, Any], policies: Dict[str, Any], errors: List[str]
) -> List[Dict[str, Any]]:
    sources = manifest.get("sources")
    if not isinstance(sources, list) or not sources:
        add_error(errors, "sources/upstreams.json 的 sources 为空")
        return []
    ids = set()
    for source in sources:
        source_id = source.get("id")
        if not isinstance(source_id, str) or not source_id:
            add_error(errors, "上游缺少有效 id")
            continue
        if source_id in ids:
            add_error(errors, f"上游 id 重复：{source_id}")
        ids.add(source_id)
        for client, key in (("quantumult-x", "quantumult_x"), ("mihomo", "mihomo")):
            cfg = source.get(key)
            if not cfg:
                continue
            url = str(cfg.get("url", ""))
            if not url.startswith("https://raw.githubusercontent.com/"):
                add_error(errors, f"{source_id}/{client} 不是允许的 GitHub raw URL")
            if "?" in url or "#" in url:
                add_error(errors, f"{source_id}/{client} URL 不应含查询参数或片段")
            policy_key = cfg.get("policy_key")
            if not isinstance(policy_key, str):
                add_error(errors, f"{source_id}/{client} 缺少 policy_key")
            elif not isinstance(policies.get(client), dict) or policy_key not in policies[client]:
                add_error(errors, f"{client} 缺少策略映射：{policy_key}")
    return sources


def validate_mihomo(
    sources: Sequence[Dict[str, Any]], errors: List[str]
) -> None:
    if not MIHOMO_PATH.exists():
        add_error(errors, f"缺少生成文件：{MIHOMO_PATH}")
        return
    try:
        data = load_yaml(MIHOMO_PATH)
    except BuildError as exc:
        add_error(errors, str(exc))
        return
    if data is None:
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

    expected_ids = [str(source["id"]) for source in sources if source.get("mihomo")]
    if set(provider_map) != set(expected_ids):
        add_error(
            errors,
            "Mihomo provider 集合不一致："
            f"expected={sorted(expected_ids)}, actual={sorted(provider_map)}",
        )
    for source in sources:
        cfg = source.get("mihomo")
        if not cfg:
            continue
        source_id = str(source["id"])
        provider = provider_map.get(source_id)
        if not isinstance(provider, dict):
            continue
        for key in ("type", "behavior", "format", "url", "path", "interval"):
            if key not in provider:
                add_error(errors, f"Mihomo provider {source_id} 缺少 {key}")
        if provider.get("type") != "http":
            add_error(errors, f"Mihomo provider {source_id} type 不是 http")
        if not str(provider.get("url", "")).startswith(
            "https://raw.githubusercontent.com/"
        ):
            add_error(errors, f"Mihomo provider {source_id} URL 非 GitHub raw")

    provider_rule_ids = set()
    for raw_rule in prepend_rules:
        rule = str(raw_rule)
        parts = split_rule(rule)
        if not parts:
            add_error(errors, "Mihomo prepend-rules 含空规则")
            continue
        if parts[0].upper() == "RULE-SET":
            if len(parts) < 3 or parts[1] not in provider_map:
                add_error(errors, f"Mihomo RULE-SET 未知 provider：{rule}")
            else:
                provider_rule_ids.add(parts[1])
    if provider_rule_ids != set(expected_ids):
        add_error(
            errors,
            "Mihomo prepend-rules 未完整引用 provider："
            f"expected={sorted(expected_ids)}, actual={sorted(provider_rule_ids)}",
        )


def validate_qx(policies: Dict[str, Any], errors: List[str]) -> None:
    if not QX_PATH.exists():
        add_error(errors, f"缺少生成文件：{QX_PATH}")
        return
    allowed_types = set(QX_TYPE_MAP.values()) | {
        "HOST",
        "HOST-SUFFIX",
        "HOST-KEYWORD",
        "HOST-WILDCARD",
        "IP6-CIDR",
        "SRC-IP-CIDR",
        "DEST-PORT",
        "FINAL",
    }
    allowed_policies = {str(value) for value in policies.get("quantumult-x", {}).values()}
    allowed_policies.update({"direct", "reject", "proxy"})
    rules: List[str] = []
    for number, raw_line in enumerate(QX_PATH.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith(";"):
            continue
        parts = split_rule(line)
        if parts[0].upper() not in allowed_types:
            add_error(errors, f"Quantumult X 第 {number} 行类型未知：{parts[0]}")
            continue
        index = action_index(parts)
        if len(parts) <= index or not parts[index]:
            add_error(errors, f"Quantumult X 第 {number} 行缺少策略：{line}")
            continue
        if parts[index] not in allowed_policies:
            add_error(errors, f"Quantumult X 第 {number} 行策略未登记：{parts[index]}")
        if any(token in line for token in ("OWNER/REPOSITORY", "REPLACE_ME", "<YOUR_")):
            add_error(errors, f"Quantumult X 第 {number} 行包含占位符")
        rules.append(line)

    try:
        local_rules = parse_local_rules(OVERRIDES_PATH)
        expected = [
            render_local_rule(rule, policies, "quantumult-x")
            for rule in local_rules
        ]
        if rules[: len(expected)] != expected:
            add_error(errors, "Quantumult X 生成物没有把本地覆盖层完整放在最前面")
    except BuildError as exc:
        add_error(errors, str(exc))
    if not rules:
        add_error(errors, "Quantumult X 生成物没有规则")


def validate_lock(manifest: Dict[str, Any], errors: List[str]) -> None:
    if not LOCK_PATH.exists():
        add_error(errors, f"缺少上游锁定信息：{LOCK_PATH}")
        return
    try:
        lock = load_json(LOCK_PATH)
    except BuildError as exc:
        add_error(errors, str(exc))
        return
    lock_sources = lock.get("sources", {})
    expected_ids = {str(source["id"]) for source in manifest.get("sources", [])}
    if set(lock_sources) != expected_ids:
        add_error(errors, "upstreams.lock.json 与上游清单的 id 集合不一致")
    for source_id, clients in lock_sources.items():
        if not isinstance(clients, dict):
            add_error(errors, f"锁定信息格式错误：{source_id}")
            continue
        for client, record in clients.items():
            if not isinstance(record, dict):
                add_error(errors, f"锁定信息格式错误：{source_id}/{client}")
                continue
            if not re.fullmatch(r"[0-9a-f]{64}", str(record.get("sha256", ""))):
                add_error(errors, f"锁定信息缺少 SHA-256：{source_id}/{client}")
            try:
                size = int(record.get("bytes", 0))
            except (TypeError, ValueError):
                size = 0
            if size <= 0:
                add_error(errors, f"锁定信息字节数无效：{source_id}/{client}")


def main() -> int:
    errors: List[str] = []
    try:
        manifest = load_json(MANIFEST_PATH)
        policies = load_json(POLICIES_PATH)
    except BuildError as exc:
        print(f"validation failed: {exc}", file=sys.stderr)
        return 2

    sources = validate_manifest(manifest, policies, errors)
    validate_mihomo(sources, errors)
    validate_qx(policies, errors)
    validate_lock(manifest, errors)
    if not REPORT_PATH.exists():
        add_error(errors, f"缺少构建报告：{REPORT_PATH}")

    if errors:
        print("validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1

    print("validation passed: manifest, lock, Mihomo Merge and Quantumult X artifact")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
