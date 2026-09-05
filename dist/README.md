# 生成物说明

本目录由 [`scripts/build.py`](../scripts/build.py) 生成，不是永久手工维护目录。修改规则事实请编辑 `sources/upstreams.json`、`patches/` 或 `overrides/rules.txt`，然后重新构建。

- `quantumult-x/providers/*.list`：Quantumult X 分类级远程入口；每个文件只包含一个 category 和一个许可证范围。请按 `quantumult-x/entry.example.conf` 中的顺序加入 `[filter_remote]`，当前不生成混合许可证的 `aggregate.list`。
- `quantumult-x/entry.example.conf`：分类远程入口示例，保留个人覆盖、广告和服务分类的匹配优先级。
- `mihomo/merge.yaml`：Clash Verge Rev / Mihomo 单一 Merge 入口。
- `mihomo/providers/<category>.yaml`：由 canonical rule model 编译的本地 provider；`merge.yaml` 只引用本仓库这些审核后产物，不直接引用第三方上游。
- `build-report.json`：构建输入、canonical 计数、patch、重复、冲突、不支持规则和客户端输出摘要。

生成物不包含节点、订阅 URL、DNS、TUN、rewrite 或 MitM 配置。第三方规则数据和衍生 provider 受对应上游许可证和 attribution 约束；根目录 MIT License 只覆盖本项目原创代码、架构和文档，不覆盖第三方规则数据。详情见 [`sources/ATTRIBUTIONS.md`](../sources/ATTRIBUTIONS.md)。
