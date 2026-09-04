# 网络规则项目

这个项目用于维护同一套网络分流意图，并为不同客户端生成各自的配置：

- Quantumult X（圈X）
- Clash Verge / Mihomo
- Shadowrocket（小火箭，后续接入）

## 当前基线

本次只完成了本机配置快照和初步分析，没有修改任何规则、重写或 MitM 设置。

- 原始本机快照位于 `sources/local/`，该目录已加入 `.gitignore`。其中可能含有订阅 URL、节点信息或其他认证数据，只用于本地分析。
- 脱敏后的 Clash 主配置来自桌面导出目录，作为规则结构参考；它不是可直接恢复订阅凭据的运行配置。
- 初步分析见 `analysis/initial-analysis.md`。

## 预期结构

后续按“规范规则目录 → 客户端适配器 → 配置生成物”的方向整理：

1. 规范规则目录保存域名/IP/关键词、意图分类、优先级和来源。
2. Quantumult X、Clash/Mihomo、Shadowrocket 分别负责语法和策略组映射。
3. 生成前执行跨客户端冲突检测、重复检测和代表性域名命中测试。
4. 运行中的 Clash `clash-verge.yaml` 只作为生成结果和验证对象，不直接手工改写。

语法检查只能证明文件可加载，不能证明规则顺序、策略组存在性或运行中的核心已经采用了新配置；这些需要单独验证。

## GitHub 上游聚合

已加入第一版“公开上游 + 本地覆盖”流水线：

- `sources/upstreams.json`：登记 MetaCubeX/meta-rules-dat 和 blackmatrix7/ios_rule_script 的公开源、格式、许可证和适配路径。
- `sources/policies.json`：把同一分类映射到 Mihomo 和 Quantumult X 各自的策略名称。
- `overrides/rules.txt`：个人规则优先层，当前先收录 PT 域名/关键词；它不会被上游更新覆盖。
- `dist/mihomo/merge.yaml`：Clash Verge Rev / Mihomo 的单个 Merge 入口。
- `dist/quantumult-x/aggregate.list`：圈 X 的单个远程分流列表入口，内部按 PT、广告、Telegram、OpenAI、YouTube、Apple、Google 等分类分段。
- `.github/workflows/update-rules.yml`：每天拉取上游、重建生成物并创建 Pull Request，等待审查后再合并。

具体接入和本地构建命令见 [`docs/integration.md`](docs/integration.md)，来源和许可证见 [`sources/ATTRIBUTIONS.md`](sources/ATTRIBUTIONS.md)。项目已创建并推送到 [zyk1172/network-rules](https://github.com/zyk1172/network-rules)，当前推送分支为 `codex/bootstrap-network-rules`。仓库现为公开项目，采用 [MIT License](LICENSE)；`sources/local/`、`sources/cache/` 等本地快照未纳入版本库。
