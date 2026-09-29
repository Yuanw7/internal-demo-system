# Roadmap

更新日期：2026-09-29

阶段 A–F 保留第二部分 Dashboard 的历史交付证据。自 2026-09-24 起，用户明确将范围扩展为同仓库 Retrieval Hub + Dashboard + MCP；新增阶段 G–K 按“先本地后端、再 MCP、再客户端联调、最后外部 ChatGPT 验收”的顺序推进。

## 阶段 A：地基与接口契约固化 — 已完成

目标：让后续 coding 有唯一使命、架构边界、接口事实来源和执行规范。

交付：

- `MISSION.md`、`ROADMAP.md`、`AGENTS.md`；
- 集成架构与工程规范；
- 第一部分交付的 OpenAPI、examples 和 handoff 原样归档；
- 项目级 `mcp-retrieval-demo` Skill；
- 零依赖 foundation/contract 校验；
- 接口缺口及 token 风险清单。

退出条件：

- `npm test` 通过；
- OpenAPI 版本、核心路径和核心 schema 可自动验证；
- Skill 结构验证通过；
- 架构明确“不处理系统原文件”和“不在客户端重排”。

## 阶段 B：契约客户端与 mock 基线 — 已完成

目标：不依赖真实后端即可稳定开发和测试。

计划交付：

- TypeScript 严格模式工程骨架；
- 单一 API client，覆盖 sources/search/document/policy/status；
- 从 OpenAPI 派生或校验的边界类型；
- 基于 `examples.json` 的 mock server 或 fixture adapter；
- 401、403、404、409、413、422 错误映射测试。

退出条件：

- mock 下可跑通“读策略 → 保存 → 再搜索”；
- 409 不会自动覆盖；
- API DTO 字段与 OpenAPI 一致，不出现第二套手写协议。

完成证据见 [`docs/PHASE_B_REPORT.md`](docs/PHASE_B_REPORT.md)。

## 阶段 C：Retrieval Policy Dashboard — 已完成

目标：可视化配置并证明下一次检索受策略影响。

计划交付：

- 数据源状态、策略编辑、搜索结果与文档读取四个最小区域；
- `source_weights`、`recency_boost`、`half_life_days`、`default_limit` 编辑；
- query 级 `source_ids/since/until/metadata/limit` 过滤；
- 策略版本、分项评分和前后排名对比；
- 输入校验、冲突提示和纯文本安全渲染。

退出条件：

- 同一查询修改来源权重后排序变化可见；
- 新鲜度配置变化有可解释结果；
- 页面不包含任何本地重排实现。

完成证据见 [`docs/PHASE_C_REPORT.md`](docs/PHASE_C_REPORT.md)。

## 阶段 D：Policy 效果与 token 评测 — 已完成

目标：用固定样例回答“策略是否有效、代价是多少”。

计划交付：

- 受控查询集和期望结果；
- source weight、freshness、metadata filter 三类实验；
- 排名、延迟、响应字节和估算 token 报告；
- 相关性退化保护和失败样例记录。

退出条件：

- 所有实验可重复运行；
- 结果包含 `policy_version`；
- token 数据按 search、fetch、工具 schema 分开记录。

完成证据见 [`docs/PHASE_D_REPORT.md`](docs/PHASE_D_REPORT.md) 和 [`docs/evaluation/BASELINE.md`](docs/evaluation/BASELINE.md)。Metadata filter 的实验规范可重复运行，但由于上游交付包没有过滤后的 SearchResponse，结果诚实标记为 `not_run`，留待阶段 E 补录。

## 阶段 E：MCP / ChatGPT 联调 — 进行中

目标：验证上游 MCP 在目标 ChatGPT 环境中的真实行为。

计划交付：

- `search → fetch → 引用` 端到端记录；
- HTTP 与 MCP 排序一致性检查；
- URL 可达性、认证、全文 fetch token 风险实测；
- 实际限制和问题清单。

退出条件：

- 至少一组带引用回答成功；
- 策略更新后 MCP 下一次查询使用新版本；
- 若完整 `fetch` 超出预算，形成明确的上游契约变更建议。

当前推进：本地 Codex stdio MCP 已通过独立会话复测；ChatGPT Developer mode、认证与外部可达引用仍等待目标环境。此步骤不使用公网 tunnel，也不扩大接口范围。

2026-09-28 补充：`codex mcp list` 已确认 `internalResearch` enabled；临时只读 Codex CLI 会话实际完成 fixture 库 `search_documents → fetch`，Policy v5 和结果 ID 均来自 MCP 结构化响应。当前注册项仍指向 fixture 数据目录；真实 Capital IQ 库切换、ChatGPT 外部连接和可打开引用继续单独验收。证据见 `docs/PHASE_E_REPORT.md`。

## 阶段 F：交付与规模化建议 — 已完成（本仓库范围）

目标：形成可运行 Demo、复现说明和每天新增数百份文档时的升级路线。

计划交付：

- 一键本地运行说明；
- 架构、工具、ranking、问题和评测总结；
- 增量入库、队列、ANN、ACL、审计与索引版本建议；
- 未完成项、责任人和接口变更记录。

完成证据：本地 fixture Demo 的一键运行、架构/MCP/ranking 说明、问题清单与规模化建议已整理在 `docs/DELIVERY.md`。2026-09-24 已对 `dist/` 生产包完成 1674×854 桌面和 390×844 移动视口验收，策略 v1→v2、下一次检索重排、正文读取与 metadata 复用均通过。真实 MCP / ChatGPT 与 Capital IQ PDF 数据工程实验属于阶段 E 和上游数据责任，所需外部输入统一登记在 `docs/memos/EXTERNAL_ACCEPTANCE.md`，不阻止阶段 F 在本仓库责任范围内关闭。

## 阶段推进规则

- 开始下一阶段前确认上一阶段退出条件。
- 接口字段或语义变化先更新契约并记录影响，再改客户端。
- 需要公网、真实凭据、付费 API 或真实数据时单独确认。
- 发现上游能力缺口时先写清可复现案例，不在客户端创建影子实现。

## 阶段 G：范围变更与本地后端地基 — 已完成

目标：把第一部分纳入本仓库，同时保留既有 Dashboard 基底和 API 1.0 历史。

计划交付：

- 更新 Mission、架构、工程规则和版本迭代日志；
- Python 后端工程、显式 migration 和版本化文档模型；
- 虚构 fixture 的 source/document/version/page/chunk/Policy 持久化；
- 不依赖真实资料的自动测试。

退出条件：数据库可重复初始化和迁移；同一 external ID 内容变化产生新版本；现有 `npm test` 保持通过。

完成证据：`backend/` 已建立独立 Python 工程、显式 migration 和不可变文档版本；全仓 `npm test` 已包含后端测试。

## 阶段 H：解析、检索与策略 — 已完成（MVP）

目标：提供可解释、可过滤、可引用的唯一服务端检索。

计划交付：文本层 PDF/文本解析、边界感知分块、FTS5、source/date/metadata 过滤、来源权重、新鲜度和 citation。

退出条件：幂等导入、版本引用、Policy v1→v2 重排和过滤测试全部通过；Dashboard 不包含 ranking。

完成证据：支持文本/JSON/EML/文本层 PDF、ZIP 容器、边界感知 chunk、FTS5、过滤和策略排序。Codex 实测发现中文连续查询召回过严后，已改为中文 run 内 bigram OR、不同 run 间 AND，并增加回归测试。2026-09-24 对授权 Capital IQ 目录完成全量本地处理：802 份尝试、792 份成功、62,821 个 current chunk；日期、metadata、来源权重、幂等和 citation 均通过。10 份失败及 154 个精确重复正文组已记录；后续精确折叠与混合检索见阶段 L。

## 阶段 I：HTTP 与 Codex MCP — 已完成

目标：让本机 Codex 通过 stdio MCP 搜索和读取资料库。

计划交付：兼容契约的 HTTP API；只读 `search`、`fetch`、`search_documents`；stdio 与 Streamable HTTP transport；MCP Inspector 和本地 Codex 配置/验收说明。

退出条件：工具 schema、注解、错误和结果通过 Inspector；Codex 完成一组 `search → fetch → 带引用分析`。

完成证据：stdio 独立子进程与 Streamable HTTP `/mcp` 均完成初始化、工具发现和调用；`internalResearch` 已注册到本机 Codex，临时只读 Codex 会话完成 `search_documents/search → fetch → 带 URL 分析`。真实资料隔离库复测中，Codex 从业绩会、公司研报和供应链研报形成了事实/推断/冲突/缺口分层分析；同时暴露完整 `fetch` 消耗约 51k token、loopback 引用依赖 HTTP 进程等限制。详见 `docs/PHASE_G_I_REPORT.md` 和 `docs/memos/REAL_DATA_ACCEPTANCE_2026-09-24.md`。

## 阶段 J：Dashboard 与端到端整合 — 已完成（本地）

目标：Dashboard、HTTP 和 MCP 使用同一后端状态。

退出条件：真实本地 Hub 下策略修改影响下一次 HTTP/MCP 查询；Policy 版本和顺序一致；前后端完整测试通过。

完成证据：本地 HTTP `check:live` 已通过 health/status/sources/policy/search/fetch；HTTP 与 MCP 同查询返回相同 Policy 版本和结果 ID。浏览器 Live 模式将 `demo_filings`/`demo_research` 权重从 `1/1` 改为 `3/0.5` 后，下一次检索顺序立即反转并显示位次变化；随后恢复 `1/1`，Policy 版本推进至 v5。前后端全仓测试和生产构建通过。

## 阶段 K：ChatGPT 受控连接与分析验收 — 外部条件待满足

目标：让 ChatGPT 在开发者模式下使用同一 MCP 搜索资料并完成带证据分析。

实施边界：私有本地服务优先使用 Secure MCP Tunnel，不默认创建公网入口；Developer mode、workspace policy、tunnel/HTTPS、认证和可打开引用 URL 是外部前置条件；工具只返回证据，ChatGPT 负责比较、判断并区分事实、推断与缺口。

退出条件：直接问题、间接问题、追问、空结果和越界请求均有记录；至少一组分析包含可打开引用，工具选择与结果可复现。

## 阶段 L：投研短句混合检索 — 已完成（本地基线）

目标：把“包含某关键词的文章列表”升级为针对公司、具体产品和产业链问题的证据发现，例如用“英伟达具体显卡”找到 NVIDIA GPU 型号与相关 AI infrastructure 证据。

实施：版本化投研概念规划；FTS5 + 本地多语 dense-vector 双路召回；文档级 RRF；完全相同正文折叠；相关性质量门槛后再应用 source weight、freshness 和 metadata/date/source filter。无模型或索引陈旧时自动回退增强 FTS。HTTP/MCP 契约字段保持不变。

退出条件：虚构行为测试覆盖概念扩展、语义候选、回退和 Policy；全量 Capital IQ 库完成向量构建；固定短句 query set 记录 hybrid top-k 证据精度与 P95；全仓 `npm test` 通过。

完成证据：全量 62,821 个 current chunk 建成 384 维本地向量索引；四个固定买方短句完成 lexical/hybrid 对照；常驻进程 20 次 hybrid 查询 P50 38.64 ms、P95 70.12 ms；精确正文折叠后 `Nebius` top 50 无重复正文组；完整记录见 `docs/memos/HYBRID_RETRIEVAL_ACCEPTANCE_2026-09-24.md`。人工 relevance grade 仍是后续质量工作，不以启发式证据词覆盖冒充完成。

## 阶段 M：MCP V0 信息源 Ranking — 已完成（虚构本地验证）

目标：在不连接邮箱、不改变 MCP/OpenAPI 契约的前提下，验证截图所表达的 Priority 1–4 信息源目录、alias 匹配、唯一主 ranking source 和下一次检索重排。

实施：新增版本化虚构来源目录和严格解析器；只接受 canonical name/显式 alias，输出 matched/ambiguous/unmatched；每份 V0 文档只映射一个主来源，并复用现有 `source_id`、`source_weights` 和 `policy_version`。

退出条件：虚构测试证明 Priority 默认权重可改变相关候选顺序；反转 Policy 后下一次检索按新版本重排；不相关文档不会因高 Priority 被召回；MCP schema 和真实资料保持不变。

完成证据：`backend/scripts/check_source_ranking_v0.py` 在临时数据库中完成 Policy v2→v3 重排，详情见 `docs/memos/MCP_V0_SOURCE_RANKING.md`。V1 的真实来源目录、邮箱同步、多来源归因和全量批次枚举仍需单独确认。

## 阶段 N：MCP V1 邮件信息源持久化 — 已完成（虚构本地验证）

目标：在不连接真实账户、不扩大 MCP/OpenAPI 契约的条件下，把 V0 静态目录升级为可审计数据库模型，并验证 EML/JSON 邮件批次、主来源归因、Dashboard 兼容和 MCP 重排。

实施：schema migration v3 新增 information source、alias、document attribution、email sync run/item；EML parser 保留发件人名称、地址和 Message-ID；同步完成必须逐文件夹记录数量并与 item 总数一致。主信息源继续投影为现有 `source_id`，Dashboard 和 MCP 不创建第二套 ranking。

退出条件：虚构三文件夹批次状态为 complete；EML/JSON 两份资料均 matched；重复运行 unchanged；现有 `/api/sources`/Policy 可直接消费；MCP `search_documents` 在 Policy v2→v3 后按新权重切换第一名；全仓测试通过。

完成证据：`backend/scripts/check_source_ranking_v1.py` 和 `docs/memos/MCP_V1_EMAIL_SOURCE_RANKING.md`。真实邮箱连接、真实来源目录、附件处理、多来源联合评分及批次 MCP tool 仍未授权或实现。

## 阶段 O：导师邮件 MCP 可分发 Demo — 已完成（本地包）

目标：在没有邮箱 API 的条件下，把邮件证据 Skill、只读 MCP、导入器、虚构样例和导师操作说明整理为可独立复现的本地插件包。

实施：导师手工将获准邮件导出为 `.eml/.json/.jsonl` 并放入三个固定目录；显式导入脚本写入本地 V1 Hub。插件 Skill 指导 Codex 执行 `search_documents → fetch → 事实/冲突/推断/缺口`，MCP 继续只暴露三个只读工具。真实邮件、数据库、来源配置和凭据不进入分发包。

退出条件：插件与 Skill 校验通过；干净临时环境完成五封虚构邮件导入、来源归因、重复折叠；真实 stdio transport 完成初始化、工具发现、search 和 fetch；形成 ZIP、导师 README 和验收边界。

完成证据：`mentor-demo/README.md`、`docs/memos/MENTOR_EMAIL_MCP_HANDOFF.md` 和 `artifacts/mentor/email-research-mcp-mentor-demo-v1.zip`。该包不等于 Outlook API、完整邮箱分页或九节日报验收。

## 阶段 P：全自动监听与处理状态监控 — P1/P2 基线已实现，P3/P4 待完成

目标：只针对 Capital IQ 本地目录与 Outlook 建立自动发现、处理、向量发布、状态监控、重试和告警闭环，并在现有 Dashboard 展示待处理、处理中、已处理、失败和重试中。

已确认边界：

- 源文件更新或删除不覆盖、删除历史 document version；
- 只有 FTS 与 dense-vector generation 均发布后才算 `processed`；
- Outlook 附件属于必需处理范围，扫描 PDF 需要 OCR stage；
- Dashboard 仅本机开放，需要显示文件名或邮件主题，但正文仍按不可信内容隔离；
- 首期保留全部运行和历史数据；正式 retention policy 列入后续更新；
- 首期只考虑单机 SQLite/worker；PostgreSQL、多用户、ACL 和分布式部署列入后续更新；
- 延迟、积压和失败率阈值必须在测试后定标。

当前完成：schema migration v4/v5、五态 item/attempt/event/dead-letter、文件 observation/checkpoint、worker heartbeat、背压、OpenAPI 1.1.0 summary/list/detail/admin retry、Dashboard 监控区、Capital IQ `watch-folder` 轮询与向量发布门槛。Outlook 已完成认证无关 delta/附件接口、虚构分页、父子 provenance、V1 来源归因和可插拔 OCR 状态验证。1.0.0 已完整归档，MCP schema 不变。

仍待完成：文件事件监听、真实 Outlook/Graph 授权与附件下载、生产 OCR 引擎、durable raw payload/retry worker、批次 API、SSE、指标快照与告警。真实 Outlook 账号连接仍需要单独授权，OCR 引擎仍需选型。

详细实施基线见 [`docs/memos/AUTOMATED_INGESTION_MONITORING_PLAN.md`](docs/memos/AUTOMATED_INGESTION_MONITORING_PLAN.md)。
