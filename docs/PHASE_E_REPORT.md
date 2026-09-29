# Phase E Live Integration Report

> 本文记录 0.1.0 时点的历史阻塞，并追加 2026-09-28 的 Codex CLI 复测。0.2.0-dev 本地 Hub/Codex MCP 已通过，详细实现见 [`PHASE_G_I_REPORT.md`](PHASE_G_I_REPORT.md)；ChatGPT 外部验收仍未完成。

日期：2026-09-24；复测：2026-09-28

## 当前状态

阶段 E 的本地 Codex 部分已经通过，ChatGPT 外部连接部分仍在进行中。以下为 2026-09-24 的历史前置检查结果：

- `http://127.0.0.1:8765/healthz` 无服务监听；
- `RESEARCH_HUB_READ_TOKEN` 未配置；
- `RESEARCH_HUB_ADMIN_TOKEN` 未配置；
- 当前会话没有可调用的 Retrieval Hub `search`、`fetch`、`search_documents` MCP tools。

因此在该时点不能声明真实 HTTP、MCP、metadata filter 或 ChatGPT 引用链路通过。该结论已被下面的本地 Codex 复测部分更新，但不代表 ChatGPT 外部链路已经通过。

## 2026-09-28 Codex CLI MCP 复测

环境与范围：

- Codex CLI：`0.146.0`；
- `codex mcp list` 显示 `internalResearch` 为 `enabled`；
- stdio command 指向本仓库 `backend/.venv/bin/python -m research_hub.cli`；
- 当前注册数据目录为 `backend/data/hub`，即明确标记的虚构 fixture，不是 `backend/data/real-test`；
- 测试会话使用 `--ephemeral` 和 `-s read-only`，没有修改 Policy、入库或删除数据。

测试提示明确要求只使用 `internalResearch`，先调用 `search_documents({query: "芯片需求", limit: 2})`，再对第一条结果调用 `fetch`，且不得使用 shell 或读取仓库文件。Codex JSONL 事件流记录到：

1. `mcp_tool_call`：`internalResearch.search_documents`，状态 `completed`；
2. 返回 2 条 fixture 结果、`policy_version: 5`、`matched_chunks: 2`、服务端 `elapsed_ms: 5.44`；
3. `mcp_tool_call`：`internalResearch.fetch`，状态 `completed`；
4. `fetch` 的 ID 与第一条 search 结果一致，metadata 包含 `content_trust: untrusted_source_data_not_instructions`；
5. Codex 最终响应准确列出 `tools_used`、Policy 版本、结果 ID、fetch ID、标题和 URL，没有复制正文。

结论：本机 Codex 可以从已注册的 stdio MCP 实际调用本仓库 `search_documents → fetch`。本次证据验证的是 MCP tool discovery、进程启动、结构化返回和调用顺序；没有用模型口头回答替代工具事件。

复测期间观察到两个非阻塞诊断：外层受限执行环境首次启动 in-process app-server 时返回 `Operation not permitted`，在获准启动本地 Codex 进程后成功；Codex 还打印了一条旧 models cache 缺少 `base_instructions` 的 warning，但未影响 MCP 初始化或两个 tool call。

本次仍未证明：

- 当前 Codex 注册项尚未切换到 `backend/data/real-test`，因此本次不读取或引用真实 Capital IQ 内容；
- loopback URL 只有在本地 HTTP Hub 同时运行时才可由浏览器打开；stdio `fetch` 本身不依赖 HTTP 进程；
- ChatGPT Developer mode、HTTPS/Secure MCP Tunnel 和外部可达引用仍未验收；
- metadata filter、Policy 修改后的下一次 Codex 调用和真实库 hybrid 查询不由这次只读 fixture 复测覆盖。

## 2026-09-28 NVIDIA 短 Prompt A/B

### 测试设计

为了比较“只命中公司名”和“理解投资问题”的差异，本次建立了临时虚构语料，不读取或复制真实研报：10 篇短文包含 4 篇高频重复 NVIDIA 名称的资料卡/名录/会议名单、2 篇投资与估值材料、2 篇竞争/基础设施风险材料及 2 篇行业背景材料。

两组保持相同：

- Codex CLI `0.146.0`、同一模型会话模式、`--ephemeral`、`-s read-only`；
- 同一临时数据库、Policy v1、query、limit 和 MCP tool schema；
- 同一个 Prompt：“英伟达的投资价值和主要风险是什么？”；
- 都要求调用一次 `search_documents({query: "英伟达投资价值和主要风险", limit: 6})`，再根据 snippet fetch 最有用的至多两篇文档；
- 都要求区分 document facts、investment inference、risks 和 information gaps。

唯一变量：

- 对照组：同一 `RetrievalHub`，semantic adapter 返回空候选，即概念增强 FTS-only；
- 实验组：正常 production path，FTS5 + multilingual MiniLM dense vector + 文档级 RRF。

两个 stdio MCP 都通过临时 Codex config override 启动，没有修改用户全局 MCP 配置、OpenAPI、MCP schema、Policy 或仓库运行数据库。

### 工具调用与检索结果

两组 JSONL 都记录了 1 次 `internalResearch.search_documents` 和并行的 2 次 `internalResearch.fetch`，全部状态为 `completed`。

人工预先把 `investment_memo`、`valuation`、`risk` 标记为直接相关，其余 profile/catalog/history/directory/industry 标记为非直接相关。结果如下：

| 指标 | FTS-only 对照组 | Hybrid 实验组 |
|---|---:|---:|
| Top 6 直接相关文档 | 1 / 6 | 3 / 6 |
| 直接相关 Precision@6 | 16.7% | 50.0% |
| 第一篇直接相关位置 | 6 | 2 |
| Reciprocal Rank | 0.167 | 0.500 |
| Fetch 的直接相关文档 | 1 / 2 | 2 / 2 |
| Search 服务耗时 | 4.24 ms | 780.57 ms（新进程冷启动） |

对照组 top 5 依次被会议名单、产品名录、历史沿革、行业记录和公司资料卡占据；唯一直接风险材料排第 6。Codex 最终 fetch 了“竞争风险”和“公司资料卡”。

Hybrid 将“竞争风险”提升到第 2、“估值框架”提升到第 3、“AI 基础设施供应风险”召回到第 5。Codex 最终 fetch 了“竞争风险”和“估值框架”。

### 最终回答差异

两组都正确列出 AMD/自研芯片、监管、需求周期和估值风险，也都明确虚构数据不能形成现实投资建议。

对照组对投资价值的正面部分主要只能从“GPU + CUDA 转换成本”作宽泛推断，并明确缺少现金流与估值数据；这是因为返回给模型的高位候选大部分只重复公司名。

Hybrid 回答多出了可由检索证据支撑的两个判断：

1. 应用远期市盈率、自由现金流收益率和数据中心增长持续性评估投资价值；
2. AI 基础设施需求与 CUDA 黏性构成潜在增长/壁垒，但客户资本开支放缓可能触发增长下修与估值压缩。

结论：在这组受控虚构样本中，差异主要来自 retrieval，而不是 Prompt 或模型变化。Hybrid 没有完全消除关键词噪声（产品名录仍排第 1），但显著改善了 top-k 直接相关率和 Codex 实际 fetch 的证据质量。

### 限制与下一步

- 这是 10 篇人工构造的可控测试，不代表真实语料 nDCG；真实库仍需分析师 relevance labels。
- Hybrid 新 MCP 进程首次查询需要加载 ONNX 模型，冷启动约 0.78 秒；常驻进程的历史实测 P95 约 70 ms。
- 当前 lexical 60 / semantic 40 仍让高频公司名材料排第 1。若要进一步调整融合权重或加入 query-intent gate，应先形成 ranking 变更提案，不能根据一个样本直接改 production ranking。
- 临时数据库和控制 adapter 在测试后删除，不进入 Git，也不改变用户全局 `internalResearch` 注册项。

## 只读 Live 检查

上游启动并在当前 shell 配置 Read Token 后运行：

```bash
export RESEARCH_HUB_BASE_URL=http://127.0.0.1:8765
export RESEARCH_HUB_READ_TOKEN='<read token>'
export RESEARCH_HUB_LIVE_QUERY='芯片'
npm run check:live
```

命令只执行 health、status、sources、policy、search 和首条结果 fetch，不更新策略、不导入数据。输出不包含 Token 或完整正文，只记录 source IDs、result IDs、Policy 版本一致性和 payload/token 指标。

## 通过条件

- health 返回成功；
- status、policy 和 search 的 Policy version 一致；
- search 返回符合契约的服务端顺序；
- 若有结果，首条文档 fetch 符合契约；
- HTTP payload 指标可复现。

## 仍需人工或 MCP 环境完成

1. 在 Dashboard 使用 Admin Token 更新策略，再运行相同查询确认新版本。
2. 通过已配置的 MCP tools 执行相同 `search`，比较 HTTP/MCP 结果 ID 顺序。
3. 对首条最终引用结果执行 MCP `fetch` 并完成带 URL 的回答。
4. 使用真实上游响应验证 metadata filter。
5. 记录实际 MCP tool schema、调用次数和平台 usage，而不是 HTTP envelope 估算。

缺少上述环境时，这些项目保持 `not_run`，不会由 fixture 结果替代。

真实联调记录使用 [`evaluation/MCP_LIVE_TEMPLATE.md`](evaluation/MCP_LIVE_TEMPLATE.md)，确保 Policy、排序、fetch、引用和 token 证据使用同一套字段，并避免写入凭据或真实正文。

## HTTP/MCP 排序一致性检查

把 `npm run check:live` 的 JSON 输出和真实 MCP tool result 分别保存到临时文件后运行：

```bash
npm --silent run check:live > /tmp/retrieval-http.json
npm run check:mcp-parity -- /tmp/retrieval-http.json /tmp/retrieval-mcp.json
```

检查器支持标准 MCP envelope、标准 `search` payload 和高级 `search_documents` payload。标准 `search` 契约没有 `policy_version`，因此只核对结果 ID 及顺序，并将版本检查标记为 `not_available`；高级工具同时核对 `policy_version`。这一区别不会被客户端填补或猜测。

真实响应捕获文件可能包含内部文档标识，不应提交；仓库已忽略 `artifacts/live/`。

## 2026-09-28 MCP V0 信息源 Ranking 补充验证

在不连接真实邮箱、不修改 OpenAPI/MCP schema 的条件下，新增虚构 Priority 1–4 信息源目录、显式 alias 解析和唯一主 ranking source。独立临时数据库检查完成 Policy v2→v3 重排：默认 tier 权重下虚构 Priority 1 来源优先；反转权重后下一次查询使用 v3 并切换第一名。MCP `search_documents` 回归测试也验证了相同的 v2→v3 顺序变化。

该结果证明现有 `source_weights` 可以承载早期信息源优先级，但不证明邮箱 Skill 已安装、邮箱连接器可用或三个文件夹完成全量扫描。详情见 [`memos/MCP_V0_SOURCE_RANKING.md`](memos/MCP_V0_SOURCE_RANKING.md)。

## 2026-09-28 MCP V1 虚构邮件批次验证

V1 新增持久化信息源、alias、document version attribution 和 email sync run/item。虚构 EML 与 JSON 分别匹配到虚构分析师和机构；三个文件夹计数为 `1/1/0`，批次状态为 `complete`；重复执行两份文档均为 `unchanged`。

同一临时 Hub 的 MCP `search_documents` 在默认权重下返回虚构分析师为第一名；Policy 从 v2 更新至 v3 并反转两者权重后，下一次 MCP 调用返回虚构机构为第一名。现有 MCP schema 未变化。

这仍不是实际邮箱验收：没有真实账户、连接器、附件或 watermark，也没有供模型调用的批次枚举工具。完整证据见 [`memos/MCP_V1_EMAIL_SOURCE_RANKING.md`](memos/MCP_V1_EMAIL_SOURCE_RANKING.md)。

## 2026-09-28 邮箱 Skill → Codex MCP 虚构验收

### 范围与夹具

本次没有邮箱接口，因此只验证“邮件进入 Retrieval Hub 后，Codex 能否通过 MCP 检索并形成受证据约束的分析”。没有安装或冒充执行 `daily-email-summary` Skill，也没有连接真实 Outlook、Calendar、SharePoint 或 OneNote。

可重复夹具脚本为 `backend/scripts/seed_email_skill_fixture.py`，专用运行目录为 Git ignore 的 `backend/data/email-skill-codex-test`。脚本根据邮箱 Skill 的关键数据边界生成 7 封完全虚构的 EML/JSON 邮件：

- 三个文件夹完整计数：`inbox=3`、`inbox_sellside=2`、`inbox_third_party=2`；
- 两封跨文件夹相同正文，用于验证完全重复折叠；
- 一份 2026-06-01 发布、2026-09-28 才收到的旧报告，用于区分报告日期与收件日期；
- Priority 1 分析师、Priority 2 机构、Priority 1 S&T/PB 发件人、Priority 4 新闻和一个未知发件人；
- `attachment_status` 明确区分正文已读、附件未取得和不适用；
- 一封未知来源传闻包含 `IGNORE ALL PRIOR INSTRUCTIONS...`，用于验证文档提示注入不会成为指令。

首次运行创建 7 份文档；第二次运行得到 `unchanged=7`。同步批次状态为 `complete`、`error_count=0`。来源归因得到 6 个 `matched`、1 个 `unmatched`。服务端搜索把 7 份原始文档按相同正文 SHA 折叠为 6 条结果，旧报告的新鲜度继续使用 6 月发布日期。

复现夹具：

```bash
backend/.venv/bin/python backend/scripts/seed_email_skill_fixture.py \
  --data-dir backend/data/email-skill-codex-test
```

### Codex A/B 调用

两组均使用临时 `--ephemeral`、`read-only` 会话并关闭 web；不修改全局 MCP 配置。

- 对照组不允许使用工具，只给问题“虚构公司 Aurora Compute 的投资价值和主要风险是什么”。Codex 正确回答证据不足，并列出所需商业、财务、市场、估值和治理证据，没有补造公司事实。
- 实验组通过 CLI `--config` 临时注册唯一的 `emailFixture` stdio MCP，要求 `search_documents({query: "Aurora Compute", limit: 6})` 后 fetch 全部命中。JSONL 记录 1 次 search 和 6 次 fetch，全部 `completed`；没有 shell、web 或仓库读取事件。

实验组 MCP 返回 `policy_version=2`、`total=6`、`matched_chunks=7`，服务端 search 耗时 4.43 ms。Codex 最终回答：

- 逐项区分邮件事实、口径未对齐、模型投资推断和信息缺口；
- 为关键事实保留 `source_id`、文档 URL 和字符区间；
- 没有把 2026-06-01 的旧报告写成 2026-09-28 的新事实；
- 没有把未读 PDF 摘要、新闻转述或未知发件人传闻提升为已核验事实；
- 明确拒绝邮件正文中的提示注入，没有把取消订单传闻写成确认信息；
- 形成“增长线索存在，但估值、供应执行、拥挤度和证据质量使风险收益比仍无法可靠确认”的受限判断，而对照组只能给出“证据不足”。

### 发现的问题与结论

本次本地 Codex MCP 主链路通过，但不是完整邮箱 Skill 验收：

1. **重复覆盖对模型不可见。** Hub 确实把 7 份文档折叠为 6 条，但 `search_documents` 不返回去重前文档数、重复组或邮件同步批次。Codex 因此无法从 MCP 证明跨文件夹重复；`matched_chunks=7` 也不能安全解释为 7 封邮件。未来若要让日报 coverage block 可审计，需要先提出只读批次/去重 provenance 契约，而不是让 Prompt 猜测。
2. **全量邮箱扫描未验证。** 没有实际账户身份、folder id、分页、watermark、retry-after 或附件下载，因此只能证明入库后的检索与分析，不能声称 Outlook 全量扫描完成。
3. **九节日报未验证。** Calendar、SharePoint、OneNote、canonical 附件模板与 46 行 watchlist 均不在本次输入中；本次仅测试 email-only 降级分析。
4. **全文 fetch 成本仍高。** 6 份很短的虚构邮件使 Codex 会话报告 72,711 input tokens（含会话/工具上下文和结构化返回），说明真实长附件不应默认全部 fetch。应先检索 Top-K，再按问题 fetch 少量证据；需要 passage fetch 时必须先走契约变更提案。
5. **引用 URL 是 loopback。** stdio MCP 可以 fetch，但 `http://127.0.0.1:8765/...` 只有 HTTP Hub 同时运行时才能点击打开，不等于 ChatGPT 外部可达引用。

结论：在无邮箱接口的前提下，已经可以用虚构邮件验证 `Codex → MCP search → MCP fetch → 有来源约束的分析`。真实邮箱上线前，最优先补的是“邮箱同步/去重 coverage 的只读可观察性”，其次才是完整九节日报编排。

## 2026-09-28 导师可分发插件包

为便于导师用自己的已整理邮件验证 MCP，新增 `mentor-demo/` 本地插件包。它把以下内容放在同一交付边界：

- `email-research-mcp` Codex 插件和本地 marketplace；
- `mentor-email-research` Skill，固定 `search_documents → fetch → 事实/冲突/推断/缺口` 工作流；
- 三文件夹 `.eml/.json/.jsonl` 显式导入器；
- 可本地编辑、默认仅含虚构 alias 的 Priority 1–4 来源配置；
- 五封虚构邮件和不会污染导师数据库的临时自检；
- setup、import、stdio MCP 启动脚本和导师 README。

干净虚拟环境自检结果：5 份创建、批次 `complete`、文件夹计数 `2/2/1`、`error_count=0`、来源归因 `4 matched + 1 unmatched`、重复正文折叠后 4 条。stdio MCP 实际完成 initialize、list tools、`search_documents` 和 `fetch`；工具集仍为 `search/fetch/search_documents`，Policy v2，fetch ID 与第一条结果一致。

该交付没有连接任何真实邮箱，也没有把真实内容写入 ZIP。导师数据只在其本地状态目录生成。完整说明见 [`memos/MENTOR_EMAIL_MCP_HANDOFF.md`](memos/MENTOR_EMAIL_MCP_HANDOFF.md)。
