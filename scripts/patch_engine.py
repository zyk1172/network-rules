#!/usr/bin/env python3
"""Patch loading and lifecycle-aware transformations for canonical rules."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

try:
    import yaml  # type: ignore
except ImportError:  # pragma: no cover - reported with a useful error at runtime
    yaml = None

from rule_model import (
    CanonicalRule,
    canonicalize_type,
    make_rule,
    normalize_value,
)


PATCH_ACTIONS = {"add", "remove", "reclassify", "replace", "priority"}


class PatchError(ValueError):
    """Raised when a patch file is malformed."""


def _require_yaml() -> Any:
    if yaml is None:
        raise PatchError("解析 patch YAML 需要 PyYAML；请安装 requirements.txt 中的依赖")
    return yaml


def load_patches(directory: Path) -> List[Dict[str, Any]]:
    """Load patches in stable filename/order order."""

    loaded: List[Dict[str, Any]] = []
    seen_ids = set()
    yaml_module = _require_yaml()
    for path in sorted(directory.glob("*.yaml")):
        try:
            document = yaml_module.safe_load(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise PatchError(f"{path} YAML 解析失败：{exc}") from exc
        if document is None:
            continue
        if not isinstance(document, dict) or not isinstance(document.get("patches"), list):
            raise PatchError(f"{path} 顶层必须包含 patches 列表")
        for patch in document["patches"]:
            if not isinstance(patch, dict):
                raise PatchError(f"{path} 存在非对象 patch")
            patch = copy.deepcopy(patch)
            patch["_file"] = str(path.relative_to(directory.parent))
            patch_id = patch.get("id")
            action = patch.get("action")
            if not isinstance(patch_id, str) or not patch_id.strip():
                raise PatchError(f"{path} patch 缺少有效 id")
            if patch_id in seen_ids:
                raise PatchError(f"patch id 重复：{patch_id}")
            if action not in PATCH_ACTIONS:
                raise PatchError(f"{patch_id} 使用不支持的 action：{action}")
            if not isinstance(patch.get("reason"), str) or not patch["reason"].strip():
                raise PatchError(f"{patch_id} 缺少 reason")
            if not isinstance(patch.get("auto_drop_when_fixed", False), bool):
                raise PatchError(f"{patch_id} auto_drop_when_fixed 必须是布尔值")
            if not isinstance(patch.get("required", True), bool):
                raise PatchError(f"{patch_id} required 必须是布尔值")
            seen_ids.add(patch_id)
            loaded.append(patch)
    return loaded


def _normalized_match_value(match: Dict[str, Any], rule: CanonicalRule) -> Optional[str]:
    value = match.get("value")
    if value is None:
        return None
    return normalize_value(rule.type, str(value))


def patch_matches(rule: CanonicalRule, matcher: Optional[Dict[str, Any]]) -> bool:
    if matcher is None:
        return True
    if not isinstance(matcher, dict):
        return False
    match_type = matcher.get("type")
    if match_type is not None:
        normalized_type = canonicalize_type(str(match_type))
        if normalized_type != rule.type:
            return False
    match_value = _normalized_match_value(matcher, rule)
    if match_value is not None and match_value != rule.value:
        return False
    match_category = matcher.get("category")
    if match_category is not None and str(match_category) != rule.category:
        return False
    match_source = matcher.get("source")
    if match_source is not None and str(match_source) != rule.source:
        return False
    return True


def _mark_patched(rule: CanonicalRule, patch_id: str) -> None:
    rule.patched = True
    if patch_id not in rule.patch_ids:
        rule.patch_ids.append(patch_id)


def _outcome(patch: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": patch["id"],
        "action": patch["action"],
        "file": patch.get("_file", ""),
        "reason": patch["reason"],
        "required": patch.get("required", True),
        "auto_drop_when_fixed": patch.get("auto_drop_when_fixed", False),
        "status": "pending",
        "matched": 0,
        "affected": 0,
    }


def _new_patch_rule(patch: Dict[str, Any], category_ids: Sequence[str]) -> CanonicalRule:
    rule_data = patch.get("rule")
    if not isinstance(rule_data, dict):
        raise PatchError(f"{patch['id']} add 缺少 rule 对象")
    category = rule_data.get("category")
    if not isinstance(category, str) or category not in category_ids:
        raise PatchError(f"{patch['id']} add 的 category 无效：{category!r}")
    rule, reason = make_rule(
        str(rule_data.get("type", "")),
        str(rule_data.get("value", "")),
        category=category,
        source=f"patch:{patch['id']}",
        component=str(patch.get("_file", "patches")),
        source_rule=f"{rule_data.get('type')},{rule_data.get('value')}",
    )
    if rule is None:
        raise PatchError(f"{patch['id']} add 规则无效：{reason}")
    _mark_patched(rule, patch["id"])
    return rule


def apply_patches(
    candidates: List[CanonicalRule],
    patches: Sequence[Dict[str, Any]],
    category_ids: Sequence[str],
) -> Tuple[List[CanonicalRule], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Apply non-priority patches and return pending priority patches separately."""

    working = candidates
    outcomes: List[Dict[str, Any]] = []
    priority_patches: List[Dict[str, Any]] = []

    for patch in patches:
        result = _outcome(patch)
        action = patch["action"]
        patch_id = patch["id"]
        matcher = patch.get("match")
        if action in {"remove", "reclassify", "replace", "priority"} and not isinstance(
            matcher, dict
        ):
            result["status"] = "failed"
            result["error"] = "match must be an object"
            outcomes.append(result)
            continue

        if action == "priority":
            prefer = patch.get("prefer")
            over = patch.get("over", [])
            if not isinstance(prefer, str) or prefer not in category_ids:
                result["status"] = "failed"
                result["error"] = f"invalid prefer category: {prefer!r}"
            elif not isinstance(over, list) or not all(
                isinstance(item, str) for item in over
            ):
                result["status"] = "failed"
                result["error"] = "over must be a list of category ids"
            else:
                priority_patches.append(patch)
            outcomes.append(result)
            continue

        if action == "add":
            try:
                rule = _new_patch_rule(patch, category_ids)
            except PatchError as exc:
                result["status"] = "failed"
                result["error"] = str(exc)
                outcomes.append(result)
                continue
            result["matched"] = sum(
                1
                for candidate in working
                if candidate.category_key == rule.category_key
            )
            if result["matched"]:
                result["status"] = "obsolete_candidate"
            else:
                working.append(rule)
                result["status"] = "applied"
                result["affected"] = 1
            outcomes.append(result)
            continue

        if action == "remove":
            matched = [candidate for candidate in working if patch_matches(candidate, matcher)]
            result["matched"] = len(matched)
            if not matched:
                result["status"] = "obsolete_candidate"
            else:
                removed_ids = {id(candidate) for candidate in matched}
                working = [candidate for candidate in working if id(candidate) not in removed_ids]
                result["status"] = "applied"
                result["affected"] = len(matched)
            outcomes.append(result)
            continue

        if action == "reclassify":
            target = patch.get("to")
            source_category = patch.get("from")
            if not isinstance(target, str) or target not in category_ids:
                result["status"] = "failed"
                result["error"] = f"invalid to category: {target!r}"
                outcomes.append(result)
                continue
            if source_category is not None:
                if not isinstance(source_category, str) or source_category not in category_ids:
                    result["status"] = "failed"
                    result["error"] = f"invalid from category: {source_category!r}"
                    outcomes.append(result)
                    continue
            matched = [
                candidate
                for candidate in working
                if patch_matches(candidate, matcher)
                and (source_category is None or candidate.category == source_category)
            ]
            result["matched"] = len(matched)
            changed = [candidate for candidate in matched if candidate.category != target]
            if not changed:
                result["status"] = "obsolete_candidate"
            else:
                for candidate in changed:
                    candidate.category = target
                    _mark_patched(candidate, patch_id)
                result["status"] = "applied"
                result["affected"] = len(changed)
            outcomes.append(result)
            continue

        if action == "replace":
            replacement = patch.get("with")
            if not isinstance(replacement, dict):
                result["status"] = "failed"
                result["error"] = "replace 缺少 with 对象"
                outcomes.append(result)
                continue
            replacement_type = replacement.get("type")
            replacement_value = replacement.get("value")
            if not isinstance(replacement_type, str) or not isinstance(
                replacement_value, str
            ):
                result["status"] = "failed"
                result["error"] = "replace.with 需要 type 和 value"
                outcomes.append(result)
                continue
            matched = [candidate for candidate in working if patch_matches(candidate, matcher)]
            result["matched"] = len(matched)
            changed = []
            new_type = canonicalize_type(replacement_type)
            if new_type is None:
                result["status"] = "failed"
                result["error"] = f"replace.with type 不支持：{replacement_type!r}"
                outcomes.append(result)
                continue
            new_category = replacement.get("category")
            if new_category is not None and (
                not isinstance(new_category, str) or new_category not in category_ids
            ):
                result["status"] = "failed"
                result["error"] = f"replace.with category 无效：{new_category!r}"
                outcomes.append(result)
                continue
            for candidate in matched:
                new_value = normalize_value(new_type, replacement_value)
                candidate_category = new_category or candidate.category
                if (candidate.type, candidate.value, candidate.category) != (
                    new_type,
                    new_value,
                    candidate_category,
                ):
                    candidate.type = new_type
                    candidate.value = new_value
                    candidate.category = candidate_category
                    _mark_patched(candidate, patch_id)
                    changed.append(candidate)
            if not changed:
                result["status"] = "obsolete_candidate"
            else:
                result["status"] = "applied"
                result["affected"] = len(changed)
            outcomes.append(result)
            continue

        result["status"] = "failed"
        result["error"] = f"unhandled action: {action}"
        outcomes.append(result)

    return working, outcomes, priority_patches


def resolve_priority_patches(
    priority_patches: Sequence[Dict[str, Any]],
    outcomes: List[Dict[str, Any]],
    *,
    conflict_categories: Sequence[str],
    rule: CanonicalRule,
) -> Optional[Dict[str, Any]]:
    """Choose the first matching priority patch for a conflict group."""

    category_set = set(conflict_categories)
    outcome_map = {item["id"]: item for item in outcomes}
    for patch in priority_patches:
        prefer = patch.get("prefer")
        over = set(patch.get("over", []))
        if prefer not in category_set:
            continue
        other_categories = category_set - {prefer}
        if over and not (other_categories & over):
            continue
        if any(category not in over for category in other_categories):
            continue
        if not patch_matches(rule, patch.get("match")):
            continue
        result = outcome_map[patch["id"]]
        result["status"] = "applied"
        result["matched"] += 1
        result["affected"] += 1
        return patch
    return None


def patch_report(outcomes: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    details = [dict(item) for item in outcomes]
    return {
        "applied": sum(item["status"] == "applied" for item in details),
        "obsolete_candidates": sum(
            item["status"] == "obsolete_candidate" for item in details
        ),
        "failed": sum(item["status"] == "failed" for item in details),
        "details": details,
    }
