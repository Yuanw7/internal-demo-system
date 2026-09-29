# Internal Research MCP 交付说明

> 0.1.0 Dashboard 历史验收仍保留；0.2.0-dev 已新增本地 Retrieval Hub 和 Codex MCP。最新后端证据见 [`PHASE_G_I_REPORT.md`](PHASE_G_I_REPORT.md)。

日期：2026-09-24

## 1. 可运行 Demo

环境要求：Node.js 22.18+、Python 3.11+。完整后端启动见根目录 `README.md`。

```bash
npm install
npm run demo
```

命令会监听 `0.0.0.0`，由系统分配临时端口，并在终端显示本机与局域网地址。默认 fixture 模式不需要 Token、外部服务或真实文档；测试结束按 `Ctrl+C`。

完整质量门：

```bash
npm test
```

Live 模式连接本仓库 `backend/` Retrieval Hub HTTP API。浏览器跨设备时，Base URL 必须是宿主机可达地址而不是 `127.0.0.1`，Hub 也必须允许 Dashboard 的精确 CORS Origin。

## 2. 整体架构

系统保持单一权威检索边界：

```text
仓库外授权文档 → 本地 Retrieval Hub（版本 / 索引 / ranking / policy / HTTP / MCP）
                                      │
                   ┌──────────────────┴──────────────────┐
                   │                                     │
             HTTP API Client                         MCP Client
                   │                                     │
        Dashboard / Policy Eval                    ChatGPT / Agent
```

本仓库同时拥有 `backend/` Retrieval Hub 和 Dashboard。所有前端 HTTP 调用集中在 `src/api/client.ts`；OpenAPI DTO 保持 `snake_case`；Dashboard 不读取原始目录，也不实现第二套检索或排序。

策略更新流程是 `GET /api/policy` → 编辑 → `PUT /api/policy`，保存时携带最近读取的 `expected_version`。下一次搜索返回的 `policy_version` 进入 UI 和评测记录；409 冲突不会自动覆盖。

## 3. MCP tools 设计

| Tool | 输入与输出重点 | 使用建议 |
|---|---|---|
| `search({query})` | 轻量返回 `id/title/url` | 默认发现候选，控制 token |
| `fetch({id})` | 返回完整 `id/title/text/url/metadata` | 只读取最终需要引用的少量文档 |
| `search_documents({request})` | 对齐 `POST /api/search`，支持 filter 与详细评分 | 高级诊断按需使用，不默认暴露 |

HTTP 和 MCP 必须共享同一策略状态和 ranking 实现。MCP tools 保持只读；管理策略仍由受管理权限保护的 HTTP API 更新。标准流程是先 `search`，再对确需引用的结果 `fetch`，最后基于返回 URL 形成引用。

## 4. Retrieval / ranking

本地 Hub 负责文档解析、分块、短句概念规划、FTS5 与 dense-vector 双路召回和权威排序。目标不是列出所有包含“芯片”的文章，而是让“英伟达具体显卡”同时触发 NVIDIA 实体、GPU 产品型号及 AI infrastructure 语义。版本化概念配置负责可审计别名扩展，本地多语 embedding 负责发现措辞不同但观点相关的 passage。

候选在文档级使用 Reciprocal Rank Fusion；完全相同的正文只占一个结果位。语义候选先通过最低相似度门槛，之后才允许 source weight 和 freshness 改变顺序：

```text
hybrid_relevance = 60 / (60 + lexical_rank) + 40 / (60 + semantic_rank)
freshness = 0.5 ^ (age_days / half_life_days)
score = hybrid_relevance × source_weight × (1 + recency_boost × freshness)
```

Dashboard 只展示服务端返回的顺序、`score` 和 `score_details`。前后排名变化通过相同结果 ID 做位置对照，不重新计算 score，也不改变服务端顺序。query 级 `source_ids/since/until/metadata/limit` 是过滤条件，不属于持久化 Retrieval Policy。未安装模型、未构建索引或索引陈旧时，服务端自动退回概念增强 FTS；MCP tools 与 OpenAPI 字段不变。

fixture 模式同样不在客户端执行公式：它只重放正式交付包里的 v1/v2 SearchResponse，用于稳定验证 UI 和契约行为。

## 5. 本次实际验收

2026-09-24 已额外完成全量真实库 hybrid 验收：62,821 个 current chunk 建成 384 维本地索引（向量 92 MB、模型缓存 240 MB）；“英伟达具体显卡”等四个短句的 hybrid top 10 均通过证据词 smoke check，Nebius capex/GPU 用例由 lexical 8 条扩展到 hybrid 10 条；常驻进程 20 次查询 P50 38.64 ms、P95 70.12 ms。`Nebius` top 50 中完全相同正文重复组为 0。详细方法与限制见 [`HYBRID_RETRIEVAL_ACCEPTANCE_2026-09-24.md`](memos/HYBRID_RETRIEVAL_ACCEPTANCE_2026-09-24.md)。

证据词覆盖不等同人工相关性判断；下一步精度基准必须由分析师标注 query-document relevance，再计算 nDCG/Recall。

浏览器在局域网临时端口的 `dist/` 生产预览上完成：

1. 页面载入 2 个来源、2 个文档与 Policy v1。
2. 查询“芯片”返回两条 v1 服务端顺序结果。
3. `fetch`/文档读取展示纯文本正文、metadata 和 `content_trust`。
4. 保存契约示例策略后得到 Policy v2，并自动再次查询。
5. `demo_filings` 从第 2 升至第 1，权重显示 3.00；`demo_research` 从第 1 降至第 2，权重显示 0.50。
6. UI 显示 `↑ 1` / `↓ 1`，没有客户端重排。
7. 文档 metadata 建议可精确回填下一次查询过滤条件，不修改持久 Policy。
8. 1674×854 桌面视口和 390×844 移动视口均无横向溢出；移动端结果卡完整显示。

`npm test` 同时通过 foundation、生成物漂移、评测漂移、TypeScript strict、26 个前端行为测试、14 个后端测试和生产构建。

## 6. 实际遇到的问题

- 当前可重复验收基于虚构 fixture，不等于真实上游 MCP / ChatGPT 端到端已通过。
- fixture 只支持正式样例查询和 v1/v2 策略，不能代替任意查询或真实 PDF 召回测试。
- loopback 引用 URL 对远程 ChatGPT 不可达；跨设备 Live 模式还受监听地址、CORS 和 Bearer 认证约束。
- `fetch` 返回完整正文，没有分页或 token 上限；真实长 PDF 可能显著占用上下文。
- metadata filter 有请求契约，但交付 fixture 没有过滤后响应，目前只能标记 `not_run`。
- dense embedding 能改善同义措辞召回，但不自动理解表格、错误 OCR 或时点语义；仍需用固定买方问题集检查 top-k 证据，而不能只看命中数量。
- 版本化概念表当前覆盖少量 GPU/AI infra/Capex 词汇；它是高精度 query planning 层，不应无限扩展为不可审计的同义词堆。
- NumPy exact cosine 的成本随 chunk 数线性增长；它是当前本地规模的基线，不是生产大规模终态。
- 浏览器端持有 admin Token 只适合临时受控测试；正式形态需要服务端代理和权限控制。

## 7. 每天新增数百份文档时的优化方向

这些是未来工作，不在当前 Demo 内提前实现：

- 接入层：增量扫描、内容 hash 去重、幂等任务、失败重试和死信记录。
- 处理层：PDF 解析/OCR worker 池、批量处理、背压、资源限额与解析质量指标。
- 索引层：事务批量写入、FTS 索引维护、索引版本、可重建流程和冷热分层。
- 检索层：持续维护带相关性标注的买方短句 query set；分别观测 lexical/vector/fused top-k、重复率、零结果率和 P95。
- 向量层：增量 embedding、模型/概念/chunker 版本共存与后台重建；chunk 达数十万或 exact cosine P95 持续超过 500ms 时迁移 Qdrant/pgvector/HNSW 等 ANN。
- 安全层：文档级 ACL、租户隔离、凭据托管、审计和删除传播。
- MCP/token：passage/range fetch、分页、按需加载高级 tool、只 fetch 最终引用文档。
- 运维层：队列积压、吞吐、失败率、索引新鲜度、备份恢复和容量规划。

Capital IQ PDF 实验与更详细的扩展计划见 `docs/memos/DATA_ENGINEERING_AND_SCALE.md`。

## 8. 完成边界

本仓库责任范围内的 Demo、Dashboard、契约客户端、fixture、策略与 token 评测、生产构建验收、架构说明和规模化建议已经完成。阶段 F 因此关闭。

尚未声明完成的项目只有需要外部环境或上游数据责任的阶段 E：真实 HTTP/MCP 排序一致性、ChatGPT `search → fetch → 引用`、真实 metadata filter，以及 Capital IQ 受控导入实验。它们的必要输入、通过条件和复现命令统一记录在 `docs/memos/EXTERNAL_ACCEPTANCE.md`；没有这些条件时继续保持 `not_run`。
