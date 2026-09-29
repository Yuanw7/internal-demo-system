# 版本迭代日志

本日志记录目标、契约、架构和验收口径的实质变化。代码提交历史不能替代这里的产品决策记录。

## 0.2.0-dev — 2026-09-24

状态：实施中。

### 目标变化

- 项目从“只实现第二部分 Dashboard、消费外部 Retrieval Hub”扩展为同仓库的 Retrieval Hub + Dashboard + MCP。
- 最终验收改为：Codex/ChatGPT 能通过 MCP 搜索用户授权资料库，读取可定位原文，并基于证据给出分析判断和引用。
- 明确 MCP 不生成投资结论；模型负责分析，Server 负责可审计检索证据。

### 架构决策

- 本地后端成为 ingestion、versioning、index、ranking、Policy、HTTP 和 MCP 的唯一权威边界。
- 现有 Dashboard 基底保留，不复制 GitHub 版本整仓，也不在客户端新增 ranking。
- 使用版本化 document/page/chunk 模型；内容更新不得覆盖历史证据。
- 第一阶段先以 SQLite WAL + FTS5 建立基线；阶段 L 在用户确认投研短句需求后启用可选本地语义索引。
- Codex 优先使用 stdio MCP；ChatGPT 使用 Streamable HTTP `/mcp`，私有连接优先 Secure MCP Tunnel。

### MCP 验收变化

- 保留标准只读工具 `search`、`fetch`，增加高级只读 `search_documents`。
- server instructions 要求先搜索、再读取关键原文、最后形成分析，并区分文档事实、模型推断和缺口。
- 工具结果必须提供稳定 ID、绝对可引用 URL、页码/字符 offset；工具 annotations 必须准确。
- 本地 Codex 验收和 ChatGPT 外部验收分开记录，不能用 loopback 测试替代 ChatGPT 可达性。

### 与 GitHub 参考版本的关系

- 参考 `chendi-Shi/chenxi-internal-demo@624bb66d` 的 strict DTO、只读 MCP、Policy snapshot、同步状态和测试思路。
- 不要求逐文件一致；不直接继承覆盖式文档更新、固定字符分块、SQLite 向量全扫描、Web 进程内同步线程、匿名真实数据 Demo或根目录整仓覆盖。
- 详细差异见 `docs/memos/FIRST_PART_LOCAL_COMPLETION_PLAN.md`。

### 外部前置条件

- ChatGPT Developer mode 和 workspace policy 可用。
- 安全可达的 Streamable HTTP `/mcp` 或 Secure MCP Tunnel。
- 真实 Capital IQ 资料的使用授权、公司/月度范围和仓库外受控目录。

### 本迭代验收

- 阶段 G–J 在纯虚构 fixture 上自动化通过。
- Codex 完成一组 `search → fetch → 带引用分析`。
- 阶段 K 在外部条件到位后，ChatGPT 完成相同分析用例，并记录工具调用、引用、失败和边界请求。

### 2026-09-24 实施记录

- 新增 `backend/` 本地 Retrieval Hub，保留 API 1.0.0 兼容面。
- 新增显式 migration 和不可变 document version；重复内容幂等，修订内容保留历史。
- 新增文本/JSON/EML/文本层 PDF、边界感知 chunk、FTS5、过滤和 Policy ranking。
- 新增 HTTP、stdio MCP、Streamable HTTP `/mcp`、本地凭据和 Codex 配置样例。
- 全仓测试通过：27 个 Node 测试、16 个 Python 测试及 Vite build。
- Live HTTP 与 Streamable HTTP MCP 冒烟测试通过。
- `internalResearch` 已注册到本机 Codex；独立临时 Codex 会话完成带 URL 的证据分析。
- 实测发现“芯片需求”连续中文 bigram AND 漏召回；已改为 run 内 OR/run 间 AND，并完成 MCP 复测。
- 浏览器 Live 验收发现原生 `window.fetch` 被保存为未绑定函数后触发 `Illegal invocation`；API client 现统一绑定 `globalThis`，并增加接收者回归测试。
- 浏览器 Live 模式完成 Policy v3→v4 重排验收：来源权重从 `1/1` 改为 `3/0.5` 后，filings 与 research 的顺序在下一次检索中反转；恢复默认权重后 Policy 为 v5。
- HTTP 与 Streamable HTTP MCP 已用同一查询校验结果 ID 和 Policy 版本一致，Dashboard 不参与 score 计算。
- 新增 ZIP 原生只读接入和自动分批入库；修复 `21_Aug_2026` 日期识别及重复 `.pdf.pdf` 标题，并加入 ZIP/date 回归测试。
- 为真实 PDF 的 CFF Type1 字符映射增加 `fontTools` 依赖，解析器版本升级到 `local-text-v2`，旧解析版本继续保留。
- Capital IQ 授权子集完成受控测试：202 份尝试、200 份成功、4,514 个 current page、16,491 个 current chunk、4 个来源；数据库和正文保持 Git ignore。
- 真实库 Policy v1→v2 将 transcripts 权重提高后，`Nebius` 查询中 transcripts 从第 2 位升至第 1 位；恢复默认策略后为 v3，排序恢复。
- 真实 stdio MCP 和临时 Codex 会话通过。发现完整 `fetch` 导致单次分析约 51k token、首次高级工具调用需要自我纠错、loopback URL 依赖 HTTP 服务、2 份复杂 PDF 解析失败，均纳入后续优化。
- 完成所附 802 份 PDF 的全量本地处理：792 成功、9 份解析失败、1 份超过安全大小限制；当前 15,776 页、62,821 个 current chunk、数据库约 288 MB。
- 新增 schema migration v2，为 document version 保存确定性正文 SHA；回填历史版本并增加跨 source 相同正文测试。
- 全量盘点识别 154 个完全相同正文组、158 个额外副本。未擅自改变 ranking，精确重复折叠和 source/membership 重构进入正式提案。
- 全量库六个代表查询 P50 为 5.07–19.09 ms，P95 为 15.39–279.00 ms，未触发 PostgreSQL/ANN 升级阈值。
- 用户确认检索目标从宽泛关键词命中升级为投研短句、实体、具体产品与产业链语义发现；阶段 L 因此启用可选本地混合检索。
- 新增版本化 `retrieval_concepts.json`、query planner、多语 FastEmbed dense index、FTS/vector 文档级 RRF 和精确正文折叠；source weight、新鲜度与 metadata/date/source filter 仍由同一服务端权威实现。
- 选择约 220MB、384 维的 multilingual MiniLM 与 NumPy exact cosine 作为最简单本地基线，不引入云 embedding 或独立向量数据库；索引缺失/陈旧时自动回退增强 FTS，达到实测规模阈值后再迁移 ANN。
- 全量 62,821 个 current chunk 完成 dense index：vector matrix 92 MB、模型缓存 240 MB。常驻进程 20 次固定短句查询 P50 38.64 ms、P95 70.12 ms；冷启动首次查询约 0.6–1.0 秒。
- 四个固定买方短句完成 lexical/hybrid smoke check；Nebius capex/GPU 严格词法候选为 8，hybrid 补足至 10；`Nebius` top 50 的精确重复正文组从已知高占位问题降为 0。结果不替代后续人工 relevance 标注。

### 2026-09-28 MCP V0 信息源 Ranking

- 用户确认先执行 V0：验证 Priority 1–4 信息源、匹配状态和唯一主 ranking source，不接真实邮箱。
- 新增版本化虚构 `source_rankings_v0.json`，不把截图中的真实名单、账号或内部内容写入 Git。
- 新增严格 alias resolver，区分 matched、ambiguous 和 unmatched；V0 禁止 fuzzy match 自动合并同名人员。
- 每份文档只使用一个主信息源权重，避免分析师、机构、平台和分发人重复相乘；现有服务端 `source_weights`、相关性门槛和评分公式保持权威。
- 临时数据库验收完成 Policy v2→v3：默认权重下虚构 Priority 1 来源排第一，反转 Policy 后下一次查询由另一来源排第一。
- OpenAPI 1.0.0、三个 MCP tools 和响应 DTO 均未改变；真实来源目录、邮箱同步、多来源归因与 `list_email_batch` 留待 V1 单独确认。

### 2026-09-28 MCP V1 邮件信息源持久化

- 用户明确确认从 V0 升级到 V1；仍以虚构账户、发件人、机构和正文完成开发，不连接真实外部系统。
- 新增 schema migration v3：information source、alias、document version attribution、email sync run/item；原有文档表和索引继续作为唯一检索事实来源。
- EML parser 新增显式 sender name/address/Message-ID metadata；来源解析只使用邮件头或结构化 metadata，不扫描正文猜测身份。
- 三个虚构文件夹均有明确返回数，零结果文件夹仍记录；folder counts 与 item 总数不一致时拒绝标记 complete。
- V1 fixture 两份文档分别匹配虚构分析师和虚构机构；重复运行均为 unchanged，Policy 不重复增版。
- 现有 `/api/sources` 和 Dashboard Policy 编辑无需契约升级即可管理主信息源权重；alias、归因和批次尚未暴露给 UI。
- MCP `search_documents` 验证 Policy v2→v3 后第一名从虚构分析师切换到虚构机构；OpenAPI 1.0.0 和工具 schema 未改变。

### 2026-09-28 邮箱 Skill 的 Codex MCP 虚构验收

- 在没有邮箱接口的条件下，新增可重复脚本生成 7 封完全虚构 EML/JSON 邮件，覆盖三个指定文件夹、跨文件夹重复、旧报告今日转发、附件缺口、来源层级、未知发件人及文档提示注入。
- 独立 Git-ignore 数据库首次创建 7 份、再次运行 7 份均 unchanged；批次为 complete，计数 `3/2/2`，归因为 6 matched + 1 unmatched，检索折叠为 6 条。
- Codex 无工具对照组只报告证据不足；临时只读 MCP 实验组完成 1 次 `search_documents` 和 6 次 `fetch`，保留 Policy v2、source ID、URL 和字符区间，并区分事实、推断、冲突与缺口。
- Codex 没有执行邮件正文中的提示注入，也没有把旧报告收件日、未读附件、新闻转述或未知来源传闻写成已确认事实。
- 暴露契约缺口：当前 MCP search 不返回去重前数量、重复组或同步批次，模型无法独立证明 coverage。该能力若进入正式工具必须先提交契约变更提案。
- 本次不等于 Outlook 全量扫描或九节日报验收；Calendar、SharePoint、OneNote、附件下载和 46 行 watchlist 未运行。

### 2026-09-28 导师可分发版本

- 使用官方兼容插件结构，把邮件研究 Skill 与本地 stdio MCP 放入 `email-research-mcp`，并建立可添加的 `mentor-demo` 本地 marketplace。
- 新增无邮箱 API 的显式导入路径：导师只需把获准 `.eml/.json/.jsonl` 整理到三个目录；导入过程不回显正文，MCP 仍保持只读。
- 来源目录保留 Priority 1–4、显式 alias、唯一主 ranking source 和未知来源 fallback；真实来源配置只写导师本地状态目录。
- 干净环境完成 5 封虚构邮件导入、`4 matched + 1 unmatched`、5→4 重复折叠，以及 stdio MCP initialize/list/search/fetch。
- 分发 ZIP 不包含真实邮件、数据库、Token、账号或公网地址；Outlook API、分页/watermark、附件 OCR 和完整九节日报仍不在本版本验收范围。

### 2026-09-29 自动监听与状态监控需求冻结

- 用户确认首期只监听 Capital IQ 本地目录与 Outlook，不扩展 Gmail、SharePoint 或对象存储。
- 源端更新和删除均保留不可变历史版本；首期不自动清理既有数据库、批次、attempt、状态事件、指标、附件或向量 generation。
- `processed` 的验收口径收紧为 FTS 与 dense-vector generation 均已发布；向量仍待构建时即使 FTS 可回退查询，也不能在 Dashboard 标记已处理。
- Outlook 附件纳入必需处理范围，文本附件需解析，扫描 PDF 需经过 OCR stage；OCR 选型和资源限制仍待确认。
- Dashboard 仅在本机开放，需要展示文件名或邮件主题，但不返回正文，标题仍按不可信纯文本渲染。
- 当前只规划单机 SQLite/worker；retention policy、PostgreSQL、多用户/ACL、多主机 worker 与 HA 明确进入后续更新待办。
- backlog、失败率和端到端延迟阈值将在虚构压测和少量授权数据验收后定标，不写入未经测量的承诺。
- 新增监控、重试、重跑和 SSE API 会改变正式 HTTP 契约；本次只冻结方案，不修改 OpenAPI 1.0.0、不连接真实 Outlook。详细实施基线见 `docs/memos/AUTOMATED_INGESTION_MONITORING_PLAN.md`。

### 2026-09-29 阶段 P 第一批实施

- 新增 schema migration v4：ingestion connector、checkpoint、batch、item、batch item、attempt、status event 和 dead letter；既有 document/version/chunk 继续作为唯一检索事实来源。
- 五态由后端持久化；`processed` 强制要求 `semantic_generation_id` 与 `searchable_at`，避免把仅 FTS 可用的数据误报为完整处理。
- 新增 Capital IQ `watch-folder` 命令：递归发现支持格式、按路径/内容/pipeline 版本幂等、显式 worker lease、失败重试、全量 semantic generation 构建和发布。
- 新增 OpenAPI 1.1.0 ingestion summary、items、item detail 和 Admin retry；1.0.0 完整归档，三个 MCP tools 和检索 DTO 不变。
- Dashboard 新增五态 KPI、向量积压、文件名/邮件主题列表、阶段/attempt、详情和人工重试；Live 模式使用可配置代码路径的 5 秒轮询基线。
- 虚构行为测试覆盖向量发布门槛、重复扫描幂等、损坏 PDF 失败和乐观锁重试。真实 Outlook、附件 OCR、SSE、批次重跑、指标快照和告警仍待后续阶段。

### 2026-09-29 阶段 P 第二批实施

- 新增 schema migration v5：`ingestion_source_objects` 持久化文件稳定窗口与删除 observation，`ingestion_worker_heartbeats` 记录 worker 当前状态，并为 ingestion item 增加邮件/附件父子 provenance。
- `watch-folder` 新增可配置 `settle_seconds` 和 `max_queue_depth`；扫描开始/成功、目录摘要 checkpoint、背压状态、lease 续期与 stopped heartbeat 均持久化。删除文件只写 tombstone，不删除历史 document/version/chunk。
- 新增认证无关的 `OutlookDeltaClient`、确定性虚构 adapter 和 `outlook-fixture-demo`；delta checkpoint 仅在本页消息及附件完成 discovery 后推进，并拒绝缺失/循环分页 cursor。
- Outlook 正文与附件进入同一 ingestion 状态机。必需附件在持久化正文前先完成解析门槛；扫描 PDF 未配置 OCR 时，附件及父邮件失败且不写检索文档。
- 新增可替换 `OCRAdapter`；虚构 OCR 自动测试证明 OCR 文本也必须经过 persist、FTS、vectorize 和 publish 后才进入 `processed`，不把测试 adapter 描述为生产 OCR。
- 邮件 sender metadata 继续使用 V1 显式 alias/priority 归因；未知来源进入独立 fallback source，不从正文推断身份，也不在客户端重算 ranking。
- 自动测试新增稳定窗口、checkpoint、背压、删除保留、delta 分页、父子关系、OCR 阻断与 OCR 成功路径。真实 Graph 登录/附件下载、durable raw payload spool、独立 retry worker、SSE、指标快照和告警仍待后续批次。

### 2026-09-29 本机真实资料无 Token 验收模式

- 用户确认保留 Read/Admin Token 实现，但本机 Demo 暂不启用；新增显式 `serve --local-no-auth`，默认 Bearer 行为不变，CLI 仍只监听 `127.0.0.1`。
- Dashboard Live 连接新增“不启用 Token”选项；开启时不要求凭据，也不发送 `Authorization`，关闭后恢复 Read/Admin Token 输入与既有权限分层。
- 已连接既有 Capital IQ 本地索引完成真实查询验收：792 documents、62,821 chunks、4 sources、Policy v3；“英伟达投资”返回 176 个候选，首位为 NVIDIA 融资与估值主题研报。Dashboard 不重排结果。
- 该真实索引早于 ingestion control-plane，监控五态目前没有历史 item；不以文档表反推或伪造处理状态。扁平原始目录的公司来源归类和历史状态 backfill 需作为后续可审计迁移处理。
- 修复 Dashboard 刷新/交接后回落到 Fixture、导致自定义查询或策略操作出现英文 fixture 错误的问题：成功的 loopback `local-no-auth` 连接只持久化 Base URL 和模式，不保存 Token，并在刷新后自动恢复；Fixture 限制改为明确中文连接指引。
- 修复 Codex MCP 空结果配置：发现 `internalResearchReal` 实际未注册，而旧 `internalResearch` 仍指向样例库；现新增独立 stdio 注册项指向 `backend/data/real-test`。临时只读 Codex 会话实际完成 `internalResearchReal.search_documents("英伟达投资", limit=2)`，返回 `total=176`、Policy v3；不覆盖旧注册项，注册后需新会话重新发现 tools。

## 0.1.0 — 2026-09-24

状态：已完成历史基线。

- 完成 Retrieval Policy Dashboard、API 1.0 契约客户端、fixture、Policy 乐观锁、排序解释和 token 评测。
- 完成本地临时端口的桌面/移动 UI 验收。
- 第一部分仍被视为外部上游；真实 HTTP/MCP/ChatGPT/PDF 验收保持 `not_run`。
