#!/usr/bin/env python3
"""Prepare, but never activate, a rule-only Merge for an existing Clash profile."""

import argparse
import hashlib
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
BUILTINS = {"DIRECT", "REJECT", "REJECT-DROP", "PASS", "COMPATIBLE"}


def prepare(profile, policy_overrides, root=ROOT):
    raw = profile.read_bytes()
    try:
        base = yaml.safe_load(raw)
    except yaml.YAMLError:
        # Never echo YAML parser context from private node/subscription data.
        raise ValueError("无法解析基础配置 YAML（敏感内容已省略）") from None
    if not isinstance(base, dict):
        raise ValueError("基础配置必须是 YAML 对象")
    names = {g["name"] for g in base.get("proxy-groups", []) if isinstance(g, dict) and isinstance(g.get("name"), str)}
    names.update(p["name"] for p in base.get("proxies", []) if isinstance(p, dict) and isinstance(p.get("name"), str))
    manifest = json.loads((root / "sources/upstreams.json").read_text())
    policies = json.loads((root / "sources/policies.json").read_text())["mihomo"]
    enabled = {s["id"] for s in manifest["sources"] if s.get("enabled", True)}
    if set(policy_overrides) - enabled:
        raise ValueError("映射中存在未启用分类")
    effective = {c: policy_overrides.get(c, policies[c]) for c in enabled}
    missing = sorted(set(effective.values()) - names - BUILTINS)
    if missing:
        raise ValueError("基础配置缺少所需策略，请用 --policy category=现有策略 指定映射：" + ", ".join(missing))
    merge = yaml.safe_load((root / "dist/mihomo/merge.yaml").read_text())
    replacements = {c: "network-rules-" + c for c in merge["rule-providers"]}
    collisions = set(replacements.values()) & set(base.get("rule-providers", {}))
    if collisions:
        raise ValueError("基础配置已使用本项目 provider 名称，请先审核已有接入")
    # Category markers allow personal rules to map independently even when
    # several categories previously shared a policy name.
    from routing import CANONICAL_MARKER, CATEGORY_MARKER
    rules, category = [], None
    for raw_line in (root / "dist/mihomo/merge.yaml").read_text().splitlines():
        line = raw_line.strip()
        marker = CANONICAL_MARKER.match(line) or CATEGORY_MARKER.match(line)
        if marker:
            category = marker.group(1)
        if not line.startswith('- "'):
            continue
        item = json.loads(line[2:])
        parts = item.split(",")
        if parts[0] == "RULE-SET":
            category = parts[1]
            parts[1] = replacements[category]
        if category not in effective:
            raise ValueError("生成物缺少可用 canonical category")
        parts[2] = effective[category]
        rules.append(",".join(parts))
    fragment = {
        "rule-providers": {replacements[c]: p for c, p in merge["rule-providers"].items()},
        "prepend-rules": rules,
    }
    report = {
        "activated": False,
        "profile_sha256": hashlib.sha256(raw).hexdigest(),
        "policy_mapping": dict(sorted(effective.items())),
        "existing_provider_count": len(base.get("rule-providers", {})),
        "existing_rule_count": len(base.get("rules", [])),
        "candidate_provider_count": len(fragment["rule-providers"]),
        "candidate_rule_count": len(rules),
        "validation": "static policy and provider compatibility; runtime not tested",
        "next_step": "Review this rule-only fragment; activation is a separate operation.",
    }
    return fragment, report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--policy", action="append", default=[])
    args = parser.parse_args(argv)
    try:
        mapping = {}
        for value in args.policy:
            category, policy = value.split("=", 1)
            if category in mapping or not policy:
                raise ValueError("重复或空策略映射")
            mapping[category] = policy
        output = args.output_dir.resolve()
        if not output.is_relative_to(ROOT / "sources/local"):
            raise ValueError("本机接入草稿只能输出到已忽略的 sources/local/ 下")
        if output.exists():
            raise ValueError("输出目录已存在，拒绝覆盖；请指定新的目录")
        fragment, report = prepare(args.profile, mapping)
        output.mkdir(parents=True)
        (output / "merge.yaml").write_text(
            "# PREPARED ONLY — NOT ACTIVATED\n" + yaml.safe_dump(fragment, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )
        (output / "compatibility.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"output_directory": str(output), **report}, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(2, f"error: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
