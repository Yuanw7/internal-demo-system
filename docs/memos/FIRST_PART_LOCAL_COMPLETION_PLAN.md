# 第一部分本地补全与优化方案

状态：已确认，进入实施；本文是实施决策基线，各阶段完成状态以 `ROADMAP.md` 和版本迭代日志为准。

更新日期：2026-09-24

对比基线：

- 本地仓库：`a78acee`，现有能力以 Dashboard、契约客户端、fixture、策略实验和评测为主，API 契约为 `1.0.0`。
- GitHub 参考仓库：`chendi-Shi/chenxi-internal-demo`，审阅提交 `624bb66d25a9d2fea2ce563591df655549ddf8c4`，包含 `backend/`，API 契约为 `1.2.0`。
- 本文中的“Git 版本”均指上述固定提交，不泛指未来的 `main`。

## 1. 决策结论

本地补全采用“保留现有第二部分，选择性吸收 Git 版本第一部分，并先修正数据模型再接入”的方式，不进行整仓覆盖。

目标不是在 Dashboard 中增加第二套检索，而是在本仓库新增唯一的第一部分 Retrieval Hub：它拥有数据接入、版本化存储、索引、权威 ranking、Policy、HTTP API 和 MCP tools；现有 Dashboard 仍只消费服务端结果。

第一阶段目标是一个可在 `127.0.0.1` 临时端口运行、可使用虚构 fixture 完成端到端验证的 Demo。最终产品验收以 Codex/ChatGPT 能通过 MCP 搜索资料、读取原文并完成带引用分析为准。真实 Capital IQ 文件只能位于仓库外部的受控目录，不进入 Git，也不作为自动测试依赖。

### 1.1 MCP 分析职责优化

- MCP Server 只负责搜索、读取和返回结构化证据，不新增 `analyze` 或 `investment_decision` 工具。
- Codex/ChatGPT 负责综合不同文档、识别冲突观点、形成分析判断，并明确标注推断和信息缺口。
- Server instructions 要求模型先 `search`/`search_documents`，再对关键结果 `fetch`，引用绝对 URL、页码和字符范围。
- 本地 Codex 以 stdio 为首要验收路径；ChatGPT 使用 Streamable HTTP `/mcp`，私有环境通过 Secure MCP Tunnel 或受控 HTTPS 接入。
- ChatGPT 账户能力、Developer mode、workspace policy 和安全可达性属于外部条件；没有这些条件时不能把 localhost 自测声明为 ChatGPT 已验收。

## 2. 本次范围

### 2.1 必须补全

1. Python Retrieval Hub 工程和本地 SQLite 数据目录。
2. 文档、文档版本、页面、chunk、来源、Policy、同步状态的数据模型。
3. TXT、MD、JSON、JSONL、EML、文本层 PDF 的受控接入。
4. SQLite FTS5 关键词召回、metadata/date/source 过滤和服务端排序。
5. `search`、`fetch`、`search_documents` 三个只读 MCP tools，以及引导 Codex/ChatGPT 正确检索、读取、引用和分析的 server instructions。
6. HTTP API、读/管理 Token、Policy 乐观锁和统一错误格式。
7. 文件增量同步、幂等、失败重试和可观察状态。
8. API `1.0.0 → 1.2.x` 的正式迁移、客户端生成、Dashboard 联调和回归测试。
9. 可复现的启动、导入、搜索、策略修改和 MCP 验收说明。

### 2.2 本阶段明确不实现

- 不把真实研报或真实正文提交到仓库。
- 不默认调用云端 LLM、云 embedding、外部 OCR 或付费 API。
- 不在 Dashboard 计算、修正或改变服务端结果顺序。
- 不建设生产级多租户、SSO、文档级 ACL 或公网服务。
- 不在第一阶段引入 Kafka、Elasticsearch、Qdrant、Milvus 等常驻基础设施。
- 不做自动投资结论、研报摘要或未经验证的观点抽取。
- 不把 Hugging Face/ModelScope 的公开 Demo 当成真实数据部署方案。

这些能力不是永久排除，而是必须在本地闭环、质量基线和规模指标出现后单独立项。

## 3. 目标架构

```text
仓库外受控文件目录
        │
        ▼
文件发现 → 解析/质量标记 → document_version/page/chunk
        │                         │
        │                         ├─ SQLite 结构化 metadata
        │                         ├─ SQLite FTS5
        │                         └─ 可选语义索引适配器
        ▼
   增量同步状态             Retrieval Service
                                  │
                      ┌───────────┴───────────┐
                      ▼                       ▼
                 HTTP API                  MCP tools
                      │                       │
                      ▼                       ▼
                  Dashboard                ChatGPT
```

不可破坏的约束：HTTP 与 MCP 必须调用同一个 Retrieval Service、同一个 Policy snapshot 和同一套 ranking；Dashboard 不拥有索引或排序实现。

## 4. 具体模块方案

### 4.1 仓库与合并策略

要做：

- 实施前为当前提交建立可回退基线，并从独立集成分支开始。
- 将 Git 版本作为只读 donor，不把它设置为本地上游后直接 merge。
- 第一批只引入 `backend/` 所需源码、测试和依赖声明；根目录文件逐个审阅。
- 所有本地已有文件都通过普通 diff 修改，禁止以远端版本整文件覆盖。

不要这样做：

- 不执行整仓复制或强制合并。
  原因：Git 版本同时改写了 `MISSION.md`、`ROADMAP.md`、架构、契约、Dashboard 和部署文件，会抹掉本地第二部分的交付历史和责任边界。
- 不直接复制 Git 版本的 `AGENTS.md`/使命文档作为事实来源。
  原因：Git 版本内部仍残留“第一部分属于外部上游”和“本仓库已经拥有后端”两套相互冲突的描述。
- 不把生成物、`node_modules`、运行数据库、Token 文件和模型文件带入提交。

与 Git 版本区别：Git 版本已经完成合仓并重写根文档；本方案保留本地历史，以正式范围变更记录逐步迁移。

### 4.2 包结构与代码边界

计划新增：

```text
backend/
  pyproject.toml
  requirements-dev.lock
  src/research_agent/
    hub_models.py          # 唯一 DTO 定义
    database.py            # 连接、事务、migration
    migrations/            # 显式 schema 迁移
    ingestion.py           # 幂等入库与版本管理
    parsing.py             # 文件解析和页面映射
    chunking.py            # 唯一分块实现
    retrieval.py           # 召回与过滤
    ranking.py             # 唯一评分实现
    semantic.py            # 可选语义适配器
    sync_worker.py         # 独立同步 worker
    hub_api.py             # HTTP transport
    hub_mcp.py             # MCP transport
    hub_cli.py             # 本地命令入口
  tests/
```

不要这样做：

- 不直接带入 Git 版本完整 `store.py`。
  原因：该文件除 `search_tokens`、`utcnow` 外还包含另一套 run/job/cache/review/blob 工作流，Retrieval Hub 并未使用这些表，容易形成第二套存储语义。
- 不保留两套 chunking。
  原因：Git 版本 `parsing.py` 有 sentence-aware `segment_document/make_chunks`，但实际 `Hub.ingest` 使用另一套固定字符切块；代码和真实行为不一致。
- 不让通用 `config.py` 同时承担旧 OpenAI extraction 配置和 Hub 文件限制。
  原因：无关字段增加依赖和误配置面；应拆成明确的 `HubSettings`。

与 Git 版本区别：Git 版本优先快速复用已有 `research_agent` 模块；本方案在导入时清除旧工作流残留，并确保每项行为只有一个实现。

### 4.3 数据库与版本化

目标核心表：

| 表 | 关键字段 | 用途 |
|---|---|---|
| `sources` | `id/name/kind/enabled/created_at/updated_at` | 数据源和启停状态 |
| `documents` | `id/source_id/external_id/current_version_id` | 稳定业务身份 |
| `document_versions` | `id/document_id/content_sha/parser_version/published_at/metadata_json/created_at` | 不可变内容版本 |
| `pages` | `version_id/page_number/start/end/text_sha` | 引用页和字符映射 |
| `chunks` | `id/version_id/page/start/end/text/text_sha/token_estimate` | 检索证据单元 |
| `chunk_fts` | FTS5 external-content index | 关键词召回 |
| `policies` | `version/policy_json/updated_at` | 乐观锁策略状态 |
| `sync_files` | `root/source/path/hash/state/attempts/error_code` | 增量同步检查点 |
| `semantic_vectors` | `chunk_id/model_id/content_sha/vector` | 可选语义索引 |
| `schema_migrations` | `version/applied_at/checksum` | 可重复迁移 |

关键约束：

- `documents(source_id, external_id)` 唯一。
- 内容变更创建新的 `document_versions`；`documents.current_version_id` 原子切换。
- 搜索默认只读取 current version，但旧 citation 可以继续定位历史版本。
- chunk、页面和向量都从属于 version，禁止更新正文后复用旧 offset。
- 常用过滤字段，如 `company_id/report_type/published_date/language`，进入结构化列或关系表；长尾属性才放 JSON。
- SQLite 开启 WAL、foreign keys、busy timeout，并通过 migration 管理 `user_version`。

不要这样做：

- 不像 Git 版本一样在同一 `hub_documents` 行覆盖 title/body/pages。
  原因：会丢失修订历史，也无法解释过去回答引用的是哪个版本。
- 不只用 `metadata_json + json_each` 承担所有过滤。
  原因：日增数百份后高频 company/date/report_type 过滤会退化为扫描，且字段质量不可约束。
- 不把模型向量作为没有版本含义的普通缓存。
  原因：必须同时绑定 chunk 内容哈希、模型 ID、模型 digest 和维度，才能安全重建。
- 不依赖隐式 `CREATE TABLE IF NOT EXISTS` 代替 migration。
  原因：Git 版本只有 `PRAGMA user_version=1`，后续 schema 演进和失败回滚能力不足。

与 Git 版本区别：Git 版本面向单机 MVP，使用 `hub_documents + hub_chunks + hub_search` 并覆盖更新；本方案在第一次真实入库前加入不可变版本层和显式 migration。

### 4.4 PDF 解析和分块

要做：

- 第一阶段支持 text-layer PDF，并保存每页的提取状态和 warning。
- 保留页面边界、正文字符 offset、解析器名称和版本。
- 切块顺序采用：页边界 → 标题/段落 → 句子/换行 → 最大长度兜底。
- overlap 以完整句子或段落为单位，不以固定字符倒退。
- 页眉页脚、免责声明、空白页只做标记；没有验证前不自动删除。
- 对无文本页返回明确 `ocr_required`，不能把空文本当作成功导入。
- 导入报告记录文件哈希、页数、正文长度、warning、失败原因和处理时间。

不要这样做：

- 不沿用 Git 版本固定 `1400` 字符、重叠 `160` 字符的生产分块行为。
  原因：会切断句子、表格行和指标上下文，且可能让一个 chunk 跨越不合适的逻辑区域。
- 不在第一阶段静默对所有 PDF 运行 OCR。
  原因：OCR 成本、语言和表格误识别会改变可检索文本，必须作为可审计的独立阶段。
- 不根据文件系统 mtime 推断报告发布日期。
  原因：mtime 是搬运时间，不是业务时间；Git 版本这一点处理正确，应继续保持。
- 不直接删除页眉、页脚或免责声明命中。
  原因：没有版面和标注数据时，规则可能删除真实证据；先标记并评测污染率。

与 Git 版本区别：Git 版本使用 `pypdf.extract_text()`，支持页码但没有版面/表格结构，实际切块为固定字符。本方案保留其安全限制，但统一使用边界感知 chunker，并为 OCR/版面处理留下显式状态。

### 4.5 文档身份、去重和公司实体

要做：

- 稳定 document ID 继续使用 `source_id + external_id`。
- version ID 使用 `document_id + content_sha + parser_version`。
- 精确副本用原文件 SHA-256 和规范化正文 SHA-256 标记。
- 近似副本只形成 `duplicate_group` 建议，不自动删除。
- 公司名称、ticker、曾用名和子公司别名进入版本化实体词典，并记录匹配规则版本。
- 区分 `primary_topic`、`strong_mention`、`weak_mention`、`disclaimer_only`，用于质量评测，不在没有标注时自动当成真值。

不要这样做：

- 不因为正文出现公司名就把报告标成“与该公司强相关”。
  原因：Capital IQ 报告可能只在同业表格、免责声明或背景段落中出现公司名。
- 不用标题或文件名作为唯一去重键。
  原因：标题可能相同，修订版也可能沿用原文件名。
- 不自动合并近似文本。
  原因：看似重复的报告可能包含不同日期、预测值或分析师观点。

与 Git 版本区别：Git 版本提供稳定 external ID 和内容 fingerprint，但没有 document version、duplicate group、实体版本和 mention 强度模型。

### 4.6 Retrieval 与 ranking

兼容阶段先保持现有可解释语义：

```text
freshness = 0.5 ^ (age_days / half_life_days)
score = relevance × source_weight × (1 + recency_boost × freshness)
```

检索执行顺序：

1. 对 source、日期、结构化 metadata 做过滤。
2. 用版本化投研概念配置把短句规划为实体、产品和产业链概念。
3. FTS5 与本地 dense-vector 并行召回候选 chunk。
4. 用文档级 RRF 合并候选，并按 `body_sha` 折叠完全相同正文。
5. 在服务端应用 source weight 和 freshness。
6. 每篇文档返回最佳证据 chunk、分数组成和 citation。
7. 在一个只读事务中读取 Policy 和候选，返回确切 `policy_version`。

不要这样做：

- 不在 Dashboard 重新计算 score 或重新排序。
  原因：会破坏 HTTP/MCP 一致性，也是现有仓库的核心边界。
- 不让 source weight 绕过相关性质量门槛。
  原因：低相关文档不能仅因为来源权重高就排到最前；是否增加服务端 relevance floor 必须通过评测和契约提案决定，不能静默修改现有公式。
- 不把硬编码中英文同义词作为长期唯一词典。
  原因：Git 版本对 capex、margin、revenue 等概念的硬编码适合 fixture，但真实公司别名和财务术语需要版本、审计和热更新。
- 不先截取 BM25 top-k 再应用来源权重。
  原因：会导致高权重来源在候选阶段已被错误丢弃；Git 版本“先为全部匹配评分再截断”的语义应保留到规模指标证明需要候选裁剪为止。
- 不把 score 表示成概率或置信度。

与 Git 版本区别：基础排序公式保持兼容；同义词从代码迁移到版本化配置，常用 metadata 先结构化过滤，并预留需要评测后才能启用的 relevance floor。

### 4.7 语义检索

要做：

- 用户已用“英伟达具体显卡 / GPU / AI infra”明确确认语义召回需求；安装 semantic extra 并构建索引后启用混合检索。
- `SemanticIndex` 使用本地 FastEmbed multilingual MiniLM + normalized NumPy exact cosine；索引元数据保存模型、语料摘要、维度、概念版本和创建时间。
- embedding 依赖缺失、索引缺失或语料已变化时自动回退概念增强 FTS；HTTP/MCP 对外 DTO 不变化。
- 固定短句 query set 比较 lexical 与 hybrid 的 top-k 证据质量、重复占位和延迟；达到阈值后才迁移 ANN。

不要这样做：

- 不把 Ollama/BGE-M3 作为启动 Demo 的强依赖。
  原因：会增加模型下载、内存和跨平台问题，掩盖基础检索是否正确。
- 不把 NumPy exact cosine 当作日增数百份后的最终方案。
  原因：当前约 6 万 chunk 可用矩阵乘法得到简单可审计基线，但增长到数十万 chunk 后延迟与内存会线性上升。
- 不直接引入独立向量数据库。
  原因：当前缺少规模和召回证据；先通过接口隔离，达到阈值再迁移到 pgvector/Qdrant/其他 ANN。
- 不使用未经固定 revision、hash 和许可证检查的模型。

与 Git 版本区别：Git 版本已经实现 E5/Ollama 和 SQLite exact scan；本方案保留为可选实验适配器，但默认不启用，也不把 exact scan 定义为扩展架构。

### 4.8 文件同步与任务执行

要做：

- 保留 Git 版本的 settle time、SHA-256 checkpoint、指数退避、failed/missing 状态和单 worker 锁。
- API 服务与同步 worker 使用独立进程/命令，共享数据库，不在同一 Web 进程启动 daemon thread。
- 每个文件入库保持事务性；多记录 JSON 不允许部分成功。
- `missing` 只表示源文件缺失，不自动删除已入库文档。
- 对重试上限后的失败保留稳定 error code、最近错误时间和人工重试入口。
- 日增量增大后再将任务模型迁移到持久队列和多 worker。

不要这样做：

- 不在 API `serve` 命令内默认启动后台同步线程。
  原因：Git 版本这种方式适合单机 Demo，但 Web 重载、异常退出和多进程部署可能产生重复 worker 或不可预测生命周期。
- 不吞掉所有异常后只保留同一个模糊错误。
  原因：外部响应可以脱敏，但内部至少要区分 encrypted PDF、OCR required、size limit、invalid date、I/O error 等稳定错误码。
- 不因文件暂时不可访问就删除文档。
- 不把归档包“能打开”当成语料完整性的证明。

与 Git 版本区别：同步状态机大体复用，但 worker 从 API 生命周期拆开，错误码更细，并为未来任务队列保留迁移边界。

### 4.9 HTTP API、认证和契约

要做：

- 继续使用 strict Pydantic DTO、`snake_case`、未知字段拒绝和统一错误 envelope。
- 读 Token 与管理 Token 分离；入库、删除、来源修改使用管理权限。
- Policy 更新继续要求最近读取的 `expected_version`，409 不自动覆盖。
- HTTP response 和 MCP result 都从相同 DTO 映射。
- 将 Git 版本 `1.2.0` 视为候选正式交付包，先完成 path/schema/required/error/security diff 后再升级本地事实来源。
- 升级时保留 `1.0.0` 归档和 hash，不修改历史文件来伪装无迁移。

不要这样做：

- 不直接覆盖当前 `docs/contracts/openapi.json`。
  原因：本地规定契约只能通过正式交付和差异检查更新；Git 版本新增三个 endpoint 和六个 schema。
- 不在浏览器生产形态保存 Admin Token。
  原因：任何能打开页面的人都可能修改共享策略；生产形态应使用受控代理或短期会话权限。
- 不在真实数据实例启用 Git 版本的 `public_demo=True`。
  原因：该模式允许匿名读取和匿名修改共享 Policy，只适用于合成数据演示。
- 不把 CORS `*`、任意 Host 或公网 tunnel 作为默认配置。

与 Git 版本区别：Git 版本已把根契约直接提升到 `1.2.0`，并支持匿名 public demo；本方案先归档和审查迁移，匿名模式只允许合成 fixture 实例。

### 4.10 MCP tools

第一阶段保持三个工具：

| Tool | 作用 | 限制 |
|---|---|---|
| `search(query)` | 轻量搜索，返回 `id/title/url` | 使用当前保存 Policy，不接受管理参数 |
| `fetch(id)` | 按搜索结果 ID 返回原文和 metadata | 保持现有契约，不静默截断 |
| `search_documents(request)` | 高级 source/date/metadata 搜索和 citation | 与 HTTP `/api/search` 顺序、版本一致 |

不要这样做：

- 不通过 MCP 暴露入库、删除、Policy 写入或任意文件读取。
  原因：ChatGPT 工具面应保持只读和最小权限。
- 不让 MCP 自己再实现一份 query expansion 或 ranking。
  原因：Git 版本让 MCP 调用 `Hub.search` 的设计正确，应继续保持。
- 不为减少 token 偷偷改变现有 `fetch` 含义。
  原因：客户端会把它理解为完整原文。若实测超预算，应新增 `fetch_passage`/range tool，并通过契约版本升级，而不是改旧工具。
- 不返回本地绝对文件路径、Token、异常堆栈或内部同步根目录。

与 Git 版本区别：三个工具及只读注解基本直接复用；新增 passage/range 能力只作为后续正式契约提案。

### 4.11 Dashboard 接入

要做：

- 保留现有 TypeScript strict、单一 API client、fixture 模式和买方分析师界面。
- API 1.2.x 确认后，再增加 retrieval index status、sync summary 和 sync file list 客户端方法。
- 页面只展示服务端返回的检索模式、warning、同步状态和 Policy 版本。
- fixture 同步扩展，但继续明确标记为虚构数据。

不要这样做：

- 不复制 Git 版本整个 `src/` 覆盖现有 Dashboard。
  原因：远端只是增加状态字段和 public demo 支持，本地已有 UI、评测和历史应保留。
- 不在前端根据 semantic/keyword 模式修正 score。
- 不让同步异常或语义索引未启用阻断关键词检索。
- 不在 UI 声称“语义索引已提高准确率”，除非固定评测集有证据。

与 Git 版本区别：只移植 `/api/retrieval`、`/api/sync`、`/api/sync/files` 所需的客户端和视图变化，不采用整页替换，也不默认进入匿名 public demo。

### 4.12 部署

第一阶段：

- Hub 只监听 `127.0.0.1`，端口可配置或由系统临时分配。
- Dashboard 可使用已有临时局域网端口做受信网络演示。
- 提供本机进程启动说明和可选 Dockerfile，但 Docker 不作为开发必需条件。
- 数据目录、凭据、模型和原始文件全部挂载在仓库外。

不要这样做：

- 不优先移植 Hugging Face/ModelScope 部署入口。
  原因：Git 版本的容器使用 `/tmp` 数据目录、合成 fixture 和匿名 public demo，适合展示，不适合私有研报持久化。
- 不自动创建公网 tunnel 或把本地 Token 写入托管平台。
- 不把 loopback citation URL 当作 ChatGPT 已可访问的证据。
- 不让 SQLite 数据库位于多个容器共享写入的网络文件系统。

与 Git 版本区别：Git 版本同时提供 Docker/Hugging Face/ModelScope；本方案先完成本机受控闭环，公开合成 Demo 属于后续独立工作。

## 5. Git 版本文件处理清单

| Git 版本部分 | 本地处理 | 原因/差异 |
|---|---|---|
| `backend/pyproject.toml`、lock files | 选择性引入并固定 Python 3.11 | 保留可重复安装，删除未使用的旧 extraction 依赖 |
| `hub_models.py` | 高比例复用 | strict DTO、字段约束和 snake_case 方向正确 |
| `hub_api.py` | 复用 transport 与错误处理，调整 public demo 默认值 | 真实实例禁止匿名策略写入 |
| `hub_mcp.py` | 基本复用 | 三工具、只读注解和共享 Hub 设计正确 |
| `hub_runtime.py` | 复用并补权限/文件模式测试 | 本地凭据不覆盖已有文件的行为正确 |
| `hub.py` | 拆分重写 | 当前混合 schema、ingest、retrieval、ranking，且更新覆盖历史 |
| `parsing.py` | 复用安全限制，统一 chunker | 当前存在未使用分块函数和固定字符实际实现 |
| `hub_query.py` | 复用 query planner 骨架，同义词外置 | 硬编码金融词典不适合长期维护 |
| `hub_semantic.py`/`hub_e5.py` | 作为可选实验适配器后置 | exact vector scan 不能作为规模化终态 |
| `hub_sync.py` | 复用状态机，拆成独立 worker | 不绑定 Web 进程 daemon thread |
| `store.py` | 不整体引入 | 含与 Hub 无关的另一套工作流和表 |
| `config.py` | 不整体引入 | 混有旧 OpenAI extraction 配置 |
| backend tests | 迁移并增加版本、migration、chunk boundary 测试 | 现有核心测试是有价值基线 |
| 根 `MISSION/ROADMAP/ARCHITECTURE` | 不覆盖，逐项更新 | 保留本地第二部分历史和决策依据 |
| 根 OpenAPI/examples | 正式迁移，不直接覆盖 | 需要保留 1.0.0 归档和 schema diff |
| 根 `src/` | 只移植新增状态接口和视图 | 保留本地 Dashboard 基底 |
| Docker/HF/ModelScope | 第一阶段不引入 | 与本机私有数据闭环无关 |

## 6. 实施阶段与退出条件

### 阶段 0：保护基底与确定契约候选

动作：

- 建立基线 tag、集成分支和 Git 版本来源记录。
- 生成 `1.0.0 → 1.2.0` path/schema/required/security/error diff。
- 确认哪些 Git API 进入本地正式 `1.2.x`。

退出条件：本地原始基底可回退；没有代码文件被无审查覆盖；契约迁移清单得到确认。

### 阶段 1：后端骨架、migration 与版本化数据库

动作：

- 创建 Python package、依赖锁和测试入口。
- 实现 migration、连接管理和核心表。
- 实现 source、document、document_version、page、chunk、policy repository。

退出条件：空库可升级；重复升级幂等；内容变更新增 version；失败事务不产生半成品。

### 阶段 2：解析、分块与增量同步

动作：

- 实现支持格式、安全限制、页码映射和 warning。
- 建立边界感知唯一 chunker。
- 建立独立 sync worker、checkpoint、重试和 missing 状态。

退出条件：重复导入不重复建版本；修订文件保留历史；空文本 PDF 明确报告 OCR required；citation offset 可回切原文。

### 阶段 3：关键词检索、过滤与 ranking

动作：

- 建立 current-version FTS5 index。
- 实现 source/date/metadata 过滤、BM25、source weight、freshness。
- 固化相同 Policy snapshot 和可解释 score details。

退出条件：权重变化影响下一次结果；禁用来源不返回；过滤有效；HTTP 结果顺序完全来自服务端。

### 阶段 4：HTTP 与 MCP

动作：

- 实现认证、错误、状态、搜索、文档、Policy endpoint。
- 实现三个只读 MCP tools。
- 增加 HTTP/MCP parity 测试。

退出条件：同 query 的结果 ID/顺序一致；高级 MCP 与 HTTP 的 `policy_version` 一致；MCP 无写工具。

### 阶段 5：契约升级和 Dashboard 接入

动作：

- 正式归档 1.0.0，提升审查后的 1.2.x。
- 重新生成 TypeScript contracts。
- 为 retrieval/sync 状态增加 API client 和 UI，不改变 ranking。

退出条件：`npm test` 通过；未知字段仍拒绝；409 行为不变；fixture 和 live 两种模式可运行。

### 阶段 6：语义实验和规模门槛

动作：

- 在固定虚构查询集上比较 FTS 与 hybrid。
- 记录召回、Top-k、延迟、索引时间、磁盘和 fallback。
- 只有出现净提升才保留默认启用候选。

退出条件：结果有可重复报告；没有模型也能完整运行；达到向量扫描阈值时形成 ANN 迁移提案，而不是在本阶段仓促引入。

### 阶段 7：端到端交付

动作：

- 提供本地启动、fixture 导入、Dashboard 打开和 MCP 配置说明。
- 完成真实 SDK 条件下的 MCP transport 测试。
- 更新架构、路线图、README 和限制记录。

退出条件：新机器按 README 可复现；HTTP/MCP/Dashboard 闭环通过；没有真实正文、Token、运行数据库或公网地址进入 Git。

## 7. 验收矩阵

| 验收项 | 必须证据 |
|---|---|
| 基底保留 | 基线 tag、集成 diff、无整仓覆盖 |
| 数据版本 | 同 external ID 内容变化产生新 version，旧 citation 可读 |
| 幂等 | 同文件重复导入返回 unchanged，不增加 version/chunk |
| PDF | 页码/offset 回切一致；无文本页明确 warning |
| 排序 | 相同 query 修改 source weight 后下一次结果变化 |
| 新鲜度 | 固定 now 的 freshness 结果可重复 |
| metadata | company/date/report_type 使用索引化过滤并有测试 |
| Policy | `expected_version` 冲突返回 409，不自动覆盖 |
| HTTP/MCP | 候选 ID、顺序和高级工具 Policy 版本一致 |
| 安全 | MCP 只读；正文纯文本；不泄露绝对路径/凭据 |
| 降级 | embedding 不可用时关键词服务继续工作 |
| 前端 | 不包含 score 计算或 re-rank；`npm test` 通过 |
| 后端 | 完整依赖环境下 `pytest` 全通过，无条件 skip MCP 核心测试 |
| 可运行 | localhost 临时端口可启动并打开 Dashboard |

## 8. 规模升级触发条件

SQLite 继续作为默认方案，直到实际指标触发升级，而不是按文档数量主观决定。

建议触发器：

- 搜索 P95 持续超过 500 ms：检查 metadata 扫描、FTS 候选数量和 exact vector scan。
- 同步积压超过两个轮询周期：拆分发现、解析、索引为持久任务队列。
- 单日失败超过 1% 或人工重试量不可控：建立 dead-letter、错误分类和批次重放。
- exact vector scan 超过可接受延迟：迁移到 pgvector/Qdrant/其他 ANN，接口不变。
- SQLite 写锁等待持续出现：将 ingest worker 串行化或迁移 PostgreSQL。
- 文档级权限成为要求：权限过滤必须进入召回前阶段，再评估存储与索引分区。
- 需要比较多份研报的不同观点：新增 claim/metric/company/period/provenance 层，但必须保留原文 citation，且不能让自动抽取结果覆盖原文事实。

## 9. 已确认决策与剩余外部前置条件

已确认：

1. 当前仓库正式扩展为第一、第二部分同仓库，后端是唯一权威边界。
2. 不追求与 Git 版本逐文件一致，以本地目标和长期数据质量优先。
3. 关键词检索闭环已经完成；现按用户确认的投研短句场景启用可选本地 hybrid，缺少/陈旧索引时继续完整回退关键词模式。
4. 在正式数据导入前实现 document version 和 migration。
5. 最终验收包含 Codex/ChatGPT 通过 MCP 搜索资料并完成带引用分析。

2026-09-24 更新：用户已授权继续处理所附 Capital IQ 目录；802 份均已进入本地处理，结果见 `REAL_DATA_ACCEPTANCE_2026-09-24.md`。原始文件继续位于仓库外；新增资料目录或不同时间范围仍需重新确认。

仍需外部条件：ChatGPT Developer mode/workspace policy、安全可达的 `/mcp` 或 Secure MCP Tunnel，以及相应认证。

实施按第 6 节和 `ROADMAP.md` 阶段 G–K 顺序执行。任何涉及真实文档、外部账号、公网、付费服务或正式 MCP 客户端配置的步骤仍需单独确认。
