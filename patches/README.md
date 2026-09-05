# Patch 层

`patches/` 只处理公开上游数据的纠错和生命周期，不用于保存个人规则。个人规则继续放在 [`overrides/rules.txt`](../overrides/rules.txt)。生成物 `dist/` 永远不是永久修复入口。

每个 YAML 文件顶层使用 `patches` 列表。每条 patch 必须有稳定的 `id`、动作和 `reason`，建议同时填写 `added`、`auto_drop_when_fixed` 与 `required`。构建器会把每条 patch 的匹配数、影响数和状态写入 [`dist/build-report.json`](../dist/build-report.json)。`obsolete_candidate` 只代表上游可能已经自行修复；不会被自动删除，关键 patch 的失效会使验证失败，等待人工审查后再删除或调整。

## 支持的动作

```yaml
patches:
  - id: add-example
    action: add
    rule:
      type: domain-suffix
      value: example.com
      category: gemini
    reason: 上游遗漏了 Gemini 依赖域名。

  - id: remove-example
    action: remove
    match:
      type: domain-suffix
      value: example.cn
      category: google
    reason: 上游错误地把该域名归入 Google。

  - id: move-ai-google-dev
    action: reclassify
    match:
      type: domain
      value: ai.google.dev
      category: google
    from: google
    to: gemini
    reason: 这是 Gemini 专用服务端点。

  - id: replace-example
    action: replace
    match:
      type: domain
      value: example.com
      category: google
    with:
      type: domain-suffix
      value: example.com
      category: google
    reason: 将精确规则修正为域名后缀规则。

  - id: youtube-over-google
    action: priority
    match:
      type: domain-suffix
      value: youtube.com
    prefer: youtube
    over:
      - google
      - global
    reason: YouTube 专用分类优先于通用分类。
    added: 2026-09-05
    auto_drop_when_fixed: true
    required: true
```

`priority` 不直接改写规则，而是在同一 canonical 规则同时出现在多个分类时选择优先分类。没有匹配到目标的 `remove`、`reclassify`、`replace` 或 `priority` 会被报告为陈旧候选；`required: true` 的失败或失效 patch 不得静默通过验证。
