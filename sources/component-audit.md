# 上游组件审查记录

本记录用于说明为什么 manifest 没有把同名文件简单当作完整规则，也用于后续上游更新时复核组件选择。它不是第三方许可证的替代品；发布前仍需按上游仓库当前 LICENSE、README 和 NOTICE 复核。

## BlackMatrix7 `Clash` 目录

已检查以下分类的上游 README 和文件列表：

| 分类 | 上游可见组件 | 本项目选择 | 结论 |
| --- | --- | --- | --- |
| Global | `Global.yaml`、`Global_Domain.yaml`、`Global_Classical.yaml` | `Global_Classical.yaml`（authoritative，但 category 默认 disabled） | `Global_Classical.yaml` 是可单独使用的完整 classical 方案；不再使用混合文件后任意截断 |
| Netflix | `Netflix.yaml`、`Netflix_IP.yaml`、`Netflix_Classical.yaml` | QX `Netflix.list` authoritative；`Netflix_Classical.yaml` 为 Mihomo `client-only-extra` | 上游 README 建议单独使用 Classical 文件；避免只取小型域名部分，同时把 Mihomo 特有规则限制在 Mihomo 输出 |
| Claude | `Claude.yaml` | `Claude.yaml` | 单文件完整 classical 方案 |
| Gemini | `Gemini.yaml` | `Gemini.yaml` | 单文件完整 classical 方案 |
| PrivateTracker | `PrivateTracker.yaml` | `PrivateTracker.yaml` | 单文件完整 classical 方案，另保留 QX list 做跨客户端 canonical 对照 |

每个 category 现在只允许一个 `canonical-authoritative` 组件。BlackMatrix7 的另一种客户端格式通常标记为 `audit-reference`；Netflix 的 Mihomo Classical 文件特意标记为 `client-only-extra`，因此其中的 `PROCESS-NAME,com.netflix.mediaclient` 只进入 Mihomo，不会自动传播到 QX。所有非 authoritative 组件仍会在 component report 中与 authoritative source 做覆盖对照。

当前 Netflix 的跨客户端差异会显式记录：QX list 有一个 `USER-AGENT,Argo*`，Mihomo core 的 parser 没有对应的 User-Agent 规则类型，所以 Mihomo adapter 会丢弃这一条并写入 `unsupported_rules`；这比生成一个 Mihomo 无法消费的伪规则更安全。`DOMAIN-WILDCARD` 和 `PROCESS-NAME` 则由当前 Mihomo 版本支持并继续生成。

## MetaCubeX `meta-rules-dat`

MetaCubeX 的 `geo/geosite/<category>.yaml` 是可解析的域名 payload，配套 `<category>.mrs` 是 Mihomo 的二进制规则 provider。当前项目：

1. 将唯一 authoritative 组件统一转换到内部 rule model。
2. 下载并锁定 audit reference / client-only extra，记录其相对 authoritative source 的差异。
3. 生成 Mihomo 时使用本项目从 canonical model 加显式 Mihomo client-only extra 编译出的本地 classical YAML，而不是让 `merge.yaml` 直接引用第三方 MRS URL。

这保证 patch、去重和冲突选择对两个客户端都生效。MRS 当前不会被本地 parser 反序列化；如果未来需要以 MRS 作为事实来源，应先增加明确的 MRS 解码器和等价性测试，而不能悄悄把它当作已解析规则。

## Global 的架构结论

Global 的完整 Classical 组件已经登记并验证 URL 结构，但默认关闭。当前基础配置已有 LAN/private/China/GEOIP CN 和 FINAL/MATCH；泛 Global 列表与这些兜底职责重叠。项目不采用“上游 35k → 按顺序保留 10k”的长期策略，因为上游排序变化会导致代理覆盖不稳定。若未来打开，必须完整输出并重新评估客户端性能；更优先的方向是寻找更窄的专用 proxy 类来源。
