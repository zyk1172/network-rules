#!/usr/bin/env python3
"""Build the public, client-specific rule artifacts.

The repository deliberately keeps upstream URLs and local overrides separate:
the scheduled workflow refreshes public inputs, while overrides/rules.txt is
never generated or replaced.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "sources" / "upstreams.json"
POLICIES_PATH = ROOT / "sources" / "policies.json"
OVERRIDES_PATH = ROOT / "overrides" / "rules.txt"
CACHE_DIR = ROOT / "sources" / "cache"
DIST_DIR = ROOT / "dist"
LOCK_PATH = ROOT / "sources" / "upstreams.lock.json"

QX_TYPE_MAP = {
    "DOMAIN": "HOST",
    "DOMAIN-SUFFIX": "HOST-SUFFIX",
    "DOMAIN-KEYWORD": "HOST-KEYWORD",
    "DOMAIN-WILDCARD": "HOST-WILDCARD",
    "IP-CIDR": "IP-CIDR",
    "IP-CIDR6": "IP6-CIDR",
    "IP6-CIDR": "IP6-CIDR",
    "GEOIP": "GEOIP",
    "IP-ASN": "IP-ASN",
    "PROCESS-NAME": "PROCESS-NAME",
    "DST-PORT": "DEST-PORT",
    "SRC-IP-CIDR": "SRC-IP-CIDR",
    "URL-REGEX": "URL-REGEX",
    "USER-AGENT": "USER-AGENT",
    "MATCH": "FINAL",
    "FINAL": "FINAL",
}

FINAL_TYPES = {"MATCH", "FINAL"}

# Common rule types remain available for pass-through local overrides, but no
# common GEOIP/CN/LAN category is emitted by the public upstream aggregation.


class BuildError(RuntimeError):
    """Raised for an invalid source or an unbuildable artifact."""


def load_json(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BuildError(f"无法读取 JSON：{path}: {exc}") from exc


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def yaml_quote(value: str) -> str:
    # JSON double-quoted strings are valid YAML scalars and safely quote URLs
    # and Unicode policy names.
    return json.dumps(value, ensure_ascii=False)


def cache_path(source_id: str, client: str, url: str) -> Path:
    suffix = Path(url.split("?", 1)[0]).suffix or ".data"
    safe_client = client.replace("-", "_")
    return CACHE_DIR / f"{source_id}.{safe_client}{suffix}"


def fetch_source(
    source_id: str,
    client: str,
    url: str,
    *,
    offline: bool,
    allow_stale: bool,
) -> Tuple[bytes, bool]:
    if not url.startswith("https://raw.githubusercontent.com/"):
        raise BuildError(f"{source_id}/{client} 不是受允许的 GitHub raw URL：{url}")

    local_cache = cache_path(source_id, client, url)
    if offline:
        if not local_cache.exists():
            raise BuildError(f"离线模式缺少缓存：{local_cache}")
        return local_cache.read_bytes(), True

    request = urllib.request.Request(
        url,
        headers={"User-Agent": "network-rules-project/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            data = response.read()
        if not data:
            raise BuildError(f"上游返回空文件：{url}")
        local_cache.parent.mkdir(parents=True, exist_ok=True)
        local_cache.write_bytes(data)
        return data, False
    except (urllib.error.URLError, TimeoutError, OSError, BuildError) as exc:
        if allow_stale and local_cache.exists():
            print(f"warning: {source_id}/{client} 使用旧缓存：{exc}", file=sys.stderr)
            return local_cache.read_bytes(), True
        raise BuildError(f"拉取上游失败：{source_id}/{client}: {exc}") from exc


def upstream_updated(data: bytes) -> Optional[str]:
    text = data.decode("utf-8", errors="ignore")
    match = re.search(r"^#\s*UPDATED:\s*(.+?)\s*$", text, re.MULTILINE)
    return match.group(1) if match else None


def policy_value(policies: Dict[str, Any], client: str, key: str) -> str:
    mapping = policies.get(client)
    if not isinstance(mapping, dict):
        raise BuildError(f"缺少客户端策略映射：{client}")

    token = key.strip()
    if token in mapping:
        return str(mapping[token])
    lower_token = token.lower()
    for map_key, value in mapping.items():
        if str(map_key).lower() == lower_token:
            return str(value)
    # Allow a client-specific policy name directly in overrides/rules.txt.
    if token in {str(value) for value in mapping.values()}:
        return token
    raise BuildError(
        f"{client} 没有 policy-key={key!r}；请先在 sources/policies.json 增加映射"
    )


def split_rule(line: str) -> List[str]:
    return [part.strip() for part in line.strip().split(",")]


def action_index(parts: Sequence[str]) -> int:
    if not parts or parts[0].upper() in FINAL_TYPES:
        return 1
    return 2


def parse_local_rules(path: Path) -> List[List[str]]:
    if not path.exists():
        raise BuildError(f"缺少本地覆盖文件：{path}")
    result: List[List[str]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith(";"):
            continue
        parts = split_rule(stripped)
        index = action_index(parts)
        if len(parts) <= index or not parts[0]:
            raise BuildError(f"{path}:{number} 不是完整规则：{line}")
        result.append(parts)
    return result


def render_local_rule(parts: Sequence[str], policies: Dict[str, Any], client: str) -> str:
    rendered = list(parts)
    rule_type = rendered[0].upper()
    rendered[0] = (
        QX_TYPE_MAP.get(rule_type, rule_type)
        if client == "quantumult-x"
        else rule_type
    )
    rendered[action_index(rendered)] = policy_value(
        policies, client, rendered[action_index(rendered)]
    )
    return ",".join(rendered)


def normalize_key(rule: str) -> Tuple[str, ...]:
    parts = split_rule(rule)
    index = action_index(parts)
    # Policy is deliberately excluded: the first source wins when the same
    # condition appears with different actions, and the conflict is reported.
    return tuple([parts[0].upper()] + parts[1:index] + parts[index + 1 :])


def add_first_wins(
    output: List[str],
    seen: Dict[Tuple[str, ...], str],
    rule: str,
    conflicts: List[Dict[str, str]],
    source_id: str,
) -> bool:
    key = normalize_key(rule)
    previous = seen.get(key)
    if previous is not None:
        if previous != rule:
            conflicts.append(
                {"source": source_id, "rule": rule, "kept": previous}
            )
        return False
    seen[key] = rule
    output.append(rule)
    return True


def strip_yaml_scalar(value: str) -> str:
    value = value.strip()
    if " #" in value:
        value = value.split(" #", 1)[0].rstrip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    return value.strip()


def parse_meta_domain_yaml(data: bytes, source_id: str) -> Tuple[List[str], int]:
    """Convert MetaCubeX geosite YAML payload entries into QX rules."""

    rules: List[str] = []
    unsupported = 0
    text = data.decode("utf-8", errors="strict")
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line.startswith("-"):
            continue
        value = strip_yaml_scalar(line[1:].strip())
        if not value or value.startswith("#"):
            continue
        if value.startswith("+.") or value.startswith("*."):
            rule_type, value = "HOST-SUFFIX", value[2:]
        elif value.startswith("full:"):
            rule_type, value = "HOST", value[5:]
        elif value.startswith("domain:"):
            rule_type, value = "HOST-SUFFIX", value[7:]
        elif value.startswith("keyword:"):
            rule_type, value = "HOST-KEYWORD", value[8:]
        elif value.startswith("regexp:") or value.startswith("include:"):
            unsupported += 1
            continue
        elif "/" in value and re.match(r"^[0-9a-fA-F:.]+/\d+$", value):
            rule_type = "IP-CIDR6" if ":" in value else "IP-CIDR"
        else:
            rule_type = "HOST"
        value = value.strip()
        if not value or value.startswith("!"):
            unsupported += 1
            continue
        rules.append(f"{rule_type},{value}")
    if unsupported:
        print(
            f"warning: {source_id}/quantumult-x 跳过 {unsupported} 条无法无损转换的条目",
            file=sys.stderr,
        )
    return rules, unsupported


def parse_qx_list(data: bytes, source_id: str) -> Tuple[List[str], int]:
    rules: List[str] = []
    unsupported = 0
    text = data.decode("utf-8", errors="strict")
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith(";"):
            continue
        parts = split_rule(line)
        if len(parts) < 2:
            unsupported += 1
            continue
        parts[0] = parts[0].upper()
        if len(parts) < 3:
            unsupported += 1
            continue
        rules.append(",".join(parts))
    if unsupported:
        print(
            f"warning: {source_id}/quantumult-x 跳过 {unsupported} 条无法识别的条目",
            file=sys.stderr,
        )
    return rules, unsupported


def convert_qx_rule(rule: str, policy: str) -> str:
    parts = split_rule(rule)
    if len(parts) < 2:
        raise BuildError(f"上游 QX 规则不完整：{rule}")
    parts[0] = QX_TYPE_MAP.get(parts[0].upper(), parts[0].upper())
    index = action_index(parts)
    if len(parts) <= index:
        parts.append(policy)
    else:
        parts[index] = policy
    return ",".join(parts)


def build_quantumult_x(
    sources: Sequence[Dict[str, Any]],
    payloads: Dict[Tuple[str, str], bytes],
    policies: Dict[str, Any],
    local_rules: Sequence[Sequence[str]],
) -> Dict[str, Any]:
    output: List[str] = []
    seen: Dict[Tuple[str, ...], str] = {}
    conflicts: List[Dict[str, str]] = []
    source_counts: Dict[str, int] = {}
    unsupported_counts: Dict[str, int] = {}

    for parts in local_rules:
        add_first_wins(
            output,
            seen,
            render_local_rule(parts, policies, "quantumult-x"),
            conflicts,
            "local-overlay",
        )

    source_sections: List[str] = []
    for source in sources:
        client_cfg = source.get("quantumult_x")
        if not client_cfg:
            continue
        source_id = str(source["id"])
        source_sections.append(source_id)
        raw = payloads[(source_id, "quantumult-x")]
        if client_cfg["format"] == "meta-domain-yaml":
            parsed, unsupported = parse_meta_domain_yaml(raw, source_id)
            parsed = [
                convert_qx_rule(
                    rule,
                    policy_value(policies, "quantumult-x", client_cfg["policy_key"]),
                )
                for rule in parsed
            ]
        elif client_cfg["format"] == "qx-list":
            parsed, unsupported = parse_qx_list(raw, source_id)
            parsed = [
                convert_qx_rule(
                    rule,
                    policy_value(policies, "quantumult-x", client_cfg["policy_key"]),
                )
                for rule in parsed
            ]
        else:
            raise BuildError(
                f"不支持的 Quantumult X 输入格式：{source_id}/{client_cfg['format']}"
            )
        added = 0
        for rule in parsed:
            added += int(add_first_wins(output, seen, rule, conflicts, source_id))
        source_counts[source_id] = added
        unsupported_counts[source_id] = unsupported

    header = [
        "# NAME: network-rules aggregate",
        "# GENERATED-BY: network-rules-project/scripts/build.py",
        "# ORDER: local overlay -> PT -> ads -> service categories",
        "# This is a Quantumult X filter list. It does not contain nodes, rewrites or MitM settings.",
    ]
    for source_id in source_sections:
        header.append(f"# SOURCE: {source_id}")
    write_text(DIST_DIR / "quantumult-x" / "aggregate.list", "\n".join(header + output))

    return {
        "rules": len(output),
        "local_rules": len(local_rules),
        "source_rules": source_counts,
        "unsupported": unsupported_counts,
        "conflicts": len(conflicts),
        "conflict_examples": conflicts[:20],
    }


def build_mihomo(
    sources: Sequence[Dict[str, Any]],
    policies: Dict[str, Any],
    local_rules: Sequence[Sequence[str]],
) -> Dict[str, Any]:
    providers: List[str] = []
    lines = [
        "# NAME: network-rules Mihomo merge fragment",
        "# GENERATED-BY: network-rules-project/scripts/build.py",
        "# This is a Clash Verge Rev/Mihomo Merge fragment, not a standalone profile.",
        "# Local rules are prepended; proxy nodes, proxy-groups, DNS, rewrites and MitM stay in the base profile.",
        "",
        "rule-providers:",
    ]
    for source in sources:
        client_cfg = source.get("mihomo")
        if not client_cfg:
            continue
        source_id = str(source["id"])
        providers.append(source_id)
        lines.extend(
            [
                f"  {source_id}:",
                "    type: http",
                f"    behavior: {yaml_quote(str(client_cfg['behavior']))}",
                f"    format: {yaml_quote(str(client_cfg['format']))}",
                f"    url: {yaml_quote(str(client_cfg['url']))}",
                f"    path: {yaml_quote(str(client_cfg['path']))}",
                "    interval: 86400",
            ]
        )

    lines.extend(["", "prepend-rules:"])
    for parts in local_rules:
        lines.append(
            f"  - {yaml_quote(render_local_rule(parts, policies, 'mihomo'))}"
        )
    for source in sources:
        client_cfg = source.get("mihomo")
        if not client_cfg:
            continue
        policy = policy_value(policies, "mihomo", client_cfg["policy_key"])
        rule_set = f"RULE-SET,{source['id']},{policy}"
        lines.append(f"  - {yaml_quote(rule_set)}")

    write_text(DIST_DIR / "mihomo" / "merge.yaml", "\n".join(lines))
    return {
        "providers": len(providers),
        "provider_ids": providers,
        "prepend_rules": len(local_rules) + len(providers),
        "local_rules": len(local_rules),
    }


def build_qx_entry_example() -> None:
    content = "\n".join(
        [
            "# 将下面这一行加入 Quantumult X 的 [filter_remote]。",
            "# 发布本仓库后，把 OWNER/REPOSITORY 替换为你的 GitHub 路径。",
            "https://raw.githubusercontent.com/OWNER/REPOSITORY/main/dist/quantumult-x/aggregate.list, tag=网络规则聚合, update-interval=86400, opt-parser=false, enabled=true",
        ]
    )
    write_text(DIST_DIR / "quantumult-x" / "entry.example.conf", content)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--offline",
        action="store_true",
        help="只使用 sources/cache 中的缓存，不访问网络",
    )
    parser.add_argument(
        "--allow-stale",
        action="store_true",
        help="网络拉取失败时允许使用旧缓存；适合本地临时构建，不建议自动更新工作流使用",
    )
    args = parser.parse_args(argv)

    try:
        manifest = load_json(MANIFEST_PATH)
        policy_file = load_json(POLICIES_PATH)
        sources = manifest.get("sources")
        if not isinstance(sources, list) or not sources:
            raise BuildError("sources/upstreams.json 没有有效 sources")
        local_rules = parse_local_rules(OVERRIDES_PATH)

        payloads: Dict[Tuple[str, str], bytes] = {}
        lock: Dict[str, Any] = {"schema_version": 1, "sources": {}}
        for source in sources:
            source_id = str(source["id"])
            lock["sources"][source_id] = {}
            for client, client_key in (("quantumult-x", "quantumult_x"), ("mihomo", "mihomo")):
                client_cfg = source.get(client_key)
                if not client_cfg:
                    continue
                data, stale = fetch_source(
                    source_id,
                    client,
                    str(client_cfg["url"]),
                    offline=args.offline,
                    allow_stale=args.allow_stale,
                )
                payloads[(source_id, client)] = data
                lock["sources"][source_id][client] = {
                    "url": str(client_cfg["url"]),
                    "bytes": len(data),
                    "sha256": sha256(data),
                    "upstream_updated": upstream_updated(data),
                    "stale_cache": stale,
                }

        qx_report = build_quantumult_x(sources, payloads, policy_file, local_rules)
        mihomo_report = build_mihomo(sources, policy_file, local_rules)
        build_qx_entry_example()
        write_json(LOCK_PATH, lock)
        write_json(
            DIST_DIR / "build-report.json",
            {
                "schema_version": 1,
                "generator": "scripts/build.py",
                "quantumult_x": qx_report,
                "mihomo": mihomo_report,
            },
        )
        print(
            f"built: Quantumult X {qx_report['rules']} rules; "
            f"Mihomo {mihomo_report['providers']} providers; "
            f"local overlay {len(local_rules)} rules"
        )
        return 0
    except BuildError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
