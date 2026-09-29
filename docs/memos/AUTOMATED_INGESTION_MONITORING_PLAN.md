# 全自动数据监听与处理状态监控实施基线

日期：2026-09-29
状态：P1/P2 本机闭环完成；P3 已完成无账号适配器与虚构验证，真实授权/OCR 引擎待接入
关联：[`MENTOR_EMAIL_MCP_HANDOFF.md`](MENTOR_EMAIL_MCP_HANDOFF.md)

## 1. 已确认范围

首期只监听两个数据源：

1. Capital IQ 本地资料目录；
2. Outlook 邮箱。

不在首期增加 Gmail、SharePoint、对象存储或多人部署。Outlook 必须通过单独授权的只读 Connector/Graph 接入；Email Skill 负责工作流与分析约束，不能替代常驻邮箱连接器。

本阶段仅以本机运行验收：HTTP、Dashboard 和 MCP 默认监听 `127.0.0.1`，不开放局域网或公网。MCP 保持只读，不增加入库、重试、删除或邮箱写操作。

## 2. 数据生命周期决定

- 源文件或邮件更新时创建新的不可变 `document_version`，不得覆盖旧版本。
- 源文件被删除或邮件离开监听范围时，历史版本继续保留；首期不级联删除数据库、chunk、citation 或审计记录。
- Dashboard 需要展示文件名或邮件主题；不得展示正文预览，绝对路径应转换为受控的显示路径。
- 邮件附件必须进入处理范围。文本层 PDF/支持格式直接解析；扫描 PDF 进入 OCR stage。OCR 引擎、资源上限、失败口径和是否允许云 OCR 在实施前单独确认；未完成 OCR 的附件不能标记为完整处理。
- 首期暂不清理 ingestion batch、attempt、状态事件、历史版本或指标快照。保留策略、归档、压缩和删除属于后续更新待办。

## 3. “已处理”的唯一口径

单条数据只有同时满足以下条件才可写入 `processed`：

1. 读取、解析和分块成功；
2. `documents`、不可变 `document_versions`、pages 和 chunks 已事务提交；
3. FTS5 已包含当前版本；
4. 当前版本的所有必需 chunk 已进入已发布的 dense-vector generation；
5. `document_version_id`、`semantic_generation_id` 和 `searchable_at` 均已记录；
6. 对邮件附件，所有被声明为必需的附件均已解析或 OCR 成功。

因此，只有 FTS 可搜索但向量尚未发布的数据仍为 `pending`，其 `pipeline_stage` 为 `vectorize` 或 `publish`。现有“向量索引陈旧时回退增强 FTS”继续保证查询可用，但不能把尚未完成向量发布的数据展示成已处理。

状态必须由 Retrieval Hub 持久化，不由 Dashboard 根据文案或局部字段猜测：

| 状态 | 精确判定 |
|---|---|
| `pending` | 已发现且达到稳定性条件，尚无有效 worker lease；包括背压和等待向量批次 |
| `processing` | 已由 worker 原子领取，且 `lease_expires_at` 尚未过期 |
| `retrying` | 上次执行失败、仍可自动重试，并已设置 `next_attempt_at` |
| `processed` | 满足上述六项发布条件，`searchable_at` 非空 |
| `failed` | 不可重试，或重试次数耗尽，并进入逻辑死信队列 |

## 4. 实施架构

```text
Capital IQ Folder ─┐
                   ├─ Connector/Discovery ─ Checkpoint ─ Ingestion Queue
Outlook Delta API ─┘                                  │
                                                      ▼
                                      Lease Scheduler + Reaper
                                                      │
                    read/fetch → parse/OCR → persist → FTS → vector → publish
                                                      │
                         documents/versions/chunks + ingestion state/events
                                                      │
                         Monitoring API → Dashboard polling/SSE → alerts
                                                      │
                                      read-only MCP search/fetch
```

### Capital IQ

- 使用文件事件监听获得低延迟通知，并以周期 reconciliation scan 补偿丢失事件。
- 文件在 `size + mtime` 经过可配置稳定窗口后才计算 raw SHA-256 并进入队列。
- 幂等键：`SHA256(connector_id | normalized_relative_path | raw_sha256 | pipeline_version)`。
- 删除只记录 observation/tombstone，不删除历史 document version。

### Outlook

- Webhook/订阅通知只负责唤醒，Microsoft Graph delta checkpoint 才是增量事实来源。
- checkpoint 在本页邮件和附件 discovery 记录提交后推进，不等待后续解析完成。
- 邮件幂等身份优先使用 Outlook message ID/change key，并保留 Internet Message-ID 作为审计 metadata。
- 邮件正文与每个附件形成可追踪的父子关系；附件失败会阻止整封邮件达到完整 `processed`，但正文可保留阶段结果。
- token、账号和 delta secret 不进入 Git；真实账号连接仍需用户单独授权。

### 调度和索引

- 首期使用 SQLite WAL 数据库队列和单机 worker lease；不引入 Redis/Kafka。
- processing priority 与检索 `source_weight` 分开，不能让检索优先级直接控制资源调度。
- 失败按 transient/permanent/resource/auth 分类；瞬态错误指数退避，永久错误直接进入死信。
- 当前 NumPy semantic index 使用 immutable generation：后台构建新 generation，校验完成后原子切换 manifest；只有被新 generation 覆盖的 item 才完成发布。
- PostgreSQL、多主机 worker、分布式队列和 ANN 向量库列入后续更新，不属于本机 MVP。

## 5. Dashboard 与 API 待实施项

Dashboard 在现有检索/Policy 页面上增加本机监控视图：

- KPI：待处理、处理中、已处理、失败、重试中、向量积压、最老待处理年龄；
- 趋势：积压、处理速率、端到端 P50/P95；
- 分布：按 Connector、pipeline stage、错误码；
- 明细：文件名/邮件主题、状态、stage、批次、attempt、耗时、document/version、错误；
- 详情抽屉：状态时间线、附件/OCR 状态和人工重跑；
- 文件名和邮件主题按纯文本渲染，不执行 HTML，不显示正文；
- 首期 HTTP 轮询，稳定后以 SSE 发送失效通知并保留轮询 fallback。

拟新增的管理面包括 summary、items、item detail、batches、retry、rerun、connector scan 和 SSE events。它们尚不属于 OpenAPI 1.0.0；实施前必须提交完整接口提案、归档旧契约并生成新版 OpenAPI。重试/重跑使用 Admin Token、`expected_state_version` 和 Idempotency-Key；监控读取使用 Read Token。

## 6. 分阶段待办

### P1：最小可用监控

- [x] 起草监控 API 契约提案和 DTO，并归档 OpenAPI 1.0.0；
- [x] 新增 connector/checkpoint/batch/item/attempt/event/dead-letter migration；
- [ ] 将现有显式邮件导入接入统一状态记录；Capital IQ 新自动入口已接入；
- [x] 实现 summary、列表、详情和 cursor pagination；
- [x] Dashboard 增加 KPI、状态明细、失败详情和手动刷新；
- [x] 用虚构 Outlook 附件验证父子 item、OCR 阻塞和可插拔 OCR 成功路径；
- [x] OpenAPI 1.0.0 已归档；1.1.0 保留旧检索 DTO 和 MCP schema。

### P2：Capital IQ 自动闭环

- [ ] 文件事件监听；reconciliation polling 已实现；
- [x] stability check、checkpoint 和删除 observation；路径/内容/pipeline 幂等键已实现；
- [x] heartbeat 和可配置队列背压；worker lease、reaper 和自动重试基线已实现；
- [x] dense-vector generation 自动构建并通过现有临时文件原子替换发布；
- [x] 只有向量发布后才写 `processed`；
- [x] 虚构目录已验证无需手工执行 ingest/semantic-build。

### P3：Outlook 与附件/OCR

- [ ] 在用户授权后配置只读 Outlook/Graph Connector；
- [ ] 真实 Graph token 失效回扫和三文件夹覆盖；标准化 delta checkpoint/分页接口已完成；
- [ ] 真实 Graph 附件下载；虚构 adapter 已保存 message/attachment 父子 provenance；
- [ ] 选定并接入本地/云 OCR 引擎；文本附件、OCR 阻断和可插拔 OCR adapter 已完成；
- [x] 来源 alias/priority 复用现有 V1 归因，未知来源进入显式 fallback；
- [x] 用虚构 Graph adapter 自动测试 delta 分页、checkpoint、附件和 OCR；少量获准邮件验收仍待授权。

### P4：实时监控与告警

- [ ] 指标快照和 backlog 历史；
- [ ] SSE 失效通知与断线回退；
- [ ] backlog、失败率、延迟、checkpoint、worker、磁盘和向量积压告警；
- [ ] 结构化日志和 trace ID；
- [ ] 根据真实压测确定 SLA 和阈值，不提前编造数值。

## 7. 后续更新待办（不进入本机 MVP）

### 数据保留与归档

- [ ] 根据实际数据库、向量和 OCR 产物增长量确定 retention policy；
- [ ] 分别定义 batch、attempt、status event、metric snapshot、原始附件和历史向量 generation 的保留期；
- [ ] 设计归档、压缩、legal hold、删除审批和恢复流程；
- [ ] 在策略确认前保留现有全部数据，不运行自动清理。

### 多人和规模化部署

- [ ] 多用户身份、角色权限、文档级 ACL 和审计；
- [ ] SQLite 迁移 PostgreSQL，worker 使用 `SKIP LOCKED`；
- [ ] 多主机 worker、持久队列、对象存储和 HA；
- [ ] Dashboard 服务端代理管理 Admin 权限，浏览器不直接持有管理 Token；
- [ ] 根据 P95、写锁、积压和索引构建时间决定 pgvector/Qdrant/HNSW 等可替换方案；
- [ ] 局域网或远程部署前完成 TLS、SSO 和网络边界评审。

## 8. 当前未定参数

- Capital IQ 目录的扫描间隔、稳定窗口和资源上限；
- Outlook 同步时间窗、目标文件夹和 API 配额处理；
- OCR 引擎、语言、页数/大小限制和是否允许外部服务；
- worker 并发、队列水位、最大重试次数和退避区间；
- backlog、失败率和延迟 SLA；
- 各类运行数据的正式保留期。

这些参数必须通过虚构负载测试和少量授权数据验收确定，不能以未经测量的默认值作为生产承诺。

## 9. 当前实现参数与边界（2026-09-29）

- `watch-folder` 默认 `settle_seconds=5`、`max_queue_depth=1000`，只作为可覆盖的本机演示配置，不是容量或 SLA 承诺；
- schema migration v5 增加 source-object observation、worker heartbeat 和邮件附件父子字段；源端删除只写 `deleted_at`；
- `OutlookDeltaClient` 是认证无关的读取接口，当前只有虚构 adapter；没有伪装成已连接 Microsoft Graph；
- `OCRAdapter` 是可替换接口。未配置时，扫描 PDF 子 item 失败并阻止父邮件进入 `processed`；测试 adapter 只验证状态机，不代表生产 OCR 质量；
- delta checkpoint 在全部消息及附件完成 durable discovery 后推进；解析失败由已持久化 item/dead-letter 表追踪；
- 当前解析结果仍直接写既有 documents/chunks，再构建 immutable semantic generation。跨多 item 的严格原子可见性、durable raw payload spool 和独立 retry worker 是 P3 接真实账号前必须补齐的工程项。
