# Proposal 003 — Information-source ranking V1

状态：用户于 2026-09-28 确认升级到 V1；本地虚构实现已完成。

## 目标

在 V0 唯一主 ranking source 的基础上，持久化信息源目录、alias、文档归因和邮件同步批次，并让虚构 EML/JSON 邮件进入现有 Retrieval Hub。Dashboard、HTTP 和 MCP 继续消费同一个 `sources/Policy/search` 契约。

## 数据模型

Schema migration v3 新增：

- `information_sources`：逻辑信息源、类型、Priority 1–4 和目录版本；
- `information_source_aliases`：canonical/explicit alias 及规范化值；
- `document_source_attributions`：特定 document version 的主来源、角色、解析状态和候选 ID；
- `email_sync_runs`：冻结窗口、三个预期文件夹、每文件夹返回数、错误数和完成状态；
- `email_sync_items`：批次内每封邮件的 imported/skipped/failed 状态及 document 关联。

V1 仍将唯一主信息源同步到现有 `sources`，并以它作为文档 `source_id`。`ingestion_channel` 和 `email_folder` 保存在 metadata，不与分析师/机构权重相乘。

## 完整性规则

- 完成批次时，folder count 必须覆盖全部预期文件夹；零邮件文件夹也必须明确记录为 `0`；
- folder count 总数必须等于批次 item 数；
- 有失败项时状态为 `partial`，无失败项才是 `complete`；
- `imported` item 必须关联实际 document ID；
- 相同 run/window/文件夹集合可幂等重跑，参数不同则冲突。

## 契约影响

无。OpenAPI 1.0.0、`search`、`fetch`、`search_documents` 和响应 DTO 不变。现有 `/api/sources` 会列出同步后的主信息源，现有 Dashboard 可编辑其 `source_weights`。

V1 尚不通过 HTTP/MCP 暴露 alias、归因和批次详情。未来若需要在 ChatGPT 中证明邮件全量覆盖，应新增只读 `list_email_batch` 或正式 HTTP schema，并归档 API 1.0.0 后升级契约。

## 安全边界

- 自动测试只使用虚构账户、发件人、机构、邮件和正文；
- 不连接 Outlook/SharePoint/OneNote，不处理真实附件；
- 不提交 Token、真实账户或运行数据库；
- MCP 仍然只读，邮箱同步写入只允许受控 CLI/Worker 执行。
