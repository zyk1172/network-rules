# Quantumult X 生成物

请使用 `entry.example.conf` 中的多条 `[filter_remote]` 入口，并保持文件顺序不变。`providers/*.list` 是分类级文件：每个文件只包含一个 canonical category、一个登记上游和一个许可证范围。

本目录不再提供把 GPL-2.0 与 GPL-3.0 上游规则物理合成的 `aggregate.list`。这样做是公开分发边界，而不是规则遗漏；分类文件由 Quantumult X 主配置按优先级组合。

这些文件由 `scripts/build.py` 生成。请修改 `sources/upstreams.json`、`patches/` 或 `overrides/rules.txt` 后重新构建，不要直接编辑生成物。第三方规则数据遵循 [`sources/ATTRIBUTIONS.md`](../../sources/ATTRIBUTIONS.md) 中登记的许可证和 attribution 要求。
