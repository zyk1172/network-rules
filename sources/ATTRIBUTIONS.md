# 上游来源与许可证

本项目的 `dist/` 生成物会使用下列公开规则源。项目只登记来源、格式和策略映射，不把本机节点订阅、Token、密码或运行时配置纳入公共仓库。

| 生成物中的分类 | 上游项目 | 上游路径 | 许可证 | 处理方式 |
| --- | --- | --- | --- | --- |
| PT / PrivateTracker | [blackmatrix7/ios_rule_script](https://github.com/blackmatrix7/ios_rule_script) | `rule/QuantumultX/PrivateTracker/PrivateTracker.list`、`rule/Clash/PrivateTracker/PrivateTracker.yaml` | GPL-2.0 | 保留为专门的 PT 源，并在通用广告/地区源之前命中 |
| 广告 | [MetaCubeX/meta-rules-dat](https://github.com/MetaCubeX/meta-rules-dat) | `geo/geosite/category-ads-all.{yaml,mrs}` | GPL-3.0 | 通过 Mihomo MRS provider 或转换为 QX 域名规则 |
| OpenAI、Telegram、YouTube、Apple、Google、private、cn | [MetaCubeX/meta-rules-dat](https://github.com/MetaCubeX/meta-rules-dat) | `geo/geosite/<category>.{yaml,mrs}` | GPL-3.0 | 以一个分类一个 provider 的方式接入，避免把同类大列表重复叠加 |

blackmatrix7 的 PT 规则 README 还列出了 ACL4SSR PrivateTracker 与 trackerslist 等数据来源；本项目不再把这些已被上游收录的列表重复接入。`ACL4SSR/ACL4SSR` 和 `loyalsoldier/v2ray-rules-dat` 暂作为参考源，不进入默认生成链，以免许可证和分类重复增加维护成本。

公开发布本仓库或生成物前，请按各上游仓库当前的 LICENSE、NOTICE 和来源说明复核再分发要求；本文件不是法律意见。
