#!/usr/bin/env python3
"""Compile upstream rule components into canonical and client artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import shutil
import subprocess
import urllib.error
import urllib.request
from urllib.parse import quote
from collections import Counter, defaultdict
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from patch_engine import (
    PatchError,
    apply_patches,
    load_patches,
    patch_report,
    resolve_priority_patches,
)
from rule_model import (
    CANONICAL_TYPES,
    CanonicalRule,
    ParseResult,
    RuleModelError,
    client_supports,
    make_rule,
    parse_component,
    render_mihomo_rule,
    render_qx_rule,
)


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "sources" / "upstreams.json"
POLICIES_PATH = ROOT / "sources" / "policies.json"
PATCHES_DIR = ROOT / "patches"
OVERRIDES_PATH = ROOT / "overrides" / "rules.txt"
CACHE_DIR = ROOT / "sources" / "cache"
DIST_DIR = ROOT / "dist"
LOCK_PATH = ROOT / "sources" / "upstreams.lock.json"
CLIENTS = ("quantumult-x", "mihomo")
COMPONENT_FORMATS = {"qx-list", "meta-domain-yaml", "mihomo-yaml", "yaml", "mrs"}
COMPONENT_ROLES = {
    "canonical-authoritative",
    "audit-reference",
    "client-only-extra",
}
AUTHORITATIVE_ROLE = "canonical-authoritative"
AUDIT_ROLE = "audit-reference"
CLIENT_EXTRA_ROLE = "client-only-extra"


class BuildError(RuntimeError):
    """Raised for invalid manifests or unbuildable artifacts."""


def download(request: urllib.request.Request) -> bytes:
    """Retry transient transport failures, without masking integrity failures."""
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.read()
        except (urllib.error.URLError, TimeoutError, OSError):
            if attempt == 2:
                # Optional local fallback through the existing GitHub CLI.
                # No proxy settings or credentials are read, printed or changed.
                if shutil.which("gh"):
                    url = request.full_url
                    if url.startswith("https://raw.githubusercontent.com/"):
                        owner, repo, ref, path = url.removeprefix("https://raw.githubusercontent.com/").split("/", 3)
                        endpoint = f"repos/{owner}/{repo}/contents/{path}?ref={ref}"
                        command = ["gh", "api", endpoint, "-H", "Accept: application/vnd.github.raw+json"]
                    elif url.startswith("https://api.github.com/repos/"):
                        command = ["gh", "api", url.removeprefix("https://api.github.com/")]
                    else:
                        raise
                    try:
                        result = subprocess.run(command, check=True, capture_output=True, timeout=30)
                    except (subprocess.SubprocessError, OSError):
                        raise BuildError("GitHub 下载失败，CLI 备用传输也未成功；现有代理配置未改动") from None
                    return result.stdout
                raise
            time.sleep(0.5 * (attempt + 1))
    raise AssertionError("unreachable")


def load_json(path: Path) -> Dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BuildError(f"无法读取 JSON：{path}: {exc}") from exc
    if not isinstance(value, dict):
        raise BuildError(f"JSON 顶层必须是对象：{path}")
    return value


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


def category_label(source: Dict[str, Any]) -> str:
    return str(source.get("category") or source["id"])


def source_sort_key(source: Dict[str, Any]) -> Tuple[int, str]:
    return int(source.get("priority", 10000)), str(source["id"])


def policy_value(policies: Dict[str, Any], client: str, category_id: str) -> str:
    mapping = policies.get(client)
    if not isinstance(mapping, dict):
        raise BuildError(f"缺少客户端策略映射：{client}")
    if category_id in mapping:
        return str(mapping[category_id])
    # Keep a narrow migration aid for old local files; canonical data still
    # uses chatgpt as the stable category ID.
    if category_id == "openai" and "chatgpt" in mapping:
        return str(mapping["chatgpt"])
    raise BuildError(f"{client} 没有 category={category_id!r} 的策略映射")


def split_rule(line: str) -> List[str]:
    return [part.strip() for part in line.strip().split(",")]


def action_index(parts: Sequence[str]) -> int:
    if not parts or parts[0].upper() in {"FINAL", "MATCH"}:
        return 1
    return 2


def parse_local_rules(path: Path, category_ids: Sequence[str]) -> List[CanonicalRule]:
    if not path.exists():
        raise BuildError(f"缺少本地个人规则文件：{path}")
    rules: List[CanonicalRule] = []
    known_categories = set(category_ids)
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith(";"):
            continue
        parts = split_rule(stripped)
        index = action_index(parts)
        if len(parts) <= index or len(parts) < 2:
            raise BuildError(f"{path}:{number} 不是完整个人规则：{line}")
        category = parts[index]
        if category not in known_categories:
            raise BuildError(
                f"{path}:{number} 的 policy-key={category!r} 不是 canonical category"
            )
        rule, reason = make_rule(
            parts[0],
            parts[1],
            category=category,
            source="personal-rules",
            component=str(path.relative_to(ROOT)),
            source_rule=stripped,
            origin_category=category,
        )
        if rule is None:
            raise BuildError(f"{path}:{number} 无法转换为 canonical rule：{reason}")
        rules.append(rule)
    return rules


def validate_manifest(
    manifest: Dict[str, Any], policies: Dict[str, Any]
) -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    if manifest.get("schema_version") != 2:
        raise BuildError("sources/upstreams.json 必须使用 schema_version=2")
    publication = manifest.get("publication")
    if not isinstance(publication, dict):
        raise BuildError("sources/upstreams.json 缺少 publication")
    repository = str(publication.get("repository", ""))
    ref = str(publication.get("ref", ""))
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise BuildError(f"publication.repository 无效：{repository!r}")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", ref):
        raise BuildError(f"publication.ref 无效：{ref!r}")

    sources = manifest.get("sources")
    if not isinstance(sources, list) or not sources:
        raise BuildError("sources/upstreams.json 的 sources 为空")
    category_ids: set[str] = set()
    component_ids: set[str] = set()
    categories: Dict[str, Dict[str, Any]] = {}
    for source in sources:
        if not isinstance(source, dict):
            raise BuildError("上游分类必须是对象")
        source_id = source.get("id")
        if not isinstance(source_id, str) or not source_id.strip():
            raise BuildError("上游分类缺少有效 id")
        if source_id in category_ids:
            raise BuildError(f"canonical category id 重复：{source_id}")
        category_ids.add(source_id)
        category = str(source.get("category", "")).strip()
        if not category:
            raise BuildError(f"上游分类缺少可读名称：{source_id}")
        if not isinstance(source.get("priority"), int) or isinstance(
            source.get("priority"), bool
        ):
            raise BuildError(f"{source_id} priority 必须是整数")
        if not isinstance(source.get("enabled", True), bool):
            raise BuildError(f"{source_id} enabled 必须是布尔值")
        components = source.get("components")
        if not isinstance(components, dict):
            raise BuildError(f"{source_id} 缺少 components")
        authoritative_components: List[Tuple[str, str]] = []
        for client in CLIENTS:
            client_components = components.get(client)
            if not isinstance(client_components, list) or not client_components:
                raise BuildError(f"{source_id}/{client} 必须声明一个或多个组件")
            for component in client_components:
                if not isinstance(component, dict):
                    raise BuildError(f"{source_id}/{client} 存在非对象组件")
                component_id = component.get("id")
                if not isinstance(component_id, str) or not component_id.strip():
                    raise BuildError(f"{source_id}/{client} 组件缺少有效 id")
                if component_id in component_ids:
                    raise BuildError(f"上游组件 id 重复：{component_id}")
                component_ids.add(component_id)
                url = str(component.get("url", ""))
                if not url.startswith("https://raw.githubusercontent.com/"):
                    raise BuildError(f"{component_id} 不是允许的 GitHub raw URL")
                if "?" in url or "#" in url:
                    raise BuildError(f"{component_id} URL 不应含查询参数或片段")
                fmt = component.get("format")
                if fmt not in COMPONENT_FORMATS:
                    raise BuildError(f"{component_id} 使用不支持的格式：{fmt!r}")
                role = component.get("role")
                if role not in COMPONENT_ROLES:
                    raise BuildError(
                        f"{component_id} role 必须是 {sorted(COMPONENT_ROLES)} 之一"
                    )
                if "canonical" in component:
                    raise BuildError(
                        f"{component_id} 不再接受 canonical 字段，请使用明确的 role"
                    )
                if role == AUTHORITATIVE_ROLE:
                    authoritative_components.append((client, component_id))
                if "complete" in component and not isinstance(
                    component["complete"], bool
                ):
                    raise BuildError(f"{component_id} complete 必须是布尔值")
                if client == "mihomo" and fmt in {"mrs", "mihomo-yaml", "yaml"}:
                    behavior = component.get("behavior")
                    if behavior not in {"domain", "ipcidr", "classical"}:
                        raise BuildError(
                            f"{component_id} Mihomo behavior 无效：{behavior!r}"
                        )
                if fmt == "mrs" and role == AUTHORITATIVE_ROLE:
                    raise BuildError(
                        f"{component_id} MRS 无法作为 canonical-authoritative 输入"
                    )
        if len(authoritative_components) != 1:
            raise BuildError(
                f"{source_id} 必须恰好有一个 canonical-authoritative 组件，"
                f"实际为 {authoritative_components}"
            )
        for client in CLIENTS:
            mapping = policies.get(client)
            if not isinstance(mapping, dict) or source_id not in mapping:
                raise BuildError(f"{client} 缺少 category={source_id!r} 的策略映射")
        categories[source_id] = source
    return sources, categories


def component_cache_path(category_id: str, client: str, component: Dict[str, Any]) -> Path:
    explicit = component.get("cache")
    if isinstance(explicit, str) and explicit:
        return CACHE_DIR / explicit
    url = str(component["url"]).split("?", 1)[0]
    suffix = Path(url).suffix or ".data"
    safe_component = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(component["id"]))
    return CACHE_DIR / f"{category_id}.{client}.{safe_component}{suffix}"


def resolve_components(sources: Sequence[Dict[str, Any]], *, locked: bool = False) -> List[Dict[str, Any]]:
    """Pin each upstream ref once; a locked build never consults moving refs."""
    resolved = deepcopy(list(sources))
    lock = load_json(LOCK_PATH) if locked else {}
    commits: Dict[Tuple[str, str, str], str] = {}
    for source in resolved:
        if not source.get("enabled", True):
            continue
        for client, components in source["components"].items():
            for component in components:
                url = component["url"]
                owner, repo, ref, path = url.removeprefix("https://raw.githubusercontent.com/").split("/", 3)
                if locked:
                    record = lock.get("categories", {}).get(source["id"], {}).get("components", {}).get(client, {}).get(component["id"], {})
                    pinned = str(record.get("resolved_url", ""))
                    prefix = f"https://raw.githubusercontent.com/{owner}/{repo}/"
                    revision = pinned.removeprefix(prefix).split("/", 1)[0]
                    if (record.get("url") != url or record.get("role") != component["role"]
                            or not re.fullmatch(r"[0-9a-f]{40}", revision)
                            or pinned != f"{prefix}{revision}/{path}"
                            or not re.fullmatch(r"[0-9a-f]{64}", str(record.get("sha256", "")))):
                        raise BuildError(f"{component['id']} 缺少有效的不可变锁定输入；请执行在线 build 更新 lock")
                    component["_expected_sha256"] = record["sha256"]
                else:
                    key = owner, repo, ref
                    if key not in commits:
                        request = urllib.request.Request(
                            f"https://api.github.com/repos/{owner}/{repo}/commits/{quote(ref, safe='')}",
                            headers={"User-Agent": "network-rules-project/2.1", "Accept": "application/vnd.github+json"},
                        )
                        try:
                            revision = json.loads(download(request))["sha"]
                        except (OSError, ValueError, KeyError) as exc:
                            raise BuildError(f"无法锁定上游版本：{owner}/{repo}/{ref}") from exc
                        if not re.fullmatch(r"[0-9a-f]{40}", str(revision)):
                            raise BuildError(f"上游返回无效 commit：{owner}/{repo}/{ref}")
                        commits[key] = revision
                    pinned = f"https://raw.githubusercontent.com/{owner}/{repo}/{commits[key]}/{path}"
                component["_resolved_url"] = pinned
    return resolved


def fetch_component(
    category_id: str,
    client: str,
    component: Dict[str, Any],
    *,
    offline: bool,
    allow_stale: bool,
) -> Tuple[bytes, bool, Path]:
    url = str(component.get("_resolved_url", component["url"]))
    cache = component_cache_path(category_id, client, component)
    expected = component.get("_expected_sha256")
    if expected and cache.exists() and sha256(cache.read_bytes()) == expected:
        return cache.read_bytes(), offline, cache
    if offline:
        if not cache.exists():
            raise BuildError(f"离线模式缺少缓存：{cache}")
        data = cache.read_bytes()
        if expected and sha256(data) != expected:
            raise BuildError(f"离线缓存与 lock 不符：{component['id']}")
        return data, True, cache
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "network-rules-project/2.0"},
    )
    try:
        data = download(request)
        if not data:
            raise BuildError(f"上游返回空文件：{url}")
        if expected and sha256(data) != expected:
            raise BuildError(f"上游内容与锁定 hash 不符：{component['id']}")
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(data)
        return data, False, cache
    except (urllib.error.URLError, TimeoutError, OSError, BuildError) as exc:
        if allow_stale and not expected and cache.exists():
            print(f"warning: {category_id}/{client}/{component['id']} 使用旧缓存：{exc}", file=sys.stderr)
            return cache.read_bytes(), True, cache
        raise BuildError(f"拉取上游失败：{category_id}/{client}/{component['id']}: {exc}") from exc


def upstream_updated(data: bytes) -> Optional[str]:
    text = data.decode("utf-8", errors="ignore")
    match = re.search(r"^#\s*UPDATED:\s*(.+?)\s*$", text, re.MULTILINE)
    return match.group(1) if match else None


def collect_canonical_rules(
    sources: Sequence[Dict[str, Any]],
    *,
    offline: bool,
    allow_stale: bool,
    locked: bool = False,
) -> Tuple[
    List[CanonicalRule],
    Dict[str, Any],
    Dict[str, Dict[str, Any]],
    List[Dict[str, Any]],
    Dict[str, Dict[str, List[CanonicalRule]]],
]:
    """Fetch and classify components without implicitly unioning client inputs.

    Every category has exactly one authoritative component. Audit references are
    parsed only for drift reporting, while client-only extras are kept out of
    the shared canonical model and are emitted only for their declared client.
    """

    try:
        sources = resolve_components(sources, locked=locked or offline)
    except BuildError:
        if not allow_stale or locked or offline:
            raise
        # An explicitly requested stale build must still verify locked hashes.
        sources = resolve_components(sources, locked=True)
        offline = True
        print("warning: 无法解析最新上游版本；显式使用已锁定缓存", file=sys.stderr)
    candidates: List[CanonicalRule] = []
    lock: Dict[str, Any] = {"schema_version": 2, "categories": {}}
    category_stats: Dict[str, Dict[str, Any]] = {}
    component_reports: List[Dict[str, Any]] = []
    parsed_components: Dict[str, Dict[str, Dict[str, Any]]] = defaultdict(dict)
    authoritative_keys: Dict[str, set[Tuple[str, str]]] = defaultdict(set)
    client_extras: Dict[str, Dict[str, List[CanonicalRule]]] = {
        client: defaultdict(list) for client in CLIENTS
    }

    for source in sources:
        category_id = str(source["id"])
        stats = {
            "status": "enabled" if source.get("enabled", True) else "disabled",
            "raw_rules": 0,
            "normalized": 0,
            "unsupported_rules": 0,
            "authoritative_component": None,
            "audit_reference_rules": 0,
            "client_only_extra_rules": 0,
            "components": [],
        }
        category_stats[category_id] = stats
        lock_category: Dict[str, Any] = {
            "enabled": bool(source.get("enabled", True)),
            "components": {client: {} for client in CLIENTS},
        }
        lock["categories"][category_id] = lock_category
        if not source.get("enabled", True):
            continue

        for client in CLIENTS:
            for component in source["components"][client]:
                component_id = str(component["id"])
                data, stale, cache = fetch_component(
                    category_id,
                    client,
                    component,
                    offline=offline,
                    allow_stale=allow_stale,
                )
                lock_category["components"][client][component_id] = {
                    "url": str(component["url"]),
                    "resolved_url": component["_resolved_url"],
                    "role": str(component["role"]),
                    "bytes": len(data),
                    "sha256": sha256(data),
                    "upstream_updated": upstream_updated(data),
                    "stale_cache": stale,
                }
                parsed: Optional[ParseResult] = None
                if str(component["format"]) != "mrs":
                    try:
                        parsed = parse_component(
                            data,
                            component,
                            category=category_id,
                            source=str(source["provider"]),
                        )
                    except RuleModelError as exc:
                        raise BuildError(
                            f"{category_id}/{client}/{component_id} 解析失败：{exc}"
                        ) from exc
                report: Dict[str, Any] = {
                    "category": category_id,
                    "client": client,
                    "id": component_id,
                    "format": component["format"],
                    "role": str(component["role"]),
                    "contributes_to_canonical": component["role"] == AUTHORITATIVE_ROLE,
                    "complete": bool(component.get("complete", False)),
                    "bytes": len(data),
                    "stale_cache": stale,
                    "cache": str(cache.relative_to(ROOT)),
                }
                if parsed is None or not parsed.parsed:
                    report["parsed_rules"] = None
                    report["unsupported_rules"] = 0
                else:
                    report["raw_rules"] = parsed.raw_rules
                    report["parsed_rules"] = len(parsed.rules)
                    report["unsupported_rules"] = len(parsed.unsupported)
                    if parsed.unsupported:
                        report["unsupported_examples"] = parsed.unsupported[:10]
                    parsed_components[category_id][component_id] = {
                        "keys": {rule.key for rule in parsed.rules},
                        "role": str(component["role"]),
                        "client": client,
                    }
                    role = str(component["role"])
                    if role == AUTHORITATIVE_ROLE:
                        candidates.extend(parsed.rules)
                        stats["raw_rules"] += parsed.raw_rules
                        stats["normalized"] += len(parsed.rules)
                        stats["unsupported_rules"] += len(parsed.unsupported)
                        stats["authoritative_component"] = {
                            "client": client,
                            "id": component_id,
                        }
                        authoritative_keys[category_id].update(
                            rule.key for rule in parsed.rules
                        )
                    elif role == CLIENT_EXTRA_ROLE:
                        client_extras[client][category_id].extend(parsed.rules)
                        stats["client_only_extra_rules"] += len(parsed.rules)
                    elif role == AUDIT_ROLE:
                        stats["audit_reference_rules"] += len(parsed.rules)
                stats["components"].append(report)
                component_reports.append(report)

    for category_id, reports in parsed_components.items():
        expected = authoritative_keys[category_id]
        for component_id, parsed_info in reports.items():
            report = next(
                item
                for item in component_reports
                if item["category"] == category_id and item["id"] == component_id
            )
            keys = parsed_info["keys"]
            missing = sorted(expected - keys)
            extra = sorted(keys - expected)
            report["coverage_against_authoritative"] = {
                "missing": len(missing),
                "extra": len(extra),
                "missing_examples": missing[:10],
                "extra_examples": extra[:10],
            }

    return candidates, lock, category_stats, component_reports, client_extras


def deduplicate_candidates(
    candidates: Sequence[CanonicalRule],
) -> Tuple[List[CanonicalRule], List[Dict[str, Any]]]:
    unique: Dict[Tuple[str, str, str], CanonicalRule] = {}
    duplicates: List[Dict[str, Any]] = []
    for candidate in candidates:
        previous = unique.get(candidate.category_key)
        if previous is None:
            unique[candidate.category_key] = candidate
            continue
        previous.appearances.extend(candidate.appearances)
        previous.patched = previous.patched or candidate.patched
        for patch_id in candidate.patch_ids:
            if patch_id not in previous.patch_ids:
                previous.patch_ids.append(patch_id)
        duplicates.append(
            {
                "type": candidate.type,
                "value": candidate.value,
                "category": candidate.category,
                "kept": {
                    "source": previous.source,
                    "component": previous.component,
                },
                "dropped": {
                    "source": candidate.source,
                    "component": candidate.component,
                },
            }
        )
    return list(unique.values()), duplicates


def _appearance_details(rule: CanonicalRule) -> List[Dict[str, str]]:
    details: List[Dict[str, str]] = []
    seen = set()
    for appearance in rule.appearances:
        item = dict(appearance)
        item["category"] = rule.category
        if rule.origin_category and rule.origin_category != rule.category:
            item["original_category"] = rule.origin_category
        key = tuple(sorted(item.items()))
        if key not in seen:
            seen.add(key)
            details.append(item)
    return details


def resolve_canonical_rules(
    candidates: Sequence[CanonicalRule],
    categories: Dict[str, Dict[str, Any]],
    priority_patches: Sequence[Dict[str, Any]],
    patch_outcomes: List[Dict[str, Any]],
) -> Tuple[List[CanonicalRule], List[Dict[str, Any]]]:
    groups: Dict[Tuple[str, str], List[CanonicalRule]] = {}
    for candidate in candidates:
        groups.setdefault(candidate.key, []).append(candidate)

    final: List[CanonicalRule] = []
    conflicts: List[Dict[str, Any]] = []
    for key, group in groups.items():
        category_ids = list(dict.fromkeys(rule.category for rule in group))
        selected: CanonicalRule
        priority_patch = None
        if len(category_ids) > 1:
            priority_patch = resolve_priority_patches(
                priority_patches,
                patch_outcomes,
                conflict_categories=category_ids,
                rule=group[0],
            )
        if priority_patch is not None:
            selected = next(
                rule for rule in group if rule.category == priority_patch["prefer"]
            )
            reason = (
                f"priority patch {priority_patch['id']}: "
                f"{priority_patch['reason']}"
            )
        else:
            selected = min(
                group,
                key=lambda rule: (
                    -1 if rule.source == "personal-rules" else int(
                        categories.get(rule.category, {}).get("priority", 10000)
                    ),
                    int(categories.get(rule.category, {}).get("priority", 10000)),
                    rule.category,
                    rule.source,
                    rule.component,
                ),
            )
            reason = (
                "category priority: "
                f"{selected.category}="
                f"{categories.get(selected.category, {}).get('priority', 10000)}"
            )

        if len(category_ids) > 1:
            selected = deepcopy(selected)
            if priority_patch is not None:
                selected.patched = True
                if priority_patch["id"] not in selected.patch_ids:
                    selected.patch_ids.append(priority_patch["id"])
            selected.appearances = []
            for candidate in group:
                selected.appearances.extend(_appearance_details(candidate))
            conflicts.append(
                {
                    "rule": {"type": key[0], "value": key[1]},
                    "appeared_in": category_ids,
                    "appearances": selected.appearances,
                    "selected": selected.category,
                    "reason": reason,
                    "dropped": [
                        category_id
                        for category_id in category_ids
                        if category_id != selected.category
                    ],
                }
            )
        final.append(selected)

    for outcome in patch_outcomes:
        if outcome["status"] == "pending":
            outcome["status"] = "obsolete_candidate"
    return final, conflicts


def category_rule_sets(
    final_rules: Sequence[CanonicalRule],
    sources: Sequence[Dict[str, Any]],
) -> Tuple[List[CanonicalRule], Dict[str, List[CanonicalRule]]]:
    personal = [rule for rule in final_rules if rule.source == "personal-rules"]
    by_category: Dict[str, List[CanonicalRule]] = defaultdict(list)
    for rule in final_rules:
        if rule.source != "personal-rules":
            by_category[rule.category].append(rule)
    for source in sorted(sources, key=source_sort_key):
        by_category.setdefault(str(source["id"]), [])
    return personal, by_category


def write_qx_output(
    sources: Sequence[Dict[str, Any]],
    policies: Dict[str, Any],
    personal_rules: Sequence[CanonicalRule],
    by_category: Dict[str, List[CanonicalRule]],
    client_extras: Dict[str, Dict[str, List[CanonicalRule]]],
) -> Dict[str, Any]:
    """Write category-scoped QX files so third-party licenses are not mixed."""

    output_dir = DIST_DIR / "quantumult-x" / "providers"
    output_dir.mkdir(parents=True, exist_ok=True)
    sections: List[Dict[str, Any]] = []
    artifacts: List[str] = []
    generated_stem_names: set[str] = set()

    def write_category_file(
        file_name: str,
        category_id: str,
        label: str,
        rules: Sequence[CanonicalRule],
        *,
        license_scope: str,
        upstream: str,
    ) -> None:
        rendered = [
            "# NAME: network-rules Quantumult X category provider",
            "# GENERATED-BY: network-rules-project/scripts/build.py",
            f"# ===== CATEGORY: {label} ({category_id}) =====",
            "# PUBLICATION-SCOPE: one category only; do not combine another license scope in this file",
            f"# THIRD-PARTY-SOURCE: {upstream}",
            f"# LICENSE-SCOPE: {license_scope}",
            "# SOURCE-OF-TRUTH: canonical rule model after patches, deduplication and conflict resolution",
            "# This is a Quantumult X filter list. It does not contain nodes, rewrites or MitM settings.",
            f"# RULES: {len(rules)}",
        ]
        for rule in rules:
            if category_id == "personal-overlay":
                rendered.append(f"# CANONICAL-CATEGORY: {rule.category}")
            rendered.append(
                render_qx_rule(
                    rule,
                    policy_value(policies, "quantumult-x", rule.category),
                )
            )
        path = output_dir / file_name
        write_text(path, "\n".join(rendered))
        generated_stem_names.add(path.stem)
        relative = str(path.relative_to(ROOT))
        artifacts.append(relative)
        sections.append(
            {
                "id": category_id,
                "label": label,
                "rules": len(rules),
                "canonical_rules": len(rules),
                "client_only_extra_rules": 0,
                "artifact": relative,
                "license_scope": license_scope,
                "upstream": upstream,
            }
        )

    if personal_rules:
        write_category_file(
            "personal-overlay.list",
            "personal-overlay",
            "本地覆盖",
            personal_rules,
            license_scope="user-owned",
            upstream="overrides/rules.txt",
        )

    for source in sorted(sources, key=source_sort_key):
        if not source.get("enabled", True):
            continue
        category_id = str(source["id"])
        rules, canonical_count, client_extra_count, unsupported = merge_client_category_rules(
            by_category.get(category_id, []),
            client_extras.get("quantumult-x", {}).get(category_id, []),
            client="quantumult-x",
        )
        if unsupported:
            raise BuildError(
                f"Quantumult X client-only-extra 无法输出：{category_id}/{unsupported[0]}"
            )
        write_category_file(
            f"{category_id}.list",
            category_id,
            category_label(source),
            rules,
            license_scope=str(source.get("license", "upstream")),
            upstream=str(source.get("provider", "unknown")),
        )
        sections[-1]["canonical_rules"] = canonical_count
        sections[-1]["client_only_extra_rules"] = client_extra_count

    for path in output_dir.glob("*.list"):
        if path.stem in generated_stem_names:
            continue
        try:
            first_lines = path.read_text(encoding="utf-8").splitlines()[:3]
        except OSError:
            continue
        if "# GENERATED-BY: network-rules-project/scripts/build.py" in first_lines:
            path.unlink()

    # Remove the former mixed aggregate when rebuilding an existing checkout.
    legacy_path = DIST_DIR / "quantumult-x" / "aggregate.list"
    if legacy_path.exists():
        try:
            first_lines = legacy_path.read_text(encoding="utf-8").splitlines()[:3]
        except OSError:
            first_lines = []
        if "# GENERATED-BY: network-rules-project/scripts/build.py" in first_lines:
            legacy_path.unlink()

    return {
        "artifacts": artifacts,
        "artifact_mode": "category-scoped-license-separated",
        "mixed_derivative": False,
        "rules": sum(section["rules"] for section in sections),
        "canonical_rules": sum(section["canonical_rules"] for section in sections),
        "client_only_extra_rules": sum(
            section["client_only_extra_rules"] for section in sections
        ),
        "categories": sections,
    }


def provider_content(
    source: Dict[str, Any],
    rules: Sequence[CanonicalRule],
    *,
    canonical_count: int,
    client_extra_count: int,
) -> str:
    lines = [
        "# NAME: network-rules canonical provider",
        f"# CATEGORY: {category_label(source)} ({source['id']})",
        "# GENERATED-BY: network-rules-project/scripts/build.py",
        "# SOURCE-OF-TRUTH: canonical rule model after patches, deduplication and conflict resolution",
        "# THIRD-PARTY-DATA: see sources/ATTRIBUTIONS.md",
        f"# CANONICAL-RULES: {canonical_count}",
        f"# CLIENT-ONLY-EXTRA-RULES: {client_extra_count}",
        f"# RULES: {len(rules)}",
        "payload:",
    ]
    lines.extend(f"  - {yaml_quote(render_mihomo_rule(rule))}" for rule in rules)
    return "\n".join(lines)


def merge_client_category_rules(
    canonical_rules: Sequence[CanonicalRule],
    client_extra_rules: Sequence[CanonicalRule],
    *,
    client: str,
) -> Tuple[List[CanonicalRule], int, int, List[Dict[str, str]]]:
    """Combine shared rules with explicit client-only extras for one output."""

    rules: List[CanonicalRule] = []
    seen: set[Tuple[str, str]] = set()
    unsupported: List[Dict[str, str]] = []
    canonical_count = 0
    client_extra_count = 0
    for rule, role in [
        *[(rule, AUTHORITATIVE_ROLE) for rule in canonical_rules],
        *[(rule, CLIENT_EXTRA_ROLE) for rule in client_extra_rules],
    ]:
        if not client_supports(rule, client):
            unsupported.append(
                {
                    "type": rule.type,
                    "value": rule.value,
                    "category": rule.category,
                    "role": role,
                    "reason": f"unsupported by {client} client adapter",
                }
            )
            continue
        if rule.key in seen:
            continue
        seen.add(rule.key)
        rules.append(rule)
        if role == AUTHORITATIVE_ROLE:
            canonical_count += 1
        else:
            client_extra_count += 1
    return rules, canonical_count, client_extra_count, unsupported


def write_mihomo_output(
    manifest: Dict[str, Any],
    sources: Sequence[Dict[str, Any]],
    policies: Dict[str, Any],
    personal_rules: Sequence[CanonicalRule],
    by_category: Dict[str, List[CanonicalRule]],
    client_extras: Dict[str, Dict[str, List[CanonicalRule]]],
) -> Dict[str, Any]:
    publication = manifest["publication"]
    base_url = (
        f"https://raw.githubusercontent.com/{publication['repository']}/{publication['ref']}"
    )
    provider_dir = DIST_DIR / "mihomo" / "providers"
    provider_dir.mkdir(parents=True, exist_ok=True)
    active_ids = {
        str(source["id"]) for source in sources if source.get("enabled", True)
    }
    for path in provider_dir.glob("*.yaml"):
        try:
            first_lines = path.read_text(encoding="utf-8").splitlines()[:4]
        except OSError:
            continue
        if (
            "# GENERATED-BY: network-rules-project/scripts/build.py" in first_lines
            and path.stem not in active_ids
        ):
            path.unlink()

    lines = [
        "# NAME: network-rules Mihomo merge fragment",
        "# GENERATED-BY: network-rules-project/scripts/build.py",
        "# SOURCE-OF-TRUTH: canonical rule model after patches, deduplication and conflict resolution",
        "# This is a Clash Verge Rev/Mihomo Merge fragment, not a standalone profile.",
        "# Nodes, proxy-groups, DNS, rewrites and MitM stay in the base profile.",
        "",
        "rule-providers:",
    ]
    provider_ids: List[str] = []
    unsupported_rules: List[Dict[str, str]] = []
    mihomo_personal_rules: List[CanonicalRule] = []
    for rule in personal_rules:
        if client_supports(rule, "mihomo"):
            mihomo_personal_rules.append(rule)
        else:
            unsupported_rules.append(
                {
                    "type": rule.type,
                    "value": rule.value,
                    "category": rule.category,
                    "role": "personal-overlay",
                    "reason": "unsupported by Mihomo client adapter",
                }
            )
    provider_rule_counts: Dict[str, int] = {}
    provider_canonical_counts: Dict[str, int] = {}
    provider_client_extra_counts: Dict[str, int] = {}
    mihomo_client_extras = client_extras.get("mihomo", {})
    for source in sorted(sources, key=source_sort_key):
        if not source.get("enabled", True):
            continue
        category_id = str(source["id"])
        rules, canonical_count, client_extra_count, unsupported = merge_client_category_rules(
            by_category.get(category_id, []),
            mihomo_client_extras.get(category_id, []),
            client="mihomo",
        )
        unsupported_rules.extend(unsupported)
        provider_path = provider_dir / f"{category_id}.yaml"
        write_text(
            provider_path,
            provider_content(
                source,
                rules,
                canonical_count=canonical_count,
                client_extra_count=client_extra_count,
            ),
        )
        provider_rule_counts[category_id] = len(rules)
        provider_canonical_counts[category_id] = canonical_count
        provider_client_extra_counts[category_id] = client_extra_count
        provider_ids.append(category_id)
        lines.append(f"  # ===== CATEGORY: {category_label(source)} ({category_id}) =====")
        lines.extend(
            [
                f"  {category_id}:",
                "    type: http",
                "    behavior: \"classical\"",
                "    format: \"yaml\"",
                f"    url: {yaml_quote(base_url + '/dist/mihomo/providers/' + category_id + '.yaml')}",
                f"    path: {yaml_quote('./rule-providers/network-rules/' + category_id + '.yaml')}",
                "    interval: 86400",
            ]
        )

    lines.extend(["", "prepend-rules:", "  # ===== CATEGORY: 本地覆盖 (personal-overlay) ====="])
    for rule in mihomo_personal_rules:
        lines.append(f"  # CANONICAL-CATEGORY: {rule.category}")
        lines.append(
            f"  - {yaml_quote('{},{}'.format(render_mihomo_rule(rule), policy_value(policies, 'mihomo', rule.category)))}"
        )
    for source in sorted(sources, key=source_sort_key):
        if not source.get("enabled", True):
            continue
        category_id = str(source["id"])
        policy = policy_value(policies, "mihomo", category_id)
        lines.append(
            f"  # ===== CATEGORY: {category_label(source)} ({category_id}) ====="
        )
        lines.append(f"  - {yaml_quote(f'RULE-SET,{category_id},{policy}')}")

    merge_path = DIST_DIR / "mihomo" / "merge.yaml"
    write_text(merge_path, "\n".join(lines))
    return {
        "artifact": str(merge_path.relative_to(ROOT)),
        "provider_directory": str(provider_dir.relative_to(ROOT)),
        "providers": len(provider_ids),
        "provider_ids": provider_ids,
        "provider_rules": provider_rule_counts,
        "canonical_provider_rules": provider_canonical_counts,
        "client_only_extra_rules": provider_client_extra_counts,
        "prepend_rules": len(mihomo_personal_rules) + len(provider_ids),
        "personal_rules": len(mihomo_personal_rules),
        "canonical_personal_rules": len(personal_rules),
        "canonical_rules": sum(
            1
            for category_id in provider_ids
            for rule in by_category.get(category_id, [])
            if client_supports(rule, "mihomo")
        )
        + len(mihomo_personal_rules),
        "unsupported_rules": {
            "total": len(unsupported_rules),
            "by_type": dict(Counter(item["type"] for item in unsupported_rules)),
            "examples": unsupported_rules[:50],
        },
        "source": "canonical-plus-explicit-client-extras",
    }


def build_qx_entry_example(
    manifest: Dict[str, Any],
    qx_report: Dict[str, Any],
) -> None:
    publication = manifest["publication"]
    base_url = (
        f"https://raw.githubusercontent.com/{publication['repository']}/{publication['ref']}"
    )
    lines = [
        "# Quantumult X 需要将下面这些行按顺序加入 [filter_remote]。",
        "# 每个文件只包含一个 canonical category 或个人覆盖，避免把不同上游许可证物理合成一个文件。",
        "# 请保留当前顺序：它对应 personal override 和 category priority。",
    ]
    for section in qx_report.get("categories", []):
        artifact = section.get("artifact")
        if not artifact:
            continue
        category_id = str(section.get("id", "category"))
        lines.append(
            f"{base_url}/{artifact}, tag=网络规则-{category_id}, "
            "update-interval=86400, opt-parser=false, enabled=true"
        )
    content = "\n".join(lines)
    write_text(DIST_DIR / "quantumult-x" / "entry.example.conf", content)


def write_provenance(sources, personal_rules, by_category, conflicts):
    """Keep explainable canonical facts in separate category/license files."""
    directory = DIST_DIR / "canonical"
    decisions = {(c["rule"]["type"], c["rule"]["value"]): c for c in conflicts}
    sections = [("personal-overlay", "user-owned", personal_rules)] + [
        (s["id"], s["license"], by_category[s["id"]])
        for s in sorted(sources, key=source_sort_key) if s.get("enabled", True)
    ]
    artifacts = []
    for category, license_id, rules in sections:
        path = directory / f"{category}.jsonl"
        header = {"schema_version": 1, "category": category, "license": license_id}
        records = [json.dumps(header, ensure_ascii=False, sort_keys=True)]
        for rule in rules:
            record = asdict(rule)
            # Keep cross-source attribution as metadata, without copying the
            # other category's raw rule text into this license-scoped file.
            record["appearances"] = [
                {k: v for k, v in appearance.items() if k != "source_rule"}
                for appearance in record["appearances"]
            ]
            record["resolution"] = decisions.get(rule.key, {}).get("reason", "personal override" if rule.source == "personal-rules" else "category priority")
            records.append(json.dumps(record, ensure_ascii=False, sort_keys=True))
        write_text(path, "\n".join(records))
        artifacts.append(str(path.relative_to(ROOT)))
    for path in directory.glob("*.jsonl"):
        if str(path.relative_to(ROOT)) not in artifacts:
            path.unlink()
    return artifacts


def build(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--locked", action="store_true",
        help="使用 lock 中的不可变上游 commit 和 SHA256 复现生成物，不读取移动分支",
    )
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
        policies = load_json(POLICIES_PATH)
        sources, categories = validate_manifest(manifest, policies)
        category_ids = [
            str(source["id"])
            for source in sources
            if source.get("enabled", True)
        ]
        local_rules = parse_local_rules(OVERRIDES_PATH, category_ids)
        patches = load_patches(PATCHES_DIR)

        (
            upstream_candidates,
            lock,
            category_stats,
            component_reports,
            client_extras,
        ) = collect_canonical_rules(
            sources,
            offline=args.offline,
            allow_stale=args.allow_stale,
            locked=args.locked,
        )
        canonical_candidates = local_rules + upstream_candidates
        extra_object_ids = {
            id(rule): client
            for client, client_rules in client_extras.items()
            for rules in client_rules.values()
            for rule in rules
        }
        patched_working, patch_outcomes, priority_patches = apply_patches(
            canonical_candidates
            + [
                rule
                for client_rules in client_extras.values()
                for rules in client_rules.values()
                for rule in rules
            ],
            patches,
            category_ids,
        )
        patched_candidates: List[CanonicalRule] = []
        patched_client_extras: Dict[str, Dict[str, List[CanonicalRule]]] = {
            client: defaultdict(list) for client in CLIENTS
        }
        for rule in patched_working:
            owner_client = extra_object_ids.get(id(rule))
            if owner_client is None:
                patched_candidates.append(rule)
            else:
                patched_client_extras[owner_client][rule.category].append(rule)
        deduplicated, duplicates = deduplicate_candidates(patched_candidates)
        final_rules, conflicts = resolve_canonical_rules(
            deduplicated,
            categories,
            priority_patches,
            patch_outcomes,
        )
        personal_rules, by_category = category_rule_sets(final_rules, sources)

        qx_report = write_qx_output(
            sources,
            policies,
            personal_rules,
            by_category,
            patched_client_extras,
        )
        mihomo_report = write_mihomo_output(
            manifest,
            sources,
            policies,
            personal_rules,
            by_category,
            patched_client_extras,
        )
        build_qx_entry_example(manifest, qx_report)
        canonical_artifacts = write_provenance(sources, personal_rules, by_category, conflicts)

        category_patched = [
            rule for rule in patched_candidates if rule.source != "personal-rules"
        ]
        category_deduplicated = [
            rule for rule in deduplicated if rule.source != "personal-rules"
        ]
        category_final = [
            rule for rule in final_rules if rule.source != "personal-rules"
        ]
        after_patch_counts = Counter(rule.category for rule in category_patched)
        dedup_counts = Counter(rule.category for rule in category_deduplicated)
        final_counts = Counter(rule.category for rule in category_final)
        personal_after_patch = sum(
            1 for rule in patched_candidates if rule.source == "personal-rules"
        )
        for source in sources:
            category_id = str(source["id"])
            stats = category_stats[category_id]
            stats.update(
                {
                    "after_patch": after_patch_counts.get(category_id, 0),
                    "after_dedup": dedup_counts.get(category_id, 0),
                    "final": final_counts.get(category_id, 0),
                }
            )
            if not source.get("enabled", True):
                stats.update(
                    {
                        "raw_rules": 0,
                        "normalized": 0,
                        "after_patch": 0,
                        "after_dedup": 0,
                        "final": 0,
                    }
                )

        personal_stats = {
            "status": "enabled",
            "raw_rules": len(local_rules),
            "normalized": len(local_rules),
            "after_patch": personal_after_patch,
            "after_dedup": sum(
                1 for rule in deduplicated if rule.source == "personal-rules"
            ),
            "final": len(personal_rules),
            "components": [
                {
                    "id": "overrides/rules.txt",
                    "client": "canonical",
                    "role": AUTHORITATIVE_ROLE,
                    "contributes_to_canonical": True,
                    "parsed_rules": len(local_rules),
                }
            ],
        }

        patch_summary = patch_report(patch_outcomes)
        obsolete_details = [
            item for item in patch_outcomes if item["status"] == "obsolete_candidate"
        ]
        conflict_examples = sorted(
            conflicts,
            key=lambda item: (
                0 if item["reason"].startswith("priority patch") else 1,
                item["rule"]["type"],
                item["rule"]["value"],
            ),
        )[:100]
        patch_removed = sum(
            item["affected"]
            for item in patch_outcomes
            if item["action"] == "remove" and item["status"] == "applied"
        )
        conflict_dropped = sum(len(item["dropped"]) for item in conflicts)
        mihomo_unsupported = mihomo_report.get("unsupported_rules", {})
        mihomo_unsupported_total = int(mihomo_unsupported.get("total", 0))
        dropped_examples = [
            {"reason": "duplicate", **item} for item in duplicates[:20]
        ] + [
            {"reason": "conflict", **item} for item in conflict_examples[:20]
        ] + [
            {"reason": "client-unsupported", **item}
            for item in mihomo_unsupported.get("examples", [])[:20]
        ]
        categories_report = [
            {"id": "personal-overlay", "label": "本地覆盖", **personal_stats}
        ] + [
            {"id": str(source["id"]), "label": category_label(source), **category_stats[str(source["id"])]}
            for source in sorted(sources, key=source_sort_key)
        ]
        qx_client_extra_counts = {
            str(item.get("id")): int(item.get("client_only_extra_rules", 0))
            for item in qx_report.get("categories", [])
            if isinstance(item, dict) and int(item.get("client_only_extra_rules", 0)) > 0
        }
        mihomo_client_extra_counts = {
            str(category_id): int(count)
            for category_id, count in mihomo_report.get(
                "client_only_extra_rules", {}
            ).items()
            if int(count) > 0
        }
        report = {
            "schema_version": 2,
            "generator": "scripts/build.py",
            "canonical_artifacts": canonical_artifacts,
            "upstreams": {
                "component_count": len(component_reports),
                "roles": {
                    role: sum(item["role"] == role for item in component_reports)
                    for role in sorted(COMPONENT_ROLES)
                },
                "enabled_categories": [
                    str(source["id"])
                    for source in sorted(sources, key=source_sort_key)
                    if source.get("enabled", True)
                ],
                "disabled_categories": [
                    str(source["id"])
                    for source in sorted(sources, key=source_sort_key)
                    if not source.get("enabled", True)
                ],
                "components": component_reports,
            },
            "canonical_rules": {
                "raw": len(local_rules)
                + sum(int(category_stats[str(source["id"])]["raw_rules"]) for source in sources),
                "normalized": len(local_rules)
                + sum(int(category_stats[str(source["id"])]["normalized"]) for source in sources),
                "after_patch": len(patched_candidates),
                "after_dedup": len(deduplicated),
                "final": len(final_rules),
            },
            "patches": patch_summary,
            "duplicates": {
                "total": len(duplicates),
                "examples": duplicates[:50],
            },
            "conflicts": {
                "total": len(conflicts),
                "resolved": len(conflicts),
                "examples": conflict_examples,
            },
            "categories": categories_report,
            "client_only_extras": {
                "quantumult-x": qx_client_extra_counts,
                "mihomo": mihomo_client_extra_counts,
            },
            "client_outputs": {
                "quantumult-x": qx_report,
                "mihomo": mihomo_report,
            },
            "unsupported_rules": {
                "total": sum(
                    int(item.get("unsupported_rules", 0)) for item in component_reports
                ) + mihomo_unsupported_total,
                "upstream_components": [
                    item
                    for item in component_reports
                    if int(item.get("unsupported_rules", 0)) > 0
                ],
                "client_outputs": {
                    "mihomo": mihomo_unsupported,
                },
            },
            "dropped_rules": {
                "total": (
                    len(duplicates)
                    + conflict_dropped
                    + patch_removed
                    + mihomo_unsupported_total
                ),
                "by_reason": {
                    "duplicate": len(duplicates),
                    "conflict": conflict_dropped,
                    "patch-remove": patch_removed,
                    "client-unsupported": mihomo_unsupported_total,
                },
                "examples": dropped_examples,
            },
            "obsolete_patch_candidates": obsolete_details,
        }
        write_json(LOCK_PATH, lock)
        write_json(DIST_DIR / "build-report.json", report)
        print(
            f"built: canonical {len(final_rules)} rules; "
            f"Quantumult X {qx_report['rules']} rules; "
            f"Mihomo {mihomo_report['providers']} local providers; "
            f"patches applied {patch_summary['applied']}"
        )
        return 0
    except (BuildError, PatchError, RuleModelError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(build())
