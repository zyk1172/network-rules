# 初步分析：圈X与 Clash Verge 配置基线

日期：2026-09-05
范围：只读盘点、快照复制、结构解析和跨客户端规则比较。
本次没有修改任何应用配置，也没有主动抓取或更新远程规则。

## 1. 起点文件与来源

| 客户端 | 项目内快照 | 来源 | 大小 | SHA-256 |
| --- | --- | --- | ---: | --- |
| Quantumult X | `sources/local/quantumult-x/quantumult_20260905020418.conf` | `/Users/zhengyunkai/Downloads/quantumult_20260905020418.conf` | 35,709 bytes | `5a0db547972db965232d48484d61916e5a56351b443ebb22fa11b94c485a000d` |
| Quantumult X | `sources/local/quantumult-x/default.conf` | App Group 的 `configuration/default.conf` | 35,709 bytes | 与上面相同 |
| Clash Verge / Mihomo | `sources/local/clash-verge/master.yaml` | `/Users/zhengyunkai/Desktop/clash-master-config/master.yaml` | 15,191 bytes | `bf0fd1a4a71eb7b799701f94f58a92c8c72c5fb65fe8d3b8f2518be8cc69be7c` |

圈X的两个快照内容完全一致，因此指定导出可以作为当前基线。桌面目录中的 `README-export.md` 将 `master.yaml` 标为“脱敏版”；目录实际清单中没有它声称的 `local_rules/` 子目录，这一点后续需要确认。

原始快照已放在 Git 忽略的 `sources/local/` 下。圈X文件的启发式扫描发现 1 行带有 URL 查询参数、35 行包含凭据相关字段名；这不是逐项泄漏判定，但足以说明原始文件不应提交。Clash 桌面导出未发现这类字段，且两个 HTTP provider 的 URL 值是脱敏占位形式，不能当作可直接运行的订阅配置。

## 2. Quantumult X 结构

当前配置包含：`[general]`、`[dns]`、`[task_local]`、`[policy]`、`[server_remote]`、`[filter_remote]`、`[rewrite_remote]`、`[server_local]`、`[filter_local]`、`[rewrite_local]` 和 `[mitm]`。

- `[filter_local]`：117 条规则；类型为 `host` 69、`host-suffix` 32、`host-keyword` 8、`ip-cidr` 5、`host-wildcard` 1、`geoip` 1、`final` 1。没有发现完全相同的重复行。
- `[filter_remote]`：12 个远程分流定义，其中 11 个启用、1 个停用。启用源覆盖去广告、运营商劫持、Telegram、AI、Netflix、YouTube、Apple、国外影视、国外网站、中国域名和中国 IP；YouTube 已由远程源维护，本地没有再复制一份同类列表。
- `[policy]`：11 个静态策略组、6 个延迟测速策略组。`Gemini`、`Gpt`、`美加`、`🇭🇰️ 香港` 等策略依赖节点标签正则，能否选到可用节点必须结合运行时节点池验证。
- `[rewrite_remote]` 有 1 个启用源；配置还包含本地重写和 MitM，不应与分流规则混为一个生成层。

圈X本地规则中有一个语义冲突：`clients6.google.com` 先被送到 `美加`，之后又出现 `host-suffix, clients6.google.com, Google`。按首条命中模型，后者不能覆盖前者。其余本地规则没有发现相同域名的第二条 `host/host-suffix` 定义。

## 3. Clash Verge / Mihomo 结构

桌面导出 YAML 可正常解析，包含：

- 3 个 proxy provider：`provider-a` 为本地文件，`provider-b` 和 `provider-c` 为 HTTP provider；
- 20 个策略组，包括 `节点选择`、`自动选择`、`ChatGPT`、`AI`、`Gemini`、`Google`、地区测速组、`流媒体`、`Apple`、`国内直连` 和 `漏网之鱼`；
- 192 条内嵌规则：`DOMAIN-SUFFIX` 91、`DOMAIN` 69、`IP-CIDR` 10、`DOMAIN-KEYWORD` 10、`GEOSITE` 6、`GEOIP` 3、`DST-PORT` 2、`MATCH` 1；
- 没有 `rule-providers`。也就是说，当前 Clash 规则主体是固定写入 `master.yaml` 的静态列表，不会像圈X那样由 11 个启用的远程分流源自动更新。

桌面脱敏 `master.yaml` 与当前 Clash Verge 运行目录的 `clash-verge.yaml` 比较结果如下：192 条规则和 20 个策略组完全一致，3 个 provider 的键和字段也一致；运行文件额外包含节点、控制器、端口和运行时主机信息，且 DNS/TUN 存在运行时字段差异。这说明桌面导出足以作为规则结构基线，但不是运行时文件的完整替代品。

Clash 中没有完全相同的重复规则，但有 10 个域名值被定义多次：8 组是同一目标下 `DOMAIN` 与 `DOMAIN-SUFFIX` 的重复覆盖，2 组是目标冲突：

- `gdmf.apple.com` 先命中 `Apple`，后面又定义为 `REJECT`，后面的拒绝规则按首条命中不会生效；
- `clients6.google.com` 先命中 `美国`，后面又定义为 `Google`，后面的规则同样不能覆盖前者。

## 4. 两个客户端的规则意图差异

将圈X类型映射为 Clash 类型，并将 `direct → DIRECT`、`美加 → 美国`、`Gpt → ChatGPT`、`🍎 苹果服务 → Apple` 等策略名做比较后：

- 116 个圈X本地规则值中，105 个与 Clash 有相同目标的对应项；
- 9 个对应项目标不一致；
- 2 个没有相同的类型和值组合。

需要优先确认的差异：

1. AI/Gemini：圈X把 `aiplatform.googleapis.com`、`discoveryengine.googleapis.com`、`cloudcode-pa.googleapis.com`、`cloudaicompanion.googleapis.com`、`proactivebackend-pa.googleapis.com` 和 `speechs3proto2-pa.googleapis.com` 送到 `Gemini`；Clash 当前把它们送到 `Google`。这可能是有意的策略分层，也可能导致 Gemini 请求走错策略组，不能只靠名称推断。
2. Apple：圈X把 `mesu.apple.com` 和 `updates-http.cdn-apple.com` 设为 `direct`；Clash 将二者设为 `REJECT`。需要根据“允许系统更新”还是“阻止更新检查”的目标做明确选择。
3. `msub.xn--m7r52rosihxm.com`：圈X是精确域名到 `🇭🇰️ 香港`；Clash 没有同值精确规则，只有 `DOMAIN-KEYWORD,msub,日本`，其匹配范围和目标都不同。
4. 圈X有 `host-wildcard, *-aiplatform.googleapis.com, Gemini`；Clash 没有同类型规则，只出现了若干 `DOMAIN-SUFFIX` 规则。两者覆盖边界不能直接视为相同。
5. `GEOIP,cn` 的目标是圈X的 `direct`、Clash 的 `国内直连`。这是策略组名称差异，当前属于可解释映射，不单独视为错误。

Clash 的 `GEOSITE,youtube → 流媒体` 与圈X的远程 `YouTube` 列表表达了相近意图，但来源、匹配集合和更新机制不同；后续应通过代表性域名测试确认二者实际覆盖，而不是只看规则名称。

## 5. 当前结论

当前已经有可复现的本机起点，但还没有“单一事实源”：

- 圈X偏向“本地规则 + 远程规则源 + 动态策略组”；
- Clash偏向“内嵌静态规则 + 3 个节点 provider + 本地策略组”；
- 两端有一部分规则是手工同步的，且已出现明确的策略漂移和首条命中冲突；
- 圈X的重写/MitM和 Clash 的 TUN/DNS 是不同能力层，不能在第一步强行合并。

本次没有根据这些差异直接改配置，也没有把配置中的订阅 URL、节点或 Token 写入分析报告。

## 6. 下一步建议

1. 先确定规范分类和策略映射，至少明确 `Gemini/Google/AI`、Apple 更新域名、`msub` 和 PT 规则的目标。
2. 从两个原始快照提取不含凭据的规则目录，给每条规则记录来源、客户端适配语法、优先级和预计策略。
3. 为圈X远程规则和 Clash 静态列表建立来源登记；公开 GitHub 规则只保存公开来源标识和版本/哈希，订阅 URL 继续留在本机。
4. 加入跨客户端冲突检测和代表性域名命中测试，再生成 Quantumult X、Clash/Mihomo 和 Shadowrocket 输出。
5. 对 Clash 先验证最终合并配置、策略组存在性和运行核心重载，再讨论任何规则删改；不能把 YAML 解析或 `mihomo -t` 当作生效证明。
