# 配置来源

## 本机原始快照

`sources/local/` 保存本次从本机应用或用户指定导出复制的原始文件，默认不进入 Git：

- `quantumult-x/quantumult_20260905020418.conf`：用户指定的圈X导出。
- `quantumult-x/default.conf`：通过 Finder 从圈X App Group 的 `configuration/default.conf` 复制的快照；与上面的导出内容 SHA-256 相同。
- `clash-verge/master.yaml`：用户指定的桌面 `clash-master-config/master.yaml`，README 标注为脱敏导出。

Clash 运行目录中的生成配置没有复制进来，因为它包含运行时节点/订阅相关数据；本次仅以只读方式与桌面脱敏导出比较。

## 安全边界

不要把 `sources/local/` 下的内容提交到公共或共享仓库。后续应从这些原始快照中提取不含凭据的规则源，再放入可追踪的规范目录。

## 公开上游与缓存

- `upstreams.json` 是公开 GitHub 上游清单，包含客户端输入格式、规则分类和来源许可证。
- 上游清单支持在单个客户端配置下设置 `max_rules`；当前仅对 Quantumult X 的国外网站泛分类设置 10,000 条上限，Mihomo 保留完整远程 Provider。
- `policies.json` 是本机策略组名称到规则分类的映射；它不包含节点 URL。
- `upstreams.lock.json` 记录每次构建实际读取的公开文件 SHA-256 和字节数，用于审查自动更新是否只改变了上游规则。
- `cache/` 是构建时的本地缓存，已加入 Git 忽略；它不是发布内容。

个人需要优先于上游的规则放在项目根目录的 `overrides/rules.txt`，不要直接编辑生成的 `dist/` 文件。生成流程和客户端接入说明见 `docs/integration.md`。
