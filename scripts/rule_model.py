#!/usr/bin/env python3
"""Canonical rule model and client-independent rule parsing/evaluation."""

from __future__ import annotations

import fnmatch
import ipaddress
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple


CANONICAL_TYPES = {
    "domain",
    "domain-suffix",
    "domain-keyword",
    "domain-wildcard",
    "ip-cidr",
    "ip-cidr6",
    "user-agent",
    "process-name",
}


TYPE_ALIASES = {
    "DOMAIN": "domain",
    "HOST": "domain",
    "DOMAIN-SUFFIX": "domain-suffix",
    "HOST-SUFFIX": "domain-suffix",
    "DOMAIN-KEYWORD": "domain-keyword",
    "HOST-KEYWORD": "domain-keyword",
    "DOMAIN-WILDCARD": "domain-wildcard",
    "HOST-WILDCARD": "domain-wildcard",
    "IP-CIDR": "ip-cidr",
    "IP-CIDR6": "ip-cidr6",
    "IP6-CIDR": "ip-cidr6",
    "USER-AGENT": "user-agent",
    "PROCESS-NAME": "process-name",
}


CANONICAL_TO_QX = {
    "domain": "HOST",
    "domain-suffix": "HOST-SUFFIX",
    "domain-keyword": "HOST-KEYWORD",
    "domain-wildcard": "HOST-WILDCARD",
    "ip-cidr": "IP-CIDR",
    "ip-cidr6": "IP6-CIDR",
    "user-agent": "USER-AGENT",
    "process-name": "PROCESS-NAME",
}


CANONICAL_TO_MIHOMO = {
    "domain": "DOMAIN",
    "domain-suffix": "DOMAIN-SUFFIX",
    "domain-keyword": "DOMAIN-KEYWORD",
    "domain-wildcard": "DOMAIN-WILDCARD",
    "ip-cidr": "IP-CIDR",
    "ip-cidr6": "IP-CIDR6",
    "user-agent": "USER-AGENT",
    "process-name": "PROCESS-NAME",
}


# The canonical vocabulary is intentionally broader than any one client. A
# client adapter must declare what it can actually consume instead of silently
# emitting a rule type that the target core ignores. Mihomo supports the
# current domain/IP/process forms, but not Quantumult X's USER-AGENT filter.
CLIENT_SUPPORTED_TYPES = {
    "quantumult-x": set(CANONICAL_TYPES),
    "mihomo": CANONICAL_TYPES - {"user-agent"},
}


class RuleModelError(ValueError):
    """Raised when an input cannot be represented by the canonical model."""


@dataclass
class CanonicalRule:
    """A normalized rule whose category is independent from client policy names."""

    type: str
    value: str
    category: str
    source: str
    component: str
    source_rule: str
    origin_category: Optional[str] = None
    patched: bool = False
    patch_ids: List[str] = field(default_factory=list)
    appearances: List[Dict[str, str]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.origin_category is None:
            self.origin_category = self.category
        if not self.appearances:
            self.appearances.append(
                {
                    "category": str(self.origin_category),
                    "source": self.source,
                    "component": self.component,
                    "source_rule": self.source_rule,
                }
            )

    @property
    def key(self) -> Tuple[str, str]:
        return self.type, self.value

    @property
    def category_key(self) -> Tuple[str, str, str]:
        return self.type, self.value, self.category


@dataclass
class ParseResult:
    rules: List[CanonicalRule]
    raw_rules: int
    unsupported: List[Dict[str, str]] = field(default_factory=list)
    parsed: bool = True


def canonicalize_type(raw_type: str) -> Optional[str]:
    """Map QX/Mihomo rule types to the stable canonical vocabulary."""

    token = str(raw_type).strip().upper().replace("_", "-")
    return TYPE_ALIASES.get(token)


def _unquote(value: str) -> str:
    value = str(value).strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def normalize_value(rule_type: str, raw_value: str) -> str:
    """Normalize a rule value without changing its matching intent."""

    value = _unquote(raw_value).strip()
    if rule_type in {"domain", "domain-suffix", "domain-keyword", "domain-wildcard"}:
        value = value.lower().rstrip(".")
        if rule_type == "domain-suffix":
            for prefix in ("+.", "*.", "."):
                if value.startswith(prefix):
                    value = value[len(prefix) :]
                    break
    elif rule_type in {"ip-cidr", "ip-cidr6"}:
        try:
            network = ipaddress.ip_network(value, strict=False)
        except ValueError:
            return value.lower()
        value = str(network)
    return value


def make_rule(
    raw_type: str,
    raw_value: str,
    *,
    category: str,
    source: str,
    component: str,
    source_rule: str,
    origin_category: Optional[str] = None,
) -> Tuple[Optional[CanonicalRule], Optional[str]]:
    """Create a canonical rule, returning a reason when the type is unsupported."""

    rule_type = canonicalize_type(raw_type)
    if rule_type is None:
        return None, f"unsupported type: {raw_type}"
    value = normalize_value(rule_type, raw_value)
    if not value:
        return None, "empty value"
    return (
        CanonicalRule(
            type=rule_type,
            value=value,
            category=category,
            source=source,
            component=component,
            source_rule=source_rule,
            origin_category=origin_category,
        ),
        None,
    )


def render_qx_rule(rule: CanonicalRule, policy: str) -> str:
    try:
        rule_type = CANONICAL_TO_QX[rule.type]
    except KeyError as exc:
        raise RuleModelError(f"QX 不支持 canonical 类型：{rule.type}") from exc
    return f"{rule_type},{rule.value},{policy}"


def client_supports(rule: CanonicalRule, client: str) -> bool:
    return rule.type in CLIENT_SUPPORTED_TYPES.get(client, set())


def render_mihomo_rule(rule: CanonicalRule) -> str:
    if not client_supports(rule, "mihomo"):
        raise RuleModelError(f"Mihomo 不支持 canonical 类型：{rule.type}")
    try:
        rule_type = CANONICAL_TO_MIHOMO[rule.type]
    except KeyError as exc:
        raise RuleModelError(f"Mihomo 不支持 canonical 类型：{rule.type}") from exc
    return f"{rule_type},{rule.value}"


def _parse_typed_lines(
    lines: Sequence[str],
    *,
    category: str,
    source: str,
    component: str,
) -> ParseResult:
    rules: List[CanonicalRule] = []
    unsupported: List[Dict[str, str]] = []
    raw_rules = 0
    for line in lines:
        raw = str(line).strip()
        if not raw or raw.startswith("#") or raw.startswith(";"):
            continue
        raw_rules += 1
        parts = [part.strip() for part in raw.split(",")]
        if len(parts) < 2:
            unsupported.append({"source_rule": raw, "reason": "missing value"})
            continue
        rule, reason = make_rule(
            parts[0],
            parts[1],
            category=category,
            source=source,
            component=component,
            source_rule=raw,
        )
        if rule is None:
            unsupported.append({"source_rule": raw, "reason": str(reason)})
        else:
            rules.append(rule)
    return ParseResult(rules=rules, raw_rules=raw_rules, unsupported=unsupported)


def _parse_meta_item(
    item: str,
    *,
    category: str,
    source: str,
    component: str,
) -> Tuple[Optional[CanonicalRule], Optional[str]]:
    raw = str(item).strip()
    if raw.startswith("+.") or raw.startswith("*."):
        return make_rule(
            "DOMAIN-SUFFIX",
            raw[2:],
            category=category,
            source=source,
            component=component,
            source_rule=raw,
        )
    if raw.startswith("full:"):
        return make_rule(
            "DOMAIN",
            raw[5:],
            category=category,
            source=source,
            component=component,
            source_rule=raw,
        )
    if raw.startswith("domain:"):
        return make_rule(
            "DOMAIN-SUFFIX",
            raw[7:],
            category=category,
            source=source,
            component=component,
            source_rule=raw,
        )
    if raw.startswith("keyword:"):
        return make_rule(
            "DOMAIN-KEYWORD",
            raw[8:],
            category=category,
            source=source,
            component=component,
            source_rule=raw,
        )
    if raw.startswith("regexp:") or raw.startswith("include:"):
        return None, "not safely representable as a canonical rule"
    if "/" in raw and re.match(r"^[0-9a-fA-F:.]+/\d+$", raw):
        rule_type = "IP-CIDR6" if ":" in raw else "IP-CIDR"
        return make_rule(
            rule_type,
            raw,
            category=category,
            source=source,
            component=component,
            source_rule=raw,
        )
    return make_rule(
        "DOMAIN",
        raw,
        category=category,
        source=source,
        component=component,
        source_rule=raw,
    )


def _load_payload(data: bytes, component_id: str) -> List[Any]:
    try:
        import yaml  # type: ignore
    except ImportError as exc:
        raise RuleModelError(
            "解析 YAML 需要 PyYAML；请安装 requirements.txt 中的依赖"
        ) from exc
    try:
        document = yaml.safe_load(data.decode("utf-8", errors="strict"))
    except Exception as exc:
        raise RuleModelError(f"{component_id} YAML 解析失败：{exc}") from exc
    if not isinstance(document, dict) or not isinstance(document.get("payload"), list):
        raise RuleModelError(f"{component_id} 缺少 payload 列表")
    return document["payload"]


def parse_component(
    data: bytes,
    component: Dict[str, Any],
    *,
    category: str,
    source: str,
) -> ParseResult:
    """Parse one declared component into canonical rules."""

    component_id = str(component.get("id", source))
    fmt = str(component.get("format", ""))
    if fmt == "mrs":
        return ParseResult(rules=[], raw_rules=0, parsed=False)

    if fmt == "qx-list":
        return _parse_typed_lines(
            data.decode("utf-8", errors="strict").splitlines(),
            category=category,
            source=source,
            component=component_id,
        )

    payload = _load_payload(data, component_id)
    if fmt == "meta-domain-yaml":
        rules: List[CanonicalRule] = []
        unsupported: List[Dict[str, str]] = []
        for item in payload:
            if not isinstance(item, str) or not item.strip():
                unsupported.append({"source_rule": str(item), "reason": "not a string"})
                continue
            rule, reason = _parse_meta_item(
                item,
                category=category,
                source=source,
                component=component_id,
            )
            if rule is None:
                unsupported.append({"source_rule": item, "reason": str(reason)})
            else:
                rules.append(rule)
        return ParseResult(
            rules=rules,
            raw_rules=len(payload),
            unsupported=unsupported,
        )

    if fmt in {"mihomo-yaml", "yaml"}:
        typed_lines: List[str] = []
        behavior = str(component.get("behavior", "classical"))
        for item in payload:
            if not isinstance(item, str):
                typed_lines.append(str(item))
                continue
            if "," in item or canonicalize_type(item.split(",", 1)[0]) is not None:
                typed_lines.append(item)
            elif behavior == "domain":
                typed_lines.append(f"DOMAIN-SUFFIX,{item}")
            elif behavior == "ipcidr":
                typed_lines.append(f"IP-CIDR,{item}")
            else:
                typed_lines.append(item)
        result = _parse_typed_lines(
            typed_lines,
            category=category,
            source=source,
            component=component_id,
        )
        # The YAML payload is the raw unit count, even when a malformed item
        # is represented as a string for the typed parser.
        result.raw_rules = len(payload)
        return result

    raise RuleModelError(f"不支持的组件格式：{component_id}/{fmt}")


def rule_matches(
    rule: CanonicalRule,
    host: str,
    *,
    user_agent: str = "",
    process_name: str = "",
) -> bool:
    """Evaluate one canonical rule for semantic routing tests."""

    host_value = str(host).strip().lower().rstrip(".")
    if rule.type == "domain":
        return host_value == rule.value
    if rule.type == "domain-suffix":
        return host_value == rule.value or host_value.endswith("." + rule.value)
    if rule.type == "domain-keyword":
        return rule.value in host_value
    if rule.type == "domain-wildcard":
        return fnmatch.fnmatchcase(host_value, rule.value)
    if rule.type in {"ip-cidr", "ip-cidr6"}:
        try:
            address = ipaddress.ip_address(host_value)
            network = ipaddress.ip_network(rule.value, strict=False)
        except ValueError:
            return False
        return address.version == network.version and address in network
    if rule.type == "user-agent":
        return fnmatch.fnmatchcase(user_agent, rule.value)
    if rule.type == "process-name":
        return process_name == rule.value or fnmatch.fnmatchcase(process_name, rule.value)
    return False


def first_matching_rule(
    rules: Sequence[CanonicalRule],
    host: str,
    *,
    user_agent: str = "",
    process_name: str = "",
) -> Optional[CanonicalRule]:
    for rule in rules:
        if rule_matches(
            rule,
            host,
            user_agent=user_agent,
            process_name=process_name,
        ):
            return rule
    return None
