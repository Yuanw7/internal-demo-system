# Capital IQ 真实资料全量本地验收

日期：2026-09-24

状态：所附目录已完整扫描和受控导入；ChatGPT 外部连接未执行。

## 1. 安全与范围

- 用户在本轮明确授权处理所附资料目录。
- 原始数据位于仓库外；没有原始 PDF、抽取正文、Token 或运行数据库进入 Git。
- 输入清单包含 9 个 ZIP、1 个 RAR，共 802 份 PDF，约 942 MB。
- 9 个 ZIP 的 796 份 PDF 和 RAR 中 6 份 earnings transcript 均进入处理队列。
- 隔离数据库位于 `backend/data/real-test/`，受 `.gitignore` 保护；测试后数据库约 288 MB。

## 2. 导入结果

| 来源 | 尝试 | 成功 | 失败 |
|---|---:|---:|---:|
| Capital IQ · Kioxia corpus | 300 | 295 | 5 |
| Capital IQ · NBIS corpus | 244 | 242 | 2 |
| Capital IQ · SNOW corpus | 252 | 249 | 3 |
| Capital IQ · Earnings transcripts | 6 | 6 | 0 |
| 合计 | 802 | 792 | 10 |

当前版本统计：792 个 document、935 个 immutable version、15,776 个 current page、62,821 个 current chunk；788 份当前文档识别到发布日期，4 份日期仍为空。解析器升级产生的旧版本继续保留，因此历史 page/chunk 数高于 current 数。

幂等复测：6 份 transcripts 再次导入返回 `unchanged=6`，没有新增 version 或 current chunk。

### 集合重叠盘点

- 796 个 ZIP 条目的原始字节 SHA-256 均不同，说明水印、PDF metadata 或二进制结构存在差异。
- 规范化标题只有 638 个唯一值，其中 154 组标题跨归档重复，共 158 个额外条目。
- `local-text-v2` 抽取正文 SHA 复核得到完全相同的 154 个重复组和 158 个额外条目。
- 加上 6 份 transcript，当前 792 份成功文档实际对应 634 个唯一正文；再加 10 份失败条目，所附目录约代表 644 份逻辑报告。

系统没有按文件名自动删除或合并。正文 SHA 仅作为确定性重复标记；是否在 ranking 阶段折叠需要单独确认，提案见 `docs/contracts/proposals/001-real-corpus-retrieval.md`。

## 3. 接入层修复

真实数据暴露并推动以下修复：

1. 系统 `unzip` 在部分多语言文件名上报 `Illegal byte sequence`。现由 Python ZIP reader 在内存中逐条读取，不依赖文件系统解码或落盘。
2. 报告日期主要为 `21_Aug_2026`，旧解析器只识别 `2026-08-21`。现同时支持两种格式，并保留多日期歧义返回空值的规则。
3. 多数条目以 `.pdf.pdf` 结尾。标题会移除重复 PDF 后缀，但 external ID 仍绑定归档条目及 header offset。
4. 部分 PDF 使用 CFF Type1 字体。新增 `fontTools`，解析器版本升级为 `local-text-v2`。
5. 大 ZIP 超过单批 100 文档/200 万字符限制。CLI 现在自动按两项上限分批，服务端原有批次约束不放宽。
6. 错误不再统一折叠成模糊 `parse_failed_check_format_or_ocr`，本地导入报告保留稳定错误码。

RAR 仍不作为原生容器支持，本轮在受控临时目录解包后导入。没有为方便测试引入任意 shell 解压或自动 OCR。

## 4. Retrieval、过滤与 Policy

代表查询结果：

| 查询 | 命中文档 | 匹配 chunk | P50 | P95 |
|---|---:|---:|---:|---:|
| `Kioxia` | 309 | 1,721 | 13.45 ms | 279.00 ms |
| `Nebius` | 398 | 1,731 | 15.16 ms | 272.53 ms |
| `Snowflake` | 406 | 1,966 | 16.26 ms | 90.63 ms |
| `AI demand` | 423 | 2,367 | 19.09 ms | 79.41 ms |
| `data center` | 219 | 1,130 | 10.98 ms | 24.43 ms |
| `capital expenditure` | 187 | 231 | 5.07 ms | 15.39 ms |

- `archive_name=Capital IQ_Kioxia1.zip` 的 exact metadata filter 只返回 Kioxia corpus。
- `since=2026-08-01T00:00:00Z` 能排除无日期或更早资料。
- `Nebius` 默认前五来源顺序以 SNOW corpus 开头；将 transcripts 权重提高到 5、其他来源降到 0.5 后，transcripts 升至第 1 位。恢复默认权重后顺序恢复，Policy 最终为 v3。
- citation 抽样可由结果的 page/start/end 回切 `fetch` 正文。
- 六个代表查询的 P95 均低于 500 ms 门槛；当前瓶颈主要是 PDF 导入与全文 token，而不是 SQLite FTS 查询。
- 重复正文会占用结果位：Top 50 中，`Nebius` 有 23 个重复 slot，`Snowflake` 有 21 个，`Kioxia` 有 2 个。这是当前最明确的 ranking 质量问题。

## 5. MCP 与 Codex 实测

真实隔离库的 stdio MCP 完成：

- initialize 和 list_tools；
- 确认 `search`、`fetch`、`search_documents` 均为只读；
- 全量库 `search_documents` 在 source/date filter 下返回正确来源和 Policy v3；
- 对首条结果执行 `fetch`，ID 一致，返回 54,128 字符、9 页，citation 指向第 3 页。

临时只读 Codex 会话被要求只使用真实库 MCP。模型先调用 `search_documents`，随后读取 earnings call、公司研报和供应链研报，最终把文档事实、模型推断、观点张力与信息缺口分开，并附 URL/页码。临时 `internalResearchReal` 配置在验收后已移除，原 `internalResearch` 未改变。

## 6. 发现的问题与下一步

1. **完整 fetch token 成本过高**：单次真实分析消耗约 51,035 token，模型读取了多份全文。应正式提案新增 `fetch_passage` 或 range tool，而不是改变既有 `fetch` 语义。
2. **主题相关度不等于正文出现公司名**：`Kioxia`、`Snowflake` 等在宽主题报告中大量出现，当前 BM25 可能把横向策略报告排到公司专题前。应增加可评测的 `primary_topic/strong_mention/weak_mention/disclaimer_only` 标签和相关性质量门槛，不能仅靠来源权重修正。
3. **复杂 PDF 仍有缺口**：9 份为 `pdf_parse_failed`，1 份超过 20 MB 单文件安全上限；另有复杂 XForm 解码警告。需要保存解析 warning、页级字符密度和失败样本，再决定版面解析或 OCR 路线，不能为追求成功率直接放宽限制。
4. **高级工具易用性**：Codex 第一次 `search_documents` 调用参数失败，随后自我修正。应在不破坏契约的前提下强化 tool description/example；若要扁平化参数，先走 MCP schema 变更提案。
5. **引用 URL 的运行条件**：stdio MCP 返回的绝对 URL 指向本机 HTTP Hub。未启动 `serve` 时 URL 不可点击；ChatGPT 还需要安全可达的 HTTPS/tunnel，不能把 loopback 引用算作外部验收。
6. **集合不是数据来源**：Kioxia/NBIS/SNOW 是“报告包含该公司名”的集合，同一逻辑报告可同时属于多个集合。长期模型应把券商/发布者或供应渠道作为 `source`，把公司集合存为多对多 membership；否则来源权重的业务语义会混乱。
7. **RAR**：RAR 目前需显式解包。若将归档作为常态输入，应实现独立、受限、可审计的 container adapter，而不是调用任意系统命令。

本轮结论：现有架构可以在单机 SQLite 上处理本批 802 份研报并支持买方分析型 MCP 工作流，查询延迟仍有余量。下一阶段的最高优先级应是精确重复折叠、source/membership 重构、passage/range fetch、报告主题强度标注和 PDF 质量可观测性，而不是立即引入向量数据库或自动摘要。
