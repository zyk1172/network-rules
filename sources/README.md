# 来源清单与锁定信息

## 本机原始快照

`sources/local/` 保存本次从本机应用或用户指定导出复制的原始文件，默认不进入 Git：

- `quantumult-x/quantumult_20260905020418.conf`：用户指定的圈 X 导出。
- `quantumult-x/default.conf`：从圈 X App Group 复制的快照。
- `clash-verge/master.yaml`：用户指定的桌面 `clash-master-config/master.yaml`，README 标注为脱敏导出。

这些文件只用于本地分析，可能包含订阅 URL、节点信息或其他认证数据。不得把它们或从中提取出的敏感字段提交到公共仓库。

## `upstreams.json` schema v2

清单把“规则事实来源”和“客户端输入组件”分开描述。每个稳定 category 使用 canonical ID，并支持：

```text
category → client → 1..N upstream components
```

组件最少包含：

```json
{
  "id": "blackmatrix-netflix-classical",
  "url": "https://raw.githubusercontent.com/...",
  "format": "mihomo-yaml",
  "behavior": "classical",
  "canonical": true,
  "complete": true
}
```

`canonical: true` 表示该组件会被解析为内部统一规则模型；`canonical: false` 表示它仍会被下载、锁定和报告，但不直接绕过 parser 成为事实来源。这样可以同时记录客户端最佳上游格式，并防止 Mihomo 直接从第三方 URL 读取未经 patch 的规则。

允许的输入格式：

- `qx-list`：Quantumult X typed list，策略字段在 canonical 化时丢弃。
- `meta-domain-yaml`：MetaCubeX `payload` 域名列表，转换 `+.example.com`、`full:`、`keyword:` 等表达式。
- `mihomo-yaml` / `yaml`：含 `payload` 的 Mihomo classical、domain 或 ipcidr 规则。
- `mrs`：二进制 provider，仅锁定和审计，不作为当前 canonical parser 输入。

规则类型在 `scripts/rule_model.py` 中统一为 `domain`、`domain-suffix`、`domain-keyword`、`domain-wildcard`、`ip-cidr`、`ip-cidr6`、`user-agent`、`process-name`，客户端策略名称只在生成阶段使用 `policies.json` 映射。

## 锁定信息与缓存

`upstreams.lock.json` 是构建产生的公开上游输入锁定信息，记录 category/client/component、URL、字节数、SHA-256、上游更新时间和是否使用陈旧缓存。它不记录节点订阅或本地运行配置。

`cache/` 是构建时的本地缓存，已加入 Git 忽略；它不是发布内容。自动更新工作流正常访问网络，不使用陈旧缓存。`--offline` 适用于已有完整缓存的本地重复构建，`--allow-stale` 只适用于临时排障，必须审查报告中的 `stale_cache`。

## 个人覆盖与上游修补

- [`../overrides/rules.txt`](../overrides/rules.txt)：个人规则优先层，例如 PT 域名和关键词；不绑定 qBittorrent 固定监听端口。
- [`../patches/`](../patches/)：上游补丁层，支持 add/remove/reclassify/replace/priority，必须填写 reason。

二者都在生成 `dist/` 之前应用。patch 如果不再匹配会写入 `dist/build-report.json`，不会自动无声删除；关键 patch 失效时验证失败，等待人工审查。

## 当前默认来源

默认生成链包含 PT、广告、ChatGPT、Claude、Gemini、Telegram、YouTube、Netflix、Apple 和 Google。`global`（国外网站泛分类）保留在清单中但默认关闭，因为基础配置已经使用 FINAL/MATCH 处理未知流量；不再用 10,000 条任意截断解决 35k 级泛列表的性能问题。

上游组件组合及 BlackMatrix7 的 Global、Netflix、Claude、Gemini、PrivateTracker 结构审查记录见 [`component-audit.md`](component-audit.md)。许可证和 attribution 边界见 [`ATTRIBUTIONS.md`](ATTRIBUTIONS.md)。
