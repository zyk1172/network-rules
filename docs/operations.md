# 日常使用与发布

## 检查更新

README 的更新徽章、Actions 最近运行、`main/dist` 最新提交分别表示任务结果、检查时间和真正发布版本。构建成功但 PR 未合并时，客户端仍读取旧版 `main`。

每日任务固定 checkout `main`，先将上游分支锁定为具体 commit，再下载对应内容、记录 SHA256，以 `main` 为基线创建更新 PR。PR CI 执行 `build.py --locked` 复现输入，不重新读取移动分支。更新摘要显示分类数量变化、内容变化的组件数、Patch 和冲突统计；Actions summary 记录 UTC 检查时间，候选报告保留 14 天。合并需用户审核。

仓库默认分支须为 `main`；Actions 设置须允许创建 PR。GitHub 将创建和批准 PR 合为一个设置，本工作流只创建 PR，不调用 approval 或 merge；默认 token 权限仍为 read，更新 job 单独申请必要写权限。更新任务通过 `workflow_dispatch` 显式触发 CI，避免 bot PR 的事件触发策略阻断检查。

## 准备 Clash 接入

以下命令仅生成待启用文件，不打开 Clash 或更改代理方式：

```bash
python3 scripts/prepare_clash.py \
  --profile '/absolute/path/to/current-clash-profile.yaml' \
  --output-dir sources/local/clash-ready \
  --policy youtube=YouTube \
  --policy netflix=国外网站
```

指定用户当前配置，不能用历史导出代替。工具只读取配置并校验策略存在、provider 不碰撞；输出不包含节点、订阅、DNS、TUN 或认证字段。策略名缺失时停止，用 `--policy category=现有策略` 明确映射。

输出仅包括规则片段 `merge.yaml` 和 `compatibility.json`；后者包含映射、基础文件 SHA256、数量和 `activated: false`。provider 加 `network-rules-` 前缀。输出必须位于被忽略的 `sources/local/` 且目录不能已存在，避免覆盖以前草稿。

启用是独立操作：获得用户允许后才接入片段，核实内核加载和服务实际命中。静态兼容性通过不等于已启用。现有代理方式保持不变，准备工具没有系统代理、内核控制或启动客户端的代码。

## 查询分流原因

```bash
python3 scripts/rules.py explain ai.google.dev
```

从本地已生成产物读取 canonical 命中规则、上游 component、原始规则、Patch ID、冲突原因和被前面规则遮住的匹配；同时评估 QX 和 Mihomo 输出。未命中表示交给基础配置 FINAL/MATCH，不推断兜底策略。工具不发 DNS 请求、不访问代理内核，不检测真实节点可用性。

## 将问题变成可回归修补

```bash
python3 scripts/rules.py propose service.example.com \
  --category gemini --reason '已确认这是 Gemini 专用端点' \
  --output sources/local/drafts/service.json
```

默认只打印，指定 `--output` 才将草稿保存到被忽略目录。草稿包含精确域名（IP 则为 /32 或 /128）Patch 与回归案例，不自动扩成整个后缀。工具预演 canonical 优先级；如果更宽的高优先级规则仍覆盖目标，会拒绝草稿并提示人工审查。

接受审阅后的草稿并验证：

```bash
python3 scripts/rules.py accept sources/local/drafts/service.json
python3 scripts/build.py --locked
python3 scripts/validate.py
python3 -m unittest discover -s tests -v
```

`accept` 重新检查当前事实，只写 `patches/<id>.yaml` 和 `tests/routing-cases.json`，重复 ID 拒绝覆盖，不提交 Git、不更改客户端。预演不能替代构建后的双客户端回归测试。通过后在独立分支提交 PR，审核合并后才发布。

网络不可用时可显式 `build.py --offline`，缓存仍须符合锁定 SHA256，报告会标记 stale；恢复后用 `build.py --locked` 复现非 stale 产物。只有更新上游时才使用不带 `--locked` 的在线 build。
