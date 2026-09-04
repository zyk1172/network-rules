# 客户端接入与维护

本项目对外提供每个客户端一个入口，对内通过 canonical rule model 统一规则意图。入口只包含规则和策略映射，不包含节点、订阅、DNS、TUN、rewrite 或 MitM 配置。

## Clash Verge Rev / Mihomo

使用 `dist/mihomo/merge.yaml` 作为一个远程 Merge 配置片段：

```text
https://raw.githubusercontent.com/zyk1172/network-rules/main/dist/mihomo/merge.yaml
```

它不是独立订阅，不含节点。Merge 文件中的 `rule-providers` URL 全部指向本仓库自己生成并审核后的：

```text
dist/mihomo/providers/<category>.yaml
```

因此 Mihomo 不会绕过本项目直接拉取 BlackMatrix7 或 MetaCubeX 的原始 provider。每个 provider 都由 canonical 规则生成，采用 Mihomo `classical` YAML 格式；策略名称只出现在 `merge.yaml` 的 `RULE-SET` 中，规则数据本身不绑定 Mihomo 策略。

节点、proxy-groups、DNS、TUN、rewrite 和 MitM 继续使用现有基础配置。合并顺序由 `prepend-rules` 控制：个人覆盖在前，然后按 category priority 引用本项目 providers。qBittorrent 改监听端口不需要改这套公共域名/IP 规则。

当前默认分类顺序为：

```text
personal override → private-tracker → ads → chatgpt → claude → gemini
→ telegram → youtube → netflix → apple → google → FINAL/MATCH
```

其中 `FINAL/MATCH` 仍由用户基础配置决定；本项目默认关闭 `global` 泛分类。

如果本机策略组名称不同，只修改 [`sources/policies.json`](../sources/policies.json) 后重新构建。例如：

```json
{
  "mihomo": {
    "chatgpt": "ChatGPT",
    "claude": "AI",
    "gemini": "Gemini"
  }
}
```

当前 AI 规则分类只保留 `chatgpt`、`claude`、`gemini` 三个服务；`AI` 若存在，只是基础配置中的策略组名，不是 canonical category。

## Quantumult X

把 `dist/quantumult-x/entry.example.conf` 中的行加入 Quantumult X 的 `[filter_remote]`，正式发布地址为：

```text
https://raw.githubusercontent.com/zyk1172/network-rules/main/dist/quantumult-x/aggregate.list, tag=网络规则聚合, update-interval=86400, opt-parser=false, enabled=true
```

列表由同一份 canonical rule set 生成，再把稳定 category ID 转换为 QX `HOST`、`HOST-SUFFIX`、`IP-CIDR` 等语法，并映射到 QX 策略名称。现有 `[rewrite_local]`、`[rewrite_remote]` 和 `[mitm]` 不放入这个远程列表。

canonical vocabulary 可以比单个客户端更宽。比如当前 Mihomo core 没有 `USER-AGENT` 规则适配器，因此 Netflix 的 `Argo*` User-Agent 规则会保留在 QX 产物，并在 Mihomo 的 `unsupported_rules` 报告中明确记录，不会伪装成可用的 Mihomo 规则；Mihomo 支持的 `DOMAIN-WILDCARD`、`PROCESS-NAME` 等类型仍会生成。

## 分类、策略与个人规则

`sources/upstreams.json` 中的 `id` 是稳定 canonical category，例如 `netflix`，不是客户端显示名。`sources/policies.json` 才负责将其映射为 QX 的 `📺 Netflix` 或 Mihomo 的 `流媒体`。这样同一规则事实不会因为客户端策略组名称不同而被复制成两套来源。

个人规则和上游修补分开：

- [`overrides/rules.txt`](../overrides/rules.txt)：个人优先规则，保留本地习惯；不随上游更新覆盖。
- [`patches/`](../patches/)：上游缺失、错误分类、错误类型和跨分类优先级修复；每条 patch 需要 reason，并在报告中追踪是否仍然匹配。

不要直接编辑 `dist/`。如果上游已经自行修复，构建器会将 patch 标记为 `obsolete_candidate`；关键 patch 的失效会让验证失败，人工确认后再删除或更新 patch。

## Global 与规则规模

默认不发布约 35k 条 `global` 泛规则，也不再按上游顺序任意截断到 10,000 条。当前基础配置已经负责中国大陆、局域网、private、`GEOIP CN` 和最终国外网站策略，未知流量由 `FINAL/MATCH` 处理。

这不是遗漏，而是明确的架构取舍：专用分类负责可解释的路由，基础配置负责兜底。若以后确实需要“国外网站名单”，应选择更窄的来源，设计稳定的过滤/分类标准并单独评估性能，不能把列表前 N 条当作长期重要度排序。

## 上游组件选择

一个 category/client 可以声明多个组件。BlackMatrix7 的组件不能只看同名 `.yaml`：

- Global 使用上游 README 建议可单独使用的 `Global_Classical.yaml`（但默认禁用）。
- Netflix 使用可单独使用的 `Netflix_Classical.yaml`。
- Claude、Gemini、PrivateTracker 使用各自的完整 classical YAML。
- MetaCubeX 的域名 YAML 作为 canonical 域名输入；其 MRS 组件会锁定并审计，但二进制 MRS 不直接作为本项目 canonical parser 的事实来源，生成的 Mihomo provider 仍来自已解析的 canonical model。

具体 URL、格式、`behavior`、完整性标记和许可证登记在 [`sources/upstreams.json`](../sources/upstreams.json)；组件 hash 在 [`sources/upstreams.lock.json`](../sources/upstreams.lock.json)。

## 构建、验证和语义测试

```bash
python3 -m pip install -r requirements.txt
python3 scripts/build.py
python3 scripts/validate.py
python3 -m py_compile scripts/*.py
python3 -m unittest discover -s tests -v
```

离线只应在已有缓存时显式使用：

```bash
python3 scripts/build.py --offline
python3 scripts/validate.py
```

`tests/routing-cases.json` 会验证 ChatGPT、Claude、Gemini、YouTube、Netflix、PT、广告以及 Gemini/Google、YouTube/Google 冲突。测试只评估规则匹配，不测试真实节点可用性；真实客户端加载和运行时效果仍需在 Clash Verge / Quantumult X 中单独验收。

## 自动更新

GitHub Actions 每日执行：

```text
FETCH → build → validate → semantic tests → create/update PR
```

更新 PR 会附带 `scripts/update_summary.py` 根据 `dist/build-report.json` 生成的摘要，显示上游组件、canonical 计数、patch 状态、冲突和两端产物数量。工作流不会自动合并；人工审查后才能合并。
