# 网络规则项目

这是一个“上游规则聚合器 + 上游规则修补层 + 规范规则集 + 多客户端编译器”。它使用成熟公开项目维护大规模基础数据，本项目负责聚合、分类、纠错、去重、冲突解决和客户端转换，而不是重新手工维护一套完整规则库。

当前生成 Quantumult X（圈 X）和 Clash Verge Rev / Mihomo 两种产物；小火箭保留为后续适配器，不会把某个客户端的语法当成核心事实模型。

## 架构

```text
多个公开上游
      ↓ FETCH
      ↓ PARSE
      ↓ NORMALIZE
      ↓ MERGE
      ↓ PATCH
      ↓ DEDUP
      ↓ RESOLVE CONFLICT
      ↓ CANONICAL RULE SET
      ↓ VALIDATE
      ├── Quantumult X providers/*.list (category-scoped)
      └── Mihomo providers/*.yaml + merge.yaml
```

核心规则使用稳定的 canonical category ID（例如 `chatgpt`、`claude`、`gemini`、`telegram`、`netflix`、`ads`、`private-tracker`），以及与客户端无关的规则类型：`domain`、`domain-suffix`、`domain-keyword`、`domain-wildcard`、`ip-cidr`、`ip-cidr6`、`user-agent`、`process-name`。生成阶段才把它们转换成 QX 的 `HOST-SUFFIX` 或 Mihomo 的 `DOMAIN-SUFFIX`，并根据 `sources/policies.json` 映射到策略组名称。

主要入口：

- [`sources/upstreams.json`](sources/upstreams.json)：schema v2 上游清单，支持 `category → client → 1..N components`，并明确每个组件是 `canonical-authoritative`、`audit-reference` 还是 `client-only-extra`。
- [`sources/policies.json`](sources/policies.json)：canonical category 到各客户端策略名称的映射，不保存节点或订阅信息。
- [`patches/`](patches/)：上游错误修复、补充、重分类、替换和冲突优先级；patch 有生命周期状态。
- [`overrides/rules.txt`](overrides/rules.txt)：个人规则优先层，与上游修补层分离。
- [`scripts/build.py`](scripts/build.py)：FETCH、PARSE、NORMALIZE、MERGE、PATCH、DEDUP、冲突解决和双客户端生成器。
- [`scripts/validate.py`](scripts/validate.py)：清单、锁定信息、报告、QX、Mihomo 本地 provider 和语义路由验证。
- [`tests/routing-cases.json`](tests/routing-cases.json)：不依赖真实节点的代表性域名路由案例。
- [`dist/build-report.json`](dist/build-report.json)：每次构建的规则数量、重复、冲突、patch 生命周期和客户端产物摘要。

## 用户侧使用方式

内部构建较复杂，但用户侧仍保持简单入口：

- Quantumult X 使用 `dist/quantumult-x/entry.example.conf` 中按 canonical priority 排列的分类远程入口。每个 `providers/*.list` 只包含一个 category 和一个登记来源的许可证范围，避免公开发布时把 GPL-2.0 与 GPL-3.0 规则物理合成到同一个文件。
- Clash Verge Rev / Mihomo 使用一个 Merge 入口：`dist/mihomo/merge.yaml`。

Mihomo 的 `merge.yaml` 只引用本仓库生成的 `dist/mihomo/providers/<category>.yaml`，不再直接引用 BlackMatrix7 或 MetaCubeX 的未经修补文件。节点、代理组、DNS、TUN、rewrite 和 MitM 等非规则配置继续由用户自己的基础配置负责，本项目不会修改它们。

## Global 结论

`global`（国外网站泛分类）在 manifest 中保留为可审查的可选分类，但默认 `enabled: false`。原因是当前基础配置已经负责 LAN、private、China、`GEOIP CN` 和最终 `MATCH/FINAL → 国外网站`；再叠加约 35k 条泛规则会重复消耗资源，并让“取前 10k 条”受上游排序漂移影响。

因此本项目不再使用任意 10,000 条截断作为长期方案。默认只发布广告、PT、ChatGPT、Claude、Gemini、Telegram、YouTube、Netflix、Apple、Google 等明确分类；未知流量由客户端基础配置的 FINAL/MATCH 处理。若未来确认确实需要泛代理名单，应改用更窄的专用源并经过单独审查，而不是重新打开大列表截断。

## 本地开发

项目根目录执行：

```bash
python3 -m pip install -r requirements.txt
python3 scripts/build.py
python3 scripts/validate.py
python3 -m py_compile scripts/*.py
python3 -m unittest discover -s tests -v
```

网络不可用时，可以明确使用已有缓存：

```bash
python3 scripts/build.py --offline
python3 scripts/validate.py
```

正常自动更新不使用陈旧缓存；网络临时故障时才可本地显式传入 `--allow-stale`，并在报告中审查 `stale_cache`。

`.github/workflows/update-rules.yml` 每日 FETCH 上游、构建、验证并创建更新 Pull Request；`.github/workflows/pr-ci.yml` 对每个 Pull Request 只读执行同一套构建、验证、语义测试和生成物一致性检查。PR 会附带 `dist/build-report.json` 的摘要；不会自动合并，必须人工审查上游 diff、冲突、patch 生命周期和许可证。

## 本机快照与安全边界

首次分析使用的圈 X 和 Clash 配置快照位于被 `.gitignore` 排除的 `sources/local/`，仅用于本地参考，可能包含订阅 URL、节点或其他敏感数据。不得把 `sources/local/`、订阅 URL、节点、Token、密码或运行时配置提交到公共仓库。初始快照分析见 [`analysis/initial-analysis.md`](analysis/initial-analysis.md)。

## 许可证

本项目原创脚本、架构和文档代码使用 [MIT License](LICENSE)。`sources/` 中登记和 `dist/` 中转换生成的第三方规则数据，仍受各上游项目的许可证、NOTICE 和 attribution 要求约束；不能因为根目录存在 MIT License 就把全部规则数据解释为 MIT。当前 Quantumult X 公开产物采用分类级文件，不提供混合许可证的 `aggregate.list`。具体来源见 [`sources/ATTRIBUTIONS.md`](sources/ATTRIBUTIONS.md) 和 [`dist/README.md`](dist/README.md)。
