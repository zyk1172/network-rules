#!/usr/bin/env python3
"""Render a compact Markdown summary for the automated update pull request."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable


ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "dist" / "build-report.json"


def _number(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _rows(categories: Iterable[Dict[str, Any]]) -> str:
    lines = [
        "| category | raw | normalized | after patch | after dedup | final |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for category in categories:
        lines.append(
            "| {id} | {raw} | {normalized} | {after_patch} | {after_dedup} | {final} |".format(
                id=category.get("id", ""),
                raw=_number(category.get("raw_rules")),
                normalized=_number(category.get("normalized")),
                after_patch=_number(category.get("after_patch")),
                after_dedup=_number(category.get("after_dedup")),
                final=_number(category.get("final")),
            )
        )
    return "\n".join(lines)


def render(report: Dict[str, Any]) -> str:
    upstreams = report.get("upstreams", {})
    canonical = report.get("canonical_rules", {})
    patches = report.get("patches", {})
    conflicts = report.get("conflicts", {})
    unsupported = report.get("unsupported_rules", {})
    categories = report.get("categories", [])
    clients = report.get("client_outputs", {})
    lines = [
        "本 PR 由上游规则自动更新工作流生成，需人工审查后合并。",
        "",
        "## Upstream changes",
        "",
        f"- Components processed: {_number(upstreams.get('component_count'))}",
        f"- Enabled categories: {', '.join(upstreams.get('enabled_categories', [])) or 'none'}",
        f"- Disabled categories: {', '.join(upstreams.get('disabled_categories', [])) or 'none'}",
        "",
        "## Canonical",
        "",
        f"- Raw: {_number(canonical.get('raw'))}",
        f"- Normalized: {_number(canonical.get('normalized'))}",
        f"- After patch: {_number(canonical.get('after_patch'))}",
        f"- After dedup: {_number(canonical.get('after_dedup'))}",
        f"- Final: {_number(canonical.get('final'))}",
        f"- Unsupported upstream/client rules: {_number(unsupported.get('total'))}",
        "",
        "## Patches",
        "",
        f"- Applied: {_number(patches.get('applied'))}",
        f"- Obsolete candidates: {_number(patches.get('obsolete_candidates'))}",
        f"- Failed: {_number(patches.get('failed'))}",
        "",
        "## Conflicts",
        "",
        f"- Total: {_number(conflicts.get('total'))}",
        f"- Resolved: {_number(conflicts.get('resolved'))}",
        "",
        "## Categories",
        "",
        _rows(category for category in categories if isinstance(category, dict)),
        "",
        "## Client outputs",
        "",
    ]
    for client_id, client in clients.items():
        if not isinstance(client, dict):
            continue
        if client_id == "quantumult-x":
            lines.append(f"- Quantumult X: {_number(client.get('rules'))} rules")
        else:
            lines.append(
                f"- Mihomo: {_number(client.get('providers'))} local providers; "
                f"{_number(client.get('prepend_rules'))} prepend rules"
            )
    lines.extend(
        [
            "",
            "详情见 `dist/build-report.json`、`sources/upstreams.lock.json` 和生成物 diff。",
            "",
            "请确认：",
            "- 上游许可证和分类语义仍符合 `sources/ATTRIBUTIONS.md`。",
            "- 关键 patch 没有变成陈旧候选。",
            "- 代表性路由测试和客户端配置检查均通过。",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    print(render(report), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
