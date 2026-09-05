# 上游来源与许可证

本项目的原创构建器、canonical model、patch engine、验证器、测试和文档代码使用根目录的 [MIT License](../LICENSE)。这不改变第三方规则数据的权利和义务：`sources/cache/` 中的上游输入，以及从这些输入转换生成的 `dist/` 规则数据，遵循对应上游的许可证、NOTICE 和 attribution 要求。

## 当前登记来源

| canonical category | 上游项目与链接 | 使用的组件 | 许可证 | 说明 |
| --- | --- | --- | --- | --- |
| `private-tracker` | [blackmatrix7/ios_rule_script](https://github.com/blackmatrix7/ios_rule_script) | `rule/QuantumultX/PrivateTracker/PrivateTracker.list`；`rule/Clash/PrivateTracker/PrivateTracker.yaml` | GPL-2.0 | PT 专用分类；个人 PT 规则在其前面；不绑定 qBittorrent 固定端口 |
| `ads` | [MetaCubeX/meta-rules-dat](https://github.com/MetaCubeX/meta-rules-dat) | `geo/geosite/category-ads-all.yaml`；对应 `category-ads-all.mrs` 作为锁定审计组件 | GPL-3.0 | 广告优先于服务分类；Mihomo 使用本项目生成 provider |
| `chatgpt` | [MetaCubeX/meta-rules-dat](https://github.com/MetaCubeX/meta-rules-dat) | `geo/geosite/openai.yaml`；对应 `openai.mrs` 作为锁定审计组件 | GPL-3.0 | canonical ID 使用 `chatgpt`，不再使用 `openai` 作为内部分类 |
| `claude` | [blackmatrix7/ios_rule_script](https://github.com/blackmatrix7/ios_rule_script) | `rule/QuantumultX/Claude/Claude.list`；`rule/Clash/Claude/Claude.yaml` | GPL-2.0 | Claude/Anthropic 专用分类 |
| `gemini` | [blackmatrix7/ios_rule_script](https://github.com/blackmatrix7/ios_rule_script) | `rule/QuantumultX/Gemini/Gemini.list`；`rule/Clash/Gemini/Gemini.yaml` | GPL-2.0 | Gemini 专用分类；通过 patch 优先于 Google 通用分类 |
| `telegram` | [MetaCubeX/meta-rules-dat](https://github.com/MetaCubeX/meta-rules-dat) | `geo/geosite/telegram.yaml`；对应 `telegram.mrs` 作为锁定审计组件 | GPL-3.0 | Telegram 分类 |
| `youtube` | [MetaCubeX/meta-rules-dat](https://github.com/MetaCubeX/meta-rules-dat) | `geo/geosite/youtube.yaml`；对应 `youtube.mrs` 作为锁定审计组件 | GPL-3.0 | YouTube 优先于 Google 通用分类 |
| `netflix` | [blackmatrix7/ios_rule_script](https://github.com/blackmatrix7/ios_rule_script) | `rule/QuantumultX/Netflix/Netflix.list`；`rule/Clash/Netflix/Netflix_Classical.yaml` | GPL-2.0 | 使用上游 README 建议可单独使用的 Classical 组件 |
| `apple` | [MetaCubeX/meta-rules-dat](https://github.com/MetaCubeX/meta-rules-dat) | `geo/geosite/apple.yaml`；对应 `apple.mrs` 作为锁定审计组件 | GPL-3.0 | Apple 专用分类 |
| `google` | [MetaCubeX/meta-rules-dat](https://github.com/MetaCubeX/meta-rules-dat) | `geo/geosite/google.yaml`；对应 `google.mrs` 作为锁定审计组件 | GPL-3.0 | Google 通用分类，放在专用服务之后 |
| `global`（默认 disabled） | [blackmatrix7/ios_rule_script](https://github.com/blackmatrix7/ios_rule_script) | `rule/QuantumultX/Global/Global.list`；`rule/Clash/Global/Global_Classical.yaml` | GPL-2.0 | 已审计但默认不生成；避免 35k 泛规则与基础 FINAL/MATCH 重复，不做 10k 任意截断 |

上游文件和最终构建时使用的 SHA-256 见 [`upstreams.lock.json`](upstreams.lock.json)。组件结构和 BlackMatrix7 README 配置建议的审查结论见 [`component-audit.md`](component-audit.md)。

每个分类的 authoritative、audit-reference 和 client-only-extra 角色以 [`upstreams.json`](upstreams.json) 为准；角色只决定构建参与方式，不改变上游许可证。当前 Netflix 的 Mihomo Classical 是显式 client-only-extra，其他客户端组件差异只进入审计报告。

## 衍生生成物边界

`dist/quantumult-x/providers/*.list` 和 `dist/mihomo/providers/*.yaml` 是从上述第三方规则输入经过规范化、去重、patch 和客户端语法转换得到的衍生数据，不应被根目录 MIT License 单独解释为 MIT。Quantumult X 产物按 category 文件拆分，每个文件只包含一个登记来源和一个许可证范围；`dist/quantumult-x/entry.example.conf` 会按优先级列出多个远程分类文件。`dist/mihomo/merge.yaml` 主要是本项目的配置编译代码生成的入口片段，但其中的规则 provider 指向仍承载上游数据许可义务。

本项目不在公开生成链中提供把 GPL-2.0 与 GPL-3.0 规则数据物理合成的 Quantumult X `aggregate.list`。如果未来确认混合再分发具有明确的上游授权和法律依据，必须单独审查后才能重新引入聚合文件；当前默认发布策略是分类级文件，由用户的 QX 主配置按优先级组合。

不要擅自修改或替换第三方许可证文本。公开分发、重新打包或新增上游时，请重新检查上游仓库当前的 LICENSE、README、NOTICE 和 attribution 要求；本文件不是法律意见。

## 未纳入默认链的来源

BlackMatrix7 的 README 可能进一步引用 ACL4SSR、trackerslist 等数据源；本项目不重复接入已经被当前上游收录的列表。`ACL4SSR/ACL4SSR`、`loyalsoldier/v2ray-rules-dat` 等仅作为候选参考，不进入默认生成链，以免在未完成许可证和分类重叠审查前扩大衍生数据范围。

`GEOIP`、`GEOIP,CN`、`GEOSITE,cn`、LAN/private、中国大陆兜底以及 `MATCH/FINAL` 属于客户端基础配置能力，不是本项目登记的第三方规则生成物。
