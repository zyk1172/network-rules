#!/usr/bin/env python3
"""Explain published routes and prepare reviewable, tested domain corrections."""

from __future__ import annotations

import argparse
import ipaddress
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

from build import category_rule_sets, deduplicate_candidates, resolve_canonical_rules, source_sort_key
from patch_engine import apply_patches
from routing import parse_mihomo_rules, parse_qx_rules, qx_output_paths
from rule_model import CanonicalRule, client_supports, first_matching_rule, rule_matches

ROOT = Path(__file__).resolve().parents[1]


def normalize_host(value):
    host = value.strip().rstrip(".").lower()
    try:
        return str(ipaddress.ip_address(host))
    except ValueError:
        pass
    host = host.encode("idna").decode("ascii")
    if len(host) > 253 or not all(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in host.split(".")):
        raise ValueError("请输入单个域名或 IP，不接受 URL、路径、通配符或查询参数")
    return host


def load_canonical(root=ROOT):
    manifest = json.loads((root / "sources/upstreams.json").read_text())
    paths = [root / "dist/canonical/personal-overlay.jsonl"] + [
        root / f"dist/canonical/{s['id']}.jsonl"
        for s in sorted(manifest["sources"], key=source_sort_key) if s.get("enabled", True)
    ]
    rules, details = [], {}
    for path in paths:
        lines = path.read_text(encoding="utf-8").splitlines()
        for line in lines[1:]:
            record = json.loads(line)
            rule = CanonicalRule(**{k: v for k, v in record.items() if k != "resolution"})
            rules.append(rule)
            details[rule.category_key] = record
    return rules, details


def explain(host, root=ROOT):
    host = normalize_host(host)
    canonical, details = load_canonical(root)
    matches = [r for r in canonical if rule_matches(r, host)]
    qx = [r for path in qx_output_paths(root) for r in parse_qx_rules(path)]
    mihomo = parse_mihomo_rules(root / "dist/mihomo/merge.yaml", root / "dist/mihomo/providers", root)
    policies = json.loads((root / "sources/policies.json").read_text())
    clients = {}
    for client, rules in (("quantumult-x", qx), ("mihomo", mihomo)):
        winner = first_matching_rule(rules, host)
        clients[client] = {
            "category": winner.category if winner else None,
            "policy": policies[client].get(winner.category) if winner else None,
            "matched_rule": winner.source_rule if winner else None,
            "artifact": winner.component if winner else None,
        }
    return {
        "host": host,
        "scope": "published artifacts; no DNS request, runtime access or proxy change",
        "canonical": details[matches[0].category_key] if matches else None,
        "shadowed_matches": [details[r.category_key] for r in matches[1:]],
        "clients": clients,
        "fallback": None if matches else "交给基础配置 FINAL/MATCH；此工具不推断基础配置策略",
    }


def draft_patch(host, category, reason, rules, sources):
    """Correct only this host; reject proposals still shadowed by wider rules."""
    host = normalize_host(host)
    enabled = {s["id"]: s for s in sources if s.get("enabled", True)}
    if category not in enabled or not reason.strip():
        raise ValueError("目标必须是已启用分类，且必须提供 reason")
    try:
        address = ipaddress.ip_address(host)
        rule_type = "ip-cidr" if address.version == 4 else "ip-cidr6"
        value = f"{host}/{address.max_prefixlen}"
    except ValueError:
        rule_type, value = "domain", host
    if (winner := first_matching_rule(rules, host)) and winner.category == category:
        raise ValueError("该目标已经命中期望分类，无需增加 Patch")
    patch_id = "route-" + re.sub(r"[^a-z0-9-]", "-", host) + "-" + category
    patch_id = patch_id[:180]
    replacement = {"type": rule_type, "value": value, "category": category}
    patch = {
        "id": patch_id, "reason": reason.strip(),
        "added": datetime.now(timezone.utc).date().isoformat(),
        "required": True, "auto_drop_when_fixed": True,
    }
    if any(r.key == (rule_type, value) for r in rules):
        patch.update(action="replace", match={"type": rule_type, "value": value}, **{"with": replacement})
    else:
        patch.update(action="add", rule=replacement)
    # Work on copies: explaining or proposing must never mutate published facts.
    import copy
    working, outcomes, priority = apply_patches(copy.deepcopy(rules), [patch], list(enabled))
    dedup, _ = deduplicate_candidates(working)
    final, _ = resolve_canonical_rules(dedup, enabled, priority, outcomes)
    personal, grouped = category_rule_sets(final, sources)
    ordered = personal + [r for s in sorted(sources, key=source_sort_key) if s.get("enabled", True) for r in grouped[s["id"]]]
    for client in ("quantumult-x", "mihomo"):
        winner = first_matching_rule([r for r in ordered if client_supports(r, client)], host)
        if winner is None or winner.category != category:
            raise ValueError("单域名 Patch 仍被更高优先级的宽规则覆盖；请人工审查 explain 中的 shadowed_matches，不自动扩大修补范围")
    return {
        "patch_document": {"version": 1, "patches": [patch]},
        "routing_case": {"id": patch_id, "host": host, "expected_category": category},
        "review_required": True,
        "verification": "canonical simulation passed; rebuild and both-client routing tests required after acceptance",
    }


def accept_draft(draft, root=ROOT):
    """Install a reviewed draft into source files, with collision checks first."""
    case = draft["routing_case"]
    patch_id = case["id"]
    if not re.fullmatch(r"[a-z0-9-]{1,180}", patch_id):
        raise ValueError("无效 draft id")
    # Recreate and simulate from current facts rather than executing supplied YAML.
    rules, _ = load_canonical(root)
    manifest = json.loads((root / "sources/upstreams.json").read_text())
    reason = draft["patch_document"]["patches"][0]["reason"]
    refreshed = draft_patch(case["host"], case["expected_category"], reason, rules, manifest["sources"])
    if refreshed["routing_case"] != case:
        raise ValueError("draft 与当前输入不一致，请重新 propose")
    def reviewed_patches(document):
        return [{k: v for k, v in p.items() if k != "added"} for p in document["patches"]]
    if reviewed_patches(refreshed["patch_document"]) != reviewed_patches(draft["patch_document"]):
        raise ValueError("draft 已过时，修补操作发生变化，请重新 propose 并审阅")
    patch_path = root / "patches" / f"{patch_id}.yaml"
    cases_path = root / "tests/routing-cases.json"
    cases = json.loads(cases_path.read_text())
    from patch_engine import load_patches
    if patch_path.exists() or any(p["id"] == patch_id for p in load_patches(root / "patches")) or any(c["id"] == patch_id for c in cases):
        raise ValueError("Patch 或路由案例已存在，拒绝覆盖")
    cases.append(case)
    # These are explicit source changes, never dist or a client runtime profile.
    patch_path.write_text(yaml.safe_dump(refreshed["patch_document"], allow_unicode=True, sort_keys=False), encoding="utf-8")
    try:
        cases_path.write_text(json.dumps(cases, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except OSError:
        patch_path.unlink()
        raise
    return {"patch": str(patch_path), "case": str(cases_path), "next": "python3 scripts/build.py --locked && python3 scripts/validate.py"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("explain").add_argument("host")
    propose = sub.add_parser("propose")
    propose.add_argument("host")
    propose.add_argument("--category", required=True)
    propose.add_argument("--reason", required=True)
    propose.add_argument("--output", type=Path, help="可选：将待审草稿保存到 sources/local/ 下")
    sub.add_parser("accept").add_argument("draft", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "explain":
            result = explain(args.host)
        elif args.command == "accept":
            result = accept_draft(json.loads(args.draft.read_text()))
        else:
            rules, _ = load_canonical()
            manifest = json.loads((ROOT / "sources/upstreams.json").read_text())
            result = draft_patch(args.host, args.category, args.reason, rules, manifest["sources"])
            if args.output:
                target = args.output.resolve()
                if not target.is_relative_to(ROOT / "sources/local"):
                    raise ValueError("草稿只能保存在已忽略的 sources/local/ 下")
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("x", encoding="utf-8") as handle:
                    json.dump(result, handle, ensure_ascii=False, indent=2)
                    handle.write("\n")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
