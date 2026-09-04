# 上游来源与许可证

本项目的 `dist/` 生成物会使用下列公开规则源。项目只登记来源、格式和策略映射，不把本机节点订阅、Token、密码或运行时配置纳入公共仓库。

| 生成物中的分类 | 上游项目 | 上游路径 | 许可证 | 处理方式 |
| --- | --- | --- | --- | --- |
| PT / PrivateTracker | [blackmatrix7/ios_rule_script](https://github.com/blackmatrix7/ios_rule_script) | `rule/QuantumultX/PrivateTracker/PrivateTracker.list`、`rule/Clash/PrivateTracker/PrivateTracker.yaml` | GPL-2.0 | 保留为专门的 PT 源，并在通用广告/地区源之前命中 |
| Netflix | [blackmatrix7/ios_rule_script](https://github.com/blackmatrix7/ios_rule_script) | `rule/QuantumultX/Netflix/Netflix.list`、`rule/Clash/Netflix/Netflix.yaml` | GPL-2.0 | 使用客户端原生格式补足 Netflix 专用分类，目标映射到现有 Netflix/流媒体策略 |
| 广告 | [MetaCubeX/meta-rules-dat](https://github.com/MetaCubeX/meta-rules-dat) | `geo/geosite/category-ads-all.{yaml,mrs}` | GPL-3.0 | 通过 Mihomo MRS provider 或转换为 QX 域名规则 |
| ChatGPT、Telegram、YouTube、Apple、Google | [MetaCubeX/meta-rules-dat](https://github.com/MetaCubeX/meta-rules-dat) | `geo/geosite/<category>.{yaml,mrs}` | GPL-3.0 | 以一个分类一个 provider 的方式接入，避免把同类大列表重复叠加 |
| Claude | [blackmatrix7/ios_rule_script](https://github.com/blackmatrix7/ios_rule_script) | `rule/QuantumultX/Claude/Claude.list`、`rule/Clash/Claude/Claude.yaml` | GPL-2.0 | 与 OpenAI/ChatGPT 分开维护，映射到本机 AI 策略组 |
| Gemini | [blackmatrix7/ios_rule_script](https://github.com/blackmatrix7/ios_rule_script) | `rule/QuantumultX/Gemini/Gemini.list`、`rule/Clash/Gemini/Gemini.yaml` | GPL-2.0 | 与 ChatGPT、Claude 分开维护，映射到本机 Gemini 策略组 |
| 国外网站 | [blackmatrix7/ios_rule_script](https://github.com/blackmatrix7/ios_rule_script) | `rule/QuantumultX/Global/Global.list`、`rule/Clash/Global/Global.yaml` | GPL-2.0 | 作为最后的泛分类，仅接收前面专用规则未覆盖的条目，映射到本机国外网站策略 |

blackmatrix7 的 PT 规则 README 还列出了 ACL4SSR PrivateTracker 与 trackerslist 等数据来源；本项目不再把这些已被上游收录的列表重复接入。该项目的 `rule/` 是按客户端和分类拆分的目录，不能把目录本身当作单一规则文件；当前按白名单接入 PT、ChatGPT、Claude、Gemini、Netflix 和国外网站，国外网站泛分类放在所有专用分类之后，后续分类仍需逐项评估。`ACL4SSR/ACL4SSR` 和 `loyalsoldier/v2ray-rules-dat` 暂作为参考源，不进入默认生成链，以免许可证和分类重复增加维护成本。

`GEOIP`、`GEOIP,CN`、`GEOSITE,cn`、局域网/私有地址、中国大陆兜底和 `MATCH` 等基础能力由各客户端自己的配置承担，因此不作为本项目的上游生成物。

公开发布本仓库或生成物前，请按各上游仓库当前的 LICENSE、NOTICE 和来源说明复核再分发要求；本文件不是法律意见。
