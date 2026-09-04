# 单入口接入方式

本项目的“单入口”是每个客户端各自一个入口，不是把圈 X、Clash 和小火箭强行使用同一种语法：

- Clash Verge / Mihomo：使用 `dist/mihomo/merge.yaml` 作为一个 Merge 配置片段。
- Quantumult X：使用 `dist/quantumult-x/aggregate.list` 作为一个远程分流列表。
- Shadowrocket：暂不自动生成，等确认小火箭现有策略组名称后再接入，避免把 `proxy` 误映射成错误的策略。

## Clash Verge / Mihomo

`dist/mihomo/merge.yaml` 不是独立订阅，也不包含节点。它只声明公开 `rule-providers`，并通过 `prepend-rules` 把本地覆盖和这些规则集放到当前订阅规则链的前面；节点、策略组、DNS、TUN、重写和 MitM 继续由现有配置负责。

发布仓库后，在 Clash Verge Rev 中添加一个远程 Merge 配置，填入：

```text
https://raw.githubusercontent.com/OWNER/REPOSITORY/main/dist/mihomo/merge.yaml
```

本项目当前的 GitHub 仓库是 `zyk1172/network-rules`，推送分支是 `codex/bootstrap-network-rules`；在该分支审查完成前，临时地址为：

```text
https://raw.githubusercontent.com/zyk1172/network-rules/codex/bootstrap-network-rules/dist/mihomo/merge.yaml
```

仓库现为公开 MIT 项目，圈 X、Clash Verge 等客户端可以直接匿名读取这些 raw 地址。

如果你的订阅策略组名称不是当前本机配置里的 `ChatGPT`、`AI`、`Gemini`、`Telegram`、`流媒体`、`Apple`、`Google`、`国外网站`、`国内直连`，先编辑 `sources/policies.json` 后再构建。规则分类只保留 `ChatGPT`、`Claude`、`Gemini` 三个 AI 服务；其中 `AI` 是当前基础配置中的策略组目标，不是生成物分类。这个映射只影响规则的目标策略，不会修改节点订阅。

## Quantumult X

把 `dist/quantumult-x/entry.example.conf` 中的示例行加入 `[filter_remote]`，并将其中的仓库占位符换成你的 GitHub 路径。它最终只需要一个远程列表入口：

```text
https://raw.githubusercontent.com/OWNER/REPOSITORY/main/dist/quantumult-x/aggregate.list, tag=网络规则聚合, update-interval=86400, opt-parser=false, enabled=true
```

当前分支的临时入口为：

```text
https://raw.githubusercontent.com/zyk1172/network-rules/codex/bootstrap-network-rules/dist/quantumult-x/aggregate.list, tag=网络规则聚合, update-interval=86400, opt-parser=false, enabled=true
```

列表已经把公开分类转换为圈 X 语法，并按本机策略名称映射到 `Gpt`、`💻 Ai`、`Gemini`、`✉️ Telegram`、`📺 Netflix`、`🎬 YouTube`、`🍎 苹果服务`、`🌏 国外网站` 等策略。现有 `[rewrite_local]`、`[rewrite_remote]` 和 `[mitm]` 不放入这个入口。

聚合列表不是无分类的连续规则：文件中以 `CATEGORY` 注释段区分“本地覆盖、PT / PrivateTracker、广告、ChatGPT、Claude、Gemini、Telegram、YouTube、Netflix、Apple、Google、国外网站”。国外网站是泛分类，放在专用服务分类之后，只承接前面没有匹配到的条目。这些注释不会改变圈 X 的规则匹配顺序，但方便审查和定位某一类规则。Mihomo 文件中的 provider 和 `prepend-rules` 也使用同样的分类名称。

## 如何保留个人修改

只改这两个地方：

1. 在 `overrides/rules.txt` 增加或删除本地优先规则，格式为 `TYPE,condition,policy-key`。
2. 在 `sources/policies.json` 调整每个客户端的策略名称。

构建器不会写回这两个文件。生成顺序是“本地覆盖 → PT → 广告 → 专用服务分类 → 国外网站泛分类”；同一条件重复出现时保留先出现的规则，并在 `dist/build-report.json` 中记录冲突数量。

`GEOIP`、`GEOIP,CN`、`GEOSITE,cn`、局域网/私有地址、中国大陆兜底、`MATCH` 和固定端口等基础规则，不放入这个公共聚合入口。它们继续留在各客户端自己的基础配置中（按客户端使用各自语法）；本项目只维护需要外部更新或需要跨客户端转换的分类。

PT 规则只维护域名和关键词，不固定 qBittorrent 的监听端口。qB 变更端口是正常行为，不应因为端口变化去改公共规则源。

## 本地构建和自动更新

在项目根目录执行：

```bash
python3 scripts/build.py
python3 scripts/validate.py
```

网络不可用但之前已有缓存时，可以显式使用：

```bash
python3 scripts/build.py --offline
python3 scripts/validate.py
```

`.github/workflows/update-rules.yml` 每天拉取上游并重建生成物；有变化时创建更新分支和 Pull Request。工作流不会直接覆盖 `main`，也不会修改 `sources/local/`。
